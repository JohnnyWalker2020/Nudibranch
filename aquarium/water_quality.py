"""A water quality rating from your own test logs, against each tank's target ranges.

It's a summary of what you've logged, not a lab result: only parameters tested in the last 30 days count, and each is
scored against the ranges you set (or the shared defaults).

- Inside the ideal range: 100.
- Between the ideal range and the alarm limit: slides from 100 down to 50.
- Past the limit: from 40 down to 0 as it gets further out.
- The core reef parameters count double.
"""
from datetime import timedelta

from django.utils import timezone

RECENT_DAYS = 30
CORE_CODES = {'salinity', 'temperature', 'alkalinity', 'calcium', 'magnesium', 'nitrate', 'phosphate', 'ph'}

GRADES = [  # (lowest score, grade, a few words)
    (90, 'Excellent', 'Crystal clear: everything is where you want it.'),
    (75, 'Good', 'Looking healthy, with a little to tidy up.'),
    (60, 'Fair', 'A few readings are drifting. Worth a look.'),
    (40, 'Needs attention', 'Several readings are out of range.'),
    (0, 'Poor', 'Readings are well outside your targets. Check them soon.'),
]


def _score(value, low_ideal, high_ideal, low_limit, high_limit):
    """0-100 for one reading against its ranges."""
    if low_ideal <= value <= high_ideal:
        return 100.0
    width = max(high_ideal - low_ideal, abs(high_ideal) * 0.05, 1e-9)
    if value < low_ideal:
        edge, limit, gap = low_ideal, low_limit, low_ideal - value
    else:
        edge, limit, gap = high_ideal, high_limit, value - high_ideal
    span = abs(edge - limit) if limit is not None else width  # no limit set: one range-width of grace
    span = max(span, 1e-9)
    if gap <= span:
        return 100.0 - 50.0 * gap / span
    beyond = (gap - span) / max(width, span)
    return max(0.0, 40.0 * (1 - beyond))


def rate(parameter_types, latest_logs, now=None):
    """The rating for one tank. `parameter_types` must already carry that tank's ranges (ParameterType.for_system)
    and `latest_logs` is {parameter id: newest log}. Returns None when nothing recent has been logged."""
    now = now or timezone.now()
    cutoff = now - timedelta(days=RECENT_DAYS)
    rows, stale, total, weights = [], [], 0.0, 0.0
    for pt in parameter_types:
        log = latest_logs.get(pt.pk)
        if log is None:
            continue
        if log.measured_at < cutoff:
            stale.append(pt)
            continue
        low_limit = float(pt.low_limit) if pt.low_limit is not None else None
        high_limit = float(pt.high_limit) if pt.high_limit is not None else None
        score = _score(float(log.value), float(pt.min_ideal), float(pt.max_ideal), low_limit, high_limit)
        weight = 2.0 if (pt.code or '').lower() in CORE_CODES else 1.0
        rows.append({'parameter': pt, 'log': log, 'score': round(score)})
        total += score * weight
        weights += weight
    if not rows:
        return None
    overall = round(total / weights)
    grade, blurb = next((g, b) for floor, g, b in GRADES if overall >= floor)
    rows.sort(key=lambda r: r['score'])
    return {
        'score': overall,
        'grade': grade,
        'blurb': blurb,
        'tone': 'good' if overall >= 75 else 'fair' if overall >= 60 else 'bad',
        'counted': len(rows),
        'dragging': [r for r in rows if r['score'] < 100][:4],
        'stale': stale,
        'days': RECENT_DAYS,
    }
