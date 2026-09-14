from django.contrib import admin

from .models import FingerprintTemplate


@admin.register(FingerprintTemplate)
class FingerprintTemplateAdmin(admin.ModelAdmin):
    list_display = ("patient", "enrolled_at", "enrolled_by_staff_id")
    search_fields = ("patient__hospital_number", "patient__full_name")
    readonly_fields = ("encrypted_template", "enrolled_at")
