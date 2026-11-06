from django import forms
from django.utils import timezone

from .models import (
    ParameterLog, Animal, AnimalGroup, ParameterType, Tank, Sump, SumpChamber,
    Equipment, DosingReservoir, MaintenanceRoutine, WaterChangeLog, WebcamFeed,
)

# Shared Tailwind class strings
INPUT = 'w-full px-4 py-2.5 bg-slate-800 border border-slate-700 rounded-xl text-white text-sm focus:outline-none focus:ring-2 focus:ring-cyan-500'
INPUT_NOSPIN = INPUT + ' [appearance:textfield] [&::-webkit-outer-spin-button]:appearance-none [&::-webkit-inner-spin-button]:appearance-none'
TEXTAREA = 'w-full px-4 py-2 bg-slate-800 border border-slate-700 rounded-xl text-slate-200 text-sm focus:outline-none focus:ring-2 focus:ring-cyan-500'
CHECKBOX = 'w-4 h-4 rounded border-slate-700 bg-slate-800 text-cyan-500 focus:ring-cyan-500'

# <input type="datetime-local"> only understands this format
DT_LOCAL_FORMAT = '%Y-%m-%dT%H:%M'
DT_INPUT_FORMATS = [DT_LOCAL_FORMAT, '%Y-%m-%dT%H:%M:%S', '%Y-%m-%d %H:%M:%S', '%Y-%m-%d %H:%M']


def _datetime_widget(css=INPUT):
    return forms.DateTimeInput(format=DT_LOCAL_FORMAT, attrs={'class': css, 'type': 'datetime-local'})


class DefaultNowMixin:
    """Makes a datetime-local field optional and fills in 'now' when it is left blank."""
    now_field = 'measured_at'

    def _setup_now_field(self):
        field = self.fields[self.now_field]
        field.required = False
        field.input_formats = DT_INPUT_FORMATS

    def clean(self):
        cleaned = super().clean()
        if not cleaned.get(self.now_field):
            cleaned[self.now_field] = timezone.now()
        return cleaned


