"""AccessSession model + login/logout/session-current view tests, and custom
AccessSessionAuthentication tests. See staff/tests.py docstring re: the throwaway
test database and CLAUDE.md's no-placeholder-data rule."""

from django.contrib.auth.models import User
from rest_framework import status
from rest_framework.test import APITestCase

from staff.models import Staff

from .models import AccessSession, Device, PendingDeviceRequest


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
        self.assertEqual(session.contextual_capture.on_call_at_login, False)
        self.assertEqual(session.contextual_capture.ward_assignment_at_login, "Ward A")
        self.assertEqual(session.contextual_capture.patient_assignment_status, "no_patient_selected")

    def test_login_snapshots_on_call_status(self):
        user = User.objects.create_user(username="drOnCall", password="correct-horse-2")
        Staff.objects.create(
            user=user, staff_id="STF-201", full_name="Dr B", role=Staff.Role.DOCTOR,
            ward="Ward A", on_duty=False, on_call=True,
        )
        resp = self.client.post(
            "/api/access/login/",
            {"username": "drOnCall", "password": "correct-horse-2", "device_id": "device-def", "device_type": "desktop"},
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
        session = AccessSession.objects.get(token=resp.data["token"])
        self.assertFalse(session.contextual_capture.on_duty_at_login)
        self.assertTrue(session.contextual_capture.on_call_at_login)

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


class ChangePasswordViewTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="pharmC", password="old-pass-123")
        self.staff = Staff.objects.create(
            user=self.user, staff_id="STF-400", full_name="Pharm C", role=Staff.Role.PHARMACIST
        )
        login = self.client.post(
            "/api/access/login/",
            {
                "username": "pharmC",
                "password": "old-pass-123",
                "device_id": "device-pw-1",
                "device_type": "desktop",
            },
            format="json",
        )
        self.token = login.data["token"]

    def _auth_header(self, token):
        return {"HTTP_AUTHORIZATION": f"Bearer {token}"}

    def test_wrong_current_password_rejected_and_password_unchanged(self):
        resp = self.client.post(
            "/api/access/change-password/",
            {"current_password": "not-the-real-password", "new_password": "brand-new-pass-1"},
            format="json",
            **self._auth_header(self.token),
        )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

        # Same device_id as setUp's original login -- this pharmacist's primary
        # device, not a second device, so it must still log in directly (a
        # different device_id here would hit the one-device pending-approval path
        # tested separately in DeviceBindingTests and isn't what this test is about).
        login_resp = self.client.post(
            "/api/access/login/",
            {"username": "pharmC", "password": "old-pass-123", "device_id": "device-pw-1", "device_type": "desktop"},
            format="json",
        )
        self.assertEqual(login_resp.status_code, status.HTTP_201_CREATED)

    def test_new_password_too_short_rejected(self):
        resp = self.client.post(
            "/api/access/change-password/",
            {"current_password": "old-pass-123", "new_password": "short"},
            format="json",
            **self._auth_header(self.token),
        )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_correct_current_password_changes_it(self):
        resp = self.client.post(
            "/api/access/change-password/",
            {"current_password": "old-pass-123", "new_password": "brand-new-pass-1"},
            format="json",
            **self._auth_header(self.token),
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)

        # Same device_id as setUp's original login throughout -- this is about
        # password correctness, not device binding (see the note in
        # test_wrong_current_password_rejected_and_password_unchanged above).
        old_login_resp = self.client.post(
            "/api/access/login/",
            {"username": "pharmC", "password": "old-pass-123", "device_id": "device-pw-1", "device_type": "desktop"},
            format="json",
        )
        self.assertEqual(old_login_resp.status_code, status.HTTP_401_UNAUTHORIZED)

        new_login_resp = self.client.post(
            "/api/access/login/",
            {"username": "pharmC", "password": "brand-new-pass-1", "device_id": "device-pw-1", "device_type": "desktop"},
            format="json",
        )
        self.assertEqual(new_login_resp.status_code, status.HTTP_201_CREATED)

    def test_unauthenticated_cannot_change_password(self):
        resp = self.client.post(
            "/api/access/change-password/",
            {"current_password": "old-pass-123", "new_password": "brand-new-pass-1"},
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_401_UNAUTHORIZED)


