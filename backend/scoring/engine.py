"""Combines Behavioral + Contextual capture output into an access decision. This is
the only place matching/scoring/decision logic is allowed to live (CLAUDE.md
explicitly excludes it from the two capture modules).

Matching math is deliberately simple, explainable statistics (z-score-style
similarity against a stored baseline), not a full ML pipeline -- appropriate for a
hackathon demo, in the spirit of CLAUDE.md's cited reference repo.
"""

import math

from captures.models import ContextualCapture
from staff.models import Staff

from .baseline import LEARNING_MODE_SAMPLE_THRESHOLD, extract_keystroke_features, extract_mouse_features
from .disaster_mode import is_disaster_mode_active
from .models import AccessDecision, BehavioralBaseline

HARD_GATE_THRESHOLD = 15  # keystroke/touch similarity below this = severe mismatch

ROLE_CEILINGS = {
    Staff.Role.DOCTOR: set(range(1, 14)),
    Staff.Role.NURSE: set(range(1, 14)),
    Staff.Role.PHARMACIST: {1, 4, 5, 6, 7},
    Staff.Role.LAB_TECHNICIAN: {1},
    Staff.Role.CLERK: {1, 2},
}
REDUCED_BAND_EXCLUDED_CATEGORIES = {8, 9, 10, 11, 13}

# weight for the on-duty/ward factors is fixed (not baseline-dependent); the rest are.
WEIGHTS = {
    "on_duty": 20,
    "ward_assignment": 15,
    "keystroke_touch": 30,
    "mouse": 15,
    "device": 10,
    "login_time": 7,
    "location": 3,
}


def _clamp01(value):
    return max(0.0, min(1.0, value))


def _feature_similarity(current, baseline_stat):
    """0-100 similarity of one current scalar value against a stored {mean, stdev}."""
    mean = baseline_stat["mean"]
    stdev = baseline_stat["stdev"]
    denom = max(2 * stdev, 0.05 * max(abs(mean), 1e-9))
    return _clamp01(1 - abs(current - mean) / denom) * 100


def _average_similarity(current_features, stats):
    """Averages per-feature similarity across whichever features exist in both."""
    scores = []
    for feature, value in current_features.items():
        stat = stats.get(feature)
        if stat:
            scores.append(_feature_similarity(value, stat))
    return sum(scores) / len(scores) if scores else None


def _login_time_score(login_hour, stats):
    if not stats:
        return None
    mean, stdev = stats["mean"], stats["stdev"]
    diff = abs(login_hour - mean)
    diff = min(diff, 24 - diff)  # circular distance across midnight
    if stdev <= 1e-9:
        return 100.0 if diff < 0.1 else 0.0
    z = diff / stdev
    if z <= 1:
        return 100.0
    if z <= 2:
        return 50.0
    return 0.0


def _score_band(score):
    if score >= 90:
        return AccessDecision.ScoreBand.SILENT
    if score >= 70:
        return AccessDecision.ScoreBand.AUDITED_DEVIATION
    if score >= 40:
        return AccessDecision.ScoreBand.REDUCED
    return AccessDecision.ScoreBand.DENIED


def _band_to_decision_type(band):
    return {
        AccessDecision.ScoreBand.SILENT: AccessDecision.DecisionType.STANDARD_ACCESS,
        AccessDecision.ScoreBand.AUDITED_DEVIATION: AccessDecision.DecisionType.AUDITED_DEVIATION,
        AccessDecision.ScoreBand.REDUCED: AccessDecision.DecisionType.REDUCED_ACCESS,
        AccessDecision.ScoreBand.DENIED: AccessDecision.DecisionType.ACCESS_DENIED,
    }[band]


