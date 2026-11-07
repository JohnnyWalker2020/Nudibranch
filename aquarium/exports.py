"""CSV downloads of your records, to keep in a spreadsheet or share.

Each covers the selected tank, or every tank with ?tank=all. Times are in your local time zone.
"""
import csv

from django.http import HttpResponse
from django.utils import timezone
from django.utils.text import slugify

from .active import get_active_tank
from .models import DoseLog, ParameterLog, WaterChangeLog, in_system

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


def export_tests(request):
    def rows(tank):
        logs = _scoped(ParameterLog.objects.select_related('tank', 'parameter_type'), tank).order_by('measured_at')
        for log in logs.iterator():
            yield [log.tank.name if log.tank else '', log.parameter_type.name, log.parameter_type.format_value(log.value), log.parameter_type.unit,
                   _when(log.measured_at), log.notes]
    return _csv(request, 'water-tests', ['Tank', 'Parameter', 'Value', 'Unit', 'Measured at', 'Notes'], rows)


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
