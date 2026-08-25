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

    def test_all_five_roles_from_claude_md_are_valid_choices(self):
        expected = {"doctor", "nurse", "pharmacist", "lab_technician", "clerk"}
        actual = {value for value, _label in Staff.Role.choices}
        self.assertEqual(expected, actual)
