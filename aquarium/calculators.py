"""
Aquarium calculators: salt mixing, tank capacity, pump flow / turnover and dosing estimates.

Everything in this module is plain Python (no Django imports) so it can be unit tested
on its own and imported from models without circular-import problems.
"""
import math

GAL_PER_LITER = 1 / 3.78541
LITERS_PER_GAL = 3.78541
IN3_PER_GALLON = 231.0

MAX_TARGET_SG = 1.1  # roughly 135 ppt, well past anything anyone would mix

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
        # Label: about 390 g per 10 L of RO/DI for 33 ppt (1.025 SG).
        # 39 g/L at 33 ppt -> 41.36 g/L at 35 ppt -> 156.6 g per US gallon.
        'name': 'AquaForest Reef Salt',
        'grams_per_gallon': 156.6,
        'cups_per_gallon': 0.54,
    },
}


def calculate_salt_mix(
    volume: float = 10.0,
    volume_unit: str = 'gal',
    brand_key: str = 'tropic_marin_pro',
    target_salinity: float = 1.026,
    salinity_unit: str = 'sg',
    gallons: float = None,
    start_salinity: float = 0.0
):
    """
    Calculates salt mix amount (grams, ounces, lbs, and cups) needed for a water change.
    Supports volume in Gallons or Liters, and Salinity in Specific Gravity (SG) or ppt.
    Base target is 1.026 SG (35 ppt). start_salinity is what the water already measures, in the
    same unit as the target; 0 means fresh water, and only the difference is added as salt.
    """
    # Backward compatibility if gallons passed as positional/keyword
    if gallons is not None:
        volume = gallons
        volume_unit = 'gal'

    for number in (volume, target_salinity, start_salinity):
        if not math.isfinite(number):
            raise ValueError('Please enter real numbers.')
    if volume < 0:
        raise ValueError("The volume can't be negative.")

    recipe = SALT_MIX_RECIPES.get(brand_key, SALT_MIX_RECIPES['tropic_marin_pro'])

    # Normalize volume to gallons for recipe calculation
    v_unit = volume_unit.lower()
    if v_unit in ['l', 'liter', 'liters']:
        gal_equiv = volume / LITERS_PER_GAL
        liters_equiv = volume
    else:
        gal_equiv = volume
        liters_equiv = volume * LITERS_PER_GAL

    # Normalize salinity to SG
    s_unit = salinity_unit.lower()
    if s_unit == 'ppt':
        ppt_val = target_salinity
        # 35 ppt corresponds to 1.026 SG
        sg_val = 1.0 + (ppt_val / 35.0) * 0.026
    else:
        sg_val = target_salinity
        ppt_val = round((target_salinity - 1.0) / 0.026 * 35.0, 1) if target_salinity > 1.0 else 0.0
    if sg_val > MAX_TARGET_SG:
        raise ValueError('That target salinity is far above seawater. Check the number and the SG or ppt setting.')

    # Scale factor against standard 1.026 SG. Fresh water or below needs no salt at all.
    scale_factor = (sg_val - 1.0) / 0.026 if sg_val > 1.0 else 0.0

    # Salt already in the water, on the same scale. Never below fresh water.
    if s_unit == 'ppt':
        start_scale = max(start_salinity, 0.0) / 35.0
    else:
        start_scale = (start_salinity - 1.0) / 0.026 if start_salinity > 1.0 else 0.0
    already_at_target = start_scale > 0 and start_scale >= scale_factor
    scale_factor = max(scale_factor - start_scale, 0.0)

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
        'start_salinity': start_salinity,
        'already_at_target': already_at_target,
        'sg': round(sg_val, 3),
        'ppt': round(ppt_val, 1),
        'grams': round(grams_total, 1),
        'ounces': round(ounces_total, 1),
        'lbs': round(lbs_total, 2),
        'cups': round(cups_total, 1),
    }


# ---------------------------------------------------------------------------
# Light (PAR) at depth
# ---------------------------------------------------------------------------

# Rough rules of thumb. Real results depend on the fixture, its height, its optics and where you measure.
PPF_PER_WATT = 1.8        # umol of light per joule, typical of a reef LED
USABLE_LIGHT = 0.6        # the rest misses the water or is lost at the surface and the glass
PAR_HALVES_EVERY_IN = 11  # how quickly average light falls off going down through a tank
PAR_ZONES = [(50, 'Very low'), (150, 'Low: most soft corals'), (300, 'Medium: most LPS'), (500, 'High: most SPS')]


