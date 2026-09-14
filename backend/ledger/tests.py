"""Security Ledger tests. Uses Django's isolated multi-db test setup (both `default`
and `ledger` get their own temporary test databases) -- no real enrollment data, per
CLAUDE.md.
"""

import datetime
from unittest.mock import patch

from django.contrib.auth.models import User
from django.db import connections
from django.test import TestCase
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

from access.models import AccessSession
from captures.models import BehavioralCapture, ContextualCapture
from patients.models import Patient
from staff.models import Staff

from .gemini import GeminiError
from .models import LedgerEntry, LedgerImmutableError
from .services import GENESIS_HASH, record_event
from .verification import verify_chain


class RecordEventChainTests(TestCase):
    databases = {"default", "ledger"}

    def _make_staff(self):
        user = User.objects.create_user(username="ledgerStaff", password="pw-ledger-1")
        return Staff.objects.create(
            user=user, staff_id="STF-L1", full_name="Ledger Tester", role=Staff.Role.DOCTOR,
            ward="Ward A", on_duty=True,
        )

    def test_first_entry_chains_from_genesis(self):
        staff = self._make_staff()
        entry = record_event(event_type=LedgerEntry.EventType.STANDARD_ACCESS, staff=staff)
        self.assertEqual(entry.prev_hash, GENESIS_HASH)
        self.assertEqual(entry.sequence, 1)

    def test_staff_role_is_denormalized_onto_the_entry(self):
        """Added 2026-08-30, for the Security Dashboard's staff-role breakdown
        chart -- same denormalization reasoning as staff_full_name, not part
        of the hash payload."""
        staff = self._make_staff()
        entry = record_event(event_type=LedgerEntry.EventType.STANDARD_ACCESS, staff=staff)
        self.assertEqual(entry.staff_role, Staff.Role.DOCTOR)

    def test_successive_entries_link_by_hash(self):
        staff = self._make_staff()
        first = record_event(event_type=LedgerEntry.EventType.STANDARD_ACCESS, staff=staff)
        second = record_event(event_type=LedgerEntry.EventType.AUDITED_DEVIATION, staff=staff)
        third = record_event(event_type=LedgerEntry.EventType.ACCESS_DENIED, staff=staff)

        self.assertEqual(second.prev_hash, first.entry_hash)
        self.assertEqual(third.prev_hash, second.entry_hash)
        ok, bad_sequence = verify_chain()
        self.assertTrue(ok)
        self.assertIsNone(bad_sequence)

    def test_explicit_non_utc_occurred_at_still_verifies(self):
        """Regression test for a real bug (found 2026-09-14 via Offline Mode
        live testing): a caller passing an explicit, non-UTC-offset but
        timezone-AWARE `occurred_at` (e.g. DRF's DateTimeField, which
        converts an incoming timestamp to Django's configured local
        timezone -- settings.TIME_ZONE is 'Africa/Lagos', +01:00) used to
        get hashed using that local-offset ISO string, but the SAME field
        read back from the database later always comes back in UTC --
        two different valid string representations of the same instant,
        so the stored entry_hash would never re-verify. record_event() now
        normalizes occurred_at to UTC once, before it's used for both the
        hash and the saved row, so this can't happen regardless of what
        timezone the caller's datetime happens to carry."""
        staff = self._make_staff()
        lagos_offset = timezone.get_fixed_timezone(60)  # +01:00, matching settings.TIME_ZONE
        occurred_at = timezone.now().astimezone(lagos_offset)

        entry = record_event(
            event_type=LedgerEntry.EventType.REDUCED_ACCESS, staff=staff, occurred_at=occurred_at
        )

        ok, bad_sequence = verify_chain()
        self.assertTrue(ok)
        self.assertIsNone(bad_sequence)
        # The saved value is the same instant, just re-expressed in UTC.
        self.assertEqual(entry.occurred_at, occurred_at)
        self.assertEqual(entry.occurred_at.utcoffset(), datetime.timedelta(0))

    def test_tampering_via_raw_update_is_detected(self):
        staff = self._make_staff()
        record_event(event_type=LedgerEntry.EventType.STANDARD_ACCESS, staff=staff)
        entry = record_event(event_type=LedgerEntry.EventType.AUDITED_DEVIATION, staff=staff)
        record_event(event_type=LedgerEntry.EventType.ACCESS_DENIED, staff=staff)

        # Raw SQL bypasses the ORM entirely (LedgerQuerySet.update() and .save() both
        # raise LedgerImmutableError -- see models.py) -- this simulates the actual
        # threat model verify_chain() defends against: someone with direct database
        # access, not application code.
        with connections["ledger"].cursor() as cursor:
            cursor.execute(
                "UPDATE ledger_ledgerentry SET details = %s WHERE sequence = %s",
                ['{"tampered": true}', entry.sequence],
            )

        ok, bad_sequence = verify_chain()
        self.assertFalse(ok)
        self.assertEqual(bad_sequence, entry.sequence)


