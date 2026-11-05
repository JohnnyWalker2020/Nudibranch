import django.db.models.deletion
import django.utils.timezone
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
    ]

    operations = [
        migrations.CreateModel(
            name='AnimalGroup',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=60, unique=True)),
                ('description', models.TextField(blank=True)),
                ('color', models.CharField(default='#64748b', help_text='Hex color for UI tag badges', max_length=20)),
                ('icon', models.CharField(default='🐟', help_text='Emoji or icon symbol', max_length=10)),
            ],
            options={
                'ordering': ['name'],
            },
        ),
        migrations.CreateModel(
            name='ParameterType',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=60, unique=True)),
                ('code', models.SlugField(help_text='Short identifier e.g. alk, sal, ca', max_length=30, unique=True)),
                ('unit', models.CharField(help_text='e.g. dKH, SG, ppm, °F, pH', max_length=20)),
                ('min_ideal', models.DecimalField(decimal_places=3, help_text='Lower bound of target range', max_digits=7)),
                ('max_ideal', models.DecimalField(decimal_places=3, help_text='Upper bound of target range', max_digits=7)),
                ('color', models.CharField(default='#0ea5e9', help_text='Hex color code for charts and badges', max_length=20)),
                ('display_order', models.PositiveIntegerField(default=0)),
            ],
            options={
                'ordering': ['display_order', 'name'],
            },
        ),
        migrations.CreateModel(
            name='WebcamFeed',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=100)),
                ('feed_url', models.CharField(help_text='URL of the stream, snapshot, or embed link', max_length=500)),
                ('feed_type', models.CharField(choices=[('mjpeg', 'MJPEG Stream / Snapshot URL'), ('webrtc', 'WebRTC / HLS Stream (e.g. go2rtc)'), ('iframe', 'Embedded Web Player (iFrame)')], default='mjpeg', max_length=20)),
                ('is_active', models.BooleanField(default=True)),
                ('order', models.PositiveIntegerField(default=0)),
            ],
            options={
                'ordering': ['order', 'name'],
            },
        ),
        migrations.CreateModel(
            name='Animal',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(help_text="Common name or pet name (e.g. 'Ocellaris Clown Pair')", max_length=120)),
                ('species', models.CharField(blank=True, help_text='Scientific or species name (optional)', max_length=150)),
                ('count', models.PositiveIntegerField(default=1, help_text='Quantity (e.g. 10 snails or 5 chromis)')),
                ('acquired_date', models.DateField(blank=True, null=True)),
                ('status', models.CharField(choices=[('healthy', 'Healthy / Thriving'), ('quarantine', 'In Quarantine'), ('monitoring', 'Monitoring / Sick'), ('rehomed', 'Rehomed'), ('deceased', 'Deceased')], default='healthy', max_length=20)),
                ('photo', models.ImageField(blank=True, null=True, upload_to='livestock/')),
                ('notes', models.TextField(blank=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('groups', models.ManyToManyField(blank=True, related_name='animals', to='aquarium.animalgroup')),
            ],
            options={
                'ordering': ['status', 'name'],
            },
        ),
        migrations.CreateModel(
            name='ParameterLog',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('measured_at', models.DateTimeField(default=django.utils.timezone.now)),
                ('value', models.DecimalField(decimal_places=3, max_digits=8)),
                ('notes', models.CharField(blank=True, max_length=255)),
                ('parameter_type', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='logs', to='aquarium.parametertype')),
            ],
            options={
                'ordering': ['-measured_at'],
            },
        ),
    ]
