from django.contrib.auth import authenticate
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from captures.serializers import KeystrokeFeaturesSerializer
from staff.models import Staff

from .models import AccessSession, Device, PendingDeviceRequest
from .serializers import ChangePasswordSerializer, DeviceSerializer, PendingDeviceRequestSerializer
from .services import create_session


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

        user = authenticate(request, username=username, password=password)
        if user is None:
            return Response(
                {"detail": "Invalid credentials."},
                status=status.HTTP_401_UNAUTHORIZED,
            )

        staff = getattr(user, "staff_profile", None)
        if staff is None:
            return Response(
                {"detail": "This account has no associated staff profile."},
                status=status.HTTP_403_FORBIDDEN,
            )

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


class LogoutView(APIView):
    """POST /api/access/logout/ — ends the caller's own current session."""

    def post(self, request):
        session = request.auth
        session.is_active = False
        session.ended_at = timezone.now()
        session.save(update_fields=["is_active", "ended_at"])
        return Response(status=status.HTTP_204_NO_CONTENT)


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
                "ward": staff.ward,
                "started_at": session.started_at,
                "ended_at": session.ended_at,
                "is_active": session.is_active,
                "device_id": session.device_id,
                "device_type": session.device_type,
                "user_agent": session.user_agent,
                "network_segment": session.network_segment,
            }
        )
