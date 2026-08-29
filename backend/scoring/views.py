from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from captures.models import ContextualCapture
from captures.services import compute_patient_assignment_status
from ledger.models import LedgerEntry
from ledger.services import record_event
from patients.models import Patient, PatientCategoryRecord
from patients.serializers import PatientCategoryRecordSerializer
from staff.permissions import IsClinicalStaff

from .baseline import update_baseline
from .engine import ROLE_CEILINGS, compute_access_decision
from .models import AccessDecision, BehavioralBaseline
from .serializers import (
    AccessDecisionSerializer,
    DecideRequestSerializer,
    EmergencyOverrideRequestSerializer,
)


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
                "role_rule_path": decision.role_rule_path,
                "factor_breakdown": decision.factor_breakdown,
            },
        )

        return Response(AccessDecisionSerializer(decision).data, status=status.HTTP_201_CREATED)


class EmergencyOverrideView(APIView):
    """POST /api/scoring/emergency-override/ -- {patient_id, reason}

    "Break the Glass": available regardless of score or role-match (CLAUDE.md
    Emergency Override), for the exact situation scoring/engine.py's Nurse rule
    comment already calls out -- e.g. a nurse who is neither assigned to the patient
    nor on their ward has no other path to access at all.

    Requires the caller to already be logged in and authenticated (same
    AccessSessionAuthentication/IsClinicalStaff boundary as DecideView -- BTG is not a
    way around login, only around the scoring pipeline) and still respects the role
    ceiling table (ROLE_CEILINGS) -- it bypasses the hard behavioral gate, the score
    band, and the Nurse rule's assignment/ward matching, but a clerk invoking this
    still only gets categories 1-2, never the full 13.

    Not unconditional, though (user request, 2026-08-29): it is blocked for a doctor
    or nurse who is BOTH off duty AND has no connection to the patient at all (not
    assigned, not even on their ward) -- the one combination where the system has
    already concluded there is no legitimate reason to be looking at this patient.
    Every other combination (on duty regardless of assignment; off duty but same
    ward; off duty but assigned) still has BTG available, including a nurse's
    existing "neither assigned nor same-ward but on duty" rescue path.

    Deliberately does NOT check contextual.target_patient_id the way DecideView does
    -- the whole point of an emergency path is that it must still work even if the
    normal capture/contextual state is missing, stale, or itself the reason normal
    access failed. For the same reason, the new availability gate below looks up
    on-duty status and assignment/ward relationship FRESH (live staff.on_duty,
    captures.services.compute_patient_assignment_status) rather than depending on
    ContextualCapture -- unlike scoring/engine.py's Doctor rule, which reads the
    session-time snapshot (contextual.on_duty_at_login) like every other factor there.

    Baseline is deliberately NOT reinforced here (unlike DecideView) -- an override is
    by definition an abnormal session, so folding it into the rolling baseline could
    poison future legitimate comparisons.
    """

    permission_classes = [IsClinicalStaff]

    def post(self, request):
        serializer = EmergencyOverrideRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        patient_id = serializer.validated_data["patient_id"]
        reason = serializer.validated_data["reason"]

        session = request.auth
        patient = get_object_or_404(Patient, pk=patient_id)

        assignment_status = compute_patient_assignment_status(session.staff, patient)
        if (
            not session.staff.on_duty
            and assignment_status == ContextualCapture.PatientAssignmentStatus.NOT_ASSIGNED_NOT_SAME_WARD
        ):
            return Response(
                {
                    "detail": (
                        "Break the Glass is not available: you are off duty and have "
                        "no connection (assignment or ward) to this patient."
                    )
                },
                status=status.HTTP_403_FORBIDDEN,
            )

        granted_categories = sorted(ROLE_CEILINGS[session.staff.role])

        decision = AccessDecision.objects.create(
            session=session,
            patient=patient,
            gate_passed=None,
            score=None,
            score_band=None,
            decision_type=AccessDecision.DecisionType.EMERGENCY_OVERRIDE,
            granted_categories=granted_categories,
            role_rule_path="",
            factor_breakdown={"reason": reason},
        )

        record_event(
            event_type=LedgerEntry.EventType.EMERGENCY_OVERRIDE,
            staff=session.staff,
            patient=patient,
            session=session,
            details={"reason": reason, "granted_categories": granted_categories},
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
