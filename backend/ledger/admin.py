from django.contrib import admin

from .models import LedgerEntry


@admin.register(LedgerEntry)
class LedgerEntryAdmin(admin.ModelAdmin):
    """Read-only -- the ledger is append-only end to end, including from the admin.
    Gives visibility into the ledger before the real Security Dashboard exists.
    """

    list_display = ("sequence", "occurred_at", "event_type", "staff_id", "patient_hospital_number")
    list_filter = ("event_type",)
    search_fields = ("staff_id", "staff_full_name", "patient_hospital_number", "session_token")
    readonly_fields = [f.name for f in LedgerEntry._meta.fields]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
