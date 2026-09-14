from django.db import models


class SyncedBatch(models.Model):
    """Idempotency guard for Offline Mode (build step 6): one row per
    successfully-merged offline batch, keyed by the client-generated
    `batch_id`. A batch upload can legitimately be retried (the device goes
    offline again mid-upload, or the response never arrives) -- without this,
    a retry would replay the same events into the Ledger a second time.
    OfflineSyncView checks this table before merging anything, and returns
    the same "already processed" result on a repeat instead of erroring.

    `device` uses `on_delete=CASCADE`: if a device is ever removed
    (access.views.DeviceRemoveView), its sync history goes with it -- the
    permanent record of what happened is the Ledger entries themselves
    (denormalized, not FK'd to Device), same reasoning as everywhere else in
    this codebase that a downstream audit trail survives an upstream row's
    deletion.
    """

    device = models.ForeignKey("access.Device", on_delete=models.CASCADE, related_name="synced_batches")
    batch_id = models.UUIDField(unique=True)
    entries_synced = models.PositiveIntegerField(default=0)
    processed_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-processed_at"]

    def __str__(self):
        return f"SyncedBatch({self.device}, {self.batch_id}, {self.entries_synced} entries)"
