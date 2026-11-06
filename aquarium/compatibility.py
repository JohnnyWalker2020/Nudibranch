"""
Stocking compatibility rules. These are rough hobby rules of thumb meant to prompt a closer look,
not guarantees: individual animals, tank layout and adding order all matter.
"""
from collections import Counter

from .models import SpeciesCatalog

# Keeping two different species from one of these genera usually means fighting.
RIVAL_GENERA = {
    'Amphiprion': 'clownfish',
    'Zebrasoma': 'Zebrasoma tangs',
    'Acanthurus': 'Acanthurus tangs',
    'Ctenochaetus': 'bristle-tooth tangs',
    'Centropyge': 'dwarf angels',
    'Pseudochromis': 'dottybacks',
    'Synchiropus': 'dragonets',
}
SHRIMP_HUNTERS = {'Pterois', 'Dendrochirus', 'Echidna', 'Neocirrhites', 'Oxycirrhites', 'Paracirrhites',
                  'Rhinecanthus', 'Odonus', 'Serranus', 'Diodon', 'Novaculichthys', 'Choerodon'}
POD_EATERS = {'Synchiropus'}

BIOLOAD_WARNING = 0.25   # inches of adult fish per gallon
BIOLOAD_DANGER = 0.5

ACTIVE_STATUSES = ('healthy', 'quarantine', 'monitoring')


def _genus(entry):
    return (entry.species or '').split(' ')[0]


def catalog_match(animal, catalog=None):
    """Best catalog entry for a tracked animal (by exact common or scientific name), or None."""
    if catalog is not None:
        return catalog.get(animal.name.lower()) or catalog.get((animal.species or '').lower())
    match = SpeciesCatalog.objects.filter(name__iexact=animal.name).first()
    if match is None and animal.species:
        match = SpeciesCatalog.objects.filter(species__iexact=animal.species).first()
    return match


def tank_stock(tank):
    """[(catalog entry, quantity)] for the living animals in a tank. Unmatched animals are skipped."""
    catalog = {}
    for entry in SpeciesCatalog.objects.all():
        catalog[entry.name.lower()] = entry
        if entry.species and not entry.species.endswith('sp.'):
            catalog.setdefault(entry.species.lower(), entry)
    stock = []
    for animal in tank.animals.filter(status__in=ACTIVE_STATUSES):
        entry = catalog_match(animal, catalog)
        if entry is not None:
            stock.append((entry, animal.count))
    return stock


def bioload(stock, volume_gallons):
    """Adult fish inches per gallon, or None when it can't be worked out."""
    volume = float(volume_gallons or 0)
    if not volume:
        return None
    inches = sum(float(e.max_size_inches or 0) * qty for e, qty in stock if e.category == 'fish')
    return round(inches / volume, 2) if inches else 0.0


