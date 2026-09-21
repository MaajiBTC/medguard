import hmac
import secrets

from django.conf import settings
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView
from webauthn import base64url_to_bytes, generate_authentication_options, verify_authentication_response
from webauthn.helpers import bytes_to_base64url, options_to_json_dict
from webauthn.helpers.exceptions import InvalidAuthenticationResponse
from webauthn.helpers.structs import PublicKeyCredentialDescriptor, UserVerificationRequirement

from access.models import WebAuthnCredential
from access.services import clear_webauthn_challenge, webauthn_challenge_is_fresh
from alerts.models import SecurityAlert
from alerts.services import raise_alert
from captures.models import ContextualCapture
from captures.services import compute_patient_assignment_status
from ledger.models import LedgerEntry
from ledger.services import record_event
from notifications.services import notify_patient
from patients.models import Patient, PatientCategoryRecord
from patients.serializers import PatientCategoryRecordSerializer
from staff.permissions import IsAdmin, IsClinicalStaff

from .baseline import update_baseline
from .disaster_mode import is_disaster_mode_active
from .engine import ROLE_CEILINGS, compute_access_decision
from .models import AccessDecision, BehavioralBaseline, DisasterModeEvent, StepUpAssistRequest
from .serializers import (
    AccessDecisionSerializer,
    DecideRequestSerializer,
    DisasterModeActionSerializer,
    EmergencyOverrideRequestSerializer,
    StepUpAssistRequestOwnSerializer,
    StepUpAssistRequestSerializer,
)

# Shared by both step-up verification paths below -- three wrong biometric
# attempts, or the decision otherwise going stale, spends it: the clinician
# has to re-run /decide/ rather than retry indefinitely against one decision.
STEP_UP_MAX_ATTEMPTS = 3


def _generate_assist_code():
    """A 6-digit numeric code (000000-999999) -- easy to read aloud/type,
    and 1,000,000 possibilities is enough that STEP_UP_MAX_ATTEMPTS guessing
    attempts is not a meaningful brute-force risk. secrets, not random --
    this gates a real access grant."""
    return f"{secrets.randbelow(1_000_000):06d}"


class DecideView(APIView):
    """POST /api/scoring/decide/ -- {patient_id}

    Requires the caller already set the target patient via
    /api/captures/contextual/target-patient/ (reads the ContextualCapture's already-
    computed patient_assignment_status rather than recomputing it -- that factual
    lookup lives in exactly one place, the captures app, per CLAUDE.md's module
    boundaries). Computes the access decision, updates the staff member's rolling
    behavioral baseline for any non-denied outcome, writes the decision to the
    Security Ledger (every decision, including denials -- CLAUDE.md), and returns the
    decision.

    The ledger write is unguarded: if it fails, the exception propagates into a 500 and
    the caller never receives a decision that wasn't also logged (fail-closed -- an
    unaudited access grant is worse than a temporary outage).

    Admin/security officer sessions are rejected (403) -- patient-record access is not
    applicable to those roles, this isn't just an unenforced convention.
    """

    permission_classes = [IsClinicalStaff]

    def post(self, request):
        serializer = DecideRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        patient_id = serializer.validated_data["patient_id"]

        session = request.auth
        contextual = session.contextual_capture

        if contextual.target_patient_id != patient_id:
            return Response(
                {
                    "detail": (
                        "Target patient not set for this session. Call "
                        "/api/captures/contextual/target-patient/ with this patient_id first."
                    )
                },
                status=status.HTTP_409_CONFLICT,
            )

        patient = get_object_or_404(Patient, pk=patient_id)
        decision = compute_access_decision(session, patient)

        if decision.decision_type != AccessDecision.DecisionType.ACCESS_DENIED:
            baseline, _ = BehavioralBaseline.objects.get_or_create(staff=session.staff)
            update_baseline(baseline, session)

        entry = record_event(
            event_type=decision.decision_type,
            staff=session.staff,
            patient=patient,
            session=session,
            details={
                "gate_passed": decision.gate_passed,
                "score": decision.score,
                "score_band": decision.score_band,
                "granted_categories": decision.granted_categories,
                "role_rule_path": decision.role_rule_path,
                "factor_breakdown": decision.factor_breakdown,
            },
        )

        # "ACCESS_DENIED, security alert triggered" (CLAUDE.md's band table).
        # The Ledger entry above is the audit record; this is the part that
        # puts it in front of a human and makes them sign it off (added
        # 2026-09-06). Linked back to the entry by sequence number, since a
        # cross-database FK isn't possible.
        if decision.decision_type == AccessDecision.DecisionType.ACCESS_DENIED:
            raise_alert(
                alert_type=SecurityAlert.AlertType.ACCESS_DENIED,
                staff=session.staff,
                patient=patient,
                ledger_sequence=entry.sequence,
                details={
                    "gate_passed": decision.gate_passed,
                    "score": decision.score,
                    "score_band": decision.score_band,
                    "role_rule_path": decision.role_rule_path,
                    "factor_breakdown": decision.factor_breakdown,
                },
            )

        # Patient SMS notification (added 2026-09-14, the user's own idea) --
        # the same four non-silent event types the Ledger/Security Dashboard
        # already treat as noteworthy. A clean STANDARD_ACCESS stays silent.
        # Never breaks this response even if Twilio itself fails (see
        # notifications.services.notify_patient).
        if decision.decision_type != AccessDecision.DecisionType.STANDARD_ACCESS:
            notify_patient(patient=patient, event_type=decision.decision_type, staff=session.staff)

        return Response(AccessDecisionSerializer(decision).data, status=status.HTTP_201_CREATED)


