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

    class Meta:
        ordering = ["-is_primary", "-last_seen_at"]
        constraints = [
            models.UniqueConstraint(fields=["staff", "device_id"], name="unique_device_per_staff"),
        ]

    def __str__(self):
        role = "primary" if self.is_primary else "device"
        return f"{role}({self.staff}, {self.device_type or 'unknown'})"


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
