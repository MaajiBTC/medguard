from django.db import models


class SecurityAlert(models.Model):
    """A security event that a human is expected to look at and sign off on
    (added 2026-09-06, per the user).

    CLAUDE.md's band table has always said that a sub-40% decision means
    "ACCESS_DENIED, security alert triggered" -- but until now a denial only
    ever wrote one Ledger row, which scrolled past in a feed with nothing
    recording that anybody had actually reviewed it. This model is that
    missing half: every alert starts unacknowledged, and a security officer
    has to acknowledge it (optionally with a note), which is what turns the
    audit trail into an actual governance loop.

    Deliberately NOT a sixth Ledger event type -- CLAUDE.md pins the Ledger
    to exactly five, and "somebody acknowledged an alert" isn't an
    access decision. This follows the same precedent as
    scoring.DisasterModeEvent, staff.AdminActionLog and
    access.PendingDeviceRequest: a small, purpose-built table on the default
    database rather than stretching the Ledger's spec. It is also not
    hash-chained -- it is a workflow record, not the security-critical
    access trail.

    Actor fields are denormalized (copied in, no ForeignKey) for the same
    reason ledger.LedgerEntry and staff.AdminActionLog denormalize theirs: a
    staff member who is later deleted must not take the evidence of what they
    did with them. `staff_id` is blank for a lockout alert against a username
    that doesn't match any real account -- which is itself worth recording.
    """

    class AlertType(models.TextChoices):
        ACCESS_DENIED = "ACCESS_DENIED", "Access denied"
        LOGIN_LOCKOUT = "LOGIN_LOCKOUT", "Login lockout"
        STEP_UP_FAILED = "STEP_UP_FAILED", "Step-up verification failed"

    alert_type = models.CharField(max_length=32, choices=AlertType.choices)

    staff_id = models.CharField(max_length=64, blank=True, default="")
    staff_full_name = models.CharField(max_length=255, blank=True, default="")
    staff_role = models.CharField(max_length=32, blank=True, default="")
    patient_hospital_number = models.CharField(max_length=64, blank=True, default="")

    details = models.JSONField(default=dict, blank=True)
    # The Ledger entry this alert was raised alongside, where there is one
    # (denials). Stored as a plain integer, not a ForeignKey -- LedgerEntry
    # lives on a separate database, so a real FK isn't possible anyway.
    ledger_sequence = models.IntegerField(null=True, blank=True)

    raised_at = models.DateTimeField(auto_now_add=True)
    acknowledged_at = models.DateTimeField(null=True, blank=True)
    acknowledged_by_staff_id = models.CharField(max_length=64, blank=True, default="")
    acknowledgement_note = models.TextField(blank=True, default="")

    class Meta:
        ordering = ["-raised_at"]

    @property
    def acknowledged(self):
        return self.acknowledged_at is not None

    def __str__(self):
        state = "acknowledged" if self.acknowledged else "OPEN"
        return f"SecurityAlert({self.alert_type}, {self.staff_id or 'unknown'}, {state})"
