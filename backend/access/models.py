import secrets

from django.db import models


def generate_session_token():
    """Opaque bearer token for one login session (not a per-user permanent token)."""
    return secrets.token_hex(32)


class AccessSession(models.Model):
    """One login session. The shared anchor both capture models point to, so
    BehavioralCapture and ContextualCapture stay peers with no dependency between
    them (matching CLAUDE.md's module spec), while both hang off the same session.

    `started_at` doubles as the login timestamp the Contextual module needs.
    """

    staff = models.ForeignKey(
        "staff.Staff", on_delete=models.CASCADE, related_name="access_sessions"
    )
    token = models.CharField(
        max_length=64, unique=True, default=generate_session_token, editable=False
    )
    started_at = models.DateTimeField(auto_now_add=True)
    ended_at = models.DateTimeField(null=True, blank=True)
    is_active = models.BooleanField(default=True)

    device_id = models.CharField(max_length=255)
    device_type = models.CharField(max_length=32, blank=True)
    user_agent = models.CharField(max_length=512, blank=True)
    network_segment = models.CharField(max_length=128, blank=True, default="unknown")

    # WebAuthn challenge storage (added 2026-09-06) -- the pending challenge
    # between a registration or step-up authentication ceremony's two calls
    # (options -> browser ceremony -> verify). Stored on the session row
    # itself rather than Django's cache framework: the default LocMemCache is
    # per-process, which would break under Render's multi-worker gunicorn --
    # a DB row needs no new infrastructure and is trivially consistent.
    # Overwritten on every new ceremony; cleared after a successful verify.
    webauthn_challenge = models.TextField(blank=True, default="")
    webauthn_challenge_created_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-started_at"]

    def __str__(self):
        state = "active" if self.is_active else "ended"
        return f"Session({self.staff}, {state}, started {self.started_at:%Y-%m-%d %H:%M})"


class Device(models.Model):
    """One approved device for a (clinical-role) staff account. The first device to
    ever log in for an account becomes its permanent `is_primary` device (added
    2026-08-30, per the user -- one device per account, primary picked by whoever
    logs in first); every other approved device came through a PendingDeviceRequest
    below. Scoped to clinical roles only -- admin/security_officer are documented
    shared accounts (see Staff.NO_WARD_DUTY_ROLES) and never get Device rows at all,
    so LoginView skips this whole mechanism for them.
    """

    staff = models.ForeignKey("staff.Staff", on_delete=models.CASCADE, related_name="devices")
    device_id = models.CharField(max_length=255)
    device_type = models.CharField(max_length=32, blank=True)
    user_agent = models.CharField(max_length=512, blank=True)
    is_primary = models.BooleanField(default=False)
    approved_at = models.DateTimeField(auto_now_add=True)
    last_seen_at = models.DateTimeField(auto_now=True)

    # Offline Mode (build step 6, added 2026-09-12): this device's ECDSA
    # P-256 public key (base64 SPKI), registered once via
    # RegisterSyncKeyView so the private key never leaves the device.
    # Blank until the device has actually registered one -- OfflineSyncView
    # rejects a sync batch from a device with no key here, per CLAUDE.md's
    # "unsigned/unregistered device batches are rejected at sync."
    sync_public_key = models.TextField(blank=True, default="")

    class Meta:
        ordering = ["-is_primary", "-last_seen_at"]
        constraints = [
            models.UniqueConstraint(fields=["staff", "device_id"], name="unique_device_per_staff"),
        ]

    def __str__(self):
        role = "primary" if self.is_primary else "device"
        return f"{role}({self.staff}, {self.device_type or 'unknown'})"


