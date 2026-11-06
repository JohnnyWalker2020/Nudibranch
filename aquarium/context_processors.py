from .alerts import compute_alert_state
from .forms import QuickParameterLogForm


def alerts_processor(request):
    """Provides global alert counts and quick notification flags across all templates."""
    try:
        state = compute_alert_state(request)
        return {
            'global_total_alerts': state['total_alerts'],
            'global_out_of_range_count': len(state['out_of_range_params']),
            'global_low_reservoirs_count': len(state['low_reservoirs']),
            'global_due_routines_count': len(state['due_routines']),
            'global_due_equipment_count': len(state['due_equipment']),
            'global_sick_animals_count': len(state['sick_animals']),
            'alert_state': state,
            'modal_form': QuickParameterLogForm(),
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
            'alert_state': None,
            'modal_form': QuickParameterLogForm(),
        }
