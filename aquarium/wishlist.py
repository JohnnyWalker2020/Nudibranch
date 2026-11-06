"""Wishlist logic: fit checks against a tank, moving items into a plan, and marking them bought."""
from django.db import transaction
from django.utils import timezone

from .compatibility import check_stock, tank_stock
from .models import PlannedItem, Tank, WishlistItem
from .planner import create_tracked_record

PRIORITY_ORDER = {'must': 0, 'want': 1, 'someday': 2}


def primary_tank():
    current = Tank.objects.filter(is_archived=False)
    return current.filter(is_primary=True).first() or current.first()


def wanted_items():
    items = WishlistItem.objects.filter(status='wanted').select_related(
        'species', 'tank', 'planned_item__plan')
    return sorted(items, key=lambda i: (PRIORITY_ORDER.get(i.priority, 9), i.name.lower()))


def fit_summary(items, default=None):
    """
    Adds .target_tank and .fit_warnings to each livestock item (what buying just that item would
    raise), and returns the extra issues from buying everything on the list for each tank.
    """
    default = default or primary_tank()
    by_tank = {}
    stock_cache = {}
    for item in items:
        item.target_tank = item.tank or default
        item.fit_warnings = []
        tank = item.target_tank
        if item.kind != 'livestock' or item.species is None or tank is None:
            continue
        if tank.pk not in stock_cache:
            current = tank_stock(tank)
            stock_cache[tank.pk] = (current, {w['title'] for w in check_stock(current, tank.volume_gallons)})
        current, existing = stock_cache[tank.pk]
        item.fit_warnings = [
            w for w in check_stock(current + [(item.species, item.quantity)], tank.volume_gallons)
            if w['title'] not in existing and w['level'] != 'info'
        ]
        by_tank.setdefault(tank.pk, {'tank': tank, 'items': []})['items'].append(item)

    combined = []
    for group in by_tank.values():
        tank = group['tank']
        if len(group['items']) < 2:
            continue
        current, existing = stock_cache[tank.pk]
        singles = {w['title'] for item in group['items'] for w in item.fit_warnings}
        everything = current + [(item.species, item.quantity) for item in group['items']]
        extra = [w for w in check_stock(everything, tank.volume_gallons)
                 if w['title'] not in existing and w['title'] not in singles and w['level'] != 'info']
        if extra:
            combined.append({'tank': tank, 'warnings': extra})
    return combined


@transaction.atomic
def add_to_plan(item, plan):
    """Copies a wishlist item into a plan. It stays on the list, marked as planned."""
    item = WishlistItem.objects.select_for_update().get(pk=item.pk)
    if item.status != 'wanted' or item.planned_item_id:
        return None
    planned = PlannedItem.objects.create(
        plan=plan, kind=item.kind, species=item.species, name=item.name, quantity=item.quantity,
        unit_cost=item.est_price, category=item.category, wattage=item.wattage, max_flow_gph=item.max_flow_gph,
    )
    item.planned_item = planned
    item.save(update_fields=['planned_item'])
    plan.save(update_fields=['updated_at'])
    return planned


@transaction.atomic
def mark_bought(item, tank, *, quarantine=False):
    """Adds the item to a tank's tracked records and moves it to the bought list. Safe to call twice."""
    item = WishlistItem.objects.select_for_update().get(pk=item.pk)
    if item.status != 'wanted' or item.planned_item_id:
        return False
    create_tracked_record(
        tank, kind=item.kind, name=item.name, species=item.species, quantity=item.quantity,
        category=item.category, wattage=item.wattage, max_flow_gph=item.max_flow_gph, quarantine_fish=quarantine,
        unit_price=item.est_price,
    )
    item.status = 'acquired'
    item.tank = tank
    item.acquired_at = timezone.now()
    item.save(update_fields=['status', 'tank', 'acquired_at'])
    return True
