from django.db import models
from django.utils import timezone


class ParameterType(models.Model):
    """Represents a measured water metric (e.g. Salinity, Alkalinity, Calcium)."""
    name = models.CharField(max_length=60, unique=True)
    code = models.SlugField(max_length=30, unique=True, help_text="Short identifier e.g. alk, sal, ca")
    unit = models.CharField(max_length=20, help_text="e.g. dKH, SG, ppm, °F, pH")
    min_ideal = models.DecimalField(max_digits=7, decimal_places=3, help_text="Lower bound of target range")
    max_ideal = models.DecimalField(max_digits=7, decimal_places=3, help_text="Upper bound of target range")
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
    def step_size(self):
        """Returns input step attribute for HTML numeric fields."""
        if self.decimal_places == 0:
            return "1"
        return f"0.{'0' * (self.decimal_places - 1)}1"


class ParameterLog(models.Model):
    """Historical test measurement."""
    parameter_type = models.ForeignKey(ParameterType, on_delete=models.CASCADE, related_name="logs")
    measured_at = models.DateTimeField(default=timezone.now)
    value = models.DecimalField(max_digits=8, decimal_places=3)
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
        """Returns whether the reading is optimal, low, or high."""
        if self.value < self.parameter_type.min_ideal:
            return "low"
        elif self.value > self.parameter_type.max_ideal:
            return "high"
        return "optimal"

    @property
    def status_color_class(self):
        if self.status == "optimal":
            return "text-emerald-400 bg-emerald-500/10 border-emerald-500/30"
        elif self.status == "low":
            return "text-amber-400 bg-amber-500/10 border-amber-500/30"
        else:
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
        """Returns direct Wikipedia article URL for scientific species name or search URL for common name."""
        import urllib.parse
        if self.species:
            clean_species = self.species.strip().replace(' ', '_')
            return f"https://en.wikipedia.org/wiki/{urllib.parse.quote(clean_species)}"
        clean_name = self.name.split('(')[0].strip()
        return f"https://en.wikipedia.org/wiki/Special:Search?search={urllib.parse.quote(clean_name)}"

    @property
    def reef2reef_search_url(self):
        """Returns Reef2Reef community search URL for real hobbyist discussions, care, and tips."""
        import urllib.parse
        search_term = self.species if self.species else self.name.split('(')[0].strip()
        return f"https://www.reef2reef.com/search/1/?q={urllib.parse.quote(search_term)}&o=relevance"

    @property
    def reef2reef_disease_url(self):
        """Returns Reef2Reef fish disease and diagnosis subforum search."""
        import urllib.parse
        search_term = self.name.split('(')[0].strip()
        return f"https://www.reef2reef.com/search/1/?q={urllib.parse.quote(search_term)}&c[nodes][]=77&o=relevance"


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
        """Returns direct Wikipedia article URL for scientific species name or search URL for common name."""
        import urllib.parse
        if self.species:
            clean_species = self.species.strip().replace(' ', '_')
            return f"https://en.wikipedia.org/wiki/{urllib.parse.quote(clean_species)}"
        clean_name = self.name.split('(')[0].strip()
        return f"https://en.wikipedia.org/wiki/Special:Search?search={urllib.parse.quote(clean_name)}"

    @property
    def reef2reef_search_url(self):
        """Returns Reef2Reef community search URL for real hobbyist discussions, care, and tips."""
        import urllib.parse
        search_term = self.species if self.species else self.name.split('(')[0].strip()
        return f"https://www.reef2reef.com/search/1/?q={urllib.parse.quote(search_term)}&o=relevance"


class Tank(models.Model):
    """Represents an aquarium system (e.g. Main Display, Frag Tank, Quarantine)."""
    name = models.CharField(max_length=100, default="Main Display Tank")
    volume_gallons = models.DecimalField(max_digits=6, decimal_places=1, default=50.0, help_text="Total system water volume (gal)")
    is_primary = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ['-is_primary', 'name']

    def __str__(self):
        return f"{self.name} ({self.volume_gallons} gal)"


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
        ('filtration', '🧽 Filtration & Media Reactor'),
        ('monitoring', '📊 Monitor / Controller (Apex, ReefBot)'),
        ('other', '⚙️ Other Equipment'),
    ]

    STATUS_CHOICES = [
        ('operational', 'Operational / Running'),
        ('maintenance_due', 'Maintenance / Service Due'),
        ('offline', 'Offline / Standby'),
    ]

    tank = models.ForeignKey(Tank, on_delete=models.SET_NULL, null=True, blank=True, related_name='equipment')
    name = models.CharField(max_length=120, help_text="e.g. Radion XR30 Pro, Vectra M2 Return Pump")
    category = models.CharField(max_length=30, choices=CATEGORY_CHOICES, default='other')
    brand = models.CharField(max_length=100, blank=True, help_text="Manufacturer or brand")
    wattage = models.PositiveIntegerField(null=True, blank=True, help_text="Power consumption (Watts)")
    installed_date = models.DateField(null=True, blank=True)
    maintenance_interval_days = models.PositiveIntegerField(default=90, help_text="Days between service cleanings (e.g. 90)")
    last_serviced_date = models.DateField(null=True, blank=True, help_text="Last date cleaned or calibrated")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='operational')
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ['category', 'name']
        verbose_name_plural = 'Equipment'

    def __str__(self):
        tank_str = f" [{self.tank.name}]" if self.tank else ""
        return f"{self.name}{tank_str}"

    @property
    def is_service_due(self):
        """Returns True if equipment needs routine vinegar bath/cleaning."""
        if self.status == 'maintenance_due':
            return True
        if not self.last_serviced_date:
            return False
        from datetime import date, timedelta
        due_date = self.last_serviced_date + timedelta(days=self.maintenance_interval_days)
        return date.today() >= due_date

    @property
    def days_until_service(self):
        if not self.last_serviced_date:
            return None
        from datetime import date, timedelta
        due_date = self.last_serviced_date + timedelta(days=self.maintenance_interval_days)
        return (due_date - date.today()).days


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
    last_refilled_date = models.DateField(default=timezone.now)

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
        from datetime import date, timedelta
        return date.today() + timedelta(days=int(days))

    @property
    def is_low(self):
        """Flagged if under 20% or less than 3 days of liquid remain."""
        if self.percent_remaining <= 20:
            return True
        if self.days_remaining is not None and self.days_remaining <= 3:
            return True
        return False


class MaintenanceRoutine(models.Model):
    """Recurring tank checklists and maintenance routines (Water changes, testing, pump cleanings)."""
    CATEGORY_CHOICES = [
        ('water_change', '🌊 Water Change'),
        ('testing', '🧪 Water Testing'),
        ('equipment', '⚙️ Equipment Maintenance'),
        ('general', '📋 General Care'),
    ]

    tank = models.ForeignKey(Tank, on_delete=models.CASCADE, null=True, blank=True, related_name='routines')
    title = models.CharField(max_length=120, help_text="e.g. Weekly Water Change & Sump Siphon")
    category = models.CharField(max_length=20, choices=CATEGORY_CHOICES, default='general')
    frequency_days = models.PositiveIntegerField(default=7, help_text="How often to repeat in days (e.g. 7 for weekly)")
    checklist_items = models.JSONField(default=list, help_text="List of task strings")
    last_completed = models.DateTimeField(null=True, blank=True)
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ['frequency_days', 'title']

    def __str__(self):
        return f"{self.title} (Every {self.frequency_days}d)"

    @property
    def is_due(self):
        if not self.last_completed:
            return True
        from datetime import timedelta
        return timezone.now() >= self.last_completed + timedelta(days=self.frequency_days)

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
