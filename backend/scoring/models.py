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

    # Step-up verification (added 2026-09-06) -- CLAUDE.md's band table has
    # always required it for the 40-69% REDUCED_ACCESS band, but nothing
    # enforced it until now. These three fields ARE the audit record for
    # step-up: deliberately not a sixth Ledger event type (the Ledger is
    # pinned to five), and they live alongside the decision they gate rather
    # than in a separate table, since they describe this one decision.
    #
    # Mechanism-agnostic on purpose: originally flipped by a typed PIN, now by
    # either device biometrics (WebAuthn, StepUpWebAuthnVerifyView) or a
    # colleague vouching (StepUpAssistRequest below) -- these fields only
    # track *whether* a decision has been step-up-verified, never *how*.
    #
    # Only meaningful when decision_type == REDUCED_ACCESS; every other band
    # ignores them (see scoring.views.PatientRecordView).
    step_up_verified = models.BooleanField(default=False)
    step_up_verified_at = models.DateTimeField(null=True, blank=True)
    step_up_failed_attempts = models.PositiveSmallIntegerField(default=0)

    def __str__(self):
        return (
            f"AccessDecision(session={self.session_id}, patient={self.patient_id}, "
            f"{self.decision_type}, score={self.score:.1f})"
        )


class StepUpAssistRequest(models.Model):
    """A colleague-vouches request (added 2026-09-06) -- the fallback path
    for step-up verification on a device with no fingerprint/Face ID/Windows
    Hello, or before the staff member has enrolled theirs. Mirrors
    access.PendingDeviceRequest's request -> poll/list -> approve/reject
    shape, but lives here rather than in `access` because it must FK to
    AccessDecision, and `access` sits *before* `scoring` in this project's
    one-way app dependency order (config/settings.py) -- access can't import
    from scoring.

    Unlike device approval (only the account's own primary-device owner can
    approve), this is a shared queue: any other logged-in clinical staff
    member can approve, per the user's explicit choice. `approved_by` is a
    real FK (not denormalized) since, unlike the Ledger/alerts, this lives on
    the same default database throughout and isn't a tamper-evident trail.
    """

    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        APPROVED = "approved", "Approved"
        DECLINED = "declined", "Declined"

    decision = models.ForeignKey(
        AccessDecision, on_delete=models.CASCADE, related_name="assist_requests"
    )
    requesting_staff = models.ForeignKey(
        "staff.Staff", on_delete=models.CASCADE, related_name="step_up_assist_requests_made"
    )
    # Whoever approved OR declined this request -- named for "who resolved
    # it" rather than "approved_by" since it's set either way.
    resolved_by = models.ForeignKey(
        "staff.Staff", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="step_up_assist_requests_resolved",
    )
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.PENDING)
    requested_at = models.DateTimeField(auto_now_add=True)
    resolved_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-requested_at"]

    def __str__(self):
        return f"StepUpAssistRequest(decision={self.decision_id}, {self.status})"


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
