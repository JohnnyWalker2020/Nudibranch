from django.urls import path
from . import views, views_tools as tools

urlpatterns = [
    # Dashboard & Parameters
    path('', views.dashboard_view, name='dashboard'),
    path('dashboard/customize/', views.dashboard_customize_view, name='dashboard_customize'),
    path('parameters/', views.parameters_view, name='parameters'),
    path('parameters/new/', views.parameter_type_create_view, name='parameter_type_create'),
    path('parameters/<int:param_id>/settings/', views.parameter_settings_view, name='parameter_settings'),
    path('parameters/<int:param_id>/delete/', views.parameter_type_delete_view, name='parameter_type_delete'),
    path('parameters/<int:param_id>/settings/reset-targets/', views.parameter_targets_reset_view, name='parameter_targets_reset'),
    path('parameters/quick-add/', views.quick_log_create, name='quick_log_create'),
    path('parameters/logs/', views.parameter_logs_more, name='parameter_logs_more'),
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
    path('tanks/<int:tank_id>/move/', views.tank_move_view, name='tank_move'),
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
    path('tanks/<int:tank_id>/plumbing/add/', views.plumbing_create_view, name='plumbing_create'),
    path('plumbing/<int:run_id>/edit/', views.plumbing_edit_view, name='plumbing_edit'),
    path('plumbing/<int:run_id>/delete/', views.plumbing_delete_view, name='plumbing_delete'),
    path('routines/', views.routines_view, name='routines'),
    path('routines/add/', views.routine_create_view, name='routine_create'),
    path('routines/<int:routine_id>/edit/', views.routine_edit_view, name='routine_edit'),
    path('routines/<int:routine_id>/complete/', views.complete_routine_view, name='complete_routine'),
    path('routines/<int:routine_id>/delete/', views.routine_delete_view, name='routine_delete'),
    path('routines/<int:routine_id>/toggle/', views.routine_toggle_view, name='routine_toggle'),
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
    path('notifications/mute/', views.notifications_mute_view, name='notifications_mute'),

    # System selector, look and the hidden ledger
    path('system/select/', tools.system_select_view, name='system_select'),
    path('tanks/<int:tank_id>/archive/', tools.tank_archive_view, name='tank_archive'),
    path('tanks/<int:tank_id>/restore/', tools.tank_restore_view, name='tank_restore'),
    path('system/look/', tools.system_theme_view, name='system_theme'),
    path('tanks/<int:tank_id>/look/', tools.tank_look_view, name='tank_look'),
    path('the-damage/', tools.the_damage_view, name='the_damage'),
    path('the-damage/switch/', tools.damage_switch_view, name='damage_switch'),
    path('the-damage/currency/', tools.damage_currency_view, name='damage_currency'),
    path('the-damage/<int:entry_id>/edit/', tools.cost_edit_view, name='cost_edit'),
    path('the-damage/<int:entry_id>/delete/', tools.cost_delete_view, name='cost_delete'),

    # Tools hub
    path('tools/', tools.tools_view, name='tools'),
    path('tools/settings/', tools.app_settings_view, name='app_settings'),
    path('tools/power/', tools.power_view, name='power'),

    # System planner
    path('planner/', tools.planner_list_view, name='planner'),
    path('planner/new/', tools.plan_create_view, name='plan_create'),
    path('planner/projects/new/', tools.project_create_view, name='project_create'),
    path('planner/projects/<int:project_id>/', tools.project_detail_view, name='project_detail'),
    path('planner/projects/<int:project_id>/edit/', tools.project_edit_view, name='project_edit'),
    path('planner/projects/<int:project_id>/delete/', tools.project_delete_view, name='project_delete'),
    path('planner/projects/<int:project_id>/add-plans/', tools.project_add_plans_view, name='project_add_plans'),
    path('planner/projects/<int:project_id>/remove/<int:plan_id>/', tools.project_remove_plan_view, name='project_remove_plan'),
    path('planner/<int:plan_id>/', tools.plan_detail_view, name='plan_detail'),
    path('planner/<int:plan_id>/duplicate/', tools.plan_duplicate_view, name='plan_duplicate'),
    path('planner/<int:plan_id>/edit/', tools.plan_edit_view, name='plan_edit'),
    path('planner/<int:plan_id>/delete/', tools.plan_delete_view, name='plan_delete'),
    path('planner/<int:plan_id>/add-livestock/', tools.plan_add_livestock_view, name='plan_add_livestock'),
    path('planner/<int:plan_id>/add-equipment/', tools.plan_add_equipment_view, name='plan_add_equipment'),
    path('planner/<int:plan_id>/track/', tools.plan_track_view, name='plan_track'),
    path('planner/items/<int:item_id>/delete/', tools.plan_item_delete_view, name='plan_item_delete'),

    # Wishlist
    path('planner/wishlist/', tools.wishlist_view, name='wishlist'),
    path('planner/wishlist/add-livestock/', tools.wishlist_add_livestock_view, name='wishlist_add_livestock'),
    path('planner/wishlist/add-equipment/', tools.wishlist_add_equipment_view, name='wishlist_add_equipment'),
    path('planner/wishlist/species/<int:species_id>/', tools.wishlist_add_species_view, name='wishlist_add_species'),
    path('planner/wishlist/<int:item_id>/edit/', tools.wishlist_edit_view, name='wishlist_edit'),
    path('planner/wishlist/<int:item_id>/delete/', tools.wishlist_delete_view, name='wishlist_delete'),
    path('planner/wishlist/<int:item_id>/to-plan/', tools.wishlist_to_plan_view, name='wishlist_to_plan'),
    path('planner/wishlist/<int:item_id>/bought/', tools.wishlist_bought_view, name='wishlist_bought'),

    # Quarantine
    path('quarantine/', tools.quarantine_list_view, name='quarantine_list'),
    path('quarantine/<int:animal_id>/', tools.quarantine_detail_view, name='quarantine_detail'),
    path('quarantine/<int:animal_id>/start/', tools.quarantine_start_view, name='quarantine_start'),
    path('quarantine/<int:animal_id>/plan/', tools.quarantine_plan_view, name='quarantine_plan'),
    path('quarantine/<int:animal_id>/finish/', tools.quarantine_finish_view, name='quarantine_finish'),
    path('quarantine/<int:animal_id>/log/', tools.quarantine_entry_add_view, name='quarantine_entry_add'),
    path('quarantine/log/<int:entry_id>/delete/', tools.quarantine_entry_delete_view, name='quarantine_entry_delete'),

    # Growth timeline & time-lapse
    path('livestock/<int:animal_id>/timeline/', tools.timeline_view, name='timeline'),
    path('livestock/timeline/<int:photo_id>/delete/', tools.timeline_photo_delete_view, name='timeline_photo_delete'),
    path('webcams/<int:cam_id>/timelapse/', tools.timelapse_view, name='timelapse'),
    path('webcams/<int:cam_id>/timelapse/capture/', tools.timelapse_capture_view, name='timelapse_capture'),
    path('webcams/<int:cam_id>/timelapse/clear/', tools.timelapse_clear_view, name='timelapse_clear'),

    # Webhooks & phone alerts
    path('integrations/', tools.integrations_view, name='integrations'),
    path('integrations/webhooks/add/', tools.webhook_create_view, name='webhook_create'),
    path('integrations/webhooks/<int:endpoint_id>/edit/', tools.webhook_edit_view, name='webhook_edit'),
    path('integrations/webhooks/<int:endpoint_id>/delete/', tools.webhook_delete_view, name='webhook_delete'),
    path('integrations/webhooks/<int:endpoint_id>/test/', tools.webhook_test_view, name='webhook_test'),

    # Backups
    path('backups/', tools.backups_view, name='backups'),
    path('backups/create/', tools.backup_create_view, name='backup_create'),
    path('backups/restore/', tools.backup_restore_view, name='backup_restore'),
    path('backups/<str:name>/download/', tools.backup_download_view, name='backup_download'),
    path('backups/<str:name>/delete/', tools.backup_delete_view, name='backup_delete'),

    # Fill timers & RO systems
    path('timers/', tools.timers_view, name='timers'),
    path('timers/start/', tools.timer_start_view, name='timer_start'),
    path('timers/<int:timer_id>/cancel/', tools.timer_cancel_view, name='timer_cancel'),
    path('timers/<int:timer_id>/extend/', tools.timer_extend_view, name='timer_extend'),
    path('timers/<int:timer_id>/dismiss/', tools.timer_dismiss_view, name='timer_dismiss'),
    path('timers/ro/add/', tools.ro_create_view, name='ro_create'),
    path('timers/ro/<int:ro_id>/edit/', tools.ro_edit_view, name='ro_edit'),
    path('timers/ro/<int:ro_id>/delete/', tools.ro_delete_view, name='ro_delete'),
    path('api/calculators/fill/', tools.fill_calc_api, name='fill_calc_api'),
]
