"""Which tank system this device is looking at. Remembered per browser, so a phone and PC can differ."""
from .models import Tank

COOKIE_NAME = 'nudibranch_system'
COOKIE_MAX_AGE = 60 * 60 * 24 * 365


def default_tank():
    current = Tank.objects.filter(is_archived=False)
    return current.filter(is_primary=True).first() or current.first() or Tank.objects.first()


def get_active_tank(request):
    """The selected tank, falling back to the primary one (None only when no tanks exist)."""
    if hasattr(request, '_active_tank'):
        return request._active_tank
    raw = request.COOKIES.get(COOKIE_NAME, '')
    tank = Tank.objects.filter(pk=int(raw)).first() if raw.isdecimal() else None
    request._active_tank = tank or default_tank()
    return request._active_tank
