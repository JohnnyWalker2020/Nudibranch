"""The dashboard's one "Tank webcam" card becomes a card per camera, in the same place and shown or hidden as it was."""
from django.db import migrations


def split_webcam_card(apps, schema_editor):
    DashboardWidget = apps.get_model('aquarium', 'DashboardWidget')
    WebcamFeed = apps.get_model('aquarium', 'WebcamFeed')
    old = DashboardWidget.objects.filter(key='webcam').first()
    if old is None:
        return  # a dashboard never customized: camera cards are made when it's first shown
    for offset, camera in enumerate(WebcamFeed.objects.filter(is_active=True).order_by('order', 'name')):
        DashboardWidget.objects.get_or_create(key=f'webcam:{camera.pk}',
                                              defaults={'position': old.position + offset, 'enabled': old.enabled})
    old.delete()


def join_webcam_cards(apps, schema_editor):
    DashboardWidget = apps.get_model('aquarium', 'DashboardWidget')
    cards = list(DashboardWidget.objects.filter(key__startswith='webcam:').order_by('position'))
    if cards:
        DashboardWidget.objects.get_or_create(key='webcam', defaults={
            'position': cards[0].position, 'enabled': any(c.enabled for c in cards)})
        DashboardWidget.objects.filter(pk__in=[c.pk for c in cards]).delete()


class Migration(migrations.Migration):
    dependencies = [('aquarium', '0046_webcam_rotation')]
    operations = [migrations.RunPython(split_webcam_card, join_webcam_cards)]
