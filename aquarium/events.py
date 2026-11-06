"""
Works out what has just happened in the system and sends it to webhook endpoints.

Conditions (a parameter out of range, a low reservoir...) only notify when they first become
true. They're remembered in EventState, so restarting the app doesn't repeat them, and a
condition has to stay clear for CLEAR_AFTER before it can notify again (so a probe hovering
around a limit doesn't spam you).

Automated schedule events fire once. A missed one is dropped after MAX_SCHEDULE_LATENESS and is
never retried: a late or repeated trigger could double-feed a tank.
"""
import hashlib
import hmac
import json
import urllib.error
import urllib.request
import uuid
from datetime import datetime, time, timedelta

from django.utils import timezone

from .alerts import compute_alert_state
from .models import (
    AppSettings, Animal, EventState, FillTimer, MaintenanceRoutine, ParameterType, WebhookDelivery,
    WebhookEndpoint,
)

EVENT_TYPES = [
    ('parameter.critical', 'Parameter past a critical limit'),
    ('parameter.out_of_range', 'Parameter out of range'),
    ('parameter.stale', 'Probe stopped reporting'),
    ('reservoir.low', 'Reservoir running low'),
    ('routine.due', 'Manual routine due'),
    ('routine.scheduled', 'Automated schedule event (feeder, lights...)'),
    ('equipment.service_due', 'Equipment service due'),
    ('animal.attention', 'Animal sick or in quarantine'),
    ('quarantine.complete', 'Quarantine period finished'),
    ('timer.finished', 'Fill timer finished'),
]
ONE_SHOT_TYPES = ('routine.scheduled', 'timer.finished', 'test')

CLEAR_AFTER = timedelta(minutes=30)
MAX_SCHEDULE_LATENESS = timedelta(minutes=5)
RETRY_MINUTES = [1, 5, 30, 120]
REQUEST_TIMEOUT = 10
DELIVERY_RETENTION = timedelta(days=30)
NTFY_PRIORITY = {'critical': '5', 'warning': '4', 'info': '3'}


def _condition(key, event_type, severity, title, message, **data):
    return {'key': key, 'type': event_type, 'severity': severity, 'title': title, 'message': message, 'data': data}


def collect_conditions(now=None):
    """Everything that is currently true and worth telling someone about."""
    now = now or timezone.now()
    state = compute_alert_state()
    found = []

    for item in state['out_of_range_params']:
        param, log = item['param'], item['log']
        severity = 'critical' if item['critical'] else 'warning'
        event_type = 'parameter.critical' if item['critical'] else 'parameter.out_of_range'
        label = 'critically ' + log.status if item['critical'] else log.status
        found.append(_condition(
            f"param:{param.pk}:{log.status}:{severity}", event_type, severity,
            f"{param.name} is {label}: {log.formatted_value} {param.unit}",
            f"Target range is {param.formatted_min_ideal} to {param.formatted_max_ideal} {param.unit}.",
            parameter=param.code, value=float(log.value), unit=param.unit, status=log.status,
            min_ideal=float(param.min_ideal), max_ideal=float(param.max_ideal),
            measured_at=log.measured_at.isoformat(),
        ))

    for param in ParameterType.objects.exclude(stale_after_hours__isnull=True):
        latest = param.latest_log()
        if latest and now - latest.measured_at > timedelta(hours=param.stale_after_hours):
            found.append(_condition(
                f"stale:{param.pk}:{latest.pk}", 'parameter.stale', 'warning',
                f"No new {param.name} readings",
                f"Nothing logged for over {param.stale_after_hours} hours. Check the probe.",
                parameter=param.code, last_measured_at=latest.measured_at.isoformat(),
            ))

    for res in state['low_reservoirs']:
        found.append(_condition(
            f"reservoir:{res.pk}", 'reservoir.low', 'warning', f"{res.name} is running low",
            f"{res.percent_remaining}% left" + (f", about {res.days_remaining} days" if res.days_remaining is not None else "") + ".",
            reservoir=res.name, percent_remaining=res.percent_remaining, days_remaining=res.days_remaining,
        ))

    for routine in state['due_routines']:
        found.append(_condition(
            f"routine:{routine.pk}:{routine.next_due_date}", 'routine.due', 'info', f"{routine.title} is due",
            f"Due {routine.next_due_date}.", routine=routine.title, routine_id=routine.pk, due=str(routine.next_due_date),
        ))

    for eq in state['due_equipment']:
        found.append(_condition(
            f"equipment:{eq.pk}:{eq.last_serviced_date}", 'equipment.service_due', 'info', f"{eq.name} needs service",
            "Its service interval has passed.", equipment=eq.name, category=eq.category,
        ))

    for animal in state['sick_animals']:
        found.append(_condition(
            f"animal:{animal.pk}:{animal.status}", 'animal.attention', 'warning', f"{animal.name}: {animal.get_status_display()}",
            "This animal is flagged for attention.", animal=animal.name, status=animal.status,
        ))

    for animal in Animal.objects.filter(status='quarantine').exclude(quarantine_started__isnull=True):
        if animal.quarantine_complete:
            found.append(_condition(
                f"quarantine:{animal.pk}:{animal.quarantine_started}", 'quarantine.complete', 'info',
                f"{animal.name} has finished quarantine",
                f"Planned {animal.quarantine_days} days are up. Check it over before moving it.", animal=animal.name,
            ))
    return found


