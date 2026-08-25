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
