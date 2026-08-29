from django.db import models


class BehavioralBaseline(models.Model):
    """One rolling profile per staff member, built up from real logins over time —
    never seeded with synthetic data (CLAUDE.md "Enrollment data"). `sample_count`
    below the learning-mode threshold (see engine.py) means "not enough real data
    yet" for the baseline-dependent factors, not "this looks wrong".

    Stats are stored as {mean, stdev} dicts (Welford's online algorithm — see
    baseline.py) rather than raw history, so this stays a small, fixed-size row
    regardless of how many logins a staff member accumulates.
    """

    staff = models.OneToOneField(
        "staff.Staff", on_delete=models.CASCADE, related_name="behavioral_baseline"
    )
    sample_count = models.PositiveIntegerField(default=0)

    keystroke_stats = models.JSONField(default=dict, blank=True)
    mouse_stats = models.JSONField(default=dict, blank=True)
    known_device_ids = models.JSONField(default=list, blank=True)
    login_hour_stats = models.JSONField(default=dict, blank=True)
    known_network_segments = models.JSONField(default=list, blank=True)

    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"BehavioralBaseline({self.staff}, samples={self.sample_count})"


class AccessDecision(models.Model):
    """One row per scoring decision for a given (session, patient) pair — the
    operational record step 4's UI reads to know what to show. NOT the tamper-evident
    Security Ledger (that's a separate, hash-chained component, step 3).
    """

    class ScoreBand(models.TextChoices):
        SILENT = "silent", "Silent (90-100%)"
        AUDITED_DEVIATION = "audited_deviation", "Audited deviation (70-89%)"
        REDUCED = "reduced", "Reduced (40-69%)"
        DENIED = "denied", "Denied (<40% or gate failed)"

    class DecisionType(models.TextChoices):
        STANDARD_ACCESS = "STANDARD_ACCESS", "Standard access"
        AUDITED_DEVIATION = "AUDITED_DEVIATION", "Audited deviation"
        REDUCED_ACCESS = "REDUCED_ACCESS", "Reduced access"
        ACCESS_DENIED = "ACCESS_DENIED", "Access denied"
        EMERGENCY_OVERRIDE = "EMERGENCY_OVERRIDE", "Emergency override"

    session = models.ForeignKey(
        "access.AccessSession", on_delete=models.CASCADE, related_name="access_decisions"
    )
    patient = models.ForeignKey(
        "patients.Patient", on_delete=models.CASCADE, related_name="access_decisions"
    )
    computed_at = models.DateTimeField(auto_now_add=True)

    # Null for an EMERGENCY_OVERRIDE row -- it never ran the scoring pipeline, so
    # "not applicable" is honest here rather than a misleading sentinel like score=100.
    gate_passed = models.BooleanField(null=True, blank=True)
    score = models.FloatField(null=True, blank=True)
    score_band = models.CharField(max_length=32, choices=ScoreBand.choices, null=True, blank=True)
    decision_type = models.CharField(max_length=32, choices=DecisionType.choices)
    granted_categories = models.JSONField(default=list, blank=True)
    # Role-specific rule path (e.g. nurse's "assigned"/"same_ward"/"neither", doctor's
    # "off_duty_denied") -- empty string when no role-specific rule applied.
    role_rule_path = models.CharField(max_length=32, blank=True, default="")
    factor_breakdown = models.JSONField(default=dict, blank=True)

    def __str__(self):
        return (
            f"AccessDecision(session={self.session_id}, patient={self.patient_id}, "
            f"{self.decision_type}, score={self.score:.1f})"
        )


class DisasterModeEvent(models.Model):
    """History of Disaster/Mass Casualty Mode activations and deactivations (added
    2026-08-29). "Currently active" is derived from this table (see
    scoring.disaster_mode.is_disaster_mode_active()), not stored as a separate flag
    that could drift out of sync.

    Deliberately NOT routed through the Security Ledger: CLAUDE.md pins the Ledger to
    exactly five event types (STANDARD_ACCESS/AUDITED_DEVIATION/REDUCED_ACCESS/
    ACCESS_DENIED/EMERGENCY_OVERRIDE), none of which fit "the mode itself changed" --
    this stays its own small, purpose-built audit trail instead of stretching that
    spec.
    """

    class EventType(models.TextChoices):
        ACTIVATED = "activated", "Activated"
        DEACTIVATED = "deactivated", "Deactivated"

    event_type = models.CharField(max_length=16, choices=EventType.choices)
    staff = models.ForeignKey(
        "staff.Staff", on_delete=models.PROTECT, related_name="disaster_mode_events"
    )
    reason = models.CharField(max_length=500)
    occurred_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-occurred_at"]

    def __str__(self):
        return f"DisasterModeEvent({self.event_type} by {self.staff}, {self.occurred_at:%Y-%m-%d %H:%M})"
