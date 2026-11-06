"""Views for the tools section: planner, power, quarantine, timeline, time-lapse, webhooks, backups, timers."""
import json
import tempfile
import uuid
from datetime import datetime, timedelta, timezone as dt_timezone
from pathlib import Path
from urllib.parse import urlencode

from django.conf import settings
from django.contrib import messages
from django.db.models import Count
from django.http import FileResponse, Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.dateparse import parse_date
from django.views.decorators.http import require_POST

from . import backups, events, fill, planner, power, retire, timelapse, wishlist
from .active import COOKIE_MAX_AGE, COOKIE_NAME, get_active_tank
from .themes import RETIRED_ICONS, STOCK_ICONS, THEMES
from .forms_tools import (
    AnimalPhotoForm, AppSettingsForm, CostEntryForm, PlannedEquipmentForm, PlannedLivestockForm, PlannedSystemForm,
    QuarantineEntryForm, QuarantinePlanForm, ROSystemForm, SystemThemeForm, WebhookEndpointForm, WishlistEquipmentForm,
    WishlistLivestockForm,
)
from .models import (
    Animal, AnimalPhoto, AppSettings, CostEntry, DosingReservoir, FillTimer, ParameterType, PlannedItem, PlannedSystem,
    QuarantineEntry, ROSystem, SpeciesCatalog, Tank, TimelapseFrame, WebcamFeed, WebhookDelivery, WebhookEndpoint,
    WishlistItem, in_system,
)
from .views import _delete_object, _edit_object, _flash_form_errors, _safe_next, _to_decimal, _to_int, tank_volume_choices

MAX_TIMER_SECONDS = 24 * 60 * 60


def _form_page(request, form, title, back_url, subtitle='', multipart=False):
    return render(request, 'aquarium/generic_form.html', {
        'form': form, 'title': title, 'subtitle': subtitle, 'back_url': back_url, 'multipart': multipart,
    })


# ==========================================
# System selector & look
# ==========================================

@require_POST
def system_select_view(request):
    """Switches which system this browser is looking at, then returns to the same page."""
    response = redirect(_safe_next(request, reverse('dashboard')))
    tank = Tank.objects.filter(pk=_to_int(request.POST.get('tank'), None)).first()
    if tank:
        response.set_cookie(COOKIE_NAME, str(tank.pk), max_age=COOKIE_MAX_AGE, samesite='Lax')
    return response


def system_theme_view(request):
    tank = get_active_tank(request)
    if tank is None:
        messages.info(request, "Add a tank first, then you can choose its look.")
        return redirect('tank_create')
    form = SystemThemeForm(instance=tank)
    if request.method == 'POST':
        previous_icon = tank.custom_icon.name if tank.custom_icon else ''
        form = SystemThemeForm(request.POST, request.FILES, instance=tank)
        if form.is_valid():
            saved = form.save()
            if previous_icon and 'custom_icon' in request.FILES and saved.custom_icon.name != previous_icon:
                saved.custom_icon.storage.delete(previous_icon)
            messages.success(request, f"Saved the look for {saved.name}.")
            return redirect('system_theme')
        tank.refresh_from_db()
        _flash_form_errors(request, form)
    return render(request, 'aquarium/system_theme.html', {
        'form': form, 'themes': THEMES, 'stock_icons': STOCK_ICONS, 'retired_icons': RETIRED_ICONS, 'active_tank': tank,
    })


@require_POST
def tank_archive_view(request, tank_id):
    tank = get_object_or_404(Tank, pk=tank_id)
    retire.archive_system(tank)
    messages.success(request, f"{tank.name} has retired. Its history is safe, and it won't send any more alerts.")
    response = redirect('tanks')
    # Move on to a current system, rather than staying on the one just retired.
    if get_active_tank(request).pk == tank.pk:
        response.delete_cookie(COOKIE_NAME)
    return response


@require_POST
def tank_restore_view(request, tank_id):
    tank = get_object_or_404(Tank, pk=tank_id)
    retire.restore_system(tank)
    messages.success(request, f"{tank.name} is back from retirement.")
    response = redirect('tank_detail', tank_id=tank.pk)
    response.set_cookie(COOKIE_NAME, str(tank.pk), max_age=COOKIE_MAX_AGE, samesite='Lax')
    return response


# ==========================================
# The Damage: the hidden cost ledger
# ==========================================

