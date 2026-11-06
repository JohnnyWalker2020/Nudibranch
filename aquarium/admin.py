from django.contrib import admin
from django.utils.html import format_html
from .models import (
    ParameterType, ParameterLog, AnimalGroup, Animal, WebcamFeed, SpeciesCatalog,
    Tank, Sump, SumpChamber, Equipment, DosingReservoir, MaintenanceRoutine, PlumbingRun,
    WaterChangeLog, DashboardWidget, AlertRecord, AppSettings, QuarantineEntry, AnimalPhoto, TimelapseFrame, WebhookEndpoint,
    WebhookDelivery, ROSystem, FillTimer, PlannedSystem, PlannedItem, WishlistItem, CostEntry, ParameterTarget, PlanProject,
)

for _model in (AlertRecord, AppSettings, QuarantineEntry, AnimalPhoto, TimelapseFrame, WebhookEndpoint, WebhookDelivery,
               ROSystem, FillTimer, PlannedSystem, PlannedItem, WishlistItem, CostEntry, ParameterTarget, PlanProject):
    admin.site.register(_model)


@admin.register(ParameterType)
class ParameterTypeAdmin(admin.ModelAdmin):
    list_display = ('name', 'code', 'unit', 'decimal_places', 'low_limit', 'min_ideal', 'max_ideal', 'high_limit', 'color_badge', 'display_order')
    list_editable = ('decimal_places', 'display_order')
    search_fields = ('name', 'code')

    def color_badge(self, obj):
        return format_html(
            '<span style="display:inline-block; width:18px; height:18px; border-radius:4px; background-color:{}; vertical-align:middle; margin-right:6px;"></span>{}',
            obj.color, obj.color
        )
    color_badge.short_description = "Color"


@admin.register(ParameterLog)
class ParameterLogAdmin(admin.ModelAdmin):
    list_display = ('parameter_type', 'formatted_value_display', 'unit', 'status_badge', 'measured_at', 'notes')
    list_filter = ('parameter_type', 'measured_at')
    date_hierarchy = 'measured_at'
    search_fields = ('notes', 'parameter_type__name')

    def formatted_value_display(self, obj):
        return obj.formatted_value
    formatted_value_display.short_description = "Value"

    def unit(self, obj):
        return obj.parameter_type.unit

    def status_badge(self, obj):
        colors = {'ok': '#10b981', 'warning': '#f59e0b', 'critical': '#ef4444'}
        color = colors.get(obj.severity, '#64748b')
        return format_html(
            '<span style="background:{}; color:#fff; padding:2px 8px; border-radius:12px; font-weight:600; font-size:11px;">{}</span>',
            color, obj.status_label
        )
    status_badge.short_description = "Range Status"


@admin.register(AnimalGroup)
class AnimalGroupAdmin(admin.ModelAdmin):
    list_display = ('name', 'icon', 'color_badge', 'animal_count')
    search_fields = ('name',)

    def color_badge(self, obj):
        return format_html(
            '<span style="background:{}; color:#fff; padding:2px 8px; border-radius:6px; font-weight:500;">{}</span>',
            obj.color, obj.color
        )

    def animal_count(self, obj):
        return obj.animals.count()
    animal_count.short_description = "Animals in Group"


@admin.register(Animal)
class AnimalAdmin(admin.ModelAdmin):
    list_display = ('name', 'species', 'tank', 'count', 'get_groups', 'status', 'acquired_date')
    list_filter = ('tank', 'status', 'groups', 'acquired_date')
    search_fields = ('name', 'species', 'notes')
    filter_horizontal = ('groups',)

    def get_groups(self, obj):
        return ", ".join([g.name for g in obj.groups.all()]) or "—"
    get_groups.short_description = "Groups"


@admin.register(WebcamFeed)
class WebcamFeedAdmin(admin.ModelAdmin):
    list_display = ('name', 'feed_type', 'is_active', 'order', 'feed_url')
    list_editable = ('is_active', 'order')
    list_filter = ('feed_type', 'is_active')


@admin.register(SpeciesCatalog)
class SpeciesCatalogAdmin(admin.ModelAdmin):
    list_display = ('icon_name', 'species', 'category', 'suggested_group', 'care_level', 'reef_safe', 'diet')
    list_filter = ('category', 'care_level', 'reef_safe')
    search_fields = ('name', 'species', 'notes', 'diet')

    def icon_name(self, obj):
        return f"{obj.icon} {obj.name}"
    icon_name.short_description = "Species"


class SumpInline(admin.TabularInline):
    model = Sump
    extra = 0


class PlumbingRunInline(admin.TabularInline):
    model = PlumbingRun
    extra = 0


@admin.register(Tank)
class TankAdmin(admin.ModelAdmin):
    list_display = ('name', 'volume_gallons', 'capacity_is_manual', 'is_primary', 'created_at')
    list_filter = ('is_primary', 'capacity_is_manual')
    search_fields = ('name', 'notes')
    inlines = [SumpInline, PlumbingRunInline]


class SumpChamberInline(admin.TabularInline):
    model = SumpChamber
    extra = 0


@admin.register(Sump)
class SumpAdmin(admin.ModelAdmin):
    list_display = ('name', 'tank', 'volume_gallons', 'capacity_is_manual')
    list_filter = ('tank',)
    inlines = [SumpChamberInline]


@admin.register(Equipment)
class EquipmentAdmin(admin.ModelAdmin):
    list_display = ('name', 'tank', 'category', 'brand', 'wattage', 'max_flow_gph', 'power_setting_percent',
                    'status', 'last_serviced_date', 'is_service_due')
    list_filter = ('category', 'status', 'tank')
    search_fields = ('name', 'brand', 'notes')


@admin.register(DosingReservoir)
class DosingReservoirAdmin(admin.ModelAdmin):
    list_display = ('name', 'tank', 'reservoir_type', 'current_level', 'capacity', 'unit', 'daily_consumption',
                    'percent_remaining', 'days_remaining', 'is_low')
    list_filter = ('reservoir_type', 'tank')
    search_fields = ('name', 'tank__name')


@admin.register(MaintenanceRoutine)
class MaintenanceRoutineAdmin(admin.ModelAdmin):
    list_display = ('title', 'routine_type', 'tank', 'category', 'recurrence_label', 'is_active', 'last_completed', 'is_due')
    list_filter = ('routine_type', 'repeat_unit', 'category', 'is_active', 'tank')
    filter_horizontal = ('equipment',)
    search_fields = ('title', 'notes')


@admin.register(WaterChangeLog)
class WaterChangeLogAdmin(admin.ModelAdmin):
    list_display = ('tank', 'performed_at', 'gallons', 'salt_brand', 'target_salinity')
    list_filter = ('salt_brand', 'tank', 'performed_at')
    date_hierarchy = 'performed_at'
    search_fields = ('notes', 'salt_brand')


@admin.register(DashboardWidget)
class DashboardWidgetAdmin(admin.ModelAdmin):
    list_display = ('key', 'enabled', 'position')
    list_editable = ('enabled', 'position')
