from django.contrib import admin

from .models import PatientNotification


@admin.register(PatientNotification)
class PatientNotificationAdmin(admin.ModelAdmin):
    list_display = ("patient", "event_type", "sent", "phone_number", "created_at")
    list_filter = ("sent", "event_type")
    search_fields = ("patient__hospital_number", "patient__full_name", "phone_number")
    readonly_fields = ("patient", "event_type", "phone_number", "sent", "twilio_sid", "error_detail", "created_at")
