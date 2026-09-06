import math
from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from captures.models import BehavioralCapture, ContextualCapture

from .models import AccessSession, LoginAttempt


def create_session(staff, device_id, device_type, user_agent, login_keystroke_features=None):
    """Creates one AccessSession plus its paired BehavioralCapture/ContextualCapture
    rows in a single transaction. Shared by LoginView's direct-login path and
    DeviceApproveView's device-approval path, so both ways of ending up with a live
    session go through identical capture bootstrapping."""
    with transaction.atomic():
        session = AccessSession.objects.create(
            staff=staff,
            device_id=device_id,
            device_type=device_type,
            user_agent=user_agent,
            network_segment=getattr(settings, "WORKSTATION_NETWORK_SEGMENT", "unknown"),
        )
        BehavioralCapture.objects.create(
            session=session,
            keystroke_features={"login": login_keystroke_features, "session_windows": []},
        )
        ContextualCapture.objects.create(
            session=session,
            on_duty_at_login=staff.on_duty,
            on_call_at_login=staff.on_call,
            ward_assignment_at_login=staff.ward,
        )
    return session


# --- Login brute-force lockout (added 2026-09-06, per the user) --------------
#
# One place for all the lockout logic, matching this codebase's single-writer
# convention (ledger.services.record_event, staff.services.record_admin_action).
# Lockout state is derived from LoginAttempt rows rather than stored anywhere,
# so it expires on its own -- see the LoginAttempt docstring.


def _lockout_window_start():
    return timezone.now() - timedelta(minutes=settings.LOGIN_LOCKOUT_MINUTES)


def record_login_attempt(username, succeeded, device_id="", ip_address=None):
    """Records one attempt. Called for every login, successful or not."""
    return LoginAttempt.objects.create(
        username=username or "",
        succeeded=succeeded,
        device_id=device_id or "",
        ip_address=ip_address,
    )


def recent_failed_attempts(username):
    """Failed attempts for this username inside the current lockout window.

    Only counts failures since that username's last *successful* login -- a
    successful login clears the slate, so a staff member who mistypes twice,
    gets in, then mistypes again isn't inching toward a lock all day.
    """
    window_start = _lockout_window_start()
    attempts = LoginAttempt.objects.filter(username=username, attempted_at__gte=window_start)
    last_success = attempts.filter(succeeded=True).order_by("-attempted_at").first()
    if last_success is not None:
        attempts = attempts.filter(attempted_at__gt=last_success.attempted_at)
    return attempts.filter(succeeded=False)


def lockout_remaining_minutes(username):
    """Whole minutes (rounded up, minimum 1) until this account unlocks, or 0
    if it isn't locked."""
    failures = recent_failed_attempts(username)
    if failures.count() < settings.LOGIN_MAX_FAILED_ATTEMPTS:
        return 0
    oldest_relevant = failures.order_by("attempted_at").first()
    unlocks_at = oldest_relevant.attempted_at + timedelta(
        minutes=settings.LOGIN_LOCKOUT_MINUTES
    )
    seconds_left = (unlocks_at - timezone.now()).total_seconds()
    return max(1, math.ceil(seconds_left / 60)) if seconds_left > 0 else 0


def is_locked_out(username):
    return recent_failed_attempts(username).count() >= settings.LOGIN_MAX_FAILED_ATTEMPTS


def clear_lockout(username):
    """Admin-initiated early unlock -- drops the recent failures so the derived
    lock goes away immediately instead of waiting out the window."""
    return recent_failed_attempts(username).delete()


# --- WebAuthn challenge freshness (added 2026-09-06) -------------------------
#
# Shared by access.views (registration) and scoring.views (step-up
# authentication) -- both ceremonies store their pending challenge on the
# same AccessSession row (see AccessSession.webauthn_challenge) and need the
# identical freshness check, so it lives here rather than being duplicated
# in both apps.

WEBAUTHN_CHALLENGE_TTL = timedelta(minutes=5)


def webauthn_challenge_is_fresh(session):
    if not session.webauthn_challenge or not session.webauthn_challenge_created_at:
        return False
    return timezone.now() - session.webauthn_challenge_created_at < WEBAUTHN_CHALLENGE_TTL


def clear_webauthn_challenge(session):
    session.webauthn_challenge = ""
    session.webauthn_challenge_created_at = None
    session.save(update_fields=["webauthn_challenge", "webauthn_challenge_created_at"])
