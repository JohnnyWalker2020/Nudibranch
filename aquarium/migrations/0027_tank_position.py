"""Tanks get a position, starting from the order they showed in before: primary first, then by name."""
from django.db import migrations, models


def number_tanks(apps, schema_editor):
    Tank = apps.get_model('aquarium', 'Tank')
    for position, tank in enumerate(Tank.objects.order_by('-is_primary', 'name')):
        Tank.objects.filter(pk=tank.pk).update(position=position)


class Migration(migrations.Migration):
    dependencies = [('aquarium', '0026_coral_groups')]
    operations = [
        migrations.AddField(
            model_name='tank',
            name='position',
            field=models.PositiveIntegerField(default=0, editable=False, help_text='Order on the Tanks page and in the Tank menu'),
        ),
        migrations.AlterModelOptions(name='tank', options={'ordering': ['position', 'name']}),
        migrations.RunPython(number_tanks, migrations.RunPython.noop),
    ]
