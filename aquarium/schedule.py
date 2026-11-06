"""
Repeat-schedule maths for routines (plain Python, no Django imports, so it can be tested on its own).

A schedule is: a start date, "every N", and a unit (day / week / month / year).
Weekly schedules can also pick weekdays (0 = Monday ... 6 = Sunday); with none picked
they repeat on the start date's weekday. Monthly/yearly schedules land on the start
date's day of month, clamped to the end of shorter months (Jan 31 -> Feb 28).
"""
import calendar
import re
from datetime import date, timedelta

UNITS = [
    ('day', 'Days'),
    ('week', 'Weeks'),
    ('month', 'Months'),
    ('year', 'Years'),
]

# (every, unit) shortcuts offered in the form. 'custom' shows the every/unit fields.
REPEAT_PRESETS = [
    ('1:day', 'Every day'),
    ('2:day', 'Every 2 days'),
    ('1:week', 'Every week'),
    ('2:week', 'Every 2 weeks'),
    ('1:month', 'Every month'),
    ('3:month', 'Every 3 months'),
    ('6:month', 'Every 6 months'),
    ('1:year', 'Every year'),
    ('custom', 'Custom...'),
]

WEEKDAY_NAMES = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']
_PERIOD_DAYS = {'day': 1, 'week': 7, 'month': 31, 'year': 366}


def add_months(d, months):
    m = d.month - 1 + months
    y = d.year + m // 12
    m = m % 12 + 1
    return date(y, m, min(d.day, calendar.monthrange(y, m)[1]))


def _clean(every, unit, weekdays):
    every = max(1, int(every or 1))
    unit = unit if unit in _PERIOD_DAYS else 'day'
    wd = sorted({int(x) for x in (weekdays or []) if str(x).isdigit() and 0 <= int(x) <= 6})
    return every, unit, wd


def period_days(every, unit):
    every, unit, _ = _clean(every, unit, None)
    return every * _PERIOD_DAYS[unit]


def occurs_on(day, start, every=1, unit='day', weekdays=None):
    """True if the schedule has an occurrence on `day`."""
    if day < start:
        return False
    every, unit, wd = _clean(every, unit, weekdays)
    if unit == 'day':
        return (day - start).days % every == 0
    if unit == 'week':
        wd = wd or [start.weekday()]
        if day.weekday() not in wd:
            return False
        week0 = start - timedelta(days=start.weekday())
        week_n = day - timedelta(days=day.weekday())
        return ((week_n - week0).days // 7) % every == 0
    step = every * (12 if unit == 'year' else 1)
    diff = (day.year - start.year) * 12 + (day.month - start.month)
    return diff % step == 0 and day == add_months(start, diff)


def next_occurrence(on_or_after, start, every=1, unit='day', weekdays=None):
    """First occurrence on or after `on_or_after` (None if the schedule is broken)."""
    d = max(on_or_after, start)
    for _ in range(period_days(every, unit) + 8):
        if occurs_on(d, start, every, unit, weekdays):
            return d
        d += timedelta(days=1)
    return None


def previous_occurrence(on_or_before, start, every=1, unit='day', weekdays=None):
    """Last occurrence on or before `on_or_before` (None if before the start)."""
    d = on_or_before
    for _ in range(period_days(every, unit) + 8):
        if d < start:
            return None
        if occurs_on(d, start, every, unit, weekdays):
            return d
        d -= timedelta(days=1)
    return None


def next_due_date(start, every, unit, weekdays=None, last_done=None):
    """
    When a manual routine is next due.

    Never done: the first occurrence on/after the start date (may be in the past = overdue).
    Done: the completion counts for whichever occurrence it was nearest to, so doing a
    Saturday job on Friday covers that Saturday, and doing it on Sunday covers the day before.
    """
    if last_done is None:
        return next_occurrence(start, start, every, unit, weekdays)
    prev = previous_occurrence(last_done, start, every, unit, weekdays)
    nxt = next_occurrence(last_done + timedelta(days=1), start, every, unit, weekdays)
    if nxt is None:
        return None
    if prev is None:
        # Done before the schedule started: counts for the first occurrence if it's close.
        covers_next = (nxt - last_done).days * 2 < period_days(every, unit)
    else:
        covers_next = (nxt - last_done) < (last_done - prev)
    if covers_next:
        return next_occurrence(nxt + timedelta(days=1), start, every, unit, weekdays)
    return nxt


STEP_TIMER = re.compile(r'^(.*?)\s*\[\s*(\d+(?:\.\d+)?)\s*(s|secs?|seconds?|m|mins?|minutes?|h|hrs?|hours?)?\s*(?:@\s*([^\]]+?))?\s*\]\s*$', re.IGNORECASE)
MAX_STEP_MINUTES = 24 * 60


def parse_step(line):
    """
    'Wait for the colour to develop [5 min]' -> {'text': 'Wait for the colour to develop', 'minutes': 5.0, 'label': '5 min', 'webhook': ''}.
    Naming a connection, as in [5 min @Feeder], sends that step's finish to it.
    """
    match = STEP_TIMER.match(line or '')
    if not match or not match.group(1):
        return {'text': line, 'minutes': None, 'label': '', 'webhook': ''}
    amount = float(match.group(2))
    unit = (match.group(3) or 'm').lower()
    if unit.startswith('s'):
        minutes, short = amount / 60, 'sec'
    elif unit.startswith('h'):
        minutes, short = amount * 60, 'hr'
    else:
        minutes, short = amount, 'min'
    if not 0 < minutes <= MAX_STEP_MINUTES:
        return {'text': line, 'minutes': None, 'label': '', 'webhook': ''}
    return {'text': match.group(1), 'minutes': minutes, 'label': f"{amount:g} {short}", 'webhook': match.group(4) or ''}


def _ordinal(n):
    if 10 <= n % 100 <= 20:
        suffix = 'th'
    else:
        suffix = {1: 'st', 2: 'nd', 3: 'rd'}.get(n % 10, 'th')
    return f"{n}{suffix}"


def describe(start, every, unit, weekdays=None):
    """'Every day', 'Every 2 weeks on Sat', 'Every 6 months on the 5th', 'Every year on Nov 5'."""
    every, unit, wd = _clean(every, unit, weekdays)
    if unit == 'day':
        return "Every day" if every == 1 else f"Every {every} days"
    if unit == 'week':
        wd = wd or [start.weekday()]
        if wd == list(range(7)) and every == 1:
            return "Every day"
        days = "weekdays" if wd == [0, 1, 2, 3, 4] else "weekends" if wd == [5, 6] else ", ".join(WEEKDAY_NAMES[d] for d in wd)
        base = "Every week" if every == 1 else f"Every {every} weeks"
        return f"{base} on {days}"
    if unit == 'month':
        base = "Every month" if every == 1 else f"Every {every} months"
        return f"{base} on the {_ordinal(start.day)}"
    base = "Every year" if every == 1 else f"Every {every} years"
    return f"{base} on {start.strftime('%b')} {start.day}"


def preset_key(every, unit):
    key = f"{int(every or 1)}:{unit}"
    return key if key in dict(REPEAT_PRESETS) else 'custom'


def from_frequency_days(days):
    """Best (every, unit) for an old 'every N days' routine."""
    days = max(1, int(days or 1))
    if days % 365 == 0:
        return days // 365, 'year'
    if days in (30, 31):
        return 1, 'month'
    if days % 30 == 0 and days < 365:
        return days // 30, 'month'
    if days % 7 == 0:
        return days // 7, 'week'
    return days, 'day'
