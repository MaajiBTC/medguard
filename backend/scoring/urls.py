from django.urls import path

from . import views

app_name = "scoring"

urlpatterns = [
    path("decide/", views.DecideView.as_view(), name="decide"),
    path("patients/<int:patient_id>/records/", views.PatientRecordView.as_view(), name="patient-records"),
]
