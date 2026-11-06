"""
Keeps a record of alerts as they start and resolve, for the Alerts page. The background worker
passes in everything that's currently wrong, on every pass.
"""
from collections import Counter
from datetime import timedelta

from django.db.models import Q
from django.utils import timezone

from .models import AlertRecord, AppSettings, in_system

# A problem that comes back this soon carries on the same record, so a probe hovering around a limit
# doesn't fill the history. Same idea as the quiet period for notifications.
REOPEN_WITHIN = timedelta(minutes=30)
SEVERITY_RANK = {'info': 0, 'warning': 1, 'critical': 2}
MAX_LISTED = 50


def record_alert_history(conditions, now=None):
    now = now or timezone.now()
    current = {c['issue']: c for c in conditions}
    recent = AlertRecord.objects.filter(
        Q(resolved_at__isnull=True) | Q(resolved_at__gte=now - REOPEN_WITHIN)
    ).select_related('tank').order_by('started_at')
    known = {record.issue_key: record for record in recent}

    for issue, cond in current.items():
        record = known.get(issue)
        if record is None:
            AlertRecord.objects.create(
                issue_key=issue[:120], event_type=cond['type'], severity=cond['severity'], tank_id=cond['system_id'],
                subject=cond['subject'][:120], title=cond['title'][:200], message=cond['message'][:300], started_at=now,
            )
            continue
        worst = max(record.severity, cond['severity'], key=lambda level: SEVERITY_RANK.get(level, 0))
        updates = {'event_type': cond['type'], 'severity': worst, 'title': cond['title'][:200],
                   'message': cond['message'][:300], 'resolved_at': None, 'resolution': ''}
        if any(getattr(record, name) != value for name, value in updates.items()):
            AlertRecord.objects.filter(pk=record.pk).update(**updates)

    for issue, record in known.items():
        if issue not in current and record.resolved_at is None:
            retired = record.tank is not None and record.tank.is_archived
            AlertRecord.objects.filter(pk=record.pk).update(
                resolved_at=now, resolution=AlertRecord.SYSTEM_RETIRED if retired else '')


def prune_alert_history(now=None):
    now = now or timezone.now()
    keep = timedelta(days=AppSettings.load().resolved_alert_days)
    AlertRecord.objects.filter(resolved_at__lt=now - keep).delete()


def alert_summary(tank, severity='', now=None):
    """The resolved list (optionally one severity) and metrics for one system, within the days being kept."""
    now = now or timezone.now()
    days = AppSettings.load().resolved_alert_days
    cutoff = now - timedelta(days=days)
    records = list(in_system(AlertRecord.objects.select_related('tank'), tank).filter(
        Q(resolved_at__isnull=True) | Q(resolved_at__gte=cutoff)))

    resolved = sorted((r for r in records if r.resolved_at), key=lambda r: r.resolved_at, reverse=True)
    listed = [r for r in resolved if not severity or r.severity == severity]
    return {
        'days': days,
        'resolved': listed[:MAX_LISTED],
        'resolved_count': len(listed),
        'metrics': _metrics(records, resolved),
    }


def _metrics(records, resolved):
    # A notice was never a problem, so it would only skew these.
    records = [r for r in records if r.resolution != AlertRecord.NOTICE]
    if not records:
        return None
    # An alert that ended because its tank retired was never actually fixed.
    fixed = [r for r in resolved if r.resolution not in (AlertRecord.SYSTEM_RETIRED, AlertRecord.NOTICE)]
    durations = [r.duration for r in fixed]
    subject, times = Counter(r.subject for r in records).most_common(1)[0]
    return {
        'total': len(records),
        'open': sum(1 for r in records if r.resolved_at is None),
        'fixed': len(fixed),
        'critical': sum(1 for r in records if r.severity == 'critical'),
        'average': AlertRecord.describe(sum(durations, timedelta()) / len(durations)) if durations else None,
        'longest': AlertRecord.describe(max(durations)) if durations else None,
        'most_frequent': subject,
        'most_frequent_times': times,
    }
