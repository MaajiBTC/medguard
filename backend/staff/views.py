from django.contrib.auth import get_user_model
from django.db import transaction
from django.db.models import Q
from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import Staff
from .permissions import IsAdmin
from .serializers import StaffCreateSerializer, StaffDutyWardUpdateSerializer, StaffSummarySerializer


class StaffSearchView(APIView):
    """GET /api/staff/?q=... -- matches staff_id or full_name."""

    permission_classes = [IsAdmin]

    def get(self, request):
        q = request.query_params.get("q", "").strip()
        staff = Staff.objects.select_related("user").all()
        if q:
            staff = staff.filter(Q(staff_id__icontains=q) | Q(full_name__icontains=q))
        return Response(StaffSummarySerializer(staff[:50], many=True).data)


class StaffCreateView(APIView):
    """POST /api/staff/create/ -- creates the auth.User + Staff row together."""

    permission_classes = [IsAdmin]

    def post(self, request):
        serializer = StaffCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        User = get_user_model()
        with transaction.atomic():
            user = User.objects.create_user(username=data["username"], password=data["password"])
            staff = Staff.objects.create(
                user=user,
                staff_id=data["staff_id"],
                full_name=data["full_name"],
                role=data["role"],
                ward=data.get("ward", ""),
                on_duty=data.get("on_duty", False),
            )

        return Response(StaffSummarySerializer(staff).data, status=status.HTTP_201_CREATED)


class StaffDutyWardUpdateView(APIView):
    """PATCH /api/staff/<id>/duty/ -- the manual population path CLAUDE.md requires
    for ward/on_duty (never computed by a scheduler)."""

    permission_classes = [IsAdmin]

    def patch(self, request, staff_id):
        staff = get_object_or_404(Staff, pk=staff_id)
        serializer = StaffDutyWardUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        update_fields = ["updated_at"]
        if "ward" in serializer.validated_data:
            staff.ward = serializer.validated_data["ward"]
            update_fields.append("ward")
        if "on_duty" in serializer.validated_data:
            staff.on_duty = serializer.validated_data["on_duty"]
            update_fields.append("on_duty")
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
