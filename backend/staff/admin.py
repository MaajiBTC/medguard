from django.contrib import admin

from .models import Staff


@admin.register(Staff)
class StaffAdmin(admin.ModelAdmin):
    list_display = ("staff_id", "full_name", "role", "ward", "on_duty", "user")
    list_filter = ("role", "on_duty", "ward")
    search_fields = ("staff_id", "full_name", "user__username")
    autocomplete_fields = ("user",)
