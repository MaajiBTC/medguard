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
    photo = models.ImageField(
        upload_to="staff_photos/",
        blank=True,
        null=True,
        help_text=(
            "Self-uploaded profile photo (added 2026-09-05, per the user). Local disk "
            "storage -- fine for local dev/a single demo session, but Render's free "
            "tier disk is ephemeral, so this won't survive a backend redeploy there "
            "without swapping in real object storage later."
        ),
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Staff member"
        verbose_name_plural = "Staff members"

    def __str__(self):
        return f"{self.full_name} ({self.staff_id}, {self.role})"


class AdminActionLog(models.Model):
    """Audit trail of admin actions on staff accounts (added 2026-08-31, per
    the user) -- scoped to staff account lifecycle only (create/deactivate/
    reactivate/delete). Nothing before this model shipped is recoverable;
    this only starts logging from here on.

    Actor/target are denormalized (staff_id/full_name/role copied in, no
    ForeignKey) rather than referencing Staff directly -- same reasoning
    ledger.LedgerEntry already established: a target row can be deleted
    (that's literally one of the four actions logged here) without losing
    the audit record, and an actor shouldn't be able to erase evidence of
    their own action by later being deleted themselves. Lives on the default
    database (unlike the Ledger, this doesn't need cross-database isolation
    -- it's a staff-management record, not the security-critical access
    trail) and is a plain model rather than hash-chained/append-only --
    matches scoring.DisasterModeEvent's precedent (a small, purpose-built
    audit table, lighter-weight than the Ledger, registered read-only in
    admin) for this narrower scope.
    """

    class Action(models.TextChoices):
        STAFF_CREATED = "staff_created", "Created"
        STAFF_DEACTIVATED = "staff_deactivated", "Deactivated"
        STAFF_REACTIVATED = "staff_reactivated", "Reactivated"
        STAFF_DELETED = "staff_deleted", "Deleted"
        # Added 2026-09-06 alongside login lockout -- clearing someone's lock
        # early is an admin acting on a staff account, so it belongs in the
        # same lifecycle trail as the four above.
        STAFF_UNLOCKED = "staff_unlocked", "Unlocked"
        # Added 2026-09-06, retired the same day when step-up moved to device
        # biometrics + peer-assist (self-service enrollment, no admin action
        # left to log). Left defined rather than migrated away -- no real PIN
        # was ever set, so there's no historical data at stake either way.
        STEP_UP_PIN_SET = "step_up_pin_set", "Step-up PIN set (retired)"

    actor_staff_id = models.CharField(max_length=64)
    actor_full_name = models.CharField(max_length=255)
    action = models.CharField(max_length=32, choices=Action.choices)
    target_staff_id = models.CharField(max_length=64)
    target_full_name = models.CharField(max_length=255)
    target_role = models.CharField(max_length=32, blank=True, default="")
    occurred_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-occurred_at"]

    def __str__(self):
        return f"AdminActionLog({self.actor_staff_id} {self.action} {self.target_staff_id})"
