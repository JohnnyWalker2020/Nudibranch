import logging

from django.conf import settings

from .active import get_active_tank
from .alerts import compute_alert_state
from .forms import QuickParameterLogForm
from .icons import FALLBACK_ICON, fallback_url, random_pool
from .models import AppSettings, Tank
from .themes import DEFAULT_THEME, ICON_THEME, THEMES, background_color, theme_css


logger = logging.getLogger(__name__)
# The form in the quick log pop-up shares every page with other forms, so its ids must not clash with theirs.
MODAL_FORM_IDS = 'quick_%s'


def _signed_out(request):
    """The sign-in pages don't show any of this, so don't work it out for them."""
    user = getattr(request, 'user', None)
    return getattr(settings, 'LOGIN_REQUIRED', True) and (user is None or not user.is_authenticated)


def alerts_processor(request):
    """Provides global alert counts and quick notification flags across all templates."""
    if _signed_out(request):
        return {}
    try:
        state = compute_alert_state(request)
        return {
            'global_total_alerts': state['total_alerts'],
            'global_out_of_range_count': len(state['out_of_range_params']),
            'global_stale_count': len(state['stale_params']),
            'global_low_reservoirs_count': len(state['low_reservoirs']),
            'global_due_routines_count': len(state['due_routines']),
            'global_due_equipment_count': len(state['due_equipment']),
            'global_sick_animals_count': len(state['sick_animals']),
            'alert_state': state,
            'modal_form': QuickParameterLogForm(auto_id=MODAL_FORM_IDS),
        }
    except Exception:
        # Expected during initial migrations. Anything else must not look like "no alerts" without a trace.
        logger.exception("Couldn't work out the alerts")
        return {
            'global_total_alerts': 0,
            'global_out_of_range_count': 0,
            'global_stale_count': 0,
            'global_low_reservoirs_count': 0,
            'global_due_routines_count': 0,
            'global_due_equipment_count': 0,
            'global_sick_animals_count': 0,
            'alert_state': None,
            'modal_form': QuickParameterLogForm(auto_id=MODAL_FORM_IDS),
        }


def system_processor(request):
    """The selected system, every system's alert count for the selector, and this system's look."""
    if _signed_out(request):
        return {'theme_background': '#0f172a'}
    try:
        active = get_active_tank(request)
        settings_obj = AppSettings.load()
        systems = []
        tanks = list(Tank.objects.all())
        current_count = sum(1 for tank in tanks if not tank.is_archived)
        for tank in tanks:
            # Alerts on other systems stay visible here, so switching away can't hide a problem.
            is_other = active is not None and tank.pk != active.pk and not tank.is_archived
            alerts = compute_alert_state(tank=tank)['total_alerts'] if current_count > 1 and is_other else 0
            systems.append({'tank': tank, 'alerts': alerts})
        theme = active.theme if active else DEFAULT_THEME
        palette = active.icon_palette() if active and theme == ICON_THEME else None
        return {
            'active_tank': active,
            'systems': systems,
            'theme_css': theme_css(palette if palette else THEMES.get(theme, {}).get('colors', {})),
            'theme_background': palette['slate']['950'] if palette else background_color(theme),
            'system_icon_url': active.icon_url if active else '',
            'fallback_icon_url': fallback_url(),
            'random_icons': random_pool() if settings_obj.enable_random_icons else [],
            'alerts_muted': settings_obj.alerts_muted,
            'alerts_muted_until': settings_obj.alerts_muted_until,
            'costs_enabled': settings_obj.costs_enabled,
            'currency_symbol': settings_obj.currency_symbol,
        }
    except Exception:
        # Expected during initial migrations.
        logger.exception("Couldn't load the selected system")
        return {'active_tank': None, 'systems': [], 'theme_css': '', 'theme_background': '#0f172a', 'system_icon_url': '', 'costs_enabled': False,
                'fallback_icon_url': FALLBACK_ICON, 'random_icons': []}
