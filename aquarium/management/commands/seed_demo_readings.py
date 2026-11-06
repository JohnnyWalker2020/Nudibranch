import random
from datetime import timedelta
from decimal import ROUND_HALF_UP, Decimal

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from aquarium.models import ParameterLog, ParameterType, Tank

DEMO_NOTE = 'Demo data'

# Hours between tests, by parameter code. Probes report often, and slow-moving elements get tested less.
TEST_EVERY_HOURS = {
    'temperature': 12, 'ph': 12, 'alkalinity': 48, 'salinity': 72,
    'calcium': 96, 'nitrate': 96, 'phosphate': 96, 'magnesium': 168,
}
DEFAULT_TEST_EVERY_HOURS = 72

# (from this many days ago, to this many days ago, level, what happened). A window ending at 0 is still happening.
EPISODES = {
    'alkalinity': [(62, 57, 'low', 'dosing pump ran dry'), (0.4, 0, 'critical_low', 'dosing pump ran dry again')],
    'nitrate': [(48, 41, 'high', 'heavy feeding')],
    'temperature': [(34, 33.4, 'critical_high', 'heater stuck on')],
    'calcium': [(21, 16, 'low', 'reactor needs adjusting')],
    'salinity': [(12, 8, 'high', 'top-off ran out')],
    'phosphate': [(9, 0, 'high', 'skimmer needs cleaning')],
}


class Command(BaseCommand):
    help = ("Adds realistic made-up water tests so the charts and alerts have something to show. "
            "Most stay in range, with a few problems along the way. Your own readings are never changed. "
            "Run again to replace them, or use --remove to take them out.")

    def add_arguments(self, parser):
        parser.add_argument('--tank', help="A system's ID or name. Default: every system that isn't retired.")
        parser.add_argument('--days', type=int, default=90, help='How many days of history to make (default 90).')
        parser.add_argument('--remove', action='store_true', help='Remove the demo readings and add nothing.')

    def handle(self, *args, tank=None, days=90, remove=False, **options):
        tanks = self._tanks(tank)
        if days < 14:
            raise CommandError('--days must be at least 14.')
        with transaction.atomic():
            for system in tanks:
                removed, _ = demo_logs(system).delete()
                if remove:
                    self.stdout.write(f'{system.name}: removed {removed} demo readings.')
                    continue
                readings = build_readings(system, days, timezone.now())
                ParameterLog.objects.bulk_create(readings)
                self.stdout.write(self.style.SUCCESS(f'{system.name}: added {len(readings)} demo readings.'))

    def _tanks(self, wanted):
        if not wanted:
            return list(Tank.objects.filter(is_archived=False))
        found = Tank.objects.filter(pk=int(wanted)) if wanted.isdigit() else Tank.objects.filter(name__iexact=wanted)
        if not found.exists():
            raise CommandError(f'No system called "{wanted}".')
        return list(found)


def demo_logs(tank):
    return ParameterLog.objects.filter(tank=tank, notes__startswith=DEMO_NOTE)


def build_readings(tank, days, now):
    readings = []
    for base in ParameterType.objects.all():
        readings += _readings_for(base.for_system(tank), tank, days, now, random.Random(f'{tank.pk}:{base.code}'))
    return readings


def _readings_for(param, tank, days, now, rng):
    every = timedelta(hours=TEST_EVERY_HOURS.get(param.code, DEFAULT_TEST_EVERY_HOURS))
    episodes = [e for e in EPISODES.get(param.code, []) if e[0] <= days]
    times = _test_times(now, days, every, episodes, rng)

    readings = []
    drift = rng.uniform(-.3, .3)  # where it sits in its range, from -1 at the bottom to 1 at the top
    for when in times:
        drift = min(.85, max(-.85, drift * .8 + rng.gauss(0, .22)))
        days_ago = (now - when).total_seconds() / 86400
        episode = next((e for e in episodes if e[1] <= days_ago <= e[0]), None)
        if episode:
            value, note = _episode_value(param, episode[2], rng), f'{DEMO_NOTE}: {episode[3]}'
        else:
            position = drift
            if param.code == 'ph':  # a reef's pH rises with the lights and falls overnight
                position = min(.85, max(-.85, drift * .4 + (.35 if 6 <= when.hour < 18 else -.35)))
            value, note = _value_at(param, position), DEMO_NOTE
        readings.append(ParameterLog(parameter_type=param, tank=tank, measured_at=when, value=_rounded(param, value), notes=note))
    return readings


def _test_times(now, days, every, episodes, rng):
    """Newest first from just now back to the start, with people being a little late, plus one test in every episode."""
    jitter = every.total_seconds() / 3600 * .1
    times = []
    when = now - timedelta(hours=1)
    start = now - timedelta(days=days)
    while when > start:
        times.append(when - timedelta(hours=rng.uniform(0, jitter)))
        when -= every
    for begins, ends, _, _ in episodes:
        times.append(now - timedelta(days=(begins + ends) / 2))
    return sorted(times)


def _value_at(param, position):
    low, high = float(param.min_ideal), float(param.max_ideal)
    return (low + high) / 2 + position * (high - low) / 2


def _episode_value(param, level, rng):
    """Outside the ideal range by a believable amount, using this parameter's own limits, so any unit works."""
    low, high = float(param.min_ideal), float(param.max_ideal)
    span = high - low
    low_limit = float(param.low_limit) if param.low_limit is not None else low - span / 2
    high_limit = float(param.high_limit) if param.high_limit is not None else high + span / 2
    if level == 'low':
        return low - (low - low_limit) * rng.uniform(.35, .75)
    if level == 'high':
        return high + (high_limit - high) * rng.uniform(.35, .75)
    if level == 'critical_low':
        return max(0.0, low_limit - span * .1)
    return high_limit + span * .1


def _rounded(param, value):
    step = Decimal(1).scaleb(-min(param.decimal_places, 4))
    return Decimal(str(value)).quantize(step, rounding=ROUND_HALF_UP)
