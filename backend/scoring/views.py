from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from ledger.services import record_event
from patients.models import Patient, PatientCategoryRecord
from patients.serializers import PatientCategoryRecordSerializer
from staff.permissions import IsClinicalStaff

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

    Admin/security officer sessions are rejected (403) -- patient-record access is not
    applicable to those roles, this isn't just an unenforced convention.
    """

    permission_classes = [IsClinicalStaff]

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


class PatientRecordView(APIView):
    """GET /api/scoring/patients/<patient_id>/records/

    Lives in the scoring app (not patients) because it reads AccessDecision -- keeping
    the dependency direction the same one-way order settings.py documents (patients is
    upstream of scoring; scoring may import patients, never the reverse). Returns the
    caller's own most recent decision's granted categories, actual content included --
    the client never supplies which categories it wants, only which patient.
    """

    permission_classes = [IsClinicalStaff]

    def get(self, request, patient_id):
        session = request.auth
        decision = (
            AccessDecision.objects.filter(session=session, patient_id=patient_id)
            .order_by("-computed_at")
            .first()
        )
        if decision is None:
            return Response(
                {
                    "detail": (
                        "No access decision found for this session/patient. Call "
                        "/api/scoring/decide/ with this patient_id first."
                    )
                },
                status=status.HTTP_404_NOT_FOUND,
            )

        if decision.decision_type == AccessDecision.DecisionType.ACCESS_DENIED:
            return Response(
                {
                    "detail": "Access denied.",
                    "score": decision.score,
                    "score_band": decision.score_band,
                },
                status=status.HTTP_403_FORBIDDEN,
            )

        records = PatientCategoryRecord.objects.filter(
            patient_id=patient_id, category__in=decision.granted_categories
        )
        return Response(
            {
                "decision_type": decision.decision_type,
                "score": decision.score,
                "score_band": decision.score_band,
                "granted_categories": decision.granted_categories,
                "records": PatientCategoryRecordSerializer(records, many=True).data,
            }
        )
