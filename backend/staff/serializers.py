from django.contrib.auth import get_user_model
from rest_framework import serializers

from .models import Staff, Ward


class StaffSummarySerializer(serializers.ModelSerializer):
    username = serializers.CharField(source="user.username", read_only=True)
    account_active = serializers.BooleanField(source="user.is_active", read_only=True)

    class Meta:
        model = Staff
        fields = ["id", "staff_id", "full_name", "role", "ward", "on_duty", "on_call", "username", "account_active"]
        read_only_fields = fields


class StaffCreateSerializer(serializers.Serializer):
    """Body for POST /api/staff/create/ -- creates the auth.User + Staff row
    together, mirroring staff/management/commands/create_staff_account.py's pattern.
    Real staff data the admin types in, never generated."""

    username = serializers.CharField(max_length=150)
    password = serializers.CharField(write_only=True, min_length=8)
    staff_id = serializers.CharField(max_length=64)
    full_name = serializers.CharField(max_length=255)
    role = serializers.ChoiceField(choices=Staff.Role.choices)
    ward = serializers.ChoiceField(choices=Ward.choices, required=False, allow_blank=True, default="")
    on_duty = serializers.BooleanField(required=False, default=False)
    on_call = serializers.BooleanField(required=False, default=False)

    def validate_username(self, value):
        if get_user_model().objects.filter(username=value).exists():
            raise serializers.ValidationError("A user with this username already exists.")
        return value

    def validate_staff_id(self, value):
        if Staff.objects.filter(staff_id=value).exists():
            raise serializers.ValidationError("A staff member with this staff_id already exists.")
        return value


class StaffDutyWardUpdateSerializer(serializers.Serializer):
    ward = serializers.ChoiceField(choices=Ward.choices, required=False, allow_blank=True)
    on_duty = serializers.BooleanField(required=False)
    on_call = serializers.BooleanField(required=False)

    def validate(self, attrs):
        if not attrs:
            raise serializers.ValidationError("Provide at least one of: ward, on_duty, on_call.")
        return attrs