class ImmutabilityTests(TestCase):
    databases = {"default", "ledger"}

    def test_saving_an_existing_entry_raises(self):
        user = User.objects.create_user(username="ledgerStaff2", password="pw-ledger-2")
        staff = Staff.objects.create(
            user=user, staff_id="STF-L2", full_name="Ledger Tester 2", role=Staff.Role.DOCTOR,
            ward="Ward A", on_duty=True,
        )
        entry = record_event(event_type=LedgerEntry.EventType.STANDARD_ACCESS, staff=staff)

        entry.details = {"changed": True}
        with self.assertRaises(LedgerImmutableError):
            entry.save()

    def test_deleting_an_entry_raises(self):
        user = User.objects.create_user(username="ledgerStaff3", password="pw-ledger-3")
        staff = Staff.objects.create(
            user=user, staff_id="STF-L3", full_name="Ledger Tester 3", role=Staff.Role.DOCTOR,
            ward="Ward A", on_duty=True,
        )
        entry = record_event(event_type=LedgerEntry.EventType.STANDARD_ACCESS, staff=staff)

        with self.assertRaises(LedgerImmutableError):
            entry.delete()

    def test_bulk_queryset_update_raises(self):
        """Regression test: QuerySet.update() bypasses instance save() entirely (it's
        a direct SQL UPDATE), so without LedgerQuerySet this would silently succeed."""
        user = User.objects.create_user(username="ledgerStaff4", password="pw-ledger-4")
        staff = Staff.objects.create(
            user=user, staff_id="STF-L4", full_name="Ledger Tester 4", role=Staff.Role.DOCTOR,
            ward="Ward A", on_duty=True,
        )
        record_event(event_type=LedgerEntry.EventType.STANDARD_ACCESS, staff=staff)

        with self.assertRaises(LedgerImmutableError):
            LedgerEntry.objects.using("ledger").filter(staff_id="STF-L4").update(details={"x": 1})

    def test_bulk_queryset_delete_raises(self):
        """Regression test: QuerySet.delete() bypasses instance delete() entirely --
        this is the exact gap discovered during manual testing of this feature."""
        user = User.objects.create_user(username="ledgerStaff5", password="pw-ledger-5")
        staff = Staff.objects.create(
            user=user, staff_id="STF-L5", full_name="Ledger Tester 5", role=Staff.Role.DOCTOR,
            ward="Ward A", on_duty=True,
        )
        record_event(event_type=LedgerEntry.EventType.STANDARD_ACCESS, staff=staff)

        with self.assertRaises(LedgerImmutableError):
            LedgerEntry.objects.using("ledger").filter(staff_id="STF-L5").delete()

        self.assertEqual(LedgerEntry.objects.using("ledger").filter(staff_id="STF-L5").count(), 1)


