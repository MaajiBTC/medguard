from django.db import models


class PatientNotification(models.Model):
    """One row per attempted patient-facing SMS (added 2026-09-14, the
    user's own idea -- the competition is "Safe Access to Patient Records",
    so the patient gets to know when their own record was accessed in any
    way CLAUDE.md's scoring bands already treat as noteworthy). Kept even
    when the send fails or Twilio isn't configured yet -- this IS the
    record of what was attempted, useful for demoing the feature honestly
    before real credentials exist, and a lightweight audit trail after.

    Real FK to Patient (unlike ledger.LedgerEntry's denormalized staff_id
    pattern) -- this app lives on the default database, not a separate one,
    so there's no reason not to.
    """

    patient = models.ForeignKey("patients.Patient", on_delete=models.CASCADE, related_name="notifications")
    event_type = models.CharField(max_length=32)
    phone_number = models.CharField(max_length=32, blank=True, default="")
    sent = models.BooleanField(default=False)
    twilio_sid = models.CharField(max_length=64, blank=True, default="")
    error_detail = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        outcome = "sent" if self.sent else "failed"
        return f"PatientNotification({self.patient}, {self.event_type}, {outcome})"
