from .active import get_active_tank
from .alerts import compute_alert_state
from .forms import QuickParameterLogForm
from .models import AppSettings, Tank
from .themes import DEFAULT_THEME, background_color, theme_colors_json


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


def system_processor(request):
    """The selected system, every system's alert count for the selector, and this system's look."""
    try:
        active = get_active_tank(request)
        settings_obj = AppSettings.load()
        systems = []
        tanks = list(Tank.objects.all())
        current_count = sum(1 for tank in tanks if not tank.is_archived)
        for tank in tanks:
            # Alerts on other systems stay visible here, so switching away can't hide a problem.
            alerts = compute_alert_state(tank=tank)['total_alerts'] if current_count > 1 and not tank.is_archived else 0
            systems.append({'tank': tank, 'alerts': alerts})
        theme = active.theme if active else DEFAULT_THEME
        return {
            'active_tank': active,
            'systems': systems,
            'theme_colors_json': theme_colors_json(theme),
            'theme_background': background_color(theme),
            'system_icon_url': active.icon_url if active else '',
            'costs_enabled': settings_obj.costs_enabled,
            'currency_symbol': settings_obj.currency_symbol,
        }
    except Exception:
        # Fallback during initial migrations.
        return {'active_tank': None, 'systems': [], 'theme_colors_json': '{}', 'theme_background': '#0f172a', 'system_icon_url': '', 'costs_enabled': False}
