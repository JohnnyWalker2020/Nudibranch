"""Bringing water tests in from a spreadsheet (CSV): from this app's Export, another app, or one you kept yourself.

Two steps, so nothing is saved by surprise: upload shows a preview (what will be added, what's skipped and why),
then Add saves it. Either layout works:
  one reading per row   Tank, Parameter, Value, Unit, Measured at, Notes  (Tank, Unit and Notes are optional)
  a grid                Tank, Measured at, Alkalinity (dKH), Calcium (ppm), ...  (a column per test)
A reading already logged for the same test, tank and minute is skipped, so importing a file twice is harmless.
"""
import csv
import io
import re
from collections import OrderedDict
from datetime import datetime, time, timedelta
from decimal import Decimal, InvalidOperation

from django.contrib import messages
from django.shortcuts import redirect, render
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from django.views.decorators.http import require_POST

from .active import get_active_tank
from .conversions import convert_value
from .models import ParameterLog, ParameterType, Tank, note_level_readings

MAX_BYTES = 5 * 1024 * 1024
MAX_READINGS = 20000
SESSION_KEY = 'test_import'

DATE_HEADERS = {'measured at', 'measured', 'date', 'date/time', 'date time', 'datetime', 'timestamp', 'when', 'tested',
                'tested at', 'test date', 'date tested'}
TIME_HEADERS = {'time', 'time of day'}
TANK_HEADERS = {'tank', 'system', 'aquarium'}
PARAM_HEADERS = {'parameter', 'test', 'element', 'measurement'}
VALUE_HEADERS = {'value', 'result', 'reading', 'level'}
UNIT_HEADERS = {'unit', 'units'}
NOTE_HEADERS = {'notes', 'note', 'comment', 'comments'}

# Short names people use for column headings, and what they mean
ALIASES = {
    'alk': 'alkalinity', 'kh': 'alkalinity', 'dkh': 'alkalinity', 'alkalinity (kh)': 'alkalinity',
    'ca': 'calcium', 'mg': 'magnesium', 'no3': 'nitrate', 'nitrates': 'nitrate', 'po4': 'phosphate',
    'phosphates': 'phosphate', 'temp': 'temperature', 'sal': 'salinity', 'salt': 'salinity', 'sg': 'salinity',
    'no2': 'nitrite', 'nh3': 'ammonia', 'nh4': 'ammonia', 'k': 'potassium', 'sr': 'strontium', 'i': 'iodine',
    'fe': 'iron', 'cu': 'copper', 'b': 'boron', 'ph value': 'ph',
    'level': 'water_level', 'water level': 'water_level', 'water depth': 'water_level', 'depth': 'water_level',
}
# Units that mean the same thing, written differently
SAME_UNIT = {'mg/l': 'ppm', 'mgl': 'ppm', 'µg/l': 'ppb', 'ug/l': 'ppb', '°f': 'f', 'degf': 'f', 'deg f': 'f',
             '°c': 'c', 'degc': 'c', 'deg c': 'c', 'dkh': 'dkh', 'psu': 'ppt', 'specific gravity': 'sg',
             'inch': 'in', 'inches': 'in', '"': 'in', 'centimeters': 'cm', 'millimeters': 'mm'}

SLASH_DATE = re.compile(r'^(\d{1,2})[/.\-](\d{1,2})[/.\-](\d{2,4})'
                        r'(?:[ T,]+(\d{1,2}):(\d{2})(?::(\d{2}))?\s*([AaPp]\.?[Mm]\.?)?)?$')
ISO_DATE = re.compile(r'^(\d{4})[/.\-](\d{1,2})[/.\-](\d{1,2})'
                      r'(?:[ T,]+(\d{1,2}):(\d{2})(?::(\d{2}))?\s*([AaPp]\.?[Mm]\.?)?)?$')
HEADER_UNIT = re.compile(r'^(.*?)\s*[(\[]\s*([^)\]]*)\s*[)\]]\s*$')


def _norm(text):
    return re.sub(r'\s+', ' ', (text or '').strip().strip('﻿').lower())


def _unit(text):
    u = _norm(text)
    return SAME_UNIT.get(u, u)


def _clean_cell(text):
    """Undoes the export's guard against spreadsheet formulas (a leading apostrophe)."""
    text = (text or '').strip()
    return text[1:] if text[:2] in ("'=", "'+", "'-", "'@") else text


class ParameterMatcher:
    """Finds the test a column heading or Parameter cell means: by name, code or a common short name."""
    def __init__(self):
        self.by_key = {}
        for ptype in ParameterType.objects.all():
            for key in (ptype.name, ptype.code):
                self.by_key.setdefault(_norm(key), ptype)

    def find(self, label):
        label = _norm(label)
        if not label:
            return None
        return self.by_key.get(label) or self.by_key.get(ALIASES.get(label, ''))


