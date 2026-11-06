import urllib.parse
from datetime import timedelta

from django.db import models
from django.utils import timezone

from .calculators import (
    estimate_capacity_gallons, estimate_flow_gph, gph_to_lph, turnover_summary,
    pipe_volume_gallons, LITERS_PER_GAL, PIPE_SIZES,
)
from . import schedule as sched

WEEKDAYS = [(0, 'Mon'), (1, 'Tue'), (2, 'Wed'), (3, 'Thu'), (4, 'Fri'), (5, 'Sat'), (6, 'Sun')]
PIPE_SIZE_CHOICES = [(key, f"{label} PVC") for key, (label, _id) in PIPE_SIZES.items()]


def all_weekdays():
    # Kept because migration 0007 references it.
    return [0, 1, 2, 3, 4, 5, 6]


class ParameterType(models.Model):
    """Represents a measured water metric (e.g. Salinity, Alkalinity, Calcium)."""
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

    class Meta:
        ordering = ['display_order', 'name']

    def __str__(self):
        return f"{self.name} ({self.unit})"

    def latest_log(self):
        return self.logs.order_by('-measured_at').first()

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

    @property
    def step_size(self):
        """Returns input step attribute for HTML numeric fields."""
        if self.decimal_places == 0:
            return "1"
        return f"0.{'0' * (self.decimal_places - 1)}1"


class ParameterLog(models.Model):
    """Historical test measurement."""
    parameter_type = models.ForeignKey(ParameterType, on_delete=models.CASCADE, related_name="logs")
    measured_at = models.DateTimeField(default=timezone.now)
    value = models.DecimalField(max_digits=10, decimal_places=4)
    notes = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ['-measured_at']

    def __str__(self):
        return f"{self.parameter_type.name}: {self.value} {self.parameter_type.unit} @ {self.measured_at:%Y-%m-%d %H:%M}"

    @property
    def formatted_value(self):
        """Formats measurement according to the parameter's configured decimal places."""
        return self.parameter_type.format_value(self.value)

    @property
    def status(self):
        """'low', 'optimal' or 'high' relative to the ideal range."""
        return self.parameter_type.classify(self.value)[0]

    @property
    def severity(self):
        """'ok', 'warning' (outside ideal) or 'critical' (past the low/high limit)."""
        return self.parameter_type.classify(self.value)[1]

    @property
    def status_label(self):
        status, severity = self.parameter_type.classify(self.value)
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


class AnimalGroup(models.Model):
    """Groups / tags for livestock (e.g. 'Cleanup Crew', 'School', 'SPS Corals')."""
    name = models.CharField(max_length=60, unique=True)
    description = models.TextField(blank=True)
    color = models.CharField(max_length=20, default="#64748b", help_text="Hex color for UI tag badges")
    icon = models.CharField(max_length=10, default="🐟", help_text="Emoji or icon symbol")

    class Meta:
        ordering = ['name']

    def __str__(self):
        return self.name


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

    name = models.CharField(max_length=120, help_text="Common name or pet name (e.g. 'Ocellaris Clown Pair')")
    species = models.CharField(max_length=150, blank=True, help_text="Scientific or species name (optional)")
    tank = models.ForeignKey('Tank', on_delete=models.SET_NULL, null=True, blank=True, related_name='animals', help_text="Assigned tank system")
    groups = models.ManyToManyField(AnimalGroup, blank=True, related_name="animals")
    count = models.PositiveIntegerField(default=1, help_text="Quantity (e.g. 10 snails or 5 chromis)")
    acquired_date = models.DateField(null=True, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='healthy')
    photo = models.ImageField(upload_to="livestock/", blank=True, null=True)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['status', 'name']

    def __str__(self):
        qty_str = f" ({self.count}x)" if self.count > 1 else ""
        return f"{self.name}{qty_str}"

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
    feed_url = models.CharField(max_length=500, help_text="URL of the stream, snapshot, or embed link")
    feed_type = models.CharField(max_length=20, choices=FEED_TYPES, default='mjpeg')
    is_active = models.BooleanField(default=True)
    order = models.PositiveIntegerField(default=0)

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

    name = models.CharField(max_length=120, unique=True, help_text="Common hobbyist name")
    species = models.CharField(max_length=150, blank=True, help_text="Scientific/taxonomic name")
    category = models.CharField(max_length=20, choices=CATEGORY_CHOICES, default='fish')
    suggested_group = models.CharField(max_length=60, default='Fish', help_text="Default group when added to tank")
    care_level = models.CharField(max_length=30, default='Beginner', help_text="Beginner, Moderate, or Expert")
    reef_safe = models.CharField(max_length=30, default='Yes', help_text="Yes, With Caution, or No")
    diet = models.CharField(max_length=150, blank=True, help_text="e.g. Herbivore, Omnivore, Carnivore")
    notes = models.TextField(blank=True, help_text="Care tips, temperament, and requirements")
    icon = models.CharField(max_length=10, default='🐠')

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