DAMAGE_VERDICTS = [
    (0, "A clean slate. Suspiciously clean."),
    (100, "Still just a phase. You could stop any time."),
    (500, "A few nice dinners out. Worth it, the fish say."),
    (2000, "That's a decent laptop, and it can't even host clownfish."),
    (5000, "A solid used motorcycle, except wetter."),
    (15000, "A reliable used car. This one just never leaves the living room."),
    (40000, "A new car. Your corals would like you to know they appreciate it."),
    (100000, "A down payment on a house. For the fish."),
]


def _damage_verdict(total):
    verdict = DAMAGE_VERDICTS[0][1]
    for threshold, text in DAMAGE_VERDICTS:
        if total >= threshold and (threshold or total == 0):
            verdict = text
    return verdict


def _parse_date(raw):
    try:
        return parse_date(raw or '')
    except ValueError:
        return None


def _spending_points(entries, start, end):
    """Running total for the chart: [{'x': timestamp in ms, 'y': total, 'label': date}], oldest first."""
    by_day = {}
    for entry in entries:
        by_day[entry.spent_on] = by_day.get(entry.spent_on, 0.0) + float(entry.amount)
    if not by_day:
        return []

    def point(day, total):
        stamp = datetime.combine(day, datetime.min.time(), tzinfo=dt_timezone.utc).timestamp() * 1000
        return {'x': int(stamp), 'y': round(total, 2), 'label': day.strftime('%b %d, %Y')}

    days = sorted(by_day)
    first = start if start and start < days[0] else days[0] - timedelta(days=1)
    points = [point(first, 0.0)]
    total = 0.0
    for day in days:
        total += by_day[day]
        points.append(point(day, total))
    if end > days[-1]:
        points.append(point(end, total))
    return points


def the_damage_view(request):
    active = get_active_tank(request)
    if not AppSettings.load().costs_enabled:
        return render(request, 'aquarium/the_damage.html')

    # ?tank=all or ?tank=<id>, defaulting to the selected system.
    tank_param = request.GET.get('tank') or ('all' if request.GET.get('all') else '')
    tank = Tank.objects.filter(pk=_to_int(tank_param, None)).first() if tank_param != 'all' else None
    if tank is None and tank_param != 'all':
        tank = active
    show_all = tank is None

    if request.method == 'POST':
        form = CostEntryForm(request.POST)
        if form.is_valid():
            entry = form.save()
            messages.success(request, f"Added. No judgement. {entry.description} is on the fire.")
            return redirect(request.get_full_path())
        _flash_form_errors(request, form)

    today = timezone.localdate()
    date_from, date_to = _parse_date(request.GET.get('from')), _parse_date(request.GET.get('to'))
    if date_from and date_to and date_from > date_to:
        date_from, date_to = date_to, date_from

    system_entries = CostEntry.objects.select_related('tank')
    if not show_all:
        system_entries = system_entries.filter(tank=tank)
    system_entries = list(system_entries)
    entries = [e for e in system_entries
               if (not date_from or e.spent_on >= date_from) and (not date_to or e.spent_on <= date_to)]
    total = sum(float(e.amount) for e in entries)

    categories = dict(CostEntry.CATEGORY_CHOICES)
    grouped = {}
    for entry in entries:
        grouped[entry.category] = grouped.get(entry.category, 0.0) + float(entry.amount)
    by_category = [
        {'label': categories.get(key, key), 'total': value, 'percent': round(value / total * 100) if total else 0}
        for key, value in sorted(grouped.items(), key=lambda item: -item[1])
    ]

    gallons = sum(t.total_system_gallons for t in Tank.objects.filter(is_archived=False)) if show_all else tank.total_system_gallons
    first = date_from or min((e.spent_on for e in entries), default=None)
    last = min(date_to, today) if date_to else today
    system_query = {'tank': 'all' if show_all else tank.pk}
    presets = [
        ('Last 30 days', {'from': (today - timedelta(days=30)).isoformat()}),
        ('Last 90 days', {'from': (today - timedelta(days=90)).isoformat()}),
        ('This year', {'from': today.replace(month=1, day=1).isoformat()}),
        ('All time', {}),
    ]
    return render(request, 'aquarium/the_damage.html', {
        'entries': sorted(entries, key=lambda e: (e.spent_on, e.pk), reverse=True)[:100],
        'total': total,
        'verdict': _damage_verdict(total),
        'this_year': sum(float(e.amount) for e in system_entries if e.spent_on.year == today.year),
        'per_gallon': total / gallons if gallons and total else None,
        'per_day': total / max(1, (last - first).days + 1) if first and total else None,
        'power_month': power.power_summary(tank)['cost_month'],
        'by_category': by_category,
        'currency': AppSettings.load().currency_symbol,
        'show_all': show_all,
        'selected_tank': tank,
        'systems_all': Tank.objects.order_by('is_archived', '-is_primary', 'name'),
        'multiple_systems': Tank.objects.count() > 1,
        'date_from': date_from,
        'date_to': date_to,
        'range_active': bool(date_from or date_to),
        'presets': [
            {'label': label, 'query': urlencode({**system_query, **dates}),
             'active': dates.get('from') == (date_from.isoformat() if date_from else None) and not date_to}
            for label, dates in presets
        ],
        'chart_points': _spending_points(entries, date_from, last),
        'form': CostEntryForm(initial={'tank': tank or active, 'spent_on': today}),
    })


