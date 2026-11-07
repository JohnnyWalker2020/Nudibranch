"""Forms for the tools section: planner, webhooks, timers, quarantine, timeline and settings."""
import random
from urllib.parse import urlsplit

from django import forms
from django.db import transaction
from django.db.models import Q

from .events import EVENT_TYPES
from .icons import character_icons
from .forms import CHECKBOX, INPUT, TEXTAREA
from .models import (
    AnimalPhoto, AppSettings, CostEntry, Equipment, PlanProject, PlannedItem, PlannedSystem, QuarantineEntry, ROSystem, currency_choices,
    SpeciesCatalog, Tank, WebhookEndpoint, WishlistItem,
)


class StyledFormMixin:
    """Applies the app's input styling to every field."""

    def _style_fields(self):
        for field in self.fields.values():
            widget = field.widget
            if isinstance(widget, forms.CheckboxInput):
                widget.attrs.setdefault('class', CHECKBOX)
            elif isinstance(widget, forms.CheckboxSelectMultiple):
                widget.attrs.setdefault('class', 'space-y-1 text-sm text-slate-300')
            elif isinstance(widget, forms.Textarea):
                widget.attrs.setdefault('class', TEXTAREA)
                widget.attrs.setdefault('rows', 3)
            else:
                widget.attrs.setdefault('class', INPUT)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._style_fields()


class SystemThemeForm(forms.ModelForm):
    MAX_ICON_BYTES = 5 * 1024 * 1024
    ALLOWED_FORMATS = ('PNG', 'JPEG', 'WEBP', 'GIF')
    icon_choice = forms.ChoiceField(required=False)

    class Meta:
        model = Tank
        fields = ['theme', 'icon_choice', 'custom_icon']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        choices = [('', 'Random'), ('custom', 'Your icon')]
        choices += [(c['young'], c['label']) for c in character_icons()]
        if AppSettings.load().enable_old_version_icons:
            choices += [(c['old'], f"{c['label']} (old)") for c in character_icons()]
        self.fields['icon_choice'].choices = choices

    def clean_custom_icon(self):
        upload = self.cleaned_data.get('custom_icon')
        if upload and 'custom_icon' in self.files:
            if upload.size > self.MAX_ICON_BYTES:
                raise forms.ValidationError('That image is over 5 MB.')
            if getattr(upload.image, 'format', None) not in self.ALLOWED_FORMATS:
                raise forms.ValidationError('Use a PNG, JPG, WebP or GIF image.')
        return upload

    def save(self, commit=True):
        # A new upload is obviously the icon they want.
        if 'custom_icon' in self.files:
            self.instance.icon_choice = 'custom'
        return super().save(commit)


SIN_DESCRIPTIONS = [
    'One more coral, I promise',
    'It was on sale, so I basically made money',
    'A frag the size of a grain of rice',
    'The pump I "needed"',
    'Overnight shipping for one snail',
    'A light that cost more than my first car',
    '"Just browsing," they said',
    'Emergency livestock (there was no emergency)',
    'Impulse zoa. No regrets. Some regrets.',
    'Salt. Again. Somehow.',
    'An upgrade to the upgrade',
    'Not telling anyone at home about this one',
    'It followed me home from the fish store',
    'Research. Strictly for research.',
]


class EquipmentPriceField(forms.ModelChoiceField):
    def label_from_instance(self, obj):
        label = obj.name
        if obj.tank:
            label += f' · {obj.tank.name}'
        if obj.paid is not None:
            label += f' · paid {AppSettings.load().currency_symbol}{obj.paid:.2f}'
        return label


