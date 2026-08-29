from rest_framework import serializers

from .models import AccessDecision


class DecideRequestSerializer(serializers.Serializer):
    """Body for /api/scoring/decide/."""

    patient_id = serializers.IntegerField()


class EmergencyOverrideRequestSerializer(serializers.Serializer):
    """Body for /api/scoring/emergency-override/ (Break the Glass). `reason` is
    required -- an always-available, always-logged bypass with no justification text
    would make the resulting Ledger/Security Dashboard entries useless for audit.

    `reason_category` (added 2026-08-29) is a required, structured companion to the
    free-text reason -- selecting "cross_coverage" is itself what lets BTG through
    the off-duty+unconnected block (self-attested, permanently logged; see
    scoring.views.EmergencyOverrideView), not a system-verified check.
    """

    CROSS_COVERAGE = "cross_coverage"
    REASON_CATEGORY_CHOICES = [
        ("clinical_emergency", "Clinical emergency / direct patient care"),
        (CROSS_COVERAGE, "Cross-coverage (covering an unrostered shift)"),
        ("other", "Other"),
    ]

    patient_id = serializers.IntegerField()
    reason_category = serializers.ChoiceField(choices=REASON_CATEGORY_CHOICES)
    reason = serializers.CharField(min_length=10, trim_whitespace=True)


class DisasterModeActionSerializer(serializers.Serializer):
    """Body for /api/scoring/disaster-mode/activate/ and .../deactivate/ -- a
    hospital-wide switch, so a written reason is required either way."""

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
            "role_rule_path",
            "factor_breakdown",
        ]
        read_only_fields = fields
