import copy
from decimal import Decimal
import urllib.parse
from datetime import timedelta

from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.db.models import OuterRef, Subquery
from django.db.models.signals import post_delete, post_save, pre_delete, pre_save
from django.dispatch import receiver
from django.utils import timezone
from django.utils.functional import cached_property

from .silly_names import random_epitaph
from .calculators import (
    estimate_capacity_gallons, estimate_flow_at_head, estimate_flow_gph, gph_to_lph, par_estimate, turnover_summary,
    pipe_volume_gallons, FT_PER_M, LITERS_PER_GAL, PIPE_INSIDE, PIPE_SIZES, PIPE_TYPE_SHORT, PIPE_TYPES,
)
from . import icons
from . import schedule as sched
from .images import compressed_jpeg
from .themes import DEFAULT_THEME, THEME_CHOICES, palette_from_colors

WEEKDAYS = [(0, 'Mon'), (1, 'Tue'), (2, 'Wed'), (3, 'Thu'), (4, 'Fri'), (5, 'Sat'), (6, 'Sun')]
PIPE_SIZE_CHOICES = [(key, label) for key, (label, _id) in PIPE_SIZES.items()]


# "Every system", as opposed to tank=None, which means "records that aren't assigned to a system".
ANY = object()


def in_system(queryset, tank):
    """Limits a queryset with a `tank` field to one system. Unassigned records show under every system."""
    if tank is ANY:
        return queryset
    if tank is None:
        return queryset.filter(tank__isnull=True)
    return queryset.filter(models.Q(tank=tank) | models.Q(tank__isnull=True))


def not_retired(queryset):
    """Leaves out records belonging to archived systems (for alerts and background jobs)."""
    return queryset.filter(models.Q(tank__isnull=True) | models.Q(tank__is_archived=False))


def all_weekdays():
    # Kept because migration 0007 references it.
    return [0, 1, 2, 3, 4, 5, 6]


RANGE_FIELDS = ('low_limit', 'min_ideal', 'max_ideal', 'high_limit')


class ParameterTypeQuerySet(models.QuerySet):
    def in_use(self):
        """Every parameter, or while ICP elements are switched off in Settings, the regular ones plus any ICP
        elements picked one at a time."""
        return self if AppSettings.load().icp_enabled else self.filter(visible_q())


def visible_q(prefix=''):
    """The Q that keeps a parameter in sight while ICP is switched off. prefix='parameter_type__' for logs."""
    return models.Q(**{f'{prefix}is_trace': False}) | models.Q(**{f'{prefix}icp_picked': True})


class ParameterType(models.Model):
    """Represents a measured water metric (e.g. Salinity, Alkalinity, Calcium)."""
    objects = ParameterTypeQuerySet.as_manager()
    name = models.CharField(max_length=60, unique=True)
    code = models.SlugField(max_length=30, unique=True, help_text="Short identifier e.g. alk, sal, ca")
    unit = models.CharField(max_length=20, help_text="e.g. dKH, SG, ppm, °F, pH")
    low_limit = models.DecimalField(max_digits=10, decimal_places=3, null=True, blank=True,
                                    help_text="At or below this is critically low (optional)")
    min_ideal = models.DecimalField(max_digits=10, decimal_places=3, help_text="Lower bound of target range")
    max_ideal = models.DecimalField(max_digits=10, decimal_places=3, help_text="Upper bound of target range")
    high_limit = models.DecimalField(max_digits=10, decimal_places=3, null=True, blank=True,
                                     help_text="At or above this is critically high (optional)")
    color = models.CharField(max_length=20, default="#0ea5e9", help_text="Hex color code for charts and badges")
    decimal_places = models.PositiveSmallIntegerField(default=1, help_text="Number of decimal places (e.g. 0 for ppm, 3 for SG)")
    display_order = models.PositiveIntegerField(default=0)
    stale_after_hours = models.PositiveIntegerField(
        null=True, blank=True,
        help_text="Alert if no reading arrives for this many hours (for probes; blank = never)")
    is_trace = models.BooleanField(default=False, help_text='An ICP or trace element: left off the All chart and listed after the others')
    show_on_dashboard = models.BooleanField(default=True, help_text='Show a card for it on the dashboard')
    icp_picked = models.BooleanField(
        default=False, help_text='An ICP element added on its own, so it shows even while ICP elements are switched off')

    class Meta:
        ordering = ['display_order', 'name']

    @property
    def test_every_days(self):
        """Whole days for a test reminder, or None when the gap is set in hours for a probe (or not set)."""
        hours = self.stale_after_hours
        return hours // 24 if hours and hours % 24 == 0 else None

    def __str__(self):
        return f"{self.name} ({self.unit})"

    def for_system(self, tank):
        """
        This parameter with one system's target ranges, if it has its own. Everything that reads the
        ranges (classify, the formatted values, templates) then just works. Falls back to these shared
        defaults. The result is read-only: units and decimals live here, ranges in ParameterTarget.
        """
        tank_id = getattr(tank, 'pk', tank)
        if not isinstance(tank_id, int):
            return self
        if 'targets' in getattr(self, '_prefetched_objects_cache', {}):
            target = next((t for t in self.targets.all() if t.tank_id == tank_id), None)
        else:
            target = self.targets.filter(tank_id=tank_id).first()
        if target is None:
            return self
        view = copy.copy(self)
        for field in RANGE_FIELDS:
            setattr(view, field, getattr(target, field))
        view.is_system_view = True
        view.has_system_targets = True
        return view

    def save(self, *args, **kwargs):
        if getattr(self, 'is_system_view', False):
            raise ValueError("A parameter's per-system view can't be saved.")
        super().save(*args, **kwargs)

    def latest_log(self, tank=ANY):
        return in_system(self.logs.all(), tank).order_by('-measured_at').first()

    def format_value(self, val):
        """Formats a number according to the parameter's configured decimal places."""
        if val is None:
            return ""
        try:
            f_val = float(val)
            if self.decimal_places == 0:
                return f"{round(f_val):d}"
            return f"{f_val:.{self.decimal_places}f}"
        except (ValueError, TypeError):
            return str(val)

    @property
    def formatted_min_ideal(self):
        return self.format_value(self.min_ideal)

    @property
    def formatted_max_ideal(self):
        return self.format_value(self.max_ideal)

    @property
    def formatted_low_limit(self):
        return self.format_value(self.low_limit)

    @property
    def formatted_high_limit(self):
        return self.format_value(self.high_limit)

    def classify(self, value):
        """
        (status, severity) for a reading.
        status: 'low' | 'optimal' | 'high' (relative to the ideal range)
        severity: 'ok' | 'warning' (outside ideal, inside limits) | 'critical' (at/past a limit).
        With no limit set on that side, outside the ideal range is a warning.
        """
        if value < self.min_ideal:
            critical = self.low_limit is not None and value <= self.low_limit
            return 'low', 'critical' if critical else 'warning'
        if value > self.max_ideal:
            critical = self.high_limit is not None and value >= self.high_limit
            return 'high', 'critical' if critical else 'warning'
        return 'optimal', 'ok'


class ParameterLog(models.Model):
    """Historical test measurement."""
    parameter_type = models.ForeignKey(ParameterType, on_delete=models.CASCADE, related_name="logs")
    tank = models.ForeignKey('Tank', on_delete=models.CASCADE, null=True, blank=True, related_name='parameter_logs',
                             help_text="Tank this was measured in")
    measured_at = models.DateTimeField(default=timezone.now)
    value = models.DecimalField(max_digits=10, decimal_places=4)
    notes = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ['-measured_at']
        indexes = [models.Index(fields=['tank', 'parameter_type', '-measured_at'], name='log_tank_param_time')]

    def __str__(self):
        return f"{self.parameter_type.name}: {self.value} {self.parameter_type.unit} @ {self.measured_at:%Y-%m-%d %H:%M}"

    @property
    def formatted_value(self):
        """Formats measurement according to the parameter's configured decimal places."""
        return self.parameter_type.format_value(self.value)

    @cached_property
    def _classification(self):
        # Judged against the targets of the system it was measured in.
        return self.parameter_type.for_system(self.tank_id).classify(self.value)

    @property
    def status(self):
        """'low', 'optimal' or 'high' relative to the ideal range."""
        return self._classification[0]

    @property
    def severity(self):
        """'ok', 'warning' (outside ideal) or 'critical' (past the low/high limit)."""
        return self._classification[1]

    @property
    def status_label(self):
        status, severity = self._classification
        if severity == 'critical':
            return f"CRITICAL {status.upper()}"
        return status.upper()

    @property
    def status_color_class(self):
        severity = self.severity
        if severity == 'ok':
            return "text-emerald-400 bg-emerald-500/10 border-emerald-500/30"
        if severity == 'warning':
            return "text-amber-400 bg-amber-500/10 border-amber-500/30"
        return "text-rose-400 bg-rose-500/10 border-rose-500/30"


def latest_logs_by_parameter(tank, *, back=0):
    """{parameter id: newest log} for a system, in two queries however many parameters there are.
    back=1 gives the reading before the newest, for showing which way a value is moving."""
    newest = in_system(ParameterLog.objects.filter(parameter_type=OuterRef('pk')), tank).order_by('-measured_at', '-pk')
    ids = ParameterType.objects.annotate(newest=Subquery(newest.values('pk')[back:back + 1])).values_list('newest', flat=True)
    return {log.parameter_type_id: log for log in ParameterLog.objects.filter(pk__in=[pk for pk in ids if pk])}


def trend(parameter_type, latest, previous):
    """Which way a parameter moved since the test before, and whether that's toward its ideal range."""
    if latest is None or previous is None:
        return None
    change = float(latest.value) - float(previous.value)
    if parameter_type.format_value(abs(change)) == parameter_type.format_value(0):
        return {'arrow': '→', 'text': 'no change', 'tone': 'steady'}
    low, high = float(parameter_type.min_ideal), float(parameter_type.max_ideal)
    before, now = float(previous.value), float(latest.value)
    distance = lambda v: (low - v) if v < low else (v - high) if v > high else 0
    if distance(now) < distance(before):
        tone = 'better'
    elif distance(now) > distance(before):
        tone = 'worse'
    else:
        tone = 'steady'  # moved, but stayed inside the ideal range
    return {'arrow': '↑' if change > 0 else '↓', 'text': ('+' if change > 0 else '−') + parameter_type.format_value(abs(change)),
            'tone': tone}


class AnimalGroup(models.Model):
    """Groups / tags for livestock (e.g. 'Cleanup Crew', 'School', 'SPS Corals')."""
    name = models.CharField(max_length=60, unique=True)
    description = models.TextField(blank=True)
    color = models.CharField(max_length=20, default="#64748b", help_text="Hex color for UI tag badges")
    icon = models.CharField(max_length=10, default="🐟", help_text="Emoji or icon symbol")
    position = models.PositiveIntegerField(default=0, editable=False, help_text="Order on the Livestock page")

    class Meta:
        ordering = ['position', 'name']

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        # A new category goes to the end of the list.
        if self._state.adding and not self.position:
            last = AnimalGroup.objects.aggregate(models.Max('position'))['position__max']
            self.position = 0 if last is None else last + 1
        super().save(*args, **kwargs)


