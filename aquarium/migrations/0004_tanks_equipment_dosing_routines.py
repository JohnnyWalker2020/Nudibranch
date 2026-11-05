import django.db.models.deletion
import django.utils.timezone
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('aquarium', '0003_speciescatalog'),
    ]

    operations = [
        migrations.CreateModel(
            name='Tank',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(default='Main Display Tank', max_length=100)),
                ('volume_gallons', models.DecimalField(decimal_places=1, default=50.0, help_text='Total system water volume (gal)', max_digits=6)),
                ('is_primary', models.BooleanField(default=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('notes', models.TextField(blank=True)),
            ],
            options={
                'ordering': ['-is_primary', 'name'],
            },
        ),
        migrations.CreateModel(
            name='MaintenanceRoutine',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('title', models.CharField(help_text='e.g. Weekly Water Change & Sump Siphon', max_length=120)),
                ('category', models.CharField(choices=[('water_change', '🌊 Water Change'), ('testing', '🧪 Water Testing'), ('equipment', '⚙️ Equipment Maintenance'), ('general', '📋 General Care')], default='general', max_length=20)),
                ('frequency_days', models.PositiveIntegerField(default=7, help_text='How often to repeat in days (e.g. 7 for weekly)')),
                ('checklist_items', models.JSONField(default=list, help_text='List of task strings')),
                ('last_completed', models.DateTimeField(blank=True, null=True)),
                ('notes', models.TextField(blank=True)),
                ('tank', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name='routines', to='aquarium.tank')),
            ],
            options={
                'ordering': ['frequency_days', 'title'],
            },
        ),
        migrations.CreateModel(
            name='Equipment',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(help_text='e.g. Radion XR30 Pro, Vectra M2 Return Pump', max_length=120)),
                ('category', models.CharField(choices=[('lighting', '💡 Lighting'), ('return_pump', '🔄 Return Pump'), ('wavemaker', '🌊 Wavemaker / Powerhead'), ('skimmer', '🫧 Protein Skimmer'), ('heater', '🌡️ Heater & Temperature Controller'), ('dosing', '🧪 Dosing Pump'), ('ato', '💧 Auto Top-Off (ATO) Unit'), ('filtration', '🧽 Filtration & Media Reactor'), ('monitoring', '📊 Monitor / Controller (Apex, ReefBot)'), ('other', '⚙️ Other Equipment')], default='other', max_length=30)),
                ('brand', models.CharField(blank=True, help_text='Manufacturer or brand', max_length=100)),
                ('wattage', models.PositiveIntegerField(blank=True, help_text='Power consumption (Watts)', null=True)),
                ('installed_date', models.DateField(blank=True, null=True)),
                ('maintenance_interval_days', models.PositiveIntegerField(default=90, help_text='Days between service cleanings (e.g. 90)')),
                ('last_serviced_date', models.DateField(blank=True, help_text='Last date cleaned or calibrated', null=True)),
                ('status', models.CharField(choices=[('operational', 'Operational / Running'), ('maintenance_due', 'Maintenance / Service Due'), ('offline', 'Offline / Standby')], default='operational', max_length=20)),
                ('notes', models.TextField(blank=True)),
                ('tank', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='equipment', to='aquarium.tank')),
            ],
            options={
                'verbose_name_plural': 'Equipment',
                'ordering': ['category', 'name'],
            },
        ),
        migrations.CreateModel(
            name='DosingReservoir',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(help_text='e.g. Alkalinity (Soda Ash), Calcium, All-For-Reef, ATO RO/DI', max_length=100)),
                ('reservoir_type', models.CharField(choices=[('dosing_additive', '🧪 Chemical Additive (Alk, Ca, Mg, AFR)'), ('ato_freshwater', '💧 ATO Fresh RO/DI Water')], default='dosing_additive', max_length=20)),
                ('capacity', models.DecimalField(decimal_places=2, help_text='Total container size (ml for dosing, gal for ATO)', max_digits=8)),
                ('current_level', models.DecimalField(decimal_places=2, help_text='Current liquid amount remaining', max_digits=8)),
                ('unit', models.CharField(default='ml', help_text='ml for dosing, gal or L for ATO', max_length=10)),
                ('daily_consumption', models.DecimalField(decimal_places=2, help_text='Daily dose (ml/day) or evaporation (gal/day)', max_digits=8)),
                ('color', models.CharField(default='#06b6d4', max_length=20)),
                ('last_refilled_date', models.DateField(default=django.utils.timezone.now)),
                ('tank', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='reservoirs', to='aquarium.tank')),
            ],
            options={
                'ordering': ['reservoir_type', 'name'],
            },
        ),
        migrations.CreateModel(
            name='WaterChangeLog',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('performed_at', models.DateTimeField(default=django.utils.timezone.now)),
                ('gallons', models.DecimalField(decimal_places=1, help_text='Gallons of new water changed', max_digits=6)),
                ('salt_brand', models.CharField(blank=True, help_text='e.g. Tropic Marin Pro, Red Sea Blue Bucket', max_length=100)),
                ('target_salinity', models.DecimalField(blank=True, decimal_places=3, help_text='Mixed water salinity', max_digits=6, null=True)),
                ('notes', models.TextField(blank=True)),
                ('tank', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='water_changes', to='aquarium.tank')),
            ],
            options={
                'ordering': ['-performed_at'],
            },
        ),
    ]