def par_zone(par):
    for limit, label in PAR_ZONES:
        if par < limit:
            return label
    return 'Very high: acclimate corals slowly'


def par_estimate(watts, width, depth, height, unit='in'):
    """Rough average PAR near the top, in the middle and on the bottom of a tank, or None if something's missing."""
    to_inches = 1 / 2.54 if unit == 'cm' else 1
    width, depth, height = (float(x or 0) * to_inches for x in (width, depth, height))
    if watts <= 0 or width <= 0 or depth <= 0 or height <= 0:
        return None
    area_m2 = (width * 0.0254) * (depth * 0.0254)
    surface = watts * PPF_PER_WATT * USABLE_LIGHT / area_m2
    levels = []
    for label, inches in (('Near the top', min(2.0, height)), ('Middle', height / 2), ('Bottom', height)):
        par = surface * 0.5 ** (inches / PAR_HALVES_EVERY_IN)
        rounded = int(round(par, -1))
        levels.append({'label': label, 'inches': round(inches, 1), 'cm': round(inches * 2.54), 'par': rounded, 'zone': par_zone(rounded)})
    return levels


# ---------------------------------------------------------------------------
# Tank / sump capacity
# ---------------------------------------------------------------------------

def box_volume_gallons(width, depth, height, unit='in'):
    """Geometric volume (gallons) of a rectangular box. Dimensions in inches or cm."""
    w, d, h = float(width), float(depth), float(height)
    if (unit or 'in').lower() == 'cm':
        liters = (w * d * h) / 1000.0
        return liters * GAL_PER_LITER
    return (w * d * h) / IN3_PER_GALLON


def estimate_capacity_gallons(width, depth, height, unit='in', fill_percent=90.0):
    """
    Estimated usable water volume. `fill_percent` accounts for glass/acrylic
    thickness, the water line sitting below the rim, bracing, etc.
    """
    if not (width and depth and height):
        return None
    pct = max(1.0, min(100.0, float(fill_percent)))
    return round(box_volume_gallons(width, depth, height, unit) * pct / 100.0, 1)


# ---------------------------------------------------------------------------
# Plumbing volume
# ---------------------------------------------------------------------------

# Nominal PVC pipe size -> (label, Schedule 40 inside diameter in inches).
PIPE_SIZES = {
    '0.5': ('1/2"', 0.622),
    '0.75': ('3/4"', 0.824),
    '1': ('1"', 1.049),
    '1.25': ('1-1/4"', 1.380),
    '1.5': ('1-1/2"', 1.610),
    '2': ('2"', 2.067),
}


def pipe_volume_gallons(length_ft, inside_diameter_in, fill_percent=100):
    """
    Water held in a pipe: cross-section area x length x how full it runs.
    `inside_diameter_in` is the real inside diameter in inches (see PIPE_SIZES for Sch 40 PVC).
    """
    if not length_ft or not inside_diameter_in:
        return 0.0
    fill = max(0.0, min(100.0, float(fill_percent if fill_percent is not None else 100)))
    area_in2 = math.pi * (float(inside_diameter_in) / 2.0) ** 2
    return round(area_in2 * float(length_ft) * 12.0 / IN3_PER_GALLON * fill / 100.0, 2)


# ---------------------------------------------------------------------------
# Pump flow and turnover
# ---------------------------------------------------------------------------

# Rule-of-thumb ranges (turnovers per hour). These are community guidelines, not hard rules.
RETURN_TURNOVER_RANGE = (4.0, 10.0)        # return pump flow / total system volume
CIRCULATION_TURNOVER_RANGE = (20.0, 50.0)  # (return + wavemakers) / display volume, mixed reef


def estimate_flow_gph(max_flow_gph, power_percent=100, derate_percent=0):
    """
    Estimated real flow of a pump or wavemaker.
    flow = rated max x power setting x (1 - head/plumbing loss).
    Power-to-flow is treated as linear, which is a reasonable approximation for
    most DC pumps; real curves vary by model, so treat the result as an estimate.
    """
    if not max_flow_gph:
        return None
    power = max(0.0, min(100.0, float(power_percent if power_percent is not None else 100)))
    derate = max(0.0, min(95.0, float(derate_percent or 0)))
    return float(max_flow_gph) * (power / 100.0) * (1.0 - derate / 100.0)


