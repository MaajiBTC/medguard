"""Chain-integrity check, independent of services.py's write path. Walks the whole
ledger and recomputes every hash, so it catches both a broken prev_hash link and a
row whose fields were altered without going through record_event() (e.g. a direct
`.update()` that bypasses LedgerEntry.save()'s immutability check).
"""

from .models import LedgerEntry
from .services import GENESIS_HASH, _compute_entry_hash


def verify_chain():
    """Returns (True, None) if every entry's hash checks out and the chain is
    unbroken, or (False, first_bad_sequence) at the first entry that doesn't."""
    prev_hash = GENESIS_HASH
    for entry in LedgerEntry.objects.using("ledger").order_by("sequence"):
        if entry.prev_hash != prev_hash:
            return False, entry.sequence

        recomputed = _compute_entry_hash(
            prev_hash=entry.prev_hash,
            sequence=entry.sequence,
            occurred_at=entry.occurred_at,
            event_type=entry.event_type,
            staff_id=entry.staff_id,
            patient_hospital_number=entry.patient_hospital_number,
            session_token=entry.session_token,
            device_id=entry.device_id,
            details=entry.details,
        )
        if recomputed != entry.entry_hash:
            return False, entry.sequence

        prev_hash = entry.entry_hash

    return True, None
