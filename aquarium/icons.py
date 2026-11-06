"""
The character icons. Each character is a pair of files in static/icons/nudibranch:
NN-some-name-young.png and NN-some-name-old.png. Add a pair there and it appears after a restart.
Small copies for the pages are made by `manage.py build_icon_thumbnails` when the app starts.
"""
import colorsys
import re
from functools import lru_cache
from pathlib import Path

from django.conf import settings
from PIL import Image

ICON_URL = '/static/icons/nudibranch/'
FALLBACK_ICON = '/static/icons/icon.svg'
YOUNG = '-young'
OLD = '-old'


def icon_dir():
    return Path(settings.BASE_DIR) / 'static' / 'icons' / 'nudibranch'


def thumbnail_dir():
    return icon_dir() / 'thumbs'


def _url_for(stem):
    if (thumbnail_dir() / f'{stem}.webp').exists():
        return f'{ICON_URL}thumbs/{stem}.webp'
    return f'{ICON_URL}{stem}.png'


def _label(base):
    return re.sub(r'^\d+-', '', base).replace('-', ' ').title()


@lru_cache(maxsize=1)
def character_icons():
    """[{'key', 'label', 'young', 'old', 'young_url', 'old_url'}] in file name order."""
    directory = icon_dir()
    characters = []
    seen = {}
    for path in sorted(directory.glob(f'*{YOUNG}.png')):
        base = path.stem[:-len(YOUNG)]
        old_stem = f'{base}{OLD}'
        has_old = (directory / f'{old_stem}.png').exists()
        label = _label(base)
        seen[label] = seen.get(label, 0) + 1
        if seen[label] > 1:
            label = f'{label} {seen[label]}'
        characters.append({
            'key': base,
            'label': label,
            'young': path.stem,
            'old': old_stem if has_old else path.stem,
            'young_url': _url_for(path.stem),
            'old_url': _url_for(old_stem if has_old else path.stem),
        })
    return characters


def _character_for(choice):
    for character in character_icons():
        if choice in (character['young'], character['old']):
            return character
    return None


def display_stem(choice, *, aged, old_allowed):
    """
    Which file to show for a chosen young or old icon, or '' if it's no longer available.
    `aged` means a retired system with aging on. Old icons otherwise need the setting that allows them.
    """
    character = _character_for(choice)
    if character is None:
        return ''
    if aged or (choice == character['old'] and old_allowed):
        return character['old']
    return character['young']


def retired_default_stem(pk):
    """A retired system on "Surprise me" has no chosen character, so give it a lasting old one."""
    characters = character_icons()
    return characters[pk % len(characters)]['old'] if characters else ''


def url_for_stem(stem):
    return _url_for(stem) if stem else ''


def file_for_stem(stem):
    thumbnail = thumbnail_dir() / f'{stem}.webp'
    return thumbnail if thumbnail.exists() else icon_dir() / f'{stem}.png'


@lru_cache(maxsize=256)
def _read_colors(path, _modified):
    with Image.open(path) as image:
        pixels = list(image.convert('RGBA').resize((64, 64)).getdata())
    buckets = {}
    for red, green, blue, alpha in pixels:
        hue, lightness, saturation = colorsys.rgb_to_hls(red / 255, green / 255, blue / 255)
        # Skip see-through, near-black, near-white and grey pixels: they say nothing about the colour.
        if alpha < 128 or lightness < .15 or lightness > .9 or saturation < .25:
            continue
        bucket = buckets.setdefault(int(hue * 24) % 24, {'weight': 0.0, 'red': 0.0, 'green': 0.0, 'blue': 0.0})
        weight = saturation * (1 - abs(lightness - .5))
        bucket['weight'] += weight
        bucket['red'] += red * weight
        bucket['green'] += green * weight
        bucket['blue'] += blue * weight
    if not buckets:
        return None

    def color_of(bucket):
        total = bucket['weight'] * 255
        hue, _, saturation = colorsys.rgb_to_hls(bucket['red'] / total, bucket['green'] / total, bucket['blue'] / total)
        return hue, saturation

    ranked = sorted(buckets.items(), key=lambda item: -item[1]['weight'])
    first_key, first = ranked[0]
    primary = color_of(first)
    for key, bucket in ranked[1:]:
        distance = min(abs(key - first_key), 24 - abs(key - first_key))
        if distance >= 4:  # at least 60 degrees around the colour wheel, so it reads as a second colour
            return primary, color_of(bucket)
    return primary, ((primary[0] + 1 / 12) % 1, primary[1])  # one-colour icon: use a neighbouring hue


def colors_from_file(path):
    """The (hue, saturation) of an image's two main colours, or None if it has no real colour."""
    try:
        return _read_colors(str(path), Path(path).stat().st_mtime)
    except (OSError, ValueError):
        return None


def young_version(choice):
    character = _character_for(choice)
    return character['young'] if character else choice


def random_pool():
    """What "Surprise me" picks from. Only young versions."""
    return [{'path': c['young_url'], 'style': c['label']} for c in character_icons()]


def fallback_url():
    characters = character_icons()
    return characters[0]['young_url'] if characters else FALLBACK_ICON