def _wikipedia_url(species, name):
    if species:
        clean_species = species.strip().replace(' ', '_')
        return f"https://en.wikipedia.org/wiki/{urllib.parse.quote(clean_species)}"
    clean_name = name.split('(')[0].strip()
    return f"https://en.wikipedia.org/wiki/Special:Search?search={urllib.parse.quote(clean_name)}"


def reef2reef_search(term, extra=""):
    """Site-restricted web search for Reef2Reef threads.

    Reef2Reef's own /search/ URL needs a server-side search id, so a plain GET with ?q=
    is unreliable. A site: search on a general engine always works.
    """
    query = f"site:reef2reef.com {term} {extra}".strip()
    return f"https://www.google.com/search?q={urllib.parse.quote_plus(query)}"


class Animal(models.Model):
    """Livestock entry in the aquarium."""
    STATUS_CHOICES = [
        ('healthy', 'Healthy / Thriving'),
        ('quarantine', 'In Quarantine'),
        ('monitoring', 'Monitoring / Sick'),
        ('rehomed', 'Rehomed'),
        ('deceased', 'Deceased'),
    ]
    GONE_STATUSES = ('rehomed', 'deceased')

    name = models.CharField(max_length=120, help_text="Common name or pet name (e.g. 'Ocellaris Clown Pair')")
    species = models.CharField(max_length=150, blank=True, help_text="Scientific or species name (optional)")
    tank = models.ForeignKey('Tank', on_delete=models.SET_NULL, null=True, blank=True, related_name='animals', help_text="Assigned tank")
    groups = models.ManyToManyField(AnimalGroup, blank=True, related_name="animals")
    count = models.PositiveIntegerField(default=1, help_text="Quantity (e.g. 10 snails or 5 chromis)")
    acquired_date = models.DateField(null=True, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='healthy')
    photo = models.ImageField(upload_to="livestock/", blank=True, null=True)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    quarantine_started = models.DateField(null=True, blank=True, help_text="Day quarantine began")
    quarantine_days = models.PositiveIntegerField(default=30, help_text="Planned quarantine length in days")
    paid = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True,
                               help_text="What you paid in total. Added to The Damage automatically")
    nickname = models.CharField(max_length=120, blank=True, help_text="A name of its own")
    banned_to_sump = models.BooleanField(default=False, help_text="Shows a tag on its livestock card")
    died_on = models.DateField(null=True, blank=True, help_text="Filled in with today if left blank")
    epitaph = models.CharField(max_length=160, blank=True, help_text="Left blank, one gets picked. {date} becomes the date of death")

    class Meta:
        ordering = ['status', 'name']

    def __str__(self):
        qty_str = f" ({self.count}x)" if self.count > 1 else ""
        return f"{self.name}{qty_str}"

    def save(self, *args, **kwargs):
        changed = set()
        if self.status == 'quarantine' and not self.quarantine_started:
            self.quarantine_started = timezone.localdate()
            changed.add('quarantine_started')
        if self.status == 'deceased':
            # Older entries already have an epitaph and no known date, and shouldn't get today's date by being saved.
            if not self.epitaph:
                self.epitaph = random_epitaph()
                self.died_on = self.died_on or timezone.localdate()
                changed |= {'epitaph', 'died_on'}
        elif self.died_on or self.epitaph:
            self.died_on, self.epitaph = None, ''  # back from the dead, so a later death gets its own stone
            changed |= {'epitaph', 'died_on'}
        update_fields = kwargs.get('update_fields')
        if update_fields is not None:
            kwargs['update_fields'] = set(update_fields) | changed
        super().save(*args, **kwargs)

    @property
    def epitaph_text(self):
        """The tombstone line, with the date of death filled in."""
        date = self.died_on.strftime('%m-%d-%Y') if self.died_on else 'some sad day'
        return self.epitaph.replace('{date}', date)

    @property
    def quarantine_day(self):
        """Day number of quarantine (1 = first day), or None if it has no start date."""
        if not self.quarantine_started:
            return None
        return (timezone.localdate() - self.quarantine_started).days + 1

    @property
    def quarantine_end_date(self):
        if not self.quarantine_started:
            return None
        return self.quarantine_started + timedelta(days=self.quarantine_days)

    @property
    def quarantine_percent(self):
        day = self.quarantine_day
        if day is None or not self.quarantine_days:
            return 0
        return max(0, min(100, round((day - 1) / self.quarantine_days * 100)))

    @property
    def quarantine_complete(self):
        end = self.quarantine_end_date
        return self.status == 'quarantine' and end is not None and timezone.localdate() >= end

    @property
    def wikipedia_url(self):
        return _wikipedia_url(self.species, self.name)

    @property
    def reef2reef_search_url(self):
        """Reef2Reef community search for real hobbyist discussions, care, and tips."""
        return reef2reef_search(self.species if self.species else self.name.split('(')[0].strip())

    @property
    def reef2reef_disease_url(self):
        """Reef2Reef fish disease and diagnosis search."""
        return reef2reef_search(self.name.split('(')[0].strip(), "disease treatment")


class WebcamFeed(models.Model):
    """Live video feed or camera snapshot."""
    FEED_TYPES = [
        ('mjpeg', 'MJPEG Stream / Snapshot URL'),
        ('webrtc', 'WebRTC / HLS Stream (e.g. go2rtc)'),
        ('iframe', 'Embedded Web Player (iFrame)'),
    ]

    name = models.CharField(max_length=100)
    tank = models.ForeignKey('Tank', on_delete=models.SET_NULL, null=True, blank=True, related_name='webcams',
                             help_text="Tank this camera watches (blank = show on every tank)")
    feed_url = models.CharField(max_length=500, help_text="URL of the stream, snapshot, or embed link")
    feed_type = models.CharField(max_length=20, choices=FEED_TYPES, default='mjpeg')
    is_active = models.BooleanField(default=True)
    order = models.PositiveIntegerField(default=0)
    snapshot_url = models.CharField(
        max_length=500, blank=True,
        help_text="Still-image URL for time-lapse. Blank = grab a frame from the stream URL above (MJPEG feeds only)")
    timelapse_enabled = models.BooleanField(default=False, help_text="Capture a time-lapse frame on a schedule")
    timelapse_interval_minutes = models.PositiveIntegerField(default=60, help_text="Minutes between frames")
    timelapse_keep_days = models.PositiveIntegerField(default=90, help_text="Delete frames older than this many days")
    last_capture_at = models.DateTimeField(null=True, blank=True, editable=False)
    last_capture_error = models.CharField(max_length=255, blank=True, editable=False)

    class Meta:
        ordering = ['order', 'name']

    def __str__(self):
        return self.name


class SpeciesCatalog(models.Model):
    """Catalog of common saltwater aquarium animals for quick lookup and 1-click tank adding."""
    CATEGORY_CHOICES = [
        ('fish', 'Fish'),
        ('cleanup_crew', 'Cleanup Crew'),
        ('invert', 'Invertebrates & Shrimp'),
        ('coral', 'Corals & Anemones'),
    ]

    TEMPERAMENT_CHOICES = [
        ('peaceful', 'Peaceful'),
        ('semi', 'Semi-aggressive'),
        ('aggressive', 'Aggressive'),
    ]

    name = models.CharField(max_length=120, unique=True, help_text="Common hobbyist name")
    species = models.CharField(max_length=150, blank=True, help_text="Scientific/taxonomic name")
    category = models.CharField(max_length=20, choices=CATEGORY_CHOICES, default='fish')
    suggested_group = models.CharField(max_length=60, default='Fish', help_text="Default group when added to tank")
    care_level = models.CharField(max_length=30, default='Beginner', help_text="Beginner, Moderate, or Expert")
    reef_safe = models.CharField(max_length=30, default='Yes', help_text="Yes, With Caution, or No")
    diet = models.CharField(max_length=150, blank=True, help_text="e.g. Herbivore, Omnivore, Carnivore")
    notes = models.TextField(blank=True, help_text="Care tips, temperament, and requirements")
    icon = models.CharField(max_length=10, default='🐠')
    min_tank_gallons = models.PositiveIntegerField(null=True, blank=True, help_text="Rough minimum display size for an adult")
    max_size_inches = models.DecimalField(max_digits=5, decimal_places=1, null=True, blank=True, help_text="Typical adult length")
    temperament = models.CharField(max_length=12, choices=TEMPERAMENT_CHOICES, blank=True)

    class Meta:
        ordering = ['category', 'name']
        verbose_name_plural = 'Species Catalog'

    def __str__(self):
        return f"{self.icon} {self.name} ({self.species})" if self.species else f"{self.icon} {self.name}"

    @property
    def wikipedia_url(self):
        return _wikipedia_url(self.species, self.name)

    @property
    def reef2reef_search_url(self):
        return reef2reef_search(self.species if self.species else self.name.split('(')[0].strip())


class DimensionedVessel(models.Model):
    """Shared fields for anything that holds water and has a box shape (tank, sump)."""
    DIMENSION_UNITS = [
        ('in', 'Inches'),
        ('cm', 'Centimeters'),
    ]

    width = models.DecimalField(max_digits=7, decimal_places=1, null=True, blank=True, help_text="Interior width, left to right")
    depth = models.DecimalField(max_digits=7, decimal_places=1, null=True, blank=True, help_text="Interior depth, front to back")
    height = models.DecimalField(max_digits=7, decimal_places=1, null=True, blank=True, help_text="Interior height")
    dimension_unit = models.CharField(max_length=2, choices=DIMENSION_UNITS, default='in')
    fill_percent = models.DecimalField(
        max_digits=5, decimal_places=1, default=90,
        help_text="Usable water as a % of the box volume (glass thickness, water line below the rim, bracing)",
    )
    capacity_is_manual = models.BooleanField(
        default=False,
        help_text="Tick to enter the capacity yourself instead of estimating it from the dimensions",
    )
    volume_gallons = models.DecimalField(max_digits=7, decimal_places=1, default=50.0, help_text="Water volume (US gallons)")

    class Meta:
        abstract = True

    @property
    def has_dimensions(self):
        return bool(self.width and self.depth and self.height)

    @property
    def estimated_gallons(self):
        """Capacity estimated from the dimensions (None if any dimension is missing)."""
        if not self.has_dimensions:
            return None
        return estimate_capacity_gallons(self.width, self.depth, self.height, self.dimension_unit, self.fill_percent)

    @property
    def volume_liters(self):
        return round(float(self.volume_gallons or 0) * LITERS_PER_GAL, 1)

    def save(self, *args, **kwargs):
        # Keep the stored capacity in sync with the dimensions unless the user typed it in.
        if not self.capacity_is_manual and self.has_dimensions:
            estimate = self.estimated_gallons
            if estimate is not None:
                self.volume_gallons = estimate
        super().save(*args, **kwargs)