FT_PER_M = 3.28084


def estimate_flow_at_head(max_flow_gph, max_head_ft, head_ft, power_percent=100):
    """
    Estimated return-pump flow lifting water `head_ft`, from the two numbers on the box: rated max flow (at no
    lift) and max head (the height where flow stops). The curve between them is taken as a straight line, and a
    slower speed shrinks it by the pump affinity laws (flow with speed, head with speed squared). Real curves bow a
    little, so treat it as an estimate. Returns 0 when the pump can't lift that high at this speed.
    """
    if not max_flow_gph or not max_head_ft or head_ft is None:
        return None
    speed = max(0.0, min(100.0, float(power_percent if power_percent is not None else 100))) / 100.0
    shutoff = float(max_head_ft) * speed * speed
    head = max(0.0, float(head_ft))
    if speed <= 0 or head >= shutoff:
        return 0.0
    return float(max_flow_gph) * speed * (1.0 - head / shutoff)


def gph_to_lph(gph):
    return gph * LITERS_PER_GAL if gph is not None else None


def _rate(value, rng):
    if value is None:
        return 'unknown'
    if value < rng[0]:
        return 'low'
    if value > rng[1]:
        return 'high'
    return 'ok'


def turnover_summary(display_gallons, system_gallons, return_gph, wavemaker_gph):
    """Turnover figures for a tank given summed return-pump and wavemaker flow (gph)."""
    display = float(display_gallons or 0)
    system = float(system_gallons or 0) or display
    return_gph = float(return_gph or 0)
    wave_gph = float(wavemaker_gph or 0)

    return_turnover = round(return_gph / system, 1) if system and return_gph else None
    total_gph = return_gph + wave_gph
    circulation = round(total_gph / display, 1) if display and total_gph else None

    return {
        'return_gph': round(return_gph),
        'wavemaker_gph': round(wave_gph),
        'total_gph': round(total_gph),
        'return_lph': round(return_gph * LITERS_PER_GAL),
        'total_lph': round(total_gph * LITERS_PER_GAL),
        'return_turnover': return_turnover,
        'circulation_turnover': circulation,
        'return_status': _rate(return_turnover, RETURN_TURNOVER_RANGE),
        'circulation_status': _rate(circulation, CIRCULATION_TURNOVER_RANGE),
        'return_range': RETURN_TURNOVER_RANGE,
        'circulation_range': CIRCULATION_TURNOVER_RANGE,
        'system_gallons': round(system, 1),
        'display_gallons': round(display, 1),
    }


# ---------------------------------------------------------------------------
# Dosing estimates
# ---------------------------------------------------------------------------

DKH_PER_MEQ = 2.8  # 1 meq/L alkalinity = 2.8 dKH (same constant used by conversions.py)

# Conservative per-day increase limits. These are commonly quoted hobby guidelines
# (alkalinity especially); they are editable defaults in the UI, not hard rules.
MAX_DAILY_RAISE = {
    'alkalinity': 1.4,   # dKH / day
    'calcium': 20.0,     # ppm / day
    'magnesium': 50.0,   # ppm / day
    'nitrate': 2.0,      # ppm / day
    'phosphate': 0.02,   # ppm / day
    'potassium': 10.0,   # ppm / day
    'iodine': 0.01,      # ppm / day
    'strontium': 1.0,    # ppm / day
}

