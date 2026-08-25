"""Patient / PatientAssignment model tests. See staff/tests.py docstring re: the
throwaway test database and CLAUDE.md's no-placeholder-data rule."""

from django.contrib.auth.models import User
from django.db import IntegrityError, transaction
from django.test import TestCase
from rest_framework import status
from rest_framework.test import APITestCase

from staff.models import Staff

from .models import Patient, PatientAssignment, PatientCategoryRecord


class PatientModelTests(TestCase):
    def test_create_patient(self):
        patient = Patient.objects.create(hospital_number="HN-0001", full_name="Test Patient", ward="Ward A")
        self.assertEqual(str(patient), "Test Patient (HN-0001)")

    def test_hospital_number_must_be_unique(self):
        Patient.objects.create(hospital_number="HN-DUP", full_name="A", ward="Ward A")
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Patient.objects.create(hospital_number="HN-DUP", full_name="B", ward="Ward B")


class PatientAssignmentModelTests(TestCase):
    def _make_staff(self, username, staff_id, role=Staff.Role.NURSE, ward="Ward A"):
        user = User.objects.create_user(username=username, password="test-pass-123")
        return Staff.objects.create(user=user, staff_id=staff_id, full_name=username, role=role, ward=ward)

    def test_active_assignment_created(self):
        patient = Patient.objects.create(hospital_number="HN-100", full_name="P", ward="Ward A")
        nurse = self._make_staff("nurse1", "STF-100")
        assignment = PatientAssignment.objects.create(
            patient=patient, staff=nurse, role_in_assignment=PatientAssignment.RoleInAssignment.NURSE
        )
        self.assertTrue(assignment.active)
        self.assertIsNotNone(assignment.assigned_at)

    def test_duplicate_active_assignment_blocked(self):
        patient = Patient.objects.create(hospital_number="HN-101", full_name="P", ward="Ward A")
        nurse = self._make_staff("nurse2", "STF-101")
        PatientAssignment.objects.create(
            patient=patient, staff=nurse, role_in_assignment=PatientAssignment.RoleInAssignment.NURSE
        )
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                PatientAssignment.objects.create(
                    patient=patient, staff=nurse, role_in_assignment=PatientAssignment.RoleInAssignment.NURSE
                )

    def test_multiple_active_assignments_same_patient_role_different_staff_allowed(self):
        """Shift coverage: two different nurses can both be actively assigned to the
        same patient at once."""
        patient = Patient.objects.create(hospital_number="HN-102", full_name="P", ward="Ward A")
        nurse_a = self._make_staff("nurse3", "STF-102")
        nurse_b = self._make_staff("nurse4", "STF-103")
        PatientAssignment.objects.create(patient=patient, staff=nurse_a, role_in_assignment="nurse")
        PatientAssignment.objects.create(patient=patient, staff=nurse_b, role_in_assignment="nurse")
        self.assertEqual(patient.assignments.filter(active=True).count(), 2)

    def test_reactivating_after_deactivation_allowed(self):
        patient = Patient.objects.create(hospital_number="HN-103", full_name="P", ward="Ward A")
        nurse = self._make_staff("nurse5", "STF-104")
        first = PatientAssignment.objects.create(patient=patient, staff=nurse, role_in_assignment="nurse")
        first.active = False
        first.save(update_fields=["active"])
        second = PatientAssignment.objects.create(patient=patient, staff=nurse, role_in_assignment="nurse")
        self.assertTrue(second.active)

    def test_doctor_and_nurse_can_both_be_assigned_to_same_patient(self):
        patient = Patient.objects.create(hospital_number="HN-104", full_name="P", ward="Ward A")
        doctor = self._make_staff("doc1", "STF-105", role=Staff.Role.DOCTOR)
        nurse = self._make_staff("nurse6", "STF-106", role=Staff.Role.NURSE)
        PatientAssignment.objects.create(patient=patient, staff=doctor, role_in_assignment="doctor")
        PatientAssignment.objects.create(patient=patient, staff=nurse, role_in_assignment="nurse")
        self.assertEqual(patient.assignments.filter(active=True).count(), 2)


