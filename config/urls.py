"""
URL configuration for Betala Inventory project.
"""

from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from django.contrib.auth import views as auth_views
from django.views.generic import RedirectView
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView

urlpatterns = [
    path('admin/', admin.site.urls),
    
    # Authentication - bruk Betala login
    path('login/', RedirectView.as_view(pattern_name='betala_sync:betala_login', permanent=False), name='login'),
    path('logout/', auth_views.LogoutView.as_view(), name='logout'),
    
    # Main apps
    path('', include('inventory.urls', namespace='inventory')),
    path('rapporter/', include('reports.urls', namespace='reports')),
    path('betala/', include('betala_sync.urls', namespace='betala_sync')),
    
    # API
    path('api/schema/', SpectacularAPIView.as_view(), name='schema'),
    path('api/docs/', SpectacularSwaggerView.as_view(url_name='schema'), name='swagger-ui'),
    path('api/', include('inventory.api.urls', namespace='api')),
]

# Debug toolbar
if settings.DEBUG:
    import debug_toolbar
    urlpatterns = [
        path('__debug__/', include(debug_toolbar.urls)),
    ] + urlpatterns
    
    # Serve media files in development
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)
