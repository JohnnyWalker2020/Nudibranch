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


def calculate_salt_mix(gallons: float, brand_key: str = 'tropic_marin_pro', target_salinity: float = 1.026):
    """
    Calculates salt mix amount (grams, lbs, and cups) needed for a water change.
    Base target is 1.026 SG (35 ppt).
    """
    recipe = SALT_MIX_RECIPES.get(brand_key, SALT_MIX_RECIPES['tropic_marin_pro'])
    
    # Scale proportionally if user targets e.g. 1.024 or 1.025
    scale_factor = (target_salinity - 1.0) / 0.026 if target_salinity > 1.0 else 1.0
    
    grams_total = gallons * recipe['grams_per_gallon'] * scale_factor
    lbs_total = grams_total / 453.592
    cups_total = gallons * recipe['cups_per_gallon'] * scale_factor

    return {
        'brand_name': recipe['name'],
        'gallons': gallons,
        'target_salinity': target_salinity,
        'grams': round(grams_total, 1),
        'lbs': round(lbs_total, 2),
        'cups': round(cups_total, 1),
    }