@require_POST
def damage_switch_view(request):
    """Lights or puts out the fire: turns prices on or off across the whole app. Nothing is deleted."""
    enabled = request.POST.get('enabled') == '1'
    AppSettings.load()
    AppSettings.objects.filter(pk=1).update(costs_enabled=enabled)
    if enabled:
        messages.success(request, "It's lit. You can now enter prices on the wishlist and in plans.")
    else:
        messages.info(request, "Fire's out. Prices are hidden, and everything you entered is kept for next time.")
    return redirect('the_damage')


def cost_edit_view(request, entry_id):
    if not AppSettings.load().costs_enabled:
        return redirect('the_damage')
    return _edit_object(request, CostEntry, CostEntryForm, entry_id, title='Edit Purchase', back_url=reverse('the_damage'))


@require_POST
def cost_delete_view(request, entry_id):
    CostEntry.objects.filter(pk=entry_id).delete()
    return redirect('the_damage')


# ==========================================
# Tools hub & settings
# ==========================================

def tools_view(request):
    settings_obj = AppSettings.load()
    return render(request, 'aquarium/tools.html', {
        'settings_obj': settings_obj,
        'plan_count': PlannedSystem.objects.count(),
        'running_timers': FillTimer.objects.filter(status='running').count(),
        'endpoint_count': WebhookEndpoint.objects.filter(is_active=True).count(),
        'quarantine_count': Animal.objects.filter(status='quarantine').count(),
        'power': power.power_summary(get_active_tank(request)),
        'latest_backup': next(iter(backups.list_backups()), None),
    })


def app_settings_view(request):
    obj = AppSettings.load()
    return _edit_object(request, AppSettings, AppSettingsForm, obj.pk, title='App Settings',
                        subtitle='Electricity price and automatic backups', back_url=reverse('tools'))


# ==========================================
# Power
# ==========================================

def power_view(request):
    raw = request.GET.get('tank')
    if raw == 'all':
        tank = None
    else:
        tank = Tank.objects.filter(pk=_to_int(raw, None)).first() or get_active_tank(request)
    return render(request, 'aquarium/power.html', {
        'summary': power.power_summary(tank), 'tanks': Tank.objects.filter(is_archived=False), 'selected_tank': tank,
    })


# ==========================================
# Quarantine
# ==========================================

def quarantine_list_view(request):
    active = Animal.objects.filter(status='quarantine').select_related('tank').order_by('quarantine_started', 'name')
    others = Animal.objects.exclude(status__in=['quarantine', 'rehomed', 'deceased']).order_by('name')
    return render(request, 'aquarium/quarantine_list.html', {'active': active, 'others': others})


def quarantine_detail_view(request, animal_id):
    animal = get_object_or_404(Animal, pk=animal_id)
    return render(request, 'aquarium/quarantine_detail.html', {
        'animal': animal,
        'entries': animal.quarantine_entries.all(),
        'entry_form': QuarantineEntryForm(initial={'logged_on': timezone.localdate()}),
        'plan_form': QuarantinePlanForm(initial={
            'started': animal.quarantine_started or timezone.localdate(), 'days': animal.quarantine_days,
        }),
    })


@require_POST
def quarantine_start_view(request, animal_id):
    animal = get_object_or_404(Animal, pk=animal_id)
    animal.status = 'quarantine'
    animal.quarantine_started = timezone.localdate()
    animal.save()
    messages.success(request, f"{animal.name} is now in quarantine.")
    return redirect('quarantine_detail', animal_id=animal.pk)


