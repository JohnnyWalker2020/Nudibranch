"""Registry of dashboard widgets plus helpers for the saved layout (order + visibility)."""
from django.db import transaction

from .models import DashboardWidget

# Default order = order of this list. `span` is 'full' (whole row) or 'half'.
DASHBOARD_WIDGETS = [
    {'key': 'alerts', 'title': 'Tank alerts', 'icon': '⚠️', 'span': 'full',
     'description': 'Out-of-range tests, low reservoirs, overdue routines and service'},
    {'key': 'water_quality', 'title': 'Water quality rating', 'icon': '💎', 'span': 'full',
     'description': 'A 0-100 score from your latest tests against your target ranges'},
    {'key': 'countdown', 'title': 'Timers', 'icon': '⏱️', 'span': 'full',
     'description': 'A countdown plus your saved timers, each ready to start. Alerts your phone when one ends'},
    {'key': 'parameters', 'title': 'Parameter cards', 'icon': '🧪', 'span': 'full',
     'description': 'Latest value of every tracked parameter'},
    {'key': 'quick_measure', 'title': 'Quick measurements', 'icon': '⚡', 'span': 'half',
     'description': 'Type a value, pick what it is, save'},
    {'key': 'reservoirs', 'title': 'Dosing & ATO levels', 'icon': '💧', 'span': 'half',
     'description': 'Reservoir levels and days remaining'},
    {'key': 'trends', 'title': 'Water trends', 'icon': '📈', 'span': 'full',
     'description': 'Trend chart with a selector per parameter'},
    {'key': 'recent_logs', 'title': 'Recent test logs', 'icon': '📋', 'span': 'half',
     'description': 'Your latest measurements'},
    {'key': 'tank_summary', 'title': 'Tank & flow summary', 'icon': '🏛️', 'span': 'half',
     'description': 'Total volume and estimated turnover per tank'},
    {'key': 'livestock', 'title': 'Livestock roster', 'icon': '🐠', 'span': 'half',
     'description': 'Photos and groups of your animals'},
    {'key': 'webcam', 'title': 'Tank webcam', 'icon': '📹', 'span': 'half',
     'description': 'Live camera quick-view'},
]

WIDGET_KEYS = [w['key'] for w in DASHBOARD_WIDGETS]

# The countdown card's one-tap times: (seconds, label).
COUNTDOWN_PRESETS = [(60, '1m'), (120, '2m'), (180, '3m'), (300, '5m'), (600, '10m'), (1800, '30m'), (3600, '1h')]


def get_dashboard_layout():
    """All widgets (enabled or not) in saved order, creating rows for any new ones."""
    rows = {w.key: w for w in DashboardWidget.objects.all()}
    for index, spec in enumerate(DASHBOARD_WIDGETS):
        if spec['key'] not in rows:
            rows[spec['key']], _ = DashboardWidget.objects.get_or_create(
                key=spec['key'], defaults={'position': index * 10, 'enabled': True})

    layout = []
    for default_index, spec in enumerate(DASHBOARD_WIDGETS):
        row = rows[spec['key']]
        item = dict(spec)
        item.update(enabled=row.enabled, position=row.position, default_index=default_index)
        item['template'] = f"aquarium/widgets/{spec['key']}.html"
        layout.append(item)
    layout.sort(key=lambda w: (w['position'], w['default_index']))
    return layout


@transaction.atomic
def save_dashboard_layout(ordered_keys, enabled_keys):
    """Persist the order (list of keys) and which keys are visible."""
    seen = []
    for key in ordered_keys:
        if key in WIDGET_KEYS and key not in seen:
            seen.append(key)
    for key in WIDGET_KEYS:  # anything missing keeps its place at the end
        if key not in seen:
            seen.append(key)
    enabled = set(k for k in enabled_keys if k in WIDGET_KEYS)
    for position, key in enumerate(seen):
        DashboardWidget.objects.update_or_create(
            key=key, defaults={'position': position * 10, 'enabled': key in enabled})


def reset_dashboard_layout():
    DashboardWidget.objects.all().delete()
