from django.contrib import admin
from django.urls import path, include, re_path
from django.conf import settings
from django.conf.urls.static import static
from django.views.static import serve

from aquarium import views as aquarium_views

urlpatterns = [
    path('admin/', admin.site.urls),
    # Service worker must live at the site root to control every page (a file under /static/ only controls /static/).
    path('sw.js', aquarium_views.service_worker_view, name='service_worker'),
    path('', include('aquarium.urls')),
]

# Serve media files in development
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
else:
    # Also support serving uploaded media in simple single-container setup
    urlpatterns += [
        re_path(r'^media/(?P<path>.*)$', serve, {'document_root': settings.MEDIA_ROOT}),
    ]
