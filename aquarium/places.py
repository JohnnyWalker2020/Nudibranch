"""Places in a system where a water level can be read: the display tank, a sump, one of its chambers, a reservoir.

Readings with a place are kept apart from the tank's water tests (see ParameterLog.objects), so a sump at
150 mm and a display at 400 mm never land on one chart or one alert. Each place has its own low and high level.
"""
from django.db.models import Max

from .models import AppSettings, DosingReservoir, ParameterLog, ParameterType, Sump, SumpChamber

PLACE_KEYS = ('chamber', 'sump', 'reservoir')
LEVEL_CODE = 'water_level'


class PlaceError(ValueError):
    pass


def _pick(queryset, identifier, kind, name_of, lookup_help):
    """One place from an ID or a name (any case). Several with the same name need the ID."""
    text = str(identifier).strip()
    if not text:
        raise PlaceError(f"Give the {kind}'s ID or name.")
    if text.isdecimal():
        found = queryset.filter(pk=int(text)).first()
        if found:
            return found
    matches = [p for p in queryset if text.lower() in {n.lower() for n in name_of(p)}]
    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        raise PlaceError(f"More than one {kind} is called '{text}'. Send its ID instead ({lookup_help}).")
    raise PlaceError(f"Unknown {kind} '{text}' ({lookup_help}).")


def chamber_names(chamber):
    """A chamber answers to its own name, its plain type name, and 'Sump › Chamber' or 'Sump/Chamber'."""
    plain = chamber.plain_name
    return {plain, chamber.name or plain, f"{chamber.sump.name} › {plain}", f"{chamber.sump.name}/{plain}",
            f"{chamber.sump.name} / {plain}"}


def resolve(reading, tank=None):
    """The place a reading names, as {'chamber': obj} / {'sump': obj} / {'reservoir': obj}, or {} for the display.

    `tank`, when the reading names one, narrows the search and must match. Raises PlaceError.
    """
    given = [key for key in PLACE_KEYS if reading.get(key) not in (None, '')]
    if not given:
        return {}
    if len(given) > 1:
        raise PlaceError(f"Give one place, not {' and '.join(given)}. A chamber already says which sump it's in.")
    key = given[0]
    help_text = 'GET /api/tanks/<tank>/ lists them'
    if key == 'chamber':
        queryset = SumpChamber.objects.select_related('sump__tank').filter(sump__tank__is_archived=False)
        if tank is not None:
            queryset = queryset.filter(sump__tank=tank)
        place = _pick(queryset, reading[key], 'chamber', chamber_names, help_text)
    elif key == 'sump':
        queryset = Sump.objects.select_related('tank').filter(tank__is_archived=False)
        if tank is not None:
            queryset = queryset.filter(tank=tank)
        place = _pick(queryset, reading[key], 'sump', lambda s: {s.name}, help_text)
    else:
        queryset = DosingReservoir.objects.select_related('tank').filter(tank__is_archived=False)
        if tank is not None:
            queryset = queryset.filter(tank=tank)
        place = _pick(queryset, reading[key], 'reservoir', lambda r: {r.name}, help_text)
    return {key: place}


def tank_of(place):
    kind, obj = next(iter(place.items()))
    return obj.sump.tank if kind == 'chamber' else obj.tank


def describe(log):
    """A reading's place for the API: None for the display tank."""
    if log.chamber_id:
        return {'type': 'chamber', 'id': log.chamber_id, 'name': log.place_label}
    if log.sump_id:
        return {'type': 'sump', 'id': log.sump_id, 'name': log.place_label}
    if log.reservoir_id:
        return {'type': 'reservoir', 'id': log.reservoir_id, 'name': log.place_label}
    return None


