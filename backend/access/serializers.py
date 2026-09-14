from rest_framework import serializers

from .models import Device, PendingDeviceRequest


class ChangePasswordSerializer(serializers.Serializer):
    current_password = serializers.CharField(write_only=True)
    new_password = serializers.CharField(write_only=True, min_length=8)


class DeviceSerializer(serializers.ModelSerializer):
    class Meta:
        model = Device
        fields = ["id", "device_type", "user_agent", "is_primary", "approved_at", "last_seen_at"]


class RegisterSyncKeySerializer(serializers.Serializer):
    device_id = serializers.CharField(max_length=255)
    public_key = serializers.CharField()


class PendingDeviceRequestSerializer(serializers.ModelSerializer):
    """Deliberately excludes poll_token/session_token -- this is what the account
    owner's own Devices panel sees, and neither value is theirs to know: poll_token
    identifies the *requesting* device's own poll session, session_token is a live
    bearer credential."""

    class Meta:
        model = PendingDeviceRequest
        fields = ["id", "device_type", "user_agent", "requested_at"]