@require_POST
def quarantine_plan_view(request, animal_id):
    animal = get_object_or_404(Animal, pk=animal_id)
    form = QuarantinePlanForm(request.POST)
    if form.is_valid():
        animal.quarantine_started = form.cleaned_data['started']
        animal.quarantine_days = form.cleaned_data['days']
        animal.save()
        messages.success(request, "Quarantine plan updated.")
    else:
        _flash_form_errors(request, form)
    return redirect('quarantine_detail', animal_id=animal.pk)


@require_POST
def quarantine_finish_view(request, animal_id):
    animal = get_object_or_404(Animal, pk=animal_id)
    animal.status = 'healthy'
    animal.save()
    messages.success(request, f"{animal.name} is out of quarantine and marked healthy.")
    return redirect('quarantine_list')


@require_POST
def quarantine_entry_add_view(request, animal_id):
    animal = get_object_or_404(Animal, pk=animal_id)
    form = QuarantineEntryForm(request.POST)
    if form.is_valid():
        entry = form.save(commit=False)
        entry.animal = animal
        entry.save()
        messages.success(request, "Logged.")
    else:
        _flash_form_errors(request, form)
    return redirect('quarantine_detail', animal_id=animal.pk)


@require_POST
def quarantine_entry_delete_view(request, entry_id):
    entry = get_object_or_404(QuarantineEntry, pk=entry_id)
    animal_id = entry.animal_id
    entry.delete()
    messages.success(request, "Entry deleted.")
    return redirect('quarantine_detail', animal_id=animal_id)


# ==========================================
# Growth timeline
# ==========================================

def timeline_view(request, animal_id):
    animal = get_object_or_404(Animal, pk=animal_id)
    if request.method == 'POST':
        form = AnimalPhotoForm(request.POST, request.FILES)
        if form.is_valid():
            photo = form.save(commit=False)
            photo.animal = animal
            photo.save()
            messages.success(request, "Photo added to the timeline.")
            return redirect('timeline', animal_id=animal.pk)
        _flash_form_errors(request, form)
    else:
        form = AnimalPhotoForm(initial={'taken_on': timezone.localdate()})
    photos = list(animal.timeline_photos.all())
    return render(request, 'aquarium/timeline.html', {
        'animal': animal,
        'photos': photos,
        'form': form,
        'first': photos[0] if photos else None,
        'last': photos[-1] if photos else None,
        'photos_json': json.dumps([
            {'url': p.image.url, 'date': p.taken_on.strftime('%b %d, %Y'), 'note': p.note} for p in photos
        ]),
    })


@require_POST
def timeline_photo_delete_view(request, photo_id):
    photo = get_object_or_404(AnimalPhoto, pk=photo_id)
    animal_id = photo.animal_id
    photo.delete()
    messages.success(request, "Photo removed.")
    return redirect('timeline', animal_id=animal_id)


# ==========================================
# Webcam time-lapse
# ==========================================

def timelapse_view(request, cam_id):
    feed = get_object_or_404(WebcamFeed, pk=cam_id)
    days = _to_int(request.GET.get('days'), 7, 0, 3650)
    frames = feed.frames.all()
    if days:
        frames = frames.filter(captured_at__gte=timezone.now() - timedelta(days=days))
    frames = list(frames)
    return render(request, 'aquarium/timelapse.html', {
        'feed': feed,
        'days': days,
        'frame_count': len(frames),
        'total_frames': feed.frames.count(),
        'can_capture': bool(timelapse.snapshot_source(feed)),
        'frames_json': json.dumps([
            {'url': f.image.url, 'at': timezone.localtime(f.captured_at).strftime('%b %d %H:%M')} for f in frames
        ]),
    })


@require_POST
def timelapse_capture_view(request, cam_id):
    feed = get_object_or_404(WebcamFeed, pk=cam_id)
    frame = timelapse.capture_frame(feed)
    if frame:
        messages.success(request, "Frame captured.")
    else:
        feed.refresh_from_db()
        messages.error(request, f"Couldn't capture a frame: {feed.last_capture_error}")
    return redirect('timelapse', cam_id=feed.pk)


@require_POST
def timelapse_clear_view(request, cam_id):
    feed = get_object_or_404(WebcamFeed, pk=cam_id)
    for frame in feed.frames.all():
        frame.delete()
    messages.success(request, "All frames for this camera were deleted.")
    return redirect('timelapse', cam_id=feed.pk)


# ==========================================
# Webhooks & phone alerts
# ==========================================

