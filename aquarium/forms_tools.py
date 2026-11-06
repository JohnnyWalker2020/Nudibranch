"""Forms for the tools section: planner, webhooks, timers, quarantine, timeline and settings."""
from urllib.parse import urlsplit

from django import forms

from .events import EVENT_TYPES
from .themes import RETIRED_ICONS, STOCK_ICONS
from .forms import CHECKBOX, CostGatedMixin, INPUT, TEXTAREA
from .models import (
    AnimalPhoto, AppSettings, CostEntry, Equipment, PlannedItem, PlannedSystem, QuarantineEntry, ROSystem,
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
    icon_choice = forms.ChoiceField(
        required=False, choices=[('', 'Random'), ('custom', 'Your icon')] + STOCK_ICONS + RETIRED_ICONS)

    class Meta:
        model = Tank
        fields = ['theme', 'icon_choice', 'custom_icon']

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


class CostEntryForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = CostEntry
        fields = ['description', 'amount', 'spent_on', 'category', 'tank']
        labels = {'tank': 'System', 'spent_on': 'Date', 'amount': 'Cost', 'description': 'What was it'}
        widgets = {
            'description': forms.TextInput(attrs={'placeholder': 'e.g. One more coral, I promise'}),
            'spent_on': forms.DateInput(format='%Y-%m-%d', attrs={'type': 'date'}),
            'amount': forms.NumberInput(attrs={'min': '0', 'step': '0.01', 'inputmode': 'decimal'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['tank'].empty_label = 'Not tied to one system'


class AppSettingsForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = AppSettings
        fields = ['electricity_rate', 'currency_symbol', 'auto_backup_days', 'auto_backup_keep']


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


class PlannedSystemForm(CostGatedMixin, StyledFormMixin, forms.ModelForm):
    cost_fields = ('budget',)

    class Meta:
        model = PlannedSystem
        fields = ['name', 'goal', 'existing_tank', 'dimension_unit', 'width', 'depth', 'height', 'fill_percent',
                  'capacity_is_manual', 'volume_gallons', 'sump_gallons', 'budget', 'notes']
        labels = {
            'existing_tank': 'Stock an existing tank instead?',
            'capacity_is_manual': 'Enter the capacity myself',
            'volume_gallons': 'Display volume (gallons)',
            'sump_gallons': 'Sump volume (gallons)',
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['existing_tank'].empty_label = 'No, this is a new system'
        self.fields['existing_tank'].queryset = Tank.objects.filter(is_archived=False)


class PlannedLivestockForm(CostGatedMixin, StyledFormMixin, forms.ModelForm):
    cost_fields = ('unit_cost',)
    species = forms.ModelChoiceField(queryset=SpeciesCatalog.objects.order_by('name'), empty_label='Choose a species...')

    class Meta:
        model = PlannedItem
        fields = ['species', 'quantity', 'unit_cost']
        labels = {'unit_cost': 'Price each'}


class WishlistLivestockForm(CostGatedMixin, StyledFormMixin, forms.ModelForm):
    cost_fields = ('est_price',)
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


class WishlistEquipmentForm(CostGatedMixin, StyledFormMixin, forms.ModelForm):
    cost_fields = ('est_price',)
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


class PlannedEquipmentForm(CostGatedMixin, StyledFormMixin, forms.ModelForm):
    cost_fields = ('unit_cost',)
    category = forms.ChoiceField(choices=Equipment.CATEGORY_CHOICES)

    class Meta:
        model = PlannedItem
        fields = ['name', 'category', 'quantity', 'wattage', 'max_flow_gph', 'unit_cost']
        labels = {'wattage': 'Watts each', 'max_flow_gph': 'Rated flow each (gph)', 'unit_cost': 'Price each'}
        widgets = {'name': forms.TextInput(attrs={'placeholder': 'e.g. 36 W LED, 300 W heater'})}
