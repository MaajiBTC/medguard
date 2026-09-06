from django.contrib.auth import get_user_model
from django.db import transaction
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from access.services import clear_lockout

from .models import AdminActionLog, Staff
from .permissions import IsAdmin, IsAdminOrSecurityOfficer
from .serializers import (
    AdminActionLogSerializer,
    StaffCreateSerializer,
    StaffDutyWardUpdateSerializer,
    StaffSummarySerializer,
)
from .services import record_admin_action


class StaffSearchView(APIView):
    """GET /api/staff/?q=...&role=... -- q matches staff_id or full_name; role is an
    exact match against Staff.Role, used by the Admin dashboard's role-category
    drill-down so results aren't limited by the 50-row search cap below.

    Opened to IsAdminOrSecurityOfficer (added 2026-08-30) -- the Security
    dashboard's Staff activity page (search a staff member, then view their
    Ledger history) reuses this same endpoint rather than duplicating search
    logic; it never needed Admin-only management data, just lookup."""

    permission_classes = [IsAdminOrSecurityOfficer]

    def get(self, request):
        q = request.query_params.get("q", "").strip()
        role = request.query_params.get("role", "").strip()
        staff = Staff.objects.select_related("user").all()
        if q:
            staff = staff.filter(Q(staff_id__icontains=q) | Q(full_name__icontains=q))
        if role:
            staff = staff.filter(role=role)
        return Response(StaffSummarySerializer(staff[:50], many=True, context={"request": request}).data)


class StaffSummaryView(APIView):
    """GET /api/staff/summary/ -- real counts for the Admin dashboard's overview
    page and role-category tiles (not the 50-row search cap). on_duty_by_role is
    scoped to Staff.CLINICAL_ROLES -- admin/security_officer are
    NO_WARD_DUTY_ROLES and excluded from Staff browsing entirely, so an on-duty
    breakdown for them wouldn't mean anything here."""

    permission_classes = [IsAdmin]

    def get(self, request):
        by_role = {role: 0 for role, _ in Staff.Role.choices}
        for row in Staff.objects.values("role").annotate(count=Count("id")):
            by_role[row["role"]] = row["count"]

        on_duty_by_role = {role.value: 0 for role in Staff.CLINICAL_ROLES}
        on_duty_rows = Staff.objects.filter(on_duty=True, role__in=Staff.CLINICAL_ROLES)
        for row in on_duty_rows.values("role").annotate(count=Count("id")):
            on_duty_by_role[row["role"]] = row["count"]

        return Response({
            "total": Staff.objects.count(),
            "on_duty": Staff.objects.filter(on_duty=True).count(),
            "on_call": Staff.objects.filter(on_call=True).count(),
            "by_role": by_role,
            "on_duty_by_role": on_duty_by_role,
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
            record_admin_action(
                actor=request.auth.staff, action=AdminActionLog.Action.STAFF_CREATED, target=staff
            )

        return Response(
            StaffSummarySerializer(staff, context={"request": request}).data, status=status.HTTP_201_CREATED
        )


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

        return Response(StaffSummarySerializer(staff, context={"request": request}).data)


class StaffDeactivateView(APIView):
    """POST /api/staff/<id>/deactivate/ -- blocks login (Django's authenticate()
    already refuses inactive users) without touching the Staff row or its history."""

    permission_classes = [IsAdmin]

    def post(self, request, staff_id):
        staff = get_object_or_404(Staff, pk=staff_id)
        staff.user.is_active = False
        staff.user.save(update_fields=["is_active"])
        record_admin_action(
            actor=request.auth.staff, action=AdminActionLog.Action.STAFF_DEACTIVATED, target=staff
        )
        return Response(StaffSummarySerializer(staff, context={"request": request}).data)


class StaffReactivateView(APIView):
    """POST /api/staff/<id>/reactivate/"""

    permission_classes = [IsAdmin]

    def post(self, request, staff_id):
        staff = get_object_or_404(Staff, pk=staff_id)
        staff.user.is_active = True
        staff.user.save(update_fields=["is_active"])
        record_admin_action(
            actor=request.auth.staff, action=AdminActionLog.Action.STAFF_REACTIVATED, target=staff
        )
        return Response(StaffSummarySerializer(staff, context={"request": request}).data)


class StaffDeleteView(APIView):
    """POST /api/staff/<id>/delete/ -- a real, permanent delete (added
    2026-08-30, per the user, a deliberate exception to this project's usual
    "deactivate, never delete" rule -- see StaffDeactivateView above, which
    stays available for the reversible case). 400s for admin/security_officer
    targets -- defense in depth, since the Admin dashboard's Staff panel this
    button lives on already can't reach those rows, but the endpoint itself
    shouldn't rely on that.

    Deletes staff.user (auth.User) rather than the Staff row directly --
    Staff.user is a OneToOneField(..., on_delete=CASCADE), so removing the
    User cascades to the Staff row and everything else that FKs to it
    (AccessSession, Device, PendingDeviceRequest, patient assignments,
    behavioral baselines) through their existing cascade relationships.
    ledger.LedgerEntry rows are untouched -- that app denormalizes staff
    identity instead of holding a foreign key (see ledger/models.py), so a
    deleted staff member's historical audit trail survives intact."""

    permission_classes = [IsAdmin]

    def post(self, request, staff_id):
        staff = get_object_or_404(Staff, pk=staff_id)
        if staff.role in Staff.NO_WARD_DUTY_ROLES:
            return Response(
                {"detail": "Admin/security officer accounts can't be deleted from here."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        staff.user.delete()
        # staff.staff_id/full_name/role stay readable on the in-memory Python
        # object after delete() -- only pk/id get cleared -- so this still
        # captures the right target identity even though the row is gone.
        record_admin_action(
            actor=request.auth.staff, action=AdminActionLog.Action.STAFF_DELETED, target=staff
        )
        return Response(status=status.HTTP_204_NO_CONTENT)


class StaffUnlockView(APIView):
    """POST /api/staff/<id>/unlock/ -- clears a brute-force lockout early
    (added 2026-09-06). Without this an admin would have to wait out
    settings.LOGIN_LOCKOUT_MINUTES; the lock does expire on its own either
    way (see access.services), this just skips the wait.

    Always returns 200 with the updated row, even if the account wasn't
    actually locked -- "make sure this account isn't locked" is idempotent by
    nature, and a 400 here would just be noise for the admin.
    """

    permission_classes = [IsAdmin]

    def post(self, request, staff_id):
        staff = get_object_or_404(Staff, pk=staff_id)
        clear_lockout(staff.user.username)
        record_admin_action(
            actor=request.auth.staff, action=AdminActionLog.Action.STAFF_UNLOCKED, target=staff
        )
        return Response(StaffSummarySerializer(staff, context={"request": request}).data)


class AdminActionListView(APIView):
    """GET /api/staff/admin-actions/?actor_staff_id=... -- an admin's own
    logged actions (added 2026-08-31, per the user, for the Security
    dashboard's Admins page). Same permission reasoning as StaffSearchView --
    this is a lookup, not account management."""

    permission_classes = [IsAdminOrSecurityOfficer]

    def get(self, request):
        actor_staff_id = request.query_params.get("actor_staff_id", "").strip()
        actions = AdminActionLog.objects.all()
        if actor_staff_id:
            actions = actions.filter(actor_staff_id=actor_staff_id)
        return Response(AdminActionLogSerializer(actions[:50], many=True).data)
