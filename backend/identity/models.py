from django.db import models


class FingerprintTemplate(models.Model):
    """MedGuard Identity (CLAUDE.md bonus, step 7) -- one enrolled fingerprint
    template per patient. `OneToOneField` -- re-enrolling replaces whatever
    was there, same pattern `access.WebAuthnCredential` already uses for
    "re-enrolling replaces" rather than accumulating rows.

    `encrypted_template` is a Fernet-encrypted JSON blob of extracted
    minutiae points (`identity.crypto`/`identity.extraction`) -- never the
    raw uploaded image, which is processed in memory (a deleted temp file)
    and discarded, per CLAUDE.md: "Store encrypted templates (AES), never
    raw images." Two genuine scans of the same finger are never pixel- or
    even minutiae-identical, so this stores the derived template, not a
    hash of the image.
    """

    patient = models.OneToOneField(
        "patients.Patient", on_delete=models.CASCADE, related_name="fingerprint_template"
    )
    encrypted_template = models.TextField()
    enrolled_at = models.DateTimeField(auto_now=True)
    enrolled_by_staff_id = models.CharField(max_length=64, blank=True, default="")

    def __str__(self):
        return f"FingerprintTemplate({self.patient})"