class EmergencyOverrideView(APIView):
    """POST /api/scoring/emergency-override/ -- {patient_id, reason}

    "Break the Glass": available regardless of score or role-match (CLAUDE.md
    Emergency Override), for the exact situation scoring/engine.py's Nurse rule
    comment already calls out -- e.g. a nurse who is neither assigned to the patient
    nor on their ward has no other path to access at all.

    Requires the caller to already be logged in and authenticated (same
    AccessSessionAuthentication/IsClinicalStaff boundary as DecideView -- BTG is not a
    way around login, only around the scoring pipeline) and still respects the role
    ceiling table (ROLE_CEILINGS) -- it bypasses the hard behavioral gate, the score
    band, and the Nurse rule's assignment/ward matching, but a clerk invoking this
    still only gets categories 1-2, never the full 13.

    Not unconditional, though (user request, 2026-08-29): it is blocked for a doctor
    or nurse who is BOTH off duty (and not on call) AND has no connection to the
    patient at all (not assigned, not even on their ward) -- the one combination
    where the system has already concluded there is no legitimate reason to be
    looking at this patient. Every other combination (on duty/on call regardless of
    assignment; off duty but same ward; off duty but assigned) still has BTG
    available, including a nurse's existing "neither assigned nor same-ward but on
    duty" rescue path. The only thing that lifts the block is Disaster/Mass Casualty
    Mode (see disaster_mode.is_disaster_mode_active()) -- hospital-wide, admin-set,
    and audited in its own table.

    Selecting the "cross_coverage" reason_category used to lift it too (self-attested,
    2026-08-29). Removed 2026-09-20, per the user: "a staff cannot cross cover when
    he's not on duty or not on call" -- someone genuinely covering a shift is on duty
    or on call, and if the roster hasn't caught up, an admin setting either flag is
    the honest fix, not a checkbox the requester ticks about themselves. The category
    itself stays (see EmergencyOverrideRequestSerializer): an on-duty clinician
    covering a colleague's patients still has a real reason to record, it just no
    longer opens a door.

    Deliberately does NOT check contextual.target_patient_id the way DecideView does
    -- the whole point of an emergency path is that it must still work even if the
    normal capture/contextual state is missing, stale, or itself the reason normal
    access failed. For the same reason, the availability gate below looks up on-duty/
    on-call status and assignment/ward relationship FRESH (live staff fields,
    captures.services.compute_patient_assignment_status) rather than depending on
    ContextualCapture -- unlike scoring/engine.py's Doctor rule, which reads the
    session-time snapshot (contextual.on_duty_at_login/on_call_at_login) like every
    other factor there.

    Baseline is deliberately NOT reinforced here (unlike DecideView) -- an override is
    by definition an abnormal session, so folding it into the rolling baseline could
    poison future legitimate comparisons.
    """

    permission_classes = [IsClinicalStaff]

    def post(self, request):
        serializer = EmergencyOverrideRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        patient_id = serializer.validated_data["patient_id"]
        reason_category = serializer.validated_data["reason_category"]
        reason = serializer.validated_data["reason"]

        session = request.auth
        patient = get_object_or_404(Patient, pk=patient_id)

        assignment_status = compute_patient_assignment_status(session.staff, patient)
        effectively_on_duty = session.staff.on_duty or session.staff.on_call
        blocked = (
            not effectively_on_duty
            and assignment_status == ContextualCapture.PatientAssignmentStatus.NOT_ASSIGNED_NOT_SAME_WARD
        )
        if blocked and not is_disaster_mode_active():
            return Response(
                {
                    "detail": (
                        "Break the Glass is not available: you are off duty, not on "
                        "call, and have no connection (assignment or ward) to this "
                        "patient."
                    )
                },
                status=status.HTTP_403_FORBIDDEN,
            )

        granted_categories = sorted(ROLE_CEILINGS[session.staff.role])

        decision = AccessDecision.objects.create(
            session=session,
            patient=patient,
            gate_passed=None,
            score=None,
            score_band=None,
            decision_type=AccessDecision.DecisionType.EMERGENCY_OVERRIDE,
            granted_categories=granted_categories,
            role_rule_path="",
            factor_breakdown={"reason": reason, "reason_category": reason_category},
        )

        record_event(
            event_type=LedgerEntry.EventType.EMERGENCY_OVERRIDE,
            staff=session.staff,
            patient=patient,
            session=session,
            details={
                "reason": reason,
                "reason_category": reason_category,
                "granted_categories": granted_categories,
            },
        )

        # Patient SMS notification (added 2026-09-14) -- every Break the
        # Glass is one of the four trigger types already, so this always
        # fires here, unconditionally.
        notify_patient(patient=patient, event_type=LedgerEntry.EventType.EMERGENCY_OVERRIDE, staff=session.staff)

        return Response(AccessDecisionSerializer(decision).data, status=status.HTTP_201_CREATED)


