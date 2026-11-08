from django.db import migrations, models


def number_alphabetically(apps, schema_editor):
    """Existing categories start in the order they were shown before: by name."""
    AnimalGroup = apps.get_model('aquarium', 'AnimalGroup')
    for position, group in enumerate(AnimalGroup.objects.order_by('name')):
        AnimalGroup.objects.filter(pk=group.pk).update(position=position)


class Migration(migrations.Migration):

    dependencies = [
        ('aquarium', '0032_head_height_filters'),
    ]

    operations = [
        migrations.AddField(
            model_name='animalgroup',
            name='position',
            field=models.PositiveIntegerField(default=0, editable=False, help_text='Order on the Livestock page'),
        ),
        migrations.AlterModelOptions(
            name='animalgroup',
            options={'ordering': ['position', 'name']},
        ),
        migrations.RunPython(number_alphabetically, migrations.RunPython.noop),
    ]
