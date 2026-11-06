"""
Retiring a system: keeps all its data and stops its alerts and jobs. Its icon switches to the old
version when it's displayed (see Tank.icon_url), so nothing needs undoing when it comes back.
"""
from django.db import transaction
from django.utils import timezone

from .models import Tank


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
    tank.is_primary = False
    tank.save(update_fields=['is_archived', 'archived_at', 'is_primary'])
    _promote_new_primary()


@transaction.atomic
def restore_system(tank):
    if not tank.is_archived:
        return
    tank.is_archived = False
    tank.archived_at = None
    tank.is_primary = not Tank.objects.filter(is_archived=False, is_primary=True).exists()
    tank.save(update_fields=['is_archived', 'archived_at', 'is_primary'])