class MyBaselineView(APIView):
    """GET /api/scoring/my-baseline/ -- Offline Mode (build step 6). The
    caller's own frozen behavioral baseline snapshot plus the current
    Disaster Mode flag, cached client-side (frontend/src/offline/db.js) so
    ClinicalDashboard.jsx's offline scoring path (scoringEngine.js) can
    reproduce compute_access_decision()'s weighted math without a server --
    see the approved plan's design decision #5: offline decisions read this
    frozen snapshot and never write one back; Welford reinforcement only
    happens back online, through the normal /decide/ path.

    Self-service (always request.auth.staff, no staff_id in the URL), same
    pattern as ChangePasswordView -- there's nothing here a staff member
    isn't already implicitly trusted with, since it's their own behavioral
    profile driving their own sessions' scores.
    """

    permission_classes = [IsClinicalStaff]

    def get(self, request):
        baseline, _ = BehavioralBaseline.objects.get_or_create(staff=request.auth.staff)
        return Response(
            {
                "sample_count": baseline.sample_count,
                "keystroke_stats": baseline.keystroke_stats,
                "mouse_stats": baseline.mouse_stats,
                "known_device_ids": baseline.known_device_ids,
                "login_hour_stats": baseline.login_hour_stats,
                "known_network_segments": baseline.known_network_segments,
                "disaster_mode_active": is_disaster_mode_active(),
            }
        )


class DisasterModeView(APIView):
    """GET /api/scoring/disaster-mode/ -- current status. Admin-only, matching the
    Admin-dashboard-only UI for this feature."""

    permission_classes = [IsAdmin]

    def get(self, request):
        latest = DisasterModeEvent.objects.order_by("-occurred_at").first()
        return Response(
            {
                "active": is_disaster_mode_active(),
                "last_event": (
                    {
                        "event_type": latest.event_type,
                        "staff_id": latest.staff.staff_id,
                        "staff_full_name": latest.staff.full_name,
                        "reason": latest.reason,
                        "occurred_at": latest.occurred_at,
                    }
                    if latest
                    else None
                ),
            }
        )


