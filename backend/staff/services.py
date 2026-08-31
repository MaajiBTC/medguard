"""record_admin_action() is the only sanctioned way to create an
AdminActionLog -- mirrors ledger.services.record_event()'s "one writer path"
convention, so every instrumented view goes through the same place.
"""

from .models import AdminActionLog


def record_admin_action(*, actor, action, target):
    return AdminActionLog.objects.create(
        actor_staff_id=actor.staff_id,
        actor_full_name=actor.full_name,
        action=action,
        target_staff_id=target.staff_id,
        target_full_name=target.full_name,
        target_role=target.role,
    )
