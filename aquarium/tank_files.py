"""Export a tank's setup to a YAML file, and import one back as a new tank.

A tank file holds the setup, not the history: the tank, its sumps and chambers, plumbing, equipment and where it sits,
living animals and their categories, target ranges, routines, and dosing / ATO containers. Water tests, logs and photos
stay out (backups and the CSV downloads cover those). Prices are left out unless asked for.

Importing never changes anything that exists: it always makes a new tank. It's checked first with a dry run that's rolled
back, so a bad file changes nothing.
"""
import datetime
from decimal import Decimal

import yaml
from django.core.exceptions import ValidationError
from django.db import models, transaction
from django.utils import timezone

from .models import (
    Animal, AnimalGroup, DosingReservoir, Equipment, MaintenanceRoutine, ParameterTarget, ParameterType, PlumbingRun,
    Sump, SumpChamber, Tank,
)

FORMAT_KEY = 'nudibranch_tank'
FORMAT_VERSION = 1
MAX_FILE_BYTES = 1024 * 1024

# Never written or read, whatever the model has.
_ALWAYS_SKIP = {'id', 'created_at', 'paid', 'photo', 'custom_icon', 'last_completed', 'is_primary', 'tank', 'sump',
                'chamber', 'substrate_product', 'parameter_type', 'groups', 'equipment'}
_PRICE_FIELDS = {'paid'}


_COUNT_LABELS = {}  # friendly names for the import preview, set at the bottom


class TankFileError(Exception):
    """The file can't be used. The message is for the person importing it."""


# ---------- shared helpers ----------

def _fields(model, prices=False):
    """The plain fields a tank file carries for this model: editable, not relations, not files."""
    names = []
    for f in model._meta.concrete_fields:
        if f.name in _PRICE_FIELDS and prices:
            names.append(f.name)
            continue
        if f.name in _ALWAYS_SKIP or not f.editable or f.is_relation or isinstance(f, (models.FileField, models.AutoField)):
            continue
        names.append(f.name)
    return names


def _plain(value):
    """A model value as something YAML writes cleanly."""
    if isinstance(value, Decimal):
        return int(value) if value == value.to_integral_value() else float(value)
    if isinstance(value, datetime.datetime):
        return timezone.localtime(value).isoformat(timespec='minutes') if timezone.is_aware(value) else value.isoformat()
    if isinstance(value, (datetime.date, datetime.time)):
        return value.isoformat()
    return value


def _dump_obj(obj, prices=False, skip=()):
    data = {}
    for name in _fields(type(obj), prices):
        if name in skip:
            continue
        value = getattr(obj, name)
        if value in (None, '', [], {}):
            continue  # leave blanks out to keep the file short; the model default fills them back in
        data[name] = _plain(value)
    # The name (or title) first, so each entry reads naturally.
    first = next((k for k in ('name', 'title') if k in data), None)
    return {first: data.pop(first), **data} if first else data


# ---------- export ----------

def export_tank(tank, prices=False):
    """The tank's setup as a dict, ready for yaml."""
    equipment = list(tank.equipment.select_related('sump', 'chamber').order_by('category', 'name'))
    extra = tank.substrate_product
    if extra and extra not in equipment:
        equipment.append(extra)  # the substrate product isn't always placed in the tank

    def location(eq):
        if eq.tank_id != tank.id:
            return None
        if eq.chamber_id:
            return {'sump': eq.chamber.sump.name, 'chamber': eq.chamber.position}
        if eq.sump_id:
            return {'sump': eq.sump.name}
        return 'display'

    tank_data = _dump_obj(tank, prices, skip={'icon_choice'} if tank.icon_choice == 'custom' else ())
    if tank.substrate_product:
        tank_data['substrate_product'] = tank.substrate_product.name

    animals = [a for a in tank.animals.prefetch_related('groups').order_by('name') if a.status not in Animal.GONE_STATUSES]
    used_groups = {g.pk: g for a in animals for g in a.groups.all()}

    data = {
        FORMAT_KEY: FORMAT_VERSION,
        'exported': timezone.localdate().isoformat(),
        'tank': tank_data,
        'sumps': [{**_dump_obj(s, prices),
                   'chambers': [_dump_obj(c, prices) for c in s.chambers.all()]} for s in tank.sumps.all()],
        'plumbing': [_dump_obj(r, prices) for r in tank.plumbing_runs.all()],
        'equipment': [{**_dump_obj(eq, prices), 'location': location(eq)} for eq in equipment],
        'categories': [_dump_obj(g, prices) for g in sorted(used_groups.values(), key=lambda g: g.position)],
        'livestock': [{**_dump_obj(a, prices), 'categories': [g.name for g in a.groups.all()]} for a in animals],
        'targets': [{'parameter': t.parameter_type.code or t.parameter_type.name, **_dump_obj(t, prices)}
                    for t in tank.parameter_targets.select_related('parameter_type')],
        'routines': [{**_dump_obj(r, prices), 'equipment': [e.name for e in r.equipment.all()]}
                     for r in tank.routines.prefetch_related('equipment')],
        'reservoirs': [{**_dump_obj(r, prices), 'current_level': r.level_now} for r in tank.reservoirs.all()],  # what's in it today
    }
    # Leave empty sections out.
    return {k: v for k, v in data.items() if v not in ([], None)}


