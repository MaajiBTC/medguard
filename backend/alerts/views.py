from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework.response import Response
from rest_framework.views import APIView

from staff.permissions import IsSecurityOfficer

from .models import SecurityAlert
from .serializers import AcknowledgeAlertSerializer, SecurityAlertSerializer

PAGE_SIZE = 100


class AlertListView(APIView):
    """GET /api/alerts/?alert_type=&acknowledged=true|false -- security-officer-only.

    Same permission reasoning as the Ledger views: alerts are the Security
    Dashboard's business, not the Admin dashboard's.
    """

    permission_classes = [IsSecurityOfficer]

    def get(self, request):
        alerts = SecurityAlert.objects.all()

        alert_type = request.query_params.get("alert_type")
        if alert_type:
            alerts = alerts.filter(alert_type=alert_type)

        acknowledged = request.query_params.get("acknowledged")
        if acknowledged == "true":
            alerts = alerts.filter(acknowledged_at__isnull=False)
        elif acknowledged == "false":
            alerts = alerts.filter(acknowledged_at__isnull=True)

        return Response(SecurityAlertSerializer(alerts[:PAGE_SIZE], many=True).data)


class UnacknowledgedAlertCountView(APIView):
    """GET /api/alerts/unacknowledged-count/ -- cheap poll target for the nav
    badge, mirroring access.views.DevicePendingCountView's role for the
    profile-icon dot."""

    permission_classes = [IsSecurityOfficer]

    def get(self, request):
        count = SecurityAlert.objects.filter(acknowledged_at__isnull=True).count()
        return Response({"count": count})


class AlertAcknowledgeView(APIView):
    """POST /api/alerts/<id>/acknowledge/ {note?} -- records that a named
    security officer has actually looked at this alert.

    Already-acknowledged alerts are left alone (the first acknowledgement is
    the one that counts -- re-acknowledging would overwrite who reviewed it
    and when).
    """

    permission_classes = [IsSecurityOfficer]

    def post(self, request, alert_id):
        alert = get_object_or_404(SecurityAlert, pk=alert_id)
        if alert.acknowledged:
            return Response(SecurityAlertSerializer(alert).data)

        serializer = AcknowledgeAlertSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        alert.acknowledged_at = timezone.now()
        alert.acknowledged_by_staff_id = request.auth.staff.staff_id
        alert.acknowledgement_note = serializer.validated_data.get("note", "")
        alert.save(
            update_fields=["acknowledged_at", "acknowledged_by_staff_id", "acknowledgement_note"]
        )
        return Response(SecurityAlertSerializer(alert).data)
