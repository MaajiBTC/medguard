from django.urls import path

from . import views

app_name = "scoring"

urlpatterns = [
    path("decide/", views.DecideView.as_view(), name="decide"),
    path("emergency-override/", views.EmergencyOverrideView.as_view(), name="emergency-override"),
    path(
        "decisions/<int:decision_id>/step-up/webauthn/options/",
        views.StepUpWebAuthnOptionsView.as_view(),
        name="step-up-webauthn-options",
    ),
    path(
        "decisions/<int:decision_id>/step-up/webauthn/verify/",
        views.StepUpWebAuthnVerifyView.as_view(),
        name="step-up-webauthn-verify",
    ),
    path(
        "decisions/<int:decision_id>/step-up/assist/request/",
        views.StepUpAssistRequestView.as_view(),
        name="step-up-assist-request",
    ),
    path("step-up/assist-requests/", views.StepUpAssistListView.as_view(), name="step-up-assist-list"),
    path(
        "step-up/assist-requests/<int:request_id>/approve/",
        views.StepUpAssistApproveView.as_view(),
        name="step-up-assist-approve",
    ),
    path(
        "step-up/assist-requests/<int:request_id>/decline/",
        views.StepUpAssistDeclineView.as_view(),
        name="step-up-assist-decline",
    ),
    path("patients/<int:patient_id>/records/", views.PatientRecordView.as_view(), name="patient-records"),
    path("disaster-mode/", views.DisasterModeView.as_view(), name="disaster-mode"),
    path("disaster-mode/activate/", views.DisasterModeActivateView.as_view(), name="disaster-mode-activate"),
    path("disaster-mode/deactivate/", views.DisasterModeDeactivateView.as_view(), name="disaster-mode-deactivate"),
]