class DisasterModeActivateView(APIView):
    """POST /api/scoring/disaster-mode/activate/ -- {reason}. Suspends the Doctor
    off-duty+unconnected hard-deny rule and BTG's availability gate hospital-wide
    (see engine.py and EmergencyOverrideView above) until deactivated. Rejects with
    400 if already active, so the history table stays a meaningful audit trail
    rather than accumulating redundant entries."""

    permission_classes = [IsAdmin]

    def post(self, request):
        if is_disaster_mode_active():
            return Response({"detail": "Disaster Mode is already active."}, status=status.HTTP_400_BAD_REQUEST)
        serializer = DisasterModeActionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        event = DisasterModeEvent.objects.create(
            event_type=DisasterModeEvent.EventType.ACTIVATED,
            staff=request.auth.staff,
            reason=serializer.validated_data["reason"],
        )
        return Response(
            {"active": True, "occurred_at": event.occurred_at}, status=status.HTTP_201_CREATED
        )


class DisasterModeDeactivateView(APIView):
    """POST /api/scoring/disaster-mode/deactivate/ -- {reason}."""

    permission_classes = [IsAdmin]

    def post(self, request):
        if not is_disaster_mode_active():
            return Response({"detail": "Disaster Mode is not active."}, status=status.HTTP_400_BAD_REQUEST)
        serializer = DisasterModeActionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        event = DisasterModeEvent.objects.create(
            event_type=DisasterModeEvent.EventType.DEACTIVATED,
            staff=request.auth.staff,
            reason=serializer.validated_data["reason"],
        )
        return Response(
            {"active": False, "occurred_at": event.occurred_at}, status=status.HTTP_201_CREATED
        )


def _is_eligible_assistant(colleague, requesting_staff):
    """Amended 2026-09-18, per the user: the colleague-assist pool is no
    longer "any logged-in clinical colleague, hospital-wide" -- it's
    narrowed to staff on duty (or on call, equivalent everywhere else in
    this app -- the Doctor rule, BTG's own availability gate) in the SAME
    ward as the requester. Deliberately no hospital-wide fallback if nobody
    qualifies -- consistent with how the Nurse/Doctor rules already treat
    "nobody legitimately connected" as a hard boundary rather than
    softening it; Break the Glass already exists specifically to rescue
    that case. Enforced here, not just filtered out of the list view, so a
    colleague who doesn't qualify can't approve/decline via a direct API
    call to a request_id they already know."""
    if colleague.id == requesting_staff.id:
        return False
    if not (colleague.on_duty or colleague.on_call):
        return False
    return colleague.ward == requesting_staff.ward


def _get_own_reduced_decision(request, decision_id):
    """Shared lookup + guards for every step-up endpoint below. Scoped to the
    caller's own session -- a decision belonging to anyone else's session is
    a 404, not a 403, so this can't be used to probe which decision IDs
    exist. Returns (decision, error_response); error_response is None when
    the decision is a legitimate, still-open step-up target."""
    decision = get_object_or_404(AccessDecision, pk=decision_id, session=request.auth)

    if decision.decision_type != AccessDecision.DecisionType.REDUCED_ACCESS:
        return decision, Response(
            {"detail": "Step-up verification only applies to reduced-access decisions."},
            status=status.HTTP_400_BAD_REQUEST,
        )
    if decision.step_up_verified:
        return decision, Response({"detail": "Already verified.", "step_up_verified": True})
    if decision.step_up_failed_attempts >= STEP_UP_MAX_ATTEMPTS:
        return decision, Response(
            {
                "detail": "Too many failed attempts. Request access again to retry.",
                "attempts_remaining": 0,
            },
            status=status.HTTP_403_FORBIDDEN,
        )
    return decision, None