def integrations_view(request):
    if request.method == 'POST':
        changed = 0
        for param in ParameterType.objects.all():
            raw = request.POST.get(f'stale_{param.pk}', '').strip()
            value = _to_int(raw, None, 1, 8760) if raw else None
            if param.stale_after_hours != value:
                param.stale_after_hours = value
                param.save(update_fields=['stale_after_hours'])
                changed += 1
        messages.success(request, "Probe alerts saved." if changed else "No changes.")
        return redirect('integrations')
    settings_obj = AppSettings.load()
    return render(request, 'aquarium/integrations.html', {
        'endpoints': WebhookEndpoint.objects.annotate(delivery_count=Count('deliveries'))
                     .prefetch_related('routines', 'timer_reservoirs'),
        'deliveries': WebhookDelivery.objects.select_related('endpoint')[:30],
        'parameters': ParameterType.objects.all(),
        'settings_obj': settings_obj,
        'api_key_set': bool(getattr(settings, 'API_SECRET_KEY', '')),
        'event_types': events.EVENT_TYPES,
    })


def webhook_create_view(request):
    if request.method == 'POST':
        form = WebhookEndpointForm(request.POST)
        if form.is_valid():
            endpoint = form.save()
            messages.success(request, f"Added {endpoint.name}. Send a test to check it works.")
            return redirect('integrations')
    else:
        form = WebhookEndpointForm()
    return _form_page(request, form, 'Add Webhook or Phone Alert', reverse('integrations'),
                      'Events are sent as they happen, in the background')


def webhook_edit_view(request, endpoint_id):
    return _edit_object(request, WebhookEndpoint, WebhookEndpointForm, endpoint_id, title='Edit Webhook',
                        back_url=reverse('integrations'), delete_url=reverse('webhook_delete', args=[endpoint_id]))


def webhook_delete_view(request, endpoint_id):
    endpoint = get_object_or_404(WebhookEndpoint, pk=endpoint_id)
    return _delete_object(request, WebhookEndpoint, endpoint_id, label=endpoint.name, back_url=reverse('integrations'))


@require_POST
def webhook_test_view(request, endpoint_id):
    endpoint = get_object_or_404(WebhookEndpoint, pk=endpoint_id)
    delivery = WebhookDelivery.objects.create(
        endpoint=endpoint, event_id=str(uuid.uuid4()), event_type='test', severity='info',
        title='Nudibranch test', message='If you can read this, this connection works.',
        data={'test': True}, max_attempts=1,
    )
    if events.send_delivery(delivery):
        messages.success(request, f"Test sent to {endpoint.name} (HTTP {delivery.response_code}).")
    else:
        messages.error(request, f"Test to {endpoint.name} failed: {delivery.error or delivery.response_code}")
    return redirect('integrations')


# ==========================================
# Backups
# ==========================================

def backups_view(request):
    return render(request, 'aquarium/backups.html', {
        'backups': backups.list_backups(),
        'settings_obj': AppSettings.load(),
    })


@require_POST
def backup_create_view(request):
    path = backups.create_backup('manual', include_timelapse=bool(request.POST.get('include_timelapse')))
    messages.success(request, f"Backup created: {path.name}")
    return redirect('backups')


def backup_download_view(request, name):
    try:
        path = backups.resolve_backup(name)
    except backups.BackupError as exc:
        raise Http404(str(exc))
    return FileResponse(open(path, 'rb'), as_attachment=True, filename=path.name)


@require_POST
def backup_delete_view(request, name):
    try:
        backups.resolve_backup(name).unlink()
        messages.success(request, "Backup deleted.")
    except backups.BackupError as exc:
        messages.error(request, str(exc))
    return redirect('backups')


@require_POST
def backup_restore_view(request):
    if request.POST.get('confirm', '').strip().upper() != 'RESTORE':
        messages.error(request, 'Type RESTORE to confirm. Nothing was changed.')
        return redirect('backups')
    upload = request.FILES.get('file')
    try:
        if upload:
            with tempfile.TemporaryDirectory() as tmp:
                target = Path(tmp) / 'upload.zip'
                with open(target, 'wb') as out:
                    for chunk in upload.chunks():
                        out.write(chunk)
                safety = backups.restore_backup(target)
        else:
            safety = backups.restore_backup(backups.resolve_backup(request.POST.get('name', '')))
    except backups.BackupError as exc:
        messages.error(request, f"Nothing was restored: {exc}")
        return redirect('backups')
    messages.success(request, f"Restored. Your previous data was saved as {safety}.")
    return redirect('backups')


# ==========================================
# Fill timers & RO calculator
# ==========================================

