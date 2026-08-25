from django.contrib import admin

from .models import AccessSession


@admin.register(AccessSession)
class AccessSessionAdmin(admin.ModelAdmin):
    list_display = ("staff", "is_active", "started_at", "ended_at", "device_type", "network_segment")
    list_filter = ("is_active", "device_type")
    search_fields = ("staff__staff_id", "staff__full_name", "device_id", "token")
    readonly_fields = ("token", "started_at")
    autocomplete_fields = ("staff",)
