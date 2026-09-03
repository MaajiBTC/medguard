from django.shortcuts import get_object_or_404
from rest_framework.response import Response
from rest_framework.views import APIView

from staff.permissions import IsSecurityOfficer

from .gemini import GeminiError, explain_entry
from .models import LedgerEntry
from .serializers import LedgerEntrySerializer

PAGE_SIZE = 50


class LedgerFeedView(APIView):
    """GET /api/ledger/entries/?event_type=&staff_id=&staff_role=&patient_hospital_number=&since=&until=&before=

    Security-officer-only read of the hash-chained ledger (CLAUDE.md Security
    Dashboard: "live feed... filterable by staff member/patient/date"). Newest first;
    `before` (a sequence number) pages further back. Read-only -- no write path lives
    here, that's ledger.services.record_event(). `staff_role` added 2026-08-31 for
    the Ledger page's role "slicer" -- filters on the denormalized staff_role field
    (see LedgerEntry.staff_role), same as the other exact-match filters above it.
    """

    permission_classes = [IsSecurityOfficer]

    def get(self, request):
        entries = LedgerEntry.objects.using("ledger").all()

        event_type = request.query_params.get("event_type")
        if event_type:
            entries = entries.filter(event_type=event_type)

        staff_id = request.query_params.get("staff_id")
        if staff_id:
            entries = entries.filter(staff_id=staff_id)

        staff_role = request.query_params.get("staff_role")
        if staff_role:
            entries = entries.filter(staff_role=staff_role)

        patient_hospital_number = request.query_params.get("patient_hospital_number")
        if patient_hospital_number:
            entries = entries.filter(patient_hospital_number=patient_hospital_number)

        since = request.query_params.get("since")
        if since:
            entries = entries.filter(occurred_at__gte=since)

        until = request.query_params.get("until")
        if until:
            entries = entries.filter(occurred_at__lte=until)

        before = request.query_params.get("before")
        if before:
            entries = entries.filter(sequence__lt=before)

        entries = entries.order_by("-sequence")[:PAGE_SIZE]
        return Response(LedgerEntrySerializer(entries, many=True).data)


class LedgerEntryExplainView(APIView):
    """POST /api/ledger/entries/<sequence>/explain/ -- security-officer-only.
    Sends the entry's denormalized fields + details JSON to Gemini (see
    gemini.py) and returns a plain-English explanation for the security
    officer. Generated fresh on every call, never persisted -- the Ledger
    stays exactly what services.record_event() wrote; an AI's paraphrase of
    an entry is not part of the audited record.
    """

    permission_classes = [IsSecurityOfficer]

    def post(self, request, sequence):
        entry = get_object_or_404(LedgerEntry.objects.using("ledger"), sequence=sequence)
        try:
            explanation = explain_entry(entry)
        except GeminiError as exc:
            return Response({"detail": str(exc)}, status=502)
        return Response({"explanation": explanation})
