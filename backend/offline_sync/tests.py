"""Offline Mode sync tests (build step 6, added 2026-09-12). No real
enrollment data -- Django's isolated test database only, per CLAUDE.md.

A real browser signs with Web Crypto's ECDSA (raw r||s signature bytes);
these tests use the `cryptography` package to play that same role, decoding
its DER output into raw r||s so the payload matches exactly what
offline_sync.verification.verify_batch_signature expects to receive from a
real device.
"""

import base64
import hashlib
import json
import uuid
from unittest.mock import patch

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature
from django.contrib.auth.models import User
from rest_framework import status
from rest_framework.test import APITestCase

from access.models import Device
from alerts.models import SecurityAlert
from ledger.models import LedgerEntry
from ledger.verification import verify_chain
from patients.models import Patient
from staff.models import Staff

from .models import SyncedBatch
from .verification import LOCAL_GENESIS_HASH


def _keypair():
    private_key = ec.generate_private_key(ec.SECP256R1())
    public_key_der = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.DER,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    return private_key, base64.b64encode(public_key_der).decode("ascii")


def _sign_raw(private_key, payload_bytes):
    der_signature = private_key.sign(payload_bytes, ec.ECDSA(hashes.SHA256()))
    r, s = decode_dss_signature(der_signature)
    raw = r.to_bytes(32, "big") + s.to_bytes(32, "big")
    return base64.b64encode(raw).decode("ascii")


def _canonical(payload):
    return json.dumps(payload, sort_keys=True, default=str).encode("utf-8")


def _local_hash(prev_hash, client_seq, occurred_at, event_type, patient_hospital_number, details):
    payload = {
        "prev_local_hash": prev_hash,
        "client_seq": client_seq,
        "occurred_at": occurred_at,
        "event_type": event_type,
        "patient_hospital_number": patient_hospital_number,
        "details": details,
    }
    return hashlib.sha256(_canonical(payload)).hexdigest()


