from django.contrib import admin

from .models import SecurityAlert


@admin.register(SecurityAlert)
class SecurityAlertAdmin(admin.ModelAdmin):
    """Read-only in admin -- alerts are raised by alerts.services.raise_alert()
    and acknowledged through the Security Dashboard, never hand-edited."""

    list_display = ("id", "alert_type", "staff_id", "raised_at", "acknowledged_at")
    list_filter = ("alert_type",)
    search_fields = ("staff_id", "staff_full_name", "patient_hospital_number")

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
