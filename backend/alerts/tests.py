"""Security alert tests (added 2026-09-06). No real enrollment data -- Django's
isolated test database only, per CLAUDE.md."""

from django.contrib.auth.models import User
from rest_framework import status
from rest_framework.test import APITestCase

from staff.models import Staff

from .models import SecurityAlert
from .services import raise_alert


class RaiseAlertTests(APITestCase):
    def test_alert_starts_unacknowledged_with_denormalized_staff(self):
        user = User.objects.create_user(username="alertDoc", password="pw-alert-1")
        staff = Staff.objects.create(
            user=user, staff_id="STF-A1", full_name="Alert Doctor", role=Staff.Role.DOCTOR
        )

        alert = raise_alert(
            alert_type=SecurityAlert.AlertType.ACCESS_DENIED,
            staff=staff,
            details={"score": 22.0},
            ledger_sequence=7,
        )

        self.assertEqual(alert.staff_id, "STF-A1")
        self.assertEqual(alert.staff_full_name, "Alert Doctor")
        self.assertEqual(alert.staff_role, Staff.Role.DOCTOR)
        self.assertEqual(alert.ledger_sequence, 7)
        self.assertFalse(alert.acknowledged)
        self.assertIsNone(alert.acknowledged_at)

    def test_alert_survives_staff_deletion(self):
        """Denormalized on purpose -- deleting a staff member must not delete
        the evidence of what they did (same reasoning as ledger.LedgerEntry)."""
        user = User.objects.create_user(username="alertDoc2", password="pw-alert-2")
        staff = Staff.objects.create(
            user=user, staff_id="STF-A2", full_name="Alert Doctor 2", role=Staff.Role.NURSE
        )
        raise_alert(alert_type=SecurityAlert.AlertType.STEP_UP_FAILED, staff=staff)

        user.delete()  # cascades to Staff

        alert = SecurityAlert.objects.get(staff_id="STF-A2")
        self.assertEqual(alert.staff_full_name, "Alert Doctor 2")

    def test_alert_without_staff_is_allowed(self):
        """A lockout against a username matching no real account still deserves
        an alert."""
        alert = raise_alert(
            alert_type=SecurityAlert.AlertType.LOGIN_LOCKOUT,
            details={"username": "not-a-real-account"},
        )
        self.assertEqual(alert.staff_id, "")
        self.assertEqual(alert.details["username"], "not-a-real-account")


class AlertApiTests(APITestCase):
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
        _staff, token = self._login("adminAlertApi", "pw-alert-api-1", "STF-AA1", Staff.Role.ADMIN)
        self.assertEqual(
            self.client.get("/api/alerts/", **self._auth(token)).status_code,
            status.HTTP_403_FORBIDDEN,
        )
        self.assertEqual(
            self.client.get("/api/alerts/unacknowledged-count/", **self._auth(token)).status_code,
            status.HTTP_403_FORBIDDEN,
        )

    def test_list_and_filter(self):
        _officer, token = self._login("secAlertApi", "pw-alert-api-2", "STF-AA2", Staff.Role.SECURITY_OFFICER)
        doctor = self._login("docAlertApi", "pw-alert-api-3", "STF-AA3", Staff.Role.DOCTOR)[0]

        raise_alert(alert_type=SecurityAlert.AlertType.ACCESS_DENIED, staff=doctor)
        raise_alert(alert_type=SecurityAlert.AlertType.LOGIN_LOCKOUT, staff=doctor)

        resp = self.client.get("/api/alerts/", **self._auth(token))
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(len(resp.data), 2)

        filtered = self.client.get("/api/alerts/?alert_type=LOGIN_LOCKOUT", **self._auth(token))
        self.assertEqual(len(filtered.data), 1)
        self.assertEqual(filtered.data[0]["alert_type"], "LOGIN_LOCKOUT")

    def test_unacknowledged_count_and_acknowledge_flow(self):
        officer, token = self._login("secAlertApi2", "pw-alert-api-4", "STF-AA4", Staff.Role.SECURITY_OFFICER)
        doctor = self._login("docAlertApi2", "pw-alert-api-5", "STF-AA5", Staff.Role.DOCTOR)[0]
        alert = raise_alert(alert_type=SecurityAlert.AlertType.ACCESS_DENIED, staff=doctor)

        count_resp = self.client.get("/api/alerts/unacknowledged-count/", **self._auth(token))
        self.assertEqual(count_resp.data["count"], 1)

        ack_resp = self.client.post(
            f"/api/alerts/{alert.id}/acknowledge/",
            {"note": "Checked with the ward -- wrong workstation, no action needed."},
            format="json",
            **self._auth(token),
        )
        self.assertEqual(ack_resp.status_code, status.HTTP_200_OK)
        self.assertTrue(ack_resp.data["acknowledged"])
        self.assertEqual(ack_resp.data["acknowledged_by_staff_id"], officer.staff_id)

        self.assertEqual(
            self.client.get("/api/alerts/unacknowledged-count/", **self._auth(token)).data["count"],
            0,
        )
        unack = self.client.get("/api/alerts/?acknowledged=false", **self._auth(token))
        self.assertEqual(len(unack.data), 0)

    def test_acknowledging_twice_keeps_the_first_reviewer(self):
        officer, token = self._login("secAlertApi3", "pw-alert-api-6", "STF-AA6", Staff.Role.SECURITY_OFFICER)
        alert = raise_alert(alert_type=SecurityAlert.AlertType.LOGIN_LOCKOUT)

        self.client.post(
            f"/api/alerts/{alert.id}/acknowledge/", {"note": "first"}, format="json", **self._auth(token)
        )
        second = self.client.post(
            f"/api/alerts/{alert.id}/acknowledge/", {"note": "second"}, format="json", **self._auth(token)
        )
        self.assertEqual(second.status_code, status.HTTP_200_OK)
        self.assertEqual(second.data["acknowledgement_note"], "first")
        self.assertEqual(second.data["acknowledged_by_staff_id"], officer.staff_id)

    def test_note_is_optional(self):
        _officer, token = self._login("secAlertApi4", "pw-alert-api-7", "STF-AA7", Staff.Role.SECURITY_OFFICER)
        alert = raise_alert(alert_type=SecurityAlert.AlertType.STEP_UP_FAILED)
        resp = self.client.post(
            f"/api/alerts/{alert.id}/acknowledge/", {}, format="json", **self._auth(token)
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertTrue(resp.data["acknowledged"])
