"""
URL configuration for config project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/6.1/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path('admin/', admin.site.urls),
    path('api/access/', include('access.urls')),
    path('api/captures/', include('captures.urls')),
    path('api/scoring/', include('scoring.urls')),
    path('api/staff/', include('staff.urls')),
    path('api/patients/', include('patients.urls')),
    path('api/ledger/', include('ledger.urls')),
    path('api/alerts/', include('alerts.urls')),
    path('api/offline/', include('offline_sync.urls')),
    path('api/identity/', include('identity.urls')),
]

# Uploaded staff photos (see config/settings.py's MEDIA_URL/MEDIA_ROOT) --
# dev-only serving; production would need a real static/media server.
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
