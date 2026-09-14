"""Encrypts/decrypts the minutiae template stored on FingerprintTemplate.
Fernet (AES-128-CBC + HMAC, from the `cryptography` package already a direct
dependency for Offline Mode's sync-batch signature verification) is a
legitimate authenticated-encryption scheme, satisfying CLAUDE.md's "store
encrypted templates (AES)."
"""

import json

from cryptography.fernet import Fernet
from django.conf import settings


def _fernet():
    return Fernet(settings.FINGERPRINT_TEMPLATE_KEY)


def encrypt_minutiae(minutiae):
    """minutiae: list of {"x": int, "y": int, "angle": float, "type": str}."""
    payload = json.dumps(minutiae).encode("utf-8")
    return _fernet().encrypt(payload).decode("ascii")


def decrypt_minutiae(encrypted_template):
    payload = _fernet().decrypt(encrypted_template.encode("ascii"))
    return json.loads(payload)
