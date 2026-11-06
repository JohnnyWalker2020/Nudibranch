"""RO/DI output estimate and fill-time maths. Plain Python, no Django imports."""

LITERS_PER_GAL = 3.78541
ML_PER_GAL = 3785.41
TEMP_CHANGE_PER_C = 1.03  # membrane output changes roughly 3% per degree C


def temperature_factor(feed_temp_f, rated_temp_f=77):
    delta_c = (float(feed_temp_f) - float(rated_temp_f)) * 5 / 9
    return TEMP_CHANGE_PER_C ** delta_c


def estimated_gph(rated_gpd, rated_psi=60, rated_temp_f=77, feed_psi=60, feed_temp_f=77, measured_gph=None):
    """
    Output in gallons per hour. A real timed measurement always wins.
    Otherwise: rating, scaled by pressure and temperature. Worn membranes and clogged
    prefilters reduce this further, which is why timing a real fill is worth doing.
    """
    if measured_gph:
        return float(measured_gph)
    rated_psi = float(rated_psi) or 60
    pressure = max(0.0, float(feed_psi)) / rated_psi
    return float(rated_gpd) / 24 * pressure * temperature_factor(feed_temp_f, rated_temp_f)


def to_gallons(amount, unit):
    """Converts a reservoir amount to gallons. Unknown units are treated as gallons."""
    amount = float(amount or 0)
    unit = (unit or '').strip().lower()
    if unit in ('ml', 'milliliter', 'milliliters'):
        return amount / ML_PER_GAL
    if unit in ('l', 'liter', 'liters', 'litre', 'litres'):
        return amount / LITERS_PER_GAL
    return amount


def fill_estimate(gallons, gph, waste_ratio=0, stop_at_percent=100):
    """Time and water used to make `gallons` of product, stopping at stop_at_percent of the amount."""
    gallons = max(0.0, float(gallons or 0)) * max(0.0, min(100.0, float(stop_at_percent))) / 100
    gph = float(gph or 0)
    if gph <= 0:
        return None
    minutes = gallons / gph * 60
    waste = gallons * float(waste_ratio or 0)
    return {
        'gallons': round(gallons, 2),
        'liters': round(gallons * LITERS_PER_GAL, 1),
        'minutes': round(minutes, 1),
        'seconds': int(round(minutes * 60)),
        'hours_label': format_duration(minutes * 60),
        'waste_gallons': round(waste, 1),
        'gph': round(gph, 2),
        'gpm': round(gph / 60, 3),
    }


def format_duration(seconds):
    seconds = int(round(seconds))
    hours, remainder = divmod(seconds, 3600)
    minutes = remainder // 60
    if hours:
        return f"{hours} h {minutes} min"
    if minutes:
        return f"{minutes} min"
    return f"{seconds} s"
