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

    session = models.ForeignKey(
        "access.AccessSession", on_delete=models.CASCADE, related_name="access_decisions"
    )
    patient = models.ForeignKey(
        "patients.Patient", on_delete=models.CASCADE, related_name="access_decisions"
    )
    computed_at = models.DateTimeField(auto_now_add=True)

    gate_passed = models.BooleanField()
    score = models.FloatField()
    score_band = models.CharField(max_length=32, choices=ScoreBand.choices)
    decision_type = models.CharField(max_length=32, choices=DecisionType.choices)
    granted_categories = models.JSONField(default=list, blank=True)
    nurse_path = models.CharField(max_length=16, blank=True, default="")
    factor_breakdown = models.JSONField(default=dict, blank=True)

    def __str__(self):
        return (
            f"AccessDecision(session={self.session_id}, patient={self.patient_id}, "
            f"{self.decision_type}, score={self.score:.1f})"
        )
