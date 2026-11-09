from django.db import migrations, models


def carve_older_graves(apps, schema_editor):
    """Animals already marked deceased get a tombstone line. Their date of death isn't known, so it stays blank."""
    Animal = apps.get_model('aquarium', 'Animal')
    Animal.objects.filter(status='deceased', epitaph='').update(epitaph='Gone to the big sump in the sky.')


class Migration(migrations.Migration):

    dependencies = [
        ('aquarium', '0038_pipe_type'),
    ]

    operations = [
        migrations.AddField(
            model_name='animal',
            name='nickname',
            field=models.CharField(blank=True, help_text='A name of its own', max_length=120),
        ),
        migrations.AddField(
            model_name='animal',
            name='banned_to_sump',
            field=models.BooleanField(default=False, help_text='Shows a tag on its livestock card'),
        ),
        migrations.AddField(
            model_name='animal',
            name='died_on',
            field=models.DateField(blank=True, help_text='Filled in with today if left blank', null=True),
        ),
        migrations.AddField(
            model_name='animal',
            name='epitaph',
            field=models.CharField(blank=True, help_text='Left blank, one gets picked. {date} becomes the date of death', max_length=160),
        ),
        migrations.RunPython(carve_older_graves, migrations.RunPython.noop),
    ]
