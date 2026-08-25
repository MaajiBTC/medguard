"""Staff model tests.

Runs against Django's throwaway test database (created/destroyed per test run,
transactions rolled back per test) — never touches the real db.sqlite3. Fixture
creation here is standard practice and does not conflict with CLAUDE.md's
no-placeholder-data rule, which is about the real application database.
"""

from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import TestCase
from rest_framework import status
from rest_framework.test import APITestCase

from .models import Staff


class StaffModelTests(TestCase):
    def _make_user(self, username="dr_adaeze"):
        return User.objects.create_user(username=username, password="test-pass-123")

    def test_create_staff_with_valid_fields(self):
        user = self._make_user()
        staff = Staff.objects.create(
            user=user,
            staff_id="STF-001",
            full_name="Dr. Adaeze Okafor",
            role=Staff.Role.DOCTOR,
            ward="General Medicine",
            on_duty=True,
        )
        self.assertEqual(staff.role, "doctor")
        self.assertTrue(staff.on_duty)
        self.assertIn("STF-001", str(staff))

    def test_on_duty_defaults_false(self):
        user = self._make_user("dr_default")
        staff = Staff.objects.create(
            user=user, staff_id="STF-030", full_name="A", role=Staff.Role.LAB_TECHNICIAN
        )
        self.assertFalse(staff.on_duty)

    def test_staff_id_must_be_unique(self):
        user1 = self._make_user("user1")
        user2 = self._make_user("user2")
        Staff.objects.create(user=user1, staff_id="STF-DUP", full_name="A", role=Staff.Role.NURSE)
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Staff.objects.create(user=user2, staff_id="STF-DUP", full_name="B", role=Staff.Role.NURSE)

    def test_user_can_only_have_one_staff_profile(self):
        user = self._make_user("user3")
        Staff.objects.create(user=user, staff_id="STF-010", full_name="A", role=Staff.Role.CLERK)
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Staff.objects.create(user=user, staff_id="STF-011", full_name="B", role=Staff.Role.CLERK)

    def test_invalid_role_rejected_by_full_clean(self):
        user = self._make_user("user4")
        staff = Staff(user=user, staff_id="STF-020", full_name="A", role="wizard")
        with self.assertRaises(ValidationError):
            staff.full_clean()

    def test_all_seven_roles_are_valid_choices(self):
        expected = {
            "doctor", "nurse", "pharmacist", "lab_technician", "clerk", "admin", "security_officer",
        }
        actual = {value for value, _label in Staff.Role.choices}
        self.assertEqual(expected, actual)

    def test_clinical_roles_excludes_admin_and_security_officer(self):
        expected = {"doctor", "nurse", "pharmacist", "lab_technician", "clerk"}
        actual = {role.value for role in Staff.CLINICAL_ROLES}
        self.assertEqual(expected, actual)


class StaffApiTests(APITestCase):
    """Admin-only staff-management endpoints (staff/views.py). Mirrors the
    login-then-call-with-Bearer-token pattern the rest of the suite already uses."""

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

    def test_non_admin_cannot_search_staff(self):
        _staff, token = self._login("docStaffApi1", "pw-staff-api-1", "STF-S900", Staff.Role.DOCTOR)
        resp = self.client.get("/api/staff/", **self._auth(token))
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)

    def test_admin_can_create_and_search_staff(self):
        _admin, token = self._login("adminApi1", "pw-staff-api-2", "STF-S901", Staff.Role.ADMIN)

        create_resp = self.client.post(
            "/api/staff/create/",
            {
                "username": "newNurseApi1",
                "password": "pw-new-nurse-1",
                "staff_id": "STF-S902",
                "full_name": "New Nurse",
                "role": Staff.Role.NURSE,
                "ward": "Ward A",
            },
            format="json",
            **self._auth(token),
        )
        self.assertEqual(create_resp.status_code, status.HTTP_201_CREATED, create_resp.data)

        search_resp = self.client.get("/api/staff/?q=STF-S902", **self._auth(token))
        self.assertEqual(search_resp.status_code, status.HTTP_200_OK)
        self.assertEqual(len(search_resp.data), 1)
        self.assertEqual(search_resp.data[0]["staff_id"], "STF-S902")

    def test_admin_can_update_duty_and_ward(self):
        _admin, admin_token = self._login("adminApi2", "pw-staff-api-3", "STF-S903", Staff.Role.ADMIN)
        nurse, _token = self._login("nurseDutyApi", "pw-staff-api-4", "STF-S904", Staff.Role.NURSE, on_duty=False)

        resp = self.client.patch(
            f"/api/staff/{nurse.id}/duty/",
            {"ward": "Ward B", "on_duty": True},
            format="json",
            **self._auth(admin_token),
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        nurse.refresh_from_db()
        self.assertEqual(nurse.ward, "Ward B")
        self.assertTrue(nurse.on_duty)

    def test_deactivated_staff_cannot_log_in(self):
        _admin, admin_token = self._login("adminApi3", "pw-staff-api-5", "STF-S905", Staff.Role.ADMIN)
        clerk, _token = self._login("clerkDeactApi", "pw-staff-api-6", "STF-S906", Staff.Role.CLERK)

        deactivate_resp = self.client.post(
            f"/api/staff/{clerk.id}/deactivate/", **self._auth(admin_token)
        )
        self.assertEqual(deactivate_resp.status_code, status.HTTP_200_OK)
        self.assertFalse(deactivate_resp.data["account_active"])

        login_resp = self.client.post(
            "/api/access/login/",
            {"username": "clerkDeactApi", "password": "pw-staff-api-6", "device_id": "device-x", "device_type": "desktop"},
            format="json",
        )
        self.assertEqual(login_resp.status_code, status.HTTP_401_UNAUTHORIZED)

        reactivate_resp = self.client.post(
            f"/api/staff/{clerk.id}/reactivate/", **self._auth(admin_token)
        )
        self.assertTrue(reactivate_resp.data["account_active"])

        login_again_resp = self.client.post(
            "/api/access/login/",
            {"username": "clerkDeactApi", "password": "pw-staff-api-6", "device_id": "device-x", "device_type": "desktop"},
            format="json",
        )
        self.assertEqual(login_again_resp.status_code, status.HTTP_201_CREATED)
