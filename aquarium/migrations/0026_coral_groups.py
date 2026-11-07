"""Adds SPS, LPS and soft coral groups and an anemone group, and sorts the catalog's corals into them.

Existing animals that came from the catalog are added to their new group too. They stay in "Corals",
so nothing disappears from that filter.
"""
from django.db import migrations

NEW_GROUPS = [
    {'name': 'SPS Corals', 'icon': '🌿', 'color': '#a3e635', 'description': 'Small-polyp stony corals like Acropora and Montipora. Usually want strong light, strong flow and very stable water.'},
    {'name': 'LPS Corals', 'icon': '🧠', 'color': '#f97316', 'description': 'Large-polyp stony corals like hammers, torches and brains. Moderate light and flow.'},
    {'name': 'Soft Corals', 'icon': '🍄', 'color': '#f472b6', 'description': 'Leathers, zoanthids, mushrooms, polyps and gorgonians. No stony skeleton, and usually the hardiest.'},
    {'name': 'Anemones', 'icon': '🌺', 'color': '#e879f9', 'description': 'Anemones can move around the tank and sting nearby corals.'},
]

GROUP_FOR = {
    'Acan Echinata': 'LPS Corals',
    'Acan Lord': 'LPS Corals',
    'Acropora Millepora': 'SPS Corals',
    'Acropora Tenuis': 'SPS Corals',
    'Alveopora': 'LPS Corals',
    'Anthelia': 'Soft Corals',
    'Birdsnest Coral': 'SPS Corals',
    'Blastomussa': 'LPS Corals',
    'Bounce Mushroom': 'Soft Corals',
    'Branching Hammer Coral': 'LPS Corals',
    'Bubble Coral': 'LPS Corals',
    'Bubble Tip Anemone (BTA)': 'Anemones',
    'Button Coral': 'LPS Corals',
    'Cabbage Leather Coral': 'Soft Corals',
    'Candy Cane Coral': 'LPS Corals',
    'Carnation Coral': 'Soft Corals',
    'Chalice Coral': 'LPS Corals',
    'Clove Polyps': 'Soft Corals',
    'Colt Coral': 'Soft Corals',
    'Condylactis Anemone': 'Anemones',
    'Cyphastrea': 'SPS Corals',
    "Devil's Hand Leather Coral": 'Soft Corals',
    'Discosoma Mushroom': 'Soft Corals',
    'Duncan Coral': 'LPS Corals',
    'Elegance Coral': 'LPS Corals',
    'Favia': 'LPS Corals',
    'Favites': 'LPS Corals',
    'Finger Leather Coral': 'Soft Corals',
    'Frogspawn Coral': 'LPS Corals',
    'Galaxea': 'LPS Corals',
    'Goniopora': 'LPS Corals',
    'Green Star Polyps (GSP)': 'Soft Corals',
    "Haddon's Carpet Anemone": 'Anemones',
    'Hammer Coral': 'LPS Corals',
    'Hydnophora': 'SPS Corals',
    'Kenya Tree Coral': 'Soft Corals',
    'Leptoseris': 'LPS Corals',
    'Lobophyllia': 'LPS Corals',
    'Long Tentacle Anemone': 'Anemones',
    'Mini Maxi Carpet Anemone': 'Anemones',
    'Montipora Cap': 'SPS Corals',
    'Montipora Digitata': 'SPS Corals',
    'Montipora Setosa': 'SPS Corals',
    'Open Brain Coral': 'LPS Corals',
    'Pavona Cactus Coral': 'SPS Corals',
    'Pipe Organ Coral': 'Soft Corals',
    'Plate Coral': 'LPS Corals',
    'Pocillopora': 'SPS Corals',
    'Porites': 'SPS Corals',
    'Psammocora': 'SPS Corals',
    'Pulsing Xenia': 'Soft Corals',
    'Rhodactis Mushroom': 'Soft Corals',
    'Ricordea Florida': 'Soft Corals',
    'Ricordea Yuma': 'Soft Corals',
    'Ritteri Anemone': 'Anemones',
    'Rock Flower Anemone': 'Anemones',
    'Scolymia': 'LPS Corals',
    'Scroll Coral': 'LPS Corals',
    'Sea Fan': 'Soft Corals',
    'Sea Rod Gorgonian': 'Soft Corals',
    'Sebae Anemone': 'Anemones',
    'Stylophora': 'SPS Corals',
    'Sun Coral': 'LPS Corals',
    'Toadstool Leather Coral': 'Soft Corals',
    'Torch Coral': 'LPS Corals',
    'Yellow Polyps': 'Soft Corals',
    'Zoanthids & Palys': 'Soft Corals',
}


def forwards(apps, schema_editor):
    AnimalGroup = apps.get_model('aquarium', 'AnimalGroup')
    SpeciesCatalog = apps.get_model('aquarium', 'SpeciesCatalog')
    Animal = apps.get_model('aquarium', 'Animal')
    groups = {}
    for g in NEW_GROUPS:
        groups[g['name']], _ = AnimalGroup.objects.get_or_create(name=g['name'], defaults=g)
    for name, group in GROUP_FOR.items():
        # Only catalog entries still on the old default, so an edited suggestion is kept.
        SpeciesCatalog.objects.filter(name=name, suggested_group__in=['Corals', 'Invertebrates']).update(suggested_group=group)
        for animal in Animal.objects.filter(name=name):
            animal.groups.add(groups[group])


class Migration(migrations.Migration):
    dependencies = [('aquarium', '0025_mute_and_tank_wording')]
    operations = [migrations.RunPython(forwards, migrations.RunPython.noop)]
