"""AccessSession model + login/logout/session-current view tests, and custom
AccessSessionAuthentication tests. See staff/tests.py docstring re: the throwaway
test database and CLAUDE.md's no-placeholder-data rule."""

from django.contrib.auth.models import User
from rest_framework import status
from rest_framework.test import APITestCase

from staff.models import Staff

from .models import AccessSession


class AccessSessionModelTests(APITestCase):
    def test_token_auto_generated_and_unique(self):
        user1 = User.objects.create_user(username="u1", password="pw-one-12345")
        user2 = User.objects.create_user(username="u2", password="pw-two-12345")
        staff1 = Staff.objects.create(user=user1, staff_id="S1", full_name="A", role=Staff.Role.DOCTOR)
        staff2 = Staff.objects.create(user=user2, staff_id="S2", full_name="B", role=Staff.Role.DOCTOR)

        s1 = AccessSession.objects.create(staff=staff1, device_id="dev-1")
        s2 = AccessSession.objects.create(staff=staff2, device_id="dev-2")

        self.assertNotEqual(s1.token, s2.token)
        self.assertEqual(len(s1.token), 64)  # secrets.token_hex(32) -> 64 hex chars
        self.assertTrue(s1.is_active)
        self.assertIsNone(s1.ended_at)

    def test_network_segment_defaults_to_unknown_when_not_supplied(self):
        user = User.objects.create_user(username="u3", password="pw-three-12345")
        staff = Staff.objects.create(user=user, staff_id="S3", full_name="C", role=Staff.Role.CLERK)
        session = AccessSession.objects.create(staff=staff, device_id="dev-3")
        self.assertEqual(session.network_segment, "unknown")


class LoginViewTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="drA", password="correct-horse-1")
        self.staff = Staff.objects.create(
            user=self.user,
            staff_id="STF-200",
            full_name="Dr A",
            role=Staff.Role.DOCTOR,
            ward="Ward A",
            on_duty=True,
        )

    def test_login_success_creates_session_and_empty_captures(self):
        resp = self.client.post(
            "/api/access/login/",
            {
                "username": "drA",
                "password": "correct-horse-1",
                "device_id": "device-abc",
                "device_type": "desktop",
            },
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
        self.assertIn("token", resp.data)

        session = AccessSession.objects.get(token=resp.data["token"])
        self.assertTrue(session.is_active)
        self.assertTrue(hasattr(session, "behavioral_capture"))
        self.assertTrue(hasattr(session, "contextual_capture"))

        self.assertEqual(session.behavioral_capture.keystroke_features, {"login": None, "session_windows": []})
        self.assertEqual(session.contextual_capture.on_duty_at_login, True)
        self.assertEqual(session.contextual_capture.ward_assignment_at_login, "Ward A")
        self.assertEqual(session.contextual_capture.patient_assignment_status, "no_patient_selected")

    def test_login_with_keystroke_features_stores_login_baseline(self):
        resp = self.client.post(
            "/api/access/login/",
            {
                "username": "drA",
                "password": "correct-horse-1",
                "device_id": "device-abc",
                "device_type": "desktop",
                "keystroke_features": {
                    "flight_times": [110.0, 95.0],
                    "digraph_latencies": [140.0, 130.0],
                    "trigraph_latencies": [260.0],
                    "error_correction_rate": 0.0,
                    "rhythm_consistency": 0.85,
                    "automation_flags": [],
                },
            },
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
        session = AccessSession.objects.get(token=resp.data["token"])
        login_features = session.behavioral_capture.keystroke_features["login"]
        self.assertEqual(login_features["flight_times"], [110.0, 95.0])
        self.assertEqual(login_features["rhythm_consistency"], 0.85)

    def test_login_with_malformed_keystroke_features_still_succeeds(self):
        """Keystroke features are best-effort telemetry -- a malformed shape must
        never block a real login."""
        resp = self.client.post(
            "/api/access/login/",
            {
                "username": "drA",
                "password": "correct-horse-1",
                "device_id": "device-abc",
                "device_type": "desktop",
                "keystroke_features": {"error_correction_rate": "not-a-number"},
            },
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
        session = AccessSession.objects.get(token=resp.data["token"])
        self.assertIsNone(session.behavioral_capture.keystroke_features["login"])

    def test_login_bad_password_rejected(self):
        resp = self.client.post(
            "/api/access/login/",
            {
                "username": "drA",
                "password": "totally-wrong-password",
                "device_id": "device-abc",
                "device_type": "desktop",
            },
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertEqual(AccessSession.objects.count(), 0)

    def test_login_unknown_username_rejected(self):
        resp = self.client.post(
            "/api/access/login/",
            {
                "username": "nobody-registered",
                "password": "whatever-123",
                "device_id": "device-abc",
                "device_type": "desktop",
            },
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_login_no_staff_profile_rejected(self):
        User.objects.create_user(username="no_staff", password="whatever-123")
        resp = self.client.post(
            "/api/access/login/",
            {
                "username": "no_staff",
                "password": "whatever-123",
                "device_id": "device-abc",
                "device_type": "desktop",
            },
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(AccessSession.objects.count(), 0)

    def test_login_missing_device_id_rejected(self):
        resp = self.client.post(
            "/api/access/login/",
            {"username": "drA", "password": "correct-horse-1"},
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_login_missing_credentials_rejected(self):
        resp = self.client.post("/api/access/login/", {"device_id": "device-abc"}, format="json")
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)


class AuthenticationTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="nurseB", password="pw-secure-99")
        self.staff = Staff.objects.create(
            user=self.user, staff_id="STF-300", full_name="Nurse B", role=Staff.Role.NURSE, ward="Ward C"
        )
        login = self.client.post(
            "/api/access/login/",
            {
                "username": "nurseB",
                "password": "pw-secure-99",
                "device_id": "device-xyz",
                "device_type": "mobile",
            },
            format="json",
        )
        self.token = login.data["token"]

    def _auth_header(self, token):
        return {"HTTP_AUTHORIZATION": f"Bearer {token}"}

    def test_valid_token_accepted(self):
        resp = self.client.get("/api/access/session/current/", **self._auth_header(self.token))
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data["staff_id"], "STF-300")
        self.assertEqual(resp.data["role"], "nurse")

    def test_missing_token_rejected(self):
        resp = self.client.get("/api/access/session/current/")
        self.assertEqual(resp.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_invalid_token_rejected(self):
        resp = self.client.get("/api/access/session/current/", **self._auth_header("not-a-real-token"))
        self.assertEqual(resp.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_malformed_auth_header_rejected(self):
        resp = self.client.get("/api/access/session/current/", HTTP_AUTHORIZATION="Bearer")
        self.assertEqual(resp.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_inactive_session_token_rejected(self):
        session = AccessSession.objects.get(token=self.token)
        session.is_active = False
        session.save(update_fields=["is_active"])

        resp = self.client.get("/api/access/session/current/", **self._auth_header(self.token))
        self.assertEqual(resp.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_logout_ends_session_and_invalidates_token(self):
        resp = self.client.post("/api/access/logout/", **self._auth_header(self.token))
        self.assertEqual(resp.status_code, status.HTTP_204_NO_CONTENT)

        session = AccessSession.objects.get(token=self.token)
        self.assertFalse(session.is_active)
        self.assertIsNotNone(session.ended_at)

        resp2 = self.client.get("/api/access/session/current/", **self._auth_header(self.token))
        self.assertEqual(resp2.status_code, status.HTTP_401_UNAUTHORIZED)