def export_yaml(tank, prices=False):
    header = (f"# Nudibranch tank file: {tank.name}\n"
              "# The setup only: no water tests, logs or photos. Import it on the Tanks page to make a new tank.\n"
              "# Units are stored beside each number (dimension_unit, head_height_unit...). Volumes are US gallons.\n")
    body = yaml.safe_dump(export_tank(tank, prices), sort_keys=False, allow_unicode=True, width=120)
    return header + body


# ---------- import ----------

def parse(text):
    """The file as a dict, or TankFileError. Refuses YAML aliases, so a crafted file can't balloon."""
    if len(text.encode('utf-8')) > MAX_FILE_BYTES:
        raise TankFileError("That file is over 1 MB, which is far bigger than any tank file.")
    try:
        if any(isinstance(e, yaml.AliasEvent) for e in yaml.parse(text, Loader=yaml.SafeLoader)):
            raise TankFileError("The file uses YAML aliases (*name), which tank files don't need. Please remove them.")
        data = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        mark = getattr(exc, 'problem_mark', None)
        where = f" (line {mark.line + 1})" if mark else ""
        raise TankFileError(f"That isn't valid YAML{where}.") from exc
    if not isinstance(data, dict) or FORMAT_KEY not in data:
        raise TankFileError("That doesn't look like a Nudibranch tank file (it should start with nudibranch_tank: 1).")
    if data.get(FORMAT_KEY) != FORMAT_VERSION:
        raise TankFileError(f"This is a version {data.get(FORMAT_KEY)} tank file. This app reads version {FORMAT_VERSION}.")
    if not isinstance(data.get('tank'), dict) or not data['tank'].get('name'):
        raise TankFileError("The file has no tank, or the tank has no name.")
    return data


