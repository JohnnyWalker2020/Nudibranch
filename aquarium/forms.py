from django import forms
from .models import (
    ParameterLog, Animal, AnimalGroup, ParameterType,
    Tank, Equipment, DosingReservoir, MaintenanceRoutine, WaterChangeLog
)


class QuickParameterLogForm(forms.ModelForm):
    """Mobile-friendly quick add form for water parameters."""
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
            'measured_at': forms.DateTimeInput(attrs={
                'class': 'w-full px-4 py-2 bg-slate-800 border border-slate-700 rounded-xl text-slate-400 focus:outline-none focus:ring-2 focus:ring-cyan-500 text-sm',
                'type': 'datetime-local'
            })
        }


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
        fields = ['name', 'species', 'groups', 'count', 'acquired_date', 'status', 'photo', 'notes']
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
            'groups': forms.CheckboxSelectMultiple(attrs={
                'class': 'rounded border-slate-700 text-cyan-500 focus:ring-cyan-500 bg-slate-800'
            }),
            'count': forms.NumberInput(attrs={
                'class': 'w-full px-4 py-2.5 bg-slate-800 border border-slate-700 rounded-xl text-white text-center font-bold text-lg focus:outline-none focus:ring-2 focus:ring-cyan-500',
                'min': '1',
                'value': '1'
            }),
            'acquired_date': forms.DateInput(attrs={
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


class TankForm(forms.ModelForm):
    class Meta:
        model = Tank
        fields = ['name', 'volume_gallons', 'is_primary', 'notes']
        widgets = {
            'name': forms.TextInput(attrs={'class': 'w-full px-4 py-2.5 bg-slate-800 border border-slate-700 rounded-xl text-white text-sm', 'placeholder': 'e.g. 120g Display Tank'}),
            'volume_gallons': forms.NumberInput(attrs={'class': 'w-full px-4 py-2.5 bg-slate-800 border border-slate-700 rounded-xl text-white text-sm', 'step': '0.1'}),
            'is_primary': forms.CheckboxInput(attrs={'class': 'rounded border-slate-700 text-cyan-500 bg-slate-800'}),
            'notes': forms.Textarea(attrs={'class': 'w-full px-4 py-2 bg-slate-800 border border-slate-700 rounded-xl text-slate-200 text-sm', 'rows': 2}),
        }


class EquipmentForm(forms.ModelForm):
    class Meta:
        model = Equipment
        fields = ['tank', 'name', 'category', 'brand', 'wattage', 'installed_date', 'maintenance_interval_days', 'last_serviced_date', 'status', 'notes']
        widgets = {
            'tank': forms.Select(attrs={'class': 'w-full px-4 py-2.5 bg-slate-800 border border-slate-700 rounded-xl text-white text-sm'}),
            'name': forms.TextInput(attrs={'class': 'w-full px-4 py-2.5 bg-slate-800 border border-slate-700 rounded-xl text-white text-sm', 'placeholder': 'e.g. Radion XR30 G6 Pro'}),
            'category': forms.Select(attrs={'class': 'w-full px-4 py-2.5 bg-slate-800 border border-slate-700 rounded-xl text-white text-sm'}),
            'brand': forms.TextInput(attrs={'class': 'w-full px-4 py-2.5 bg-slate-800 border border-slate-700 rounded-xl text-white text-sm', 'placeholder': 'e.g. EcoTech Marine'}),
            'wattage': forms.NumberInput(attrs={'class': 'w-full px-4 py-2.5 bg-slate-800 border border-slate-700 rounded-xl text-white text-sm', 'placeholder': 'Watts'}),
            'installed_date': forms.DateInput(attrs={'class': 'w-full px-4 py-2.5 bg-slate-800 border border-slate-700 rounded-xl text-white text-sm', 'type': 'date'}),
            'maintenance_interval_days': forms.NumberInput(attrs={'class': 'w-full px-4 py-2.5 bg-slate-800 border border-slate-700 rounded-xl text-white text-sm'}),
            'last_serviced_date': forms.DateInput(attrs={'class': 'w-full px-4 py-2.5 bg-slate-800 border border-slate-700 rounded-xl text-white text-sm', 'type': 'date'}),
            'status': forms.Select(attrs={'class': 'w-full px-4 py-2.5 bg-slate-800 border border-slate-700 rounded-xl text-white text-sm'}),
            'notes': forms.Textarea(attrs={'class': 'w-full px-4 py-2 bg-slate-800 border border-slate-700 rounded-xl text-slate-200 text-sm', 'rows': 2}),
        }


class DosingReservoirForm(forms.ModelForm):
    class Meta:
        model = DosingReservoir
        fields = ['tank', 'name', 'reservoir_type', 'capacity', 'current_level', 'unit', 'daily_consumption', 'color']
        widgets = {
            'tank': forms.Select(attrs={'class': 'w-full px-4 py-2.5 bg-slate-800 border border-slate-700 rounded-xl text-white text-sm'}),
            'name': forms.TextInput(attrs={'class': 'w-full px-4 py-2.5 bg-slate-800 border border-slate-700 rounded-xl text-white text-sm', 'placeholder': 'e.g. Alkalinity (Soda Ash), ATO RO/DI'}),
            'reservoir_type': forms.Select(attrs={'class': 'w-full px-4 py-2.5 bg-slate-800 border border-slate-700 rounded-xl text-white text-sm'}),
            'capacity': forms.NumberInput(attrs={'class': 'w-full px-4 py-2.5 bg-slate-800 border border-slate-700 rounded-xl text-white text-sm', 'step': '0.1'}),
            'current_level': forms.NumberInput(attrs={'class': 'w-full px-4 py-2.5 bg-slate-800 border border-slate-700 rounded-xl text-white text-sm', 'step': '0.1'}),
            'unit': forms.TextInput(attrs={'class': 'w-full px-4 py-2.5 bg-slate-800 border border-slate-700 rounded-xl text-white text-sm', 'placeholder': 'ml, gal, or L'}),
            'daily_consumption': forms.NumberInput(attrs={'class': 'w-full px-4 py-2.5 bg-slate-800 border border-slate-700 rounded-xl text-white text-sm', 'step': '0.1'}),
            'color': forms.TextInput(attrs={'class': 'w-full px-4 py-2.5 bg-slate-800 border border-slate-700 rounded-xl text-white text-sm', 'type': 'color'}),
        }


class WaterChangeLogForm(forms.ModelForm):
    class Meta:
        model = WaterChangeLog
        fields = ['tank', 'gallons', 'salt_brand', 'target_salinity', 'notes', 'performed_at']
        widgets = {
            'tank': forms.Select(attrs={'class': 'w-full px-4 py-2.5 bg-slate-800 border border-slate-700 rounded-xl text-white text-sm'}),
            'gallons': forms.NumberInput(attrs={'class': 'w-full px-4 py-2.5 bg-slate-800 border border-slate-700 rounded-xl text-white text-sm', 'step': '0.5'}),
            'salt_brand': forms.TextInput(attrs={'class': 'w-full px-4 py-2.5 bg-slate-800 border border-slate-700 rounded-xl text-white text-sm', 'placeholder': 'e.g. Tropic Marin Pro'}),
            'target_salinity': forms.NumberInput(attrs={'class': 'w-full px-4 py-2.5 bg-slate-800 border border-slate-700 rounded-xl text-white text-sm', 'step': '0.001'}),
            'notes': forms.TextInput(attrs={'class': 'w-full px-4 py-2 bg-slate-800 border border-slate-700 rounded-xl text-slate-200 text-sm', 'placeholder': 'Temperature matched, cleaned glass'}),
            'performed_at': forms.DateTimeInput(attrs={'class': 'w-full px-4 py-2 bg-slate-800 border border-slate-700 rounded-xl text-white text-sm', 'type': 'datetime-local'}),
        }