KG_PER_LB = 0.45359237


class Tank(DimensionedVessel):
    """Represents an aquarium system (e.g. Main Display, Frag Tank, Quarantine)."""
    WEIGHT_UNITS = [('lb', 'lb'), ('kg', 'kg')]
    SUBSTRATE_TYPES = [
        ('bare', 'Bare bottom'),
        ('live_sand', 'Live sand'),
        ('aragonite', 'Dry aragonite sand'),
        ('crushed_coral', 'Crushed coral'),
        ('reef_rubble', 'Rubble'),
        ('mud', 'Mineral mud'),
        ('other', 'Other'),
    ]
    name = models.CharField(max_length=100, default="Main Display Tank")
    is_primary = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    notes = models.TextField(blank=True)
    theme = models.CharField(max_length=20, choices=THEME_CHOICES, default=DEFAULT_THEME)
    UI_STYLES = [('standard', 'Standard'), ('8bit', '8-bit')]
    ui_style = models.CharField(max_length=10, choices=UI_STYLES, default='standard',
                                help_text="How the cards and buttons look while this tank is selected")
    icon_choice = models.CharField(max_length=60, blank=True, help_text="A character icon, 'custom', or blank for the default")
    custom_icon = models.ImageField(upload_to='icons/', null=True, blank=True)
    substrate_type = models.CharField(max_length=20, choices=SUBSTRATE_TYPES, blank=True)
    substrate_amount = models.DecimalField(max_digits=8, decimal_places=1, null=True, blank=True)
    substrate_unit = models.CharField(max_length=2, choices=WEIGHT_UNITS, default='lb')
    substrate_product = models.ForeignKey('Equipment', on_delete=models.SET_NULL, null=True, blank=True,
                                          related_name='substrate_for_tanks',
                                          help_text="The product it is, from your equipment list")
    live_rock_amount = models.DecimalField(max_digits=8, decimal_places=1, null=True, blank=True)
    live_rock_unit = models.CharField(max_length=2, choices=WEIGHT_UNITS, default='lb')
    is_archived = models.BooleanField(default=False, editable=False)
    archived_at = models.DateTimeField(null=True, blank=True, editable=False)
    position = models.PositiveIntegerField(default=0, editable=False, help_text="Order on the Tanks page and in the Tank menu")

    class Meta:
        ordering = ['position', 'name']

    def __str__(self):
        # Everywhere a tank is picked, its size is the whole system's water: display, sumps and plumbing.
        return f"{self.name} ({self.total_system_gallons} gal)"

    def save(self, *args, **kwargs):
        # A new tank goes to the end of the list.
        if self._state.adding and not self.position:
            last = Tank.objects.aggregate(models.Max('position'))['position__max']
            self.position = 0 if last is None else last + 1
        super().save(*args, **kwargs)

    @staticmethod
    def _weight_label(amount, unit):
        """'50 lb (22.7 kg)': what was entered, then the other unit. '' when nothing's entered."""
        if amount is None:
            return ''
        value = float(amount)
        other = f"{value * KG_PER_LB:.1f} kg" if unit == 'lb' else f"{value / KG_PER_LB:.1f} lb"
        return f"{value:g} {unit} ({other})"

    @property
    def substrate_amount_label(self):
        return self._weight_label(self.substrate_amount, self.substrate_unit)

    @property
    def live_rock_label(self):
        return self._weight_label(self.live_rock_amount, self.live_rock_unit)

    @property
    def icon_url(self):
        """The icon to show for this system, or '' if the page should pick one (random icons, or a missing upload)."""
        # Your own upload never changes, retired or not.
        if self.icon_choice == 'custom':
            return self.custom_icon.url if self.custom_icon else ''
        return icons.url_for_stem(self._icon_stem())

    def _icon_stem(self):
        app_settings = AppSettings.load()
        aged = self.is_archived and not app_settings.disable_icon_aging
        stem = ''
        if self.icon_choice:
            stem = icons.display_stem(self.icon_choice, aged=aged, old_allowed=app_settings.enable_old_version_icons)
        if stem:
            return stem
        if aged:
            return icons.retired_default_stem(self.pk)
        return '' if app_settings.enable_random_icons else icons.default_stem(self.pk)

    def icon_palette(self):
        """Page colours taken from the icon being shown, or None (a random icon has no lasting colours)."""
        if self.icon_choice == 'custom':
            path = self.custom_icon.path if self.custom_icon else None
        else:
            stem = self._icon_stem()
            path = icons.file_for_stem(stem) if stem else None
        colors = icons.colors_from_file(path) if path else None
        return palette_from_colors(*colors) if colors else None

    @property
    def living_animal_count(self):
        return sum(a.count for a in self.animals.all() if a.status not in Animal.GONE_STATUSES)

    @property
    def sump_gallons(self):
        return sum(float(s.volume_gallons or 0) for s in self.sumps.all())

    @property
    def plumbing_gallons(self):
        """Water held in all plumbing runs."""
        return round(sum(run.gallons for run in self.plumbing_runs.all()), 2)

    @property
    def plumbing_feet(self):
        return round(sum(run.total_length_ft for run in self.plumbing_runs.all()), 1)

    @property
    def total_system_gallons(self):
        """Display tank + sumps + plumbing. Used for dosing and return-pump turnover."""
        return round(float(self.volume_gallons or 0) + self.sump_gallons + self.plumbing_gallons, 1)

    @property
    def total_system_liters(self):
        return round(self.total_system_gallons * LITERS_PER_GAL, 1)

    def light_summary(self):
        """Display lights, their power now, and the rough PAR that gives. Sump and refugium lights don't reach the display."""
        lights = [eq for eq in self.equipment.all() if eq.category == 'lighting' and not eq.sump_id]
        running = [eq for eq in lights if eq.status != 'offline' and eq.wattage]
        watts_now = sum(eq.wattage * eq.power_setting_percent / 100 for eq in running)
        levels = par_estimate(watts_now, self.width, self.depth, self.height, self.dimension_unit) if self.has_dimensions else None
        return {
            'lights': lights,
            'watts_now': round(watts_now),
            'watts_full': sum(eq.wattage for eq in running),
            'levels': levels,
        }

    def flow_summary(self):
        """Turnover figures based on the equipment assigned to this tank."""
        return_gph = 0.0
        wave_gph = 0.0
        for eq in self.equipment.all():
            flow = eq.estimated_flow_gph
            if not flow or eq.status == 'offline':
                continue
            if eq.category == 'return_pump':
                return_gph += flow
            elif eq.category == 'wavemaker':
                wave_gph += flow
        return turnover_summary(self.volume_gallons, self.total_system_gallons, return_gph, wave_gph)


class ParameterTarget(models.Model):
    """One system's own target ranges for a parameter. Without one, the parameter's shared defaults apply."""
    tank = models.ForeignKey(Tank, on_delete=models.CASCADE, related_name='parameter_targets')
    parameter_type = models.ForeignKey(ParameterType, on_delete=models.CASCADE, related_name='targets')
    low_limit = models.DecimalField(max_digits=10, decimal_places=3, null=True, blank=True)
    min_ideal = models.DecimalField(max_digits=10, decimal_places=3)
    max_ideal = models.DecimalField(max_digits=10, decimal_places=3)
    high_limit = models.DecimalField(max_digits=10, decimal_places=3, null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['tank', 'parameter_type'], name='one_target_per_system_parameter'),
        ]

    def __str__(self):
        return f"{self.parameter_type.name} targets for {self.tank.name}"


class PlumbingRun(models.Model):
    """A stretch of pipe holding system water (return line, drains, manifold...)."""
    LENGTH_UNITS = [('ft', 'Feet'), ('m', 'Meters')]
    DIAMETER_UNITS = [('in', 'Inches'), ('mm', 'Millimeters')]
    SIZE_CHOICES = PIPE_SIZE_CHOICES + [('custom', 'Custom inside diameter')]

    tank = models.ForeignKey(Tank, on_delete=models.CASCADE, related_name='plumbing_runs')
    name = models.CharField(max_length=80, blank=True, help_text="e.g. Return line, Main drain, Emergency drain")
    length = models.DecimalField(max_digits=7, decimal_places=1, help_text="Length of one pipe")
    length_unit = models.CharField(max_length=2, choices=LENGTH_UNITS, default='ft')
    pipe_type = models.CharField(max_length=6, choices=PIPE_TYPES, default='pvc40', help_text="What the pipe is made of")
    pipe_size = models.CharField(max_length=6, choices=SIZE_CHOICES, default='1',
                                 help_text="Nominal size, or enter a custom inside diameter")
    custom_diameter = models.DecimalField(max_digits=6, decimal_places=3, null=True, blank=True,
                                          help_text="Inside diameter, when the size is Custom")
    custom_diameter_unit = models.CharField(max_length=2, choices=DIAMETER_UNITS, default='in')
    count = models.PositiveSmallIntegerField(default=1, help_text="Number of identical pipes (e.g. 2 drains)")
    fill_percent = models.DecimalField(max_digits=5, decimal_places=1, default=100,
                                       help_text="How full the pipe runs. Return lines are 100%; drains often 50-80%")

    class Meta:
        ordering = ['tank', 'id']

    def __str__(self):
        return f"{self.display_name} ({self.length} {self.length_unit}, {self.size_label})"

    @property
    def display_name(self):
        return self.name or "Plumbing run"

    @property
    def inside_diameter_in(self):
        if self.pipe_size == 'custom':
            if not self.custom_diameter:
                return None
            d = float(self.custom_diameter)
            return d / 25.4 if self.custom_diameter_unit == 'mm' else d
        return PIPE_INSIDE.get(self.pipe_type or 'pvc40', PIPE_INSIDE['pvc40']).get(self.pipe_size)

    @property
    def size_label(self):
        if self.pipe_size == 'custom':
            if not self.custom_diameter:
                return "custom (no diameter)"
            return f"{self.custom_diameter.normalize():f} {self.custom_diameter_unit} ID"
        size = PIPE_SIZES.get(self.pipe_size)
        material = PIPE_TYPE_SHORT.get(self.pipe_type or 'pvc40', 'PVC')
        return f'{size[0]} {material}' if size else self.pipe_size

    @property
    def total_length_ft(self):
        length = float(self.length or 0)
        if self.length_unit == 'm':
            length = length / 0.3048
        return length * (self.count or 1)

    @property
    def gallons(self):
        return pipe_volume_gallons(self.total_length_ft, self.inside_diameter_in, self.fill_percent)

    @property
    def liters(self):
        return round(self.gallons * LITERS_PER_GAL, 1)


# Where things sit in the display, seen from the front: across, front to back, and how high.
SPOT_ACROSS = [('left', 'Left'), ('left_center', 'Left of centre'), ('center', 'Centre'),
               ('right_center', 'Right of centre'), ('right', 'Right')]
