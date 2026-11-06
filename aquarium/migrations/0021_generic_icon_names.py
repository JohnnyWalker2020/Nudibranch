from django.db import migrations

# Icon files were renamed to plain descriptions. Systems using one keep the same character.
RENAMED = {
    '06-turtle-ninja': '06-shell-ninja',
    '07-kpop-demon-hunter': '07-pop-star-slayer',
    '09-straw-hat-pirate': '09-sun-hat-pirate',
    '13-federation-officer': '13-starship-officer',
    '14-borg-nudibranch': '14-cyborg-drone',
    '15-light-side-jedi': '15-light-blade-monk',
    '16-dark-side-jedi': '16-shadow-blade-lord',
    '17-dune-desert-sage': '17-desert-sage',
    '18-ghost-catcher': '18-spirit-catcher',
    '23-ghibli-adventurer': '23-storybook-adventurer',
    '25-joker': '25-chaos-clown',
    '26-ironman': '26-armored-inventor',
}


def rename_choices(apps, schema_editor):
    Tank = apps.get_model('aquarium', 'Tank')
    for old, new in RENAMED.items():
        for version in ('young', 'old'):
            Tank.objects.filter(icon_choice=f'{old}-{version}').update(icon_choice=f'{new}-{version}')


def restore_choices(apps, schema_editor):
    Tank = apps.get_model('aquarium', 'Tank')
    for old, new in RENAMED.items():
        for version in ('young', 'old'):
            Tank.objects.filter(icon_choice=f'{new}-{version}').update(icon_choice=f'{old}-{version}')


class Migration(migrations.Migration):

    dependencies = [
        ('aquarium', '0020_icon_theme'),
    ]

    operations = [
        migrations.RunPython(rename_choices, restore_choices),
    ]
