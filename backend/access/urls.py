from django.urls import path

from . import views

app_name = "access"

urlpatterns = [
    path("login/", views.LoginView.as_view(), name="login"),
    path("logout/", views.LogoutView.as_view(), name="logout"),
    path("change-password/", views.ChangePasswordView.as_view(), name="change-password"),
    path("session/current/", views.CurrentSessionView.as_view(), name="session-current"),
    path("devices/", views.DeviceListView.as_view(), name="device-list"),
    path("devices/pending-count/", views.DevicePendingCountView.as_view(), name="device-pending-count"),
    path("devices/<int:device_pk>/remove/", views.DeviceRemoveView.as_view(), name="device-remove"),
    path(
        "device-requests/<str:poll_token>/poll/",
        views.DeviceRequestPollView.as_view(),
        name="device-request-poll",
    ),
    path(
        "device-requests/<int:request_id>/approve/",
        views.DeviceApproveView.as_view(),
        name="device-request-approve",
    ),
    path(
        "device-requests/<int:request_id>/reject/",
        views.DeviceRejectView.as_view(),
        name="device-request-reject",
    ),
]