SPOT_DEPTH = [('back', 'Back'), ('middle', 'Middle'), ('front', 'Front')]
_ACROSS_PERCENT = {'left': 10, 'left_center': 30, 'center': 50, 'right_center': 70, 'right': 90}
_DEPTH_PERCENT = {'back': 18, 'middle': 50, 'front': 82}


def _band(value, words):
    """0-100 split evenly into the given words: _band(10, ('left', 'centre', 'right')) == 'left'."""
    return words[min(len(words) - 1, int(value * len(words) / 101))]


def _aim_words(heading):
    """A heading seen from above (0 = toward the front glass, clockwise) as words."""
    names = ['toward the front', 'toward the front right', 'to the right', 'toward the back right',
             'toward the back', 'toward the back left', 'to the left', 'toward the front left']
    return names[int(((heading % 360) + 22.5) // 45) % 8]


def spot_percent(across, depth):
    """A spot on a top-down sketch of the display (back at the top), as {'left': %, 'top': %}, or None if unset.
    Only one of the two set still places it, in the middle of the other."""
    if not across and not depth:
        return None
    return {'left': _ACROSS_PERCENT.get(across, 50), 'top': _DEPTH_PERCENT.get(depth, 50)}


class Sump(DimensionedVessel):
    """A sump / refugium system plumbed to a tank. Can be split into chambers."""
    tank = models.ForeignKey(Tank, on_delete=models.CASCADE, related_name='sumps')
    name = models.CharField(max_length=100, default="Sump")
    notes = models.TextField(blank=True)

    # Sumps run at a lower water level than their box volume, so default to a lower fill.
    fill_percent = models.DecimalField(
        max_digits=5, decimal_places=1, default=60,
        help_text="Usable water as a % of the box volume (glass thickness, water line below the rim, bracing)",
    )
    volume_gallons = models.DecimalField(max_digits=7, decimal_places=1, default=20.0, help_text="Water volume (US gallons)")
    HEAD_UNITS = [('ft', 'ft'), ('m', 'm')]
    head_height = models.DecimalField(
        max_digits=5, decimal_places=1, null=True, blank=True,
        help_text="How far the return pump lifts the water: from the sump's water line up to the return outlet. "
                  "Add about 1 ft (0.3 m) for every 10 ft of pipe and a little for each elbow")
    head_height_unit = models.CharField(max_length=2, choices=HEAD_UNITS, default='ft')
    OVERFLOW_TYPES = [('internal', 'Internal overflow box'), ('corner', 'Corner overflow'),
                      ('coast', 'Coast-to-coast'), ('external', 'External / hang-on'), ('drilled', 'Drilled bulkhead')]
    overflow_type = models.CharField(max_length=10, choices=OVERFLOW_TYPES, blank=True,
                                     help_text="How water leaves the display for this sump")
    overflow_across = models.CharField(max_length=12, choices=SPOT_ACROSS, blank=True,
                                       help_text="Where the overflow is, seen from the front")
    overflow_depth = models.CharField(max_length=6, choices=SPOT_DEPTH, blank=True)

    class Meta:
        ordering = ['tank', 'name']

    @property
    def overflow_label(self):
        """'Corner overflow, back right', or '' if not set."""
        where = ' '.join(p for p in [self.get_overflow_depth_display().lower() if self.overflow_depth else '',
                                     self.get_overflow_across_display().lower() if self.overflow_across else ''] if p)
        kind = self.get_overflow_type_display() if self.overflow_type else ''
        if kind and where:
            return f"{kind}, {where}"
        return kind or (where[:1].upper() + where[1:])

    @property
    def overflow_spot(self):
        if self.overflow_type == 'coast':  # runs the whole back wall
            return {'left': 50, 'top': _DEPTH_PERCENT.get(self.overflow_depth or 'back'), 'wide': True}
        return spot_percent(self.overflow_across, self.overflow_depth)

    @property
    def head_height_ft(self):
        if self.head_height is None:
            return None
        return float(self.head_height) * (FT_PER_M if self.head_height_unit == 'm' else 1)

    def __str__(self):
        return f"{self.name} ({self.volume_gallons} gal)"

    @property
    def chamber_share_total(self):
        return round(sum(float(c.share_percent or 0) for c in self.chambers.all()), 1)


class SumpChamber(models.Model):
    """One compartment of a sump (return, skimmer, refugium, filtration...)."""
    CHAMBER_TYPES = [
        ('inflow', '⬇️ Inflow / Filter Sock'),
        ('skimmer', '🫧 Protein Skimmer'),
        ('filter', '🧽 Filtration / Media'),
        ('refugium', '🌿 Refugium'),
        ('bubble_trap', '💨 Bubble Trap'),
        ('heater', '🌡️ Heater / Equipment'),
        ('ato', '💧 ATO / Top-off'),
        ('return', '🔄 Return Pump'),
        ('other', '⚙️ Other'),
    ]

    sump = models.ForeignKey(Sump, on_delete=models.CASCADE, related_name='chambers')
    position = models.PositiveIntegerField(default=1, help_text="Order in the water path, 1 = first")
    name = models.CharField(max_length=80, blank=True)
    chamber_type = models.CharField(max_length=20, choices=CHAMBER_TYPES, default='other')
    share_percent = models.DecimalField(max_digits=5, decimal_places=1, default=0, help_text="Share of the sump's water volume in this chamber")
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ['sump', 'position', 'id']

    def __str__(self):
        return f"{self.display_name} ({self.sump.name})"

    @property
    def display_name(self):
        return self.name or self.get_chamber_type_display()

    @property
    def volume_gallons(self):
        return round(float(self.sump.volume_gallons or 0) * float(self.share_percent or 0) / 100.0, 1)


class Equipment(models.Model):
    """Hardware attached to an aquarium system."""
    CATEGORY_CHOICES = [
        ('lighting', '💡 Lighting'),
        ('return_pump', '🔄 Return Pump'),
        ('wavemaker', '🌊 Wavemaker / Powerhead'),
        ('skimmer', '🫧 Protein Skimmer'),
        ('heater', '🌡️ Heater & Temperature Controller'),
        ('dosing', '🧪 Dosing Pump'),
        ('ato', '💧 Auto Top-Off (ATO) Unit'),
        ('feeder', '🍤 Auto Feeder'),
        ('substrate', '🏖️ Substrate'),
        ('filter', '🧦 Filter (sock, roller mat, sponge, canister)'),
        ('filtration', '🧽 Filtration & Media Reactor'),
        ('monitoring', '📊 Monitor / Controller (Apex, ReefBot)'),
        ('other', '⚙️ Other Equipment'),
    ]

    STATUS_CHOICES = [
        ('operational', 'Operational / Running'),
        ('maintenance_due', 'Maintenance / Service Due'),
        ('offline', 'Offline / Standby'),
    ]

    FLOW_CATEGORIES = ('return_pump', 'wavemaker')
    DEFAULT_RETURN_DERATE = 25  # % lost to head height and plumbing, the middle of the usual 20-40%
    NO_SERVICE_CATEGORIES = ('substrate',)  # sand doesn't get cleaned on a schedule

    tank = models.ForeignKey(Tank, on_delete=models.SET_NULL, null=True, blank=True, related_name='equipment')
    sump = models.ForeignKey(Sump, on_delete=models.SET_NULL, null=True, blank=True, related_name='equipment',
                             help_text="Sump this sits in (blank = display tank)")
    chamber = models.ForeignKey(SumpChamber, on_delete=models.SET_NULL, null=True, blank=True, related_name='equipment',
                                help_text="Sump chamber this sits in")
    name = models.CharField(max_length=120, help_text="e.g. Radion XR30 Pro, Vectra M2 Return Pump")
    category = models.CharField(max_length=30, choices=CATEGORY_CHOICES, default='other')
    brand = models.CharField(max_length=100, blank=True, help_text="Manufacturer or brand")
    wattage = models.PositiveIntegerField(null=True, blank=True, help_text="Power consumption (Watts)")
    installed_date = models.DateField(null=True, blank=True)
    maintenance_interval_days = models.PositiveIntegerField(default=90, help_text="Days between service cleanings (e.g. 90)")
    last_serviced_date = models.DateField(null=True, blank=True, help_text="Last date cleaned or calibrated")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='operational')
    max_flow_gph = models.PositiveIntegerField(null=True, blank=True, help_text="Rated maximum flow in gallons per hour (L/h ÷ 3.785 = gph)")
    power_setting_percent = models.PositiveSmallIntegerField(default=100, help_text="Current power / speed setting, 1-100%")
    flow_derate_percent = models.PositiveSmallIntegerField(default=0, help_text="Flow lost to head height and plumbing, % (return pumps are often 20-40%)")
    max_head = models.DecimalField(max_digits=5, decimal_places=1, null=True, blank=True,
                                   help_text="Return pumps: rated max head from the box, the height where flow stops. "
                                             "With the sump's head height, it replaces the head loss %")
    max_head_unit = models.CharField(max_length=2, choices=[('ft', 'ft'), ('m', 'm')], default='ft')
    # Pumps and wavemakers: where the water comes out in the display, set on the picture pickers.
    # x: 0 left to 100 right, y: 0 back to 100 front, z: 0 surface to 100 bottom (all as seen from the front).
    outlet_x = models.PositiveSmallIntegerField(null=True, blank=True)
    outlet_y = models.PositiveSmallIntegerField(null=True, blank=True)
    outlet_z = models.PositiveSmallIntegerField(null=True, blank=True)
    # heading, seen from above: 0 toward the front glass, 90 to the right, 180 toward the back, 270 to the left.
    outlet_heading = models.PositiveSmallIntegerField(null=True, blank=True)
    # tilt, seen from the front: 90 straight up, 0 level, -90 straight down.
    outlet_tilt = models.SmallIntegerField(default=0)
    paid =models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True,
                               help_text="What you paid in total. Added to The Damage automatically")
    hours_per_day = models.DecimalField(max_digits=4, decimal_places=1, null=True, blank=True,
                                        help_text="Hours it draws power per day, for the power estimate (blank = typical for this category)")
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ['category', 'name']
        verbose_name_plural = 'Equipment'

    def __str__(self):
        tank_str = f" [{self.tank.name}]" if self.tank else ""
        return f"{self.name}{tank_str}"

    def save(self, *args, **kwargs):
        # Keep tank / sump / chamber consistent: a chamber implies its sump, a sump implies its tank.
        if self.chamber_id:
            self.sump_id = self.chamber.sump_id
        if self.sump_id:
            self.tank_id = self.sump.tank_id
        super().save(*args, **kwargs)

    @property
    def location_label(self):
        """Where it sits, e.g. 'Display tank', 'Sump', 'Sump › Return Pump'."""
        if self.chamber_id:
            return f"{self.chamber.sump.name} › {self.chamber.display_name}"
        if self.sump_id:
            return self.sump.name
        if self.tank_id:
            return "Display tank"
        return ""

    @property
    def location_key(self):
        if self.chamber_id:
            return f"chamber:{self.chamber_id}"
        if self.sump_id:
            return f"sump:{self.sump_id}"
        if self.tank_id:
            return f"tank:{self.tank_id}"
        return ""

    @property
    def estimated_flow_gph(self):
        """Estimated real flow (gph) at the current power setting, or None if no max flow is set.
        A return pump in a sump with a head height, whose max head is known, uses its pump curve instead of the
        head loss %."""
        head = self.head_lift_ft
        if head is not None and self.max_head_ft:
            return estimate_flow_at_head(self.max_flow_gph, self.max_head_ft, head, self.power_setting_percent)
        return estimate_flow_gph(self.max_flow_gph, self.power_setting_percent, self.flow_derate_percent)

    @property
    def max_head_ft(self):
        if self.max_head is None:
            return None
        return float(self.max_head) * (FT_PER_M if self.max_head_unit == 'm' else 1)

    @property
    def head_lift_ft(self):
        """The head height this pump lifts against: its sump's, for a return pump sitting in a sump."""
        if self.category != 'return_pump' or not self.sump_id:
            return None
        return self.sump.head_height_ft

    SCHEDULE_CATEGORIES = ('lighting', 'skimmer', 'return_pump', 'wavemaker', 'feeder', 'dosing', 'ato', 'filter',
                           'filtration', 'heater', 'other')

    @property
    def schedule_events(self):
        """Every time of day this runs something, from its active automated routines, earliest first."""
        events = []
        for routine in self.routines.all():
            if routine.is_automated and routine.is_active:
                events.extend(routine.sorted_events)
        return sorted(events, key=lambda e: e['time'])

    @property
    def schedule_text(self):
        """'10:00 Lights on · 20:00 Lights off', or ''."""
        return ' · '.join(f"{e['time']} {e.get('action', '')}".strip() for e in self.schedule_events)

    @property
    def has_outlet(self):
        return self.outlet_x is not None and self.outlet_y is not None

    @property
    def outlet_label(self):
        """'Back, centre, near the surface, toward the front, angled up', or '' if not placed."""
        if not self.has_outlet:
            return ''
        parts = [_band(self.outlet_y, ('Back', 'Middle', 'Front')),
                 _band(self.outlet_x, ('left', 'left of centre', 'centre', 'right of centre', 'right'))]
        if self.outlet_z is not None:
            parts.append(_band(self.outlet_z, ('near the surface', 'mid-water', 'near the bottom')))
        tilt = self.outlet_tilt or 0
        if tilt >= 60:
            parts.append('pointing up')
        elif tilt <= -60:
            parts.append('pointing down')
        elif self.outlet_heading is not None:
            parts.append(_aim_words(self.outlet_heading))
            if tilt >= 15:
                parts.append('angled up')
            elif tilt <= -15:
                parts.append('angled down')
        return ', '.join(parts)

    @property
    def outlet_spot(self):
        """Where to draw it on the top-down sketch, as left/top percentages, or None."""
        if not self.has_outlet:
            return None
        return {'left': 6 + self.outlet_x * 0.88, 'top': 10 + self.outlet_y * 0.8}

    @property
    def uses_head_curve(self):
        return self.head_lift_ft is not None and bool(self.max_head_ft) and bool(self.max_flow_gph)

    @property
    def estimated_flow_gph_display(self):
        flow = self.estimated_flow_gph
        return round(flow) if flow is not None else None

    @property
    def estimated_flow_lph_display(self):
        lph = gph_to_lph(self.estimated_flow_gph)
        return round(lph) if lph is not None else None

    @property
    def _service_anchor(self):
        return self.last_serviced_date or self.installed_date

    @property
    def needs_service(self):
        return self.category not in self.NO_SERVICE_CATEGORIES

    @property
    def is_service_due(self):
        """True if the equipment needs its routine cleaning/service."""
        if self.status == 'offline' or not self.needs_service:
            return False
        if self.status == 'maintenance_due':
            return True
        anchor = self._service_anchor
        if not anchor:
            return False
        due_date = anchor + timedelta(days=self.maintenance_interval_days)
        return timezone.localdate() >= due_date

    @property
    def days_until_service(self):
        anchor = self._service_anchor
        if not anchor:
            return None
        due_date = anchor + timedelta(days=self.maintenance_interval_days)
        return (due_date - timezone.localdate()).days