class DecideViewLedgerIntegrationTests(APITestCase):
    databases = {"default", "ledger"}

    def _login(self, username, password, staff_id, role, ward="", on_duty=True):
        user = User.objects.create_user(username=username, password=password)
        staff = Staff.objects.create(
            user=user, staff_id=staff_id, full_name=username, role=role, ward=ward, on_duty=on_duty
        )
        resp = self.client.post(
            "/api/access/login/",
            {"username": username, "password": password, "device_id": f"device-{staff_id}", "device_type": "desktop"},
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED, resp.data)
        return staff, resp.data["token"]

    def _auth(self, token):
        return {"HTTP_AUTHORIZATION": f"Bearer {token}"}

    def test_decide_writes_a_matching_ledger_entry(self):
        staff, token = self._login("ledgerApi1", "pw-ledger-api-1", "STF-L900", Staff.Role.DOCTOR, ward="Ward A")
        patient = Patient.objects.create(hospital_number="HN-L900", full_name="LP1", ward="Ward A")

        target_resp = self.client.post(
            "/api/captures/contextual/target-patient/", {"patient_id": patient.id}, format="json", **self._auth(token)
        )
        self.assertEqual(target_resp.status_code, status.HTTP_200_OK)

        decide_resp = self.client.post("/api/scoring/decide/", {"patient_id": patient.id}, format="json", **self._auth(token))
        self.assertEqual(decide_resp.status_code, status.HTTP_201_CREATED)

        entries = LedgerEntry.objects.using("ledger").filter(staff_id="STF-L900")
        self.assertEqual(entries.count(), 1)
        entry = entries.first()
        self.assertEqual(entry.event_type, decide_resp.data["decision_type"])
        self.assertEqual(entry.patient_hospital_number, "HN-L900")
        self.assertEqual(entry.details["score"], decide_resp.data["score"])

        ok, bad_sequence = verify_chain()
        self.assertTrue(ok)
        self.assertIsNone(bad_sequence)

    def test_denied_decision_is_also_logged(self):
        """Nurse rule case 3 (neither assigned nor same ward) -- a hard denial must
        still write to the ledger (CLAUDE.md: every decision, not just grants)."""
        staff, token = self._login("ledgerApi2", "pw-ledger-api-2", "STF-L901", Staff.Role.NURSE, ward="Ward A")
        patient = Patient.objects.create(hospital_number="HN-L901", full_name="LP2", ward="Ward B")

        self.client.post(
            "/api/captures/contextual/target-patient/", {"patient_id": patient.id}, format="json", **self._auth(token)
        )
        decide_resp = self.client.post("/api/scoring/decide/", {"patient_id": patient.id}, format="json", **self._auth(token))
        self.assertEqual(decide_resp.status_code, status.HTTP_201_CREATED)
        self.assertEqual(decide_resp.data["decision_type"], "ACCESS_DENIED")

        entry = LedgerEntry.objects.using("ledger").get(staff_id="STF-L901")
        self.assertEqual(entry.event_type, "ACCESS_DENIED")
        self.assertEqual(entry.details["granted_categories"], [])


