"""Single place that works out what currently needs the user's attention."""
from .models import ParameterType, DosingReservoir, MaintenanceRoutine, Equipment, Animal


def compute_alert_state(request=None):
    """
    Returns the lists/counts behind the alert badge, dashboard widget and alerts hub.
    The result is cached on the request so it is only computed once per page load.
    """
    if request is not None and hasattr(request, '_alert_state'):
        return request._alert_state

    out_of_range = []
    for pt in ParameterType.objects.all():
        latest = pt.latest_log()
        if latest and latest.status in ('low', 'high'):
            out_of_range.append({'param': pt, 'log': latest, 'critical': latest.severity == 'critical'})
    out_of_range.sort(key=lambda item: not item['critical'])  # critical first
    critical_params = sum(1 for item in out_of_range if item['critical'])

    low_reservoirs = [r for r in DosingReservoir.objects.select_related('tank') if r.is_low]
    due_routines = [r for r in MaintenanceRoutine.objects.select_related('tank') if r.is_due]
    due_equipment = [e for e in Equipment.objects.select_related('tank') if e.is_service_due]
    sick_animals = list(Animal.objects.filter(status__in=['quarantine', 'monitoring']).select_related('tank'))

    total = (len(out_of_range) + len(low_reservoirs) + len(due_routines)
             + len(due_equipment) + len(sick_animals))
    penalty = (len(out_of_range) * 10 + critical_params * 10 + len(low_reservoirs) * 8 + len(due_routines) * 6
               + len(due_equipment) * 6 + len(sick_animals) * 15)

    state = {
        'out_of_range_params': out_of_range,
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
