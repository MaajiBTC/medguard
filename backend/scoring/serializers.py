from rest_framework import serializers

from .models import AccessDecision


class DecideRequestSerializer(serializers.Serializer):
    """Body for /api/scoring/decide/."""

    patient_id = serializers.IntegerField()


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
