"""Verification for Offline Mode's signed sync batches.

Two separate checks, mirroring the two halves of CLAUDE.md's requirement
("each device has its own registered signing key... verified against the
central ledger before merging"):

1. `verify_signature` -- proves the WHOLE batch came from a device that
   registered a signing key (access.views.RegisterSyncKeyView), and hasn't
   been altered in transit/at rest since the device signed it.
2. `recompute_local_hash` / the chain check in views.py -- proves the
   entries inside the batch weren't reordered or edited relative to each
   other, using the same local chain the device built while queueing them
   offline (see CLAUDE.md's "still hash-chained in real time").

This is a deliberately separate, simpler scheme from ledger.services'
production hash chain (see the approved plan's design decision #2) -- it
only has to prove "this queue wasn't tampered with before it reached us",
not reproduce the production Ledger's own sequence/hash. The real,
canonical chain is still built exactly as always, by replaying verified
entries through ledger.services.record_event() one at a time.
"""

import base64
import hashlib
import json

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import encode_dss_signature

LOCAL_GENESIS_HASH = "0" * 64


def canonical_json(payload):
    return json.dumps(payload, sort_keys=True, default=str).encode("utf-8")


def recompute_local_hash(*, prev_local_hash, client_seq, occurred_at, event_type,
                          patient_hospital_number, details):
    """Must exactly mirror frontend/src/offline/localLedger.js's
    computeLocalEntryHash -- same field set, same sorted-key JSON
    canonicalization, same SHA-256."""
    payload = {
        "prev_local_hash": prev_local_hash,
        "client_seq": client_seq,
        "occurred_at": occurred_at,
        "event_type": event_type,
        "patient_hospital_number": patient_hospital_number,
        "details": details,
    }
    return hashlib.sha256(canonical_json(payload)).hexdigest()


class BadSignature(Exception):
    pass


def verify_batch_signature(*, public_key_b64, batch_id, entries_payload, signature_b64):
    """`public_key_b64` is the SPKI-encoded public key registered via
    RegisterSyncKeyView. `signature_b64` is the device's ECDSA signature
    (raw r||s, base64) over the canonical JSON of {batch_id, entries}."""
    try:
        public_key = serialization.load_der_public_key(base64.b64decode(public_key_b64))
        signature_raw = base64.b64decode(signature_b64)
        # Web Crypto's ECDSA signatures are raw (r||s) concatenated, not the
        # DER encoding `cryptography` expects by default -- convert.
        half = len(signature_raw) // 2
        r = int.from_bytes(signature_raw[:half], "big")
        s = int.from_bytes(signature_raw[half:], "big")
        der_signature = encode_dss_signature(r, s)
        signed_payload = canonical_json({"batch_id": batch_id, "entries": entries_payload})
        public_key.verify(der_signature, signed_payload, ec.ECDSA(hashes.SHA256()))
    except (InvalidSignature, ValueError, TypeError) as exc:
        raise BadSignature(str(exc)) from exc
