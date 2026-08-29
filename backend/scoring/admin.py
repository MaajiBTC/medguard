from django.contrib import admin

from .models import AccessDecision, BehavioralBaseline, DisasterModeEvent


@admin.register(BehavioralBaseline)
class BehavioralBaselineAdmin(admin.ModelAdmin):
    list_display = ("staff", "sample_count", "updated_at")
    readonly_fields = (
        "staff",
        "sample_count",
        "keystroke_stats",
        "mouse_stats",
        "known_device_ids",
        "login_hour_stats",
        "known_network_segments",
        "updated_at",
    )
    search_fields = ("staff__staff_id", "staff__full_name")
    autocomplete_fields = ("staff",)


@admin.register(AccessDecision)
class AccessDecisionAdmin(admin.ModelAdmin):
    list_display = ("session", "patient", "decision_type", "score", "role_rule_path", "computed_at")
    list_filter = ("decision_type", "score_band", "role_rule_path")
    readonly_fields = (
        "session",
        "patient",
        "computed_at",
        "gate_passed",
        "score",
        "score_band",
        "decision_type",
        "granted_categories",
        "role_rule_path",
        "factor_breakdown",
    )
    search_fields = ("session__staff__staff_id", "patient__hospital_number")
    autocomplete_fields = ("session", "patient")


@admin.register(DisasterModeEvent)
class DisasterModeEventAdmin(admin.ModelAdmin):
    """Read-only -- history of Disaster Mode toggles, same audit-not-editable spirit
    as the Security Ledger, even though this lives in scoring, not ledger."""

    list_display = ("event_type", "staff", "occurred_at")
    list_filter = ("event_type",)
    readonly_fields = ("event_type", "staff", "reason", "occurred_at")
    search_fields = ("staff__staff_id", "staff__full_name")
    autocomplete_fields = ("staff",)

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