def compute_access_decision(session, patient):
    staff = session.staff
    contextual = session.contextual_capture
    behavioral = session.behavioral_capture
    baseline, _ = BehavioralBaseline.objects.get_or_create(staff=staff)

    learning_mode = baseline.sample_count < LEARNING_MODE_SAMPLE_THRESHOLD
    current_keystroke = extract_keystroke_features(behavioral)
    current_mouse = extract_mouse_features(behavioral.mouse_events)

    keystroke_touch_score = 100.0 if learning_mode else _average_similarity(current_keystroke, baseline.keystroke_stats)
    if keystroke_touch_score is None:
        keystroke_touch_score = 100.0  # no comparable data yet even past the threshold -- don't penalize

    # --- Hard gate: checked before anything else, overrides everything (CLAUDE.md) ---
    if not learning_mode and keystroke_touch_score < HARD_GATE_THRESHOLD:
        decision = AccessDecision.objects.create(
            session=session,
            patient=patient,
            gate_passed=False,
            score=keystroke_touch_score,
            score_band=AccessDecision.ScoreBand.DENIED,
            decision_type=AccessDecision.DecisionType.ACCESS_DENIED,
            granted_categories=[],
            role_rule_path="",
            factor_breakdown={"gate": {"keystroke_touch_similarity": keystroke_touch_score}},
        )
        return decision

    # --- Touch-only devices drop the mouse factor, redistributing its weight ---
    touch_only = session.device_type in ("mobile", "tablet") and not behavioral.mouse_events
    weights = dict(WEIGHTS)
    if touch_only:
        mouse_weight = weights.pop("mouse")
        remaining_total = sum(weights.values())
        weights = {k: v + (v / remaining_total) * mouse_weight for k, v in weights.items()}

    mouse_score = None
    if not touch_only:
        mouse_score = 100.0 if learning_mode else _average_similarity(current_mouse, baseline.mouse_stats)
        if mouse_score is None:
            mouse_score = 100.0

    device_score = 100.0 if (learning_mode or session.device_id in baseline.known_device_ids) else 0.0

    login_hour = session.started_at.hour + session.started_at.minute / 60
    login_time_score = 100.0 if learning_mode else _login_time_score(login_hour, baseline.login_hour_stats)
    if login_time_score is None:
        login_time_score = 100.0

    location_score = (
        100.0 if (learning_mode or session.network_segment in baseline.known_network_segments) else 0.0
    )

    on_duty_score = 100.0 if contextual.on_duty_at_login else 0.0

    assignment_status = contextual.patient_assignment_status
    ward_ok = assignment_status in (
        ContextualCapture.PatientAssignmentStatus.ASSIGNED,
        ContextualCapture.PatientAssignmentStatus.SAME_WARD_NOT_ASSIGNED,
        ContextualCapture.PatientAssignmentStatus.NOT_APPLICABLE,  # factor doesn't apply to this role
    )
    ward_score = 100.0 if ward_ok else 0.0

    factor_scores = {
        "on_duty": on_duty_score,
        "ward_assignment": ward_score,
        "keystroke_touch": keystroke_touch_score,
        "device": device_score,
        "login_time": login_time_score,
        "location": location_score,
    }
    if not touch_only:
        factor_scores["mouse"] = mouse_score

    score = sum(factor_scores[factor] * weight / 100 for factor, weight in weights.items())
    score_band = _score_band(score)
    decision_type = _band_to_decision_type(score_band)
    granted_categories = sorted(ROLE_CEILINGS[staff.role])
    if score_band == AccessDecision.ScoreBand.REDUCED:
        granted_categories = sorted(set(granted_categories) - REDUCED_BAND_EXCLUDED_CATEGORIES)
    if score_band == AccessDecision.ScoreBand.DENIED:
        granted_categories = []

    role_rule_path = ""
    # on_call counts the same as on_duty (added 2026-08-29, user: "is just like on
    # duty status but virtually") -- someone off duty but reachable isn't treated as
    # disconnected from the hospital. Both role rules below share this.
    effectively_on_duty = contextual.on_duty_at_login or contextual.on_call_at_login
    disaster_mode = is_disaster_mode_active()

    if staff.role == Staff.Role.NURSE:
        if assignment_status == ContextualCapture.PatientAssignmentStatus.ASSIGNED:
            role_rule_path = "assigned"
            # standard scoring result stands as computed above
        elif assignment_status == ContextualCapture.PatientAssignmentStatus.SAME_WARD_NOT_ASSIGNED:
            if effectively_on_duty or disaster_mode:
                # A nurse working her own ward cares for every patient on it, not
                # only the ones formally assigned to her -- so this stays full
                # access, always logged as an audited deviation regardless of score
                # (CLAUDE.md's Nurse rule, case 2).
                role_rule_path = "same_ward"
                decision_type = AccessDecision.DecisionType.AUDITED_DEVIATION
                granted_categories = sorted(ROLE_CEILINGS[Staff.Role.NURSE])
            else:
                # ...but only while she's actually working. Off duty and not on
                # call, that justification is gone, so this is denied exactly like
                # the equivalent doctor case -- with Break the Glass still available
                # (added 2026-09-20, user's explicit choice: deny "only when she's
                # off duty", leaving the on-duty case untouched above).
                role_rule_path = "off_duty_same_ward_denied"
                decision_type = AccessDecision.DecisionType.ACCESS_DENIED
                granted_categories = []
        else:
            # Neither assigned nor same ward -- hard-denied regardless of score
            # (user correction 2026-08-25; see CLAUDE.md's Nurse rule). Break the
            # Glass remains available here as long as the nurse is on duty (see
            # scoring.views.EmergencyOverrideView's own gate) -- CLAUDE.md's
            # documented rescue path for this exact case.
            role_rule_path = "neither"
            decision_type = AccessDecision.DecisionType.ACCESS_DENIED
            granted_categories = []
    elif staff.role == Staff.Role.DOCTOR:
        if not effectively_on_duty and not disaster_mode:
            # An off-duty (and not on-call) doctor who isn't assigned to this patient
            # is hard-denied regardless of score, in BOTH unassigned cases. The two
            # are denied for the same reason but differ in what happens next, which
            # is why they carry distinct role_rule_path values:
            #
            #   same ward, not assigned (added 2026-09-20, user request) -> denied,
            #     but Break the Glass stays available (EmergencyOverrideView's gate
            #     only blocks NOT_ASSIGNED_NOT_SAME_WARD), so per the user this is
            #     "the only way he can access" -- a deliberate, justified, logged
            #     override rather than silent routine access. The nurse branch above
            #     reaches the same outcome, by the same reasoning and under the same
            #     role_rule_path value.
            #   neither assigned nor same ward (added 2026-08-29) -> denied AND BTG
            #     is blocked/hidden too; no path at all short of Disaster Mode.
            #
            # Still untouched, still plain weighted scoring: any on-duty/on-call
            # doctor, and an off-duty doctor who IS assigned to this patient.
            # Suspended hospital-wide during Disaster/Mass Casualty Mode.
            if assignment_status == ContextualCapture.PatientAssignmentStatus.NOT_ASSIGNED_NOT_SAME_WARD:
                role_rule_path = "off_duty_denied"
                decision_type = AccessDecision.DecisionType.ACCESS_DENIED
                granted_categories = []
            elif assignment_status == ContextualCapture.PatientAssignmentStatus.SAME_WARD_NOT_ASSIGNED:
                role_rule_path = "off_duty_same_ward_denied"
                decision_type = AccessDecision.DecisionType.ACCESS_DENIED
                granted_categories = []

    decision = AccessDecision.objects.create(
        session=session,
        patient=patient,
        gate_passed=True,
        score=score,
        score_band=score_band,
        decision_type=decision_type,
        granted_categories=granted_categories,
        role_rule_path=role_rule_path,
        factor_breakdown={
            "weights": weights,
            "factor_scores": factor_scores,
            "learning_mode": learning_mode,
            "sample_count": baseline.sample_count,
        },
    )
    return decision
