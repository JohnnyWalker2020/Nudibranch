"""Analyses a planned system and turns it into tracked records."""
from django.db import transaction
from django.utils import timezone

from .calculators import estimate_flow_gph, turnover_summary
from .compatibility import ACTIVE_STATUSES, bioload, check_stock, tank_stock
from .models import AnimalGroup, Animal, AppSettings, Equipment, Sump, Tank
from .power import DAYS_PER_MONTH, TYPICAL_HOURS, daily_kwh, power_summary

RETURN_HEAD_LOSS_PERCENT = 25  # planning assumption for head height and plumbing losses
HEATER_WATTS_PER_GALLON = (3.0, 5.0)

# Gear a system normally needs, by planning goal.
ESSENTIALS = [
    ('lighting', 'Lighting', ('mixed', 'soft', 'lps', 'sps', 'nano')),
    ('heater', 'Heater', ('mixed', 'soft', 'lps', 'sps', 'nano', 'fowlr')),
    ('wavemaker', 'Wavemaker or powerhead', ('mixed', 'soft', 'lps', 'sps', 'fowlr')),
    ('ato', 'Auto top-off', ('mixed', 'soft', 'lps', 'sps', 'nano', 'fowlr')),
]


def _display_gallons(plan):
    return float(plan.existing_tank.volume_gallons if plan.existing_tank_id else plan.volume_gallons or 0)


def _system_gallons(plan):
    if plan.existing_tank_id:
        return plan.existing_tank.total_system_gallons
    return float(plan.volume_gallons or 0) + float(plan.sump_gallons or 0)


def analyze(plan):
    """Everything the planner page shows: stock warnings, flow, heat, power, cost and missing gear."""
    items = list(plan.items.select_related('species'))
    livestock = [i for i in items if i.kind == 'livestock']
    gear = [i for i in items if i.kind == 'equipment']
    display = _display_gallons(plan)
    system = _system_gallons(plan)
    existing_tank = plan.existing_tank

    # Livestock: planned animals plus whatever already lives in the tank being planned for.
    stock = [(i.species, i.quantity) for i in livestock if i.species_id and not i.tracked]
    current_stock = tank_stock(existing_tank) if existing_tank else []
    all_stock = current_stock + stock + [(i.species, i.quantity) for i in livestock if i.species_id and i.tracked and not existing_tank]
    reef = plan.goal != 'fowlr'
    warnings = check_stock(all_stock, display, reef=reef)
    unmatched = [i.name for i in livestock if not i.species_id]
    load = bioload(all_stock, display)

    # Equipment already on an existing tank counts toward the totals.
    real_gear = []
    if existing_tank:
        real_gear = list(existing_tank.equipment.exclude(status='offline'))
    categories = {i.category for i in gear} | {e.category for e in real_gear}

    return_gph = sum(estimate_flow_gph(i.max_flow_gph, 100, RETURN_HEAD_LOSS_PERCENT) * i.quantity
                     for i in gear if i.category == 'return_pump' and i.max_flow_gph and not (existing_tank and i.tracked))
    wave_gph = sum(float(i.max_flow_gph) * i.quantity
                   for i in gear if i.category == 'wavemaker' and i.max_flow_gph and not (existing_tank and i.tracked))
    for eq in real_gear:
        flow = eq.estimated_flow_gph
        if flow and eq.category == 'return_pump':
            return_gph += flow
        elif flow and eq.category == 'wavemaker':
            wave_gph += flow
    flow = turnover_summary(display, system, return_gph, wave_gph)

    heater_watts = (sum((i.wattage or 0) * i.quantity for i in gear if i.category == 'heater' and not (existing_tank and i.tracked))
                    + sum(e.wattage or 0 for e in real_gear if e.category == 'heater'))
    heater_per_gal = round(heater_watts / system, 1) if system and heater_watts else None
    if heater_per_gal is None:
        heater_status = 'none'
    elif heater_per_gal < HEATER_WATTS_PER_GALLON[0]:
        heater_status = 'low'
    elif heater_per_gal > HEATER_WATTS_PER_GALLON[1] * 2:
        heater_status = 'high'
    else:
        heater_status = 'ok'

    settings_obj = AppSettings.load()
    rate = float(settings_obj.electricity_rate)
    planned_kwh = sum(daily_kwh(i.wattage, TYPICAL_HOURS.get(i.category, 24)) * i.quantity
                      for i in gear if i.wattage and not (existing_tank and i.tracked))
    existing_kwh = power_summary(existing_tank)['kwh_day'] if existing_tank else 0
    kwh_day = planned_kwh + existing_kwh

    total_cost = sum(float(i.total_cost) for i in items)
    budget = float(plan.budget) if plan.budget is not None else None

    missing = [label for key, label, goals in ESSENTIALS if plan.goal in goals and key not in categories]
    if plan.goal != 'nano' and (float(plan.sump_gallons or 0) > 0 or (existing_tank and existing_tank.sumps.exists())):
        if 'return_pump' not in categories:
            missing.insert(0, 'Return pump (you have a sump)')
        if 'skimmer' not in categories and plan.goal != 'soft':
            missing.append('Protein skimmer')

    return {
        'livestock': livestock,
        'gear': gear,
        'display_gallons': round(display, 1),
        'system_gallons': round(system, 1),
        'warnings': warnings,
        'danger_count': sum(1 for w in warnings if w['level'] == 'danger'),
        'warning_count': sum(1 for w in warnings if w['level'] == 'warning'),
        'unmatched': unmatched,
        'bioload': load,
        'flow': flow,
        'heater_watts': heater_watts,
        'heater_per_gal': heater_per_gal,
        'heater_status': heater_status,
        'heater_range': HEATER_WATTS_PER_GALLON,
        'kwh_day': round(kwh_day, 2),
        'cost_month_power': round(kwh_day * DAYS_PER_MONTH * rate, 2),
        'currency': settings_obj.currency_symbol,
        'total_cost': round(total_cost, 2),
        'budget': budget,
        'over_budget': budget is not None and total_cost > budget,
        'budget_percent': min(100, round(total_cost / budget * 100)) if budget else None,
        'missing': missing,
        'untracked_count': sum(1 for i in items if not i.tracked),
    }


