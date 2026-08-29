from django.urls import path

from . import views

app_name = "scoring"

urlpatterns = [
    path("decide/", views.DecideView.as_view(), name="decide"),
    path("emergency-override/", views.EmergencyOverrideView.as_view(), name="emergency-override"),
    path("patients/<int:patient_id>/records/", views.PatientRecordView.as_view(), name="patient-records"),
    path("disaster-mode/", views.DisasterModeView.as_view(), name="disaster-mode"),
    path("disaster-mode/activate/", views.DisasterModeActivateView.as_view(), name="disaster-mode-activate"),
    path("disaster-mode/deactivate/", views.DisasterModeDeactivateView.as_view(), name="disaster-mode-deactivate"),
]