def converter(from_unit, ptype):
    """A function turning a value in from_unit into the test's own unit, or None if there's no known way."""
    have, want = _unit(from_unit), _unit(ptype.unit)
    if not have or have == want:
        return lambda v: v
    try:  # convert_value hands back the same number when it has no formula, so check it actually changes
        if convert_value(1.0, have, want, ptype.code) == 1.0 and convert_value(2.0, have, want, ptype.code) == 2.0:
            return None
    except (TypeError, ValueError, ZeroDivisionError):
        return None
    return lambda v: convert_value(v, have, want, ptype.code)


def parse_number(text):
    text = _clean_cell(text).replace(' ', '')
    if ',' in text and '.' not in text:
        text = text.replace(',', '.')  # 8,4 written the European way
    try:
        value = Decimal(text)
    except InvalidOperation:
        return None
    return value if value.is_finite() else None


def _clock(hour, minute, second, ampm):
    hour, minute, second = int(hour or 12), int(minute or 0), int(second or 0)
    if ampm:
        ampm = ampm.replace('.', '').lower()
        if ampm == 'pm' and hour < 12:
            hour += 12
        elif ampm == 'am' and hour == 12:
            hour = 0
    return time(hour, minute, second)


def date_order_hint(cells):
    """'day' or 'month' if the file's slashed dates give it away (a 25/03 or a 03/25), else None."""
    for cell in cells:
        m = SLASH_DATE.match(_clean_cell(cell))
        if m and int(m.group(1)) > 12:
            return 'day'
        if m and int(m.group(2)) > 12:
            return 'month'
    return None


def parse_when(text, day_first):
    """A local, timezone-aware time from the ways dates are usually written. A date alone is taken as noon."""
    text = _clean_cell(text)
    if not text:
        return None
    try:
        moment = parse_datetime(text.replace(' ', 'T', 1) if 'T' not in text else text)
    except ValueError:
        moment = None
    if moment is None:
        try:
            m = ISO_DATE.match(text)
            if m:
                y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
                moment = datetime.combine(datetime(y, mo, d).date(), _clock(*m.group(4, 5, 6, 7)))
            else:
                m = SLASH_DATE.match(text)
                if not m:
                    return None
                a, b, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
                y += 2000 if y < 100 else 0
                d, mo = (a, b) if day_first else (b, a)
                moment = datetime.combine(datetime(y, mo, d).date(), _clock(*m.group(4, 5, 6, 7)))
        except ValueError:
            return None
    if timezone.is_naive(moment):
        moment = timezone.make_aware(moment)
    return moment


def read_csv(raw):
    """Rows of cells from uploaded bytes, whatever the separator (comma, semicolon or tab)."""
    for encoding in ('utf-8-sig', 'cp1252', 'latin-1'):
        try:
            text = raw.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    sample = text[:4096]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=',;\t')
    except csv.Error:
        dialect = csv.excel
    return [row for row in csv.reader(io.StringIO(text), dialect) if any(cell.strip() for cell in row)]


class Problems:
    """Skipped readings, grouped by reason, with a few row numbers for each."""
    def __init__(self):
        self.reasons = OrderedDict()

    def add(self, reason, row=None):
        entry = self.reasons.setdefault(reason, {'count': 0, 'rows': []})
        entry['count'] += 1
        if row is not None and len(entry['rows']) < 5:
            entry['rows'].append(row)

    def as_list(self):
        return [{'reason': r, **e} for r, e in self.reasons.items()]


