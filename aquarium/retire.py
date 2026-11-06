"""Archiving a system: keeps all its data, stops its alerts and jobs, and gives it a retiree icon."""
from django.db import transaction
from django.utils import timezone

from .models import Tank
from .themes import RETIRED_ICONS


def retired_icon_for(tank):
    """Picks from the retiree set, always the same one for a given system."""
    return RETIRED_ICONS[tank.pk % len(RETIRED_ICONS)][0]


def is_retired_icon(choice):
    return choice in {key for key, _ in RETIRED_ICONS}


def _promote_new_primary():
    current = Tank.objects.filter(is_archived=False)
    if not current.filter(is_primary=True).exists():
        replacement = current.order_by('name').first()
        if replacement:
            Tank.objects.filter(pk=replacement.pk).update(is_primary=True)


@transaction.atomic
def archive_system(tank):
    if tank.is_archived:
        return
    tank.is_archived = True
    tank.archived_at = timezone.now()
    tank.icon_before_archive = tank.icon_choice
    tank.icon_choice = retired_icon_for(tank)
    tank.is_primary = False
    tank.save(update_fields=['is_archived', 'archived_at', 'icon_before_archive', 'icon_choice', 'is_primary'])
    _promote_new_primary()


@transaction.atomic
def restore_system(tank):
    if not tank.is_archived:
        return
    tank.is_archived = False
    tank.archived_at = None
    # Keep an icon the user picked while it was retired, unless it's still from the retiree set.
    if is_retired_icon(tank.icon_choice):
        tank.icon_choice = tank.icon_before_archive
    tank.icon_before_archive = ''
    tank.is_primary = not Tank.objects.filter(is_archived=False, is_primary=True).exists()
    tank.save(update_fields=['is_archived', 'archived_at', 'icon_before_archive', 'icon_choice', 'is_primary'])
