from django.db import migrations


def assign_existing_tests(apps, schema_editor):
    """Tests logged before systems existed belong to the primary tank (or the only/first tank)."""
    Tank = apps.get_model('aquarium', 'Tank')
    ParameterLog = apps.get_model('aquarium', 'ParameterLog')
    tank = Tank.objects.filter(is_primary=True).order_by('name').first() or Tank.objects.order_by('name').first()
    if tank is not None:
        ParameterLog.objects.filter(tank__isnull=True).update(tank=tank)


class Migration(migrations.Migration):

    dependencies = [
        ('aquarium', '0012_system_scope'),
    ]

    operations = [
        # Going backwards just leaves the assignment in place; the column itself is removed by 0012.
        migrations.RunPython(assign_existing_tests, migrations.RunPython.noop),
    ]