class DosingReservoir(models.Model):
    """Liquid additive reservoirs and ATO freshwater containers with runout estimation."""
    RESERVOIR_TYPES = [
        ('dosing_additive', '🧪 Chemical Additive (Alk, Ca, Mg, AFR)'),
        ('ato_freshwater', '💧 ATO Fresh RO/DI Water'),
    ]

    tank = models.ForeignKey(Tank, on_delete=models.CASCADE, related_name='reservoirs')
    name = models.CharField(max_length=100, help_text="e.g. Alkalinity (Soda Ash), Calcium, All-For-Reef, ATO RO/DI")
    reservoir_type = models.CharField(max_length=20, choices=RESERVOIR_TYPES, default='dosing_additive')
    capacity = models.DecimalField(max_digits=8, decimal_places=2, help_text="Total container size (ml for dosing, gal for ATO)")
    current_level = models.DecimalField(max_digits=8, decimal_places=2, help_text="Current liquid amount remaining")
    unit = models.CharField(max_length=10, default='ml', help_text="ml for dosing, gal or L for ATO")
    daily_consumption = models.DecimalField(max_digits=8, decimal_places=2, help_text="Daily dose (ml/day) or evaporation (gal/day)")
    color = models.CharField(max_length=20, default="#06b6d4")
    last_refilled_date = models.DateField(default=timezone.localdate)
    # current_level is what was in it at this moment. With a daily use set, it counts down from here by itself.
    level_set_at = models.DateTimeField(default=timezone.now, editable=False)

    class Meta:
        ordering = ['reservoir_type', 'name']

    def __str__(self):
        return f"{self.name} ({self.level_now}/{self.capacity} {self.unit})"

    @property
    def counts_down(self):
        """True when it has a daily use, so the level is an estimate that drops by itself."""
        return bool(self.daily_consumption and self.daily_consumption > 0)

    def level_at(self, when=None):
        """The estimated level at `when` (default now): the last level set, less the daily use since then."""
        level = float(self.current_level)
        if not self.counts_down or not self.level_set_at:
            return level
        days = max(0.0, ((when or timezone.now()) - self.level_set_at).total_seconds() / 86400)
        return max(0.0, level - float(self.daily_consumption) * days)

    @property
    def level_now(self):
        return round(self.level_at(), 2)

    def level_now_decimal(self, when=None):
        """level_at as a 2-place Decimal, ready to save back as current_level."""
        return Decimal(str(round(self.level_at(when), 2)))

    @property
    def percent_remaining(self):
        if not self.capacity or self.capacity <= 0:
            return 0
        pct = (self.level_now / float(self.capacity)) * 100
        return max(0, min(100, round(pct)))

    @property
    def days_remaining(self):
        if not self.counts_down:
            return None
        return max(0.0, round(self.level_now / float(self.daily_consumption), 1))

    @property
    def estimated_empty_date(self):
        """The day it runs out. Fixed from when the level was set, so it doesn't slide later each day."""
        if not self.counts_down:
            return None
        start = self.level_set_at or timezone.now()
        empty_at = start + timedelta(days=float(self.current_level) / float(self.daily_consumption))
        return timezone.localdate(empty_at)

    @property
    def is_low(self):
        """Flagged if under 20% or less than 3 days of liquid remain."""
        if self.percent_remaining <= 20:
            return True
        if self.days_remaining is not None and self.days_remaining <= 3:
            return True
        return False


class MaintenanceRoutine(models.Model):
    """
    Either a manual checklist you tick off every N days (water changes, testing, cleaning),
    or an automated schedule your equipment runs on its own (feeders, lights, skimmer, pumps).
    """
    TYPE_CHOICES = [
        ('manual', '📋 Manual checklist'),
        ('automated', '🤖 Automated schedule'),
    ]
    CATEGORY_CHOICES = [
        ('water_change', '🌊 Water Change'),
        ('testing', '🧪 Water Testing'),
        ('equipment', '⚙️ Equipment Maintenance'),
        ('general', '📋 General Care'),
        ('feeding', '🍤 Feeding'),
        ('lighting', '💡 Lighting'),
        ('skimmer', '🫧 Skimmer'),
        ('flow', '🌀 Pumps & Flow'),
        ('dosing', '🧪 Dosing'),
        ('ato', '💧 Top-Off'),
    ]

    tank = models.ForeignKey(Tank, on_delete=models.CASCADE, null=True, blank=True, related_name='routines')
    title = models.CharField(max_length=120, help_text="e.g. Weekly Water Change & Sump Siphon")
    routine_type = models.CharField(max_length=10, choices=TYPE_CHOICES, default='manual')
    category = models.CharField(max_length=20, choices=CATEGORY_CHOICES, default='general')
    equipment = models.ManyToManyField(Equipment, blank=True, related_name='routines',
                                       help_text="Equipment this routine runs on or services")
    # Set for the daily schedule made from a piece of equipment's own edit form; it goes when the schedule is cleared.
    owner_equipment = models.OneToOneField(Equipment, on_delete=models.CASCADE, null=True, blank=True,
                                           related_name='own_schedule', editable=False)
    # Repeat schedule (both types): every N days / weeks / months / years from the start date.
    repeat_every = models.PositiveIntegerField(default=1, help_text="Repeat every N units")
    repeat_unit = models.CharField(max_length=5, choices=sched.UNITS, default='week')
    start_date = models.DateField(default=timezone.localdate, help_text="First day the schedule applies")
    schedule_days = models.JSONField(default=list, blank=True,
                                     help_text="Weekly schedules: weekdays it runs, 0 = Monday ... 6 = Sunday")
    due_time = models.TimeField(null=True, blank=True, help_text="Manual routines: time of day it's due (optional)")
    checklist_items = models.JSONField(default=list, help_text="List of task strings")
    schedule_events = models.JSONField(default=list, blank=True,
                                       help_text='Automated events: [{"time": "08:00", "action": "Lights on"}]')
    is_active = models.BooleanField(default=True, help_text="Untick to pause this routine")
    last_completed = models.DateTimeField(null=True, blank=True)
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ['title']

    def __str__(self):
        return f"{self.title} ({self.recurrence_label})"

    @property
    def is_automated(self):
        return self.routine_type == 'automated'

    @property
    def recurrence_label(self):
        return sched.describe(self.start_date, self.repeat_every, self.repeat_unit, self.schedule_days)

    def _occurs_on(self, day):
        return sched.occurs_on(day, self.start_date, self.repeat_every, self.repeat_unit, self.schedule_days)

    # ---- manual routines ----

    @property
    def checklist_steps(self):
        """The checklist with any timers split out. A running one is added by the Routines page."""
        steps = []
        for item in self.checklist_items or []:
            step = sched.parse_step(item)
            step['timer_name'] = f"{self.title}: {step['text']}"[:100]
            step['routine_id'] = self.pk
            steps.append(step)
        return steps

    @property
    def next_due_date(self):
        if self.is_automated:
            return None
        last = timezone.localtime(self.last_completed).date() if self.last_completed else None
        return sched.next_due_date(self.start_date, self.repeat_every, self.repeat_unit, self.schedule_days, last)

    @property
    def days_until_due(self):
        due = self.next_due_date
        return (due - timezone.localdate()).days if due else None

    @property
    def is_due(self):
        # Automated schedules run themselves, and paused routines never nag.
        if self.is_automated or not self.is_active:
            return False
        due = self.next_due_date
        if due is None:
            return False
        today = timezone.localdate()
        if due < today:
            return True
        if due == today:
            return self.due_time is None or timezone.localtime().time() >= self.due_time
        return False

    @property
    def is_overdue(self):
        days = self.days_until_due
        return self.is_due and days is not None and days < 0

    # ---- automated schedule helpers ----

    @property
    def sorted_events(self):
        events = [e for e in (self.schedule_events or []) if isinstance(e, dict) and e.get('time')]
        return sorted(events, key=lambda e: e['time'])

    @property
    def days_display(self):
        return self.recurrence_label

    def next_event(self, now=None):
        """Next scheduled event as {'at': aware datetime, 'time': 'HH:MM', 'action': str}, or None."""
        events = self.sorted_events
        if not (self.is_automated and self.is_active and events):
            return None
        now = timezone.localtime(now or timezone.now())
        for offset in range(sched.period_days(self.repeat_every, self.repeat_unit) + 8):
            day = (now + timedelta(days=offset)).date()
            if not self._occurs_on(day):
                continue
            for e in events:
                try:
                    hh, mm = (int(x) for x in e['time'].split(':'))
                except (ValueError, AttributeError):
                    continue
                at = now.replace(year=day.year, month=day.month, day=day.day,
                                 hour=hh, minute=mm, second=0, microsecond=0)
                if at > now:
                    return {'at': at, 'time': e['time'], 'action': e.get('action', '')}
        return None

    @property
    def upcoming(self):
        return self.next_event()


