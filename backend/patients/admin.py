from django.contrib import admin

from .models import Patient, PatientAssignment


@admin.register(Patient)
class PatientAdmin(admin.ModelAdmin):
    list_display = ("hospital_number", "full_name", "ward")
    search_fields = ("hospital_number", "full_name")
    list_filter = ("ward",)


@admin.register(PatientAssignment)
class PatientAssignmentAdmin(admin.ModelAdmin):
    list_display = ("patient", "staff", "role_in_assignment", "active", "assigned_at")
    list_filter = ("role_in_assignment", "active")
    search_fields = ("patient__hospital_number", "patient__full_name", "staff__staff_id", "staff__full_name")
    autocomplete_fields = ("patient", "staff")