def build_import(rows, default_tank, date_order='auto'):
    """Works out the readings in a CSV. Returns (readings, problems, notes). Nothing is saved here.
    Each reading is {'tank', 'ptype', 'value', 'when', 'notes', 'row'}."""
    problems, notes = Problems(), []
    if not rows:
        problems.add("The file is empty.")
        return [], problems, notes
    header = [_norm(_clean_cell(h)) for h in rows[0]]
    body = rows[1:]

    def col(names):
        return next((i for i, h in enumerate(header) if h in names), None)
    date_col, time_col, tank_col = col(DATE_HEADERS), col(TIME_HEADERS), col(TANK_HEADERS)
    param_col, value_col, unit_col, note_col = col(PARAM_HEADERS), col(VALUE_HEADERS), col(UNIT_HEADERS), col(NOTE_HEADERS)
    if date_col is None and time_col is not None:
        date_col, time_col = time_col, None
    if date_col is None:
        problems.add("There's no date column. Name it Date or Measured at.")
        return [], problems, notes

    def cell(row, i):
        return row[i].strip() if i is not None and i < len(row) else ''

    def when_text(row):
        text = cell(row, date_col)
        return f"{text} {cell(row, time_col)}".strip() if time_col is not None else text

    hint = date_order_hint(when_text(r) for r in body)
    if date_order == 'auto':
        day_first = hint == 'day'
        if hint is None and any(SLASH_DATE.match(_clean_cell(when_text(r))) for r in body):
            notes.append("Dates like 03/04/2026 could be read either way. They're read month first (March 4); "
                         "if they're day first, change Dates are written and preview again.")
    else:
        day_first = date_order == 'day'

    tanks = {_norm(t.name): t for t in Tank.objects.all()}
    unknown_tanks = set()

    def tank_for(row):
        name = cell(row, tank_col)
        if not name:
            return default_tank
        found = tanks.get(_norm(name))
        if found is None:
            unknown_tanks.add(name)
            return default_tank
        return found

    matcher = ParameterMatcher()
    readings = []
    now = timezone.now()

    def add(row_no, row, ptype, raw_value, convert, unit_label):
        if not raw_value.strip():
            return
        value = parse_number(raw_value)
        if value is None:
            problems.add(f"{ptype.name}: “{raw_value.strip()[:20]}” isn't a plain number", row_no)
            return
        if convert is None:
            problems.add(f"{ptype.name}: no way to convert {unit_label} to {ptype.unit}. Change the test's unit, or the file's", row_no)
            return
        try:
            value = Decimal(str(round(convert(float(value)), 4)))
        except (OverflowError, ValueError, InvalidOperation):
            problems.add(f"{ptype.name}: “{raw_value.strip()[:20]}” is out of range", row_no)
            return
        if abs(value) >= 10 ** 6:
            problems.add(f"{ptype.name}: “{raw_value.strip()[:20]}” is out of range", row_no)
            return
        when = parse_when(when_text(row), day_first)
        if when is None:
            problems.add("The date couldn't be read", row_no)
            return
        if when > now + timedelta(days=1):
            problems.add("Dated in the future", row_no)
            return
        readings.append({'tank': tank_for(row), 'ptype': ptype, 'value': value, 'when': when,
                         'notes': _clean_cell(cell(row, note_col))[:255], 'row': row_no})

    if param_col is not None and value_col is not None:
        notes.append("Read as one reading per row.")
        unknown = {}
        for n, row in enumerate(body, start=2):
            label = cell(row, param_col)
            ptype = matcher.find(label)
            if ptype is None:
                if label:
                    unknown.setdefault(label, []).append(n)
                continue
            unit = cell(row, unit_col)
            add(n, row, ptype, cell(row, value_col), converter(unit, ptype), unit)
        for label, row_nos in unknown.items():
            for row_no in row_nos:
                problems.add(f"“{label[:30]}” isn't one of your tests. Add it under Water first, or rename it in the file", row_no)
    else:
        used = {date_col, time_col, tank_col, unit_col, note_col}
        columns = []
        for i, raw in enumerate(rows[0]):
            if i in used or not raw.strip():
                continue
            label, unit = _clean_cell(raw), ''
            m = HEADER_UNIT.match(label)
            if m:
                label, unit = m.group(1), m.group(2)
            ptype = matcher.find(label) or matcher.find(_clean_cell(raw))
            if ptype is None:
                notes.append(f"Column “{raw.strip()[:30]}” isn't one of your tests, so it's left out. "
                             "Add it under Water first, or rename the column.")
                continue
            columns.append((i, ptype, converter(unit, ptype), unit))
        if not columns:
            problems.add("No columns match your tests. Name them like your tests, e.g. Alkalinity (dKH).")
            return [], problems, notes
        notes.append("Read as a grid: " + ', '.join(p.name for _, p, _, _ in columns) + '.')
        for n, row in enumerate(body, start=2):
            for i, ptype, convert, unit in columns:
                add(n, row, ptype, cell(row, i), convert, unit)

    if unknown_tanks:
        notes.append(f"{', '.join(sorted(unknown_tanks)[:5])} isn't one of your tanks, so "
                     f"{'its' if len(unknown_tanks) == 1 else 'their'} readings go into {default_tank.name}.")
    if len(readings) > MAX_READINGS:
        problems.add(f"Only the first {MAX_READINGS} readings are taken. Split the file to bring in the rest.")
        readings = readings[:MAX_READINGS]
    return readings, problems, notes


def _minute(moment):
    return timezone.localtime(moment).strftime('%Y-%m-%d %H:%M')


