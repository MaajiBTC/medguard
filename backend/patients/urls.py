from django.urls import path

from . import views

app_name = "patients"

urlpatterns = [
    path("", views.PatientSearchView.as_view(), name="search"),
    path("summary/", views.PatientSummaryView.as_view(), name="summary"),
    path("assigned-to-me/", views.MyAssignedPatientsView.as_view(), name="assigned-to-me"),
    path("create/", views.PatientCreateView.as_view(), name="create"),
    path("<int:patient_id>/ward/", views.PatientWardUpdateView.as_view(), name="ward-update"),
    path("<int:patient_id>/records/all/", views.PatientCategoryRecordsView.as_view(), name="records-all"),
    path(
        "<int:patient_id>/records/<int:category>/",
        views.PatientCategoryUpdateView.as_view(),
        name="category-update",
    ),
    path(
        "<int:patient_id>/assignments/",
        views.PatientAssignmentListCreateView.as_view(),
        name="assignments",
    ),
    path(
        "<int:patient_id>/assignments/<int:assignment_id>/",
        views.PatientAssignmentDeactivateView.as_view(),
        name="assignment-deactivate",
    ),
]
