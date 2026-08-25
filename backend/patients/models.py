from django.db import models


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
        blank=True,
        help_text="Ward the patient currently occupies (free text).",
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
