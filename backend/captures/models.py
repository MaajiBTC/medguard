from django.db import models

from access.models import AccessSession
from patients.models import Patient


class ContextualCapture(models.Model):
    """One row per session — simple factual lookups only, no scoring (CLAUDE.md).

    `on_duty_at_login` / `ward_assignment_at_login` are snapshots taken at login
    time, not live reads of the mutable Staff row — this protects historical
    accuracy (a later change to Staff.on_duty must not rewrite what happened during
    a past session) and sets the precedent step 3's Ledger will also want.

    Login timestamp, device, and network are intentionally NOT duplicated here — the
    serializer reads them off the related AccessSession.
    """

    class PatientAssignmentStatus(models.TextChoices):
        NOT_APPLICABLE = "not_applicable", "Not applicable (role has no assignment concept)"
        NO_PATIENT_SELECTED = "no_patient_selected", "No patient selected yet"
        ASSIGNED = "assigned", "Specifically assigned to this patient"
        SAME_WARD_NOT_ASSIGNED = "same_ward_not_assigned", "Same ward, not specifically assigned"
        NOT_ASSIGNED_NOT_SAME_WARD = "not_assigned_not_same_ward", "Neither assigned nor same ward"

    session = models.OneToOneField(
        AccessSession, on_delete=models.CASCADE, related_name="contextual_capture"
    )

    on_duty_at_login = models.BooleanField()
    on_call_at_login = models.BooleanField(
        default=False,
        help_text="Snapshot of staff.on_call at login time (added 2026-08-29) -- same historical-accuracy reasoning as on_duty_at_login above.",
    )
    ward_assignment_at_login = models.CharField(max_length=128, blank=True)

    target_patient = models.ForeignKey(
        Patient,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="contextual_captures",
    )
    patient_assignment_status = models.CharField(
        max_length=32,
        choices=PatientAssignmentStatus.choices,
        default=PatientAssignmentStatus.NO_PATIENT_SELECTED,
    )
    patient_assignment_checked_at = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return f"ContextualCapture(session={self.session_id}, status={self.patient_assignment_status})"


class BehavioralCapture(models.Model):
    """One row per session — no matching/scoring (CLAUDE.md explicitly excludes that
    from this module).

    `keystroke_features` holds `{"login": {...} | None, "session_windows": [...]}` —
    derived, anonymized timing features only (flight/digraph/trigraph latency,
    error/correction rate, rhythm consistency, automation flags), never raw key
    identity (see CLAUDE.md's Behavioral Signal Capture Module section, revised
    2026-08-25). `mouse_events`/`touch_events` stay raw, timestamped, append-only
    arrays — an empty list is the correct value for a signal family that doesn't
    apply to this device (e.g. touch_events stays [] on a desktop with a mouse).
    """

    session = models.OneToOneField(
        AccessSession, on_delete=models.CASCADE, related_name="behavioral_capture"
    )

    keystroke_features = models.JSONField(default=dict, blank=True)
    mouse_events = models.JSONField(default=list, blank=True)
    touch_events = models.JSONField(default=list, blank=True)

    mouse_event_count = models.PositiveIntegerField(default=0)
    touch_event_count = models.PositiveIntegerField(default=0)

    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        session_windows = len(self.keystroke_features.get("session_windows", []))
        return (
            f"BehavioralCapture(session={self.session_id}, "
            f"keystroke_windows={session_windows}, mouse={self.mouse_event_count}, "
            f"touch={self.touch_event_count})"
        )
