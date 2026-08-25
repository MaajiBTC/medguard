"""Patient / PatientAssignment model tests. See staff/tests.py docstring re: the
throwaway test database and CLAUDE.md's no-placeholder-data rule."""

from django.contrib.auth.models import User
from django.db import IntegrityError, transaction
from django.test import TestCase

from staff.models import Staff

from .models import Patient, PatientAssignment


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
