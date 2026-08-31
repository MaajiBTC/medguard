from rest_framework import serializers

from .models import LedgerEntry


class LedgerEntrySerializer(serializers.ModelSerializer):
    """`session_token` is deliberately excluded: it's a live bearer credential for an
    active session while that session lasts, so it never belongs in a dashboard
    response -- it's stored on the entry only for internal correlation."""

    class Meta:
        model = LedgerEntry
        fields = [
            "sequence",
            "occurred_at",
            "event_type",
            "staff_id",
            "staff_full_name",
            "staff_role",
            "patient_hospital_number",
            "device_id",
            "details",
            "prev_hash",
            "entry_hash",
        ]
        read_only_fields = fields