class LedgerFeedViewTests(APITestCase):
    """/api/ledger/entries/ -- security-officer-only (staff/permissions.py)."""

    databases = {"default", "ledger"}

    def _login(self, username, password, staff_id, role):
        user = User.objects.create_user(username=username, password=password)
        staff = Staff.objects.create(user=user, staff_id=staff_id, full_name=username, role=role)
        resp = self.client.post(
            "/api/access/login/",
            {"username": username, "password": password, "device_id": f"device-{staff_id}", "device_type": "desktop"},
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED, resp.data)
        return staff, resp.data["token"]

    def _auth(self, token):
        return {"HTTP_AUTHORIZATION": f"Bearer {token}"}

    def test_non_security_officer_forbidden(self):
        _staff, token = self._login("adminLedgerApi", "pw-ledger-feed-1", "STF-LF900", Staff.Role.ADMIN)
        resp = self.client.get("/api/ledger/entries/", **self._auth(token))
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)

    def test_security_officer_sees_entries_newest_first_and_can_filter(self):
        officer, token = self._login("secOfficerApi", "pw-ledger-feed-2", "STF-LF901", Staff.Role.SECURITY_OFFICER)
        doctor = self._login("docLedgerFeedApi", "pw-ledger-feed-3", "STF-LF902", Staff.Role.DOCTOR)[0]

        record_event(event_type=LedgerEntry.EventType.STANDARD_ACCESS, staff=doctor)
        record_event(event_type=LedgerEntry.EventType.ACCESS_DENIED, staff=doctor)

        resp = self.client.get("/api/ledger/entries/", **self._auth(token))
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(len(resp.data), 2)
        self.assertEqual(resp.data[0]["event_type"], "ACCESS_DENIED")  # newest first
        self.assertEqual(resp.data[0]["staff_role"], "doctor")
        self.assertNotIn("session_token", resp.data[0])

        filtered_resp = self.client.get(
            "/api/ledger/entries/?event_type=ACCESS_DENIED", **self._auth(token)
        )
        self.assertEqual(len(filtered_resp.data), 1)
        self.assertEqual(filtered_resp.data[0]["event_type"], "ACCESS_DENIED")

    def test_staff_role_filter(self):
        """staff_role query param, added 2026-08-31 for the Ledger page's role
        "slicer" -- filters on the denormalized staff_role field."""
        officer, token = self._login("secOfficerApi2", "pw-ledger-feed-4", "STF-LF903", Staff.Role.SECURITY_OFFICER)
        doctor = self._login("docLedgerFeedApi2", "pw-ledger-feed-5", "STF-LF904", Staff.Role.DOCTOR)[0]
        nurse = self._login("nurseLedgerFeedApi", "pw-ledger-feed-6", "STF-LF905", Staff.Role.NURSE)[0]

        record_event(event_type=LedgerEntry.EventType.STANDARD_ACCESS, staff=doctor)
        record_event(event_type=LedgerEntry.EventType.STANDARD_ACCESS, staff=nurse)

        resp = self.client.get("/api/ledger/entries/?staff_role=nurse", **self._auth(token))
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(len(resp.data), 1)
        self.assertEqual(resp.data[0]["staff_role"], "nurse")


class LedgerEntryExplainViewTests(APITestCase):
    """/api/ledger/entries/<sequence>/explain/ -- security-officer-only.
    gemini.explain_entry is always mocked here so the suite never makes a
    real network call (added 2026-09-03, per the user's "explain with AI"
    feature)."""

    databases = {"default", "ledger"}

    def _login(self, username, password, staff_id, role):
        user = User.objects.create_user(username=username, password=password)
        staff = Staff.objects.create(user=user, staff_id=staff_id, full_name=username, role=role)
        resp = self.client.post(
            "/api/access/login/",
            {"username": username, "password": password, "device_id": f"device-{staff_id}", "device_type": "desktop"},
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED, resp.data)
        return staff, resp.data["token"]

    def _auth(self, token):
        return {"HTTP_AUTHORIZATION": f"Bearer {token}"}

    def test_non_security_officer_forbidden(self):
        _staff, token = self._login("adminExplainApi", "pw-explain-1", "STF-EX900", Staff.Role.ADMIN)
        resp = self.client.post("/api/ledger/entries/1/explain/", **self._auth(token))
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)

    def test_unknown_sequence_404s(self):
        _officer, token = self._login("secOfficerExplainApi", "pw-explain-2", "STF-EX901", Staff.Role.SECURITY_OFFICER)
        resp = self.client.post("/api/ledger/entries/999999/explain/", **self._auth(token))
        self.assertEqual(resp.status_code, status.HTTP_404_NOT_FOUND)

    def test_success_returns_explanation(self):
        officer, token = self._login("secOfficerExplainApi2", "pw-explain-3", "STF-EX902", Staff.Role.SECURITY_OFFICER)
        doctor = self._login("docExplainApi", "pw-explain-4", "STF-EX903", Staff.Role.DOCTOR)[0]
        entry = record_event(
            event_type=LedgerEntry.EventType.ACCESS_DENIED,
            staff=doctor,
            details={"score": 12.5, "factor_breakdown": {"gate": {"keystroke_touch_similarity": 0.1}}},
        )

        with patch("ledger.views.explain_entry", return_value="The doctor's typing pattern didn't match, so access was denied.") as mocked:
            resp = self.client.post(f"/api/ledger/entries/{entry.sequence}/explain/", **self._auth(token))

        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data["explanation"], "The doctor's typing pattern didn't match, so access was denied.")
        mocked.assert_called_once()

    def test_gemini_failure_returns_502(self):
        officer, token = self._login("secOfficerExplainApi3", "pw-explain-5", "STF-EX904", Staff.Role.SECURITY_OFFICER)
        doctor = self._login("docExplainApi2", "pw-explain-6", "STF-EX905", Staff.Role.DOCTOR)[0]
        entry = record_event(event_type=LedgerEntry.EventType.STANDARD_ACCESS, staff=doctor)

        with patch("ledger.views.explain_entry", side_effect=GeminiError("AI explanations aren't configured.")):
            resp = self.client.post(f"/api/ledger/entries/{entry.sequence}/explain/", **self._auth(token))

        self.assertEqual(resp.status_code, 502)
        self.assertIn("aren't configured", resp.data["detail"])


