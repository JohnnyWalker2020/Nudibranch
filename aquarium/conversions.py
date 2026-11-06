"""
Unit conversion utilities for reef aquarium water parameters.
Supports Temperature (°F/°C), Salinity (SG/ppt/mS/cm), Alkalinity (dKH/meq/L/ppm),
and Nutrients (ppm/ppb).
"""

# Common unit choices per parameter category
PARAMETER_UNIT_SUGGESTIONS = {
    'temperature': [
        ('°F', 'Fahrenheit (°F) - default 1 decimal', 1),
        ('°C', 'Celsius (°C) - default 1 decimal', 1),
    ],
    'salinity': [
        ('SG', 'Specific Gravity (SG, e.g. 1.026) - default 3 decimals', 3),
        ('ppt', 'Parts Per Thousand (ppt, e.g. 35) - default 1 decimal', 1),
        ('mS/cm', 'Conductivity (mS/cm, e.g. 53.0) - default 1 decimal', 1),
    ],
    'alkalinity': [
        ('dKH', 'German Carbonate Hardness (dKH, e.g. 8.4) - default 1 decimal', 1),
        ('meq/L', 'Milliequivalents per Liter (meq/L, e.g. 3.0) - default 2 decimals', 2),
        ('ppm', 'Parts Per Million CaCO3 (ppm, e.g. 150) - default 0 decimals', 0),
    ],
    'calcium': [
        ('ppm', 'Parts Per Million (ppm, e.g. 430) - default 0 decimals', 0),
        ('mg/L', 'Milligrams per Liter (mg/L, e.g. 430) - default 0 decimals', 0),
    ],
    'magnesium': [
        ('ppm', 'Parts Per Million (ppm, e.g. 1350) - default 0 decimals', 0),
        ('mg/L', 'Milligrams per Liter (mg/L, e.g. 1350) - default 0 decimals', 0),
    ],
    'nitrate': [
        ('ppm', 'Parts Per Million (ppm, e.g. 5.0) - default 1 decimal', 1),
        ('ppb', 'Parts Per Billion (ppb, e.g. 5000) - default 0 decimals', 0),
    ],
    'phosphate': [
        ('ppm', 'Parts Per Million PO4 (ppm, e.g. 0.03) - default 2 decimals', 2),
        ('ppb', 'Phosphorus ppb P (Hanna HI736, e.g. 10) - default 0 decimals', 0),
    ],
    'ph': [
        ('pH', 'pH Scale (e.g. 8.20) - default 2 decimals', 2),
    ],
}

_PPT_UNITS = ['ppt', 'psu', 'parts per thousand']
_SG_UNITS = ['sg', 'specific gravity']
_MS_UNITS = ['ms/cm', 'ms']
_MEQ_UNITS = ['meq/l', 'meq']


def convert_value(val_float: float, from_unit: str, to_unit: str, code: str = '') -> float:
    """
    Converts a numerical reading from one unit to another.
    `code` is the parameter code (e.g. 'phosphate'); it keeps parameter-specific
    formulas (like ppm PO4 -> ppb P) from being applied to unrelated parameters
    such as nitrate.
    If no conversion formula exists or units match, returns the original value.
    """
    from_u = from_unit.strip().lower()
    to_u = to_unit.strip().lower()
    code = (code or '').strip().lower()

    if from_u == to_u:
        return val_float

    # 1. Temperature (°F <-> °C)
    if from_u in ('°f', 'f'):
        if to_u in ('°c', 'c'):
            return (val_float - 32.0) * (5.0 / 9.0)
    elif from_u in ('°c', 'c'):
        if to_u in ('°f', 'f'):
            return (val_float * (9.0 / 5.0)) + 32.0

    # 2. Salinity (SG <-> ppt <-> mS/cm)
    # 1.0264 SG ~ 35.0 ppt ~ 53.0 mS/cm
    if from_u in _SG_UNITS:
        if to_u in _PPT_UNITS:
            return (val_float - 1.0) * 1340.0
        elif to_u in _MS_UNITS:
            return (val_float - 1.0) * 1340.0 * 1.5143
    elif from_u in _PPT_UNITS:
        if to_u in _SG_UNITS:
            return 1.0 + (val_float / 1340.0)
        elif to_u in _MS_UNITS:
            return val_float * 1.5143
    elif from_u in _MS_UNITS:
        if to_u in _PPT_UNITS:
            return val_float / 1.5143
        elif to_u in _SG_UNITS:
            return 1.0 + ((val_float / 1.5143) / 1340.0)

    # 3. Alkalinity (dKH <-> meq/L <-> ppm CaCO3)
    # 1 meq/L = 2.8 dKH = 50 ppm CaCO3; 1 dKH = 17.86 ppm CaCO3
    if code in ('', 'alkalinity'):
        if from_u == 'dkh':
            if to_u in _MEQ_UNITS:
                return val_float / 2.8
            elif to_u in ('ppm', 'mg/l'):
                return val_float * 17.86
        elif from_u in _MEQ_UNITS:
            if to_u == 'dkh':
                return val_float * 2.8
            elif to_u in ('ppm', 'mg/l'):
                return val_float * 50.0
        elif from_u in ('ppm', 'mg/l'):
            if to_u == 'dkh':
                return val_float / 17.86
            elif to_u in _MEQ_UNITS:
                return val_float / 50.0

    # 4. Phosphate (ppm PO4 <-> ppb Phosphorus P)
    # ppb P = ppm PO4 * 1000 / 3.066
    if code == 'phosphate':
        if from_u in ('ppm', 'mg/l') and to_u in ('ppb', 'ppb p'):
            return (val_float * 1000.0) / 3.066
        elif from_u in ('ppb', 'ppb p') and to_u in ('ppm', 'mg/l'):
            return (val_float * 3.066) / 1000.0

    # 5. General ppm <-> ppb (1000:1)
    if from_u == 'ppm' and to_u in ('ppb', 'ppb p'):
        return val_float * 1000.0
    elif from_u in ('ppb', 'ppb p') and to_u == 'ppm':
        return val_float / 1000.0

    # 6. ppm <-> mg/L (1:1)
    if (from_u == 'ppm' and to_u == 'mg/l') or (from_u == 'mg/l' and to_u == 'ppm'):
        return val_float

    # Default fallback: cannot convert automatically, return original
    return val_float


def suggest_decimals(unit: str, code: str = '') -> int:
    """Returns recommended decimal places for a unit/parameter code."""
    u = unit.strip().lower()
    c = code.strip().lower()

    if u in ['ppm', 'ppb', 'mg/l'] and c in ['calcium', 'magnesium', 'alkalinity']:
        return 0
    if u in ['sg', 'specific gravity']:
        return 3
    if u in ['ph']:
        return 2
    if c == 'phosphate' and u == 'ppm':
        return 2
    if u in ['°f', '°c', 'dkh', 'ppt']:
        return 1
    if u in ['meq/l', 'meq']:
        return 2

    # Fallback default
    return 1
