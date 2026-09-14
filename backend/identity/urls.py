from django.urls import path

from . import views

app_name = "identity"

urlpatterns = [
    path("enroll/", views.EnrollFingerprintView.as_view(), name="enroll"),
    path("identify/", views.IdentifyFingerprintView.as_view(), name="identify"),
]