class OfflineSyncViewTests(APITestCase):
    databases = {"default", "ledger"}

    def setUp(self):
        self.user = User.objects.create_user(username="drOffline", password="pw-offline-1")
        self.staff = Staff.objects.create(
            user=self.user, staff_id="STF-700", full_name="Dr Offline", role=Staff.Role.DOCTOR
        )
        login = self.client.post(
            "/api/access/login/",
            {"username": "drOffline", "password": "pw-offline-1", "device_id": "offline-dev-1", "device_type": "desktop"},
            format="json",
        )
        self.token = login.data["token"]
        self.device = Device.objects.get(staff=self.staff, device_id="offline-dev-1")

        self.private_key, self.public_key_b64 = _keypair()
        self.device.sync_public_key = self.public_key_b64
        self.device.save(update_fields=["sync_public_key"])

        self.patient = Patient.objects.create(hospital_number="HN-OFFLINE-1", full_name="Offline Patient")

    def _auth_header(self):
        return {"HTTP_AUTHORIZATION": f"Bearer {self.token}"}

    def _build_batch(self, entries_spec):
        """entries_spec: list of (event_type, patient_hospital_number, details)."""
        entries = []
        prev_hash = LOCAL_GENESIS_HASH
        for i, (event_type, hosp_no, details) in enumerate(entries_spec, start=1):
            occurred_at = f"2026-09-1{i}T10:00:00Z"
            entry_hash = _local_hash(prev_hash, i, occurred_at, event_type, hosp_no, details)
            entries.append(
                {
                    "client_seq": i,
                    "occurred_at": occurred_at,
                    "event_type": event_type,
                    "patient_hospital_number": hosp_no,
                    "details": details,
                    "prev_local_hash": prev_hash,
                    "entry_local_hash": entry_hash,
                }
            )
            prev_hash = entry_hash

        batch_id = str(uuid.uuid4())
        signature = _sign_raw(self.private_key, _canonical({"batch_id": batch_id, "entries": entries}))
        return {
            "device_id": "offline-dev-1",
            "batch_id": batch_id,
            "signature": signature,
            "entries": entries,
        }

    def test_valid_batch_merges_into_ledger(self):
        payload = self._build_batch(
            [
                (LedgerEntry.EventType.STANDARD_ACCESS, "HN-OFFLINE-1", {"score": 95}),
                (LedgerEntry.EventType.REDUCED_ACCESS, "HN-OFFLINE-1", {"score": 50, "step_up_deferred_offline": True}),
            ]
        )
        resp = self.client.post("/api/offline/sync/", payload, format="json", **self._auth_header())
        self.assertEqual(resp.status_code, status.HTTP_200_OK, resp.data)
        self.assertEqual(resp.data["merged"], 2)

        entries = list(LedgerEntry.objects.using("ledger").order_by("sequence"))
        self.assertEqual(len(entries), 2)
        self.assertEqual(entries[0].event_type, LedgerEntry.EventType.STANDARD_ACCESS)
        self.assertEqual(entries[0].staff_id, "STF-700")
        self.assertEqual(entries[0].patient_hospital_number, "HN-OFFLINE-1")
        self.assertTrue(entries[0].details["synced_from_offline"])
        self.assertEqual(entries[1].details["step_up_deferred_offline"], True)

        self.assertEqual(SyncedBatch.objects.filter(batch_id=payload["batch_id"]).count(), 1)

        # Regression check for a real bug (found 2026-09-14): merged entries
        # must actually re-verify, not just have the right field values --
        # see ledger.tests.RecordEventChainTests.
        # test_explicit_non_utc_occurred_at_still_verifies for the root cause.
        ok, bad_sequence = verify_chain()
        self.assertTrue(ok, f"chain failed to verify at sequence {bad_sequence}")

    def test_access_denied_entry_raises_alert(self):
        payload = self._build_batch(
            [(LedgerEntry.EventType.ACCESS_DENIED, "HN-OFFLINE-1", {"score": 12})]
        )
        resp = self.client.post("/api/offline/sync/", payload, format="json", **self._auth_header())
        self.assertEqual(resp.status_code, status.HTTP_200_OK, resp.data)

        alert = SecurityAlert.objects.get(staff_id="STF-700")
        self.assertEqual(alert.alert_type, SecurityAlert.AlertType.ACCESS_DENIED)
        self.assertIsNotNone(alert.ledger_sequence)

    def test_non_standard_entry_notifies_patient(self):
        """Patient SMS notifications (added 2026-09-14) -- same four trigger
        types as the online DecideView, mocked at the point of use
        (offline_sync.views.notify_patient) so this never makes a real
        network call."""
        payload = self._build_batch(
            [(LedgerEntry.EventType.REDUCED_ACCESS, "HN-OFFLINE-1", {"score": 55})]
        )
        with patch("offline_sync.views.notify_patient") as mocked:
            resp = self.client.post("/api/offline/sync/", payload, format="json", **self._auth_header())
        self.assertEqual(resp.status_code, status.HTTP_200_OK, resp.data)
        mocked.assert_called_once()
        call_kwargs = mocked.call_args.kwargs
        self.assertEqual(call_kwargs["event_type"], LedgerEntry.EventType.REDUCED_ACCESS)
        self.assertEqual(call_kwargs["patient"], self.patient)

    def test_standard_access_entry_does_not_notify_patient(self):
        payload = self._build_batch(
            [(LedgerEntry.EventType.STANDARD_ACCESS, "HN-OFFLINE-1", {"score": 95})]
        )
        with patch("offline_sync.views.notify_patient") as mocked:
            resp = self.client.post("/api/offline/sync/", payload, format="json", **self._auth_header())
        self.assertEqual(resp.status_code, status.HTTP_200_OK, resp.data)
        mocked.assert_not_called()

    def test_bad_signature_rejected(self):
        payload = self._build_batch([(LedgerEntry.EventType.STANDARD_ACCESS, "HN-OFFLINE-1", {})])
        other_private_key, _ = _keypair()
        payload["signature"] = _sign_raw(
            other_private_key, _canonical({"batch_id": payload["batch_id"], "entries": payload["entries"]})
        )
        resp = self.client.post("/api/offline/sync/", payload, format="json", **self._auth_header())
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(LedgerEntry.objects.using("ledger").count(), 0)

    def test_tampered_local_chain_rejected(self):
        payload = self._build_batch(
            [
                (LedgerEntry.EventType.STANDARD_ACCESS, "HN-OFFLINE-1", {"score": 95}),
                (LedgerEntry.EventType.STANDARD_ACCESS, "HN-OFFLINE-1", {"score": 91}),
            ]
        )
        # Tamper with the second entry's details but keep its now-stale
        # entry_local_hash, then re-sign over the tampered payload -- this
        # isolates the local-chain-recompute check from the signature check
        # (a real device could never do this without exporting its private
        # key, but the test only needs to exercise the code path).
        payload["entries"][1]["details"] = {"score": 999}
        payload["signature"] = _sign_raw(
            self.private_key, _canonical({"batch_id": payload["batch_id"], "entries": payload["entries"]})
        )
        resp = self.client.post("/api/offline/sync/", payload, format="json", **self._auth_header())
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(LedgerEntry.objects.using("ledger").count(), 0)

    def test_unregistered_device_rejected(self):
        self.device.sync_public_key = ""
        self.device.save(update_fields=["sync_public_key"])
        payload = self._build_batch([(LedgerEntry.EventType.STANDARD_ACCESS, "HN-OFFLINE-1", {})])
        resp = self.client.post("/api/offline/sync/", payload, format="json", **self._auth_header())
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_duplicate_batch_id_is_idempotent(self):
        payload = self._build_batch([(LedgerEntry.EventType.STANDARD_ACCESS, "HN-OFFLINE-1", {})])
        first = self.client.post("/api/offline/sync/", payload, format="json", **self._auth_header())
        self.assertEqual(first.status_code, status.HTTP_200_OK)

        second = self.client.post("/api/offline/sync/", payload, format="json", **self._auth_header())
        self.assertEqual(second.status_code, status.HTTP_200_OK)
        self.assertTrue(second.data.get("already_processed"))

        self.assertEqual(LedgerEntry.objects.using("ledger").count(), 1)

    def test_unauthenticated_rejected(self):
        payload = self._build_batch([(LedgerEntry.EventType.STANDARD_ACCESS, "HN-OFFLINE-1", {})])
        resp = self.client.post("/api/offline/sync/", payload, format="json")
        self.assertEqual(resp.status_code, status.HTTP_401_UNAUTHORIZED)