def emit(event_type, severity, title, message, data=None, max_attempts=None, *,
         routine_id=None, reservoir_id=None, endpoints=None):
    """
    Queues one event for every endpoint that wants it, or just for `endpoints` when they're
    chosen explicitly. Returns the number queued.
    """
    if max_attempts is None:
        max_attempts = 1 if event_type in ('routine.scheduled',) else 5
    if endpoints is None:
        endpoints = [e for e in WebhookEndpoint.objects.filter(is_active=True)
                     if e.wants(event_type, routine_id=routine_id, reservoir_id=reservoir_id)]
    now = timezone.now()
    for endpoint in endpoints:
        WebhookDelivery.objects.create(
            endpoint=endpoint, event_id=str(uuid.uuid4()), event_type=event_type, severity=severity,
            title=title[:200], message=(message or '')[:500], data=data or {},
            max_attempts=max_attempts, next_attempt_at=now,
        )
    return len(endpoints)


def sync_conditions(now=None):
    """Fires conditions that have just become true and forgets those that stayed clear."""
    now = now or timezone.now()
    settings_obj = AppSettings.load()
    current = {c['key']: c for c in collect_conditions(now)}
    known = {s.key: s for s in EventState.objects.exclude(event_type__in=ONE_SHOT_TYPES)}
    fired = 0

    for key, cond in current.items():
        state = known.get(key)
        if state is None:
            EventState.objects.create(key=key[:120], event_type=cond['type'], activated_at=now)
            # The first ever run only records what's already wrong, rather than sending a burst of old news.
            if settings_obj.events_baselined:
                fired += emit(cond['type'], cond['severity'], cond['title'], cond['message'], cond['data'],
                              routine_id=cond['data'].get('routine_id'))
        elif state.cleared_at is not None:
            EventState.objects.filter(pk=state.pk).update(cleared_at=None)

    for key, state in known.items():
        if key in current:
            continue
        if state.cleared_at is None:
            EventState.objects.filter(pk=state.pk).update(cleared_at=now)
        elif now - state.cleared_at >= CLEAR_AFTER:
            state.delete()

    if not settings_obj.events_baselined:
        AppSettings.objects.filter(pk=settings_obj.pk).update(events_baselined=True)
    return fired


def fire_scheduled(now=None):
    """Fires automated routine events whose time has just passed."""
    now = now or timezone.now()
    settings_obj = AppSettings.load()
    since = settings_obj.last_schedule_check or now - timedelta(minutes=1)
    since = max(since, now - MAX_SCHEDULE_LATENESS)
    tz = timezone.get_current_timezone()
    days = {timezone.localtime(since, tz).date(), timezone.localtime(now, tz).date()}
    fired = 0

    routines = MaintenanceRoutine.objects.filter(routine_type='automated', is_active=True).select_related('tank')
    for routine in routines:
        for day in days:
            if not routine._occurs_on(day):
                continue
            for event in routine.sorted_events:
                try:
                    hour, minute = (int(x) for x in str(event['time']).split(':'))
                    at = timezone.make_aware(datetime.combine(day, time(hour, minute)), tz)
                except (ValueError, TypeError):
                    continue
                if not since < at <= now:
                    continue
                key = f"sched:{routine.pk}:{day}:{hour:02d}{minute:02d}"
                _, created = EventState.objects.get_or_create(key=key, defaults={'event_type': 'routine.scheduled', 'activated_at': now})
                if not created:
                    continue
                action = event.get('action') or 'Scheduled event'
                fired += emit(
                    'routine.scheduled', 'info', f"{routine.title}: {action}",
                    f"Scheduled for {hour:02d}:{minute:02d}.",
                    {'routine': routine.title, 'routine_id': routine.pk, 'category': routine.category,
                     'action': action, 'scheduled_for': at.isoformat(),
                     'tank': routine.tank.name if routine.tank else None,
                     'equipment': list(routine.equipment.values_list('name', flat=True))},
                    routine_id=routine.pk,
                )

    AppSettings.objects.filter(pk=settings_obj.pk).update(last_schedule_check=now)
    EventState.objects.filter(event_type='routine.scheduled', activated_at__lt=now - timedelta(days=2)).delete()
    return fired


