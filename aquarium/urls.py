from django.urls import path
from . import views

urlpatterns = [
    # Dashboard & Parameters
    path('', views.dashboard_view, name='dashboard'),
    path('dashboard/customize/', views.dashboard_customize_view, name='dashboard_customize'),
    path('parameters/', views.parameters_view, name='parameters'),
    path('parameters/new/', views.parameter_type_create_view, name='parameter_type_create'),
    path('parameters/<int:param_id>/settings/', views.parameter_settings_view, name='parameter_settings'),
    path('parameters/<int:param_id>/delete/', views.parameter_type_delete_view, name='parameter_type_delete'),
    path('parameters/quick-add/', views.quick_log_create, name='quick_log_create'),
    path('parameters/quick-measure/', views.quick_measure_create, name='quick_measure_create'),
    path('parameters/delete/<int:log_id>/', views.delete_log, name='delete_log'),
    path('parameters/log/<int:log_id>/edit/', views.log_edit_view, name='log_edit'),

    # REST API Endpoints
    path('api/parameters/chart-data/', views.api_chart_data, name='api_chart_data'),
    path('api/parameters/chart-data/all/', views.api_all_chart_data, name='api_all_chart_data'),
    path('api/parameters/types/', views.api_parameter_types, name='api_parameter_types'),
    path('api/parameters/log/', views.api_parameter_log, name='api_parameter_log'),

    # Livestock GUI
    path('livestock/', views.livestock_view, name='livestock'),
    path('livestock/add/', views.animal_create_view, name='animal_create'),
    path('livestock/groups/add/', views.group_create_view, name='group_create'),
    path('livestock/groups/<int:group_id>/edit/', views.group_edit_view, name='group_edit'),
    path('livestock/groups/<int:group_id>/delete/', views.group_delete_view, name='group_delete'),
    path('livestock/<int:animal_id>/edit/', views.animal_edit_view, name='animal_edit'),
    path('livestock/<int:animal_id>/photo/', views.animal_upload_photo_view, name='animal_upload_photo'),
    path('livestock/<int:animal_id>/delete/', views.animal_delete_view, name='animal_delete'),

    # Common Species Catalog
    path('species/', views.species_catalog_view, name='species_catalog'),
    path('species/<int:species_id>/add/', views.species_add_to_tank, name='species_add_to_tank'),
    path('api/species/', views.api_species_catalog, name='api_species_catalog'),

    # Dosing & ATO Reservoirs
    path('dosing/', views.dosing_view, name='dosing'),
    path('dosing/add/', views.dosing_create_view, name='dosing_create'),
    path('dosing/<int:res_id>/edit/', views.dosing_edit_view, name='dosing_edit'),
    path('dosing/<int:res_id>/delete/', views.dosing_delete_view, name='dosing_delete'),
    path('dosing/<int:res_id>/refill/', views.refill_reservoir_view, name='refill_reservoir'),
    path('api/calculators/dosing/', views.dose_calc_api, name='dose_calc_api'),

    # Tanks, sumps & chambers
    path('tanks/', views.tanks_view, name='tanks'),
    path('tanks/add/', views.tank_create_view, name='tank_create'),
    path('tanks/<int:tank_id>/', views.tank_detail_view, name='tank_detail'),
    path('tanks/<int:tank_id>/edit/', views.tank_edit_view, name='tank_edit'),
    path('tanks/<int:tank_id>/delete/', views.tank_delete_view, name='tank_delete'),
    path('tanks/<int:tank_id>/sumps/add/', views.sump_create_view, name='sump_create'),
    path('sumps/<int:sump_id>/edit/', views.sump_edit_view, name='sump_edit'),
    path('sumps/<int:sump_id>/delete/', views.sump_delete_view, name='sump_delete'),
    path('sumps/<int:sump_id>/chambers/split/', views.sump_split_view, name='sump_split'),
    path('chambers/<int:chamber_id>/edit/', views.chamber_edit_view, name='chamber_edit'),
    path('chambers/<int:chamber_id>/delete/', views.chamber_delete_view, name='chamber_delete'),

    # Equipment
    path('equipment/', views.equipment_view, name='equipment'),
    path('equipment/add/', views.equipment_create_view, name='equipment_create'),
    path('equipment/<int:eq_id>/edit/', views.equipment_edit_view, name='equipment_edit'),
    path('equipment/<int:eq_id>/delete/', views.equipment_delete_view, name='equipment_delete'),
    path('equipment/<int:eq_id>/service/', views.service_equipment_view, name='service_equipment'),
    path('equipment/<int:eq_id>/power/', views.equipment_power_view, name='equipment_power'),

    # Maintenance Routines & Water Changes
    path('routines/', views.routines_view, name='routines'),
    path('routines/add/', views.routine_create_view, name='routine_create'),
    path('routines/<int:routine_id>/edit/', views.routine_edit_view, name='routine_edit'),
    path('routines/<int:routine_id>/complete/', views.complete_routine_view, name='complete_routine'),
    path('routines/<int:routine_id>/delete/', views.routine_delete_view, name='routine_delete'),
    path('routines/water-change/add/', views.water_change_log_create, name='water_change_log_create'),
    path('routines/water-change/<int:wc_id>/edit/', views.water_change_edit_view, name='water_change_edit'),
    path('routines/water-change/<int:wc_id>/delete/', views.water_change_delete_view, name='water_change_delete'),
    path('api/calculators/salt-mix/', views.water_change_calc_api, name='water_change_calc_api'),

    # Webcams
    path('webcams/', views.webcams_view, name='webcams'),
    path('webcams/add/', views.webcam_create_view, name='webcam_create'),
    path('webcams/<int:cam_id>/edit/', views.webcam_edit_view, name='webcam_edit'),
    path('webcams/<int:cam_id>/delete/', views.webcam_delete_view, name='webcam_delete'),

    # Notifications & Alerts Center
    path('notifications/', views.notifications_view, name='notifications'),
]
