from django.db import migrations, models

ACROSS = {'left': 10, 'left_center': 30, 'center': 50, 'right_center': 70, 'right': 90}
DEPTH = {'back': 15, 'middle': 50, 'front': 85}
HEIGHT = {'surface': 10, 'mid': 50, 'bottom': 90}
HEADING = {'front': 0, 'right': 90, 'back': 180, 'left': 270}
TILT = {'up': 75, 'down': -75}


def to_positions(apps, schema_editor):
    """The old menu choices become exact positions and angles on the pickers."""
    Equipment = apps.get_model('aquarium', 'Equipment')
    for eq in Equipment.objects.exclude(outlet_across='', outlet_depth='', outlet_height='', outlet_aim=''):
        if eq.outlet_across or eq.outlet_depth:
            eq.outlet_x = ACROSS.get(eq.outlet_across, 50)
            eq.outlet_y = DEPTH.get(eq.outlet_depth, 50)
        if eq.outlet_height:
            eq.outlet_z = HEIGHT[eq.outlet_height]
        if eq.outlet_aim in HEADING:
            eq.outlet_heading = HEADING[eq.outlet_aim]
        eq.outlet_tilt = TILT.get(eq.outlet_aim, 0)
        eq.save(update_fields=['outlet_x', 'outlet_y', 'outlet_z', 'outlet_heading', 'outlet_tilt'])


class Migration(migrations.Migration):

    dependencies = [
        ('aquarium', '0034_outlets_and_overflow'),
    ]

    operations = [
        migrations.AddField(model_name='equipment', name='outlet_x', field=models.PositiveSmallIntegerField(blank=True, null=True)),
        migrations.AddField(model_name='equipment', name='outlet_y', field=models.PositiveSmallIntegerField(blank=True, null=True)),
        migrations.AddField(model_name='equipment', name='outlet_z', field=models.PositiveSmallIntegerField(blank=True, null=True)),
        migrations.AddField(model_name='equipment', name='outlet_heading', field=models.PositiveSmallIntegerField(blank=True, null=True)),
        migrations.AddField(model_name='equipment', name='outlet_tilt', field=models.SmallIntegerField(default=0)),
        migrations.RunPython(to_positions, migrations.RunPython.noop),
        migrations.RemoveField(model_name='equipment', name='outlet_across'),
        migrations.RemoveField(model_name='equipment', name='outlet_depth'),
        migrations.RemoveField(model_name='equipment', name='outlet_height'),
        migrations.RemoveField(model_name='equipment', name='outlet_aim'),
    ]
