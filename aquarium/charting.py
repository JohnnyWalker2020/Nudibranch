"""Turns readings into chart points. Sensors can send a reading every few seconds, so by default the readings
in each minute are averaged into one point; hand-logged tests, hours apart, come through unchanged."""
from datetime import timezone as dt_timezone

from django.utils import timezone

DEFAULT_EVERY_SECONDS = 60


def every_seconds(request):
    """?every=<seconds> picks the spacing (0 = every reading as it came in). One minute unless asked."""
    try:
        value = int(request.GET.get('every', DEFAULT_EVERY_SECONDS))
    except (TypeError, ValueError):
        return DEFAULT_EVERY_SECONDS
    return max(0, min(value, 86400))


def points(queryset, decimals, every=DEFAULT_EVERY_SECONDS):
    """{'labels', 'timestamps', 'values'} for Chart.js: one averaged point per `every` seconds."""
    rows = queryset.order_by('measured_at').values_list('measured_at', 'value')
    buckets = []  # [start, total, count]
    for when, value in rows.iterator():
        stamp = when.timestamp()
        start = stamp - (stamp % every) if every else stamp
        if buckets and buckets[-1][0] == start:
            buckets[-1][1] += float(value)
            buckets[-1][2] += 1
        else:
            buckets.append([start, float(value), 1])

    def shown(value):
        return round(value, decimals) if decimals > 0 else round(value)
    local = timezone.localtime
    return {
        'labels': [local(timezone.datetime.fromtimestamp(b[0], tz=dt_timezone.utc)).strftime('%m/%d %H:%M') for b in buckets],
        'timestamps': [int(b[0] * 1000) for b in buckets],
        'values': [shown(b[1] / b[2]) for b in buckets],
        'every_seconds': every,
    }