def _ro_context(system):
    return {
        'system': system,
        'gph': round(fill.estimated_gph(
            system.rated_gpd, system.rated_psi, system.rated_temp_f, system.feed_psi, system.feed_temp_f,
            system.measured_gph), 2),
    }


def _system_gph(system):
    return fill.estimated_gph(system.rated_gpd, system.rated_psi, system.rated_temp_f,
                              system.feed_psi, system.feed_temp_f, system.measured_gph)


def timers_view(request):
    systems = list(ROSystem.objects.all())
    ro_rows = [_ro_context(s) for s in systems]
    reservoirs = []
    active_tank = get_active_tank(request)
    for res in in_system(DosingReservoir.objects.select_related('tank'), active_tank):
        reservoirs.append({
            'id': res.pk, 'name': res.name,
            'gallons_to_full': round(max(0.0, fill.to_gallons(float(res.capacity) - float(res.current_level), res.unit)), 3),
            'capacity_gallons': round(fill.to_gallons(res.capacity, res.unit), 3),
            'is_ato': res.reservoir_type == 'ato_freshwater',
        })
    reservoirs.sort(key=lambda r: (not r['is_ato'], r['name']))
    settings_obj = AppSettings.load()
    return render(request, 'aquarium/timers.html', {
        'running': FillTimer.objects.filter(status='running').select_related('reservoir'),
        'recent': FillTimer.objects.exclude(status='running').select_related('reservoir').order_by('-ends_at')[:5],
        'ro_rows': ro_rows,
        'reservoirs': reservoirs,
        'systems_json': json.dumps([
            {'id': r['system'].pk, 'name': r['system'].name, 'gph': r['gph'], 'waste': float(r['system'].waste_ratio)}
            for r in ro_rows]),
        'reservoirs_json': json.dumps(reservoirs),
        'worker_online': settings_obj.worker_online,
        'timer_endpoints': sum(1 for e in WebhookEndpoint.objects.filter(is_active=True)
                               if e.wants('timer.finished', check_targets=False)),
        'all_endpoints': WebhookEndpoint.objects.filter(is_active=True),
        'volume_tank': tank_volume_choices(active_tank),
    })


@require_POST
def timer_start_view(request):
    minutes = _to_decimal(request.POST.get('minutes'))
    seconds = int(float(minutes) * 60) if minutes is not None else 0
    if not 0 < seconds <= MAX_TIMER_SECONDS:
        messages.error(request, "Enter a time between a few seconds and 24 hours.")
        return redirect('timers')
    reservoir = DosingReservoir.objects.filter(pk=_to_int(request.POST.get('reservoir'), None)).first()
    name = (request.POST.get('name') or '').strip()[:100] or (f"Fill {reservoir.name}" if reservoir else 'Timer')
    now = timezone.now()
    timer = FillTimer.objects.create(name=name, reservoir=reservoir, started_at=now, ends_at=now + timedelta(seconds=seconds))
    chosen = [pk for pk in (_to_int(raw, None) for raw in request.POST.getlist('endpoints')) if pk]
    timer.endpoints.set(WebhookEndpoint.objects.filter(pk__in=chosen))
    messages.success(request, f"Timer started: {name}.")
    return redirect('timers')


@require_POST
def timer_cancel_view(request, timer_id):
    FillTimer.objects.filter(pk=timer_id, status='running').update(status='cancelled')
    return redirect('timers')


@require_POST
def timer_extend_view(request, timer_id):
    timer = get_object_or_404(FillTimer, pk=timer_id)
    minutes = _to_int(request.POST.get('minutes'), 5, 1, 240)
    now = timezone.now()
    timer.ends_at = max(timer.ends_at, now) + timedelta(minutes=minutes)
    timer.status = 'running'
    timer.notified = False
    timer.save()
    return redirect('timers')


@require_POST
def timer_dismiss_view(request, timer_id):
    FillTimer.objects.filter(pk=timer_id).exclude(status='running').delete()
    return redirect('timers')


def ro_create_view(request):
    if request.method == 'POST':
        form = ROSystemForm(request.POST)
        if form.is_valid():
            system = form.save()
            _ensure_single_default(system)
            messages.success(request, f"Added {system.name}.")
            return redirect('timers')
    else:
        form = ROSystemForm(initial={'is_default': not ROSystem.objects.exists()})
    return _form_page(request, form, 'Add RO/DI System', reverse('timers'),
                      "Use your membrane's spec sheet. Time a real fill for the most accurate result.")


def _ensure_single_default(system):
    if system.is_default:
        ROSystem.objects.exclude(pk=system.pk).update(is_default=False)


