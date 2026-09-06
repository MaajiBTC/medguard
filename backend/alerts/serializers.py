from rest_framework import serializers

from .models import SecurityAlert


class SecurityAlertSerializer(serializers.ModelSerializer):
    acknowledged = serializers.BooleanField(read_only=True)

    class Meta:
        model = SecurityAlert
        fields = [
            "id",
            "alert_type",
            "staff_id",
            "staff_full_name",
            "staff_role",
            "patient_hospital_number",
            "details",
            "ledger_sequence",
            "raised_at",
            "acknowledged",
            "acknowledged_at",
            "acknowledged_by_staff_id",
            "acknowledgement_note",
        ]
        read_only_fields = fields


class AcknowledgeAlertSerializer(serializers.Serializer):
    """An acknowledgement note is optional -- the act of acknowledging is the
    record that matters; forcing text would just produce a lot of "ok"."""

    note = serializers.CharField(required=False, allow_blank=True, default="", max_length=2000)
