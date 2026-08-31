from django.urls import path

from . import views

app_name = "staff"

urlpatterns = [
    path("", views.StaffSearchView.as_view(), name="search"),
    path("summary/", views.StaffSummaryView.as_view(), name="summary"),
    path("create/", views.StaffCreateView.as_view(), name="create"),
    path("<int:staff_id>/duty/", views.StaffDutyWardUpdateView.as_view(), name="duty-update"),
    path("<int:staff_id>/deactivate/", views.StaffDeactivateView.as_view(), name="deactivate"),
    path("<int:staff_id>/reactivate/", views.StaffReactivateView.as_view(), name="reactivate"),
    path("<int:staff_id>/delete/", views.StaffDeleteView.as_view(), name="delete"),
    path("admin-actions/", views.AdminActionListView.as_view(), name="admin-actions"),
]
