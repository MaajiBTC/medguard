from django.contrib import admin

from .models import AdminActionLog, Staff


@admin.register(Staff)
class StaffAdmin(admin.ModelAdmin):
    list_display = ("staff_id", "full_name", "role", "ward", "on_duty", "user")
    list_filter = ("role", "on_duty", "ward")
    search_fields = ("staff_id", "full_name", "user__username")
    autocomplete_fields = ("user",)


@admin.register(AdminActionLog)
class AdminActionLogAdmin(admin.ModelAdmin):
    """Read-only -- an audit trail shouldn't be editable from the admin
    either, same reasoning as LedgerEntryAdmin."""

    list_display = ("occurred_at", "actor_staff_id", "action", "target_staff_id", "target_role")
    list_filter = ("action",)
    search_fields = ("actor_staff_id", "actor_full_name", "target_staff_id", "target_full_name")
    readonly_fields = [f.name for f in AdminActionLog._meta.fields]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
