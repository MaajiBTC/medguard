from rest_framework import serializers

from .models import AccessDecision, StepUpAssistRequest


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


class StepUpAssistRequestSerializer(serializers.ModelSerializer):
    """A colleague-vouches request (added 2026-09-06), as seen by the
    approving colleague: enough context (who's asking, for which patient) to
    make a real judgment call rather than a blind click."""

    requesting_staff_id = serializers.CharField(source="requesting_staff.staff_id", read_only=True)
    requesting_staff_name = serializers.CharField(source="requesting_staff.full_name", read_only=True)
    requesting_staff_role = serializers.CharField(source="requesting_staff.role", read_only=True)
    patient_hospital_number = serializers.CharField(
        source="decision.patient.hospital_number", read_only=True
    )
    resolved_by_staff_id = serializers.CharField(
        source="resolved_by.staff_id", read_only=True, default=""
    )

    class Meta:
        model = StepUpAssistRequest
        fields = [
            "id",
            "decision",
            "status",
            "requesting_staff_id",
            "requesting_staff_name",
            "requesting_staff_role",
            "patient_hospital_number",
            "resolved_by_staff_id",
            "requested_at",
            "resolved_at",
        ]
        read_only_fields = fields


class StepUpAssistRequestOwnSerializer(StepUpAssistRequestSerializer):
    """The same request, as seen by the REQUESTER who created it (added
    2026-09-17) -- adds verification_code, which the shared-queue serializer
    above deliberately never exposes. Used only by
    StepUpAssistRequestView.post()'s own response; never returned to the
    colleague who'll be asked to type this code in."""

    class Meta(StepUpAssistRequestSerializer.Meta):
        fields = StepUpAssistRequestSerializer.Meta.fields + ["verification_code"]
        read_only_fields = fields


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
            "step_up_verified",
            "step_up_required",
        ]
        read_only_fields = fields

    # Added 2026-09-06 -- lets the clinical dashboard know, straight off the
    # decide response, whether it must show the PIN challenge before it can
    # fetch records (the backend enforces this too -- see PatientRecordView).
    step_up_required = serializers.SerializerMethodField()

    def get_step_up_required(self, obj):
        return (
            obj.decision_type == AccessDecision.DecisionType.REDUCED_ACCESS
            and not obj.step_up_verified
        )
