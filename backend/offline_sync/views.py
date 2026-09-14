from django.db import transaction
from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from access.models import Device
from alerts.models import SecurityAlert
from alerts.services import raise_alert
from ledger.models import LedgerEntry
from ledger.services import record_event
from notifications.services import notify_patient
from patients.models import Patient
from staff.permissions import IsClinicalStaff

from .models import SyncedBatch
from .serializers import OfflineSyncRequestSerializer
from .verification import LOCAL_GENESIS_HASH, BadSignature, recompute_local_hash, verify_batch_signature


class OfflineSyncView(APIView):
    """POST /api/offline/sync/ -- Offline Mode (build step 6). Merges a
    signed batch of locally-queued access events (produced while this
    device had no connectivity -- see frontend/src/offline/) into the real
    Security Ledger, via the same ledger.services.record_event() every
    online decision already goes through.

    Deliberately does NOT reconstruct AccessDecision rows for these events
    (see the approved plan's design decision #3) -- the durable record of
    "this access happened" is the Ledger entry, exactly as CLAUDE.md
    requires; AccessDecision stays a live, request-time construct used only
    for step-up gating on an active session.
    """

    permission_classes = [IsClinicalStaff]

    def post(self, request):
        serializer = OfflineSyncRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        staff = request.auth.staff

        device = get_object_or_404(Device, staff=staff, device_id=data["device_id"])
        if not device.sync_public_key:
            return Response(
                {"detail": "This device has no signing key registered -- cannot sync offline events."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        existing = SyncedBatch.objects.filter(batch_id=data["batch_id"]).first()
        if existing is not None:
            return Response({"merged": existing.entries_synced, "already_processed": True})

        # Signature covers the exact bytes the device signed -- use the raw
        # request body, not validated_data (which has already converted
        # occurred_at into a Python datetime and would no longer
        # canonicalize to the same JSON the device actually signed).
        raw_entries = request.data.get("entries", [])
        try:
            verify_batch_signature(
                public_key_b64=device.sync_public_key,
                batch_id=str(data["batch_id"]),
                entries_payload=raw_entries,
                signature_b64=data["signature"],
            )
        except BadSignature:
            return Response(
                {"detail": "Batch signature verification failed -- rejected."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Local chain self-consistency -- each entry must chain from the
        # previous one exactly as the device computed it while offline.
        # Hashes are recomputed from the RAW string values (same reasoning
        # as the signature check above), not the parsed/validated ones.
        expected_prev = LOCAL_GENESIS_HASH
        for raw_entry, entry in zip(raw_entries, data["entries"]):
            if entry["prev_local_hash"] != expected_prev:
                return Response(
                    {"detail": f"Offline queue tampering detected at position {entry['client_seq']}."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            recomputed = recompute_local_hash(
                prev_local_hash=raw_entry["prev_local_hash"],
                client_seq=raw_entry["client_seq"],
                occurred_at=raw_entry["occurred_at"],
                event_type=raw_entry["event_type"],
                patient_hospital_number=raw_entry.get("patient_hospital_number", ""),
                details=raw_entry.get("details", {}),
            )
            if recomputed != entry["entry_local_hash"]:
                return Response(
                    {"detail": f"Offline queue tampering detected at position {entry['client_seq']}."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            expected_prev = entry["entry_local_hash"]

        merged = 0
        with transaction.atomic():
            batch = SyncedBatch.objects.create(device=device, batch_id=data["batch_id"])
            for entry in data["entries"]:
                patient = None
                if entry["patient_hospital_number"]:
                    patient = Patient.objects.filter(
                        hospital_number=entry["patient_hospital_number"]
                    ).first()

                ledger_entry = record_event(
                    event_type=entry["event_type"],
                    staff=staff,
                    patient=patient,
                    session=request.auth,
                    details={**entry["details"], "synced_from_offline": True},
                    occurred_at=entry["occurred_at"],
                )
                merged += 1

                if entry["event_type"] == LedgerEntry.EventType.ACCESS_DENIED:
                    raise_alert(
                        alert_type=SecurityAlert.AlertType.ACCESS_DENIED,
                        staff=staff,
                        patient=patient,
                        ledger_sequence=ledger_entry.sequence,
                        details={**entry["details"], "synced_from_offline": True},
                    )

                # Patient SMS notification (added 2026-09-14) -- same four
                # trigger types as DecideView/EmergencyOverrideView, fired
                # "now" (when the device finally reconnects), not backdated
                # to the original offline occurred_at. `patient` can be None
                # here (a hospital_number that didn't resolve to a real
                # patient) -- nothing to notify in that case.
                if patient and entry["event_type"] != LedgerEntry.EventType.STANDARD_ACCESS:
                    notify_patient(patient=patient, event_type=entry["event_type"], staff=staff)

            batch.entries_synced = merged
            batch.save(update_fields=["entries_synced"])

        return Response({"merged": merged})