class LedgerVerifyViewTests(APITestCase):
    """/api/ledger/verify/ -- security-officer-only. Exposes verify_chain()
    (added 2026-09-06, per the user) so the Ledger's tamper-evidence can
    actually be demonstrated, not just tested."""

    databases = {"default", "ledger"}

    def _login(self, username, password, staff_id, role):
        user = User.objects.create_user(username=username, password=password)
        staff = Staff.objects.create(user=user, staff_id=staff_id, full_name=username, role=role)
        resp = self.client.post(
            "/api/access/login/",
            {"username": username, "password": password, "device_id": f"device-{staff_id}", "device_type": "desktop"},
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED, resp.data)
        return staff, resp.data["token"]

    def _auth(self, token):
        return {"HTTP_AUTHORIZATION": f"Bearer {token}"}

    def test_non_security_officer_forbidden(self):
        _staff, token = self._login("adminVerifyApi", "pw-verify-1", "STF-V900", Staff.Role.ADMIN)
        resp = self.client.get("/api/ledger/verify/", **self._auth(token))
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)

    def test_unauthenticated_forbidden(self):
        resp = self.client.get("/api/ledger/verify/")
        self.assertEqual(resp.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_intact_chain_reports_valid_with_entry_count(self):
        _officer, token = self._login("secOfficerVerify", "pw-verify-2", "STF-V901", Staff.Role.SECURITY_OFFICER)
        doctor = self._login("docVerifyApi", "pw-verify-3", "STF-V902", Staff.Role.DOCTOR)[0]

        record_event(event_type=LedgerEntry.EventType.STANDARD_ACCESS, staff=doctor)
        record_event(event_type=LedgerEntry.EventType.ACCESS_DENIED, staff=doctor)

        resp = self.client.get("/api/ledger/verify/", **self._auth(token))
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertTrue(resp.data["valid"])
        self.assertIsNone(resp.data["bad_sequence"])
        self.assertEqual(resp.data["entries_checked"], 2)
        self.assertIn("verified_at", resp.data)

    def test_tampered_chain_reports_the_bad_entry(self):
        """Same raw-SQL tamper as RecordEventChainTests above -- the threat
        model here is direct database access, not application code."""
        _officer, token = self._login("secOfficerVerify2", "pw-verify-4", "STF-V903", Staff.Role.SECURITY_OFFICER)
        doctor = self._login("docVerifyApi2", "pw-verify-5", "STF-V904", Staff.Role.DOCTOR)[0]

        record_event(event_type=LedgerEntry.EventType.STANDARD_ACCESS, staff=doctor)
        entry = record_event(event_type=LedgerEntry.EventType.AUDITED_DEVIATION, staff=doctor)

        with connections["ledger"].cursor() as cursor:
            cursor.execute(
                "UPDATE ledger_ledgerentry SET details = %s WHERE sequence = %s",
                ['{"tampered": true}', entry.sequence],
            )

        resp = self.client.get("/api/ledger/verify/", **self._auth(token))
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertFalse(resp.data["valid"])
        self.assertEqual(resp.data["bad_sequence"], entry.sequence)

    def test_empty_chain_is_valid(self):
        _officer, token = self._login("secOfficerVerify3", "pw-verify-6", "STF-V905", Staff.Role.SECURITY_OFFICER)
        resp = self.client.get("/api/ledger/verify/", **self._auth(token))
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertTrue(resp.data["valid"])
        self.assertEqual(resp.data["entries_checked"], 0)
