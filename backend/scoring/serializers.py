from rest_framework import serializers

from .models import AccessDecision


class DecideRequestSerializer(serializers.Serializer):
    """Body for /api/scoring/decide/."""

    patient_id = serializers.IntegerField()


class EmergencyOverrideRequestSerializer(serializers.Serializer):
    """Body for /api/scoring/emergency-override/ (Break the Glass). `reason` is
    required -- an always-available, always-logged bypass with no justification text
    would make the resulting Ledger/Security Dashboard entries useless for audit."""

    patient_id = serializers.IntegerField()
    reason = serializers.CharField(min_length=10, trim_whitespace=True)


class AccessDecisionSerializer(serializers.ModelSerializer):
    class Meta:
        model = AccessDecision
        fields = [
            "id",
            "session",
            "patient",
            "computed_at",
            "gate_passed",
            "score",
            "score_band",
            "decision_type",
            "granted_categories",
            "nurse_path",
            "factor_breakdown",
        ]
        read_only_fields = fields