class Tank(DimensionedVessel):
    """Represents an aquarium system (e.g. Main Display, Frag Tank, Quarantine)."""
    name = models.CharField(max_length=100, default="Main Display Tank")
    is_primary = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ['-is_primary', 'name']

    def __str__(self):
        return f"{self.name} ({self.volume_gallons} gal)"

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


class PlumbingRun(models.Model):
    """A stretch of pipe holding system water (return line, drains, manifold...)."""
    LENGTH_UNITS = [('ft', 'Feet'), ('m', 'Meters')]
    DIAMETER_UNITS = [('in', 'Inches'), ('mm', 'Millimeters')]
    SIZE_CHOICES = PIPE_SIZE_CHOICES + [('custom', 'Custom inside diameter')]

    tank = models.ForeignKey(Tank, on_delete=models.CASCADE, related_name='plumbing_runs')
    name = models.CharField(max_length=80, blank=True, help_text="e.g. Return line, Main drain, Emergency drain")
    length = models.DecimalField(max_digits=7, decimal_places=1, help_text="Length of one pipe")
    length_unit = models.CharField(max_length=2, choices=LENGTH_UNITS, default='ft')
    pipe_size = models.CharField(max_length=6, choices=SIZE_CHOICES, default='1',
                                 help_text="Nominal Schedule 40 PVC size, or enter a custom inside diameter")
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
        size = PIPE_SIZES.get(self.pipe_size)
        return size[1] if size else None

    @property
    def size_label(self):
        if self.pipe_size == 'custom':
            if not self.custom_diameter:
                return "custom (no diameter)"
            return f"{self.custom_diameter.normalize():f} {self.custom_diameter_unit} ID"
        size = PIPE_SIZES.get(self.pipe_size)
        return f'{size[0]} PVC' if size else self.pipe_size

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

    class Meta:
        ordering = ['tank', 'name']

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
        """Estimated real flow (gph) at the current power setting, or None if no max flow is set."""
        return estimate_flow_gph(self.max_flow_gph, self.power_setting_percent, self.flow_derate_percent)

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
    def is_service_due(self):
        """True if the equipment needs its routine cleaning/service."""
        if self.status == 'offline':
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

    class Meta:
        ordering = ['reservoir_type', 'name']

    def __str__(self):
        return f"{self.name} ({self.current_level}/{self.capacity} {self.unit})"

    @property
    def percent_remaining(self):
        if not self.capacity or self.capacity <= 0:
            return 0
        pct = (float(self.current_level) / float(self.capacity)) * 100
        return max(0, min(100, round(pct)))

    @property
    def days_remaining(self):
        if not self.daily_consumption or self.daily_consumption <= 0:
            return None
        return max(0.0, round(float(self.current_level) / float(self.daily_consumption), 1))

    @property
    def estimated_empty_date(self):
        days = self.days_remaining
        if days is None:
            return None
        return timezone.localdate() + timedelta(days=int(days))

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

    @property
    def frequency_days(self):
        """Approximate interval in days (for sorting)."""
        return sched.period_days(self.repeat_every, self.repeat_unit)

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

    @property
    def runs_today(self):
        return self._occurs_on(timezone.localdate())

    @property
    def days_since_completed(self):
        if not self.last_completed:
            return None
        return (timezone.now() - self.last_completed).days


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
