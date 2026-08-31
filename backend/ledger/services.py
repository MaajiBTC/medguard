"""Hash-chain writer. record_event() is the only sanctioned way to create a
LedgerEntry -- every other component (Scoring Engine now, Emergency Override later)
calls into this rather than touching LedgerEntry.objects.create() directly, so the
chain-linking logic lives in exactly one place.
"""

import hashlib
import json

from django.db import transaction
from django.utils import timezone

from .models import LedgerEntry

GENESIS_HASH = "0" * 64


def _compute_entry_hash(*, prev_hash, sequence, occurred_at, event_type, staff_id,
                         patient_hospital_number, session_token, device_id, details):
    payload = {
        "prev_hash": prev_hash,
        "sequence": sequence,
        "occurred_at": occurred_at.isoformat(),
        "event_type": event_type,
        "staff_id": staff_id,
        "patient_hospital_number": patient_hospital_number,
        "session_token": session_token,
        "device_id": device_id,
        "details": details,
    }
    canonical = json.dumps(payload, sort_keys=True, default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def record_event(*, event_type, staff, patient=None, session=None, details=None, occurred_at=None):
    """Appends one entry to the hash chain and returns it.

    `staff`/`patient`/`session` are the real model instances (from whichever database
    they live on) -- only their identifying fields are copied in, never a live
    reference, since LedgerEntry lives on a different database and can't hold a
    ForeignKey to them.
    """
    details = details or {}
    occurred_at = occurred_at or timezone.now()

    with transaction.atomic(using="ledger"):
        last = LedgerEntry.objects.using("ledger").select_for_update().order_by("-sequence").first()
        prev_hash = last.entry_hash if last else GENESIS_HASH
        next_sequence = (last.sequence + 1) if last else 1

        staff_id = staff.staff_id
        staff_full_name = staff.full_name
        staff_role = staff.role
        patient_hospital_number = patient.hospital_number if patient else ""
        session_token = session.token if session else ""
        device_id = session.device_id if session else ""

        entry_hash = _compute_entry_hash(
            prev_hash=prev_hash,
            sequence=next_sequence,
            occurred_at=occurred_at,
            event_type=event_type,
            staff_id=staff_id,
            patient_hospital_number=patient_hospital_number,
            session_token=session_token,
            device_id=device_id,
            details=details,
        )

        return LedgerEntry.objects.using("ledger").create(
            sequence=next_sequence,
            occurred_at=occurred_at,
            event_type=event_type,
            staff_id=staff_id,
            staff_full_name=staff_full_name,
            staff_role=staff_role,
            patient_hospital_number=patient_hospital_number,
            session_token=session_token,
            device_id=device_id,
            details=details,
            prev_hash=prev_hash,
            entry_hash=entry_hash,
        )
