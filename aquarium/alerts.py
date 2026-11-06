"""Single place that works out what currently needs the user's attention."""
from datetime import timedelta

from django.utils import timezone

from .active import get_active_tank
from .models import (
    ANY, ParameterType, DosingReservoir, MaintenanceRoutine, Equipment, Animal, Tank, in_system,
    latest_logs_by_parameter, not_retired,
)


def log_buckets():
    """Each system's readings are separate. Readings with no tank only matter when there are no tanks."""
    return list(Tank.objects.filter(is_archived=False)) or [None]


def _parameter_problems(tank, param_types, now):
    """(readings out of range, probes that have gone quiet) for one system."""
    latest = latest_logs_by_parameter(tank)
    out_of_range, stale = [], []
    for base in param_types:
        log = latest.get(base.pk)
        if log is None:
            continue
        pt = base.for_system(tank)
        log.parameter_type = pt  # already loaded, so judging the reading needs no more queries
        if log.status in ('low', 'high'):
            out_of_range.append({'param': pt, 'log': log, 'critical': log.severity == 'critical', 'tank': tank})
        if pt.stale_after_hours and now - log.measured_at > timedelta(hours=pt.stale_after_hours):
            stale.append({'param': pt, 'log': log, 'tank': tank})
    return out_of_range, stale


def compute_alert_state(request=None, tank=ANY):
    """
    Returns the lists/counts behind the alert badge, dashboard widget and alerts hub.

    With a request, it covers that browser's selected system and is cached for the page load.
    Otherwise it covers `tank`, or every system when no tank is given (the background worker).
    """
    if request is not None:
        if hasattr(request, '_alert_state'):
            return request._alert_state
        tank = get_active_tank(request)

    if tank is not ANY and tank is not None and tank.is_archived:
        # A retired system is a record of the past. It has nothing to alert about.
        state = {'out_of_range_params': [], 'stale_params': [], 'low_reservoirs': [], 'due_routines': [], 'due_equipment': [],
                 'sick_animals': [], 'total_alerts': 0, 'health_score': 100}
        if request is not None:
            request._alert_state = state
        return state

    def scoped(queryset):
        return not_retired(queryset) if tank is ANY else in_system(queryset, tank)

    now = timezone.now()
    param_types = list(ParameterType.objects.prefetch_related('targets'))
    out_of_range, stale_params = [], []
    for bucket in (log_buckets() if tank is ANY else [tank]):
        bad, stale = _parameter_problems(bucket, param_types, now)
        out_of_range += bad
        stale_params += stale
    out_of_range.sort(key=lambda item: not item['critical'])  # critical first
    critical_params = sum(1 for item in out_of_range if item['critical'])

    low_reservoirs = [r for r in scoped(DosingReservoir.objects.select_related('tank')) if r.is_low]
    due_routines = [r for r in scoped(MaintenanceRoutine.objects.select_related('tank')) if r.is_due]
    due_equipment = [e for e in scoped(Equipment.objects.select_related('tank')) if e.is_service_due]
    sick_animals = list(scoped(Animal.objects.filter(status__in=['quarantine', 'monitoring']).select_related('tank')))

    total = (len(out_of_range) + len(stale_params) + len(low_reservoirs) + len(due_routines)
             + len(due_equipment) + len(sick_animals))
    penalty = (len(out_of_range) * 10 + critical_params * 10 + len(stale_params) * 6 + len(low_reservoirs) * 8 + len(due_routines) * 6
               + len(due_equipment) * 6 + len(sick_animals) * 15)

    state = {
        'out_of_range_params': out_of_range,
        'stale_params': stale_params,
        'low_reservoirs': low_reservoirs,
        'due_routines': due_routines,
        'due_equipment': due_equipment,
        'sick_animals': sick_animals,
        'total_alerts': total,
        'health_score': max(25, 100 - penalty),
    }
    if request is not None:
        request._alert_state = state
    return state
