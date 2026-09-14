from django.contrib import admin

from .models import SyncedBatch


@admin.register(SyncedBatch)
class SyncedBatchAdmin(admin.ModelAdmin):
    list_display = ("device", "batch_id", "entries_synced", "processed_at")
    search_fields = ("device__staff__staff_id", "batch_id")
    readonly_fields = ("device", "batch_id", "entries_synced", "processed_at")
