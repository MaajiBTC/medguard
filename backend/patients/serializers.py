from rest_framework import serializers

from staff.models import Ward

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

    class Meta:
        model = PatientCategoryRecord
        fields = ["category", "category_name", "content", "updated_at"]
        read_only_fields = ["category", "category_name", "updated_at"]


class PatientCategoryContentUpdateSerializer(serializers.Serializer):
    content = serializers.JSONField()


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
    patient's own summary fields plus which role this assignment is under."""

    patient_id = serializers.IntegerField(source="patient.id", read_only=True)
    hospital_number = serializers.CharField(source="patient.hospital_number", read_only=True)
    full_name = serializers.CharField(source="patient.full_name", read_only=True)
    ward = serializers.CharField(source="patient.ward", read_only=True)

    class Meta:
        model = PatientAssignment
        fields = ["patient_id", "hospital_number", "full_name", "ward", "role_in_assignment", "assigned_at"]
        read_only_fields = fields