def create_tracked_record(tank, *, kind, name, species=None, quantity=1, category='', wattage=None,
                          max_flow_gph=None, quarantine_fish=False, unit_price=None):
    """
    Creates the real equipment or animal record for something planned or bought. A known price is
    recorded as what you paid, which adds it to The Damage (only while costs are switched on).
    """
    price = unit_price if unit_price and AppSettings.load().costs_enabled else None
    if kind == 'equipment':
        for _ in range(quantity):
            Equipment.objects.create(
                tank=tank, name=name[:120], category=category or 'other', wattage=wattage,
                max_flow_gph=max_flow_gph, paid=price,
                flow_derate_percent=RETURN_HEAD_LOSS_PERCENT if category == 'return_pump' else 0,
            )
        return
    is_fish = species is not None and species.category == 'fish'
    notes = ''
    if species is not None:
        notes = f"Care: {species.care_level}. Diet: {species.diet}. {species.notes}".strip()
    animal = Animal.objects.create(
        name=name[:120], species=species.species if species else '', tank=tank, count=quantity,
        status='quarantine' if quarantine_fish and is_fish else 'healthy', notes=notes,
        acquired_date=timezone.localdate(), paid=price * quantity if price else None,
    )
    if species is not None and species.suggested_group:
        group, _ = AnimalGroup.objects.get_or_create(
            name=species.suggested_group, defaults={'icon': species.icon, 'color': '#0ea5e9'})
        animal.groups.add(group)


@transaction.atomic
def track_plan(plan, *, quarantine_fish=False):
    """
    Creates real records from a plan and returns the tank. Items already tracked are skipped, so
    a plan can be added to and tracked again later.
    """
    tank = plan.existing_tank or plan.tracked_tank
    if tank is None:
        tank = Tank.objects.create(
            name=plan.name[:100], width=plan.width, depth=plan.depth, height=plan.height,
            dimension_unit=plan.dimension_unit, fill_percent=plan.fill_percent,
            capacity_is_manual=plan.capacity_is_manual, volume_gallons=plan.volume_gallons,
            is_primary=not Tank.objects.filter(is_archived=False, is_primary=True).exists(), notes=plan.notes,
        )
        if float(plan.sump_gallons or 0) > 0:
            Sump.objects.create(tank=tank, name='Sump', volume_gallons=plan.sump_gallons, capacity_is_manual=True)

    for item in plan.items.filter(tracked=False).select_related('species'):
        create_tracked_record(
            tank, kind=item.kind, name=item.name, species=item.species, quantity=item.quantity,
            category=item.category, wattage=item.wattage, max_flow_gph=item.max_flow_gph,
            quarantine_fish=quarantine_fish, unit_price=item.unit_cost,
        )
        item.tracked = True
        item.save(update_fields=['tracked'])

    plan.tracked_tank = tank
    plan.save(update_fields=['tracked_tank', 'updated_at'])
    return tank
