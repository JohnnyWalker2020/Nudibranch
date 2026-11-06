import django.db.models.deletion
import django.utils.timezone
from django.db import migrations, models

FILL_HELP = "Usable water as a % of the box volume (glass thickness, water line below the rim, bracing)"
MANUAL_HELP = "Tick to enter the capacity yourself instead of estimating it from the dimensions"


class Migration(migrations.Migration):

    dependencies = [
        ('aquarium', '0005_animal_tank'),
    ]

    operations = [
        # ---- widen numeric fields so converted units (e.g. ppb) fit ----
        migrations.AlterField(
            model_name='parametertype',
            name='min_ideal',
            field=models.DecimalField(decimal_places=3, help_text='Lower bound of target range', max_digits=10),
        ),
        migrations.AlterField(
            model_name='parametertype',
            name='max_ideal',
            field=models.DecimalField(decimal_places=3, help_text='Upper bound of target range', max_digits=10),
        ),
        migrations.AlterField(
            model_name='parameterlog',
            name='value',
            field=models.DecimalField(decimal_places=4, max_digits=10),
        ),
        migrations.AlterField(
            model_name='dosingreservoir',
            name='last_refilled_date',
            field=models.DateField(default=django.utils.timezone.localdate),
        ),

        # ---- Tank dimensions / capacity ----
        migrations.AddField(
            model_name='tank',
            name='dimension_unit',
            field=models.CharField(choices=[('in', 'Inches'), ('cm', 'Centimeters')], default='in', max_length=2),
        ),
        migrations.AddField(
            model_name='tank',
            name='width',
            field=models.DecimalField(blank=True, decimal_places=1, help_text='Interior width, left to right', max_digits=7, null=True),
        ),
        migrations.AddField(
            model_name='tank',
            name='depth',
            field=models.DecimalField(blank=True, decimal_places=1, help_text='Interior depth, front to back', max_digits=7, null=True),
        ),
        migrations.AddField(
            model_name='tank',
            name='height',
            field=models.DecimalField(blank=True, decimal_places=1, help_text='Interior height', max_digits=7, null=True),
        ),
        migrations.AddField(
            model_name='tank',
            name='fill_percent',
            field=models.DecimalField(decimal_places=1, default=90, help_text=FILL_HELP, max_digits=5),
        ),
        migrations.AddField(
            model_name='tank',
            name='capacity_is_manual',
            field=models.BooleanField(default=False, help_text=MANUAL_HELP),
        ),
        migrations.AlterField(
            model_name='tank',
            name='volume_gallons',
            field=models.DecimalField(decimal_places=1, default=50.0, help_text='Water volume (US gallons)', max_digits=7),
        ),

        # ---- Sump and chambers ----
        migrations.CreateModel(
            name='Sump',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('width', models.DecimalField(blank=True, decimal_places=1, help_text='Interior width, left to right', max_digits=7, null=True)),
                ('depth', models.DecimalField(blank=True, decimal_places=1, help_text='Interior depth, front to back', max_digits=7, null=True)),
                ('height', models.DecimalField(blank=True, decimal_places=1, help_text='Interior height', max_digits=7, null=True)),
                ('dimension_unit', models.CharField(choices=[('in', 'Inches'), ('cm', 'Centimeters')], default='in', max_length=2)),
                ('capacity_is_manual', models.BooleanField(default=False, help_text=MANUAL_HELP)),
                ('fill_percent', models.DecimalField(decimal_places=1, default=60, help_text=FILL_HELP, max_digits=5)),
                ('volume_gallons', models.DecimalField(decimal_places=1, default=20.0, help_text='Water volume (US gallons)', max_digits=7)),
                ('name', models.CharField(default='Sump', max_length=100)),
                ('notes', models.TextField(blank=True)),
                ('tank', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='sumps', to='aquarium.tank')),
            ],
            options={
                'ordering': ['tank', 'name'],
            },
        ),
        migrations.CreateModel(
            name='SumpChamber',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('position', models.PositiveIntegerField(default=1, help_text='Order in the water path, 1 = first')),
                ('name', models.CharField(blank=True, max_length=80)),
                ('chamber_type', models.CharField(choices=[('inflow', '⬇️ Inflow / Filter Sock'), ('skimmer', '🫧 Protein Skimmer'), ('filter', '🧽 Filtration / Media'), ('refugium', '🌿 Refugium'), ('bubble_trap', '💨 Bubble Trap'), ('heater', '🌡️ Heater / Equipment'), ('ato', '💧 ATO / Top-off'), ('return', '🔄 Return Pump'), ('other', '⚙️ Other')], default='other', max_length=20)),
                ('share_percent', models.DecimalField(decimal_places=1, default=0, help_text="Share of the sump's water volume in this chamber", max_digits=5)),
                ('notes', models.TextField(blank=True)),
                ('sump', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='chambers', to='aquarium.sump')),
            ],
            options={
                'ordering': ['sump', 'position', 'id'],
            },
        ),

        # ---- Equipment flow ----
        migrations.AddField(
            model_name='equipment',
            name='max_flow_gph',
            field=models.PositiveIntegerField(blank=True, help_text='Rated maximum flow in gallons per hour (L/h ÷ 3.785 = gph)', null=True),
        ),
        migrations.AddField(
            model_name='equipment',
            name='power_setting_percent',
            field=models.PositiveSmallIntegerField(default=100, help_text='Current power / speed setting, 1-100%'),
        ),
        migrations.AddField(
            model_name='equipment',
            name='flow_derate_percent',
            field=models.PositiveSmallIntegerField(default=0, help_text='Flow lost to head height and plumbing, % (return pumps are often 20-40%)'),
        ),

        # ---- Dashboard layout ----
        migrations.CreateModel(
            name='DashboardWidget',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('key', models.CharField(max_length=40, unique=True)),
                ('enabled', models.BooleanField(default=True)),
                ('position', models.PositiveIntegerField(default=0)),
            ],
            options={
                'ordering': ['position', 'id'],
            },
        ),
    ]
