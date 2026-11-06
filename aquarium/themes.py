"""Per-system colour schemes. The pages use Tailwind's cyan, blue and slate classes, so a theme swaps those palettes."""
import json

STOCK_ICONS = [
    ('cyberpunk', 'Cyberpunk'),
    ('dragon', 'Dragon'),
    ('kpop_hunter', 'K-Pop Demon Hunter'),
    ('medieval_knight', 'Medieval Knight'),
    ('ninja_turtle', 'Ninja Turtle'),
    ('robot', 'Mecha Robot'),
    ('superhero', 'Superhero'),
    ('unicorn', 'Unicorn'),
    ('witch', 'Sorcerer Witch'),
]

# PLACEHOLDER art. To swap in final icons, replace static/icons/nudibranch/retired_*.svg, keeping the names.
RETIRED_ICONS = [
    ('retired_grandpa', 'Grandpa'),
    ('retired_grandma', 'Grandma'),
    ('retired_cane', 'Out for a Stroll'),
    ('retired_rocker', 'Rocking Chair'),
]

_ORANGE = {'50': '#fff7ed', '100': '#ffedd5', '200': '#fed7aa', '300': '#fdba74', '400': '#fb923c', '500': '#f97316',
           '600': '#ea580c', '700': '#c2410c', '800': '#9a3412', '900': '#7c2d12', '950': '#431407'}
_PINK = {'50': '#fdf2f8', '100': '#fce7f3', '200': '#fbcfe8', '300': '#f9a8d4', '400': '#f472b6', '500': '#ec4899',
         '600': '#db2777', '700': '#be185d', '800': '#9d174d', '900': '#831843', '950': '#500724'}
_EMERALD = {'50': '#ecfdf5', '100': '#d1fae5', '200': '#a7f3d0', '300': '#6ee7b7', '400': '#34d399', '500': '#10b981',
            '600': '#059669', '700': '#047857', '800': '#065f46', '900': '#064e3b', '950': '#022c22'}
_TEAL = {'50': '#f0fdfa', '100': '#ccfbf1', '200': '#99f6e4', '300': '#5eead4', '400': '#2dd4bf', '500': '#14b8a6',
         '600': '#0d9488', '700': '#0f766e', '800': '#115e59', '900': '#134e4a', '950': '#042f2e'}
_VIOLET = {'50': '#f5f3ff', '100': '#ede9fe', '200': '#ddd6fe', '300': '#c4b5fd', '400': '#a78bfa', '500': '#8b5cf6',
           '600': '#7c3aed', '700': '#6d28d9', '800': '#5b21b6', '900': '#4c1d95', '950': '#2e1065'}
_FUCHSIA = {'50': '#fdf4ff', '100': '#fae8ff', '200': '#f5d0fe', '300': '#f0abfc', '400': '#e879f9', '500': '#d946ef',
            '600': '#c026d3', '700': '#a21caf', '800': '#86198f', '900': '#701a75', '950': '#4a044e'}
_AMBER = {'50': '#fffbeb', '100': '#fef3c7', '200': '#fde68a', '300': '#fcd34d', '400': '#fbbf24', '500': '#f59e0b',
          '600': '#d97706', '700': '#b45309', '800': '#92400e', '900': '#78350f', '950': '#451a03'}
_RED = {'50': '#fef2f2', '100': '#fee2e2', '200': '#fecaca', '300': '#fca5a5', '400': '#f87171', '500': '#ef4444',
        '600': '#dc2626', '700': '#b91c1c', '800': '#991b1b', '900': '#7f1d1d', '950': '#450a0a'}


def _slate(base_700, base_800, base_900, base_950):
    return {'700': base_700, '800': base_800, '900': base_900, '950': base_950}


THEMES = {
    'ocean': {'name': 'Deep Ocean', 'swatch': ['#06b6d4', '#2563eb', '#0f172a'], 'colors': {}},
    'coral': {'name': 'Coral Reef', 'swatch': ['#f97316', '#db2777', '#1c1412'], 'colors': {
        'cyan': _ORANGE, 'blue': _PINK, 'slate': _slate('#4a3b36', '#33272a', '#211a1b', '#140f10')}},
    'kelp': {'name': 'Kelp Forest', 'swatch': ['#10b981', '#0d9488', '#0b1a16'], 'colors': {
        'cyan': _EMERALD, 'blue': _TEAL, 'slate': _slate('#2f4a42', '#1f332d', '#12211d', '#091411')}},
    'anemone': {'name': 'Anemone', 'swatch': ['#8b5cf6', '#c026d3', '#16112a'], 'colors': {
        'cyan': _VIOLET, 'blue': _FUCHSIA, 'slate': _slate('#3f3a5c', '#2b2742', '#1a172e', '#0f0c1f')}},
    'sunset': {'name': 'Sunset Lagoon', 'swatch': ['#f59e0b', '#dc2626', '#1a1408'], 'colors': {
        'cyan': _AMBER, 'blue': _RED, 'slate': _slate('#4a4230', '#332d20', '#211d14', '#14110a')}},
}
DEFAULT_THEME = 'ocean'
THEME_CHOICES = [(key, theme['name']) for key, theme in THEMES.items()]


def theme_colors_json(key):
    """Palette overrides for tailwind.config. Built only from the constants above, so safe to print into a page."""
    theme = THEMES.get(key) or THEMES[DEFAULT_THEME]
    return json.dumps(theme['colors'])


def background_color(key):
    theme = THEMES.get(key) or THEMES[DEFAULT_THEME]
    return theme['swatch'][2]
