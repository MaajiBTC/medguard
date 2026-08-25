from django.db import models


class LedgerImmutableError(Exception):
    """Raised on any attempt to modify or delete an existing LedgerEntry. The ledger is
    append-only (CLAUDE.md Security Ledger) -- this stops accidental/ORM-level tampering
    from the app itself. It is not the real security boundary: that's the separate
    `ledger` database/credentials this app is routed to (see db_router.py), which a
    compromised main application has no access to at all.
    """


class LedgerEntry(models.Model):
    """One row per logged security decision -- independent, hash-chained, append-only
    (CLAUDE.md Security Ledger). Lives on the separate `ledger` database (see
    db_router.py), so it cannot use ForeignKeys to staff/patients/access models
    (cross-database relations aren't supported by Django) -- every reference below is a
    plain denormalized value, snapshotted at write time. Only ever created via
    services.record_event(), never instantiated/saved directly.
    """

    class EventType(models.TextChoices):
        STANDARD_ACCESS = "STANDARD_ACCESS", "Standard access"
        AUDITED_DEVIATION = "AUDITED_DEVIATION", "Audited deviation"
        REDUCED_ACCESS = "REDUCED_ACCESS", "Reduced access"
        ACCESS_DENIED = "ACCESS_DENIED", "Access denied"
        EMERGENCY_OVERRIDE = "EMERGENCY_OVERRIDE", "Emergency override"

    sequence = models.AutoField(primary_key=True)
    occurred_at = models.DateTimeField()
    event_type = models.CharField(max_length=32, choices=EventType.choices)

    staff_id = models.CharField(max_length=64)
    staff_full_name = models.CharField(max_length=255, blank=True, default="")
    patient_hospital_number = models.CharField(max_length=64, blank=True, default="")
    session_token = models.CharField(max_length=64, blank=True, default="")
    device_id = models.CharField(max_length=255, blank=True, default="")

    details = models.JSONField(default=dict, blank=True)

    prev_hash = models.CharField(max_length=64)
    entry_hash = models.CharField(max_length=64, unique=True)

    class Meta:
        ordering = ["sequence"]

    def __str__(self):
        return f"LedgerEntry(#{self.sequence}, {self.event_type}, staff={self.staff_id})"

    def save(self, *args, **kwargs):
        if self.pk is not None and LedgerEntry.objects.filter(pk=self.pk).exists():
            raise LedgerImmutableError("Ledger entries are append-only and cannot be modified.")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise LedgerImmutableError("Ledger entries are append-only and cannot be deleted.")
