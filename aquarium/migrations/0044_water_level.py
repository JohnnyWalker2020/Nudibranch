"""Adds Water level, for depth and level sensors, to an install that already has its tests set up.

A brand new install gets it from seed_reef_data instead (which only seeds when there are no tests yet).
It's stored in millimeters; readings sent in inches or centimeters are converted. The range is wide on
purpose, so nothing is flagged until a target is set for each tank: a sump and a display run at very
different levels.
"""
from django.db import migrations

WATER_LEVEL = {'name': 'Water level', 'code': 'water_level', 'unit': 'mm', 'decimal_places': 0,
               'min_ideal': 0, 'max_ideal': 2500, 'color': '#14b8a6', 'show_on_dashboard': False}


def add_water_level(apps, schema_editor):
    ParameterType = apps.get_model('aquarium', 'ParameterType')
    if not ParameterType.objects.filter(is_trace=False).exists():
        return  # a new install: seed_reef_data adds it with the rest
    if ParameterType.objects.filter(code='water_level').exists() or ParameterType.objects.filter(name__iexact='Water level').exists():
        return  # already made by hand
    last = ParameterType.objects.filter(is_trace=False).order_by('-display_order').values_list('display_order', flat=True).first() or 0
    ParameterType.objects.create(display_order=last + 1, **WATER_LEVEL)


def remove_water_level(apps, schema_editor):
    ParameterType = apps.get_model('aquarium', 'ParameterType')
    ParameterType.objects.filter(code='water_level', logs__isnull=True).delete()


class Migration(migrations.Migration):
    dependencies = [('aquarium', '0043_tank_stage_icon_version')]
    operations = [migrations.RunPython(add_water_level, remove_water_level)]
