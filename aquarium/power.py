"""Electricity use and cost estimates from equipment wattage."""
from .models import AppSettings, Equipment

DAYS_PER_MONTH = 30.44

# Typical hours per day at full rated power when the user hasn't entered their own figure.
TYPICAL_HOURS = {
    'lighting': 9,
    'return_pump': 24,
    'wavemaker': 24,
    'skimmer': 24,
    'heater': 6,
    'dosing': 0.5,
    'ato': 0.5,
    'feeder': 0.2,
    'filtration': 24,
    'monitoring': 24,
    'other': 24,
}
# Wattage scales with the speed/power setting for these categories.
SCALES_WITH_SETTING = ('lighting', 'return_pump', 'wavemaker')


def daily_kwh(watts, hours, setting_percent=100):
    return float(watts or 0) * (float(setting_percent or 100) / 100) * float(hours or 0) / 1000


def equipment_row(eq, rate):
    typical = TYPICAL_HOURS.get(eq.category, 24)
    hours = float(eq.hours_per_day) if eq.hours_per_day is not None else typical
    setting = eq.power_setting_percent if eq.category in SCALES_WITH_SETTING else 100
    kwh = 0.0 if eq.status == 'offline' else daily_kwh(eq.wattage, hours, setting)
    return {
        'equipment': eq,
        'hours': hours,
        'is_typical': eq.hours_per_day is None,
        'setting': setting,
        'kwh_day': round(kwh, 2),
        'cost_month': round(kwh * DAYS_PER_MONTH * rate, 2),
    }


def power_summary(tank=None):
    settings_obj = AppSettings.load()
    rate = float(settings_obj.electricity_rate)
    gear = Equipment.objects.select_related('tank').exclude(wattage__isnull=True).exclude(wattage=0)
    if tank is not None:
        gear = gear.filter(tank=tank)
    rows = sorted((equipment_row(eq, rate) for eq in gear), key=lambda r: -r['kwh_day'])
    kwh_day = sum(r['kwh_day'] for r in rows)
    return {
        'rows': rows,
        'kwh_day': round(kwh_day, 2),
        'kwh_month': round(kwh_day * DAYS_PER_MONTH, 1),
        'cost_day': round(kwh_day * rate, 2),
        'cost_month': round(kwh_day * DAYS_PER_MONTH * rate, 2),
        'cost_year': round(kwh_day * 365 * rate, 2),
        'rate': rate,
        'currency': settings_obj.currency_symbol,
    }
