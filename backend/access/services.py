from django.conf import settings
from django.db import transaction

from captures.models import BehavioralCapture, ContextualCapture

from .models import AccessSession


def create_session(staff, device_id, device_type, user_agent, login_keystroke_features=None):
    """Creates one AccessSession plus its paired BehavioralCapture/ContextualCapture
    rows in a single transaction. Shared by LoginView's direct-login path and
    DeviceApproveView's device-approval path, so both ways of ending up with a live
    session go through identical capture bootstrapping."""
    with transaction.atomic():
        session = AccessSession.objects.create(
            staff=staff,
            device_id=device_id,
            device_type=device_type,
            user_agent=user_agent,
            network_segment=getattr(settings, "WORKSTATION_NETWORK_SEGMENT", "unknown"),
        )
        BehavioralCapture.objects.create(
            session=session,
            keystroke_features={"login": login_keystroke_features, "session_windows": []},
        )
        ContextualCapture.objects.create(
            session=session,
            on_duty_at_login=staff.on_duty,
            on_call_at_login=staff.on_call,
            ward_assignment_at_login=staff.ward,
        )
    return session
