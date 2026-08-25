from django.conf import settings
from django.contrib.auth import authenticate
from django.db import transaction
from django.utils import timezone
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from captures.models import BehavioralCapture, ContextualCapture

from .models import AccessSession


class LoginView(APIView):
    """POST /api/access/login/

    Authenticates (username/password against Django's built-in auth.User), looks up
    the linked Staff profile (403 if none), then creates an AccessSession plus one
    empty BehavioralCapture and one pre-filled ContextualCapture in a single
    transaction. Returns the opaque bearer token for the new session.

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

        with transaction.atomic():
            session = AccessSession.objects.create(
                staff=staff,
                device_id=device_id,
                device_type=device_type,
                user_agent=request.META.get("HTTP_USER_AGENT", "")[:512],
                network_segment=getattr(settings, "WORKSTATION_NETWORK_SEGMENT", "unknown"),
            )
            BehavioralCapture.objects.create(session=session)
            ContextualCapture.objects.create(
                session=session,
                on_duty_at_login=staff.on_duty,
                ward_assignment_at_login=staff.ward,
            )

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


class LogoutView(APIView):
    """POST /api/access/logout/ — ends the caller's own current session."""

    def post(self, request):
        session = request.auth
        session.is_active = False
        session.ended_at = timezone.now()
        session.save(update_fields=["is_active", "ended_at"])
        return Response(status=status.HTTP_204_NO_CONTENT)


class CurrentSessionView(APIView):
    """GET /api/access/session/current/ — debug view of the caller's own session."""

    def get(self, request):
        session = request.auth
        staff = session.staff
        return Response(
            {
                "id": session.id,
                "staff_id": staff.staff_id,
                "staff_full_name": staff.full_name,
                "role": staff.role,
                "started_at": session.started_at,
                "ended_at": session.ended_at,
                "is_active": session.is_active,
                "device_id": session.device_id,
                "device_type": session.device_type,
                "user_agent": session.user_agent,
                "network_segment": session.network_segment,
            }
        )
