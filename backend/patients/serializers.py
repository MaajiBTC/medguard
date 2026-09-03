from rest_framework import serializers

from staff.models import Ward

from .category_fields import CATEGORY_FIELDS
from .models import Patient, PatientAssignment, PatientCategoryRecord


class PatientSummarySerializer(serializers.ModelSerializer):
    """Search-result shape -- identifiers only, never category content."""

    class Meta:
        model = Patient
        fields = ["id", "hospital_number", "full_name", "ward"]
        read_only_fields = fields


class PatientCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = Patient
        fields = ["hospital_number", "full_name", "ward"]


class PatientWardUpdateSerializer(serializers.Serializer):
    ward = serializers.ChoiceField(choices=Ward.choices, allow_blank=True)


class PatientCategoryRecordSerializer(serializers.ModelSerializer):
    category_name = serializers.CharField(source="get_category_display", read_only=True)
    # Named field_defs, not "fields" -- that name collides with DRF's own
    # Serializer.fields property. Backend-owned single source of truth (see
    # category_fields.py) so the frontend renders its form purely from what
    # this sends, with no per-category schema duplicated in JS.
    field_defs = serializers.SerializerMethodField()

    class Meta:
        model = PatientCategoryRecord
        fields = ["category", "category_name", "field_defs", "content", "updated_at"]
        read_only_fields = ["category", "category_name", "field_defs", "updated_at"]

    def get_field_defs(self, obj):
        return CATEGORY_FIELDS.get(obj.category, [])


class PatientCategoryContentUpdateSerializer(serializers.Serializer):
    content = serializers.JSONField()

    def validate_content(self, value):
        category = self.context.get("category")
        if not isinstance(value, dict):
            raise serializers.ValidationError("content must be an object.")
        valid_names = {f["name"] for f in CATEGORY_FIELDS.get(category, [])}
        unknown = set(value.keys()) - valid_names
        if unknown:
            raise serializers.ValidationError(
                f"Unknown field(s) for this category: {', '.join(sorted(unknown))}"
            )
        for key, val in value.items():
            if val is not None and not isinstance(val, str):
                raise serializers.ValidationError(f"Field '{key}' must be a string.")
        return value


class PatientAssignmentCreateSerializer(serializers.Serializer):
    staff_id = serializers.CharField(max_length=64)
    role_in_assignment = serializers.ChoiceField(choices=PatientAssignment.RoleInAssignment.choices)


class PatientAssignmentSerializer(serializers.ModelSerializer):
    staff_id = serializers.CharField(source="staff.staff_id", read_only=True)
    staff_full_name = serializers.CharField(source="staff.full_name", read_only=True)

    class Meta:
        model = PatientAssignment
        fields = ["id", "staff_id", "staff_full_name", "role_in_assignment", "assigned_at", "active"]
        read_only_fields = fields


class AssignedPatientSerializer(serializers.ModelSerializer):
    """One row from PatientAssignment, shaped for 'my assigned patients' -- the
    patient's own summary fields plus which role this assignment is under.
    Also reused by StaffAssignmentsView (admin-only, Admin dashboard's Staff
    panel) -- `id` is included for that caller to build the deactivate URL
    (/api/patients/<patient_id>/assignments/<id>/); MyAssignedPatientsView's
    caller (the clinical dashboard, no unassign action there) just ignores it."""

    patient_id = serializers.IntegerField(source="patient.id", read_only=True)
    hospital_number = serializers.CharField(source="patient.hospital_number", read_only=True)
    full_name = serializers.CharField(source="patient.full_name", read_only=True)
    ward = serializers.CharField(source="patient.ward", read_only=True)

    class Meta:
        model = PatientAssignment
        fields = ["id", "patient_id", "hospital_number", "full_name", "ward", "role_in_assignment", "assigned_at"]
        read_only_fields = fields
