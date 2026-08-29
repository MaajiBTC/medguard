"""Factual lookups shared across apps. compute_patient_assignment_status() is the one
sanctioned way to determine a staff member's relationship to a patient (assigned /
same-ward / neither / not-applicable) -- both captures.views.TargetPatientView (to
record it on a session's ContextualCapture) and scoring.views.EmergencyOverrideView
(to gate Break the Glass, freshly, without depending on a prior capture step) call
this rather than duplicating the lookup.
"""

from patients.models import PatientAssignment
from staff.models import Staff

from .models import ContextualCapture


def compute_patient_assignment_status(staff, patient):
    if staff.role not in (Staff.Role.DOCTOR, Staff.Role.NURSE):
        return ContextualCapture.PatientAssignmentStatus.NOT_APPLICABLE

    is_assigned = PatientAssignment.objects.filter(
        patient=patient, staff=staff, active=True
    ).exists()
    if is_assigned:
        return ContextualCapture.PatientAssignmentStatus.ASSIGNED

    same_ward = (
        bool(staff.ward)
        and bool(patient.ward)
        and staff.ward.strip().lower() == patient.ward.strip().lower()
    )
    if same_ward:
        return ContextualCapture.PatientAssignmentStatus.SAME_WARD_NOT_ASSIGNED

    return ContextualCapture.PatientAssignmentStatus.NOT_ASSIGNED_NOT_SAME_WARD
