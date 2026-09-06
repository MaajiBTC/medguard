from django.urls import path

from . import views

app_name = "alerts"

urlpatterns = [
    path("", views.AlertListView.as_view(), name="list"),
    path("unacknowledged-count/", views.UnacknowledgedAlertCountView.as_view(), name="unacknowledged-count"),
    path("<int:alert_id>/acknowledge/", views.AlertAcknowledgeView.as_view(), name="acknowledge"),
]
