from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from ledger.services import record_event
from patients.models import Patient

from .baseline import update_baseline
from .engine import compute_access_decision
from .models import AccessDecision, BehavioralBaseline
from .serializers import AccessDecisionSerializer, DecideRequestSerializer


class DecideView(APIView):
    """POST /api/scoring/decide/ -- {patient_id}

    Requires the caller already set the target patient via
    /api/captures/contextual/target-patient/ (reads the ContextualCapture's already-
    computed patient_assignment_status rather than recomputing it -- that factual
    lookup lives in exactly one place, the captures app, per CLAUDE.md's module
    boundaries). Computes the access decision, updates the staff member's rolling
    behavioral baseline for any non-denied outcome, writes the decision to the
    Security Ledger (every decision, including denials -- CLAUDE.md), and returns the
    decision.

    The ledger write is unguarded: if it fails, the exception propagates into a 500 and
    the caller never receives a decision that wasn't also logged (fail-closed -- an
    unaudited access grant is worse than a temporary outage).
    """

    def post(self, request):
        serializer = DecideRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        patient_id = serializer.validated_data["patient_id"]

        session = request.auth
        contextual = session.contextual_capture

        if contextual.target_patient_id != patient_id:
            return Response(
                {
                    "detail": (
                        "Target patient not set for this session. Call "
                        "/api/captures/contextual/target-patient/ with this patient_id first."
                    )
                },
                status=status.HTTP_409_CONFLICT,
            )

        patient = get_object_or_404(Patient, pk=patient_id)
        decision = compute_access_decision(session, patient)

        if decision.decision_type != AccessDecision.DecisionType.ACCESS_DENIED:
            baseline, _ = BehavioralBaseline.objects.get_or_create(staff=session.staff)
            update_baseline(baseline, session)

        record_event(
            event_type=decision.decision_type,
            staff=session.staff,
            patient=patient,
            session=session,
            details={
                "gate_passed": decision.gate_passed,
                "score": decision.score,
                "score_band": decision.score_band,
                "granted_categories": decision.granted_categories,
                "nurse_path": decision.nurse_path,
                "factor_breakdown": decision.factor_breakdown,
            },
        )

        return Response(AccessDecisionSerializer(decision).data, status=status.HTTP_201_CREATED)