def finish_timers(now=None):
    """Marks finished fill timers and sends their alert."""
    now = now or timezone.now()
    fired = 0
    for timer in FillTimer.objects.filter(status='running', ends_at__lte=now).select_related('reservoir'):
        chosen = list(timer.endpoints.filter(is_active=True))
        fired += emit(
            'timer.finished', 'warning', f"Timer finished: {timer.name}",
            "Check your fill now.",
            {'timer': timer.name, 'timer_id': timer.pk, 'reservoir': timer.reservoir.name if timer.reservoir else None,
             'reservoir_id': timer.reservoir_id},
            reservoir_id=timer.reservoir_id,
            endpoints=chosen or None,
        )
        FillTimer.objects.filter(pk=timer.pk).update(status='finished', notified=True)
    return fired


def build_request(delivery):
    """Returns a urllib Request for a delivery in its endpoint's format."""
    endpoint = delivery.endpoint
    if endpoint.format == 'ntfy':
        body = (delivery.message or delivery.title).encode('utf-8')
        headers = {
            'Title': delivery.title.encode('ascii', 'ignore').decode('ascii').strip() or 'Nudibranch',
            'Priority': NTFY_PRIORITY.get(delivery.severity, '3'),
            'Tags': 'rotating_light' if delivery.severity == 'critical' else 'tropical_fish',
        }
    else:
        body = json.dumps({
            'id': delivery.event_id,
            'type': delivery.event_type,
            'severity': delivery.severity,
            'title': delivery.title,
            'message': delivery.message,
            'occurred_at': delivery.created_at.isoformat(),
            'data': delivery.data,
        }).encode('utf-8')
        headers = {
            'Content-Type': 'application/json',
            'X-Nudibranch-Event': delivery.event_type,
            'X-Nudibranch-Delivery': delivery.event_id,
        }
        if endpoint.secret:
            digest = hmac.new(endpoint.secret.encode('utf-8'), body, hashlib.sha256).hexdigest()
            headers['X-Nudibranch-Signature'] = f"sha256={digest}"
    headers['User-Agent'] = 'Nudibranch-Reef-Tracker'
    return urllib.request.Request(endpoint.url, data=body, headers=headers, method='POST')


def send_delivery(delivery, now=None):
    """Attempts one send and records the outcome. Returns True on success."""
    now = now or timezone.now()
    delivery.attempts += 1
    code = None
    error = ''
    try:
        with urllib.request.urlopen(build_request(delivery), timeout=REQUEST_TIMEOUT) as response:
            code = response.status
    except urllib.error.HTTPError as exc:
        code = exc.code
        error = f"HTTP {exc.code}"
    except (urllib.error.URLError, OSError, ValueError) as exc:
        error = str(getattr(exc, 'reason', exc))[:255] or exc.__class__.__name__

    delivery.response_code = code
    delivery.error = error
    success = code is not None and 200 <= code < 300
    if success:
        delivery.status = 'sent'
        delivery.sent_at = now
    elif delivery.attempts >= delivery.max_attempts:
        delivery.status = 'failed'
    else:
        wait = RETRY_MINUTES[min(delivery.attempts - 1, len(RETRY_MINUTES) - 1)]
        delivery.next_attempt_at = now + timedelta(minutes=wait)
    delivery.save()
    return success


def deliver_due(now=None, limit=50):
    now = now or timezone.now()
    due = (WebhookDelivery.objects.select_related('endpoint')
           .filter(status='pending', next_attempt_at__lte=now).order_by('created_at')[:limit])
    sent = 0
    for delivery in due:
        sent += 1 if send_delivery(delivery, now) else 0
    return sent


def prune(now=None):
    now = now or timezone.now()
    WebhookDelivery.objects.filter(created_at__lt=now - DELIVERY_RETENTION).delete()
