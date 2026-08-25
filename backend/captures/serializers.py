from rest_framework import serializers

from .models import BehavioralCapture, ContextualCapture


class KeystrokeFeaturesSerializer(serializers.Serializer):
    """Derived, anonymized keystroke-dynamics features — never raw key identity.
    Computed client-side (see frontend/src/capture/behavioral/keystrokeFeatures.js)
    from flight/digraph/trigraph timing indexed by keystroke position, never by
    which character was pressed. See CLAUDE.md's Behavioral Signal Capture Module
    section (revised 2026-08-25)."""

    flight_times = serializers.ListField(child=serializers.FloatField(), default=list)
    digraph_latencies = serializers.ListField(child=serializers.FloatField(), default=list)
    trigraph_latencies = serializers.ListField(child=serializers.FloatField(), default=list)
    error_correction_rate = serializers.FloatField(default=0)
    rhythm_consistency = serializers.FloatField(default=0)
    automation_flags = serializers.ListField(child=serializers.CharField(max_length=64), default=list)


class MouseEventSerializer(serializers.Serializer):
    """Shape: {event, x, y, button?, t}."""

    event = serializers.ChoiceField(choices=["mousemove", "mousedown", "mouseup"])
    x = serializers.FloatField()
    y = serializers.FloatField()
    button = serializers.IntegerField(required=False, allow_null=True)
    t = serializers.FloatField()


class TouchEventSerializer(serializers.Serializer):
    """Shape: {event, x, y, pressure?, contact_size?, touch_id?, t}."""

    event = serializers.ChoiceField(choices=["touchstart", "touchmove", "touchend"])
    x = serializers.FloatField()
    y = serializers.FloatField()
    pressure = serializers.FloatField(required=False, allow_null=True)
    contact_size = serializers.FloatField(required=False, allow_null=True)
    touch_id = serializers.IntegerField(required=False, allow_null=True)
    t = serializers.FloatField()


class BehavioralEventBatchSerializer(serializers.Serializer):
    """Validates a batch POSTed to /api/captures/behavioral/events/. Any of the three
    families may be omitted (defaults to empty) — a touch device won't send mouse
    events and vice versa."""

    keystroke_features = KeystrokeFeaturesSerializer(required=False)
    mouse_events = MouseEventSerializer(many=True, required=False, default=list)
    touch_events = TouchEventSerializer(many=True, required=False, default=list)

    def validate(self, attrs):
        if not attrs.get("keystroke_features") and not attrs.get("mouse_events") and not attrs.get("touch_events"):
            raise serializers.ValidationError("At least one of keystroke_features, mouse_events, touch_events is required.")
        return attrs


class BehavioralCaptureSerializer(serializers.ModelSerializer):
    class Meta:
        model = BehavioralCapture
        fields = [
            "id",
            "session",
            "keystroke_features",
            "mouse_events",
            "touch_events",
            "mouse_event_count",
            "touch_event_count",
            "updated_at",
        ]
        read_only_fields = fields


class TargetPatientSerializer(serializers.Serializer):
    """Body for /api/captures/contextual/target-patient/."""

    patient_id = serializers.IntegerField()


class ContextualCaptureSerializer(serializers.ModelSerializer):
    """Flattened debug view — pulls login timestamp/device/network off the related
    AccessSession rather than duplicating that data on this model."""

    started_at = serializers.DateTimeField(source="session.started_at", read_only=True)
    device_id = serializers.CharField(source="session.device_id", read_only=True)
    device_type = serializers.CharField(source="session.device_type", read_only=True)
    network_segment = serializers.CharField(source="session.network_segment", read_only=True)
    target_patient_id = serializers.SerializerMethodField()
    target_patient_hospital_number = serializers.SerializerMethodField()

    def get_target_patient_id(self, obj):
        # obj.target_patient_id avoids an extra query and is None when unset,
        # unlike dotted-source lookups through a null FK (which DRF would skip).
        return obj.target_patient_id

    def get_target_patient_hospital_number(self, obj):
        return obj.target_patient.hospital_number if obj.target_patient_id else None

    class Meta:
        model = ContextualCapture
        fields = [
            "id",
            "session",
            "started_at",
            "device_id",
            "device_type",
            "network_segment",
            "on_duty_at_login",
            "ward_assignment_at_login",
            "target_patient_id",
            "target_patient_hospital_number",
            "patient_assignment_status",
            "patient_assignment_checked_at",
        ]
        read_only_fields = fields
