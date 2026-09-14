from django.conf import settings
from django.contrib.auth import authenticate
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import status
from rest_framework.parsers import MultiPartParser
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView
from webauthn import base64url_to_bytes, generate_registration_options, verify_registration_response
from webauthn.helpers import bytes_to_base64url, options_to_json_dict
from webauthn.helpers.exceptions import InvalidRegistrationResponse
from webauthn.helpers.structs import (
    AuthenticatorAttachment,
    AuthenticatorSelectionCriteria,
    ResidentKeyRequirement,
    UserVerificationRequirement,
)

from alerts.models import SecurityAlert
from alerts.services import raise_alert
from captures.serializers import KeystrokeFeaturesSerializer
from staff.models import Staff
from staff.permissions import IsClinicalStaff

from .models import AccessSession, Device, PendingDeviceRequest, WebAuthnCredential
from .serializers import (
    ChangePasswordSerializer,
    DeviceSerializer,
    PendingDeviceRequestSerializer,
    RegisterSyncKeySerializer,
)
from .services import (
    clear_webauthn_challenge,
    create_session,
    is_locked_out,
    lockout_remaining_minutes,
    record_login_attempt,
    webauthn_challenge_is_fresh,
)


class LoginView(APIView):
    """POST /api/access/login/

    Authenticates (username/password against Django's built-in auth.User), looks up
    the linked Staff profile (403 if none), then either creates an AccessSession (via
    access.services.create_session) or -- for clinical roles logging in from a device
    that isn't their approved one yet -- returns a pending-approval response instead
    (see the one-device-per-account block below).

    No auth required to call this endpoint (that's the point — it's how you get a
    token), so it's excluded from the default AccessSessionAuthentication/
    IsAuthenticated settings.
    """

    authentication_classes = []
    permission_classes = [AllowAny]

    def post(self, request):
        username = request.data.get("username")
        password = request.data.get("password")
        device_id = request.data.get("device_id")
        device_type = request.data.get("device_type", "")
        user_agent = request.META.get("HTTP_USER_AGENT", "")[:512]

        # Derived, anonymized keystroke-dynamics features from the login form itself
        # (never raw key identity — see CLAUDE.md's Behavioral module). Optional and
        # best-effort: malformed/missing data just means no login-time keystroke
        # baseline for this session, not a failed login.
        login_keystroke_features = None
        keystroke_features_data = request.data.get("keystroke_features")
        if keystroke_features_data:
            kf_serializer = KeystrokeFeaturesSerializer(data=keystroke_features_data)
            if kf_serializer.is_valid():
                login_keystroke_features = dict(kf_serializer.validated_data)

        if not username or not password:
            return Response(
                {"detail": "username and password are required."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if not device_id:
            return Response(
                {"detail": "device_id is required."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        ip_address = request.META.get("REMOTE_ADDR") or None

        # Brute-force lockout (added 2026-09-06) -- checked BEFORE authenticate(),
        # so a locked account is refused even when the password is finally
        # guessed correctly. That's the whole point: the attacker gets no signal
        # that they've landed on the right one.
        if is_locked_out(username):
            minutes = lockout_remaining_minutes(username)
            record_login_attempt(username, succeeded=False, device_id=device_id, ip_address=ip_address)
            return Response(
                {
                    "detail": (
                        f"Account temporarily locked after too many failed attempts. "
                        f"Try again in {minutes} minute{'s' if minutes != 1 else ''}, "
                        f"or ask an administrator to unlock it."
                    ),
                    "locked_out": True,
                    "minutes_remaining": minutes,
                },
                status=status.HTTP_429_TOO_MANY_REQUESTS,
            )

        user = authenticate(request, username=username, password=password)
        if user is None:
            record_login_attempt(username, succeeded=False, device_id=device_id, ip_address=ip_address)
            if is_locked_out(username):
                # This failure is the one that crossed the threshold.
                raise_alert(
                    alert_type=SecurityAlert.AlertType.LOGIN_LOCKOUT,
                    staff=Staff.objects.filter(user__username=username).first(),
                    details={
                        "username": username,
                        "failed_attempts": settings.LOGIN_MAX_FAILED_ATTEMPTS,
                        "lockout_minutes": settings.LOGIN_LOCKOUT_MINUTES,
                        "device_id": device_id,
                        "ip_address": ip_address,
                    },
                )
            return Response(
                {"detail": "Invalid credentials."},
                status=status.HTTP_401_UNAUTHORIZED,
            )

        staff = getattr(user, "staff_profile", None)
        if staff is None:
            record_login_attempt(username, succeeded=False, device_id=device_id, ip_address=ip_address)
            return Response(
                {"detail": "This account has no associated staff profile."},
                status=status.HTTP_403_FORBIDDEN,
            )

        record_login_attempt(username, succeeded=True, device_id=device_id, ip_address=ip_address)

        # One device per account (added 2026-08-30), clinical roles only -- admin/
        # security_officer are documented shared accounts (Staff.NO_WARD_DUTY_ROLES)
        # and skip this entirely, logging in exactly as before. This only ever runs
        # after authenticate() has already verified the password, so an attacker
        # without the password never reaches it.
        if staff.role in Staff.CLINICAL_ROLES:
            staff_devices = Device.objects.filter(staff=staff)
            known_device = staff_devices.filter(device_id=device_id).first()

            if known_device is not None:
                known_device.device_type = device_type
                known_device.user_agent = user_agent
                known_device.save(update_fields=["device_type", "user_agent", "last_seen_at"])
            elif not staff_devices.exists():
                Device.objects.create(
                    staff=staff,
                    device_id=device_id,
                    device_type=device_type,
                    user_agent=user_agent,
                    is_primary=True,
                )
            else:
                pending, _ = PendingDeviceRequest.objects.get_or_create(
                    staff=staff,
                    device_id=device_id,
                    status=PendingDeviceRequest.Status.PENDING,
                    defaults={"device_type": device_type, "user_agent": user_agent},
                )
                return Response(
                    {"status": "pending_approval", "poll_token": pending.poll_token},
                    status=status.HTTP_202_ACCEPTED,
                )

        session = create_session(staff, device_id, device_type, user_agent, login_keystroke_features)

        return Response(
            {
                "token": session.token,
                "staff": {
                    "staff_id": staff.staff_id,
                    "full_name": staff.full_name,
                    "role": staff.role,
                },
            },
            status=status.HTTP_201_CREATED,
        )


class DeviceRequestPollView(APIView):
    """GET /api/access/device-requests/<poll_token>/poll/ — unauthenticated (the
    requesting device has no token yet, that's the whole point of this endpoint).
    Keyed by the opaque poll_token, not the row's integer id, so it can't be
    enumerated by a caller who doesn't already hold it."""

    authentication_classes = []
    permission_classes = [AllowAny]

    def get(self, request, poll_token):
        pending = get_object_or_404(PendingDeviceRequest, poll_token=poll_token)

        if pending.status == PendingDeviceRequest.Status.PENDING:
            return Response({"status": "pending"})
        if pending.status == PendingDeviceRequest.Status.REJECTED:
            return Response({"status": "rejected"})

        # Approved -- hand back the token exactly once, then clear it so a leaked
        # poll_token can't be replayed later to re-fetch a live session token.
        token = pending.session_token
        if not token:
            return Response({"status": "approved", "token": None})
        pending.session_token = ""
        pending.save(update_fields=["session_token"])
        staff = pending.staff
        return Response(
            {
                "status": "approved",
                "token": token,
                "staff": {
                    "staff_id": staff.staff_id,
                    "full_name": staff.full_name,
                    "role": staff.role,
                },
            }
        )


class DeviceListView(APIView):
    """GET /api/access/devices/ — the caller's own approved devices plus their still-
    pending requests. Self-service like ChangePasswordView/CurrentSessionView: any
    logged-in staff member sees only their own account's rows."""

    def get(self, request):
        staff = request.auth.staff
        devices = Device.objects.filter(staff=staff)
        pending = PendingDeviceRequest.objects.filter(
            staff=staff, status=PendingDeviceRequest.Status.PENDING
        )
        return Response(
            {
                "devices": DeviceSerializer(devices, many=True).data,
                "pending_requests": PendingDeviceRequestSerializer(pending, many=True).data,
            }
        )


class DevicePendingCountView(APIView):
    """GET /api/access/devices/pending-count/ — cheap poll target for the header's
    profile-icon badge, so it doesn't have to pull the full device list every cycle."""

    def get(self, request):
        count = PendingDeviceRequest.objects.filter(
            staff=request.auth.staff, status=PendingDeviceRequest.Status.PENDING
        ).count()
        return Response({"count": count})


class DeviceApproveView(APIView):
    """POST /api/access/device-requests/<request_id>/approve/ — grants the pending
    device a real session (via access.services.create_session, the same path a
    normal login uses) and records it as a non-primary approved Device."""

    def post(self, request, request_id):
        pending = get_object_or_404(
            PendingDeviceRequest,
            pk=request_id,
            staff=request.auth.staff,
            status=PendingDeviceRequest.Status.PENDING,
        )
        Device.objects.create(
            staff=pending.staff,
            device_id=pending.device_id,
            device_type=pending.device_type,
            user_agent=pending.user_agent,
            is_primary=False,
        )
        session = create_session(pending.staff, pending.device_id, pending.device_type, pending.user_agent)
        pending.status = PendingDeviceRequest.Status.APPROVED
        pending.session_token = session.token
        pending.resolved_at = timezone.now()
        pending.save(update_fields=["status", "session_token", "resolved_at"])
        return Response(status=status.HTTP_204_NO_CONTENT)


class DeviceRejectView(APIView):
    """POST /api/access/device-requests/<request_id>/reject/ — no session is ever
    created for a rejected request."""

    def post(self, request, request_id):
        pending = get_object_or_404(
            PendingDeviceRequest,
            pk=request_id,
            staff=request.auth.staff,
            status=PendingDeviceRequest.Status.PENDING,
        )
        pending.status = PendingDeviceRequest.Status.REJECTED
        pending.resolved_at = timezone.now()
        pending.save(update_fields=["status", "resolved_at"])
        return Response(status=status.HTTP_204_NO_CONTENT)


class DeviceRemoveView(APIView):
    """POST /api/access/devices/<device_pk>/remove/ — the primary device can never
    be removed; removing any other device also ends its still-active session, if
    any, so the removal actually revokes access rather than just tidying a list."""

    def post(self, request, device_pk):
        device = get_object_or_404(Device, pk=device_pk, staff=request.auth.staff)
        if device.is_primary:
            return Response(
                {"detail": "The primary device cannot be removed."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        AccessSession.objects.filter(
            staff=device.staff, device_id=device.device_id, is_active=True
        ).update(is_active=False, ended_at=timezone.now())
        device.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class RegisterSyncKeyView(APIView):
    """POST /api/access/devices/register-signing-key/ -- Offline Mode (build
    step 6). Self-service, same "acts on the caller's own Device row"
    pattern as DeviceListView -- {device_id, public_key} where public_key is
    this device's ECDSA P-256 public key (base64 SPKI), generated and kept
    client-side (the private key never leaves the device, non-extractable in
    IndexedDB). Registering it here is what lets OfflineSyncView later trust
    a signed batch from this device; a device with no key registered here
    can never sync (CLAUDE.md: "unsigned/unregistered device batches are
    rejected"). 404, not 403, if this isn't already an approved device for
    the caller -- same probing-defense pattern used elsewhere in this app.
    """

    permission_classes = [IsClinicalStaff]

    def post(self, request):
        serializer = RegisterSyncKeySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        device = get_object_or_404(
            Device,
            staff=request.auth.staff,
            device_id=serializer.validated_data["device_id"],
        )
        device.sync_public_key = serializer.validated_data["public_key"]
        device.save(update_fields=["sync_public_key"])
        return Response({"detail": "Signing key registered."})


class LogoutView(APIView):
    """POST /api/access/logout/ — ends the caller's own current session."""

    def post(self, request):
        session = request.auth
        session.is_active = False
        session.ended_at = timezone.now()
        session.save(update_fields=["is_active", "ended_at"])
        return Response(status=status.HTTP_204_NO_CONTENT)


def _photo_url(request, staff):
    """Absolute URL for a staff member's uploaded photo, or None -- shared by
    every view that returns staff info alongside a photo (added 2026-09-05)."""
    return request.build_absolute_uri(staff.photo.url) if staff.photo else None


class ChangePasswordView(APIView):
    """POST /api/access/change-password/ -- any logged-in staff member changes
    their own password (self-service, from the frontend's Profile page). Default
    IsAuthenticated is the only gate needed; there's no role restriction since
    this only ever acts on the caller's own account."""

    def post(self, request):
        serializer = ChangePasswordSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = request.auth.staff.user
        if not user.check_password(serializer.validated_data["current_password"]):
            return Response(
                {"detail": "Current password is incorrect."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        user.set_password(serializer.validated_data["new_password"])
        user.save()
        return Response({"detail": "Password updated."})


class ProfilePhotoView(APIView):
    """POST (multipart, {photo: <file>}) to upload/replace the caller's own
    profile photo; DELETE to remove it. Self-service like ChangePasswordView
    above -- always request.auth.staff, no staff_id in the URL. Added
    2026-09-05, per the user, so the Security dashboard can show a real photo
    instead of RoleAvatar's cartoon once one exists."""

    parser_classes = [MultiPartParser]

    def post(self, request):
        photo = request.FILES.get("photo")
        if not photo:
            return Response({"detail": "photo file is required."}, status=status.HTTP_400_BAD_REQUEST)
        staff = request.auth.staff
        staff.photo = photo
        staff.save(update_fields=["photo"])
        return Response({"photo_url": _photo_url(request, staff)})

    def delete(self, request):
        staff = request.auth.staff
        staff.photo.delete(save=True)
        return Response(status=status.HTTP_204_NO_CONTENT)


class CurrentSessionView(APIView):
    """GET /api/access/session/current/ — the caller's own session, plus live (not
    login-time-snapshotted) duty status/ward, so dashboards can show current status
    without a separate endpoint. Contrast with ContextualCapture's
    on_duty_at_login/ward_assignment_at_login, which are deliberately frozen
    snapshots for historical accuracy (see captures/models.py) -- this view is for
    live display, not scoring or audit history."""

    def get(self, request):
        session = request.auth
        staff = session.staff
        return Response(
            {
                "id": session.id,
                "staff_id": staff.staff_id,
                "staff_full_name": staff.full_name,
                "role": staff.role,
                "on_duty": staff.on_duty,
                "on_call": staff.on_call,
                "ward": staff.ward,
                "photo_url": _photo_url(request, staff),
                "started_at": session.started_at,
                "ended_at": session.ended_at,
                "is_active": session.is_active,
                "device_id": session.device_id,
                "device_type": session.device_type,
                "user_agent": session.user_agent,
                "network_segment": session.network_segment,
                # Added 2026-09-06: does THIS device have a step-up biometric
                # credential enrolled -- lets the clinical dashboard decide
                # whether to offer the biometric button or go straight to
                # "ask a colleague" without a separate round trip.
                "has_webauthn_credential": WebAuthnCredential.objects.filter(
                    staff=staff, device__device_id=session.device_id
                ).exists(),
            }
        )


class WebAuthnRegistrationOptionsView(APIView):
    """POST /api/access/webauthn/registration-options/ -- self-service,
    clinical roles only (admin/security officer never go through scoring, so
    they'd have no use for step-up at all). First step of enrolling THIS
    device's biometric unlock (Face ID/fingerprint/Windows Hello) as a
    step-up credential (added 2026-09-06, replacing the typed PIN).

    `authenticator_attachment=PLATFORM` is what restricts the browser to the
    device's own built-in authenticator rather than also offering a USB
    security key -- this is specifically about "this device", not "any
    credential this person owns".
    """

    permission_classes = [IsClinicalStaff]

    def post(self, request):
        session = request.auth
        staff = session.staff

        options = generate_registration_options(
            rp_id=settings.WEBAUTHN_RP_ID,
            rp_name=settings.WEBAUTHN_RP_NAME,
            user_id=str(staff.id).encode("utf-8"),
            user_name=staff.staff_id,
            user_display_name=staff.full_name,
            authenticator_selection=AuthenticatorSelectionCriteria(
                authenticator_attachment=AuthenticatorAttachment.PLATFORM,
                user_verification=UserVerificationRequirement.REQUIRED,
                resident_key=ResidentKeyRequirement.DISCOURAGED,
            ),
        )
        session.webauthn_challenge = bytes_to_base64url(options.challenge)
        session.webauthn_challenge_created_at = timezone.now()
        session.save(update_fields=["webauthn_challenge", "webauthn_challenge_created_at"])

        return Response(options_to_json_dict(options))


class WebAuthnRegisterView(APIView):
    """POST /api/access/webauthn/register/ -- {credential: <navigator.credentials.create() response>}

    Second step: verifies the browser's response against the challenge from
    registration-options/ above, then creates (or replaces) THIS device's
    WebAuthnCredential. `device` is looked up by the session's own
    device_id -- this only ever enrolls the device the staff member is
    currently sitting at, never an arbitrary one.
    """

    permission_classes = [IsClinicalStaff]

    def post(self, request):
        session = request.auth
        staff = session.staff

        if not webauthn_challenge_is_fresh(session):
            return Response(
                {"detail": "Registration session expired. Please try again."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        device = get_object_or_404(Device, staff=staff, device_id=session.device_id)

        try:
            verification = verify_registration_response(
                credential=request.data.get("credential"),
                expected_challenge=base64url_to_bytes(session.webauthn_challenge),
                expected_rp_id=settings.WEBAUTHN_RP_ID,
                expected_origin=settings.WEBAUTHN_ORIGIN,
                require_user_verification=True,
            )
        except InvalidRegistrationResponse as exc:
            return Response({"detail": f"Could not verify registration: {exc}"}, status=status.HTTP_400_BAD_REQUEST)
        finally:
            clear_webauthn_challenge(session)

        WebAuthnCredential.objects.update_or_create(
            device=device,
            defaults={
                "staff": staff,
                "credential_id": bytes_to_base64url(verification.credential_id),
                "public_key": bytes_to_base64url(verification.credential_public_key),
                "sign_count": verification.sign_count,
            },
        )
        return Response({"detail": "Step-up verification enabled on this device."})
