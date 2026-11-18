"""The tanks API: GET /api/tanks/ (a short list) and GET /api/tanks/<id or name>/ (the whole system).

The detail matches the Tank system page: the display tank, each sump and how it's divided into chambers,
plumbing, flow and lighting, with equipment listed where it sits. Notes and prices are left out.
"""
from django.http import JsonResponse
from django.urls import reverse

from .active import default_tank
from . import places
from .models import Equipment, Tank


def _number(value, places=1):
    return round(float(value), places) if value is not None else None


def _dimensions(vessel):
    if not vessel.has_dimensions:
        return None
    return {'width': _number(vessel.width), 'depth': _number(vessel.depth), 'height': _number(vessel.height),
            'unit': vessel.dimension_unit}


def _volume_from(vessel):
    """'dimensions' when the volume is worked out from the size, 'typed' when it was entered by hand."""
    return 'dimensions' if vessel.has_dimensions and not vessel.capacity_is_manual else 'typed'


def _equipment(items):
    return [{'id': eq.id, 'name': eq.name, 'category': eq.category, 'status': eq.status} for eq in items]


def _water(tank):
    return {
        'tank_gallons': _number(tank.volume_gallons),
        'display_gallons': tank.display_water_gallons,
        'inside_gallons': float(round(tank.inside_sump_gallons, 1)),
        'sumps_gallons': float(round(tank.below_sump_gallons, 1)),
        'plumbing_gallons': float(round(tank.plumbing_gallons, 2)),
        'total_gallons': tank.total_system_gallons,
        'total_liters': tank.total_system_liters,
    }


def _tanks():
    return (Tank.objects.filter(is_archived=False).order_by('position', 'pk')
            .prefetch_related('sumps__chambers', 'plumbing_runs', 'animals', 'equipment'))


def _find(identifier):
    """A current tank by ID or name (any case). Archived tanks don't take new readings, so they aren't found."""
    text = str(identifier).strip()
    tanks = _tanks()
    if text.isdecimal():
        tank = tanks.filter(pk=int(text)).first()
        if tank:
            return tank
    return tanks.filter(name__iexact=text).first()


def tank_summary(tank, request=None):
    sumps = list(tank.sumps.all())
    url = reverse('api_tank_detail', args=[tank.pk])
    return {
        'id': tank.id,
        'name': tank.name,
        'is_primary': tank.is_primary,
        'stage': tank.stage,
        'has_sump': bool(sumps),
        'sump_count': len(sumps),
        'total_gallons': tank.total_system_gallons,
        'total_liters': tank.total_system_liters,
        'living_animals': tank.living_animal_count,
        'url': request.build_absolute_uri(url) if request else url,
    }


def _targets(place):
    return {'low_mm': _number(place.level_low_mm), 'high_mm': _number(place.level_high_mm)}


def tank_detail(tank):
    levels = places.latest_levels(tank)
    placed = list(Equipment.objects.filter(tank=tank).order_by('category', 'name'))
    by_sump, by_chamber, in_display = {}, {}, []
    for eq in placed:
        if eq.chamber_id:
            by_chamber.setdefault(eq.chamber_id, []).append(eq)
        elif eq.sump_id:
            by_sump.setdefault(eq.sump_id, []).append(eq)
        else:
            in_display.append(eq)

    sumps = []
    for sump in tank.sumps.all():
        chambers = list(sump.chambers.all())
        sumps.append({
            'id': sump.id,
            'name': sump.name,
            'location': sump.location,
            'volume_gallons': _number(sump.volume_gallons),
            'volume_liters': sump.volume_liters,
            'volume_from': _volume_from(sump),
            'fill_percent': _number(sump.fill_percent),
            'dimensions': _dimensions(sump),
            'overflow': None if sump.is_inside else (sump.overflow_label or None),
            'head_height_ft': _number(sump.head_height_ft),
            'chamber_share_total': sump.chamber_share_total if chambers else None,
            'level': places.level_json(levels.get(('sump', sump.id))),
            'level_targets': _targets(sump),
            'equipment': _equipment(by_sump.get(sump.id, [])),
            'chambers': [{
                'id': c.id,
                'position': c.position,
                'name': c.plain_name,  # without the app's emoji
                'type': c.chamber_type,
                'share_percent': _number(c.share_percent),
                'volume_gallons': c.volume_gallons,
                'level': places.level_json(levels.get(('chamber', c.id))),
                'level_targets': _targets(c),
                'equipment': _equipment(by_chamber.get(c.id, [])),
            } for c in chambers],
        })

    runs = list(tank.plumbing_runs.all())
    flow = tank.flow_summary()
    light = tank.light_summary()
    return {
        'id': tank.id,
        'name': tank.name,
        'is_primary': tank.is_primary,
        'stage': tank.stage,
        'living_animals': tank.living_animal_count,
        'water': _water(tank),
        'display': {
            'dimensions': _dimensions(tank),
            'volume_from': _volume_from(tank),
            'fill_percent': _number(tank.fill_percent),
            'substrate': tank.substrate_amount_label or None,
            'live_rock': tank.live_rock_label or None,
            'level': places.level_json(levels.get(('display', None))),
            'equipment': _equipment(in_display),
        },
        'has_sump': bool(sumps),
        'sumps': sumps,
        'reservoirs': [{
            'id': r.id, 'name': r.name, 'type': r.reservoir_type, 'capacity': _number(r.capacity, 2), 'unit': r.unit,
            'level': places.level_json(levels.get(('reservoir', r.id))), 'level_targets': _targets(r),
        } for r in tank.reservoirs.all().order_by('reservoir_type', 'name')],
        'plumbing': {
            'total_feet': float(tank.plumbing_feet),
            'gallons': float(round(tank.plumbing_gallons, 2)),
            'runs': [{'id': r.id, 'name': r.display_name, 'pipe': r.size_label, 'length': _number(r.length),
                      'unit': r.length_unit, 'count': r.count, 'gallons': round(r.gallons, 2)} for r in runs],
        },
        'flow': {key: flow[key] for key in ('return_gph', 'wavemaker_gph', 'total_gph', 'return_turnover',
                                            'circulation_turnover', 'return_status', 'circulation_status')},
        'lighting': {'lights': len(light['lights']), 'watts_now': light['watts_now'], 'watts_full': light['watts_full']},
    }


def api_tanks(request):
    """GET /api/tanks/ - your current tanks, so a device or script can find the tank to send readings to."""
    tanks = list(_tanks())
    primary = default_tank()  # where readings without a tank go
    return JsonResponse({'count': len(tanks), 'primary_tank_id': primary.pk if primary else None,
                         'tanks': [tank_summary(t, request) for t in tanks]}, json_dumps_params={'ensure_ascii': False})


def api_tank_detail(request, identifier):
    """GET /api/tanks/<id or name>/ - one tank's whole system, as the Tank system page shows it."""
    tank = _find(identifier)
    if tank is None:
        return JsonResponse({'error': f"Unknown tank '{identifier}'."}, status=404)
    return JsonResponse(tank_detail(tank), json_dumps_params={'ensure_ascii': False})
