"""
Aquarium calculators for Salt Mixing, Evaporation, and Reservoir Estimations.
"""

# Salt mix grams per gallon needed to achieve 1.026 SG (35 ppt)
SALT_MIX_RECIPES = {
    'tropic_marin_pro': {
        'name': 'Tropic Marin Pro-Reef',
        'grams_per_gallon': 148.0,  # ~39 g/L
        'cups_per_gallon': 0.50,
    },
    'red_sea_blue': {
        'name': 'Red Sea Salt (Blue Bucket)',
        'grams_per_gallon': 145.0,  # ~38.2 g/L
        'cups_per_gallon': 0.49,
    },
    'red_sea_coral_pro': {
        'name': 'Red Sea Coral Pro',
        'grams_per_gallon': 152.0,  # ~40.2 g/L
        'cups_per_gallon': 0.52,
    },
    'instant_ocean': {
        'name': 'Instant Ocean Standard',
        'grams_per_gallon': 140.0,
        'cups_per_gallon': 0.50,
    },
    'reef_crystals': {
        'name': 'Instant Ocean Reef Crystals',
        'grams_per_gallon': 146.0,
        'cups_per_gallon': 0.50,
    },
    'fritz_pro': {
        'name': 'Fritz Pro RPM',
        'grams_per_gallon': 144.0,
        'cups_per_gallon': 0.50,
    },
    'aquaforest': {
        'name': 'AquaForest Reef Salt',
        'grams_per_gallon': 148.0,
        'cups_per_gallon': 0.51,
    },
}


def calculate_salt_mix(
    volume: float = 10.0,
    volume_unit: str = 'gal',
    brand_key: str = 'tropic_marin_pro',
    target_salinity: float = 1.026,
    salinity_unit: str = 'sg',
    gallons: float = None
):
    """
    Calculates salt mix amount (grams, ounces, lbs, and cups) needed for a water change.
    Supports volume in Gallons or Liters, and Salinity in Specific Gravity (SG) or ppt.
    Base target is 1.026 SG (35 ppt).
    """
    # Backward compatibility if gallons passed as positional/keyword
    if gallons is not None:
        volume = gallons
        volume_unit = 'gal'

    recipe = SALT_MIX_RECIPES.get(brand_key, SALT_MIX_RECIPES['tropic_marin_pro'])

    # Normalize volume to gallons for recipe calculation
    v_unit = volume_unit.lower()
    if v_unit in ['l', 'liter', 'liters']:
        gal_equiv = volume / 3.78541
        liters_equiv = volume
    else:
        gal_equiv = volume
        liters_equiv = volume * 3.78541

    # Normalize salinity to SG
    s_unit = salinity_unit.lower()
    if s_unit == 'ppt':
        ppt_val = target_salinity
        # 35 ppt corresponds to 1.026 SG
        sg_val = 1.0 + (ppt_val / 35.0) * 0.026
    else:
        sg_val = target_salinity
        ppt_val = round((target_salinity - 1.0) / 0.026 * 35.0, 1) if target_salinity > 1.0 else 35.0

    # Scale factor against standard 1.026 SG
    scale_factor = (sg_val - 1.0) / 0.026 if sg_val > 1.0 else 1.0

    grams_total = gal_equiv * recipe['grams_per_gallon'] * scale_factor
    ounces_total = grams_total / 28.3495
    lbs_total = grams_total / 453.592
    cups_total = gal_equiv * recipe['cups_per_gallon'] * scale_factor

    return {
        'brand_name': recipe['name'],
        'volume': round(volume, 2),
        'volume_unit': volume_unit,
        'gallons': round(gal_equiv, 2),
        'liters': round(liters_equiv, 2),
        'target_salinity': target_salinity,
        'salinity_unit': salinity_unit,
        'sg': round(sg_val, 3),
        'ppt': round(ppt_val, 1),
        'grams': round(grams_total, 1),
        'ounces': round(ounces_total, 1),
        'lbs': round(lbs_total, 2),
        'cups': round(cups_total, 1),
    }
