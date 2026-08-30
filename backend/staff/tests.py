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

from .models import Staff, Ward


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

    def test_four_wards_are_valid_choices(self):
        expected = {"general_male", "general_female", "surgical", "emergency"}
        actual = {value for value, _label in Ward.choices}
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
                "ward": Ward.GENERAL_MALE,
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
            {"ward": Ward.SURGICAL, "on_duty": True},
            format="json",
            **self._auth(admin_token),
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        nurse.refresh_from_db()
        self.assertEqual(nurse.ward, Ward.SURGICAL)
        self.assertTrue(nurse.on_duty)

    def test_admin_can_update_on_call(self):
        _admin, admin_token = self._login("adminApi4", "pw-staff-api-7", "STF-S907", Staff.Role.ADMIN)
        doctor, _token = self._login("docOnCallApi", "pw-staff-api-8", "STF-S908", Staff.Role.DOCTOR, on_duty=False)
        self.assertFalse(doctor.on_call)

        resp = self.client.patch(
            f"/api/staff/{doctor.id}/duty/",
            {"on_call": True},
            format="json",
            **self._auth(admin_token),
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertTrue(resp.data["on_call"])
        doctor.refresh_from_db()
        self.assertTrue(doctor.on_call)

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

    def test_invalid_ward_rejected_on_create(self):
        _admin, token = self._login("adminApi5", "pw-staff-api-9", "STF-S909", Staff.Role.ADMIN)
        resp = self.client.post(
            "/api/staff/create/",
            {
                "username": "badWardNurse",
                "password": "pw-bad-ward-1",
                "staff_id": "STF-S910",
                "full_name": "Bad Ward Nurse",
                "role": Staff.Role.NURSE,
                "ward": "Ward A",
            },
            format="json",
            **self._auth(token),
        )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_invalid_ward_rejected_on_duty_update(self):
        _admin, admin_token = self._login("adminApi6", "pw-staff-api-10", "STF-S911", Staff.Role.ADMIN)
        nurse, _token = self._login("nurseBadWardApi", "pw-staff-api-11", "STF-S912", Staff.Role.NURSE)
        resp = self.client.patch(
            f"/api/staff/{nurse.id}/duty/",
            {"ward": "Ward A"},
            format="json",
            **self._auth(admin_token),
        )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_search_filters_by_role(self):
        _admin, token = self._login("adminApi7", "pw-staff-api-12", "STF-S913", Staff.Role.ADMIN)
        self._login("doctorRoleFilterApi", "pw-staff-api-13", "STF-S914", Staff.Role.DOCTOR)
        self._login("nurseRoleFilterApi", "pw-staff-api-14", "STF-S915", Staff.Role.NURSE)

        resp = self.client.get("/api/staff/?role=doctor", **self._auth(token))
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        staff_ids = {row["staff_id"] for row in resp.data}
        self.assertIn("STF-S914", staff_ids)
        self.assertNotIn("STF-S915", staff_ids)

    def test_summary_counts(self):
        _admin, token = self._login("adminApi8", "pw-staff-api-15", "STF-S916", Staff.Role.ADMIN)
        doctor1, _t = self._login("doctorSummaryApi1", "pw-staff-api-16", "STF-S917", Staff.Role.DOCTOR, on_duty=True)
        self._login("doctorSummaryApi2", "pw-staff-api-17", "STF-S918", Staff.Role.DOCTOR, on_duty=False)
        self._login("nurseSummaryApi1", "pw-staff-api-19", "STF-S920", Staff.Role.NURSE, on_duty=True)
        doctor1.on_call = True
        doctor1.save(update_fields=["on_call"])

        resp = self.client.get("/api/staff/summary/", **self._auth(token))
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data["total"], 4)  # admin + 2 doctors + 1 nurse
        self.assertEqual(resp.data["on_duty"], 3)  # admin (default True) + doctor1 + nurse1
        self.assertEqual(resp.data["on_call"], 1)  # doctor1
        self.assertEqual(resp.data["by_role"]["doctor"], 2)
        self.assertEqual(resp.data["by_role"]["nurse"], 1)
        self.assertEqual(resp.data["on_duty_by_role"]["doctor"], 1)
        self.assertEqual(resp.data["on_duty_by_role"]["nurse"], 1)
        self.assertEqual(resp.data["on_duty_by_role"]["pharmacist"], 0)
        self.assertNotIn("admin", resp.data["on_duty_by_role"])

    def test_non_admin_cannot_read_summary(self):
        _staff, token = self._login("docSummaryDeniedApi", "pw-staff-api-18", "STF-S919", Staff.Role.DOCTOR)
        resp = self.client.get("/api/staff/summary/", **self._auth(token))
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)

    def test_admin_cannot_create_another_admin(self):
        _admin, token = self._login("adminApi9", "pw-staff-api-19", "STF-S920", Staff.Role.ADMIN)
        resp = self.client.post(
            "/api/staff/create/",
            {
                "username": "secondAdminApi",
                "password": "pw-second-admin-1",
                "staff_id": "STF-S921",
                "full_name": "Second Admin",
                "role": Staff.Role.ADMIN,
            },
            format="json",
            **self._auth(token),
        )
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)

    def test_security_officer_can_create_admin(self):
        _officer, token = self._login("secOfficerApi1", "pw-staff-api-20", "STF-S922", Staff.Role.SECURITY_OFFICER)
        resp = self.client.post(
            "/api/staff/create/",
            {
                "username": "adminFromSecurityApi",
                "password": "pw-admin-from-sec-1",
                "staff_id": "STF-S923",
                "full_name": "Admin From Security",
                "role": Staff.Role.ADMIN,
            },
            format="json",
            **self._auth(token),
        )
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED, resp.data)

    def test_security_officer_cannot_create_non_admin_role(self):
        _officer, token = self._login("secOfficerApi2", "pw-staff-api-21", "STF-S924", Staff.Role.SECURITY_OFFICER)
        resp = self.client.post(
            "/api/staff/create/",
            {
                "username": "nurseFromSecurityApi",
                "password": "pw-nurse-from-sec-1",
                "staff_id": "STF-S925",
                "full_name": "Blocked Nurse",
                "role": Staff.Role.NURSE,
            },
            format="json",
            **self._auth(token),
        )
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)

    def test_clinical_staff_cannot_create_staff(self):
        _doctor, token = self._login("docCreateDeniedApi", "pw-staff-api-22", "STF-S926", Staff.Role.DOCTOR)
        resp = self.client.post(
            "/api/staff/create/",
            {
                "username": "blockedCreateApi",
                "password": "pw-blocked-create-1",
                "staff_id": "STF-S927",
                "full_name": "Blocked",
                "role": Staff.Role.CLERK,
            },
            format="json",
            **self._auth(token),
        )
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)

    def test_ward_duty_call_forced_blank_for_admin_and_security_officer(self):
        _admin, token = self._login("adminApi10", "pw-staff-api-23", "STF-S928", Staff.Role.ADMIN)
        resp = self.client.post(
            "/api/staff/create/",
            {
                "username": "secWithWardApi",
                "password": "pw-sec-ward-1",
                "staff_id": "STF-S929",
                "full_name": "Security With Attempted Ward",
                "role": Staff.Role.SECURITY_OFFICER,
                "ward": Ward.EMERGENCY,
                "on_duty": True,
                "on_call": True,
            },
            format="json",
            **self._auth(token),
        )
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED, resp.data)
        created = Staff.objects.get(staff_id="STF-S929")
        self.assertEqual(created.ward, "")
        self.assertFalse(created.on_duty)
        self.assertFalse(created.on_call)

    def test_duty_ward_update_rejected_for_admin_and_security_officer(self):
        _admin, admin_token = self._login("adminApi11", "pw-staff-api-24", "STF-S930", Staff.Role.ADMIN)
        officer, _t = self._login("secOfficerApi3", "pw-staff-api-25", "STF-S931", Staff.Role.SECURITY_OFFICER)
        resp = self.client.patch(
            f"/api/staff/{officer.id}/duty/",
            {"on_duty": True},
            format="json",
            **self._auth(admin_token),
        )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
