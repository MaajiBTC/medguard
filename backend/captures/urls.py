from django.urls import path

from . import views

app_name = "captures"

urlpatterns = [
    path("behavioral/events/", views.BehavioralEventsView.as_view(), name="behavioral-events"),
    path("behavioral/", views.BehavioralCaptureDetailView.as_view(), name="behavioral-detail"),
    path(
        "contextual/target-patient/",
        views.TargetPatientView.as_view(),
        name="contextual-target-patient",
    ),
    path("contextual/", views.ContextualCaptureDetailView.as_view(), name="contextual-detail"),
]