DOSE_PARAMETERS = {
    'alkalinity': {'name': 'Alkalinity', 'unit': 'dKH', 'decimals': 2},
    'calcium': {'name': 'Calcium', 'unit': 'ppm', 'decimals': 1},
    'magnesium': {'name': 'Magnesium', 'unit': 'ppm', 'decimals': 0},
    # These use the product's own label rather than chemistry worked out here. `typical` is roughly natural
    # seawater, offered as a target only when the parameter isn't being tracked with its own range.
    'nitrate': {'name': 'Nitrate', 'unit': 'ppm', 'decimals': 1, 'label_only': True,
                'note': "Usually only needed in very clean tanks where nitrate reads near zero."},
    'phosphate': {'name': 'Phosphate', 'unit': 'ppm', 'decimals': 3, 'label_only': True,
                  'note': "Usually only needed where phosphate reads near zero. It's easy to overshoot, so dose small amounts."},
    'potassium': {'name': 'Potassium', 'unit': 'ppm', 'decimals': 0, 'label_only': True, 'typical': 400,
                  'note': "Test before dosing. Salt mixes and water changes often keep this close to normal."},
    'iodine': {'name': 'Iodine', 'unit': 'ppm', 'decimals': 3, 'label_only': True, 'typical': 0.06,
               'note': "Hard to test accurately at home, and too much can harm livestock. Many keepers rely on water changes instead."},
    'strontium': {'name': 'Strontium', 'unit': 'ppm', 'decimals': 1, 'label_only': True, 'typical': 8,
                  'note': "Hard to test accurately at home. Only dose if a test shows it's low."},
}

# Molar masses (g/mol). Amount needed is computed from stoichiometry, not from brand recipes.
DOSE_CHEMICALS = {
    'baking_soda': {
        'name': 'Sodium bicarbonate (baking soda, NaHCO3)',
        'parameter': 'alkalinity', 'molar_mass': 84.007, 'equivalents': 1,
    },
    'soda_ash': {
        'name': 'Sodium carbonate, anhydrous (soda ash, Na2CO3)',
        'parameter': 'alkalinity', 'molar_mass': 105.989, 'equivalents': 2,
    },
    'calcium_chloride_dihydrate': {
        'name': 'Calcium chloride dihydrate (CaCl2·2H2O)',
        'parameter': 'calcium', 'molar_mass': 147.01, 'ion_mass': 40.078,
    },
    'calcium_chloride_anhydrous': {
        'name': 'Calcium chloride anhydrous (CaCl2)',
        'parameter': 'calcium', 'molar_mass': 110.98, 'ion_mass': 40.078,
    },
    'magnesium_chloride_hexahydrate': {
        'name': 'Magnesium chloride hexahydrate (MgCl2·6H2O)',
        'parameter': 'magnesium', 'molar_mass': 203.30, 'ion_mass': 24.305,
    },
    'epsom_salt': {
        'name': 'Epsom salt, magnesium sulfate heptahydrate (MgSO4·7H2O)',
        'parameter': 'magnesium', 'molar_mass': 246.47, 'ion_mass': 24.305,
    },
}


def grams_per_unit_raise(chemical_key, liters):
    """Grams of dry chemical that raise `liters` of water by 1 unit (1 dKH, or 1 ppm)."""
    chem = DOSE_CHEMICALS[chemical_key]
    if chem['parameter'] == 'alkalinity':
        meq_per_l = 1.0 / DKH_PER_MEQ
        mg_per_l = meq_per_l * chem['molar_mass'] / chem['equivalents']
    else:
        mg_per_l = chem['molar_mass'] / chem['ion_mass']  # mg chemical per 1 mg/L of Ca or Mg
    return mg_per_l * liters / 1000.0