def ro_edit_view(request, ro_id):
    response = _edit_object(request, ROSystem, ROSystemForm, ro_id, title='Edit RO/DI System',
                            back_url=reverse('timers'), delete_url=reverse('ro_delete', args=[ro_id]))
    if request.method == 'POST':
        system = ROSystem.objects.filter(pk=ro_id).first()
        if system:
            _ensure_single_default(system)
    return response


def ro_delete_view(request, ro_id):
    system = get_object_or_404(ROSystem, pk=ro_id)
    return _delete_object(request, ROSystem, ro_id, label=system.name, back_url=reverse('timers'))


def fill_calc_api(request):
    """Fill time for a volume on a chosen RO system (used by the calculator on the timers page)."""
    system = ROSystem.objects.filter(pk=_to_int(request.GET.get('system'), None)).first()
    gallons = _to_decimal(request.GET.get('gallons'))
    stop_at = _to_decimal(request.GET.get('stop_at'))
    if system is None or gallons is None:
        return JsonResponse({'error': 'Choose a system and an amount.'}, status=400)
    return JsonResponse(fill.fill_estimate(
        gallons, _system_gph(system), system.waste_ratio, stop_at if stop_at is not None else 100,
    ))


# ==========================================
# System planner
# ==========================================

def planner_list_view(request):
    plans = list(PlannedSystem.objects.select_related('existing_tank', 'tracked_tank').prefetch_related('items'))
    rows = [{'plan': plan, 'analysis': planner.analyze(plan)} for plan in plans]
    return render(request, 'aquarium/planner_list.html', {'rows': rows})


def plan_create_view(request):
    if request.method == 'POST':
        form = PlannedSystemForm(request.POST)
        if form.is_valid():
            plan = form.save()
            return redirect('plan_detail', plan_id=plan.pk)
    else:
        initial = {}
        tank_id = _to_int(request.GET.get('tank'), None)
        if tank_id:
            tank = Tank.objects.filter(pk=tank_id).first()
            if tank:
                initial = {'existing_tank': tank, 'name': f"Stocking plan for {tank.name}"}
        form = PlannedSystemForm(initial=initial)
    return _form_page(request, form, 'New System Plan', reverse('planner'),
                      'Sketch a system, or plan additions to a tank you already have')


def plan_detail_view(request, plan_id):
    plan = get_object_or_404(PlannedSystem.objects.select_related('existing_tank', 'tracked_tank'), pk=plan_id)
    return render(request, 'aquarium/planner_detail.html', {
        'plan': plan,
        'a': planner.analyze(plan),
        'livestock_form': PlannedLivestockForm(prefix='animal'),
        'equipment_form': PlannedEquipmentForm(prefix='gear'),
    })


def plan_edit_view(request, plan_id):
    return _edit_object(request, PlannedSystem, PlannedSystemForm, plan_id, title='Edit Plan',
                        back_url=reverse('plan_detail', args=[plan_id]), delete_url=reverse('plan_delete', args=[plan_id]))


def plan_delete_view(request, plan_id):
    plan = get_object_or_404(PlannedSystem, pk=plan_id)
    return _delete_object(request, PlannedSystem, plan_id, label=plan.name, back_url=reverse('planner'),
                          warning='Only the plan is deleted. Anything already being tracked stays.')


@require_POST
def plan_add_livestock_view(request, plan_id):
    plan = get_object_or_404(PlannedSystem, pk=plan_id)
    form = PlannedLivestockForm(request.POST, prefix='animal')
    if form.is_valid():
        item = form.save(commit=False)
        item.plan = plan
        item.kind = 'livestock'
        item.name = item.species.name
        item.save()
        plan.save(update_fields=['updated_at'])
    else:
        _flash_form_errors(request, form)
    return redirect('plan_detail', plan_id=plan.pk)


@require_POST
def plan_add_equipment_view(request, plan_id):
    plan = get_object_or_404(PlannedSystem, pk=plan_id)
    form = PlannedEquipmentForm(request.POST, prefix='gear')
    if form.is_valid():
        item = form.save(commit=False)
        item.plan = plan
        item.kind = 'equipment'
        item.save()
        plan.save(update_fields=['updated_at'])
    else:
        _flash_form_errors(request, form)
    return redirect('plan_detail', plan_id=plan.pk)


@require_POST
def plan_item_delete_view(request, item_id):
    item = get_object_or_404(PlannedItem, pk=item_id)
    plan_id = item.plan_id
    item.delete()
    return redirect('plan_detail', plan_id=plan_id)