def latest_levels(tank):
    """{('display', None) | ('sump', id) | ('chamber', id) | ('reservoir', id): newest water level} for one tank."""
    if tank is None or not AppSettings.load().has_level_readings:
        return {}  # no level has ever been logged, so there is nothing to look up
    level = ParameterType.objects.filter(code=LEVEL_CODE).first()
    if level is None or tank is None:
        return {}
    readings = ParameterLog.everywhere.filter(parameter_type=level, tank=tank)
    # One small query per place that has readings, however many a sensor has sent
    groups = readings.values('chamber_id', 'sump_id', 'reservoir_id').annotate(last=Max('measured_at'))
    newest = {}
    for group in groups:
        log = (readings.filter(chamber_id=group['chamber_id'], sump_id=group['sump_id'], reservoir_id=group['reservoir_id'],
                               measured_at=group['last'])
               .select_related('parameter_type', 'chamber__sump', 'sump', 'reservoir').order_by('-pk').first())
        if group['chamber_id']:
            key = ('chamber', group['chamber_id'])
        elif group['sump_id']:
            key = ('sump', group['sump_id'])
        elif group['reservoir_id']:
            key = ('reservoir', group['reservoir_id'])
        else:
            key = ('display', None)
        newest[key] = log
    return newest


def level_json(log):
    """A place's newest level for the API, or None when it has never been read."""
    if log is None:
        return None
    return {'value': float(log.value), 'formatted_value': log.formatted_value, 'unit': log.parameter_type.unit,
            'status': log.status, 'measured_at': log.measured_at.isoformat(), 'reading_id': log.pk}


def place_view(log):
    """The water level test as seen from one place: its name says where, its range is that place's own levels.
    Alerts and their pages show it like any other test. It can't be saved."""
    import copy
    from decimal import Decimal

    from .conversions import convert_value
    test, place = log.parameter_type, log.place
    unit = test.unit or 'mm'

    def in_unit(mm):
        return Decimal(str(round(convert_value(float(mm), 'mm', unit), 4)))
    view = copy.copy(test)
    view.name = f"{test.name} · {log.place_label}"
    view.min_ideal = in_unit(place.level_low_mm) if place.level_low_mm is not None else test.min_ideal
    view.max_ideal = in_unit(place.level_high_mm) if place.level_high_mm is not None else test.max_ideal
    view.low_limit = view.high_limit = None
    view.is_system_view = True
    return view


def level_problems(tank):
    """Places in a tank whose newest water level is outside their own levels, shaped like the alerts' other items."""
    found = []
    for (kind, pk), log in latest_levels(tank).items():
        if kind == 'display' or log.status == 'optimal':
            continue  # the display's level is judged with the tank's other tests
        found.append({'param': place_view(log), 'log': log, 'critical': False, 'tank': tank, 'place_key': f"{kind}:{pk}"})
    return found


def sparkline(log, hours=24, width=120, height=28):
    """SVG polyline points for a place's last day of levels, one point a minute. '' with fewer than two points."""
    from datetime import timedelta

    from django.utils import timezone

    from . import charting
    readings = ParameterLog.everywhere.filter(
        parameter_type_id=log.parameter_type_id, tank_id=log.tank_id, chamber_id=log.chamber_id, sump_id=log.sump_id,
        reservoir_id=log.reservoir_id, measured_at__gte=timezone.now() - timedelta(hours=hours))
    chart = charting.points(readings, 2)
    values, stamps = chart['values'], chart['timestamps']
    if len(values) < 2:
        return ''
    low, high = min(values), max(values)
    spread = (high - low) or 1
    start, span = stamps[0], (stamps[-1] - stamps[0]) or 1
    return ' '.join(f"{(s - start) / span * width:.1f},{height - 2 - (v - low) / spread * (height - 4):.1f}"
                    for s, v in zip(stamps, values))


def spots(tank):
    """Everything the tank page needs to show and log water levels at each place, by (kind, id).
    Without a water level test there are none; until a level has been logged it makes no queries."""
    level = ParameterType.objects.filter(code=LEVEL_CODE).first()
    if level is None:
        return None
    newest = latest_levels(tank)
    return {'test': level, 'newest': newest}


def spot(levels, kind, obj=None):
    """One place's level chip: its newest reading, a sparkline and what the log form posts."""
    if not levels:
        return None
    log = levels['newest'].get((kind, obj.pk if obj is not None else None))
    return {'kind': kind, 'id': obj.pk if obj is not None else '', 'log': log, 'unit': levels['test'].unit,
            'spark': sparkline(log) if log else '',
            'low': getattr(obj, 'level_low_mm', None), 'high': getattr(obj, 'level_high_mm', None)}
