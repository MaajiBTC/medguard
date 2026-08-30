from django.conf import settings
from django.db import models


class Ward(models.TextChoices):
    """Fixed hospital ward taxonomy, shared by Staff.ward and Patient.ward (see
    patients/models.py) so the Nurse/Doctor "same ward" access rules in
    scoring/engine.py can rely on an exact match between the two fields instead of
    free text typed independently on each side."""

    GENERAL_MALE = "general_male", "General Male Ward"
    GENERAL_FEMALE = "general_female", "General Female Ward"
    SURGICAL = "surgical", "Surgical Ward"
    EMERGENCY = "emergency", "Emergency Ward"


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
        ADMIN = "admin", "Admin"
        SECURITY_OFFICER = "security_officer", "Security officer"

    # Roles with patient-record category access via the Scoring Engine (CLAUDE.md's
    # role -> category table). Admin/security officer are system roles, not clinical
    # ones -- they never call /api/scoring/decide/.
    CLINICAL_ROLES = {Role.DOCTOR, Role.NURSE, Role.PHARMACIST, Role.LAB_TECHNICIAN, Role.CLERK}

    # System roles (added 2026-08-30): shared accounts with no ward/on-duty/on-call
    # concept -- neither field is ever meaningfully checked for these roles (the
    # Doctor/Nurse rules that read ward/on_duty/on_call only apply to those two
    # roles), so staff/views.py forces them blank/false on create and rejects
    # attempts to set them via the duty/ward update endpoint.
    NO_WARD_DUTY_ROLES = {Role.ADMIN, Role.SECURITY_OFFICER}

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
        choices=Ward.choices,
        blank=True,
        help_text="Ward this staff member is generally assigned to (manually set).",
    )
    on_duty = models.BooleanField(
        default=False,
        help_text="Manually toggled on-duty status. Never computed by a scheduler.",
    )
    on_call = models.BooleanField(
        default=False,
        help_text=(
            "Manually toggled on-call status -- reachable/available even while off "
            "duty. Treated as equivalent to on_duty by the Doctor rule and BTG's "
            "availability gate (see scoring app, added 2026-08-29). Never computed."
        ),
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Staff member"
        verbose_name_plural = "Staff members"

    def __str__(self):
        return f"{self.full_name} ({self.staff_id}, {self.role})"
