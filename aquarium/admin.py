from django.contrib import admin
from django.utils.html import format_html
from .models import ParameterType, ParameterLog, AnimalGroup, Animal, WebcamFeed


@admin.register(ParameterType)
class ParameterTypeAdmin(admin.ModelAdmin):
    list_display = ('name', 'code', 'unit', 'min_ideal', 'max_ideal', 'color_badge', 'display_order')
    list_editable = ('display_order',)
    search_fields = ('name', 'code')

    def color_badge(self, obj):
        return format_html(
            '<span style="display:inline-block; width:18px; height:18px; border-radius:4px; background-color:{}; vertical-align:middle; margin-right:6px;"></span>{}',
            obj.color, obj.color
        )
    color_badge.short_description = "Color"


@admin.register(ParameterLog)
class ParameterLogAdmin(admin.ModelAdmin):
    list_display = ('parameter_type', 'value', 'unit', 'status_badge', 'measured_at', 'notes')
    list_filter = ('parameter_type', 'measured_at')
    date_hierarchy = 'measured_at'
    search_fields = ('notes', 'parameter_type__name')

    def unit(self, obj):
        return obj.parameter_type.unit

    def status_badge(self, obj):
        colors = {
            'optimal': '#10b981',
            'low': '#f59e0b',
            'high': '#ef4444'
        }
        color = colors.get(obj.status, '#64748b')
        return format_html(
            '<span style="background:{}; color:#fff; padding:2px 8px; border-radius:12px; font-weight:600; font-size:11px;">{}</span>',
            color, obj.status.upper()
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
    list_display = ('name', 'species', 'count', 'get_groups', 'status', 'acquired_date')
    list_filter = ('status', 'groups', 'acquired_date')
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
