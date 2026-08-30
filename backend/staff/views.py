from django.contrib.auth import get_user_model
from django.db import transaction
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import Staff
from .permissions import IsAdmin, IsAdminOrSecurityOfficer
from .serializers import StaffCreateSerializer, StaffDutyWardUpdateSerializer, StaffSummarySerializer


class StaffSearchView(APIView):
    """GET /api/staff/?q=...&role=... -- q matches staff_id or full_name; role is an
    exact match against Staff.Role, used by the Admin dashboard's role-category
    drill-down so results aren't limited by the 50-row search cap below."""

    permission_classes = [IsAdmin]

    def get(self, request):
        q = request.query_params.get("q", "").strip()
        role = request.query_params.get("role", "").strip()
        staff = Staff.objects.select_related("user").all()
        if q:
            staff = staff.filter(Q(staff_id__icontains=q) | Q(full_name__icontains=q))
        if role:
            staff = staff.filter(role=role)
        return Response(StaffSummarySerializer(staff[:50], many=True).data)


class StaffSummaryView(APIView):
    """GET /api/staff/summary/ -- real counts for the Admin dashboard's overview
    page and role-category tiles (not the 50-row search cap)."""

    permission_classes = [IsAdmin]

    def get(self, request):
        by_role = {role: 0 for role, _ in Staff.Role.choices}
        for row in Staff.objects.values("role").annotate(count=Count("id")):
            by_role[row["role"]] = row["count"]
        return Response({
            "total": Staff.objects.count(),
            "on_duty": Staff.objects.filter(on_duty=True).count(),
            "by_role": by_role,
        })


class StaffCreateView(APIView):
    """POST /api/staff/create/ -- creates the auth.User + Staff row together.

    Both Admin and Security Officer can reach this endpoint, but only for
    different target roles (added 2026-08-30, per the user): an Admin can create
    any role except another admin account; a Security Officer can *only* create
    admin accounts. Shared-account roles (admin/security officer) never get a
    ward/on-duty/on-call value, regardless of what's submitted -- those fields
    aren't meaningful for a shared account (see Staff.NO_WARD_DUTY_ROLES)."""

    permission_classes = [IsAdminOrSecurityOfficer]

    def post(self, request):
        serializer = StaffCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        requester_role = request.auth.staff.role
        target_role = data["role"]
        if requester_role == Staff.Role.ADMIN and target_role == Staff.Role.ADMIN:
            return Response(
                {"detail": "Admins cannot create other admin accounts. Use the Security dashboard."},
                status=status.HTTP_403_FORBIDDEN,
            )
        if requester_role == Staff.Role.SECURITY_OFFICER and target_role != Staff.Role.ADMIN:
            return Response(
                {"detail": "Security officers can only create admin accounts."},
                status=status.HTTP_403_FORBIDDEN,
            )

        no_ward_duty = target_role in Staff.NO_WARD_DUTY_ROLES
        User = get_user_model()
        with transaction.atomic():
            user = User.objects.create_user(username=data["username"], password=data["password"])
            staff = Staff.objects.create(
                user=user,
                staff_id=data["staff_id"],
                full_name=data["full_name"],
                role=target_role,
                ward="" if no_ward_duty else data.get("ward", ""),
                on_duty=False if no_ward_duty else data.get("on_duty", False),
                on_call=False if no_ward_duty else data.get("on_call", False),
            )

        return Response(StaffSummarySerializer(staff).data, status=status.HTTP_201_CREATED)


class StaffDutyWardUpdateView(APIView):
    """PATCH /api/staff/<id>/duty/ -- the manual population path CLAUDE.md requires
    for ward/on_duty (never computed by a scheduler). Rejected outright for admin/
    security officer accounts (added 2026-08-30) -- shared accounts with no ward/
    on-duty/on-call concept, see Staff.NO_WARD_DUTY_ROLES."""

    permission_classes = [IsAdmin]

    def patch(self, request, staff_id):
        staff = get_object_or_404(Staff, pk=staff_id)
        if staff.role in Staff.NO_WARD_DUTY_ROLES:
            return Response(
                {"detail": "Ward/on-duty/on-call don't apply to this role's shared account."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        serializer = StaffDutyWardUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        update_fields = ["updated_at"]
        if "ward" in serializer.validated_data:
            staff.ward = serializer.validated_data["ward"]
            update_fields.append("ward")
        if "on_duty" in serializer.validated_data:
            staff.on_duty = serializer.validated_data["on_duty"]
            update_fields.append("on_duty")
        if "on_call" in serializer.validated_data:
            staff.on_call = serializer.validated_data["on_call"]
            update_fields.append("on_call")
        staff.save(update_fields=update_fields)

        return Response(StaffSummarySerializer(staff).data)


class StaffDeactivateView(APIView):
    """POST /api/staff/<id>/deactivate/ -- blocks login (Django's authenticate()
    already refuses inactive users) without touching the Staff row or its history."""

    permission_classes = [IsAdmin]

    def post(self, request, staff_id):
        staff = get_object_or_404(Staff, pk=staff_id)
        staff.user.is_active = False
        staff.user.save(update_fields=["is_active"])
        return Response(StaffSummarySerializer(staff).data)


class StaffReactivateView(APIView):
    """POST /api/staff/<id>/reactivate/"""

    permission_classes = [IsAdmin]

    def post(self, request, staff_id):
        staff = get_object_or_404(Staff, pk=staff_id)
        staff.user.is_active = True
        staff.user.save(update_fields=["is_active"])
        return Response(StaffSummarySerializer(staff).data)