class WaterChangeLog(models.Model):
    """Historical water change entries."""
    tank = models.ForeignKey(Tank, on_delete=models.CASCADE, related_name='water_changes')
    performed_at = models.DateTimeField(default=timezone.now)
    gallons = models.DecimalField(max_digits=6, decimal_places=1, help_text="Gallons of new water changed")
    salt_brand = models.CharField(max_length=100, blank=True, help_text="e.g. Tropic Marin Pro, Red Sea Blue Bucket")
    target_salinity = models.DecimalField(max_digits=6, decimal_places=3, null=True, blank=True, help_text="Mixed water salinity")
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ['-performed_at']

    def __str__(self):
        return f"{self.gallons} gal change on {self.performed_at:%b %d, %Y}"


class DashboardWidget(models.Model):
    """Per-widget visibility and order for the customizable dashboard."""
    key = models.CharField(max_length=40, unique=True)
    enabled = models.BooleanField(default=True)
    position = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ['position', 'id']

    def __str__(self):
        return f"{self.key} ({'on' if self.enabled else 'off'})"


# ==========================================
# App-wide settings
# ==========================================

# Stored as the symbol itself, which is what the pages show. Choosing one never converts any amounts.
CURRENCIES = [
    ('$', '$ US dollar'),
    ('€', '€ Euro'),
    ('£', '£ British pound'),
    ('CA$', 'CA$ Canadian dollar'),
    ('A$', 'A$ Australian dollar'),
    ('NZ$', 'NZ$ New Zealand dollar'),
    ('¥', '¥ Japanese yen'),
    ('₹', '₹ Indian rupee'),
    ('R$', 'R$ Brazilian real'),
    ('MX$', 'MX$ Mexican peso'),
    ('kr', 'kr Krona / krone'),
    ('CHF', 'CHF Swiss franc'),
]


def currency_choices(current=None):
    """The list above, keeping a symbol someone typed in before this became a list."""
    if current and current not in dict(CURRENCIES):
        return [(current, f'{current} (your own)')] + CURRENCIES
    return list(CURRENCIES)


class AppSettings(models.Model):
    """Single row of app-wide settings and background worker bookkeeping."""
    electricity_rate = models.DecimalField(max_digits=6, decimal_places=4, default=0.15,
                                           help_text="Your electricity price per kWh")
    currency_symbol = models.CharField(max_length=4, default='$')
    costs_enabled = models.BooleanField(default=False, editable=False,
                                        help_text="Prices stay hidden until this is turned on in The Damage")
    disable_icon_aging = models.BooleanField(
        default=False, help_text="Retired tanks keep their young icon instead of switching to the old version")
    enable_old_version_icons = models.BooleanField(
        default=False, help_text="Lets you pick the old version of a character for any tank")
    enable_random_icons = models.BooleanField(
        default=False, help_text="Tanks with no chosen icon show a different character on every page")
    icp_enabled = models.BooleanField(
        default=False, verbose_name='Enable ICP elements',
        help_text="Adds about 30 elements from lab (ICP) water tests, like boron, iodine and copper. They're listed after your regular tests and stay off the All chart and the dashboard until you choose them.")
    alerts_muted_until = models.DateTimeField(null=True, blank=True, editable=False)
    alerts_muted_forever = models.BooleanField(default=False, editable=False)
    resolved_alert_days = models.PositiveSmallIntegerField(
        'Days to keep resolved alerts', default=7, validators=[MinValueValidator(1), MaxValueValidator(30)],
        help_text="How long resolved alerts and their metrics stay on the Alerts page (1 to 30)")
    auto_backup_days = models.PositiveIntegerField(default=7, help_text="Make a backup every N days (0 = off)")
    auto_backup_keep = models.PositiveIntegerField(default=4, help_text="How many automatic backups to keep")
    worker_last_seen = models.DateTimeField(null=True, blank=True, editable=False)
    last_schedule_check = models.DateTimeField(null=True, blank=True, editable=False)
    events_baselined = models.BooleanField(default=False, editable=False)
    last_auto_backup = models.DateTimeField(null=True, blank=True, editable=False)

    class Meta:
        verbose_name_plural = 'App settings'

    def __str__(self):
        return 'App settings'

    @classmethod
    def load(cls):
        # Read once per page view; many parts of a page ask for the settings.
        from . import request_cache
        return request_cache.get('app_settings', lambda: cls.objects.get_or_create(pk=1)[0])

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        from . import request_cache
        request_cache.forget('app_settings')

    @property
    def alerts_muted(self):
        if self.alerts_muted_forever:
            return True
        return bool(self.alerts_muted_until and timezone.now() < self.alerts_muted_until)

    @property
    def worker_online(self):
        return bool(self.worker_last_seen and timezone.now() - self.worker_last_seen < timedelta(minutes=3))


# ==========================================
# Quarantine & growth timeline
# ==========================================

class QuarantineEntry(models.Model):
    """One line in an animal's quarantine log: a medication dose, an observation, a water change..."""
    KIND_CHOICES = [
        ('medication', '💊 Medication'),
        ('observation', '👀 Observation'),
        ('water_change', '🌊 Water change'),
        ('test', '🧪 Water test'),
    ]
    animal = models.ForeignKey(Animal, on_delete=models.CASCADE, related_name='quarantine_entries')
    logged_on = models.DateField(default=timezone.localdate)
    kind = models.CharField(max_length=15, choices=KIND_CHOICES, default='observation')
    medication = models.CharField(max_length=100, blank=True, help_text="e.g. copper, praziquantel")
    dose = models.CharField(max_length=60, blank=True, help_text="e.g. 2.5 ml, 0.25 ppm")
    notes = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ['-logged_on', '-id']
        verbose_name_plural = 'Quarantine entries'

    def __str__(self):
        return f"{self.animal.name}: {self.get_kind_display()} on {self.logged_on}"


class AnimalPhoto(models.Model):
    """Dated photo for the growth timeline."""
    animal = models.ForeignKey(Animal, on_delete=models.CASCADE, related_name='timeline_photos')
    image = models.ImageField(upload_to='timeline/')
    taken_on = models.DateField(default=timezone.localdate)
    note = models.CharField(max_length=200, blank=True)

    class Meta:
        ordering = ['taken_on', 'id']

    def __str__(self):
        return f"{self.animal.name} on {self.taken_on}"


class TimelapseFrame(models.Model):
    """One captured webcam frame."""
    feed = models.ForeignKey(WebcamFeed, on_delete=models.CASCADE, related_name='frames')
    image = models.ImageField(upload_to='timelapse/')
    captured_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ['captured_at']

    def __str__(self):
        return f"{self.feed.name} @ {self.captured_at:%Y-%m-%d %H:%M}"


# ==========================================
# Webhooks & alert delivery
# ==========================================

class WebhookEndpoint(models.Model):
    """Somewhere to send events: Home Assistant, a phone alert service, your own script."""
    FORMAT_CHOICES = [
        ('json', 'JSON webhook (Home Assistant, scripts, ESP32)'),
        ('ntfy', 'Phone alert via ntfy'),
    ]
    name = models.CharField(max_length=80)
    # Not a URLField: its validator rejects short local device names such as http://esp32-feeder/
    url = models.CharField(max_length=500, help_text="http(s) address to POST to. For ntfy: https://ntfy.sh/your-private-topic")
    format = models.CharField(max_length=10, choices=FORMAT_CHOICES, default='json')
    secret = models.CharField(max_length=128, blank=True,
                              help_text="Optional. JSON webhooks are signed with this (X-Nudibranch-Signature)")
    event_types = models.JSONField(default=list, blank=True, help_text="Events to send; empty means all")
    routines = models.ManyToManyField(MaintenanceRoutine, blank=True, related_name='webhook_endpoints',
                                      help_text="Only send routine events for these")
    timer_reservoirs = models.ManyToManyField(DosingReservoir, blank=True, related_name='webhook_endpoints',
                                              help_text="Only send fill timer events for these reservoirs")
    is_active = models.BooleanField(default=True)
    pause_reason = models.CharField(max_length=200, blank=True, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return self.name

    def wants(self, event_type, routine_id=None, reservoir_id=None, check_targets=True):
        """
        Whether this endpoint should receive an event.

        An endpoint with targets and no ticked event types receives only events about its targets.
        That matters for hardware: a webhook pointed at a feeder must not fire on a parameter alert.
        """
        if not self.is_active:
            return False
        routine_ids = set(self.routines.values_list('pk', flat=True))
        reservoir_ids = set(self.timer_reservoirs.values_list('pk', flat=True))
        is_routine_event = event_type.startswith('routine.')
        is_timer_event = event_type.startswith('timer.')

        if self.event_types:
            if event_type not in self.event_types:
                return False
        elif routine_ids or reservoir_ids:
            if not ((is_routine_event and routine_ids) or (is_timer_event and reservoir_ids)):
                return False

        if check_targets:
            if is_routine_event and routine_ids and routine_id not in routine_ids:
                return False
            if is_timer_event and reservoir_ids and reservoir_id not in reservoir_ids:
                return False
        return True


class WebhookDelivery(models.Model):
    """One event being sent to one endpoint, with its retry state."""
    STATUS_CHOICES = [('pending', 'Pending'), ('sent', 'Sent'), ('failed', 'Failed')]

    endpoint = models.ForeignKey(WebhookEndpoint, on_delete=models.CASCADE, related_name='deliveries')
    event_id = models.CharField(max_length=36)
    event_type = models.CharField(max_length=40)
    severity = models.CharField(max_length=10, default='info')
    title = models.CharField(max_length=200)
    message = models.CharField(max_length=500, blank=True)
    data = models.JSONField(default=dict, blank=True)
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default='pending')
    attempts = models.PositiveSmallIntegerField(default=0)
    max_attempts = models.PositiveSmallIntegerField(default=5)
    next_attempt_at = models.DateTimeField(default=timezone.now)
    response_code = models.PositiveSmallIntegerField(null=True, blank=True)
    error = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(default=timezone.now)
    sent_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-created_at', '-id']
        constraints = [
            models.UniqueConstraint(fields=['endpoint', 'event_id'], name='unique_delivery_per_endpoint'),
        ]
        verbose_name_plural = 'Webhook deliveries'

    def __str__(self):
        return f"{self.event_type} -> {self.endpoint.name} ({self.status})"


