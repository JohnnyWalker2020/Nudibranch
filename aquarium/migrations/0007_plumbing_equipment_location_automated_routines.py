import aquarium.models
import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('aquarium', '0006_tank_dimensions_sumps_flow_dashboard'),
    ]

    operations = [
        # ---- Tank plumbing (adds to total system volume) ----
        migrations.AddField(
            model_name='tank',
            name='plumbing_length_ft',
            field=models.DecimalField(blank=True, decimal_places=1, help_text='Total length of water-filled pipe (drains + return), in feet', max_digits=6, null=True),
        ),
        migrations.AddField(
            model_name='tank',
            name='plumbing_diameter',
            field=models.CharField(blank=True, choices=[('0.5', '1/2" PVC'), ('0.75', '3/4" PVC'), ('1', '1" PVC'), ('1.25', '1-1/4" PVC'), ('1.5', '1-1/2" PVC'), ('2', '2" PVC')], help_text='Nominal pipe size (Schedule 40 PVC)', max_length=5),
        ),

        # ---- Equipment: auto feeder category + placement in a sump / chamber ----
        migrations.AlterField(
            model_name='equipment',
            name='category',
            field=models.CharField(choices=[('lighting', '💡 Lighting'), ('return_pump', '🔄 Return Pump'), ('wavemaker', '🌊 Wavemaker / Powerhead'), ('skimmer', '🫧 Protein Skimmer'), ('heater', '🌡️ Heater & Temperature Controller'), ('dosing', '🧪 Dosing Pump'), ('ato', '💧 Auto Top-Off (ATO) Unit'), ('feeder', '🍤 Auto Feeder'), ('filtration', '🧽 Filtration & Media Reactor'), ('monitoring', '📊 Monitor / Controller (Apex, ReefBot)'), ('other', '⚙️ Other Equipment')], default='other', max_length=30),
        ),
        migrations.AddField(
            model_name='equipment',
            name='sump',
            field=models.ForeignKey(blank=True, help_text='Sump this sits in (blank = display tank)', null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='equipment', to='aquarium.sump'),
        ),
        migrations.AddField(
            model_name='equipment',
            name='chamber',
            field=models.ForeignKey(blank=True, help_text='Sump chamber this sits in', null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='equipment', to='aquarium.sumpchamber'),
        ),

        # ---- Routines: automated schedules + linked equipment ----
        migrations.AddField(
            model_name='maintenanceroutine',
            name='routine_type',
            field=models.CharField(choices=[('manual', '📋 Manual checklist'), ('automated', '🤖 Automated schedule')], default='manual', max_length=10),
        ),
        migrations.AlterField(
            model_name='maintenanceroutine',
            name='category',
            field=models.CharField(choices=[('water_change', '🌊 Water Change'), ('testing', '🧪 Water Testing'), ('equipment', '⚙️ Equipment Maintenance'), ('general', '📋 General Care'), ('feeding', '🍤 Feeding'), ('lighting', '💡 Lighting'), ('skimmer', '🫧 Skimmer'), ('flow', '🌀 Pumps & Flow'), ('dosing', '🧪 Dosing'), ('ato', '💧 Top-Off')], default='general', max_length=20),
        ),
        migrations.AddField(
            model_name='maintenanceroutine',
            name='equipment',
            field=models.ManyToManyField(blank=True, help_text='Equipment this routine runs on or services', related_name='routines', to='aquarium.equipment'),
        ),
        migrations.AddField(
            model_name='maintenanceroutine',
            name='schedule_events',
            field=models.JSONField(blank=True, default=list, help_text='Automated events: [{"time": "08:00", "action": "Lights on"}]'),
        ),
        migrations.AddField(
            model_name='maintenanceroutine',
            name='schedule_days',
            field=models.JSONField(blank=True, default=aquarium.models.all_weekdays, help_text='Days the schedule runs, 0 = Monday ... 6 = Sunday'),
        ),
        migrations.AddField(
            model_name='maintenanceroutine',
            name='is_active',
            field=models.BooleanField(default=True, help_text='Untick to pause this routine'),
        ),
    ]
