from .models import ParameterType, DosingReservoir, MaintenanceRoutine, Equipment, Animal


def alerts_processor(request):
    """Provides global alert count and quick notification flags across all templates."""
    try:
        # Out-of-range parameters
        out_of_range_count = 0
        for pt in ParameterType.objects.all():
            latest = pt.latest_log()
            if latest and latest.status in ['low', 'high']:
                out_of_range_count += 1

        low_reservoirs_count = sum(1 for r in DosingReservoir.objects.all() if r.is_low)
        due_routines_count = sum(1 for r in MaintenanceRoutine.objects.all() if r.is_due)
        due_equipment_count = sum(1 for e in Equipment.objects.all() if e.is_service_due)
        sick_animals_count = Animal.objects.filter(status__in=['quarantine', 'monitoring']).count()

        total_alerts = (
            out_of_range_count +
            low_reservoirs_count +
            due_routines_count +
            due_equipment_count +
            sick_animals_count
        )

        return {
            'global_total_alerts': total_alerts,
            'global_out_of_range_count': out_of_range_count,
            'global_low_reservoirs_count': low_reservoirs_count,
            'global_due_routines_count': due_routines_count,
            'global_due_equipment_count': due_equipment_count,
            'global_sick_animals_count': sick_animals_count,
        }
    except Exception:
        # Fallback during initial migrations or empty DB
        return {
            'global_total_alerts': 0,
            'global_out_of_range_count': 0,
            'global_low_reservoirs_count': 0,
            'global_due_routines_count': 0,
            'global_due_equipment_count': 0,
            'global_sick_animals_count': 0,
        }
