"""Template helpers: the app's drawn icons, the shared add/edit/delete buttons, and Arrange card order.

    {% load nudi %}
    {% icon 'glue' %}                                   just the picture
    {% act 'edit' url %}                                a link button: picture + word
    {% act 'flush' button=True %}                       a submit button, inside a form that posts
    {% act 'add' url label='Add sump' primary=True %}   the big gradient button a page leads with
"""
import json

from django import template
from django.utils.html import format_html
from django.utils.safestring import mark_safe

register = template.Library()

# Drawn on a 24 x 24 grid, in their own colours so they read the same on every theme.
ICONS = {
    # A cardboard parcel, for adding things.
    'box': (
        '<path d="M3 8l9 4v10l-9-4z" fill="#b9804a"/>'
        '<path d="M21 8l-9 4v10l9-4z" fill="#9a6434"/>'
        '<path d="M3 8l9-4 9 4-9 4z" fill="#dcaa6e"/>'
        '<path d="M7.5 6l9 4v2.6" fill="none" stroke="#f3dcae" stroke-width="1.8"/>'
        '<path d="M14 16.5l4.5-2" stroke="#7a4a22" stroke-width="1" stroke-linecap="round"/>'
    ),
    # A fish in a bag of water, for adding livestock.
    'fishbag': (
        '<path d="M8.6 4.2h6.8l-1.2 2c3.6 1.6 5.8 4.8 5.8 8.6 0 4-3.6 6.9-8 6.9s-8-2.9-8-6.9c0-3.8 2.2-7 5.8-8.6z" '
        'fill="#e0f2fe" fill-opacity=".25" stroke="#bae6fd" stroke-width="1"/>'
        '<path d="M4.25 12.6h15.5c.17.7.25 1.4.25 2.2 0 4-3.6 6.9-8 6.9s-8-2.9-8-6.9c0-.8.08-1.5.25-2.2z" '
        'fill="#38bdf8" fill-opacity=".6"/>'
        '<path d="M8.4 3.2c1.2.7 2.4 1 3.6 1s2.4-.3 3.6-1" fill="none" stroke="#f472b6" stroke-width="1.6" stroke-linecap="round"/>'
        '<ellipse cx="11.2" cy="16.4" rx="3.1" ry="1.9" fill="#fb923c"/>'
        '<path d="M14 16.4l2.6-1.8v3.6z" fill="#fb923c"/>'
        '<path d="M11.6 14.6v3.6" stroke="#fff" stroke-width=".9"/>'
        '<circle cx="9.6" cy="16" r=".55" fill="#0f172a"/>'
        '<circle cx="15.5" cy="10.5" r=".7" fill="#fff" fill-opacity=".7"/>'
    ),
    # A tube of superglue (frag glue) with a drop on the nozzle, for editing.
    'glue': (
        '<g transform="rotate(-38 12 12)">'
        '<path d="M2.6 10.3l1-.8h10.9a1 1 0 0 1 1 1v3a1 1 0 0 1-1 1H3.6l-1-.8z" fill="#e2e8f0"/>'
        '<rect x="5.6" y="9.5" width="4.6" height="5" fill="#ef4444"/>'
        '<path d="M7 11.2h1.8M7 12.8h1.8" stroke="#fff" stroke-width=".8"/>'
        '<path d="M15.5 10.4l2.9 1v1.2l-2.9 1z" fill="#94a3b8"/>'
        '<rect x="18.4" y="11.35" width="3.6" height="1.3" rx=".5" fill="#f59e0b"/>'
        '</g>'
        '<path d="M20.4 9.1s-1.2 1.5-1.2 2.3a1.2 1.2 0 0 0 2.4 0c0-.8-1.2-2.3-1.2-2.3z" fill="#f8fafc"/>'
    ),
    # A rubbish bin, for deleting equipment and other things.
    'bin': (
        '<path d="M5.2 7.5h13.6l-1.1 12.6a2 2 0 0 1-2 1.9H8.3a2 2 0 0 1-2-1.9z" fill="#64748b"/>'
        '<rect x="3.5" y="4.6" width="17" height="2.6" rx="1.1" fill="#94a3b8"/>'
        '<path d="M9.8 2.8h4.4v1.8H9.8z" fill="#94a3b8"/>'
        '<path d="M9.4 10.5v8M12 10.5v8M14.6 10.5v8" stroke="#cbd5e1" stroke-width="1.3" stroke-linecap="round"/>'
    ),
    # A toilet, for removing livestock and corals.
    'toilet': (
        '<rect x="3.5" y="2.8" width="7" height="9.6" rx="1.3" fill="#f1f5f9"/>'
        '<rect x="5" y="4.4" width="3" height="1.1" rx=".55" fill="#94a3b8"/>'
        '<path d="M3.5 12.4h17c0 3.4-2.4 5.6-5.8 6.2l.8 2.9H8.6l.7-3.1c-3.5-.6-5.8-2.7-5.8-6z" fill="#e2e8f0"/>'
        '<rect x="9.4" y="10.6" width="11.6" height="1.9" rx=".95" fill="#cbd5e1"/>'
        '<path d="M11.5 14.2c1.8.1 3.6.5 5.2 1.3" fill="none" stroke="#38bdf8" stroke-width="1.3" stroke-linecap="round"/>'
    ),
    # A plug pulled out of its socket, for taking equipment off a tank (it stays in the list).
    'unplug': (
        '<path d="M2.5 13h4.5" stroke="#64748b" stroke-width="2" stroke-linecap="round"/>'
        '<rect x="7" y="9.4" width="5.2" height="7.2" rx="1.6" fill="#cbd5e1"/>'
        '<path d="M12.2 11.3h2.4M12.2 14.7h2.4" stroke="#e2e8f0" stroke-width="1.4" stroke-linecap="round"/>'
        '<rect x="17.2" y="7.6" width="4.3" height="10.8" rx="1.1" fill="#475569"/>'
        '<path d="M18.6 11.3h1.5M18.6 14.7h1.5" stroke="#0f172a" stroke-width="1.3" stroke-linecap="round"/>'
        '<path d="M15.6 7.8l.7 1.4M15.6 18.2l.7-1.4M15.4 13h.9" stroke="#fbbf24" stroke-width="1.1" stroke-linecap="round"/>'
    ),
    # A PVC elbow with a drip, for plumbing.
    'pipe': (
        '<path d="M2 7.5h8.5a6 6 0 0 1 6 6V21" fill="none" stroke="#e2e8f0" stroke-width="5"/>'
        '<rect x="6.5" y="4" width="2.4" height="7" rx=".6" fill="#94a3b8"/>'
        '<rect x="13" y="15" width="7" height="2.4" rx=".6" fill="#94a3b8"/>'
        '<path d="M21 4.5s-1.4 1.8-1.4 2.7a1.4 1.4 0 0 0 2.8 0c0-.9-1.4-2.7-1.4-2.7z" fill="#38bdf8"/>'
    ),
    # A glass sump split by baffles, half full of water.
    'sump': (
        '<rect x="3" y="10" width="18" height="9.2" fill="#38bdf8" fill-opacity=".45"/>'
        '<path d="M2.5 5.5v13a1.5 1.5 0 0 0 1.5 1.5h16a1.5 1.5 0 0 0 1.5-1.5v-13" fill="none" stroke="#94a3b8" stroke-width="1.4"/>'
        '<path d="M8.5 5.5v11M12.5 8v12M15.5 5.5v11" stroke="#e2e8f0" stroke-width="1.2"/>'
        '<path d="M4.5 12.5c.7-.4 1.4-.4 2.1 0M17.3 12.5c.7-.4 1.4-.4 2.1 0" fill="none" stroke="#e0f2fe" stroke-width=".9" stroke-linecap="round"/>'
    ),
    # A little headstone, for livestock no longer with us.
    'headstone': (
        '<path d="M6 21V10a6 6 0 0 1 12 0v11z" fill="#94a3b8"/>'
        '<path d="M6 10a6 6 0 0 1 12 0" fill="none" stroke="#cbd5e1" stroke-width="1"/>'
        '<path d="M12 8.2v6M9.6 10.4h4.8" stroke="#475569" stroke-width="1.5" stroke-linecap="round"/>'
        '<path d="M3 21h18" stroke="#4ade80" stroke-width="2" stroke-linecap="round"/>'
        '<path d="M5 20.2l.6-1.6M8 20.3l.4-1.3M16.3 20.3l.4-1.4M19 20.2l.5-1.5" stroke="#4ade80" stroke-width="1" stroke-linecap="round"/>'
    ),
    # Stacked cards with the middle one lifted out, for Arrange.
    'arrange': (
        '<rect x="3" y="3.5" width="18" height="5" rx="1.5" fill="#64748b"/>'
        '<rect x="5" y="10" width="18" height="5" rx="1.5" fill="#22d3ee"/>'
        '<rect x="3" y="16.5" width="18" height="5" rx="1.5" fill="#64748b"/>'
        '<path d="M8 12.5h4" stroke="#0f172a" stroke-width="1.4" stroke-linecap="round"/>'
    ),
}