class CostEntryForm(StyledFormMixin, forms.ModelForm):
    equipment = EquipmentPriceField(
        queryset=Equipment.objects.none(), required=False, empty_label='Not tied to any equipment', label='Which equipment',
        help_text="Sets what you paid on that equipment. If it already has a price, this replaces it.",
    )

    class Meta:
        model = CostEntry
        fields = ['description', 'amount', 'spent_on', 'category', 'tank']
        labels = {'tank': 'Tank', 'spent_on': 'Date', 'amount': 'Cost', 'description': 'What was it'}
        widgets = {
            'description': forms.TextInput(attrs={'placeholder': 'e.g. One more coral, I promise'}),
            'spent_on': forms.DateInput(format='%Y-%m-%d', attrs={'type': 'date'}),
            'amount': forms.NumberInput(attrs={'min': '0', 'step': '0.01', 'inputmode': 'decimal'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['tank'].empty_label = 'Not tied to one tank'
        self.fields['description'].required = False
        self.fields['description'].widget.attrs['placeholder'] = f'e.g. {random.choice(SIN_DESCRIPTIONS)}'
        self.replaced_price = None
        self.linked_equipment_id = self.instance.equipment_id
        if self.instance.animal_id:
            # This line belongs to an animal, so it can't belong to equipment as well.
            self.fields.pop('equipment')
        else:
            current = Q(tank__isnull=True) | Q(tank__is_archived=False)
            if self.linked_equipment_id:
                current |= Q(pk=self.linked_equipment_id)
                self.fields['equipment'].initial = self.linked_equipment_id
            self.fields['equipment'].queryset = Equipment.objects.filter(current).select_related('tank').order_by('name')

    def clean_amount(self):
        amount = self.cleaned_data['amount']
        if amount < 0:
            raise forms.ValidationError("Nice try. Refunds aren't sins.")
        return amount

    def clean(self):
        cleaned = super().clean()
        if not cleaned.get('description'):
            equipment = cleaned.get('equipment')
            if equipment:
                cleaned['description'] = equipment.name[:150]
            elif 'description' not in self.errors:
                self.add_error('description', 'Every sin needs a name. What was it?')
        return cleaned

    def save(self, commit=True):
        entry = super().save(commit=False)
        if 'equipment' not in self.fields:
            if commit:
                entry.save()
            return entry
        equipment = self.cleaned_data.get('equipment')
        entry.equipment = equipment
        if equipment:
            entry.tank = equipment.tank or entry.tank
            if entry.category == 'other':
                entry.category = 'equipment'
        if commit:
            with transaction.atomic():
                if equipment:
                    previous = CostEntry.objects.filter(equipment=equipment).exclude(pk=entry.pk).first()
                    if previous:
                        self.replaced_price = previous.amount
                        previous.delete()
                entry.save()
                if self.linked_equipment_id and (not equipment or equipment.pk != self.linked_equipment_id):
                    Equipment.objects.filter(pk=self.linked_equipment_id).update(paid=None)
        return entry


class AppSettingsForm(StyledFormMixin, forms.ModelForm):
    currency_symbol = forms.ChoiceField(label='Currency', help_text="Only changes the symbol shown. Amounts aren't converted.")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['currency_symbol'].choices = currency_choices(self.instance.currency_symbol)
        days = self.fields['resolved_alert_days']
        days.required = False
        days.widget.attrs.update(min=1, max=30)

    def clean_resolved_alert_days(self):
        days = self.cleaned_data.get('resolved_alert_days')
        return self.instance.resolved_alert_days if days is None else days

    class Meta:
        model = AppSettings
        fields = ['electricity_rate', 'currency_symbol', 'auto_backup_days', 'auto_backup_keep',
                  'disable_icon_aging', 'enable_old_version_icons', 'enable_random_icons', 'resolved_alert_days']


class WebhookEndpointForm(StyledFormMixin, forms.ModelForm):
    event_types = forms.MultipleChoiceField(
        choices=EVENT_TYPES, required=False, widget=forms.CheckboxSelectMultiple,
        label='Events to send',
        help_text="Leave all unticked to send everything. If you choose routines or reservoirs below, leaving these unticked sends only events about those.",
    )

    class Meta:
        model = WebhookEndpoint
        fields = ['name', 'format', 'url', 'secret', 'event_types', 'routines', 'timer_reservoirs', 'is_active']
        labels = {'routines': 'Only these routines', 'timer_reservoirs': 'Only fill timers for these reservoirs'}
        help_texts = {
            'routines': "For a webhook that controls something, such as a feeder, tick just that routine. None ticked = all routines.",
            'timer_reservoirs': "None ticked = all fill timers. You can also choose a connection when you start a timer.",
        }
        widgets = {
            'name': forms.TextInput(attrs={'placeholder': 'e.g. My phone, Home Assistant feeder'}),
            'secret': forms.TextInput(attrs={'autocomplete': 'off'}),
            'routines': forms.CheckboxSelectMultiple,
            'timer_reservoirs': forms.CheckboxSelectMultiple,
        }

    def save(self, commit=True):
        self.instance.pause_reason = ''
        return super().save(commit)

    def clean_url(self):
        url = self.cleaned_data['url'].strip()
        try:
            parts = urlsplit(url)
            hostname = parts.hostname
            parts.port  # raises ValueError if the port isn't valid
        except ValueError as exc:
            raise forms.ValidationError('That address isn\'t valid.') from exc
        if parts.scheme.lower() not in ('http', 'https') or not hostname or any(c.isspace() for c in url):
            raise forms.ValidationError('Use an http:// or https:// address.')
        return url


class QuarantineEntryForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = QuarantineEntry
        fields = ['logged_on', 'kind', 'medication', 'dose', 'notes']
        widgets = {'logged_on': forms.DateInput(format='%Y-%m-%d', attrs={'type': 'date'})}


class QuarantinePlanForm(StyledFormMixin, forms.Form):
    started = forms.DateField(label='Started', widget=forms.DateInput(format='%Y-%m-%d', attrs={'type': 'date'}))
    days = forms.IntegerField(label='Planned days', min_value=1, max_value=365)


class AnimalPhotoForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = AnimalPhoto
        fields = ['image', 'taken_on', 'note']
        widgets = {
            'taken_on': forms.DateInput(format='%Y-%m-%d', attrs={'type': 'date'}),
            'image': forms.ClearableFileInput(attrs={'accept': 'image/*'}),
        }


class ROSystemForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = ROSystem
        fields = ['name', 'rated_gpd', 'rated_psi', 'rated_temp_f', 'feed_psi', 'feed_temp_f', 'waste_ratio', 'measured_gph', 'is_default']
        labels = {
            'rated_gpd': 'Rated output (GPD)', 'rated_psi': 'Rated pressure (psi)', 'rated_temp_f': 'Rated temperature (°F)',
            'feed_psi': 'Your water pressure (psi)', 'feed_temp_f': 'Your water temperature (°F)',
            'waste_ratio': 'Waste per gallon made', 'measured_gph': 'Measured output (gal/hour)',
            'is_default': 'Use by default',
        }


class PlannedSystemForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = PlannedSystem
        fields = ['name', 'project', 'goal', 'existing_tank', 'dimension_unit', 'width', 'depth', 'height', 'fill_percent',
                  'capacity_is_manual', 'volume_gallons', 'sump_gallons', 'budget', 'notes']
        labels = {
            'project': 'Part of a project',
            'existing_tank': 'Stock an existing tank instead?',
            'capacity_is_manual': 'Enter the capacity myself',
            'volume_gallons': 'Display volume (gallons)',
            'sump_gallons': 'Sump volume (gallons)',
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['existing_tank'].empty_label = 'No, this is a new tank'
        self.fields['project'].empty_label = 'No project'
        self.fields['existing_tank'].queryset = Tank.objects.filter(is_archived=False)


class PlanProjectForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = PlanProject
        fields = ['name', 'budget', 'notes']
        widgets = {'name': forms.TextInput(attrs={'placeholder': 'e.g. Fish room build-out'})}


class PlannedLivestockForm(StyledFormMixin, forms.ModelForm):
    species = forms.ModelChoiceField(queryset=SpeciesCatalog.objects.order_by('name'), empty_label='Choose a species...')

    class Meta:
        model = PlannedItem
        fields = ['species', 'quantity', 'unit_cost']
        labels = {'unit_cost': 'Price each'}


class WishlistLivestockForm(StyledFormMixin, forms.ModelForm):
    species = forms.ModelChoiceField(queryset=SpeciesCatalog.objects.order_by('name'), empty_label='Choose a species...')

    class Meta:
        model = WishlistItem
        fields = ['species', 'quantity', 'est_price', 'priority', 'tank', 'link', 'notes']
        labels = {'est_price': 'Price each', 'tank': 'Check against tank'}
        widgets = {'notes': forms.Textarea(attrs={'rows': 2})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['tank'].empty_label = 'My primary tank'

    def save(self, commit=True):
        item = super().save(commit=False)
        item.kind = 'livestock'
        item.name = item.species.name
        if commit:
            item.save()
        return item


class WishlistEquipmentForm(StyledFormMixin, forms.ModelForm):
    category = forms.ChoiceField(choices=Equipment.CATEGORY_CHOICES, label='Type')

    class Meta:
        model = WishlistItem
        fields = ['name', 'category', 'quantity', 'est_price', 'priority', 'wattage', 'max_flow_gph', 'link', 'notes']
        labels = {'est_price': 'Price each', 'wattage': 'Watts each', 'max_flow_gph': 'Rated flow each (gph)'}
        widgets = {'notes': forms.Textarea(attrs={'rows': 2}),
                   'name': forms.TextInput(attrs={'placeholder': 'e.g. Calcium reactor'})}

    def save(self, commit=True):
        item = super().save(commit=False)
        item.kind = 'equipment'
        if commit:
            item.save()
        return item


class PlannedEquipmentForm(StyledFormMixin, forms.ModelForm):
    category = forms.ChoiceField(choices=Equipment.CATEGORY_CHOICES)

    class Meta:
        model = PlannedItem
        fields = ['name', 'category', 'quantity', 'wattage', 'max_flow_gph', 'unit_cost']
        labels = {'wattage': 'Watts each', 'max_flow_gph': 'Rated flow each (gph)', 'unit_cost': 'Price each'}
        widgets = {'name': forms.TextInput(attrs={'placeholder': 'e.g. 36 W LED, 300 W heater'})}


# Tank names show total water; load what that needs with the menu.
for _form in (CostEntryForm, WishlistLivestockForm):
    _form.base_fields['tank'].queryset = _form.base_fields['tank'].queryset.prefetch_related('sumps', 'plumbing_runs')
