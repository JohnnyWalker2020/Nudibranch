"""ICP elements: the extra things a lab water test (ICP-OES) reports, added as parameters.

They're marked as trace parameters, so they stay off the All chart, come after your regular tests in every
list, and have no dashboard card until you turn one on. Existing parameters with the same code are left alone.

The ranges are rough: mostly natural seawater levels, with common reef-keeping guidance for metals that should be
near zero. Labs publish their own targets, and they don't all agree, so edit a range to match your lab's report.
"""
from django.db import migrations, models

# (code, name, unit, decimals, low alert, ideal from, ideal to, high alert, colour)
ICP_ELEMENTS = [
    # Major and minor elements, reported in mg/L (the same as ppm)
    ('sodium', 'Sodium', 'mg/L', 0, 9500, 10000, 11000, 11500, '#94a3b8'),
    ('sulfur', 'Sulfur', 'mg/L', 0, 800, 850, 950, 1000, '#facc15'),
    ('potassium', 'Potassium', 'ppm', 0, 350, 380, 420, 450, '#a855f7'),
    ('strontium', 'Strontium', 'ppm', 1, 5, 7, 9, 12, '#f472b6'),
    ('bromine', 'Bromine', 'mg/L', 1, 50, 60, 75, 90, '#b45309'),
    ('boron', 'Boron', 'mg/L', 2, None, 4, 6, 10, '#65a30d'),
    # Trace elements, reported in µg/L (the same as ppb). Iodine stays in ppm, like home test kits.
    ('iodine', 'Iodine', 'ppm', 3, 0.02, 0.05, 0.07, 0.12, '#7c3aed'),
    ('lithium', 'Lithium', 'µg/L', 0, None, 150, 250, 400, '#0ea5e9'),
    ('silicon', 'Silicon', 'µg/L', 0, None, 0, 500, 1500, '#78716c'),
    ('phosphorus', 'Phosphorus (ICP)', 'µg/L', 0, 3, 10, 35, 100, '#ca8a04'),
    ('barium', 'Barium', 'µg/L', 1, None, 5, 20, 50, '#14b8a6'),
    ('molybdenum', 'Molybdenum', 'µg/L', 1, None, 8, 15, 30, '#6366f1'),
    ('iron', 'Iron', 'µg/L', 2, None, 0, 3, 10, '#dc2626'),
    ('manganese', 'Manganese', 'µg/L', 2, None, 0, 3, 10, '#db2777'),
    ('zinc', 'Zinc', 'µg/L', 2, None, 0, 8, 20, '#64748b'),
    ('vanadium', 'Vanadium', 'µg/L', 2, None, 0, 3, 10, '#0891b2'),
    ('copper', 'Copper', 'µg/L', 2, None, 0, 2, 5, '#ea580c'),
    ('nickel', 'Nickel', 'µg/L', 2, None, 0, 2, 5, '#4d7c0f'),
    ('cobalt', 'Cobalt', 'µg/L', 2, None, 0, 0.5, 2, '#1d4ed8'),
    ('chromium', 'Chromium', 'µg/L', 2, None, 0, 0.5, 2, '#15803d'),
    ('selenium', 'Selenium', 'µg/L', 2, None, 0, 0.5, 2, '#be123c'),
    ('titanium', 'Titanium', 'µg/L', 2, None, 0, 1, 5, '#9ca3af'),
    ('aluminium', 'Aluminium', 'µg/L', 1, None, 0, 10, 30, '#cbd5e1'),
    ('tin', 'Tin', 'µg/L', 2, None, 0, 1, 5, '#a3a3a3'),
    ('arsenic', 'Arsenic', 'µg/L', 2, None, 0, 3, 10, '#991b1b'),
    ('antimony', 'Antimony', 'µg/L', 2, None, 0, 1, 3, '#57534e'),
    ('lead', 'Lead', 'µg/L', 2, None, 0, 0.5, 2, '#334155'),
    ('cadmium', 'Cadmium', 'µg/L', 2, None, 0, 0.1, 0.5, '#e11d48'),
    ('mercury', 'Mercury', 'µg/L', 2, None, 0, 0.1, 0.5, '#7f1d1d'),
]


def add_elements(apps, schema_editor):
    ParameterType = apps.get_model('aquarium', 'ParameterType')
    for position, (code, name, unit, decimals, low, start, end, high, colour) in enumerate(ICP_ELEMENTS):
        if ParameterType.objects.filter(code=code).exists() or ParameterType.objects.filter(name=name).exists():
            continue
        ParameterType.objects.create(
            code=code, name=name, unit=unit, decimal_places=decimals, low_limit=low, min_ideal=start, max_ideal=end,
            high_limit=high, color=colour, display_order=100 + position, is_trace=True, show_on_dashboard=False,
        )


class Migration(migrations.Migration):
    dependencies = [('aquarium', '0029_dose_log')]

    operations = [
        migrations.AddField(
            model_name='parametertype', name='is_trace',
            field=models.BooleanField(default=False, help_text='An ICP or trace element: left off the All chart and listed after the others'),
        ),
        migrations.AddField(
            model_name='parametertype', name='show_on_dashboard',
            field=models.BooleanField(default=True, help_text='Show a card for it on the dashboard'),
        ),
        migrations.AddField(
            model_name='appsettings', name='icp_enabled',
            field=models.BooleanField(default=False, verbose_name='Enable ICP elements', help_text="Adds about 30 elements from lab (ICP) water tests, like boron, iodine and copper. They're listed after your regular tests and stay off the All chart and the dashboard until you choose them."),
        ),
        migrations.RunPython(add_elements, migrations.RunPython.noop),
    ]