class DeviceBindingLoginTests(APITestCase):
    """One device per (clinical) account, added 2026-08-30. See access/models.py's
    Device/PendingDeviceRequest docstrings and CLAUDE.md."""

    def setUp(self):
        self.user = User.objects.create_user(username="drDevice", password="pw-device-123")
        self.staff = Staff.objects.create(
            user=self.user, staff_id="STF-500", full_name="Dr Device", role=Staff.Role.DOCTOR
        )

    def _login(self, device_id, device_type="desktop", password="pw-device-123"):
        return self.client.post(
            "/api/access/login/",
            {"username": "drDevice", "password": password, "device_id": device_id, "device_type": device_type},
            format="json",
        )

    def test_first_clinical_login_becomes_primary_device(self):
        resp = self._login("device-1")
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
        self.assertIn("token", resp.data)

        device = Device.objects.get(staff=self.staff)
        self.assertEqual(device.device_id, "device-1")
        self.assertTrue(device.is_primary)

    def test_same_device_repeated_login_succeeds_normally(self):
        self._login("device-1")
        resp = self._login("device-1")
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
        self.assertIn("token", resp.data)
        self.assertEqual(Device.objects.filter(staff=self.staff).count(), 1)

    def test_different_device_creates_pending_request_not_session(self):
        self._login("device-1")
        sessions_before = AccessSession.objects.filter(staff=self.staff).count()

        resp = self._login("device-2")
        self.assertEqual(resp.status_code, status.HTTP_202_ACCEPTED)
        self.assertEqual(resp.data["status"], "pending_approval")
        self.assertIn("poll_token", resp.data)

        self.assertEqual(AccessSession.objects.filter(staff=self.staff).count(), sessions_before)
        pending = PendingDeviceRequest.objects.get(staff=self.staff, device_id="device-2")
        self.assertEqual(pending.status, PendingDeviceRequest.Status.PENDING)
        self.assertEqual(pending.poll_token, resp.data["poll_token"])

    def test_repeated_attempt_from_same_new_device_reuses_pending_request(self):
        self._login("device-1")
        first = self._login("device-2")
        second = self._login("device-2")
        self.assertEqual(first.data["poll_token"], second.data["poll_token"])
        self.assertEqual(
            PendingDeviceRequest.objects.filter(staff=self.staff, device_id="device-2").count(), 1
        )

    def test_admin_role_unaffected_by_device_binding(self):
        admin_user = User.objects.create_user(username="adminD", password="pw-admin-123")
        Staff.objects.create(user=admin_user, staff_id="STF-501", full_name="Admin D", role=Staff.Role.ADMIN)

        for device_id in ("dev-a", "dev-b", "dev-c"):
            resp = self.client.post(
                "/api/access/login/",
                {"username": "adminD", "password": "pw-admin-123", "device_id": device_id, "device_type": "desktop"},
                format="json",
            )
            self.assertEqual(resp.status_code, status.HTTP_201_CREATED)

        self.assertEqual(Device.objects.count(), 0)
        self.assertEqual(PendingDeviceRequest.objects.count(), 0)

    def test_security_officer_role_unaffected_by_device_binding(self):
        sec_user = User.objects.create_user(username="secD", password="pw-sec-123")
        Staff.objects.create(user=sec_user, staff_id="STF-502", full_name="Sec D", role=Staff.Role.SECURITY_OFFICER)

        for device_id in ("dev-x", "dev-y"):
            resp = self.client.post(
                "/api/access/login/",
                {"username": "secD", "password": "pw-sec-123", "device_id": device_id, "device_type": "desktop"},
                format="json",
            )
            self.assertEqual(resp.status_code, status.HTTP_201_CREATED)

        self.assertEqual(Device.objects.count(), 0)


class DeviceRequestPollViewTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="drPoll", password="pw-poll-123")
        self.staff = Staff.objects.create(
            user=self.user, staff_id="STF-510", full_name="Dr Poll", role=Staff.Role.NURSE
        )
        self.client.post(
            "/api/access/login/",
            {"username": "drPoll", "password": "pw-poll-123", "device_id": "primary-dev", "device_type": "desktop"},
            format="json",
        )
        pending_resp = self.client.post(
            "/api/access/login/",
            {"username": "drPoll", "password": "pw-poll-123", "device_id": "second-dev", "device_type": "mobile"},
            format="json",
        )
        self.poll_token = pending_resp.data["poll_token"]

    def test_poll_unknown_token_404(self):
        resp = self.client.get("/api/access/device-requests/not-a-real-token/poll/")
        self.assertEqual(resp.status_code, status.HTTP_404_NOT_FOUND)

    def test_poll_pending(self):
        resp = self.client.get(f"/api/access/device-requests/{self.poll_token}/poll/")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data["status"], "pending")

    def test_poll_rejected(self):
        pending = PendingDeviceRequest.objects.get(poll_token=self.poll_token)
        pending.status = PendingDeviceRequest.Status.REJECTED
        pending.save(update_fields=["status"])

        resp = self.client.get(f"/api/access/device-requests/{self.poll_token}/poll/")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data["status"], "rejected")

    def test_poll_approved_returns_token_once_then_clears_it(self):
        pending = PendingDeviceRequest.objects.get(poll_token=self.poll_token)
        pending.status = PendingDeviceRequest.Status.APPROVED
        pending.session_token = "a" * 64
        pending.save(update_fields=["status", "session_token"])

        first = self.client.get(f"/api/access/device-requests/{self.poll_token}/poll/")
        self.assertEqual(first.status_code, status.HTTP_200_OK)
        self.assertEqual(first.data["status"], "approved")
        self.assertEqual(first.data["token"], "a" * 64)

        second = self.client.get(f"/api/access/device-requests/{self.poll_token}/poll/")
        self.assertEqual(second.data["status"], "approved")
        self.assertIsNone(second.data["token"])


class DeviceManagementViewTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="drManage", password="pw-manage-123")
        self.staff = Staff.objects.create(
            user=self.user, staff_id="STF-520", full_name="Dr Manage", role=Staff.Role.DOCTOR
        )
        login = self.client.post(
            "/api/access/login/",
            {"username": "drManage", "password": "pw-manage-123", "device_id": "primary-dev", "device_type": "desktop"},
            format="json",
        )
        self.token = login.data["token"]
        self.primary_device = Device.objects.get(staff=self.staff)

        self.client.post(
            "/api/access/login/",
            {"username": "drManage", "password": "pw-manage-123", "device_id": "second-dev", "device_type": "mobile"},
            format="json",
        )
        self.pending = PendingDeviceRequest.objects.get(staff=self.staff, device_id="second-dev")

        other_user = User.objects.create_user(username="drOther", password="pw-other-123")
        self.other_staff = Staff.objects.create(
            user=other_user, staff_id="STF-521", full_name="Dr Other", role=Staff.Role.DOCTOR
        )

    def _auth_header(self, token=None):
        return {"HTTP_AUTHORIZATION": f"Bearer {token or self.token}"}

    def test_device_list_returns_own_devices_and_pending(self):
        resp = self.client.get("/api/access/devices/", **self._auth_header())
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(len(resp.data["devices"]), 1)
        self.assertTrue(resp.data["devices"][0]["is_primary"])
        self.assertEqual(len(resp.data["pending_requests"]), 1)
        self.assertEqual(resp.data["pending_requests"][0]["device_type"], "mobile")

    def test_pending_count(self):
        resp = self.client.get("/api/access/devices/pending-count/", **self._auth_header())
        self.assertEqual(resp.data["count"], 1)

    def test_approve_creates_device_and_working_session(self):
        resp = self.client.post(
            f"/api/access/device-requests/{self.pending.id}/approve/", **self._auth_header()
        )
        self.assertEqual(resp.status_code, status.HTTP_204_NO_CONTENT)

        self.pending.refresh_from_db()
        self.assertEqual(self.pending.status, PendingDeviceRequest.Status.APPROVED)
        self.assertTrue(Device.objects.filter(staff=self.staff, device_id="second-dev", is_primary=False).exists())

        poll = self.client.get(f"/api/access/device-requests/{self.pending.poll_token}/poll/")
        self.assertEqual(poll.data["status"], "approved")
        self.assertIsNotNone(poll.data["token"])

    def test_reject_leaves_no_session(self):
        resp = self.client.post(
            f"/api/access/device-requests/{self.pending.id}/reject/", **self._auth_header()
        )
        self.assertEqual(resp.status_code, status.HTTP_204_NO_CONTENT)
        self.pending.refresh_from_db()
        self.assertEqual(self.pending.status, PendingDeviceRequest.Status.REJECTED)
        self.assertFalse(Device.objects.filter(staff=self.staff, device_id="second-dev").exists())

    def test_acting_twice_on_resolved_request_404s(self):
        self.client.post(f"/api/access/device-requests/{self.pending.id}/reject/", **self._auth_header())
        resp = self.client.post(f"/api/access/device-requests/{self.pending.id}/approve/", **self._auth_header())
        self.assertEqual(resp.status_code, status.HTTP_404_NOT_FOUND)

    def test_cannot_approve_another_staffs_pending_request(self):
        other_login = self.client.post(
            "/api/access/login/",
            {"username": "drOther", "password": "pw-other-123", "device_id": "other-primary", "device_type": "desktop"},
            format="json",
        )
        resp = self.client.post(
            f"/api/access/device-requests/{self.pending.id}/approve/",
            **self._auth_header(other_login.data["token"]),
        )
        self.assertEqual(resp.status_code, status.HTTP_404_NOT_FOUND)

    def test_cannot_remove_primary_device(self):
        resp = self.client.post(
            f"/api/access/devices/{self.primary_device.id}/remove/", **self._auth_header()
        )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertTrue(Device.objects.filter(pk=self.primary_device.id).exists())

    def test_remove_non_primary_device_ends_its_active_session(self):
        self.client.post(f"/api/access/device-requests/{self.pending.id}/approve/", **self._auth_header())
        second_device = Device.objects.get(staff=self.staff, device_id="second-dev")
        second_session = AccessSession.objects.get(staff=self.staff, device_id="second-dev")
        self.assertTrue(second_session.is_active)

        resp = self.client.post(f"/api/access/devices/{second_device.id}/remove/", **self._auth_header())
        self.assertEqual(resp.status_code, status.HTTP_204_NO_CONTENT)
        self.assertFalse(Device.objects.filter(pk=second_device.id).exists())

        second_session.refresh_from_db()
        self.assertFalse(second_session.is_active)
        self.assertIsNotNone(second_session.ended_at)

    def test_cannot_remove_another_staffs_device(self):
        self.client.post(
            "/api/access/login/",
            {"username": "drOther", "password": "pw-other-123", "device_id": "other-primary", "device_type": "desktop"},
            format="json",
        )
        other_device = Device.objects.get(staff=self.other_staff, device_id="other-primary")

        resp = self.client.post(
            f"/api/access/devices/{other_device.id}/remove/", **self._auth_header()
        )
        self.assertEqual(resp.status_code, status.HTTP_404_NOT_FOUND)
