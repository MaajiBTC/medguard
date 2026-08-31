"""Security Ledger tests. Uses Django's isolated multi-db test setup (both `default`
and `ledger` get their own temporary test databases) -- no real enrollment data, per
CLAUDE.md.
"""

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
