import django.db.models.deletion
import django.utils.timezone
from django.db import migrations, models

PIPE_CHOICES = [('0.5', '1/2" PVC'), ('0.75', '3/4" PVC'), ('1', '1" PVC'), ('1.25', '1-1/4" PVC'),
                ('1.5', '1-1/2" PVC'), ('2', '2" PVC'), ('custom', 'Custom inside diameter')]

# Sensible alert limits for the default parameters, applied only when the parameter still uses the
# seeded unit and the limits sit outside its ideal range. Editable afterwards in Parameter settings.
DEFAULT_LIMITS = {
    ('salinity', 'SG'): (1.023, 1.028),
    ('alkalinity', 'dKH'): (7.0, 11.0),
    ('calcium', 'ppm'): (380, 480),
    ('magnesium', 'ppm'): (1250, 1450),
    ('nitrate', 'ppm'): (0.5, 25),
    ('phosphate', 'ppm'): (0.01, 0.2),
    ('temperature', '°F'): (75, 81),
    ('ph', 'pH'): (7.8, 8.5),
}


def copy_tank_plumbing(apps, schema_editor):
    Tank = apps.get_model('aquarium', 'Tank')
    PlumbingRun = apps.get_model('aquarium', 'PlumbingRun')
    for tank in Tank.objects.all():
        if tank.plumbing_length_ft and tank.plumbing_diameter:
            PlumbingRun.objects.create(tank=tank, name='Plumbing', length=tank.plumbing_length_ft,
                                       length_unit='ft', pipe_size=tank.plumbing_diameter)


def _from_frequency_days(days):
    days = max(1, int(days or 1))
    if days % 365 == 0:
        return days // 365, 'year'
    if days in (30, 31):
        return 1, 'month'
    if days % 30 == 0 and days < 365:
        return days // 30, 'month'
    if days % 7 == 0:
        return days // 7, 'week'
    return days, 'day'


def convert_routines(apps, schema_editor):
    Routine = apps.get_model('aquarium', 'MaintenanceRoutine')
    today = django.utils.timezone.localdate()
    for r in Routine.objects.all():
        if r.routine_type == 'automated':
            days = sorted({int(d) for d in (r.schedule_days or [])})
            if not days or len(days) == 7:
                r.repeat_every, r.repeat_unit, r.schedule_days = 1, 'day', []
            else:
                r.repeat_every, r.repeat_unit, r.schedule_days = 1, 'week', days
            r.start_date = today
        else:
            r.repeat_every, r.repeat_unit = _from_frequency_days(r.frequency_days)
            r.schedule_days = []
            # Anchor on the last completion so the next due date matches the old behaviour.
            r.start_date = (django.utils.timezone.localtime(r.last_completed).date()
                            if r.last_completed else today)
        r.save(update_fields=['repeat_every', 'repeat_unit', 'schedule_days', 'start_date'])


def default_param_limits(apps, schema_editor):
    ParameterType = apps.get_model('aquarium', 'ParameterType')
    for pt in ParameterType.objects.filter(low_limit__isnull=True, high_limit__isnull=True):
        limits = DEFAULT_LIMITS.get((pt.code, pt.unit))
        if not limits:
            continue
        low, high = limits
        if low < float(pt.min_ideal) and high > float(pt.max_ideal):
            pt.low_limit, pt.high_limit = low, high
            pt.save(update_fields=['low_limit', 'high_limit'])


class Migration(migrations.Migration):

    dependencies = [
        ('aquarium', '0007_plumbing_equipment_location_automated_routines'),
    ]

    operations = [
        # ---- Plumbing runs (replace the single length/diameter on Tank) ----
        migrations.CreateModel(
            name='PlumbingRun',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(blank=True, help_text='e.g. Return line, Main drain, Emergency drain', max_length=80)),
                ('length', models.DecimalField(decimal_places=1, help_text='Length of one pipe', max_digits=7)),
                ('length_unit', models.CharField(choices=[('ft', 'Feet'), ('m', 'Meters')], default='ft', max_length=2)),
                ('pipe_size', models.CharField(choices=PIPE_CHOICES, default='1', help_text='Nominal Schedule 40 PVC size, or enter a custom inside diameter', max_length=6)),
                ('custom_diameter', models.DecimalField(blank=True, decimal_places=3, help_text='Inside diameter, when the size is Custom', max_digits=6, null=True)),
                ('custom_diameter_unit', models.CharField(choices=[('in', 'Inches'), ('mm', 'Millimeters')], default='in', max_length=2)),
                ('count', models.PositiveSmallIntegerField(default=1, help_text='Number of identical pipes (e.g. 2 drains)')),
                ('fill_percent', models.DecimalField(decimal_places=1, default=100, help_text='How full the pipe runs. Return lines are 100%; drains often 50-80%', max_digits=5)),
                ('tank', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='plumbing_runs', to='aquarium.tank')),
            ],
            options={
                'ordering': ['tank', 'id'],
            },
        ),
        migrations.RunPython(copy_tank_plumbing, migrations.RunPython.noop),
        migrations.RemoveField(model_name='tank', name='plumbing_length_ft'),
        migrations.RemoveField(model_name='tank', name='plumbing_diameter'),

        # ---- Routine repeat schedules ----
        migrations.AddField(
            model_name='maintenanceroutine',
            name='repeat_every',
            field=models.PositiveIntegerField(default=1, help_text='Repeat every N units'),
        ),
        migrations.AddField(
            model_name='maintenanceroutine',
            name='repeat_unit',
            field=models.CharField(choices=[('day', 'Days'), ('week', 'Weeks'), ('month', 'Months'), ('year', 'Years')], default='week', max_length=5),
        ),
        migrations.AddField(
            model_name='maintenanceroutine',
            name='start_date',
            field=models.DateField(default=django.utils.timezone.localdate, help_text='First day the schedule applies'),
        ),
        migrations.AddField(
            model_name='maintenanceroutine',
            name='due_time',
            field=models.TimeField(blank=True, help_text="Manual routines: time of day it's due (optional)", null=True),
        ),
        migrations.AlterField(
            model_name='maintenanceroutine',
            name='schedule_days',
            field=models.JSONField(blank=True, default=list, help_text='Weekly schedules: weekdays it runs, 0 = Monday ... 6 = Sunday'),
        ),
        migrations.RunPython(convert_routines, migrations.RunPython.noop),
        migrations.RemoveField(model_name='maintenanceroutine', name='frequency_days'),
        migrations.AlterModelOptions(
            name='maintenanceroutine',
            options={'ordering': ['title']},
        ),

        # ---- Parameter low / high limits around the ideal range ----
        migrations.AddField(
            model_name='parametertype',
            name='low_limit',
            field=models.DecimalField(blank=True, decimal_places=3, help_text='At or below this is critically low (optional)', max_digits=10, null=True),
        ),
        migrations.AddField(
            model_name='parametertype',
            name='high_limit',
            field=models.DecimalField(blank=True, decimal_places=3, help_text='At or above this is critically high (optional)', max_digits=10, null=True),
        ),
        migrations.RunPython(default_param_limits, migrations.RunPython.noop),
    ]
