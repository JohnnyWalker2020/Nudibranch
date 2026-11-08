"""Common tanks to start the Add / Edit tank form from.

Sizes are approximate: makers differ by an inch or so, and glass and trim eat into the water. The form says so and
everything stays editable.

- Standard glass tanks: outside length × depth × height in inches. Only the dimensions are filled, so the form
  estimates the water from the box and the usable-water %.
- Reef-ready systems: display dimensions in cm, plus the maker's (or retailers') display water in litres, which goes in
  as the capacity. Their sumps sit in the cabinet, so add the sump separately on the tank page.
"""

L_PER_GAL = 3.78541


def _std(name, w, d, h):
    return {'name': name, 'unit': 'in', 'width': w, 'depth': d, 'height': h}


def _reef(name, w, d, h, display_liters, note):
    return {'name': name, 'unit': 'cm', 'width': w, 'depth': d, 'height': h,
            'gallons': round(display_liters / L_PER_GAL, 1), 'liters': display_liters, 'note': note}


AIO = "The filter section at the back isn't included."
REEFER = "The sump in the cabinet isn't included, so add it as a sump on the tank page."

TANK_PRESETS = [
    {'group': 'Standard glass tanks', 'tanks': [
        _std('5.5 gallon', 16, 8, 10),
        _std('10 gallon', 20, 10, 12),
        _std('20 gallon high', 24, 12, 16),
        _std('20 gallon long', 30, 12, 12),
        _std('29 gallon', 30, 12, 18),
        _std('30 gallon breeder', 36, 18, 12),
        _std('40 gallon breeder', 36, 18, 16),
        _std('40 gallon long', 48, 12, 16),
        _std('55 gallon', 48, 13, 21),
        _std('65 gallon', 36, 18, 24),
        _std('75 gallon', 48, 18, 21),
        _std('90 gallon', 48, 18, 24),
        _std('120 gallon (4 ft)', 48, 24, 24),
        _std('125 gallon', 72, 18, 21),
        _std('150 gallon', 72, 18, 28),
        _std('180 gallon', 72, 24, 25),
    ]},
    {'group': 'Waterbox all-in-one', 'tanks': [
        _reef('Waterbox AIO 25 Peninsula', 60, 40, 40, 90, AIO),
        _reef('Waterbox AIO 35.2', 60, 50, 45, 125, AIO),
        _reef('Waterbox AIO 50.3', 90, 50, 45, 186, AIO),
    ]},
    {'group': 'Red Sea Reefer (display only)', 'tanks': [
        _reef('Red Sea Reefer 170', 60, 50, 51, 128, REEFER),
        _reef('Red Sea Reefer 250', 90, 50, 53, 203, REEFER),
        _reef('Red Sea Reefer 350', 120, 50, 53, 273, REEFER),
    ]},
]
