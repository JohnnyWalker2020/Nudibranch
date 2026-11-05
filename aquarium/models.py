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
    display_order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ['display_order', 'name']

    def __str__(self):
        return f"{self.name} ({self.unit})"

    def latest_log(self):
        return self.logs.order_by('-measured_at').first()


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