class _Importer:
    def __init__(self, data):
        self.data = data
        self.notes = []          # things skipped or changed, shown in the preview
        self.counts = {}
        self.equipment_by_name = {}

    def _list(self, key):
        value = self.data.get(key) or []
        if not isinstance(value, list):
            raise TankFileError(f"'{key}' should be a list.")
        for item in value:
            if not isinstance(item, dict):
                raise TankFileError(f"Every entry under '{key}' should be a set of name: value lines.")
        return value

    def _build(self, model, raw, label, **links):
        """A saved object from the file's values, checked by the model's own rules."""
        allowed = set(_fields(model, prices=True))
        obj = model(**links)
        for key, value in raw.items():
            if key not in allowed:
                continue
            field = model._meta.get_field(key)
            try:
                if isinstance(value, float):
                    value = repr(value)  # 63.1 stays 63.1, not a long binary fraction
                setattr(obj, key, field.to_python(value) if value is not None else None)
            except ValidationError as exc:
                raise TankFileError(f"{label}: {key} {'; '.join(exc.messages)}") from exc
        # Empty lists (a routine with no checklist) are what the app itself saves, so they aren't "blank" errors.
        empty_lists = [f.name for f in model._meta.concrete_fields if getattr(obj, f.attname, None) in ([], {})]
        try:
            obj.full_clean(exclude=[n for n in ('tank', 'sump', 'chamber', 'parameter_type') if n not in links] + empty_lists,
                           validate_unique=False)
        except ValidationError as exc:
            problems = '; '.join(f"{k}: {', '.join(v)}" for k, v in exc.message_dict.items())
            raise TankFileError(f"{label}: {problems}") from exc
        obj.save()
        label_plural = _COUNT_LABELS.get(model, model._meta.verbose_name_plural)
        self.counts[label_plural] = self.counts.get(label_plural, 0) + 1
        return obj

    def run(self):
        raw_tank = dict(self.data['tank'])
        name = str(raw_tank['name'])[:100]
        if Tank.objects.filter(name__iexact=name).exists():
            new_name = f"{name} (imported)"[:100]
            self.notes.append(f"You already have a tank called {name}, so this one is {new_name}.")
            raw_tank['name'] = new_name
        tank = self._build(Tank, raw_tank, 'Tank', is_primary=not Tank.objects.filter(is_archived=False).exists())
        self.tank = tank

        sumps, chambers = {}, {}
        for raw in self._list('sumps'):
            sump = self._build(Sump, raw, f"Sump {raw.get('name', '')}".strip(), tank=tank)
            sumps[sump.name] = sump
            for craw in raw.get('chambers') or []:
                if isinstance(craw, dict):
                    c = self._build(SumpChamber, craw, f"{sump.name} chamber", sump=sump)
                    chambers[(sump.name, c.position)] = c

        for raw in self._list('plumbing'):
            self._build(PlumbingRun, raw, 'Plumbing run', tank=tank)

        for raw in self._list('equipment'):
            loc = raw.get('location')
            links = {}
            if loc == 'display':
                links = {'tank': tank}
            elif isinstance(loc, dict) and loc.get('sump') in sumps:
                sump = sumps[loc['sump']]
                chamber = chambers.get((sump.name, loc.get('chamber')))
                links = {'tank': tank, 'sump': sump, 'chamber': chamber}
                if loc.get('chamber') is not None and chamber is None:
                    self.notes.append(f"{raw.get('name')}: chamber #{loc.get('chamber')} isn't in {sump.name}, so it's in the sump as a whole.")
            elif loc not in (None, ''):
                self.notes.append(f"{raw.get('name')}: couldn't find where it goes, so it's in the display.")
                links = {'tank': tank}
            eq = self._build(Equipment, raw, f"Equipment {raw.get('name', '')}".strip(), **links)
            self.equipment_by_name.setdefault(eq.name, eq)

        product = raw_tank.get('substrate_product')
        if product:
            if product in self.equipment_by_name:
                tank.substrate_product = self.equipment_by_name[product]
                tank.save(update_fields=['substrate_product'])
            else:
                self.notes.append(f"Substrate product {product} wasn't in the file's equipment, so it's left blank.")

        groups = {}
        for raw in self._list('categories'):
            existing = AnimalGroup.objects.filter(name__iexact=str(raw.get('name', ''))).first()
            if existing:
                groups[existing.name.lower()] = existing  # use yours rather than making a twin
            elif raw.get('name'):
                groups[str(raw['name']).lower()] = self._build(AnimalGroup, raw, f"Category {raw['name']}")

        for raw in self._list('livestock'):
            animal = self._build(Animal, raw, f"Animal {raw.get('name', '')}".strip(), tank=tank)
            for gname in raw.get('categories') or []:
                group = groups.get(str(gname).lower()) or AnimalGroup.objects.filter(name__iexact=str(gname)).first()
                if group is None:
                    group = self._build(AnimalGroup, {'name': str(gname)}, f"Category {gname}")
                    groups[group.name.lower()] = group
                animal.groups.add(group)

        for raw in self._list('targets'):
            key = str(raw.get('parameter', ''))
            ptype = ParameterType.objects.filter(code=key).first() or ParameterType.objects.filter(name__iexact=key).first()
            if ptype is None:
                self.notes.append(f"No parameter called {key} here, so its target range was skipped.")
                continue
            self._build(ParameterTarget, raw, f"Target for {key}", tank=tank, parameter_type=ptype)

        for raw in self._list('routines'):
            routine = self._build(MaintenanceRoutine, raw, f"Routine {raw.get('title', '')}".strip(), tank=tank)
            for ename in raw.get('equipment') or []:
                eq = self.equipment_by_name.get(ename)
                if eq:
                    routine.equipment.add(eq)
                else:
                    self.notes.append(f"Routine {routine.title}: {ename} isn't in the file's equipment, so it isn't linked.")

        for raw in self._list('reservoirs'):
            self._build(DosingReservoir, raw, f"Container {raw.get('name', '')}".strip(), tank=tank)
        return tank


def import_tank(data, dry_run=False):
    """Makes the tank. Returns (tank or None, counts, notes). With dry_run, checks everything and keeps nothing."""
    importer = _Importer(data)
    with transaction.atomic():
        tank = importer.run()
        if dry_run:
            transaction.set_rollback(True)
            tank = None
    return tank, importer.counts, importer.notes


_COUNT_LABELS.update({
    Tank: 'tank', Sump: 'sumps', SumpChamber: 'sump chambers', PlumbingRun: 'plumbing runs', Equipment: 'equipment',
    AnimalGroup: 'new categories', Animal: 'livestock entries', ParameterTarget: 'target ranges',
    MaintenanceRoutine: 'routines', DosingReservoir: 'dosing and ATO containers',
})
