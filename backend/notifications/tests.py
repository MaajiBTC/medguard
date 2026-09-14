"""Patient SMS notification tests (added 2026-09-14, the user's own idea).
requests.post is always mocked here so the suite never makes a real network
call -- same convention already used for ledger.gemini.explain_entry's
tests. No real enrollment data -- Django's isolated test database only, per
CLAUDE.md.
"""

from unittest.mock import Mock, patch

from django.contrib.auth.models import User
from django.test import TestCase, override_settings

from ledger.models import LedgerEntry
from patients.models import Patient, PatientCategoryRecord
from staff.models import Staff

from .models import PatientNotification
from .services import notify_patient

TWILIO_SETTINGS = dict(
    TWILIO_ACCOUNT_SID="ACtest", TWILIO_AUTH_TOKEN="test-token", TWILIO_FROM_NUMBER="+10000000000",
)


class NotifyPatientTests(TestCase):
    def _make_staff(self):
        user = User.objects.create_user(username="notifyDoc", password="pw-notify-1")
        return Staff.objects.create(user=user, staff_id="STF-N1", full_name="Notify Doctor", role=Staff.Role.DOCTOR)

    def _make_patient_with_phone(self, phone="+15551234567"):
        patient = Patient.objects.create(hospital_number="HN-N1", full_name="Notify Patient")
        for category, _ in PatientCategoryRecord.Category.choices:
            PatientCategoryRecord.objects.create(patient=patient, category=category)
        PatientCategoryRecord.objects.filter(patient=patient, category=1).update(content={"phone": phone})
        return patient

    @override_settings(**TWILIO_SETTINGS)
    def test_successful_send_is_recorded(self):
        staff = self._make_staff()
        patient = self._make_patient_with_phone()

        mock_response = Mock(status_code=201, text="")
        mock_response.json.return_value = {"sid": "SMtest123"}
        with patch("notifications.services.requests.post", return_value=mock_response) as mocked:
            result = notify_patient(patient=patient, event_type=LedgerEntry.EventType.REDUCED_ACCESS, staff=staff)

        mocked.assert_called_once()
        self.assertTrue(result.sent)
        self.assertEqual(result.twilio_sid, "SMtest123")
        self.assertEqual(result.phone_number, "+15551234567")
        self.assertEqual(PatientNotification.objects.count(), 1)

        # Message content: no category *content* leaked, just who/what kind.
        sent_body = mocked.call_args.kwargs["data"]["Body"]
        self.assertIn("Notify Doctor", sent_body)
        self.assertIn("Reduced access", sent_body)

    @override_settings(TWILIO_ACCOUNT_SID=None, TWILIO_AUTH_TOKEN=None, TWILIO_FROM_NUMBER=None)
    def test_missing_config_records_failure_without_raising(self):
        staff = self._make_staff()
        patient = self._make_patient_with_phone()

        result = notify_patient(patient=patient, event_type=LedgerEntry.EventType.ACCESS_DENIED, staff=staff)

        self.assertFalse(result.sent)
        self.assertIn("not configured", result.error_detail)

    @override_settings(**TWILIO_SETTINGS)
    def test_missing_phone_number_records_failure_without_raising(self):
        staff = self._make_staff()
        patient = Patient.objects.create(hospital_number="HN-N2", full_name="No Phone Patient")
        for category, _ in PatientCategoryRecord.Category.choices:
            PatientCategoryRecord.objects.create(patient=patient, category=category)

        with patch("notifications.services.requests.post") as mocked:
            result = notify_patient(patient=patient, event_type=LedgerEntry.EventType.AUDITED_DEVIATION, staff=staff)

        mocked.assert_not_called()
        self.assertFalse(result.sent)
        self.assertIn("No phone number", result.error_detail)

    @override_settings(**TWILIO_SETTINGS)
    def test_twilio_error_response_records_failure_without_raising(self):
        staff = self._make_staff()
        patient = self._make_patient_with_phone()

        mock_response = Mock(status_code=400, text="Invalid phone number")
        with patch("notifications.services.requests.post", return_value=mock_response):
            result = notify_patient(patient=patient, event_type=LedgerEntry.EventType.EMERGENCY_OVERRIDE, staff=staff)

        self.assertFalse(result.sent)
        self.assertIn("400", result.error_detail)

    @override_settings(**TWILIO_SETTINGS)
    def test_network_error_records_failure_without_raising(self):
        import requests

        staff = self._make_staff()
        patient = self._make_patient_with_phone()

        with patch("notifications.services.requests.post", side_effect=requests.ConnectionError("boom")):
            result = notify_patient(patient=patient, event_type=LedgerEntry.EventType.ACCESS_DENIED, staff=staff)

        self.assertFalse(result.sent)
        self.assertIn("Could not reach Twilio", result.error_detail)