class PatientApiTests(APITestCase):
    """Patient search/create/ward/category/assignment endpoints (patients/views.py)."""

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

    def test_any_authenticated_staff_can_search_patients(self):
        Patient.objects.create(hospital_number="HN-P900", full_name="Search Target", ward="Ward A")
        _staff, token = self._login("clerkSearchApi", "pw-patient-api-1", "STF-P900", Staff.Role.CLERK)

        resp = self.client.get("/api/patients/?q=HN-P900", **self._auth(token))
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(len(resp.data), 1)
        self.assertEqual(resp.data[0]["hospital_number"], "HN-P900")

    def test_non_admin_cannot_create_patient(self):
        _staff, token = self._login("clerkCreateApi", "pw-patient-api-2", "STF-P901", Staff.Role.CLERK)
        resp = self.client.post(
            "/api/patients/create/",
            {"hospital_number": "HN-P901", "full_name": "Blocked", "ward": "Ward A"},
            format="json",
            **self._auth(token),
        )
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)

    def test_admin_create_patient_auto_creates_thirteen_category_rows(self):
        _admin, token = self._login("adminPatientApi1", "pw-patient-api-3", "STF-P902", Staff.Role.ADMIN)
        resp = self.client.post(
            "/api/patients/create/",
            {"hospital_number": "HN-P902", "full_name": "New Patient", "ward": "Ward A"},
            format="json",
            **self._auth(token),
        )
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED, resp.data)
        patient = Patient.objects.get(hospital_number="HN-P902")
        self.assertEqual(patient.category_records.count(), 13)
        self.assertEqual(
            set(patient.category_records.values_list("category", flat=True)),
            set(range(1, 14)),
        )

    def test_admin_can_update_patient_ward_and_category_content(self):
        _admin, token = self._login("adminPatientApi2", "pw-patient-api-4", "STF-P903", Staff.Role.ADMIN)
        patient = Patient.objects.create(hospital_number="HN-P903", full_name="P", ward="Ward A")
        PatientCategoryRecord.objects.bulk_create(
            PatientCategoryRecord(patient=patient, category=c) for c, _ in PatientCategoryRecord.Category.choices
        )

        ward_resp = self.client.patch(
            f"/api/patients/{patient.id}/ward/", {"ward": "Ward C"}, format="json", **self._auth(token)
        )
        self.assertEqual(ward_resp.status_code, status.HTTP_200_OK)
        patient.refresh_from_db()
        self.assertEqual(patient.ward, "Ward C")

        content_resp = self.client.patch(
            f"/api/patients/{patient.id}/records/6/",
            {"content": {"notes": "Penicillin allergy"}},
            format="json",
            **self._auth(token),
        )
        self.assertEqual(content_resp.status_code, status.HTTP_200_OK)
        record = PatientCategoryRecord.objects.get(patient=patient, category=6)
        self.assertEqual(record.content, {"notes": "Penicillin allergy"})

    def test_admin_can_assign_and_deactivate_doctor_and_nurse(self):
        _admin, admin_token = self._login("adminPatientApi3", "pw-patient-api-5", "STF-P904", Staff.Role.ADMIN)
        doctor, _t = self._login("docAssignApi", "pw-patient-api-6", "STF-P905", Staff.Role.DOCTOR)
        nurse, _t2 = self._login("nurseAssignApi", "pw-patient-api-7", "STF-P906", Staff.Role.NURSE)
        patient = Patient.objects.create(hospital_number="HN-P904", full_name="P", ward="Ward A")

        doc_resp = self.client.post(
            f"/api/patients/{patient.id}/assignments/",
            {"staff_id": doctor.staff_id, "role_in_assignment": "doctor"},
            format="json",
            **self._auth(admin_token),
        )
        self.assertEqual(doc_resp.status_code, status.HTTP_201_CREATED, doc_resp.data)

        nurse_resp = self.client.post(
            f"/api/patients/{patient.id}/assignments/",
            {"staff_id": nurse.staff_id, "role_in_assignment": "nurse"},
            format="json",
            **self._auth(admin_token),
        )
        self.assertEqual(nurse_resp.status_code, status.HTTP_201_CREATED, nurse_resp.data)

        list_resp = self.client.get(f"/api/patients/{patient.id}/assignments/", **self._auth(admin_token))
        self.assertEqual(len(list_resp.data), 2)

        deactivate_resp = self.client.delete(
            f"/api/patients/{patient.id}/assignments/{doc_resp.data['id']}/", **self._auth(admin_token)
        )
        self.assertEqual(deactivate_resp.status_code, status.HTTP_204_NO_CONTENT)
        self.assertEqual(
            PatientAssignment.objects.filter(patient=patient, active=True).count(), 1
        )

    def test_assigned_to_me_returns_only_this_staff_members_active_assignments(self):
        doctor, doc_token = self._login("docAssignedApi", "pw-patient-api-8", "STF-P907", Staff.Role.DOCTOR)
        other_doctor, _t = self._login("otherDocAssignedApi", "pw-patient-api-9", "STF-P908", Staff.Role.DOCTOR)
        patient_mine = Patient.objects.create(hospital_number="HN-P905", full_name="Mine", ward="Ward A")
        patient_other = Patient.objects.create(hospital_number="HN-P906", full_name="Other", ward="Ward A")
        PatientAssignment.objects.create(patient=patient_mine, staff=doctor, role_in_assignment="doctor")
        PatientAssignment.objects.create(patient=patient_other, staff=other_doctor, role_in_assignment="doctor")

        resp = self.client.get("/api/patients/assigned-to-me/", **self._auth(doc_token))
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(len(resp.data), 1)
        self.assertEqual(resp.data[0]["hospital_number"], "HN-P905")

    def test_assigned_to_me_empty_for_role_with_no_assignment_concept(self):
        _staff, token = self._login("clerkAssignedApi", "pw-patient-api-10", "STF-P909", Staff.Role.CLERK)
        resp = self.client.get("/api/patients/assigned-to-me/", **self._auth(token))
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data, [])
