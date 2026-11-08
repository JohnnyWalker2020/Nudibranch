"""Popular equipment with the specs this app uses, to fill in the equipment form.

Figures are the makers' ratings as listed by retailers (2026): rated flow is at no lift, max head is where flow stops,
and watts are the most it draws (DC pumps and LEDs usually draw less at lower settings). Where sellers disagree,
the most consistent figure is used, or the more cautious one. Everything stays editable on the form.
"""

CATALOG = [
    # (group, name, brand, category, watts, rated gph, max head ft)
    ('Return pumps', 'Vectra S2', 'EcoTech Marine', 'return_pump', 72, 1400, 11.5),
    ('Return pumps', 'Vectra M2', 'EcoTech Marine', 'return_pump', 96, 2000, 21.5),
    ('Return pumps', 'Vectra L2', 'EcoTech Marine', 'return_pump', 150, 3100, 21.5),
    ('Return pumps', 'Syncra Silent 1.5', 'Sicce', 'return_pump', 23, 357, 6.0),
    ('Return pumps', 'Syncra Silent 2.0', 'Sicce', 'return_pump', 35, 568, 6.5),
    ('Return pumps', 'Syncra Silent 3.0', 'Sicce', 'return_pump', 48, 714, 9.8),
    ('Return pumps', 'Syncra Silent 4.0', 'Sicce', 'return_pump', 85, 951, 12.5),
    ('Return pumps', 'DCP-5000', 'Jebao', 'return_pump', 40, 1450, 13.0),
    ('Return pumps', 'DCP-8000', 'Jebao', 'return_pump', 65, 2113, 17.0),
    ('Wavemakers', 'VorTech MP10wQD', 'EcoTech Marine', 'wavemaker', 18, 1500, None),
    ('Wavemakers', 'VorTech MP40wQD', 'EcoTech Marine', 'wavemaker', 38, 4500, None),
    ('Lights', 'Radion XR15 G6 Pro', 'EcoTech Marine', 'lighting', 95, None, None),
    ('Lights', 'Radion XR30 G6 Pro', 'EcoTech Marine', 'lighting', 215, None, None),
    ('Lights', 'Hydra 32 HD', 'Aqua Illumination', 'lighting', 90, None, None),
    ('Lights', 'Hydra 64 HD', 'Aqua Illumination', 'lighting', 135, None, None),
    ('Lights', 'Prime 16HD', 'Aqua Illumination', 'lighting', 55, None, None),
    ('Heaters', 'Jäger 100 W', 'Eheim', 'heater', 100, None, None),
    ('Heaters', 'Jäger 150 W', 'Eheim', 'heater', 150, None, None),
    ('Heaters', 'Jäger 200 W', 'Eheim', 'heater', 200, None, None),
    ('Heaters', 'Jäger 300 W', 'Eheim', 'heater', 300, None, None),
]


def as_options():
    """[(group, [(index, 'Brand Name'), ...]), ...] for a grouped menu, and the specs by index for the page."""
    groups, specs = {}, {}
    for index, (group, name, brand, category, watts, gph, head) in enumerate(CATALOG):
        groups.setdefault(group, []).append((str(index), f"{brand} {name}"))
        specs[str(index)] = {'name': f"{brand} {name}", 'brand': brand, 'category': category, 'wattage': watts,
                             'max_flow_gph': gph, 'max_head': head}
    return list(groups.items()), specs
