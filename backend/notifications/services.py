"""Patient-facing SMS notifications via Twilio (added 2026-09-14, the
user's own idea). Single writer, matching this codebase's established
convention (ledger.services.record_event, alerts.services.raise_alert):
notify_patient() is the only sanctioned way to create a PatientNotification.

Deliberately never raises -- unlike ledger.gemini.explain_entry (a
user-initiated action that's fine to fail loudly with a 502), this runs as
a background side effect of an access decision (DecideView,
EmergencyOverrideView, OfflineSyncView) and must never break that decision
just because Twilio is unreachable, unconfigured, or the patient has no
phone number on file. Every outcome -- success or any kind of failure --
still gets a PatientNotification row, so the attempt itself is never lost.
"""

import requests
from django.conf import settings

from ledger.models import LedgerEntry
from patients.models import PatientCategoryRecord

from .models import PatientNotification

TWILIO_TIMEOUT_SECONDS = 8


def _patient_phone(patient):
    record = PatientCategoryRecord.objects.filter(patient=patient, category=1).first()
    if not record:
        return ""
    return (record.content or {}).get("phone", "").strip()


def _build_message(event_type, staff):
    event_label = LedgerEntry.EventType(event_type).label if event_type in LedgerEntry.EventType.values else event_type
    return (
        f"MedGuard alert: your medical record was accessed by {staff.full_name} "
        f"({staff.get_role_display()}) -- flagged as \"{event_label}\". "
        "If this seems unexpected, please contact the hospital."
    )


def notify_patient(*, patient, event_type, staff):
    """Looks up the patient's own phone number (category 1's structured
    "phone" field -- no new patient field needed) and sends them a minimal,
    privacy-conscious SMS -- never any category *content*, just that an
    access happened, by whom, and what kind. Always returns the created
    PatientNotification row; never raises."""
    phone_number = _patient_phone(patient)
    if not phone_number:
        return PatientNotification.objects.create(
            patient=patient, event_type=event_type, sent=False,
            error_detail="No phone number on file for this patient (category 1).",
        )

    account_sid = settings.TWILIO_ACCOUNT_SID
    auth_token = settings.TWILIO_AUTH_TOKEN
    from_number = settings.TWILIO_FROM_NUMBER
    if not (account_sid and auth_token and from_number):
        return PatientNotification.objects.create(
            patient=patient, event_type=event_type, phone_number=phone_number, sent=False,
            error_detail="Twilio is not configured (TWILIO_ACCOUNT_SID/AUTH_TOKEN/FROM_NUMBER unset).",
        )

    url = f"https://api.twilio.com/2010-04-01/Accounts/{account_sid}/Messages.json"
    body = {"To": phone_number, "From": from_number, "Body": _build_message(event_type, staff)}

    try:
        response = requests.post(url, data=body, auth=(account_sid, auth_token), timeout=TWILIO_TIMEOUT_SECONDS)
    except requests.RequestException as exc:
        return PatientNotification.objects.create(
            patient=patient, event_type=event_type, phone_number=phone_number, sent=False,
            error_detail=f"Could not reach Twilio: {exc}",
        )

    if response.status_code not in (200, 201):
        return PatientNotification.objects.create(
            patient=patient, event_type=event_type, phone_number=phone_number, sent=False,
            error_detail=f"Twilio request failed ({response.status_code}): {response.text[:300]}",
        )

    twilio_sid = ""
    try:
        twilio_sid = response.json().get("sid", "")
    except ValueError:
        pass

    return PatientNotification.objects.create(
        patient=patient, event_type=event_type, phone_number=phone_number, sent=True, twilio_sid=twilio_sid,
    )