class QuickParameterLogForm(DefaultNowMixin, forms.ModelForm):
    """Mobile-friendly quick add form for water parameters."""
    now_field = 'measured_at'

    class Meta:
        model = ParameterLog
        fields = ['parameter_type', 'value', 'notes', 'measured_at']
        widgets = {
            'parameter_type': forms.Select(attrs={
                'class': 'w-full px-4 py-3 bg-slate-800 border border-slate-700 rounded-xl text-white focus:outline-none focus:ring-2 focus:ring-cyan-500 text-lg'
            }),
            'value': forms.NumberInput(attrs={
                'class': 'w-full px-4 py-3 bg-slate-800 border border-slate-700 rounded-xl text-white focus:outline-none focus:ring-2 focus:ring-cyan-500 text-2xl font-bold tracking-wide text-center',
                'placeholder': '0.00',
                'step': 'any',
                'inputmode': 'decimal',
            }),
            'notes': forms.TextInput(attrs={
                'class': 'w-full px-4 py-2 bg-slate-800 border border-slate-700 rounded-xl text-slate-300 focus:outline-none focus:ring-2 focus:ring-cyan-500 text-sm',
                'placeholder': 'Optional note (e.g. before water change)'
            }),
            'measured_at': forms.DateTimeInput(format=DT_LOCAL_FORMAT, attrs={
                'class': 'w-full px-4 py-2 bg-slate-800 border border-slate-700 rounded-xl text-slate-400 focus:outline-none focus:ring-2 focus:ring-cyan-500 text-sm',
                'type': 'datetime-local'
            })
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._setup_now_field()


class ParameterSettingsForm(forms.ModelForm):
    """Form to edit parameter unit, decimal precision, ideal target range, and conversion."""
    convert_history = forms.BooleanField(
        required=False,
        initial=True,
        label="Convert Historical Measurements",
        help_text="Automatically convert all previously entered test logs to match the new unit"
    )

    class Meta:
        model = ParameterType
        fields = ['unit', 'decimal_places', 'min_ideal', 'max_ideal']
        widgets = {
            'unit': forms.TextInput(attrs={
                'class': 'w-full px-4 py-2.5 bg-slate-800 border border-slate-700 rounded-xl text-white font-semibold text-base focus:outline-none focus:ring-2 focus:ring-cyan-500',
                'placeholder': 'e.g. ppm, dKH, SG, °F, °C'
            }),
            'decimal_places': forms.NumberInput(attrs={
                'class': 'w-full px-4 py-2.5 bg-slate-800 border border-slate-700 rounded-xl text-white font-bold text-base text-center focus:outline-none focus:ring-2 focus:ring-cyan-500',
                'min': '0',
                'max': '4'
            }),
            'min_ideal': forms.NumberInput(attrs={
                'class': 'w-full px-4 py-2.5 bg-slate-800 border border-slate-700 rounded-xl text-white font-semibold text-base focus:outline-none focus:ring-2 focus:ring-cyan-500',
                'step': 'any'
            }),
            'max_ideal': forms.NumberInput(attrs={
                'class': 'w-full px-4 py-2.5 bg-slate-800 border border-slate-700 rounded-xl text-white font-semibold text-base focus:outline-none focus:ring-2 focus:ring-cyan-500',
                'step': 'any'
            }),
        }

    def clean_decimal_places(self):
        value = self.cleaned_data['decimal_places']
        if value > 4:
            raise forms.ValidationError("Use between 0 and 4 decimal places.")
        return value

    def clean(self):
        cleaned = super().clean()
        low, high = cleaned.get('min_ideal'), cleaned.get('max_ideal')
        if low is not None and high is not None and low > high:
            raise forms.ValidationError("Minimum target can't be higher than the maximum target.")
        return cleaned


class ParameterTypeForm(forms.ModelForm):
    """Create or edit a custom parameter (Nitrite, Ammonia, Potassium, Iodine...)."""
    class Meta:
        model = ParameterType
        fields = ['name', 'code', 'unit', 'decimal_places', 'min_ideal', 'max_ideal', 'color', 'display_order']
        widgets = {
            'name': forms.TextInput(attrs={'class': INPUT, 'placeholder': 'e.g. Nitrite'}),
            'code': forms.TextInput(attrs={'class': INPUT, 'placeholder': 'e.g. nitrite (lowercase, no spaces)'}),
            'unit': forms.TextInput(attrs={'class': INPUT, 'placeholder': 'e.g. ppm'}),
            'decimal_places': forms.NumberInput(attrs={'class': INPUT, 'min': '0', 'max': '4'}),
            'min_ideal': forms.NumberInput(attrs={'class': INPUT, 'step': 'any'}),
            'max_ideal': forms.NumberInput(attrs={'class': INPUT, 'step': 'any'}),
            'color': forms.TextInput(attrs={'class': INPUT, 'type': 'color'}),
            'display_order': forms.NumberInput(attrs={'class': INPUT, 'min': '0'}),
        }

    def clean(self):
        cleaned = super().clean()
        low, high = cleaned.get('min_ideal'), cleaned.get('max_ideal')
        if low is not None and high is not None and low > high:
            raise forms.ValidationError("Minimum target can't be higher than the maximum target.")
        if cleaned.get('decimal_places') is not None and cleaned['decimal_places'] > 4:
            self.add_error('decimal_places', "Use between 0 and 4 decimal places.")
        return cleaned


class ParameterLogEditForm(DefaultNowMixin, forms.ModelForm):
    """Fix a typo in an existing measurement."""
    now_field = 'measured_at'

    class Meta:
        model = ParameterLog
        fields = ['parameter_type', 'value', 'measured_at', 'notes']
        widgets = {
            'parameter_type': forms.Select(attrs={'class': INPUT}),
            'value': forms.NumberInput(attrs={'class': INPUT, 'step': 'any', 'inputmode': 'decimal'}),
            'measured_at': _datetime_widget(),
            'notes': forms.TextInput(attrs={'class': INPUT}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._setup_now_field()


class AnimalGroupForm(forms.ModelForm):
    """Modal form to create custom livestock groups/tags in GUI."""
    class Meta:
        model = AnimalGroup
        fields = ['name', 'icon', 'color', 'description']
        widgets = {
            'name': forms.TextInput(attrs={
                'class': 'w-full px-4 py-2.5 bg-slate-800 border border-slate-700 rounded-xl text-white text-sm focus:outline-none focus:ring-2 focus:ring-cyan-500',
                'placeholder': 'e.g. SPS Corals, School, Mated Pairs, Nano Fish'
            }),
            'icon': forms.TextInput(attrs={
                'class': 'w-full px-4 py-2.5 bg-slate-800 border border-slate-700 rounded-xl text-white text-sm focus:outline-none focus:ring-2 focus:ring-cyan-500',
                'placeholder': 'Emoji or icon e.g. 🐠, 🪸, 🦀, 🐌, 🦐, 🐡'
            }),
            'color': forms.TextInput(attrs={
                'class': 'w-full px-4 py-2.5 bg-slate-800 border border-slate-700 rounded-xl text-white text-sm focus:outline-none focus:ring-2 focus:ring-cyan-500',
                'type': 'color'
            }),
            'description': forms.TextInput(attrs={
                'class': 'w-full px-4 py-2 bg-slate-800 border border-slate-700 rounded-xl text-slate-300 text-sm focus:outline-none focus:ring-2 focus:ring-cyan-500',
                'placeholder': 'Optional brief notes about this group'
            }),
        }


class AnimalForm(forms.ModelForm):
    """Rich in-app form for adding/editing aquarium livestock."""
    new_group_name = forms.CharField(
        required=False,
        label="Or Create New Group",
        widget=forms.TextInput(attrs={
            'class': 'w-full px-4 py-2 bg-slate-800 border border-slate-700 rounded-xl text-white placeholder-slate-500 text-sm focus:outline-none focus:ring-2 focus:ring-cyan-500',
            'placeholder': 'e.g. Anemone, Tangs, Zoanthids...'
        })
    )

    class Meta:
        model = Animal
        fields = ['name', 'species', 'tank', 'groups', 'count', 'acquired_date', 'status', 'photo', 'notes']
        widgets = {
            'name': forms.TextInput(attrs={
                'class': 'w-full px-4 py-2.5 bg-slate-800 border border-slate-700 rounded-xl text-white text-base focus:outline-none focus:ring-2 focus:ring-cyan-500',
                'placeholder': 'e.g. Ocellaris Clownfish Pair, Blue Tang, Turbo Snail',
                'required': True
            }),
            'species': forms.TextInput(attrs={
                'class': 'w-full px-4 py-2.5 bg-slate-800 border border-slate-700 rounded-xl text-white text-sm focus:outline-none focus:ring-2 focus:ring-cyan-500',
                'placeholder': 'e.g. Amphiprion ocellaris (optional)'
            }),
            'tank': forms.Select(attrs={
                'class': 'w-full px-4 py-2.5 bg-slate-800 border border-slate-700 rounded-xl text-white text-sm focus:outline-none focus:ring-2 focus:ring-cyan-500'
            }),
            'groups': forms.CheckboxSelectMultiple(attrs={
                'class': 'rounded border-slate-700 text-cyan-500 focus:ring-cyan-500 bg-slate-800'
            }),
            'count': forms.NumberInput(attrs={
                'class': 'w-full px-4 py-2.5 bg-slate-800 border border-slate-700 rounded-xl text-white text-center font-bold text-lg focus:outline-none focus:ring-2 focus:ring-cyan-500',
                'min': '1',
            }),
            'acquired_date': forms.DateInput(format='%Y-%m-%d', attrs={
                'class': 'w-full px-4 py-2.5 bg-slate-800 border border-slate-700 rounded-xl text-white text-sm focus:outline-none focus:ring-2 focus:ring-cyan-500',
                'type': 'date'
            }),
            'status': forms.Select(attrs={
                'class': 'w-full px-4 py-2.5 bg-slate-800 border border-slate-700 rounded-xl text-white text-sm focus:outline-none focus:ring-2 focus:ring-cyan-500'
            }),
            'photo': forms.FileInput(attrs={
                'class': 'block w-full text-xs text-slate-400 file:mr-3 file:py-2 file:px-4 file:rounded-xl file:border-0 file:text-xs file:font-semibold file:bg-cyan-500/20 file:text-cyan-400 hover:file:bg-cyan-500/30 cursor-pointer',
                'accept': 'image/*'
            }),
            'notes': forms.Textarea(attrs={
                'class': 'w-full px-4 py-2 bg-slate-800 border border-slate-700 rounded-xl text-slate-200 text-sm focus:outline-none focus:ring-2 focus:ring-cyan-500',
                'rows': 3,
                'placeholder': 'Diet notes, coral placement (low/high flow), source store, quarantine history...'
            }),
        }

    def save(self, commit=True):
        instance = super().save(commit=commit)
        new_group = self.cleaned_data.get('new_group_name')
        if new_group:
            new_group = new_group.strip()
            if new_group:
                group_obj, _ = AnimalGroup.objects.get_or_create(name=new_group)
                if commit:
                    instance.groups.add(group_obj)
                else:
                    old_save_m2m = self.save_m2m

                    def new_save_m2m():
                        old_save_m2m()
                        instance.groups.add(group_obj)
                    self.save_m2m = new_save_m2m
        return instance


class VesselFormMixin:
    """Validation shared by the tank and sump forms."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Left blank is fine when the capacity is estimated from the dimensions.
        self.fields['volume_gallons'].required = False

    def clean(self):
        cleaned = super().clean()
        if cleaned.get('volume_gallons') is None and not self.errors.get('volume_gallons'):
            dims = [cleaned.get(f) for f in ('width', 'depth', 'height')]
            if all(dims):
                from .calculators import estimate_capacity_gallons
                cleaned['volume_gallons'] = estimate_capacity_gallons(
                    dims[0], dims[1], dims[2], cleaned.get('dimension_unit') or 'in',
                    cleaned.get('fill_percent') or 90)
            else:
                self.add_error('volume_gallons', "Enter the capacity, or fill in all three dimensions.")
        for field in ('width', 'depth', 'height'):
            val = cleaned.get(field)
            if val is not None and val <= 0:
                self.add_error(field, "Must be greater than zero.")
        pct = cleaned.get('fill_percent')
        if pct is not None and not (1 <= pct <= 100):
            self.add_error('fill_percent', "Use a value between 1 and 100.")
        vol = cleaned.get('volume_gallons')
        if vol is not None and vol <= 0:
            self.add_error('volume_gallons', "Must be greater than zero.")
        dims = [cleaned.get(f) for f in ('width', 'depth', 'height')]
        if any(dims) and not all(dims):
            self.add_error(None, "Enter all three dimensions (width, depth, height) or leave them all blank.")
        return cleaned


VESSEL_WIDGETS = {
    'dimension_unit': forms.Select(attrs={'class': INPUT}),
    'width': forms.NumberInput(attrs={'class': INPUT_NOSPIN, 'step': '0.1', 'inputmode': 'decimal', 'placeholder': 'Width'}),
    'depth': forms.NumberInput(attrs={'class': INPUT_NOSPIN, 'step': '0.1', 'inputmode': 'decimal', 'placeholder': 'Depth'}),
    'height': forms.NumberInput(attrs={'class': INPUT_NOSPIN, 'step': '0.1', 'inputmode': 'decimal', 'placeholder': 'Height'}),
    'fill_percent': forms.NumberInput(attrs={'class': INPUT_NOSPIN, 'step': '0.5', 'min': '1', 'max': '100'}),
    'capacity_is_manual': forms.CheckboxInput(attrs={'class': CHECKBOX}),
    'volume_gallons': forms.NumberInput(attrs={'class': INPUT_NOSPIN, 'step': '0.1', 'min': '0.1'}),
}


class TankForm(VesselFormMixin, forms.ModelForm):
    class Meta:
        model = Tank
        fields = ['name', 'is_primary', 'dimension_unit', 'width', 'depth', 'height',
                  'fill_percent', 'capacity_is_manual', 'volume_gallons', 'notes']
        widgets = {
            **VESSEL_WIDGETS,
            'name': forms.TextInput(attrs={'class': INPUT, 'placeholder': 'e.g. 120g Display Tank'}),
            'is_primary': forms.CheckboxInput(attrs={'class': CHECKBOX}),
            'notes': forms.Textarea(attrs={'class': TEXTAREA, 'rows': 2}),
        }


class SumpForm(VesselFormMixin, forms.ModelForm):
    class Meta:
        model = Sump
        fields = ['name', 'dimension_unit', 'width', 'depth', 'height',
                  'fill_percent', 'capacity_is_manual', 'volume_gallons', 'notes']
        widgets = {
            **VESSEL_WIDGETS,
            'name': forms.TextInput(attrs={'class': INPUT, 'placeholder': 'e.g. Basement Sump, Refugium'}),
            'notes': forms.Textarea(attrs={'class': TEXTAREA, 'rows': 2}),
        }


class SumpChamberForm(forms.ModelForm):
    class Meta:
        model = SumpChamber
        fields = ['name', 'chamber_type', 'position', 'share_percent', 'notes']
        widgets = {
            'name': forms.TextInput(attrs={'class': INPUT, 'placeholder': 'Optional, e.g. Chaeto refugium'}),
            'chamber_type': forms.Select(attrs={'class': INPUT}),
            'position': forms.NumberInput(attrs={'class': INPUT, 'min': '1'}),
            'share_percent': forms.NumberInput(attrs={'class': INPUT, 'step': '0.5', 'min': '0', 'max': '100'}),
            'notes': forms.Textarea(attrs={'class': TEXTAREA, 'rows': 2}),
        }

    def clean_share_percent(self):
        value = self.cleaned_data['share_percent']
        if value < 0 or value > 100:
            raise forms.ValidationError("Use a value between 0 and 100.")
        return value


class EquipmentForm(forms.ModelForm):
    class Meta:
        model = Equipment
        fields = ['tank', 'name', 'category', 'brand', 'wattage', 'max_flow_gph', 'power_setting_percent',
                  'flow_derate_percent', 'installed_date', 'maintenance_interval_days', 'last_serviced_date',
                  'status', 'notes']
        widgets = {
            'tank': forms.Select(attrs={'class': INPUT}),
            'name': forms.TextInput(attrs={'class': INPUT, 'placeholder': 'e.g. Radion XR30 G6 Pro'}),
            'category': forms.Select(attrs={'class': INPUT}),
            'brand': forms.TextInput(attrs={'class': INPUT, 'placeholder': 'e.g. EcoTech Marine'}),
            'wattage': forms.NumberInput(attrs={'class': INPUT, 'placeholder': 'Watts'}),
            'max_flow_gph': forms.NumberInput(attrs={'class': INPUT, 'placeholder': 'Rated max GPH (pumps / wavemakers)'}),
            'power_setting_percent': forms.NumberInput(attrs={'class': INPUT, 'min': '1', 'max': '100'}),
            'flow_derate_percent': forms.NumberInput(attrs={'class': INPUT, 'min': '0', 'max': '90'}),
            'installed_date': forms.DateInput(format='%Y-%m-%d', attrs={'class': INPUT, 'type': 'date'}),
            'maintenance_interval_days': forms.NumberInput(attrs={'class': INPUT, 'min': '1'}),
            'last_serviced_date': forms.DateInput(format='%Y-%m-%d', attrs={'class': INPUT, 'type': 'date'}),
            'status': forms.Select(attrs={'class': INPUT}),
            'notes': forms.Textarea(attrs={'class': TEXTAREA, 'rows': 2}),
        }

    def clean_power_setting_percent(self):
        value = self.cleaned_data['power_setting_percent']
        if not 1 <= value <= 100:
            raise forms.ValidationError("Use a value between 1 and 100.")
        return value

    def clean_flow_derate_percent(self):
        value = self.cleaned_data['flow_derate_percent']
        if not 0 <= value <= 90:
            raise forms.ValidationError("Use a value between 0 and 90.")
        return value

    def clean_maintenance_interval_days(self):
        value = self.cleaned_data['maintenance_interval_days']
        if value < 1:
            raise forms.ValidationError("Must be at least 1 day.")
        return value


class DosingReservoirForm(forms.ModelForm):
    class Meta:
        model = DosingReservoir
        fields = ['tank', 'name', 'reservoir_type', 'capacity', 'current_level', 'unit', 'daily_consumption', 'color']
        widgets = {
            'tank': forms.Select(attrs={'class': INPUT}),
            'name': forms.TextInput(attrs={'class': INPUT, 'placeholder': 'e.g. Alkalinity (Soda Ash), ATO RO/DI'}),
            'reservoir_type': forms.Select(attrs={'class': INPUT}),
            'capacity': forms.NumberInput(attrs={'class': INPUT, 'step': '0.1', 'min': '0.1'}),
            'current_level': forms.NumberInput(attrs={'class': INPUT, 'step': '0.1', 'min': '0'}),
            'unit': forms.TextInput(attrs={'class': INPUT, 'placeholder': 'ml, gal, or L'}),
            'daily_consumption': forms.NumberInput(attrs={'class': INPUT, 'step': '0.1', 'min': '0'}),
            'color': forms.TextInput(attrs={'class': INPUT, 'type': 'color'}),
        }

    def clean(self):
        cleaned = super().clean()
        cap, level = cleaned.get('capacity'), cleaned.get('current_level')
        if cap is not None and cap <= 0:
            self.add_error('capacity', "Size must be greater than zero.")
        if cap is not None and level is not None and level > cap:
            self.add_error('current_level', "Current level can't be more than the container size.")
        return cleaned


class WaterChangeLogForm(DefaultNowMixin, forms.ModelForm):
    now_field = 'performed_at'

    class Meta:
        model = WaterChangeLog
        fields = ['tank', 'gallons', 'salt_brand', 'target_salinity', 'notes', 'performed_at']
        widgets = {
            'tank': forms.Select(attrs={'class': INPUT}),
            'gallons': forms.NumberInput(attrs={'class': INPUT_NOSPIN, 'step': '0.5'}),
            'salt_brand': forms.TextInput(attrs={'class': INPUT, 'placeholder': 'e.g. Tropic Marin Pro'}),
            'target_salinity': forms.NumberInput(attrs={'class': INPUT_NOSPIN, 'step': '0.001'}),
            'notes': forms.TextInput(attrs={'class': TEXTAREA, 'placeholder': 'Temperature matched, cleaned glass'}),
            'performed_at': _datetime_widget(),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._setup_now_field()


class WebcamFeedForm(forms.ModelForm):
    class Meta:
        model = WebcamFeed
        fields = ['name', 'feed_url', 'feed_type', 'is_active', 'order']
        widgets = {
            'name': forms.TextInput(attrs={'class': INPUT, 'placeholder': 'e.g. Front view'}),
            'feed_url': forms.TextInput(attrs={'class': INPUT, 'placeholder': 'http://192.168.1.50:1984/api/stream.mjpeg?src=tank'}),
            'feed_type': forms.Select(attrs={'class': INPUT}),
            'is_active': forms.CheckboxInput(attrs={'class': CHECKBOX}),
            'order': forms.NumberInput(attrs={'class': INPUT, 'min': '0'}),
        }


class MaintenanceRoutineForm(forms.ModelForm):
    """Form to create and edit custom maintenance routines and interactive checklists."""
    checklist_raw = forms.CharField(
        widget=forms.Textarea(attrs={
            'class': 'w-full px-4 py-2.5 bg-slate-800 border border-slate-700 rounded-xl text-slate-200 text-sm focus:outline-none focus:ring-2 focus:ring-cyan-500 font-mono',
            'rows': 5,
            'placeholder': "Mix 10 gal fresh saltwater\nTurn off return pump and skimmer\nScrape glass and siphon detritus\nEmpty & clean skimmer collection cup\nRefill with new saltwater and verify salinity"
        }),
        help_text="Enter each checklist step on a new line (one task per line)",
        required=False
    )

    class Meta:
        model = MaintenanceRoutine
        fields = ['title', 'category', 'tank', 'frequency_days', 'notes']
        widgets = {
            'title': forms.TextInput(attrs={
                'class': 'w-full px-4 py-2.5 bg-slate-800 border border-slate-700 rounded-xl text-white text-sm focus:outline-none focus:ring-2 focus:ring-cyan-500',
                'placeholder': 'e.g. Weekly Water Change & Sump Siphon'
            }),
            'category': forms.Select(attrs={
                'class': 'w-full px-4 py-2.5 bg-slate-800 border border-slate-700 rounded-xl text-white text-sm focus:outline-none focus:ring-2 focus:ring-cyan-500'
            }),
            'tank': forms.Select(attrs={
                'class': 'w-full px-4 py-2.5 bg-slate-800 border border-slate-700 rounded-xl text-white text-sm focus:outline-none focus:ring-2 focus:ring-cyan-500'
            }),
            'frequency_days': forms.NumberInput(attrs={
                'class': 'w-full px-4 py-2.5 bg-slate-800 border border-slate-700 rounded-xl text-white text-sm [appearance:textfield] [&::-webkit-outer-spin-button]:appearance-none [&::-webkit-inner-spin-button]:appearance-none focus:outline-none focus:ring-2 focus:ring-cyan-500',
                'min': '1',
                'placeholder': 'e.g. 7 for weekly, 14 for bi-weekly, 30 for monthly'
            }),
            'notes': forms.Textarea(attrs={
                'class': 'w-full px-4 py-2 bg-slate-800 border border-slate-700 rounded-xl text-slate-200 text-sm focus:outline-none focus:ring-2 focus:ring-cyan-500',
                'rows': 2,
                'placeholder': 'Optional tips or special reminders for this routine'
            }),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance and self.instance.pk and self.instance.checklist_items:
            self.fields['checklist_raw'].initial = "\n".join(self.instance.checklist_items)

    def clean_frequency_days(self):
        value = self.cleaned_data['frequency_days']
        if value < 1:
            raise forms.ValidationError("Must repeat at least every 1 day.")
        return value

    def clean(self):
        cleaned_data = super().clean()
        raw_text = cleaned_data.get('checklist_raw') or ''
        # Split lines, strip whitespace, and discard blank lines
        items = [line.strip() for line in raw_text.splitlines() if line.strip()]
        self.instance.checklist_items = items
        return cleaned_data