def dose_estimate(parameter, chemical_key, current, target, system_gallons,
                  solution_g_per_l=None, max_daily_raise=None, daily_loss=0.0,
                  label_raise=None, label_ml=None, label_gallons=None):
    """
    Estimate how much to add to move `parameter` from `current` to `target`.

    Returns dry grams (always, when a dry chemical is selected) and ml of the user's
    solution (if `solution_g_per_l` is given). If the product is a commercial one,
    pass the label's "X ml raises Y per Z gallons" as label_ml / label_raise / label_gallons.
    `daily_loss` is how much the parameter drops per day from consumption, which sets
    the maintenance dose needed to hold the level steady.
    """
    if parameter not in DOSE_PARAMETERS:
        raise ValueError('Unknown parameter')
    gallons = float(system_gallons)
    if gallons <= 0:
        raise ValueError('System volume must be greater than zero')
    liters = gallons * LITERS_PER_GAL

    current = float(current)
    target = float(target)
    for number in (gallons, current, target, max_daily_raise, daily_loss, solution_g_per_l, label_raise, label_ml, label_gallons):
        if number is not None and not math.isfinite(float(number)):
            raise ValueError('Please enter real numbers.')
    for number in (label_raise, label_ml, label_gallons):
        if number is not None and float(number) < 0:
            raise ValueError("The label amounts can't be negative.")
    delta = target - current
    max_daily = float(max_daily_raise) if max_daily_raise and float(max_daily_raise) > 0 else MAX_DAILY_RAISE[parameter]
    daily_loss = max(0.0, float(daily_loss or 0))
    unit = DOSE_PARAMETERS[parameter]['unit']

    result = {
        'parameter': parameter,
        'unit': unit,
        'system_gallons': round(gallons, 1),
        'system_liters': round(liters, 1),
        'current': current,
        'target': target,
        'delta': round(delta, 3),
        'max_daily_raise': max_daily,
        'needs_raise': delta > 0,
        'warnings': [],
    }

    # --- ml per unit of raise ---
    ml_per_unit = None
    g_per_unit = None
    if label_ml and label_raise and label_gallons:
        # commercial product: label_ml raises label_raise units in label_gallons of water
        ml_per_unit = float(label_ml) * (gallons / float(label_gallons)) / float(label_raise)
        result['mode'] = 'label'
    elif chemical_key:
        if chemical_key not in DOSE_CHEMICALS:
            raise ValueError('Unknown chemical')
        if DOSE_CHEMICALS[chemical_key]['parameter'] != parameter:
            raise ValueError('That chemical does not adjust the selected parameter')
        g_per_unit = grams_per_unit_raise(chemical_key, liters)
        if solution_g_per_l and float(solution_g_per_l) > 0:
            ml_per_unit = g_per_unit / float(solution_g_per_l) * 1000.0
        result['mode'] = 'dry'
    else:
        raise ValueError('Choose a chemical or enter a product label')

    result['grams_per_unit'] = round(g_per_unit, 3) if g_per_unit is not None else None
    result['ml_per_unit'] = round(ml_per_unit, 2) if ml_per_unit is not None else None

    # --- one-off correction ---
    if delta > 0:
        result['correction_grams'] = round(g_per_unit * delta, 2) if g_per_unit is not None else None
        result['correction_ml'] = round(ml_per_unit * delta, 1) if ml_per_unit is not None else None
        days = max(1, math.ceil(delta / max_daily))
        result['correction_days'] = days
        result['correction_per_day_raise'] = round(delta / days, 3)
        result['correction_per_day_grams'] = round(g_per_unit * delta / days, 2) if g_per_unit is not None else None
        result['correction_per_day_ml'] = round(ml_per_unit * delta / days, 1) if ml_per_unit is not None else None
        if days > 1:
            result['warnings'].append(
                f"Raising {round(delta, 2)} {unit} in one go exceeds the {max_daily:g} {unit}/day guideline, "
                f"so the correction is split over {days} days. Re-test between doses."
            )
    else:
        result['correction_grams'] = 0
        result['correction_ml'] = 0 if ml_per_unit is not None else None
        result['correction_days'] = 0
        if delta < 0:
            result['warnings'].append(
                f"Current level is already {round(-delta, 2)} {unit} above target. Don't dose; "
                f"let consumption bring it down or dilute with a water change."
            )

    # --- maintenance (hold the level against daily consumption) ---
    result['daily_loss'] = round(daily_loss, 3)
    result['maintenance_grams_per_day'] = round(g_per_unit * daily_loss, 2) if g_per_unit is not None else None
    result['maintenance_ml_per_day'] = round(ml_per_unit * daily_loss, 1) if ml_per_unit is not None else None

    result['warnings'].append(
        "Estimates assume the stated volume and ideal mixing. Test after dosing and adjust; "
        "go slowly with livestock in the tank."
    )
    return result


def estimate_daily_change(points):
    """
    Least-squares slope (units per day) from [(datetime, value), ...].
    Returns None if there are fewer than 2 points or they span less than half a day.
    A negative slope means the parameter is dropping (being consumed).
    Only meaningful for periods when nothing was being dosed.
    """
    pts = sorted(points, key=lambda p: p[0])
    if len(pts) < 2:
        return None
    t0 = pts[0][0]
    xs = [(p[0] - t0).total_seconds() / 86400.0 for p in pts]
    ys = [float(p[1]) for p in pts]
    if xs[-1] < 0.5:
        return None
    n = len(xs)
    mean_x = sum(xs) / n
    mean_y = sum(ys) / n
    denom = sum((x - mean_x) ** 2 for x in xs)
    if denom == 0:
        return None
    return sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys)) / denom
