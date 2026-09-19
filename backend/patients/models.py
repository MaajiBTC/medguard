from django.db import models

from staff.models import Ward


class PatientStatus(models.TextChoices):
    """Manually-set current-state label (added 2026-09-19, per the user) --
    same "never computed, admin sets it directly" convention as Staff.on_duty/
    on_call/ward (see CLAUDE.md's explicit-exclusions section). Deliberately
    NOT an appointment-scheduling feature -- CLAUDE.md excludes booking/
    scheduling outright -- this is a plain current-state field an admin
    edits on the Patient panel's detail card, same interaction as ward."""

    ADMITTED = "admitted", "Admitted"
    DISCHARGED = "discharged", "Discharged"
    OUTPATIENT = "outpatient", "Outpatient"


class Patient(models.Model):
    """Deliberately minimal patient record for step 1.

    This is NOT the full 13-category record from CLAUDE.md — that lands in step 4's
    main UI. Here it only exists so the Contextual capture module has something real
    to look up assignment/ward facts against. Populated only with real, user-supplied
    data — never generated or placeholder rows (see CLAUDE.md "Enrollment data").
    """

    hospital_number = models.CharField(max_length=64, unique=True)
    full_name = models.CharField(max_length=255)
    ward = models.CharField(
        max_length=128,
        choices=Ward.choices,
        blank=True,
        help_text="Ward the patient currently occupies.",
    )
    status = models.CharField(
        max_length=32,
        choices=PatientStatus.choices,
        blank=True,
        help_text="Current-state label (Admitted/Discharged/Outpatient). Blank means not yet set.",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.full_name} ({self.hospital_number})"


class PatientAssignment(models.Model):
    """Records that a specific staff member (doctor or nurse) is specifically
    assigned to a specific patient — distinct from general ward assignment.

    This is the source of fact for the Contextual module's patient-assignment-status
    lookup, and later for the Nurse rule's "specifically assigned" path (CLAUDE.md).

    Assignment history is preserved: rows are soft-deactivated via `active`, never
    deleted. Multiple simultaneous active assignments per (patient, role) are allowed
    (shift coverage) — only an exact-duplicate active row (same patient, same staff,
    same role_in_assignment) is blocked.
    """

    class RoleInAssignment(models.TextChoices):
        DOCTOR = "doctor", "Doctor"
        NURSE = "nurse", "Nurse"

    patient = models.ForeignKey(Patient, on_delete=models.CASCADE, related_name="assignments")
    staff = models.ForeignKey(
        "staff.Staff", on_delete=models.CASCADE, related_name="patient_assignments"
    )
    role_in_assignment = models.CharField(
        max_length=16,
        choices=RoleInAssignment.choices,
        help_text="Denormalized at assignment time so it stays stable if staff.role later changes.",
    )
    assigned_at = models.DateTimeField(auto_now_add=True)
    active = models.BooleanField(
        default=True,
        help_text="Soft-deactivate to end an assignment; never delete, so history survives.",
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["patient", "staff", "role_in_assignment"],
                condition=models.Q(active=True),
                name="unique_active_patient_staff_role_assignment",
            )
        ]

    def __str__(self):
        status = "active" if self.active else "inactive"
        return f"{self.staff} -> {self.patient} ({self.role_in_assignment}, {status})"


class PatientCategoryRecord(models.Model):
    """One row per (patient, category) -- the actual content behind CLAUDE.md's 13
    patient record categories. `content` is a plain JSONField (no migration needed
    per category), but what's *allowed inside it* is validated against per-category
    structured field definitions (see category_fields.py's CATEGORY_FIELDS) rather
    than one free-text notes field -- reversed 2026-09-03, per the user, from this
    model's original "deliberately generic, not 13 bespoke schemas" design (see
    CLAUDE.md's dated amendment for the reasoning). Category *access control*
    (which role/score band unlocks which categories) is still the real point of
    this project, not the content schema -- this only changes what's stored once a
    category is unlocked, not who unlocks it.

    All 13 rows are created empty alongside a new Patient (see patients.views
    PatientCreateView) -- empty structure, not fabricated content, same as this
    codebase's other "starts empty, filled by real data later" patterns.
    """

    class Category(models.IntegerChoices):
        IDENTITY = 1, "Identity"
        ADMINISTRATIVE_BILLING = 2, "Administrative/Billing"
        VITAL_SIGNS = 3, "Vital Signs & Routine Observations"
        DIAGNOSIS_HISTORY = 4, "Diagnosis & Medical History"
        MEDICATION_PRESCRIPTIONS = 5, "Medication & Prescriptions"
        ALLERGIES = 6, "Allergies"
        GENERAL_LAB_RESULTS = 7, "General Lab Results"
        HIGHLY_SENSITIVE_TESTS = 8, "Highly Sensitive Test Results"
        MENTAL_HEALTH = 9, "Mental Health Records"
        REPRODUCTIVE_HEALTH = 10, "Reproductive Health Records"
        SURGICAL_PROCEDURE_HISTORY = 11, "Surgical/Procedure History"
        NURSING_CARE_NOTES = 12, "Nursing & Care Notes"
        IMAGING_RADIOLOGY = 13, "Imaging/Radiology"

    patient = models.ForeignKey(Patient, on_delete=models.CASCADE, related_name="category_records")
    category = models.PositiveSmallIntegerField(choices=Category.choices)
    content = models.JSONField(default=dict, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["patient", "category"], name="unique_patient_category")
        ]
        ordering = ["category"]

    def __str__(self):
        return f"{self.patient} / category {self.category} ({self.get_category_display()})"
