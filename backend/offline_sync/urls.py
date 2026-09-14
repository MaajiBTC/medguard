from django.urls import path

from . import views

app_name = "offline_sync"

urlpatterns = [
    path("sync/", views.OfflineSyncView.as_view(), name="sync"),
]
