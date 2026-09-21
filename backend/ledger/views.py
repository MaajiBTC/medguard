from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework.response import Response
from rest_framework.views import APIView

from staff.permissions import IsClinicalStaff, IsSecurityOfficer

from .gemini import GeminiError, explain_entry
from .models import LedgerEntry
from .serializers import LedgerEntrySerializer
from .verification import verify_chain

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


class MyActivityCalendarView(APIView):
    """GET /api/ledger/my-activity/?year=&month= -- per-day counts of the
    caller's OWN record-access events, for the Clinical dashboard's calendar
    card (added 2026-09-19, per the user).

    Deliberately narrow, because the rest of this app scopes Ledger reads to
    a Security Officer: it is filtered to `request.auth.staff.staff_id` and
    returns only dates, counts, and whether anything that day was flagged --
    never patient identities, never another staff member's activity, never
    the entries themselves. A clinician learning which days they themselves
    touched records discloses nothing they didn't already do, which is what
    makes this safe to open up; the same reasoning as the other
    self-service endpoints (MyBaselineView, DeviceListView).
    """

    permission_classes = [IsClinicalStaff]

    def get(self, request):
        now = timezone.localtime()
        try:
            year = int(request.query_params.get("year", now.year))
            month = int(request.query_params.get("month", now.month))
        except ValueError:
            return Response({"detail": "year and month must be integers."}, status=400)
        if not 1 <= month <= 12:
            return Response({"detail": "month must be between 1 and 12."}, status=400)

        entries = LedgerEntry.objects.filter(
            staff_id=request.auth.staff.staff_id,
            occurred_at__year=year,
            occurred_at__month=month,
        ).values_list("occurred_at", "event_type")

        days = {}
        total = 0
        flagged_total = 0
        for occurred_at, event_type in entries:
            # Grouped in the configured local timezone, so a day on the
            # calendar matches the day the clinician actually experienced --
            # occurred_at itself is stored UTC (see services.record_event).
            key = timezone.localtime(occurred_at).date().isoformat()
            day = days.setdefault(key, {"count": 0, "flagged_count": 0, "flagged": False})
            day["count"] += 1
            total += 1
            if event_type != LedgerEntry.EventType.STANDARD_ACCESS:
                day["flagged"] = True
                day["flagged_count"] += 1
                flagged_total += 1

        return Response({
            "year": year,
            "month": month,
            "days": days,
            "total": total,
            "flagged_total": flagged_total,
        })


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


class LedgerVerifyView(APIView):
    """GET /api/ledger/verify/ -- security-officer-only. Re-walks the entire
    hash chain via verification.verify_chain() and reports whether it's
    intact (added 2026-09-06, per the user).

    verify_chain() has existed and been tested since step 3 but was
    unreachable from outside the test suite -- which meant the Ledger's whole
    tamper-evidence property couldn't actually be shown to anyone. This is a
    thin wrapper over it: computes fresh on every call and persists nothing
    (same posture as LedgerEntryExplainView above -- a verification result is
    an observation about the Ledger, not part of it).

    `entries_checked` is counted separately rather than returned by
    verify_chain(), so that already-tested function's signature stays exactly
    as it was.
    """

    permission_classes = [IsSecurityOfficer]

    def get(self, request):
        valid, bad_sequence = verify_chain()
        return Response(
            {
                "valid": valid,
                "bad_sequence": bad_sequence,
                "entries_checked": LedgerEntry.objects.using("ledger").count(),
                "verified_at": timezone.now(),
            }
        )