class StepUpWebAuthnOptionsView(APIView):
    """POST /api/scoring/decisions/<decision_id>/step-up/webauthn/options/

    First step of verifying with THIS device's enrolled biometric (added
    2026-09-06, replacing the typed PIN). 400s if this device has no
    enrolled credential -- the frontend should not even show this button in
    that case, offering "ask a colleague" (below) instead.
    """

    permission_classes = [IsClinicalStaff]

    def post(self, request, decision_id):
        session = request.auth
        decision, error = _get_own_reduced_decision(request, decision_id)
        if error:
            return error

        credential = WebAuthnCredential.objects.filter(
            staff=session.staff, device__device_id=session.device_id
        ).first()
        if not credential:
            return Response(
                {
                    "detail": "No biometric credential enrolled on this device.",
                    "webauthn_available": False,
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        options = generate_authentication_options(
            rp_id=settings.WEBAUTHN_RP_ID,
            allow_credentials=[
                PublicKeyCredentialDescriptor(id=base64url_to_bytes(credential.credential_id))
            ],
            user_verification=UserVerificationRequirement.REQUIRED,
        )
        session.webauthn_challenge = bytes_to_base64url(options.challenge)
        session.webauthn_challenge_created_at = timezone.now()
        session.save(update_fields=["webauthn_challenge", "webauthn_challenge_created_at"])

        return Response(options_to_json_dict(options))


class StepUpWebAuthnVerifyView(APIView):
    """POST /api/scoring/decisions/<decision_id>/step-up/webauthn/verify/ --
    {credential: <navigator.credentials.get() response>}

    Second step: verifies the browser's response against the enrolled
    credential's stored public key and the challenge from options/ above. On
    a genuine cryptographic failure (bad signature, sign-count regression --
    a real red flag, not "forgot my device") raises a STEP_UP_FAILED alert,
    same as three wrong PIN guesses used to. A plain browser-side cancel
    never reaches this endpoint at all, so it never alerts.
    """

    permission_classes = [IsClinicalStaff]

    def post(self, request, decision_id):
        session = request.auth
        staff = session.staff
        decision, error = _get_own_reduced_decision(request, decision_id)
        if error:
            return error

        credential = WebAuthnCredential.objects.filter(
            staff=staff, device__device_id=session.device_id
        ).first()
        if not credential:
            return Response(
                {
                    "detail": "No biometric credential enrolled on this device.",
                    "webauthn_available": False,
                },
                status=status.HTTP_400_BAD_REQUEST,
            )
        if not webauthn_challenge_is_fresh(session):
            return Response(
                {"detail": "Verification session expired. Please try again."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            verification = verify_authentication_response(
                credential=request.data.get("credential"),
                expected_challenge=base64url_to_bytes(session.webauthn_challenge),
                expected_rp_id=settings.WEBAUTHN_RP_ID,
                expected_origin=settings.WEBAUTHN_ORIGIN,
                credential_public_key=base64url_to_bytes(credential.public_key),
                credential_current_sign_count=credential.sign_count,
                require_user_verification=True,
            )
        except InvalidAuthenticationResponse as exc:
            decision.step_up_failed_attempts += 1
            decision.save(update_fields=["step_up_failed_attempts"])
            attempts_remaining = max(0, STEP_UP_MAX_ATTEMPTS - decision.step_up_failed_attempts)
            raise_alert(
                alert_type=SecurityAlert.AlertType.STEP_UP_FAILED,
                staff=staff,
                patient=decision.patient,
                details={
                    "method": "webauthn",
                    "reason": str(exc),
                    "decision_id": decision.id,
                    "attempts_remaining": attempts_remaining,
                    "score": decision.score,
                    "score_band": decision.score_band,
                },
            )
            return Response(
                {"detail": "Could not verify.", "attempts_remaining": attempts_remaining},
                status=status.HTTP_400_BAD_REQUEST,
            )
        finally:
            clear_webauthn_challenge(session)

        credential.sign_count = verification.new_sign_count
        credential.last_used_at = timezone.now()
        credential.save(update_fields=["sign_count", "last_used_at"])

        decision.step_up_verified = True
        decision.step_up_verified_at = timezone.now()
        decision.save(update_fields=["step_up_verified", "step_up_verified_at"])
        return Response({"detail": "Verified.", "step_up_verified": True})


class StepUpAssistRequestView(APIView):
    """POST /api/scoring/decisions/<decision_id>/step-up/assist/request/

    The fallback path (added 2026-09-06) for a device with no biometric, or
    before the staff member has enrolled theirs: any other logged-in
    clinical colleague can vouch instead. Mirrors
    access.PendingDeviceRequest's create -> shared-list -> approve/decline
    shape. `get_or_create` avoids piling up duplicate pending rows if the
    clinician clicks more than once -- and, since the verification code
    (added 2026-09-17) is only ever generated once per request, a retry hits
    the same pending row and gets back the same code rather than a fresh one.

    Uses StepUpAssistRequestOwnSerializer -- unlike the shared queue
    (StepUpAssistListView), the requester who just created this is exactly
    who's supposed to see the code.
    """

    permission_classes = [IsClinicalStaff]

    def post(self, request, decision_id):
        decision, error = _get_own_reduced_decision(request, decision_id)
        if error:
            return error

        assist_request, _created = StepUpAssistRequest.objects.get_or_create(
            decision=decision,
            status=StepUpAssistRequest.Status.PENDING,
            defaults={"requesting_staff": request.auth.staff, "verification_code": _generate_assist_code()},
        )
        return Response(StepUpAssistRequestOwnSerializer(assist_request).data)


class StepUpAssistListView(APIView):
    """GET /api/scoring/step-up/assist-requests/ -- the queue a colleague can
    act on (added 2026-09-06). Unlike access.DeviceListView (scoped to your
    own account), this deliberately shows someone *else's* pending
    requests -- excludes the caller's own so nobody can approve their own
    request just by finding it in this list.

    Amended 2026-09-18: narrowed from "everyone, hospital-wide" to "staff on
    duty/on call in the requester's own ward" (see _is_eligible_assistant).
    A caller who isn't themselves on duty/on call sees an empty list --
    they're not an eligible assistant for anyone right now, same reasoning
    the helper applies per-request."""

    permission_classes = [IsClinicalStaff]

    def get(self, request):
        staff = request.auth.staff
        if not (staff.on_duty or staff.on_call):
            requests = StepUpAssistRequest.objects.none()
        else:
            requests = (
                StepUpAssistRequest.objects.filter(
                    status=StepUpAssistRequest.Status.PENDING, requesting_staff__ward=staff.ward
                )
                .exclude(requesting_staff=staff)
                .select_related("requesting_staff", "decision", "decision__patient")
            )
        return Response(StepUpAssistRequestSerializer(requests, many=True).data)


class StepUpAssistApproveView(APIView):
    """POST /api/scoring/step-up/assist-requests/<id>/approve/ -- {code}

    Added 2026-09-17, per the user: approving now requires the requester's
    verification code, not just a click -- proves the colleague actually
    made contact with the requester (read the code off their screen) rather
    than approving a notification from anywhere. Wrong-code attempts are
    counted against the underlying decision's existing
    step_up_failed_attempts (the same counter/cap a failed WebAuthn attempt
    already uses -- STEP_UP_MAX_ATTEMPTS), not a separate counter, since
    both are just different methods of the same step-up gate. On the
    correct code: flips step_up_verified on the linked decision, same as a
    successful biometric check would.
    """

    permission_classes = [IsClinicalStaff]

    def post(self, request, request_id):
        assist_request = get_object_or_404(
            StepUpAssistRequest, pk=request_id, status=StepUpAssistRequest.Status.PENDING
        )
        if assist_request.requesting_staff_id == request.auth.staff.id:
            return Response(
                {"detail": "You can't approve your own request."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if not _is_eligible_assistant(request.auth.staff, assist_request.requesting_staff):
            return Response(
                {"detail": "You're not eligible to assist this request -- only staff on duty or on call in the requester's own ward can."},
                status=status.HTTP_403_FORBIDDEN,
            )

        decision = assist_request.decision
        if decision.step_up_failed_attempts >= STEP_UP_MAX_ATTEMPTS:
            return Response(
                {"detail": "Too many failed attempts. The requester must ask again to retry."},
                status=status.HTTP_403_FORBIDDEN,
            )

        submitted_code = str(request.data.get("code", ""))
        if not hmac.compare_digest(submitted_code, assist_request.verification_code):
            decision.step_up_failed_attempts += 1
            decision.save(update_fields=["step_up_failed_attempts"])
            attempts_remaining = max(0, STEP_UP_MAX_ATTEMPTS - decision.step_up_failed_attempts)
            raise_alert(
                alert_type=SecurityAlert.AlertType.STEP_UP_FAILED,
                staff=assist_request.requesting_staff,
                patient=decision.patient,
                details={
                    "method": "assist",
                    "reason": "wrong verification code",
                    "attempted_by": request.auth.staff.staff_id,
                    "decision_id": decision.id,
                    "attempts_remaining": attempts_remaining,
                },
            )
            return Response(
                {"detail": "Incorrect code.", "attempts_remaining": attempts_remaining},
                status=status.HTTP_400_BAD_REQUEST,
            )

        assist_request.status = StepUpAssistRequest.Status.APPROVED
        assist_request.resolved_by = request.auth.staff
        assist_request.resolved_at = timezone.now()
        assist_request.save(update_fields=["status", "resolved_by", "resolved_at"])

        decision.step_up_verified = True
        decision.step_up_verified_at = timezone.now()
        decision.save(update_fields=["step_up_verified", "step_up_verified_at"])

        return Response(StepUpAssistRequestSerializer(assist_request).data)


class StepUpAssistDeclineView(APIView):
    """POST /api/scoring/step-up/assist-requests/<id>/decline/ -- unlike a
    plain timeout (nobody did anything wrong), a colleague explicitly
    declining to vouch is worth a security officer's attention."""

    permission_classes = [IsClinicalStaff]

    def post(self, request, request_id):
        assist_request = get_object_or_404(
            StepUpAssistRequest, pk=request_id, status=StepUpAssistRequest.Status.PENDING
        )
        if assist_request.requesting_staff_id == request.auth.staff.id:
            return Response(
                {"detail": "You can't decline your own request."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if not _is_eligible_assistant(request.auth.staff, assist_request.requesting_staff):
            return Response(
                {"detail": "You're not eligible to assist this request -- only staff on duty or on call in the requester's own ward can."},
                status=status.HTTP_403_FORBIDDEN,
            )

        assist_request.status = StepUpAssistRequest.Status.DECLINED
        assist_request.resolved_by = request.auth.staff
        assist_request.resolved_at = timezone.now()
        assist_request.save(update_fields=["status", "resolved_by", "resolved_at"])

        decision = assist_request.decision
        raise_alert(
            alert_type=SecurityAlert.AlertType.STEP_UP_FAILED,
            staff=assist_request.requesting_staff,
            patient=decision.patient,
            details={
                "method": "assist",
                "declined_by": request.auth.staff.staff_id,
                "decision_id": decision.id,
            },
        )
        return Response(StepUpAssistRequestSerializer(assist_request).data)


class PatientRecordView(APIView):
    """GET /api/scoring/patients/<patient_id>/records/

    Lives in the scoring app (not patients) because it reads AccessDecision -- keeping
    the dependency direction the same one-way order settings.py documents (patients is
    upstream of scoring; scoring may import patients, never the reverse). Returns the
    caller's own most recent decision's granted categories, actual content included --
    the client never supplies which categories it wants, only which patient.
    """

    permission_classes = [IsClinicalStaff]

    def get(self, request, patient_id):
        session = request.auth
        decision = (
            AccessDecision.objects.filter(session=session, patient_id=patient_id)
            .order_by("-computed_at")
            .first()
        )
        if decision is None:
            return Response(
                {
                    "detail": (
                        "No access decision found for this session/patient. Call "
                        "/api/scoring/decide/ with this patient_id first."
                    )
                },
                status=status.HTTP_404_NOT_FOUND,
            )

        if decision.decision_type == AccessDecision.DecisionType.ACCESS_DENIED:
            return Response(
                {
                    "detail": "Access denied.",
                    "score": decision.score,
                    "score_band": decision.score_band,
                },
                status=status.HTTP_403_FORBIDDEN,
            )

        # Step-up gate (added 2026-09-06, mechanism updated the same day --
        # see CLAUDE.md) -- CLAUDE.md's 40-69% band has always required step-up
        # verification; this is where it's actually enforced. It has to live
        # here rather than only in the UI: this view is what actually hands
        # over record content, so gating the React screen alone would leave
        # the API open to a direct call.
        #
        # Unlike the retired PIN (which could fail closed with no path
        # forward at all), this never truly strands anyone: `webauthn_
        # available` tells the frontend whether to offer the biometric button
        # for *this device*, but the colleague-assist path is always open
        # regardless, so the message stays a single, simple string.
        if (
            decision.decision_type == AccessDecision.DecisionType.REDUCED_ACCESS
            and not decision.step_up_verified
        ):
            webauthn_available = WebAuthnCredential.objects.filter(
                staff=session.staff, device__device_id=session.device_id
            ).exists()
            return Response(
                {
                    "detail": "Step-up verification required for reduced-access sessions.",
                    "step_up_required": True,
                    "webauthn_available": webauthn_available,
                    "decision_id": decision.id,
                    "score": decision.score,
                    "score_band": decision.score_band,
                },
                status=status.HTTP_403_FORBIDDEN,
            )

        records = PatientCategoryRecord.objects.filter(
            patient_id=patient_id, category__in=decision.granted_categories
        )
        return Response(
            {
                "decision_type": decision.decision_type,
                "score": decision.score,
                "score_band": decision.score_band,
                "granted_categories": decision.granted_categories,
                "records": PatientCategoryRecordSerializer(records, many=True).data,
            }
        )
