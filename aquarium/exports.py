"""CSV downloads of your records, to keep in a spreadsheet or share.

Each covers the selected tank, or every tank with ?tank=all. Times are in your local time zone.
Water tests can also come as a grid (?layout=grid): one row per test time, one column per parameter.
"""
import csv

from django.db.models import Count
from django.http import HttpResponse
from django.shortcuts import render
from django.utils import timezone
from django.utils.text import slugify

from .active import get_active_tank
from .models import AppSettings, DoseLog, ParameterLog, ParameterType, WaterChangeLog, in_system, visible_q

LITERS_PER_GAL = 3.78541


def _cell(value):
    """Text that a spreadsheet won't run as a formula (a note starting with = or + for example)."""
    text = '' if value is None else str(value)
    return "'" + text if text[:1] in ('=', '+', '-', '@', '\t', '\r') and not _is_number(text) else text


def _is_number(text):
    try:
        float(text)
        return True
    except ValueError:
        return False


def _when(moment):
    return timezone.localtime(moment).strftime('%Y-%m-%d %H:%M')


def _csv(request, what, header, rows):
    everything = request.GET.get('tank') == 'all'
    tank = None if everything else get_active_tank(request)
    name = 'all-tanks' if tank is None else slugify(tank.name) or 'tank'
    response = HttpResponse(content_type='text/csv; charset=utf-8')
    response['Content-Disposition'] = f'attachment; filename="nudibranch-{what}-{name}-{timezone.localdate():%Y-%m-%d}.csv"'
    response.write('\ufeff')  # so Excel reads the file as UTF-8
    writer = csv.writer(response)
    writer.writerow(header)
    for row in rows(tank):
        writer.writerow([_cell(value) for value in row])
    return response


def _scoped(queryset, tank):
    return queryset if tank is None else in_system(queryset, tank)


def _test_logs(tank, request=None):
    """The readings to export. ?p=<parameter id> (repeatable) keeps only those tests; without any, every test."""
    logs = _scoped(ParameterLog.objects.select_related('tank', 'parameter_type'), tank).order_by('measured_at', 'id')
    if not AppSettings.load().icp_enabled:  # ICP readings stay out of sight while ICP is off
        logs = logs.filter(visible_q('parameter_type__'))
    if request is not None and 'p' in request.GET:
        picked = [int(v) for v in request.GET.getlist('p') if v.isdigit()]
        logs = logs.filter(parameter_type_id__in=picked)
    return logs


def export_page(request):
    """Pick what to download: which tank, which layout, and which tests (the ones with readings are ticked)."""
    tank = get_active_tank(request)
    types = list(ParameterType.objects.in_use().order_by('display_order', 'name'))
    here = dict(_scoped(ParameterLog.objects.all(), tank).values_list('parameter_type').annotate(n=Count('id')))
    everywhere = dict(ParameterLog.objects.values_list('parameter_type').annotate(n=Count('id')))
    tests = [{'type': t, 'here': here.get(t.pk, 0), 'everywhere': everywhere.get(t.pk, 0)} for t in types]
    return render(request, 'aquarium/export.html', {'tests': tests})


def export_tests(request):
    """Every water test, one reading per row. ?layout=grid gives one row per test time and a column per parameter."""
    if request.GET.get('layout') == 'grid':
        return _export_tests_grid(request)

    def rows(tank):
        for log in _test_logs(tank, request).iterator():
            yield [log.tank.name if log.tank else '', log.parameter_type.name, log.parameter_type.format_value(log.value), log.parameter_type.unit,
                   _when(log.measured_at), log.notes]
    return _csv(request, 'water-tests', ['Tank', 'Parameter', 'Value', 'Unit', 'Measured at', 'Notes'], rows)


def _export_tests_grid(request):
    """Readings taken in the same minute on the same tank share a row, ready to chart in a spreadsheet.
    If one parameter was logged twice in that minute, the later reading is the one shown."""
    everything = request.GET.get('tank') == 'all'
    tank = None if everything else get_active_tank(request)
    logs = list(_test_logs(tank, request))
    types = sorted({log.parameter_type for log in logs}, key=lambda t: (t.display_order, t.name.lower()))
    by_moment = {}
    for log in logs:
        key = (log.tank.name if log.tank else '', _when(log.measured_at))
        by_moment.setdefault(key, {})[log.parameter_type.pk] = log.parameter_type.format_value(log.value)
    header = ['Tank', 'Measured at'] + [f"{t.name} ({t.unit})" if t.unit and t.unit.lower() != t.name.lower() else t.name
                                        for t in types]

    def rows(_tank):
        for (tank_name, when), values in sorted(by_moment.items(), key=lambda item: (item[0][1], item[0][0])):
            yield [tank_name, when] + [values.get(t.pk, '') for t in types]
    return _csv(request, 'water-tests-grid', header, rows)


def export_water_changes(request):
    def rows(tank):
        changes = _scoped(WaterChangeLog.objects.select_related('tank'), tank).order_by('performed_at')
        for wc in changes.iterator():
            yield [wc.tank.name, _when(wc.performed_at), f"{wc.gallons.normalize():f}", round(float(wc.gallons) * LITERS_PER_GAL, 1),
                   wc.salt_brand, wc.target_salinity if wc.target_salinity is not None else '', wc.notes]
    return _csv(request, 'water-changes', ['Tank', 'Date', 'Gallons', 'Liters', 'Salt', 'Salinity (SG)', 'Notes'], rows)


def export_doses(request):
    def rows(tank):
        doses = _scoped(DoseLog.objects.select_related('tank', 'reservoir'), tank).order_by('dosed_at')
        for dose in doses.iterator():
            yield [dose.tank.name, _when(dose.dosed_at), dose.parameter_label if dose.parameter else '', dose.product,
                   f"{dose.amount.normalize():f}", dose.unit, dose.reservoir.name if dose.reservoir else '', dose.notes]
    return _csv(request, 'doses', ['Tank', 'Date', 'For', 'Product', 'Amount', 'Unit', 'From container', 'Notes'], rows)
