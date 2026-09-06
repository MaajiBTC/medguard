"""The only sanctioned way to raise a SecurityAlert.

Single-writer module, matching this codebase's existing convention
(ledger.services.record_event, staff.services.record_admin_action) -- every
caller goes through raise_alert() so the denormalization rules live in exactly
one place.
"""

from .models import SecurityAlert


def raise_alert(*, alert_type, staff=None, patient=None, details=None, ledger_sequence=None):
    """Raises one unacknowledged alert.

    `staff` may be None -- a login lockout against a username that matches no
    real account still deserves an alert (arguably more so). `patient` is only
    relevant to record-access alerts.
    """
    return SecurityAlert.objects.create(
        alert_type=alert_type,
        staff_id=staff.staff_id if staff else "",
        staff_full_name=staff.full_name if staff else "",
        staff_role=staff.role if staff else "",
        patient_hospital_number=patient.hospital_number if patient else "",
        details=details or {},
        ledger_sequence=ledger_sequence,
    )
