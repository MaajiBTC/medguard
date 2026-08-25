"""BehavioralCapture / ContextualCapture model + view tests. See staff/tests.py
docstring re: the throwaway test database and CLAUDE.md's no-placeholder-data rule.
"""

from django.contrib.auth.models import User
from django.db import IntegrityError, transaction
from rest_framework import status
from rest_framework.test import APITestCase

from access.models import AccessSession
from patients.models import Patient, PatientAssignment
from staff.models import Staff

from .models import BehavioralCapture, ContextualCapture


class CaptureModelTests(APITestCase):
    def _make_session(self, username, staff_id, role=Staff.Role.CLERK, ward="", on_duty=False):
        user = User.objects.create_user(username=username, password="pw-model-test-1")
        staff = Staff.objects.create(
            user=user, staff_id=staff_id, full_name=username, role=role, ward=ward, on_duty=on_duty
        )
        session = AccessSession.objects.create(staff=staff, device_id=f"dev-{staff_id}")
        return staff, session

    def test_behavioral_capture_defaults_to_empty_arrays(self):
        _, session = self._make_session("u_bc", "STF-600")
        capture = BehavioralCapture.objects.create(session=session)
        self.assertEqual(capture.keystroke_events, [])
        self.assertEqual(capture.mouse_events, [])
        self.assertEqual(capture.touch_events, [])
        self.assertEqual(capture.keystroke_event_count, 0)
        self.assertEqual(capture.mouse_event_count, 0)
        self.assertEqual(capture.touch_event_count, 0)

    def test_only_one_behavioral_capture_per_session(self):
        _, session = self._make_session("u_bc2", "STF-601")
        BehavioralCapture.objects.create(session=session)
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                BehavioralCapture.objects.create(session=session)

    def test_contextual_capture_default_status_is_no_patient_selected(self):
        staff, session = self._make_session("u_cc", "STF-602", role=Staff.Role.DOCTOR, ward="Ward A", on_duty=True)
        capture = ContextualCapture.objects.create(
            session=session, on_duty_at_login=staff.on_duty, ward_assignment_at_login=staff.ward
        )
        self.assertEqual(capture.patient_assignment_status, ContextualCapture.PatientAssignmentStatus.NO_PATIENT_SELECTED)
        self.assertIsNone(capture.target_patient)
        self.assertIsNone(capture.patient_assignment_checked_at)

    def test_only_one_contextual_capture_per_session(self):
        _, session = self._make_session("u_cc2", "STF-603")
        ContextualCapture.objects.create(session=session, on_duty_at_login=False, ward_assignment_at_login="")
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                ContextualCapture.objects.create(session=session, on_duty_at_login=False, ward_assignment_at_login="")


class CaptureAPITestBase(APITestCase):
    """Shared login helper for capture endpoint tests."""

    def _login(self, username, password, staff_id, role, ward="", on_duty=True):
        user = User.objects.create_user(username=username, password=password)
        staff = Staff.objects.create(
            user=user, staff_id=staff_id, full_name=username, role=role, ward=ward, on_duty=on_duty
        )
        resp = self.client.post(
            "/api/access/login/",
            {
                "username": username,
                "password": password,
                "device_id": f"device-{staff_id}",
                "device_type": "desktop",
            },
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED, resp.data)
        return staff, resp.data["token"]

    def _auth(self, token):
        return {"HTTP_AUTHORIZATION": f"Bearer {token}"}


