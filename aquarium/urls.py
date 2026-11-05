from django.urls import path
from . import views

urlpatterns = [
    path('', views.dashboard_view, name='dashboard'),
    path('parameters/', views.parameters_view, name='parameters'),
    path('parameters/quick-add/', views.quick_log_create, name='quick_log_create'),
    path('parameters/delete/<int:log_id>/', views.delete_log, name='delete_log'),
    path('api/parameters/chart-data/', views.api_chart_data, name='api_chart_data'),
    path('livestock/', views.livestock_view, name='livestock'),
    path('webcams/', views.webcams_view, name='webcams'),
]
