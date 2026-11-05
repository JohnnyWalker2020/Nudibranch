from django.urls import path
from . import views

urlpatterns = [
    # Dashboard & Parameters
    path('', views.dashboard_view, name='dashboard'),
    path('parameters/', views.parameters_view, name='parameters'),
    path('parameters/<int:param_id>/settings/', views.parameter_settings_view, name='parameter_settings'),
    path('parameters/quick-add/', views.quick_log_create, name='quick_log_create'),
    path('parameters/delete/<int:log_id>/', views.delete_log, name='delete_log'),
    
    # REST API Endpoints
    path('api/parameters/chart-data/', views.api_chart_data, name='api_chart_data'),
    path('api/parameters/types/', views.api_parameter_types, name='api_parameter_types'),
    path('api/parameters/log/', views.api_parameter_log, name='api_parameter_log'),

    # Livestock GUI
    path('livestock/', views.livestock_view, name='livestock'),
    path('livestock/add/', views.animal_create_view, name='animal_create'),
    path('livestock/<int:animal_id>/edit/', views.animal_edit_view, name='animal_edit'),
    path('livestock/<int:animal_id>/delete/', views.animal_delete_view, name='animal_delete'),

    # Common Species Catalog
    path('species/', views.species_catalog_view, name='species_catalog'),
    path('species/<int:species_id>/add/', views.species_add_to_tank, name='species_add_to_tank'),
    path('api/species/', views.api_species_catalog, name='api_species_catalog'),

    # Dosing & ATO Reservoirs
    path('dosing/', views.dosing_view, name='dosing'),
    path('dosing/add/', views.dosing_create_view, name='dosing_create'),
    path('dosing/<int:res_id>/refill/', views.refill_reservoir_view, name='refill_reservoir'),

    # Equipment & Tanks
    path('equipment/', views.equipment_view, name='equipment'),
    path('equipment/add/', views.equipment_create_view, name='equipment_create'),
    path('equipment/<int:eq_id>/service/', views.service_equipment_view, name='service_equipment'),
    path('tanks/add/', views.tank_create_view, name='tank_create'),

    # Maintenance Routines & Water Changes
    path('routines/', views.routines_view, name='routines'),
    path('routines/<int:routine_id>/complete/', views.complete_routine_view, name='complete_routine'),
    path('routines/water-change/add/', views.water_change_log_create, name='water_change_log_create'),
    path('api/calculators/salt-mix/', views.water_change_calc_api, name='water_change_calc_api'),

    # Webcams
    path('webcams/', views.webcams_view, name='webcams'),
]
