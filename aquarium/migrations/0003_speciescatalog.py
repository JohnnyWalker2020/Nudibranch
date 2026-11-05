from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('aquarium', '0002_parametertype_decimal_places'),
    ]

    operations = [
        migrations.CreateModel(
            name='SpeciesCatalog',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(help_text='Common hobbyist name', max_length=120, unique=True)),
                ('species', models.CharField(blank=True, help_text='Scientific/taxonomic name', max_length=150)),
                ('category', models.CharField(choices=[('fish', 'Fish'), ('cleanup_crew', 'Cleanup Crew'), ('invert', 'Invertebrates & Shrimp'), ('coral', 'Corals & Anemones')], default='fish', max_length=20)),
                ('suggested_group', models.CharField(default='Fish', help_text='Default group when added to tank', max_length=60)),
                ('care_level', models.CharField(default='Beginner', help_text='Beginner, Moderate, or Expert', max_length=30)),
                ('reef_safe', models.CharField(default='Yes', help_text='Yes, With Caution, or No', max_length=30)),
                ('diet', models.CharField(blank=True, help_text='e.g. Herbivore, Omnivore, Carnivore', max_length=150)),
                ('notes', models.TextField(blank=True, help_text='Care tips, temperament, and requirements')),
                ('icon', models.CharField(default='🐠', max_length=10)),
            ],
            options={
                'verbose_name_plural': 'Species Catalog',
                'ordering': ['category', 'name'],
            },
        ),
    ]
