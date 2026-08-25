from django.conf import settings
from django.db import models


class Staff(models.Model):
    """A hospital staff member. One row per person, linked to their login (auth.User).

    Populated only with real, user-supplied data (see CLAUDE.md "Enrollment data") —
    never generated or placeholder rows. `role` sets the access ceiling; `ward` and
    `on_duty` are manually maintained facts (no shift-scheduling computation, per the
    project's explicit exclusions) that the Contextual capture module snapshots at
    login time.
    """

    class Role(models.TextChoices):
        DOCTOR = "doctor", "Doctor"
        NURSE = "nurse", "Nurse"
        PHARMACIST = "pharmacist", "Pharmacist"
        LAB_TECHNICIAN = "lab_technician", "Lab technician"
        CLERK = "clerk", "Clerk"

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="staff_profile",
        help_text="Django auth user this staff member logs in as (reuses Django's built-in password hashing).",
    )
    staff_id = models.CharField(max_length=64, unique=True)
    full_name = models.CharField(max_length=255)
    role = models.CharField(max_length=32, choices=Role.choices)
    ward = models.CharField(
        max_length=128,
        blank=True,
        help_text="Ward this staff member is generally assigned to (free text, manually set).",
    )
    on_duty = models.BooleanField(
        default=False,
        help_text="Manually toggled on-duty status. Never computed by a scheduler.",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Staff member"
        verbose_name_plural = "Staff members"

    def __str__(self):
        return f"{self.full_name} ({self.staff_id}, {self.role})"