def plan_track_view(request, plan_id):
    """Review what will be created, then turn the plan into real tracked records."""
    plan = get_object_or_404(PlannedSystem.objects.select_related('existing_tank', 'tracked_tank'), pk=plan_id)
    target = plan.existing_tank or plan.tracked_tank
    pending = plan.items.filter(tracked=False)
    if request.method == 'POST':
        if not pending.exists() and target is not None:
            messages.info(request, "Everything in this plan is already being tracked.")
            return redirect('tank_detail', tank_id=target.pk)
        tank = planner.track_plan(plan, quarantine_fish=bool(request.POST.get('quarantine_fish')))
        messages.success(request, f"Now tracking {tank.name}.")
        return redirect('tank_detail', tank_id=tank.pk)
    return render(request, 'aquarium/planner_track.html', {
        'plan': plan, 'target': target, 'a': planner.analyze(plan),
        'pending_livestock': pending.filter(kind='livestock'),
        'pending_gear': pending.filter(kind='equipment'),
        'back_url': _safe_next(request, reverse('plan_detail', args=[plan.pk])),
    })


# ==========================================
# Wishlist
# ==========================================

def wishlist_view(request):
    items = wishlist.wanted_items()
    combined = wishlist.fit_summary(items, default=get_active_tank(request))
    return render(request, 'aquarium/wishlist.html', {
        'items': items,
        'combined': combined,
        'total': sum(float(i.total_price) for i in items),
        'unpriced': sum(1 for i in items if i.est_price is None),
        'currency': AppSettings.load().currency_symbol,
        'bought': WishlistItem.objects.filter(status='acquired').select_related('tank').order_by('-acquired_at')[:10],
        'tanks': Tank.objects.filter(is_archived=False),
        'plans': PlannedSystem.objects.all(),
        'livestock_form': WishlistLivestockForm(),
        'equipment_form': WishlistEquipmentForm(),
    })


def _wishlist_add(request, form_class):
    form = form_class(request.POST)
    if form.is_valid():
        item = form.save()
        messages.success(request, f"Added {item.name} to your wishlist.")
    else:
        _flash_form_errors(request, form)
    return redirect('wishlist')


@require_POST
def wishlist_add_livestock_view(request):
    return _wishlist_add(request, WishlistLivestockForm)


@require_POST
def wishlist_add_equipment_view(request):
    return _wishlist_add(request, WishlistEquipmentForm)


@require_POST
def wishlist_add_species_view(request, species_id):
    """The one-tap button on species catalog cards."""
    species = get_object_or_404(SpeciesCatalog, pk=species_id)
    if WishlistItem.objects.filter(species=species, status='wanted').exists():
        messages.info(request, f"{species.name} is already on your wishlist.")
    else:
        WishlistItem.objects.create(kind='livestock', species=species, name=species.name)
        messages.success(request, f"Added {species.name} to your wishlist.")
    return redirect(_safe_next(request, reverse('wishlist')))


def wishlist_edit_view(request, item_id):
    item = get_object_or_404(WishlistItem, pk=item_id)
    form_class = WishlistEquipmentForm if item.kind == 'equipment' else WishlistLivestockForm
    return _edit_object(request, WishlistItem, form_class, item_id, title=f"Edit {item.name}", back_url=reverse('wishlist'))


@require_POST
def wishlist_delete_view(request, item_id):
    WishlistItem.objects.filter(pk=item_id).delete()
    return redirect('wishlist')


@require_POST
def wishlist_to_plan_view(request, item_id):
    item = get_object_or_404(WishlistItem, pk=item_id)
    plan = get_object_or_404(PlannedSystem, pk=_to_int(request.POST.get('plan'), 0))
    if wishlist.add_to_plan(item, plan):
        messages.success(request, f"Added {item.name} to {plan.name}.")
    else:
        messages.info(request, f"{item.name} is already in a plan or bought.")
    return redirect('wishlist')


@require_POST
def wishlist_bought_view(request, item_id):
    item = get_object_or_404(WishlistItem, pk=item_id)
    tank = Tank.objects.filter(pk=_to_int(request.POST.get('tank'), 0)).first() or wishlist.primary_tank()
    if wishlist.mark_bought(item, tank, quarantine=bool(request.POST.get('quarantine'))):
        messages.success(request, f"Nice! {item.name} is now tracked{f' in {tank.name}' if tank else ''}.")
    else:
        messages.info(request, f"{item.name} was already added.")
    return redirect('wishlist')
