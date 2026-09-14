from rest_framework import serializers

from ledger.models import LedgerEntry


class OfflineSyncEntrySerializer(serializers.Serializer):
    client_seq = serializers.IntegerField(min_value=1)
    occurred_at = serializers.DateTimeField()
    event_type = serializers.ChoiceField(choices=LedgerEntry.EventType.choices)
    patient_hospital_number = serializers.CharField(allow_blank=True, default="")
    details = serializers.JSONField(default=dict)
    prev_local_hash = serializers.CharField()
    entry_local_hash = serializers.CharField()


class OfflineSyncRequestSerializer(serializers.Serializer):
    device_id = serializers.CharField(max_length=255)
    batch_id = serializers.UUIDField()
    signature = serializers.CharField()
    entries = OfflineSyncEntrySerializer(many=True, allow_empty=False)
