"""Registry of dashboard widgets plus helpers for the saved layout (order + visibility).

Most cards are fixed (the list below). Cameras are added on top: each active camera gets a card of its own,
keyed "webcam:<id>", from any tank, so the dashboard can show several cameras at once.
"""
from django.db import transaction

from .models import DashboardWidget, WebcamFeed

# Default order = order of this list. `span` is 'full' (whole row) or 'half'.
DASHBOARD_WIDGETS = [
    {'key': 'alerts', 'title': 'Tank alerts', 'icon': '⚠️', 'span': 'full',
     'description': 'Out-of-range tests, low reservoirs, overdue routines and service'},
    {'key': 'water_quality', 'title': 'Water quality rating', 'icon': '💎', 'span': 'full',
     'description': 'A 0-100 score from your latest tests against your target ranges'},
    {'key': 'quick_tasks', 'title': 'Quick tasks', 'icon': '✅', 'span': 'half',
     'description': 'Log a water change or mark a filter cleaned, one tap each'},
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
    {'key': 'other_tanks', 'title': 'Other tanks', 'icon': '🗂️', 'span': 'half',
     'description': "Each of your other tanks' alerts and last test, a tap away. Only shows with more than one tank"},
]

WIDGET_KEYS = [w['key'] for w in DASHBOARD_WIDGETS]
CAMERA_PREFIX = 'webcam:'

# The countdown card's one-tap times: (seconds, label).
COUNTDOWN_PRESETS = [(60, '1m'), (120, '2m'), (180, '3m'), (300, '5m'), (600, '10m'), (1800, '30m'), (3600, '1h')]


def camera_key(camera):
    return f'{CAMERA_PREFIX}{camera.pk}'


def _cameras():
    return list(WebcamFeed.objects.filter(is_active=True).select_related('tank').order_by('order', 'name'))


def get_dashboard_layout():
    """All widgets (enabled or not) in saved order, creating rows for any new ones (new cameras go last, shown)."""
    rows = {w.key: w for w in DashboardWidget.objects.all()}
    cameras = _cameras()
    camera_keys = {camera_key(c) for c in cameras}
    for key in [k for k in rows if k.startswith(CAMERA_PREFIX) and k not in camera_keys]:
        DashboardWidget.objects.filter(key=key).delete()  # a camera that was deleted or switched off
        del rows[key]
    for index, spec in enumerate(DASHBOARD_WIDGETS):
        if spec['key'] not in rows:
            rows[spec['key']], _ = DashboardWidget.objects.get_or_create(
                key=spec['key'], defaults={'position': index * 10, 'enabled': True})
    end = max((r.position for r in rows.values()), default=0)
    for camera in cameras:
        key = camera_key(camera)
        if key not in rows:
            end += 10
            rows[key], _ = DashboardWidget.objects.get_or_create(key=key, defaults={'position': end, 'enabled': True})

    layout = []
    for default_index, spec in enumerate(DASHBOARD_WIDGETS):
        row = rows[spec['key']]
        item = dict(spec)
        item.update(enabled=row.enabled, position=row.position, default_index=default_index)
        item['template'] = f"aquarium/widgets/{spec['key']}.html"
        layout.append(item)
    for index, camera in enumerate(cameras):
        row = rows[camera_key(camera)]
        layout.append({
            'key': camera_key(camera), 'title': camera.name, 'icon': '📹', 'span': 'half', 'camera': camera,
            'description': f"Live view{f' · {camera.tank.name}' if camera.tank else ' · every tank'}",
            'enabled': row.enabled, 'position': row.position, 'default_index': len(DASHBOARD_WIDGETS) + index,
            'template': 'aquarium/widgets/webcam.html',
        })
    layout.sort(key=lambda w: (w['position'], w['default_index']))
    return layout


@transaction.atomic
def save_dashboard_layout(ordered_keys, enabled_keys):
    """Persist the order (list of keys) and which keys are visible."""
    valid = WIDGET_KEYS + [camera_key(c) for c in _cameras()]
    seen = []
    for key in ordered_keys:
        if key in valid and key not in seen:
            seen.append(key)
    for key in valid:  # anything missing keeps its place at the end
        if key not in seen:
            seen.append(key)
    enabled = set(k for k in enabled_keys if k in valid)
    for position, key in enumerate(seen):
        DashboardWidget.objects.update_or_create(
            key=key, defaults={'position': position * 10, 'enabled': key in enabled})


def set_camera_shown(camera, shown):
    """The camera's own 'Show on the dashboard' switch: the same setting as its tick in Customize."""
    key = camera_key(camera)
    row = DashboardWidget.objects.filter(key=key).first()
    if row is None:
        end = max(DashboardWidget.objects.values_list('position', flat=True), default=0)
        DashboardWidget.objects.create(key=key, position=end + 10, enabled=shown)
    elif row.enabled != shown:
        DashboardWidget.objects.filter(pk=row.pk).update(enabled=shown)


def camera_shown(camera):
    """Whether a camera's card is on the dashboard. A camera with no card yet will get one, shown."""
    row = DashboardWidget.objects.filter(key=camera_key(camera)).first()
    return True if row is None else row.enabled


def reset_dashboard_layout():
    DashboardWidget.objects.all().delete()
