from django.contrib import admin

from .models import BehavioralCapture, ContextualCapture


@admin.register(BehavioralCapture)
class BehavioralCaptureAdmin(admin.ModelAdmin):
    list_display = (
        "session",
        "mouse_event_count",
        "touch_event_count",
        "updated_at",
    )
    readonly_fields = (
        "keystroke_features",
        "mouse_events",
        "touch_events",
        "mouse_event_count",
        "touch_event_count",
        "updated_at",
    )
    search_fields = ("session__staff__staff_id", "session__staff__full_name")
    autocomplete_fields = ("session",)


@admin.register(ContextualCapture)
class ContextualCaptureAdmin(admin.ModelAdmin):
    list_display = (
        "session",
        "on_duty_at_login",
        "ward_assignment_at_login",
        "target_patient",
        "patient_assignment_status",
    )
    list_filter = ("patient_assignment_status", "on_duty_at_login")
    search_fields = ("session__staff__staff_id", "session__staff__full_name")
    autocomplete_fields = ("session", "target_patient")