class EventState(models.Model):
    """Remembers which conditions already fired, so each one only notifies when it first happens."""
    key = models.CharField(max_length=120, unique=True)
    event_type = models.CharField(max_length=40)
    activated_at = models.DateTimeField(default=timezone.now)
    cleared_at = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return self.key


class AlertRecord(models.Model):
    """One problem from when it started until it was resolved, for the history on the Alerts page."""
    SYSTEM_RETIRED = 'retired'
    NOTICE = 'notice'  # something worth knowing, not a problem that was fixed, such as a quarantine ending

    issue_key = models.CharField(max_length=120, db_index=True)
    event_type = models.CharField(max_length=40)
    severity = models.CharField(max_length=10, help_text="The worst it got")
    tank = models.ForeignKey('Tank', on_delete=models.CASCADE, null=True, blank=True, related_name='alert_records')
    subject = models.CharField(max_length=120)
    title = models.CharField(max_length=200)
    message = models.CharField(max_length=300, blank=True)
    started_at = models.DateTimeField(default=timezone.now)
    resolved_at = models.DateTimeField(null=True, blank=True, db_index=True)
    resolution = models.CharField(max_length=20, blank=True)

    class Meta:
        ordering = ['-started_at']

    def __str__(self):
        return self.title

    @property
    def display_title(self):
        """Without the system's name in front: the Alerts page only ever shows one system."""
        return self.title.removeprefix(f"{self.tank.name}: ") if self.tank else self.title

    @property
    def duration(self):
        return (self.resolved_at or timezone.now()) - self.started_at

    @property
    def duration_label(self):
        return self.describe(self.duration)

    @staticmethod
    def describe(span):
        minutes = int(span.total_seconds() // 60)
        if minutes < 1:
            return 'under a minute'
        days, minutes = divmod(minutes, 1440)
        hours, minutes = divmod(minutes, 60)
        parts = [(days, 'day'), (hours, 'hour')] if days else [(hours, 'hour'), (minutes, 'minute')]
        return ', '.join(f"{count} {name}{'s' if count != 1 else ''}" for count, name in parts if count)


# ==========================================
# RO/DI systems & fill timers
# ==========================================

class ROSystem(models.Model):
    """An RO/DI unit, used to estimate how long a fill takes."""
    name = models.CharField(max_length=80, default='RO/DI')
    rated_gpd = models.DecimalField(max_digits=6, decimal_places=1, default=75, help_text="Membrane rating, gallons per day")
    rated_psi = models.DecimalField(max_digits=5, decimal_places=1, default=60, help_text="Pressure the rating is quoted at (check your membrane's spec sheet)")
    rated_temp_f = models.DecimalField(max_digits=5, decimal_places=1, default=77, help_text="Temperature the rating is quoted at (usually 77°F)")
    feed_psi = models.DecimalField(max_digits=5, decimal_places=1, default=60, help_text="Your water pressure at the unit")
    feed_temp_f = models.DecimalField(max_digits=5, decimal_places=1, default=60, help_text="Your incoming water temperature")
    waste_ratio = models.DecimalField(max_digits=4, decimal_places=1, default=3, help_text="Gallons of waste per gallon of product (3 means 1:3)")
    measured_gph = models.DecimalField(max_digits=6, decimal_places=2, null=True, blank=True,
                                       help_text="Optional: your real timed output in gallons per hour. Overrides the estimate")
    is_default = models.BooleanField(default=True)

    class Meta:
        ordering = ['-is_default', 'name']
        verbose_name = 'RO system'

    def __str__(self):
        return f"{self.name} ({self.rated_gpd} GPD)"


ML_PER_UNIT = {'ml': Decimal('1'), 'l': Decimal('1000'), 'liter': Decimal('1000'), 'liters': Decimal('1000'),
               'gal': Decimal('3785.41'), 'gallon': Decimal('3785.41'), 'gallons': Decimal('3785.41'),
               'tsp': Decimal('4.92892'), 'fl oz': Decimal('29.5735')}


class DoseLog(models.Model):
    """Something added to a tank: a dose of an additive, by hand or from the Dose Estimator.

    A liquid dose taken from a container comes off that container's level, and goes back if the dose is deleted.
    """
    UNITS = [('ml', 'ml'), ('g', 'g'), ('tsp', 'tsp'), ('fl oz', 'fl oz'), ('drops', 'drops')]

    tank = models.ForeignKey(Tank, on_delete=models.CASCADE, related_name='doses')
    parameter = models.CharField(max_length=20, blank=True, help_text="What it's for, like alkalinity")
    product = models.CharField(max_length=100, blank=True, help_text="What you added, like soda ash or All-For-Reef")
    amount = models.DecimalField(max_digits=8, decimal_places=2)
    unit = models.CharField(max_length=10, choices=UNITS, default='ml')
    reservoir = models.ForeignKey('DosingReservoir', on_delete=models.SET_NULL, null=True, blank=True, related_name='doses',
                                  help_text="Take it off this container's level")
    taken = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True, editable=False,
                                help_text="How much came off the container, in its own unit")
    dosed_at = models.DateTimeField(default=timezone.now)
    notes = models.CharField(max_length=200, blank=True)

    class Meta:
        ordering = ['-dosed_at', '-id']

    def __str__(self):
        return f"{self.amount_label} {self.product or self.parameter_label} on {self.dosed_at:%b %d}"

    @property
    def amount_label(self):
        return f"{self.amount.normalize():f} {self.unit}"

    @property
    def parameter_label(self):
        from .calculators import DOSE_PARAMETERS
        return DOSE_PARAMETERS.get(self.parameter, {}).get('name', self.parameter.title())

    def amount_in(self, unit):
        """This dose in a container's unit, or None when they can't be compared (grams, drops, an unknown unit)."""
        mine, theirs = ML_PER_UNIT.get(self.unit), ML_PER_UNIT.get((unit or '').strip().lower())
        if mine is None or theirs is None:
            return None
        return (self.amount * mine / theirs).quantize(Decimal('0.01'))

    def save(self, *args, **kwargs):
        from django.db import transaction
        with transaction.atomic():
            if self.pk:  # an edit: put back what the old version took, then take the new amount
                old = DoseLog.objects.filter(pk=self.pk).select_related('reservoir').first()
                if old:
                    old._give_back()
            self.taken = None
            if self.reservoir_id:
                reservoir = DosingReservoir.objects.select_for_update().get(pk=self.reservoir_id)
                take = self.amount_in(reservoir.unit)
                if take is not None:
                    now = timezone.now()
                    level = reservoir.level_now_decimal(now)  # what's in it now, after its daily use
                    taken = min(take, level)
                    DosingReservoir.objects.filter(pk=reservoir.pk).update(current_level=level - taken, level_set_at=now)
                    self.taken = taken
            super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        from django.db import transaction
        with transaction.atomic():
            self._give_back()
            return super().delete(*args, **kwargs)

    def _give_back(self):
        if self.reservoir_id and self.taken:
            reservoir = DosingReservoir.objects.select_for_update().filter(pk=self.reservoir_id).first()
            if reservoir:
                now = timezone.now()
                level = min(reservoir.capacity, reservoir.level_now_decimal(now) + self.taken)
                DosingReservoir.objects.filter(pk=reservoir.pk).update(current_level=level, level_set_at=now)


class QuickTimer(models.Model):
    """A saved timer on the dashboard, like "Feeding, 3 min", ready to start with one tap."""
    name = models.CharField(max_length=60)
    seconds = models.PositiveIntegerField(help_text="How long it runs")
    position = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ['position', 'id']

    def __str__(self):
        return f"{self.name} ({self.duration_label})"

    @property
    def duration_label(self):
        hours, rest = divmod(self.seconds, 3600)
        minutes, seconds = divmod(rest, 60)
        parts = [f"{hours} hr" if hours else '', f"{minutes} min" if minutes else '', f"{seconds} sec" if seconds else '']
        return ' '.join(part for part in parts if part) or '0 sec'

    @property
    def clock(self):
        """The time as the countdown shows it, e.g. 05:00 or 1:30:00."""
        hours, rest = divmod(self.seconds, 3600)
        minutes, seconds = divmod(rest, 60)
        return f"{hours}:{minutes:02d}:{seconds:02d}" if hours else f"{minutes:02d}:{seconds:02d}"


class FillTimer(models.Model):
    """A running countdown, e.g. while an ATO reservoir fills."""
    STATUS_CHOICES = [('running', 'Running'), ('finished', 'Finished'), ('cancelled', 'Cancelled')]

    name = models.CharField(max_length=100)
    reservoir = models.ForeignKey(DosingReservoir, on_delete=models.SET_NULL, null=True, blank=True, related_name='timers')
    routine = models.ForeignKey(MaintenanceRoutine, on_delete=models.SET_NULL, null=True, blank=True, related_name='timers',
                                help_text="Set when this timer belongs to a step of a routine")
    quick_timer = models.ForeignKey(QuickTimer, on_delete=models.SET_NULL, null=True, blank=True, related_name='runs',
                                    help_text="Set when started from a saved timer on the dashboard")
    started_at = models.DateTimeField(default=timezone.now)
    ends_at = models.DateTimeField()
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default='running')
    notified = models.BooleanField(default=False)
    endpoints = models.ManyToManyField(WebhookEndpoint, blank=True, related_name='timers',
                                       help_text="Send this timer's alert only here (none chosen = the usual connections)")

    class Meta:
        ordering = ['ends_at']

    def __str__(self):
        return self.name

    @property
    def is_running(self):
        return self.status == 'running'


# ==========================================
# System planner
# ==========================================

class PlanProject(models.Model):
    """A group of planned systems to compare and budget together. Nothing in it is tracked until each plan is."""
    name = models.CharField(max_length=100)
    budget = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True, help_text="Budget for all its tanks together")
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return self.name


