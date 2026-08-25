from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from patients.models import Patient, PatientAssignment
from staff.models import Staff

from .models import ContextualCapture
from .serializers import (
    BehavioralCaptureSerializer,
    BehavioralEventBatchSerializer,
    ContextualCaptureSerializer,
    TargetPatientSerializer,
)


class BehavioralEventsView(APIView):
    """POST /api/captures/behavioral/events/

    Appends a batch of raw events to *the caller's own* session capture — the
    session comes from request.auth (the authenticated token), never from a
    client-supplied session id, so one staff member can never write into another's
    capture record. Malformed events (wrong shape, unknown `event` value, etc.) are
    rejected with 400 and nothing is appended.
    """

    def post(self, request):
        session = request.auth
        capture = session.behavioral_capture

        serializer = BehavioralEventBatchSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        keystroke_events = [dict(e) for e in data.get("keystroke_events", [])]
        mouse_events = [dict(e) for e in data.get("mouse_events", [])]
        touch_events = [dict(e) for e in data.get("touch_events", [])]

        # Append, never overwrite — a session's capture accumulates across many
        # flush calls from the frontend's buffered capture hook.
        capture.keystroke_events = capture.keystroke_events + keystroke_events
        capture.mouse_events = capture.mouse_events + mouse_events
        capture.touch_events = capture.touch_events + touch_events
        capture.keystroke_event_count = len(capture.keystroke_events)
        capture.mouse_event_count = len(capture.mouse_events)
        capture.touch_event_count = len(capture.touch_events)
        capture.save(
            update_fields=[
                "keystroke_events",
                "mouse_events",
                "touch_events",
                "keystroke_event_count",
                "mouse_event_count",
                "touch_event_count",
                "updated_at",
            ]
        )

        return Response(
            {
                "keystroke_event_count": capture.keystroke_event_count,
                "mouse_event_count": capture.mouse_event_count,
                "touch_event_count": capture.touch_event_count,
            },
            status=status.HTTP_200_OK,
        )


class BehavioralCaptureDetailView(APIView):
    """GET /api/captures/behavioral/ — debug: raw BehavioralCapture for the caller's
    own session."""

    def get(self, request):
        capture = request.auth.behavioral_capture
        return Response(BehavioralCaptureSerializer(capture).data)


class TargetPatientView(APIView):
    """POST /api/captures/contextual/target-patient/ — {patient_id}

    Computes only the FACTUAL patient-assignment status (assigned / same-ward /
    neither / not-applicable) via lookups against PatientAssignment and Staff/Patient
    ward fields. No scoring or access decision happens here — that is the Scoring
    Engine's job (a separate, not-yet-built component per CLAUDE.md).
    """

    def post(self, request):
        staff = request.auth.staff
        capture = request.auth.contextual_capture

        serializer = TargetPatientSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        patient = get_object_or_404(Patient, pk=serializer.validated_data["patient_id"])

        capture.target_patient = patient
        capture.patient_assignment_status = self._compute_assignment_status(staff, patient)
        capture.patient_assignment_checked_at = timezone.now()
        capture.save(
            update_fields=[
                "target_patient",
                "patient_assignment_status",
                "patient_assignment_checked_at",
            ]
        )

        return Response(ContextualCaptureSerializer(capture).data)

    @staticmethod
    def _compute_assignment_status(staff, patient):
        if staff.role not in (Staff.Role.DOCTOR, Staff.Role.NURSE):
            return ContextualCapture.PatientAssignmentStatus.NOT_APPLICABLE

        is_assigned = PatientAssignment.objects.filter(
            patient=patient, staff=staff, active=True
        ).exists()
        if is_assigned:
            return ContextualCapture.PatientAssignmentStatus.ASSIGNED

        same_ward = (
            bool(staff.ward)
            and bool(patient.ward)
            and staff.ward.strip().lower() == patient.ward.strip().lower()
        )
        if same_ward:
            return ContextualCapture.PatientAssignmentStatus.SAME_WARD_NOT_ASSIGNED

        return ContextualCapture.PatientAssignmentStatus.NOT_ASSIGNED_NOT_SAME_WARD


class ContextualCaptureDetailView(APIView):
    """GET /api/captures/contextual/ — debug: flattened ContextualCapture for the
    caller's own session."""

    def get(self, request):
        capture = request.auth.contextual_capture
        return Response(ContextualCaptureSerializer(capture).data)