class WebAuthnCredential(models.Model):
    """One device's enrolled biometric/platform-authenticator credential for
    step-up verification (added 2026-09-06, replacing the typed PIN). Self-
    enrolled only -- nobody but the staff member, sitting at this device, can
    create one; that's inherent to how WebAuthn's security model works, not
    a rule this app invents.

    A separate model from Device on purpose: being an *approved* device and
    being *biometric-enrolled for step-up* are related but distinct facts --
    a device can be perfectly approved for login and still have no step-up
    credential (nothing needed it yet, or this device has no platform
    authenticator at all). `OneToOneField` -- re-enrolling replaces whatever
    was there rather than accumulating rows.

    credential_id/public_key are stored as the base64url strings the
    `webauthn` library already produces at its own encode/decode boundary
    (bytes_to_base64url/base64url_to_bytes) -- plain TextFields, not binary
    columns, for portability between SQLite locally and Postgres on Render.
    """

    staff = models.ForeignKey(
        "staff.Staff", on_delete=models.CASCADE, related_name="webauthn_credentials"
    )
    device = models.OneToOneField(Device, on_delete=models.CASCADE, related_name="webauthn_credential")
    credential_id = models.TextField(unique=True)
    public_key = models.TextField()
    sign_count = models.PositiveBigIntegerField(default=0)
    registered_at = models.DateTimeField(auto_now_add=True)
    last_used_at = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return f"WebAuthnCredential({self.staff}, device={self.device_id})"


class PendingDeviceRequest(models.Model):
    """A login attempt from a device that isn't yet approved for this (clinical-role)
    staff account. Created instead of an AccessSession -- the requesting device polls
    `poll_token` (opaque, unguessable, same generator as AccessSession.token) until
    the account's primary-device owner approves or rejects it from their own Profile
    > Devices panel. Deliberately not routed through the Security Ledger: same
    reasoning CLAUDE.md documents for scoring.DisasterModeEvent -- the Ledger's
    event_type is pinned to exactly 5 values, none of which is "a device was
    approved," so this gets its own small table instead of stretching that spec.
    """

    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        APPROVED = "approved", "Approved"
        REJECTED = "rejected", "Rejected"

    staff = models.ForeignKey(
        "staff.Staff", on_delete=models.CASCADE, related_name="pending_device_requests"
    )
    device_id = models.CharField(max_length=255)
    device_type = models.CharField(max_length=32, blank=True)
    user_agent = models.CharField(max_length=512, blank=True)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.PENDING)
    poll_token = models.CharField(
        max_length=64, unique=True, default=generate_session_token, editable=False
    )
    # Populated by DeviceApproveView once approved; handed back to the polling
    # device exactly once (DeviceRequestPollView clears it after the first read) so
    # a leaked poll_token can't be replayed later to re-fetch a live session token.
    session_token = models.CharField(max_length=64, blank=True)
    requested_at = models.DateTimeField(auto_now_add=True)
    resolved_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-requested_at"]

    def __str__(self):
        return f"PendingDeviceRequest({self.staff}, {self.status})"


class LoginAttempt(models.Model):
    """One row per login attempt, successful or not (added 2026-09-06, per the
    user) -- the basis for brute-force lockout, and an audit trail in its own
    right.

    Keyed by the submitted `username` rather than a Staff foreign key on
    purpose: an attempt against a username that doesn't exist is exactly the
    kind of thing worth recording, and there's no Staff row to point at in
    that case. Nothing here is routed through the Security Ledger, same
    reasoning as PendingDeviceRequest above -- "someone typed the wrong
    password" isn't one of the Ledger's five pinned event types.

    Lockout state is *derived* from these rows rather than stored (see
    access.services.is_locked_out): an account is locked while it has at
    least settings.LOGIN_MAX_FAILED_ATTEMPTS failures inside the last
    settings.LOGIN_LOCKOUT_MINUTES. That makes auto-unlock free -- old
    failures simply age out of the window -- with no scheduled job needed,
    and an admin can clear a lockout early by deleting the recent failures
    (access.services.clear_lockout).
    """

    username = models.CharField(max_length=150, db_index=True)
    succeeded = models.BooleanField(default=False)
    device_id = models.CharField(max_length=255, blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    attempted_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-attempted_at"]

    def __str__(self):
        outcome = "success" if self.succeeded else "failure"
        return f"LoginAttempt({self.username}, {outcome}, {self.attempted_at:%Y-%m-%d %H:%M})"