class PlannedSystem(DimensionedVessel):
    """A draft system (or a stocking plan for an existing tank) that can be turned into tracked records."""
    GOAL_CHOICES = [
        ('mixed', 'Mixed reef'),
        ('soft', 'Soft coral reef'),
        ('lps', 'LPS dominant reef'),
        ('sps', 'SPS dominant reef'),
        ('fowlr', 'Fish only with live rock'),
        ('nano', 'Nano reef'),
    ]
    name = models.CharField(max_length=100)
    project = models.ForeignKey(PlanProject, on_delete=models.SET_NULL, null=True, blank=True, related_name='plans',
                                help_text="Group this with other planned tanks to compare them and total them up")
    goal = models.CharField(max_length=10, choices=GOAL_CHOICES, default='mixed')
    existing_tank = models.ForeignKey(Tank, on_delete=models.SET_NULL, null=True, blank=True, related_name='plans',
                                      help_text="Planning additions to a tank you already track? Choose it here")
    sump_gallons = models.DecimalField(max_digits=7, decimal_places=1, default=0, help_text="Sump water volume (0 = no sump)")
    budget = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    notes = models.TextField(blank=True)
    tracked_tank = models.ForeignKey(Tank, on_delete=models.SET_NULL, null=True, blank=True, related_name='source_plans',
                                     editable=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-updated_at']

    def __str__(self):
        return self.name


class PlannedItem(models.Model):
    """A planned animal or piece of equipment."""
    KIND_CHOICES = [('livestock', 'Livestock'), ('equipment', 'Equipment')]

    plan = models.ForeignKey(PlannedSystem, on_delete=models.CASCADE, related_name='items')
    kind = models.CharField(max_length=10, choices=KIND_CHOICES)
    species = models.ForeignKey(SpeciesCatalog, on_delete=models.SET_NULL, null=True, blank=True, related_name='planned_items')
    name = models.CharField(max_length=120)
    quantity = models.PositiveIntegerField(default=1)
    unit_cost = models.DecimalField(max_digits=9, decimal_places=2, null=True, blank=True, help_text="Price each")
    category = models.CharField(max_length=30, choices=Equipment.CATEGORY_CHOICES, blank=True)
    wattage = models.PositiveIntegerField(null=True, blank=True, help_text="Watts each")
    max_flow_gph = models.PositiveIntegerField(null=True, blank=True, help_text="Rated flow each, gph")
    power_percent = models.PositiveSmallIntegerField(default=100, help_text="Lights and pumps: how hard it'll run, 1-100%")
    hours_per_day = models.DecimalField(max_digits=4, decimal_places=1, null=True, blank=True,
                                        help_text="Lights: hours on a day")
    tracked = models.BooleanField(default=False, editable=False)

    class Meta:
        ordering = ['kind', 'name']

    def __str__(self):
        return f"{self.quantity}x {self.name}"

    @property
    def total_cost(self):
        return (self.unit_cost or 0) * self.quantity


class WishlistItem(models.Model):
    """Something you'd like to get one day. Can move into a plan, or straight into tracking once bought."""
    KIND_CHOICES = PlannedItem.KIND_CHOICES
    PRIORITY_CHOICES = [('must', 'Must have'), ('want', 'Want'), ('someday', 'Someday')]
    STATUS_CHOICES = [('wanted', 'Wanted'), ('acquired', 'Bought')]

    kind = models.CharField(max_length=10, choices=KIND_CHOICES, default='livestock')
    species = models.ForeignKey(SpeciesCatalog, on_delete=models.SET_NULL, null=True, blank=True, related_name='wishlist_items')
    name = models.CharField(max_length=120)
    quantity = models.PositiveIntegerField(default=1)
    priority = models.CharField(max_length=10, choices=PRIORITY_CHOICES, default='want')
    est_price = models.DecimalField(max_digits=9, decimal_places=2, null=True, blank=True, help_text="Estimated price each")
    link = models.URLField(max_length=500, blank=True, help_text="Store page or article")
    tank = models.ForeignKey(Tank, on_delete=models.SET_NULL, null=True, blank=True, related_name='wishlist_items',
                             help_text="Tank to check it against (blank = your primary tank)")
    category = models.CharField(max_length=30, choices=Equipment.CATEGORY_CHOICES, blank=True)
    wattage = models.PositiveIntegerField(null=True, blank=True, help_text="Watts each")
    max_flow_gph = models.PositiveIntegerField(null=True, blank=True, help_text="Rated flow each, gph")
    notes = models.TextField(blank=True)
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default='wanted')
    # Set while the item is in a plan. Removing it from the plan (or deleting the plan) returns it to the list.
    planned_item = models.OneToOneField(PlannedItem, on_delete=models.SET_NULL, null=True, blank=True,
                                        related_name='wishlist_item', editable=False)
    created_at = models.DateTimeField(auto_now_add=True)
    acquired_at = models.DateTimeField(null=True, blank=True, editable=False)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.quantity}x {self.name} ({self.get_priority_display()})"

    @property
    def total_price(self):
        return (self.est_price or 0) * self.quantity


class CostEntry(models.Model):
    """One line in the hidden spending ledger."""
    CATEGORY_CHOICES = [
        ('tank', '🏛️ Tank & plumbing'),
        ('equipment', '⚙️ Equipment'),
        ('livestock', '🐠 Livestock'),
        ('rock', '🪨 Rock & sand'),
        ('salt', '🧂 Salt & water'),
        ('additives', '🧪 Additives & testing'),
        ('food', '🍤 Food'),
        ('other', '💸 Other'),
    ]
    tank = models.ForeignKey(Tank, on_delete=models.SET_NULL, null=True, blank=True, related_name='cost_entries')
    spent_on = models.DateField(default=timezone.localdate)
    category = models.CharField(max_length=15, choices=CATEGORY_CHOICES, default='other')
    description = models.CharField(max_length=150)
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    # Set when this entry comes from an animal's or equipment's "what you paid". The money stays spent if it's deleted.
    animal = models.OneToOneField(Animal, on_delete=models.SET_NULL, null=True, blank=True, editable=False, related_name='cost_entry')
    equipment = models.OneToOneField(Equipment, on_delete=models.SET_NULL, null=True, blank=True, editable=False, related_name='cost_entry')

    class Meta:
        ordering = ['-spent_on', '-id']
        verbose_name_plural = 'Cost entries'

    def __str__(self):
        return f"{self.description}: {self.amount}"


def _sync_paid_entry(instance, link, category, description, day, keep_details=False):
    """
    Keeps the ledger line for an animal's or equipment's "what you paid" matching it.
    keep_details leaves an existing line's wording, category and date alone, so a confession stays as written.
    """
    entry = CostEntry.objects.filter(**{link: instance}).first()
    if instance.paid is None:
        if entry:
            entry.delete()
        return
    is_new = entry is None
    if is_new:
        entry = CostEntry(**{link: instance}, spent_on=day or timezone.localdate())
    elif day and not keep_details:
        entry.spent_on = day
    entry.tank = instance.tank
    if is_new or not keep_details:
        entry.category = category
        entry.description = description[:150]
    entry.amount = instance.paid
    entry.save()


@receiver(post_save, sender=Animal)
def _animal_saved(sender, instance, raw=False, **kwargs):
    if not raw:
        label = f"{instance.count}x {instance.name}" if instance.count > 1 else instance.name
        _sync_paid_entry(instance, 'animal', 'livestock', label, instance.acquired_date)


@receiver(post_save, sender=Equipment)
def _equipment_saved(sender, instance, raw=False, **kwargs):
    if not raw:
        _sync_paid_entry(instance, 'equipment', 'equipment', instance.name, instance.installed_date, keep_details=True)


def _linked_record_querysets(entry):
    if entry.animal_id:
        yield Animal.objects.filter(pk=entry.animal_id)
    if entry.equipment_id:
        yield Equipment.objects.filter(pk=entry.equipment_id)


@receiver(post_save, sender=CostEntry)
def _cost_entry_saved(sender, instance, raw=False, **kwargs):
    """Correcting the amount in the ledger corrects the animal or equipment too."""
    if not raw:
        for records in _linked_record_querysets(instance):
            records.update(paid=instance.amount)  # update() doesn't re-trigger the sync above


@receiver(post_delete, sender=CostEntry)
def _cost_entry_deleted(sender, instance, **kwargs):
    for records in _linked_record_querysets(instance):
        records.update(paid=None)


def _pause_endpoints_losing_last_target(instance, relation, label):
    """
    Without this, deleting an endpoint's only target would widen it to every routine or timer, so a
    webhook wired to one feeder could start firing for everything. Pause it and say why instead.
    """
    for endpoint in instance.webhook_endpoints.all():
        if not getattr(endpoint, relation).exclude(pk=instance.pk).exists():
            endpoint.is_active = False
            endpoint.pause_reason = f"Paused because {label} \"{instance}\" was deleted."[:200]
            endpoint.save(update_fields=['is_active', 'pause_reason'])


@receiver(pre_delete, sender=MaintenanceRoutine)
def _routine_deleted(sender, instance, **kwargs):
    _pause_endpoints_losing_last_target(instance, 'routines', 'its routine')


@receiver(pre_delete, sender=DosingReservoir)
def _reservoir_deleted(sender, instance, **kwargs):
    _pause_endpoints_losing_last_target(instance, 'timer_reservoirs', 'its reservoir')


IMAGE_FIELDS = {AnimalPhoto: 'image', TimelapseFrame: 'image', Animal: 'photo', Tank: 'custom_icon'}


@receiver(post_delete, sender=AnimalPhoto)
@receiver(post_delete, sender=TimelapseFrame)
@receiver(post_delete, sender=Animal)
@receiver(post_delete, sender=Tank)
def _delete_image_file(sender, instance, **kwargs):
    """Removes the image from disk when its record goes, so old files don't fill the drive."""
    image = getattr(instance, IMAGE_FIELDS[sender])
    if image:
        image.delete(save=False)


@receiver(pre_save, sender=Animal)
@receiver(pre_save, sender=AnimalPhoto)
def _compress_new_photo(sender, instance, raw=False, **kwargs):
    """Every new animal photo is saved as a reasonably sized JPEG, wherever it was uploaded from."""
    field = IMAGE_FIELDS[sender]
    image = getattr(instance, field)
    if raw or not image or image._committed:
        return
    smaller = compressed_jpeg(image.file, image.name)
    if smaller is not None:
        setattr(instance, field, smaller)


@receiver(pre_save, sender=Animal)
@receiver(pre_save, sender=Tank)
def _delete_replaced_image(sender, instance, raw=False, **kwargs):
    """A new photo or icon replaces the old file, rather than leaving it on the drive."""
    if raw or not instance.pk:
        return
    field = IMAGE_FIELDS[sender]
    previous = sender.objects.filter(pk=instance.pk).values_list(field, flat=True).first()
    image = getattr(instance, field)
    if previous and previous != (image.name if image else ''):
        image.storage.delete(previous)