# What each button means, and the picture and word it shows unless told otherwise.
ACTIONS = {
    'add': ('box', 'Add'),
    'add_livestock': ('fishbag', 'Add'),
    'edit': ('glue', 'Edit'),
    'delete': ('bin', 'Delete'),
    'flush': ('toilet', 'Flush'),
    'remove': ('unplug', 'Take off'),
}


@register.simple_tag
def icon(name, size='w-4 h-4', extra=''):
    shapes = ICONS.get(name)
    if shapes is None:
        return ''
    return mark_safe(f'<svg class="nudi-icon shrink-0 {size} {extra}" viewBox="0 0 24 24" aria-hidden="true" focusable="false">{shapes}</svg>')


@register.simple_tag
def act(kind, href='', label=None, title='', primary=False, button=False, compact=False, extra='', name='', value='', suffix=''):
    """One add / edit / delete button, so they look the same everywhere.
    suffix is added to the link as text (a #anchor or ?next=), since the add filter can't join a string and a number.
    compact: the picture alone (the word still goes to screen readers and the hover text), for tight spots."""
    picture, default_label = ACTIONS[kind]
    href = f'{href}{suffix}'
    label = label or default_label
    title = title or label
    css = 'act act-primary' if primary else 'act'
    css += f' act-{kind}'
    if compact:
        css += ' act-compact'
    if extra:
        css += ' ' + extra
    img = icon(picture, 'w-5 h-5' if primary else 'w-4 h-4')
    text = format_html('<span class="sr-only">{}</span>', label) if compact else format_html('<span>{}</span>', label)
    if button:
        named = format_html(' name="{}" value="{}"', name, value) if name else ''
        return format_html('<button type="submit" class="{}" title="{}"{}>{}{}</button>', css, title, named, img, text)
    return format_html('<a href="{}" class="{}" title="{}">{}{}</a>', href, css, title, img, text)


@register.simple_tag
def card_order(page):
    """The saved Arrange order for a page, as JSON for arrange.js ([] = the page's own order)."""
    from aquarium.models import AppSettings
    order = (AppSettings.load().card_order or {}).get(page, [])
    return mark_safe(json.dumps([k for k in order if isinstance(k, str)]).replace('<', '\\u003c'))
