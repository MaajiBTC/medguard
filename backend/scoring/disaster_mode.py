"""Disaster/Mass Casualty Mode status. is_disaster_mode_active() is the one
sanctioned way to check whether it's currently on -- both the Doctor rule
(engine.py) and the BTG availability gate (views.py) call this rather than
duplicating the "look at the latest event" logic.
"""

from .models import DisasterModeEvent


def is_disaster_mode_active():
    latest = DisasterModeEvent.objects.order_by("-occurred_at").first()
    return latest is not None and latest.event_type == DisasterModeEvent.EventType.ACTIVATED
