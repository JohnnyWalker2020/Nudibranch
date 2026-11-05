from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('aquarium', '0001_initial'),
    ]

    operations = [
        migrations.AddField(
            model_name='parametertype',
            name='decimal_places',
            field=models.PositiveSmallIntegerField(
                default=1,
                help_text='Number of decimal places (e.g. 0 for ppm, 3 for SG)'
            ),
        ),
    ]