def mark_duplicates(readings):
    """Flags readings already logged (same test, tank and minute), or repeated in the file itself."""
    if not readings:
        return
    start = min(r['when'] for r in readings) - timedelta(minutes=1)
    end = max(r['when'] for r in readings) + timedelta(minutes=1)
    existing = ParameterLog.objects.filter(
        tank_id__in={r['tank'].pk for r in readings}, parameter_type_id__in={r['ptype'].pk for r in readings},
        measured_at__range=(start, end)).values_list('tank_id', 'parameter_type_id', 'measured_at')
    seen = {(t, p, _minute(m)) for t, p, m in existing}
    for r in readings:
        key = (r['tank'].pk, r['ptype'].pk, _minute(r['when']))
        r['duplicate'] = key in seen
        seen.add(key)


def summary(readings):
    """Per tank and test: how many are new and how many are already there, for the preview."""
    groups = OrderedDict()
    for r in sorted(readings, key=lambda r: (r['tank'].name.lower(), r['ptype'].display_order, r['ptype'].name.lower())):
        g = groups.setdefault((r['tank'].pk, r['ptype'].pk), {'tank': r['tank'], 'ptype': r['ptype'], 'new': 0,
                                                               'duplicate': 0, 'first': r['when'], 'last': r['when']})
        g['duplicate' if r['duplicate'] else 'new'] += 1
        g['first'], g['last'] = min(g['first'], r['when']), max(g['last'], r['when'])
    return list(groups.values())


def import_view(request):
    """Upload a CSV, then see the preview. GET starts over."""
    tanks = list(Tank.objects.filter(is_archived=False)) or list(Tank.objects.all())
    active = get_active_tank(request)
    context = {'tanks': tanks, 'chosen_tank': active, 'date_order': 'auto'}
    if request.method != 'POST':
        request.session.pop(SESSION_KEY, None)
        return render(request, 'aquarium/import.html', context)

    upload = request.FILES.get('file')
    tank = next((t for t in tanks if str(t.pk) == request.POST.get('tank')), active or (tanks[0] if tanks else None))
    date_order = request.POST.get('date_order') if request.POST.get('date_order') in ('auto', 'month', 'day') else 'auto'
    context.update(chosen_tank=tank, date_order=date_order)
    if tank is None:
        messages.error(request, "Add a tank first, so the readings have somewhere to go.")
        return render(request, 'aquarium/import.html', context)
    if upload is None:
        messages.error(request, "Choose a CSV file to import.")
        return render(request, 'aquarium/import.html', context)
    if upload.size > MAX_BYTES:
        messages.error(request, "That file is over 5 MB. Split it into smaller files.")
        return render(request, 'aquarium/import.html', context)

    readings, problems, notes = build_import(read_csv(upload.read()), tank, date_order)
    mark_duplicates(readings)
    new = [r for r in readings if not r['duplicate']]
    request.session[SESSION_KEY] = {
        'file': upload.name[:100],
        'readings': [[r['tank'].pk, r['ptype'].pk, str(r['value']), r['when'].isoformat(), r['notes']] for r in new],
    }
    context.update(preview=True, file_name=upload.name, groups=summary(readings), problems=problems.as_list(),
                   notes=notes, new_count=len(new), duplicate_count=len(readings) - len(new),
                   sample=[{**r, 'shown': r['ptype'].format_value(r['value'])} for r in sorted(new, key=lambda r: r['when'])[:5]])
    return render(request, 'aquarium/import.html', context)


@require_POST
def import_confirm_view(request):
    """Saves what the preview showed. It checks for duplicates again, in case readings were logged meanwhile."""
    stored = request.session.pop(SESSION_KEY, None)
    if not stored or not stored.get('readings'):
        messages.error(request, "Nothing to import. Upload the file again.")
        return redirect('import_tests')
    tanks = {t.pk: t for t in Tank.objects.all()}
    types = {p.pk: p for p in ParameterType.objects.all()}
    readings = []
    for tank_id, ptype_id, value, when, note in stored['readings']:
        if tank_id in tanks and ptype_id in types:
            readings.append({'tank': tanks[tank_id], 'ptype': types[ptype_id], 'value': Decimal(value),
                             'when': parse_datetime(when), 'notes': note})
    mark_duplicates(readings)
    logs = [ParameterLog(tank=r['tank'], parameter_type=r['ptype'], value=r['value'], measured_at=r['when'], notes=r['notes'])
            for r in readings if not r['duplicate']]
    ParameterLog.objects.bulk_create(logs, batch_size=500)
    if any(log.parameter_type.code == 'water_level' for log in logs):
        note_level_readings()  # bulk_create skips the save hook that does this
    skipped = len(readings) - len(logs)
    messages.success(request, f"Imported {len(logs)} reading{'' if len(logs) == 1 else 's'} from {stored['file']}."
                     + (f" {skipped} were already there." if skipped else ''))
    return redirect('parameters')