def check_stock(stock, volume_gallons, *, reef=True):
    """
    Returns warnings for a list of (catalog entry, quantity), most serious first.
    Each warning is {'level': 'danger'|'warning'|'info', 'title': str, 'detail': str}.
    """
    volume = float(volume_gallons or 0)
    out = []

    def add(level, title, detail):
        out.append({'level': level, 'title': title, 'detail': detail})

    merged = {}
    for entry, qty in stock:
        merged[entry.pk] = (entry, merged.get(entry.pk, (entry, 0))[1] + qty)
    entries = list(merged.values())

    for entry, _qty in entries:
        if entry.min_tank_gallons and volume and volume < entry.min_tank_gallons:
            level = 'danger' if volume < entry.min_tank_gallons * 0.7 else 'warning'
            add(level, f"{entry.name} needs more room",
                f"Usually kept in {entry.min_tank_gallons}+ gallons. This display is {volume:g} gallons.")

    genera = {}
    for entry, _qty in entries:
        genera.setdefault(_genus(entry), []).append(entry)
    for genus, label in RIVAL_GENERA.items():
        members = genera.get(genus, [])
        if len(members) > 1:
            names = ', '.join(e.name for e in members)
            add('warning', f"Mixing {label} often leads to fighting", f"{names}. Consider keeping just one species.")

    for entry, qty in entries:
        if entry.suggested_group == 'Clownfish Pair' and qty > 2:
            add('warning', f"{qty} {entry.name} is more than a pair",
                "Clownfish groups usually fight down to a pair unless the tank is large.")

    tangs = [e for e, _ in entries if 'Tang' in e.name]
    if len(tangs) > 1 and volume and volume < 180:
        add('warning', "Multiple tangs in a smaller system",
            f"{', '.join(e.name for e in tangs)} may squabble. Extra space helps, and adding them together can too.")

    aggressive = [e for e, _ in entries if e.temperament == 'aggressive' and e.category == 'fish']
    peaceful = [e for e, _ in entries if e.temperament == 'peaceful' and e.category == 'fish']
    if aggressive and peaceful:
        add('warning', "Aggressive fish with peaceful fish",
            f"{', '.join(e.name for e in aggressive)} may bully {', '.join(e.name for e in peaceful[:4])}"
            f"{' and others' if len(peaceful) > 4 else ''}. Add peaceful fish first.")

    shrimp = [e for e, _ in entries if 'Shrimp' in e.name]
    hunters = [e for e, _ in entries if _genus(e) in SHRIMP_HUNTERS]
    if shrimp and hunters:
        add('warning', "Shrimp may become a snack",
            f"{', '.join(e.name for e in hunters)} can eat {', '.join(e.name for e in shrimp)}.")

    seahorses = [e for e, _ in entries if _genus(e) == 'Hippocampus']
    if seahorses and len([e for e, _ in entries if e.category == 'fish']) > len(seahorses):
        add('warning', "Seahorses do best on their own",
            "Faster fish usually out-compete them for food. A dedicated tank is the safer choice.")

    if reef:
        invertebrate_life = [e for e, _ in entries if e.category in ('coral', 'invert', 'cleanup_crew')]
        for entry, _qty in entries:
            if entry.reef_safe == 'No':
                add('danger', f"{entry.name} is not reef safe",
                    "It is likely to eat or damage corals and invertebrates.")
            elif entry.reef_safe == 'With Caution' and invertebrate_life:
                add('info', f"{entry.name}: reef safe with caution", entry.notes or "Keep an eye on nearby corals and inverts.")

    for entry, _qty in entries:
        if _genus(entry) in POD_EATERS:
            add('warning', f"{entry.name} needs a mature pod population",
                "Plan on a well-established tank or a refugium, or confirm it eats frozen food.")
        elif entry.care_level == 'Expert':
            add('info', f"{entry.name} is an expert-level animal", entry.notes or "Research its needs before buying.")

    load = bioload([(e, q) for e, q in entries], volume)
    if load is not None and load > BIOLOAD_DANGER:
        add('danger', "Heavy fish load",
            f"About {load} inches of adult fish per gallon. A rough comfortable limit is {BIOLOAD_WARNING}.")
    elif load is not None and load > BIOLOAD_WARNING:
        add('warning', "Fish load is on the high side",
            f"About {load} inches of adult fish per gallon. Plan for strong filtration and regular water changes.")

    order = {'danger': 0, 'warning': 1, 'info': 2}
    out.sort(key=lambda w: order[w['level']])
    return out


def warnings_for_addition(species, tank, quantity=1):
    """Warnings a new addition introduces to a tank (ignores issues that were already there)."""
    if tank is None:
        return []
    reef = True
    current = tank_stock(tank)
    before = {w['title'] for w in check_stock(current, tank.volume_gallons, reef=reef)}
    after = check_stock(current + [(species, quantity)], tank.volume_gallons, reef=reef)
    return [w for w in after if w['title'] not in before]


def count_levels(warnings):
    return Counter(w['level'] for w in warnings)
