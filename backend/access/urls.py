from django.urls import path

from . import views

app_name = "access"

urlpatterns = [
    path("login/", views.LoginView.as_view(), name="login"),
    path("logout/", views.LogoutView.as_view(), name="logout"),
    path("change-password/", views.ChangePasswordView.as_view(), name="change-password"),
    path("profile/photo/", views.ProfilePhotoView.as_view(), name="profile-photo"),
    path("session/current/", views.CurrentSessionView.as_view(), name="session-current"),
    path(
        "webauthn/registration-options/",
        views.WebAuthnRegistrationOptionsView.as_view(),
        name="webauthn-registration-options",
    ),
    path("webauthn/register/", views.WebAuthnRegisterView.as_view(), name="webauthn-register"),
    path("devices/", views.DeviceListView.as_view(), name="device-list"),
    path("devices/pending-count/", views.DevicePendingCountView.as_view(), name="device-pending-count"),
    path("devices/<int:device_pk>/remove/", views.DeviceRemoveView.as_view(), name="device-remove"),
    path(
        "devices/register-signing-key/",
        views.RegisterSyncKeyView.as_view(),
        name="device-register-signing-key",
    ),
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