class BehavioralEventsViewTests(CaptureAPITestBase):
    def setUp(self):
        self.staff, self.token = self._login("clerkA", "pw-clerk-1", "STF-400", Staff.Role.CLERK)

    def test_events_append_across_repeated_posts_not_overwrite(self):
        batch1 = {
            "keystroke_events": [{"event": "keydown", "code": "KeyA", "t": 1.0}],
            "mouse_events": [],
            "touch_events": [],
        }
        batch2 = {
            "keystroke_events": [{"event": "keyup", "code": "KeyA", "t": 1.2}],
            "mouse_events": [{"event": "mousemove", "x": 10, "y": 20, "t": 2.0}],
            "touch_events": [],
        }

        r1 = self.client.post("/api/captures/behavioral/events/", batch1, format="json", **self._auth(self.token))
        self.assertEqual(r1.status_code, status.HTTP_200_OK)
        r2 = self.client.post("/api/captures/behavioral/events/", batch2, format="json", **self._auth(self.token))
        self.assertEqual(r2.status_code, status.HTTP_200_OK)

        detail = self.client.get("/api/captures/behavioral/", **self._auth(self.token))
        self.assertEqual(detail.data["keystroke_event_count"], 2)
        self.assertEqual(detail.data["mouse_event_count"], 1)
        self.assertEqual(len(detail.data["keystroke_events"]), 2)
        self.assertEqual(detail.data["keystroke_events"][0]["code"], "KeyA")
        self.assertEqual(detail.data["keystroke_events"][1]["event"], "keyup")

    def test_malformed_event_unknown_type_rejected(self):
        bad_batch = {"keystroke_events": [{"event": "not-a-real-event", "code": "KeyA", "t": 1.0}]}
        resp = self.client.post("/api/captures/behavioral/events/", bad_batch, format="json", **self._auth(self.token))
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

        detail = self.client.get("/api/captures/behavioral/", **self._auth(self.token))
        self.assertEqual(detail.data["keystroke_event_count"], 0)

    def test_malformed_event_missing_field_rejected(self):
        bad_batch = {"mouse_events": [{"event": "mousemove", "x": 10}]}  # missing y and t
        resp = self.client.post("/api/captures/behavioral/events/", bad_batch, format="json", **self._auth(self.token))
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_empty_batch_rejected(self):
        resp = self.client.post("/api/captures/behavioral/events/", {}, format="json", **self._auth(self.token))
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_no_token_rejected_with_401(self):
        resp = self.client.get("/api/captures/behavioral/")
        self.assertEqual(resp.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_invalid_token_rejected_with_401(self):
        resp = self.client.get("/api/captures/behavioral/", HTTP_AUTHORIZATION="Bearer garbage-token-value")
        self.assertEqual(resp.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_events_scoped_to_callers_own_session_only(self):
        """A second staff member's own capture stays empty — events never leak
        across sessions since the session always comes from the token, never a
        client-supplied id."""
        _, other_token = self._login("clerkB", "pw-clerk-2", "STF-401", Staff.Role.CLERK)

        batch = {"keystroke_events": [{"event": "keydown", "code": "KeyZ", "t": 5.0}]}
        self.client.post("/api/captures/behavioral/events/", batch, format="json", **self._auth(self.token))

        other_detail = self.client.get("/api/captures/behavioral/", **self._auth(other_token))
        self.assertEqual(other_detail.data["keystroke_event_count"], 0)


class TargetPatientViewTests(CaptureAPITestBase):
    def test_assigned_status(self):
        staff, token = self._login("docA", "pw-doc-1", "STF-500", Staff.Role.DOCTOR, ward="Ward A")
        patient = Patient.objects.create(hospital_number="HN-500", full_name="P1", ward="Ward B")
        PatientAssignment.objects.create(patient=patient, staff=staff, role_in_assignment="doctor")

        resp = self.client.post(
            "/api/captures/contextual/target-patient/", {"patient_id": patient.id}, format="json", **self._auth(token)
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data["patient_assignment_status"], "assigned")
        self.assertEqual(resp.data["target_patient_id"], patient.id)

    def test_same_ward_not_assigned_status(self):
        staff, token = self._login("nurseC", "pw-nurse-1", "STF-501", Staff.Role.NURSE, ward="Ward C")
        patient = Patient.objects.create(hospital_number="HN-501", full_name="P2", ward="Ward C")

        resp = self.client.post(
            "/api/captures/contextual/target-patient/", {"patient_id": patient.id}, format="json", **self._auth(token)
        )
        self.assertEqual(resp.data["patient_assignment_status"], "same_ward_not_assigned")

    def test_not_assigned_not_same_ward_status(self):
        staff, token = self._login("nurseD", "pw-nurse-2", "STF-502", Staff.Role.NURSE, ward="Ward D")
        patient = Patient.objects.create(hospital_number="HN-502", full_name="P3", ward="Ward E")

        resp = self.client.post(
            "/api/captures/contextual/target-patient/", {"patient_id": patient.id}, format="json", **self._auth(token)
        )
        self.assertEqual(resp.data["patient_assignment_status"], "not_assigned_not_same_ward")

    def test_not_applicable_for_non_doctor_non_nurse_roles(self):
        for role, staff_id, username in [
            (Staff.Role.PHARMACIST, "STF-503", "pharmA"),
            (Staff.Role.LAB_TECHNICIAN, "STF-506", "labA"),
            (Staff.Role.CLERK, "STF-507", "clerkC"),
        ]:
            staff, token = self._login(username, "pw-role-1", staff_id, role, ward="Ward D")
            patient = Patient.objects.create(hospital_number=f"HN-{staff_id}", full_name="P4", ward="Ward D")

            resp = self.client.post(
                "/api/captures/contextual/target-patient/",
                {"patient_id": patient.id},
                format="json",
                **self._auth(token),
            )
            self.assertEqual(resp.data["patient_assignment_status"], "not_applicable")

    def test_no_patient_selected_is_initial_status_before_any_target_patient_call(self):
        staff, token = self._login("docB", "pw-doc-2", "STF-504", Staff.Role.DOCTOR, ward="Ward A")
        resp = self.client.get("/api/captures/contextual/", **self._auth(token))
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data["patient_assignment_status"], "no_patient_selected")
        self.assertIsNone(resp.data["target_patient_id"])

    def test_unknown_patient_id_returns_404(self):
        staff, token = self._login("docC", "pw-doc-3", "STF-505", Staff.Role.DOCTOR, ward="Ward A")
        resp = self.client.post(
            "/api/captures/contextual/target-patient/", {"patient_id": 999999}, format="json", **self._auth(token)
        )
        self.assertEqual(resp.status_code, status.HTTP_404_NOT_FOUND)

    def test_missing_patient_id_rejected(self):
        staff, token = self._login("docD", "pw-doc-4", "STF-508", Staff.Role.DOCTOR, ward="Ward A")
        resp = self.client.post("/api/captures/contextual/target-patient/", {}, format="json", **self._auth(token))
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_no_token_rejected_with_401(self):
        resp = self.client.get("/api/captures/contextual/")
        self.assertEqual(resp.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_invalid_token_rejected_with_401(self):
        resp = self.client.post(
            "/api/captures/contextual/target-patient/",
            {"patient_id": 1},
            format="json",
            HTTP_AUTHORIZATION="Bearer garbage-token-value",
        )
        self.assertEqual(resp.status_code, status.HTTP_401_UNAUTHORIZED)
