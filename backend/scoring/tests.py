"""Scoring Engine tests. Built the same way the rest of the suite is: construct
Staff/AccessSession/BehavioralCapture/ContextualCapture/Patient/PatientAssignment
directly via the ORM -- no real enrollment data, per CLAUDE.md."""

from types import SimpleNamespace
from unittest.mock import patch

from django.contrib.auth.models import User
from rest_framework import status
from rest_framework.test import APITestCase
from webauthn.helpers.exceptions import InvalidAuthenticationResponse

from access.models import AccessSession, Device, WebAuthnCredential
from alerts.models import SecurityAlert
from captures.models import BehavioralCapture, ContextualCapture
from ledger.models import LedgerEntry
from patients.models import Patient, PatientAssignment, PatientCategoryRecord
from staff.models import Staff

from .baseline import extract_keystroke_features, extract_mouse_features
from .engine import compute_access_decision
from .models import AccessDecision, BehavioralBaseline, DisasterModeEvent, StepUpAssistRequest

SAMPLE_MOUSE_EVENTS = [
    {"event": "mousemove", "x": 0, "y": 0, "t": 0.0},
    {"event": "mousemove", "x": 50, "y": 0, "t": 100.0},
    {"event": "mousedown", "x": 50, "y": 0, "button": 0, "t": 150.0},
    {"event": "mouseup", "x": 50, "y": 0, "button": 0, "t": 230.0},
]

SAMPLE_KEYSTROKE_FEATURES = {
    "flight_times": [100.0, 110.0],
    "digraph_latencies": [150.0, 160.0],
    "trigraph_latencies": [260.0],
    "error_correction_rate": 0.05,
    "rhythm_consistency": 0.9,
    "automation_flags": [],
}

# Every field far enough from SAMPLE_KEYSTROKE_FEATURES to fail similarity on all
# five features at once (a partial mismatch on 1-2 features averages out above the
# hard-gate threshold, since it's an average across features -- this needs to be a
# wholesale mismatch to actually trigger the gate).
MISMATCHED_KEYSTROKE_FEATURES = {
    "flight_times": [500.0, 520.0],
    "digraph_latencies": [600.0, 620.0],
    "trigraph_latencies": [900.0],
    "error_correction_rate": 0.9,
    "rhythm_consistency": 0.05,
    "automation_flags": [],
}


class ScoringTestBase(APITestCase):
    def _make_staff(self, username, staff_id, role, ward="", on_duty=True, on_call=False):
        user = User.objects.create_user(username=username, password="pw-scoring-test-1")
        return Staff.objects.create(
            user=user, staff_id=staff_id, full_name=username, role=role, ward=ward,
            on_duty=on_duty, on_call=on_call,
        )

    def _make_session(self, staff, device_id="dev-1", device_type="desktop", network_segment="seg-1"):
        return AccessSession.objects.create(
            staff=staff, device_id=device_id, device_type=device_type, network_segment=network_segment
        )

    def _make_captures(self, session, keystroke_features=None, mouse_events=None,
                       patient=None, assignment_status=None):
        behavioral = BehavioralCapture.objects.create(
            session=session,
            keystroke_features={
                "login": keystroke_features if keystroke_features is not None else dict(SAMPLE_KEYSTROKE_FEATURES),
                "session_windows": [],
            },
            mouse_events=mouse_events if mouse_events is not None else list(SAMPLE_MOUSE_EVENTS),
        )
        contextual = ContextualCapture.objects.create(
            session=session,
            on_duty_at_login=session.staff.on_duty,
            on_call_at_login=session.staff.on_call,
            ward_assignment_at_login=session.staff.ward,
            target_patient=patient,
            patient_assignment_status=assignment_status or ContextualCapture.PatientAssignmentStatus.NO_PATIENT_SELECTED,
        )
        return behavioral, contextual

    def _matching_baseline(self, staff, session, behavioral, sample_count=5):
        keystroke_feats = extract_keystroke_features(behavioral)
        mouse_feats = extract_mouse_features(behavioral.mouse_events)
        login_hour = session.started_at.hour + session.started_at.minute / 60
        return BehavioralBaseline.objects.create(
            staff=staff,
            sample_count=sample_count,
            keystroke_stats={k: {"mean": v, "stdev": 0.0} for k, v in keystroke_feats.items()},
            mouse_stats={k: {"mean": v, "stdev": 0.0} for k, v in mouse_feats.items()},
            known_device_ids=[session.device_id],
            login_hour_stats={"mean": login_hour, "stdev": 0.0},
            known_network_segments=[session.network_segment],
        )


class EngineFactorTests(ScoringTestBase):
    def test_learning_mode_gives_full_credit_with_no_baseline_history(self):
        staff = self._make_staff("docLearn", "STF-700", Staff.Role.DOCTOR, ward="Ward A", on_duty=True)
        session = self._make_session(staff)
        patient = Patient.objects.create(hospital_number="HN-700", full_name="P1", ward="Ward A")
        behavioral, contextual = self._make_captures(
            session, patient=patient,
            assignment_status=ContextualCapture.PatientAssignmentStatus.SAME_WARD_NOT_ASSIGNED,
        )
        # No BehavioralBaseline created -- get_or_create inside compute_access_decision
        # makes a fresh one with sample_count=0, which is below the learning-mode
        # threshold.
        decision = compute_access_decision(session, patient)
        self.assertTrue(decision.gate_passed)
        self.assertEqual(decision.score, 100.0)
        self.assertEqual(decision.decision_type, AccessDecision.DecisionType.STANDARD_ACCESS)
        self.assertEqual(decision.granted_categories, list(range(1, 14)))

    def test_worked_example_only_ward_fails_lands_at_85_audited_deviation(self):
        """Mirrors CLAUDE.md's confirmed-correct worked example: doctor on duty,
        everything else passing, only ward assignment fails -> 85% -> AUDITED_DEVIATION."""
        staff = self._make_staff("docWard", "STF-701", Staff.Role.DOCTOR, ward="Ward A", on_duty=True)
        session = self._make_session(staff)
        patient = Patient.objects.create(hospital_number="HN-701", full_name="P2", ward="Ward B")
        behavioral, contextual = self._make_captures(
            session, patient=patient,
            assignment_status=ContextualCapture.PatientAssignmentStatus.NOT_ASSIGNED_NOT_SAME_WARD,
        )
        self._matching_baseline(staff, session, behavioral)

        decision = compute_access_decision(session, patient)
        self.assertAlmostEqual(decision.score, 85.0, places=5)
        self.assertEqual(decision.score_band, AccessDecision.ScoreBand.AUDITED_DEVIATION)
        self.assertEqual(decision.decision_type, AccessDecision.DecisionType.AUDITED_DEVIATION)
        self.assertEqual(decision.granted_categories, list(range(1, 14)))  # doctor: no reduced-band exclusion at 85%

    def test_hard_gate_denies_regardless_of_role(self):
        staff = self._make_staff("docGate", "STF-702", Staff.Role.DOCTOR, ward="Ward A", on_duty=True)
        session = self._make_session(staff)
        patient = Patient.objects.create(hospital_number="HN-702", full_name="P3", ward="Ward A")
        mismatched_features = dict(MISMATCHED_KEYSTROKE_FEATURES)
        behavioral, contextual = self._make_captures(
            session, keystroke_features=mismatched_features, patient=patient,
            assignment_status=ContextualCapture.PatientAssignmentStatus.ASSIGNED,
        )
        # Baseline built from the ORIGINAL sample features, not the mismatched ones
        # captured this session -- simulates a wildly different typing rhythm.
        baseline_source = BehavioralCapture(keystroke_features={"login": dict(SAMPLE_KEYSTROKE_FEATURES), "session_windows": []})
        self._matching_baseline(staff, session, baseline_source)

        decision = compute_access_decision(session, patient)
        self.assertFalse(decision.gate_passed)
        self.assertEqual(decision.decision_type, AccessDecision.DecisionType.ACCESS_DENIED)
        self.assertEqual(decision.granted_categories, [])

    def test_reduced_band_excludes_high_sensitivity_categories(self):
        """on_duty stays True here deliberately: off-duty + not-assigned + not-same-
        ward is now the new Doctor hard-deny combination (see DoctorRuleTests) -- this
        test is about the reduced-band category-exclusion mechanism itself, not that
        rule, so it reaches 40-69% via ward + device + location + login-time instead."""
        staff = self._make_staff("docReduced", "STF-703", Staff.Role.DOCTOR, ward="Ward A", on_duty=True)
        session = self._make_session(staff)
        patient = Patient.objects.create(hospital_number="HN-703", full_name="P4", ward="Ward B")
        behavioral, contextual = self._make_captures(
            session, patient=patient,
            assignment_status=ContextualCapture.PatientAssignmentStatus.NOT_ASSIGNED_NOT_SAME_WARD,
        )
        # Keystroke/mouse match the baseline (gate passes, those two factors stay
        # ~100%); device/network/login-hour deliberately don't.
        keystroke_feats = extract_keystroke_features(behavioral)
        mouse_feats = extract_mouse_features(behavioral.mouse_events)
        login_hour = session.started_at.hour + session.started_at.minute / 60
        BehavioralBaseline.objects.create(
            staff=staff,
            sample_count=5,
            keystroke_stats={k: {"mean": v, "stdev": 0.0} for k, v in keystroke_feats.items()},
            mouse_stats={k: {"mean": v, "stdev": 0.0} for k, v in mouse_feats.items()},
            known_device_ids=["some-other-device"],
            login_hour_stats={"mean": (login_hour + 12) % 24, "stdev": 0.1},
            known_network_segments=["some-other-segment"],
        )
        # on_duty passes (+20), keystroke/mouse pass (+30+15); ward, device, login
        # time, location all fail (-15-10-7-3) -> 65% -> reduced band.
        decision = compute_access_decision(session, patient)
        self.assertAlmostEqual(decision.score, 65.0, places=5)
        self.assertEqual(decision.decision_type, AccessDecision.DecisionType.REDUCED_ACCESS)
        self.assertEqual(decision.granted_categories, [1, 2, 3, 4, 5, 6, 7, 12])

    def test_touch_only_device_redistributes_mouse_weight(self):
        staff = self._make_staff("docTouch", "STF-704", Staff.Role.DOCTOR, ward="Ward A", on_duty=True)
        session = self._make_session(staff, device_type="mobile")
        patient = Patient.objects.create(hospital_number="HN-704", full_name="P5", ward="Ward A")
        behavioral, contextual = self._make_captures(
            session, mouse_events=[], patient=patient,
            assignment_status=ContextualCapture.PatientAssignmentStatus.ASSIGNED,
        )
        self._matching_baseline(staff, session, behavioral)

        decision = compute_access_decision(session, patient)
        weights = decision.factor_breakdown["weights"]
        self.assertNotIn("mouse", weights)
        self.assertAlmostEqual(sum(weights.values()), 100.0, places=5)
        self.assertEqual(decision.score, 100.0)


class NurseRuleTests(ScoringTestBase):
    def test_nurse_assigned_path_uses_standard_scoring(self):
        staff = self._make_staff("nurseAssigned", "STF-800", Staff.Role.NURSE, ward="Ward A", on_duty=True)
        session = self._make_session(staff)
        patient = Patient.objects.create(hospital_number="HN-800", full_name="P6", ward="Ward A")
        PatientAssignment.objects.create(patient=patient, staff=staff, role_in_assignment="nurse")
        behavioral, contextual = self._make_captures(
            session, patient=patient, assignment_status=ContextualCapture.PatientAssignmentStatus.ASSIGNED
        )
        self._matching_baseline(staff, session, behavioral)

        decision = compute_access_decision(session, patient)
        self.assertEqual(decision.role_rule_path, "assigned")
        self.assertEqual(decision.decision_type, AccessDecision.DecisionType.STANDARD_ACCESS)
        self.assertEqual(decision.granted_categories, list(range(1, 14)))

    def test_nurse_same_ward_forces_audited_deviation_even_at_perfect_score(self):
        staff = self._make_staff("nurseSameWard", "STF-801", Staff.Role.NURSE, ward="Ward A", on_duty=True)
        session = self._make_session(staff)
        patient = Patient.objects.create(hospital_number="HN-801", full_name="P7", ward="Ward A")
        behavioral, contextual = self._make_captures(
            session, patient=patient,
            assignment_status=ContextualCapture.PatientAssignmentStatus.SAME_WARD_NOT_ASSIGNED,
        )
        self._matching_baseline(staff, session, behavioral)

        decision = compute_access_decision(session, patient)
        self.assertEqual(decision.score, 100.0)  # everything matches, including ward (same-ward counts)
        self.assertEqual(decision.role_rule_path, "same_ward")
        # Forced regardless of the underlying (silent-band) score.
        self.assertEqual(decision.decision_type, AccessDecision.DecisionType.AUDITED_DEVIATION)
        self.assertEqual(decision.granted_categories, list(range(1, 14)))

    def test_nurse_neither_assigned_nor_same_ward_hard_denied_even_at_high_score(self):
        """Regression test for the user's 2026-08-25 correction: this case must be
        hard-denied regardless of score, not fall through to standard scoring."""
        staff = self._make_staff("nurseNeither", "STF-802", Staff.Role.NURSE, ward="Ward A", on_duty=True)
        session = self._make_session(staff)
        patient = Patient.objects.create(hospital_number="HN-802", full_name="P8", ward="Ward B")
        behavioral, contextual = self._make_captures(
            session, patient=patient,
            assignment_status=ContextualCapture.PatientAssignmentStatus.NOT_ASSIGNED_NOT_SAME_WARD,
        )
        self._matching_baseline(staff, session, behavioral)

        decision = compute_access_decision(session, patient)
        # Everything except ward matches -> the raw weighted score would be 85%
        # (AUDITED_DEVIATION territory), but the nurse rule must override that.
        self.assertAlmostEqual(decision.score, 85.0, places=5)
        self.assertEqual(decision.role_rule_path, "neither")
        self.assertEqual(decision.decision_type, AccessDecision.DecisionType.ACCESS_DENIED)
        self.assertEqual(decision.granted_categories, [])

    def test_gate_overrides_nurse_same_ward_full_access(self):
        """The hard gate takes precedence over every role-specific rule, including
        the nurse same-ward forced-full-access path (CLAUDE.md)."""
        staff = self._make_staff("nurseGate", "STF-803", Staff.Role.NURSE, ward="Ward A", on_duty=True)
        session = self._make_session(staff)
        patient = Patient.objects.create(hospital_number="HN-803", full_name="P9", ward="Ward A")
        mismatched_features = dict(MISMATCHED_KEYSTROKE_FEATURES)
        behavioral, contextual = self._make_captures(
            session, keystroke_features=mismatched_features, patient=patient,
            assignment_status=ContextualCapture.PatientAssignmentStatus.SAME_WARD_NOT_ASSIGNED,
        )
        baseline_source = BehavioralCapture(keystroke_features={"login": dict(SAMPLE_KEYSTROKE_FEATURES), "session_windows": []})
        self._matching_baseline(staff, session, baseline_source)

        decision = compute_access_decision(session, patient)
        self.assertFalse(decision.gate_passed)
        self.assertEqual(decision.decision_type, AccessDecision.DecisionType.ACCESS_DENIED)
        self.assertEqual(decision.granted_categories, [])


class DoctorRuleTests(ScoringTestBase):
    """The 2026-08-29 doctor carve-out: off duty AND no connection to the patient at
    all (not assigned, not same ward) -> hard-denied, same standard as the Nurse
    rule's own worst case. Every other combination is untouched."""

    def test_off_duty_and_neither_assigned_nor_same_ward_is_denied(self):
        staff = self._make_staff("docOffDutyNeither", "STF-900", Staff.Role.DOCTOR, ward="Ward A", on_duty=False)
        session = self._make_session(staff)
        patient = Patient.objects.create(hospital_number="HN-900", full_name="P14", ward="Ward B")
        behavioral, contextual = self._make_captures(
            session, patient=patient,
            assignment_status=ContextualCapture.PatientAssignmentStatus.NOT_ASSIGNED_NOT_SAME_WARD,
        )
        self._matching_baseline(staff, session, behavioral)

        decision = compute_access_decision(session, patient)
        self.assertEqual(decision.role_rule_path, "off_duty_denied")
        self.assertEqual(decision.decision_type, AccessDecision.DecisionType.ACCESS_DENIED)
        self.assertEqual(decision.granted_categories, [])

    def test_on_call_avoids_the_hard_deny_like_on_duty(self):
        """on_call counts the same as on_duty (2026-08-29, user: "just like on duty
        status but virtually") -- off duty but on call must NOT hard-deny."""
        staff = self._make_staff(
            "docOnCallNeither", "STF-905", Staff.Role.DOCTOR, ward="Ward A", on_duty=False, on_call=True
        )
        session = self._make_session(staff)
        patient = Patient.objects.create(hospital_number="HN-905", full_name="P19", ward="Ward B")
        behavioral, contextual = self._make_captures(
            session, patient=patient,
            assignment_status=ContextualCapture.PatientAssignmentStatus.NOT_ASSIGNED_NOT_SAME_WARD,
        )
        self._matching_baseline(staff, session, behavioral)

        decision = compute_access_decision(session, patient)
        self.assertEqual(decision.role_rule_path, "")
        self.assertNotEqual(decision.decision_type, AccessDecision.DecisionType.ACCESS_DENIED)

    def test_off_duty_but_assigned_uses_standard_scoring(self):
        staff = self._make_staff("docOffDutyAssigned", "STF-901", Staff.Role.DOCTOR, ward="Ward A", on_duty=False)
        session = self._make_session(staff)
        patient = Patient.objects.create(hospital_number="HN-901", full_name="P15", ward="Ward B")
        PatientAssignment.objects.create(patient=patient, staff=staff, role_in_assignment="doctor")
        behavioral, contextual = self._make_captures(
            session, patient=patient, assignment_status=ContextualCapture.PatientAssignmentStatus.ASSIGNED
        )
        self._matching_baseline(staff, session, behavioral)

        decision = compute_access_decision(session, patient)
        self.assertEqual(decision.role_rule_path, "")
        self.assertNotEqual(decision.decision_type, AccessDecision.DecisionType.ACCESS_DENIED)

    def test_off_duty_but_same_ward_uses_standard_scoring(self):
        staff = self._make_staff("docOffDutySameWard", "STF-902", Staff.Role.DOCTOR, ward="Ward A", on_duty=False)
        session = self._make_session(staff)
        patient = Patient.objects.create(hospital_number="HN-902", full_name="P16", ward="Ward A")
        behavioral, contextual = self._make_captures(
            session, patient=patient,
            assignment_status=ContextualCapture.PatientAssignmentStatus.SAME_WARD_NOT_ASSIGNED,
        )
        self._matching_baseline(staff, session, behavioral)

        decision = compute_access_decision(session, patient)
        self.assertEqual(decision.role_rule_path, "")
        self.assertNotEqual(decision.decision_type, AccessDecision.DecisionType.ACCESS_DENIED)

    def test_on_duty_neither_assigned_nor_same_ward_uses_standard_scoring(self):
        """This is the exact scenario demoed live before this rule existed: on-duty
        doesn't trigger the new carve-out, so it still just lands in REDUCED_ACCESS
        via the normal weighted score (on_duty passes, ward fails -> 85%, actually;
        the live demo also had on_duty failing, landing at 65% -- here on_duty is
        True so only the -15% ward penalty applies)."""
        staff = self._make_staff("docOnDutyNeither", "STF-903", Staff.Role.DOCTOR, ward="Ward A", on_duty=True)
        session = self._make_session(staff)
        patient = Patient.objects.create(hospital_number="HN-903", full_name="P17", ward="Ward B")
        behavioral, contextual = self._make_captures(
            session, patient=patient,
            assignment_status=ContextualCapture.PatientAssignmentStatus.NOT_ASSIGNED_NOT_SAME_WARD,
        )
        self._matching_baseline(staff, session, behavioral)

        decision = compute_access_decision(session, patient)
        self.assertEqual(decision.role_rule_path, "")
        self.assertNotEqual(decision.decision_type, AccessDecision.DecisionType.ACCESS_DENIED)

    def test_gate_overrides_doctor_off_duty_denial(self):
        """The hard gate is checked before the new doctor rule, same as it already
        takes precedence over the Nurse rule -- confirms the new rule doesn't
        accidentally skip the gate."""
        staff = self._make_staff("docGateOffDuty", "STF-904", Staff.Role.DOCTOR, ward="Ward A", on_duty=False)
        session = self._make_session(staff)
        patient = Patient.objects.create(hospital_number="HN-904", full_name="P18", ward="Ward B")
        mismatched_features = dict(MISMATCHED_KEYSTROKE_FEATURES)
        behavioral, contextual = self._make_captures(
            session, keystroke_features=mismatched_features, patient=patient,
            assignment_status=ContextualCapture.PatientAssignmentStatus.NOT_ASSIGNED_NOT_SAME_WARD,
        )
        baseline_source = BehavioralCapture(keystroke_features={"login": dict(SAMPLE_KEYSTROKE_FEATURES), "session_windows": []})
        self._matching_baseline(staff, session, baseline_source)

        decision = compute_access_decision(session, patient)
        self.assertFalse(decision.gate_passed)
        self.assertEqual(decision.decision_type, AccessDecision.DecisionType.ACCESS_DENIED)
        self.assertEqual(decision.granted_categories, [])
        # role_rule_path stays "" -- the gate's early return never reaches the
        # doctor-rule block, so it must not be misreported as the cause.
        self.assertEqual(decision.role_rule_path, "")


class BaselineReinforcementAndAPITests(ScoringTestBase):
    # /api/scoring/decide/ now also writes to the Security Ledger (see ledger app),
    # which lives on its own database.
    databases = {"default", "ledger"}

    def _login(self, username, password, staff_id, role, ward="", on_duty=True):
        user = User.objects.create_user(username=username, password=password)
        staff = Staff.objects.create(
            user=user, staff_id=staff_id, full_name=username, role=role, ward=ward, on_duty=on_duty
        )
        resp = self.client.post(
            "/api/access/login/",
            {"username": username, "password": password, "device_id": f"device-{staff_id}", "device_type": "desktop"},
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED, resp.data)
        return staff, resp.data["token"]

    def _auth(self, token):
        return {"HTTP_AUTHORIZATION": f"Bearer {token}"}

    def test_decide_requires_target_patient_set_first(self):
        staff, token = self._login("docApi1", "pw-api-1", "STF-900", Staff.Role.DOCTOR, ward="Ward A")
        patient = Patient.objects.create(hospital_number="HN-900", full_name="P10", ward="Ward A")

        resp = self.client.post("/api/scoring/decide/", {"patient_id": patient.id}, format="json", **self._auth(token))
        self.assertEqual(resp.status_code, status.HTTP_409_CONFLICT)

    def test_decide_full_round_trip_and_baseline_reinforcement(self):
        staff, token = self._login("docApi2", "pw-api-2", "STF-901", Staff.Role.DOCTOR, ward="Ward A")
        patient = Patient.objects.create(hospital_number="HN-901", full_name="P11", ward="Ward A")

        target_resp = self.client.post(
            "/api/captures/contextual/target-patient/", {"patient_id": patient.id}, format="json", **self._auth(token)
        )
        self.assertEqual(target_resp.status_code, status.HTTP_200_OK)

        decide_resp = self.client.post("/api/scoring/decide/", {"patient_id": patient.id}, format="json", **self._auth(token))
        self.assertEqual(decide_resp.status_code, status.HTTP_201_CREATED)
        self.assertEqual(decide_resp.data["decision_type"], AccessDecision.DecisionType.STANDARD_ACCESS)

        baseline = BehavioralBaseline.objects.get(staff=staff)
        self.assertEqual(baseline.sample_count, 1)
        self.assertIn(f"device-STF-901", baseline.known_device_ids)

    def test_standard_access_does_not_notify_patient(self):
        """Patient SMS notifications (added 2026-09-14) -- a clean,
        silent decision stays silent for the patient too. notify_patient
        is mocked at the point of use (scoring.views.notify_patient) so
        this never makes a real network call."""
        _staff, token = self._login("docNotifyStd", "pw-notify-std", "STF-NSTD", Staff.Role.DOCTOR, ward="Ward A")
        patient = Patient.objects.create(hospital_number="HN-NSTD", full_name="P", ward="Ward A")
        self.client.post(
            "/api/captures/contextual/target-patient/", {"patient_id": patient.id}, format="json", **self._auth(token)
        )

        with patch("scoring.views.notify_patient") as mocked:
            resp = self.client.post(
                "/api/scoring/decide/", {"patient_id": patient.id}, format="json", **self._auth(token)
            )

        self.assertEqual(resp.data["decision_type"], AccessDecision.DecisionType.STANDARD_ACCESS)
        mocked.assert_not_called()

    def test_denied_decision_notifies_patient(self):
        """A nurse neither assigned nor on the patient's ward is a
        deterministic hard ACCESS_DENIED (CLAUDE.md's Nurse rule) --
        reliable to trigger through the real view, unlike score-band
        cases."""
        _staff, token = self._login("nurseNotifyDenied", "pw-notify-denied", "STF-NDEN", Staff.Role.NURSE, ward="Ward A")
        patient = Patient.objects.create(hospital_number="HN-NDEN", full_name="P", ward="Ward B")
        self.client.post(
            "/api/captures/contextual/target-patient/", {"patient_id": patient.id}, format="json", **self._auth(token)
        )

        with patch("scoring.views.notify_patient") as mocked:
            resp = self.client.post(
                "/api/scoring/decide/", {"patient_id": patient.id}, format="json", **self._auth(token)
            )

        self.assertEqual(resp.data["decision_type"], AccessDecision.DecisionType.ACCESS_DENIED)
        mocked.assert_called_once()
        call_kwargs = mocked.call_args.kwargs
        self.assertEqual(call_kwargs["event_type"], AccessDecision.DecisionType.ACCESS_DENIED)
        self.assertEqual(call_kwargs["patient"], patient)

    def test_baseline_not_reinforced_by_denied_decision(self):
        staff = self._make_staff("nurseDenied", "STF-902", Staff.Role.NURSE, ward="Ward A", on_duty=True)
        session = self._make_session(staff)
        patient = Patient.objects.create(hospital_number="HN-902", full_name="P12", ward="Ward B")
        behavioral, contextual = self._make_captures(
            session, patient=patient,
            assignment_status=ContextualCapture.PatientAssignmentStatus.NOT_ASSIGNED_NOT_SAME_WARD,
        )
        self._matching_baseline(staff, session, behavioral, sample_count=5)

        decision = compute_access_decision(session, patient)
        self.assertEqual(decision.decision_type, AccessDecision.DecisionType.ACCESS_DENIED)

        baseline = BehavioralBaseline.objects.get(staff=staff)
        self.assertEqual(baseline.sample_count, 5)  # unchanged -- engine itself never updates the baseline

    def test_decide_view_skips_baseline_reinforcement_on_denied_decision(self):
        """End-to-end through the real API: a nurse with no ward/assignment
        connection to the patient must be denied, and that denial must not
        reinforce her behavioral baseline."""
        staff, token = self._login("nurseApiDenied", "pw-api-3", "STF-903", Staff.Role.NURSE, ward="Ward A")
        patient = Patient.objects.create(hospital_number="HN-903", full_name="P13", ward="Ward B")

        target_resp = self.client.post(
            "/api/captures/contextual/target-patient/", {"patient_id": patient.id}, format="json", **self._auth(token)
        )
        self.assertEqual(target_resp.status_code, status.HTTP_200_OK)
        self.assertEqual(target_resp.data["patient_assignment_status"], "not_assigned_not_same_ward")

        decide_resp = self.client.post("/api/scoring/decide/", {"patient_id": patient.id}, format="json", **self._auth(token))
        self.assertEqual(decide_resp.status_code, status.HTTP_201_CREATED)
        self.assertEqual(decide_resp.data["decision_type"], AccessDecision.DecisionType.ACCESS_DENIED)
        self.assertEqual(decide_resp.data["granted_categories"], [])

        baseline = BehavioralBaseline.objects.get(staff=staff)
        self.assertEqual(baseline.sample_count, 0)

    def test_admin_and_security_officer_rejected_from_decide(self):
        """/api/scoring/decide/ is patient-record access -- not applicable to system
        roles (CLAUDE.md's role table doesn't cover them at all)."""
        for role, suffix in [(Staff.Role.ADMIN, "adm"), (Staff.Role.SECURITY_OFFICER, "sec")]:
            _staff, token = self._login(f"nonClinical{suffix}", f"pw-nonclinical-{suffix}", f"STF-NC-{suffix}", role)
            patient = Patient.objects.create(hospital_number=f"HN-NC-{suffix}", full_name="P", ward="Ward A")
            resp = self.client.post(
                "/api/scoring/decide/", {"patient_id": patient.id}, format="json", **self._auth(token)
            )
            self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)


class MyBaselineViewTests(APITestCase):
    """Offline Mode (build step 6) -- the self-service baseline snapshot the
    frontend caches for offline scoring. See offline_sync app for the sync
    side of this feature."""

    databases = {"default", "ledger"}

    def _login(self, username, password, staff_id, role):
        user = User.objects.create_user(username=username, password=password)
        staff = Staff.objects.create(user=user, staff_id=staff_id, full_name=username, role=role)
        resp = self.client.post(
            "/api/access/login/",
            {"username": username, "password": password, "device_id": f"device-{staff_id}", "device_type": "desktop"},
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED, resp.data)
        return staff, resp.data["token"]

    def _auth(self, token):
        return {"HTTP_AUTHORIZATION": f"Bearer {token}"}

    def test_creates_empty_baseline_on_first_call(self):
        _staff, token = self._login("docBaseline1", "pw-baseline-1", "STF-BL1", Staff.Role.DOCTOR)
        resp = self.client.get("/api/scoring/my-baseline/", **self._auth(token))
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data["sample_count"], 0)
        self.assertEqual(resp.data["keystroke_stats"], {})
        self.assertIn("disaster_mode_active", resp.data)
        self.assertFalse(resp.data["disaster_mode_active"])

    def test_reflects_reinforced_baseline(self):
        user = User.objects.create_user(username="docBaseline2", password="pw-baseline-2")
        staff = Staff.objects.create(
            user=user, staff_id="STF-BL2", full_name="docBaseline2", role=Staff.Role.DOCTOR, on_duty=True
        )
        login = self.client.post(
            "/api/access/login/",
            {"username": "docBaseline2", "password": "pw-baseline-2", "device_id": "device-STF-BL2", "device_type": "desktop"},
            format="json",
        )
        token = login.data["token"]
        patient = Patient.objects.create(hospital_number="HN-BL2", full_name="P")
        self.client.post(
            "/api/captures/contextual/target-patient/", {"patient_id": patient.id}, format="json", **self._auth(token)
        )
        self.client.post("/api/scoring/decide/", {"patient_id": patient.id}, format="json", **self._auth(token))

        resp = self.client.get("/api/scoring/my-baseline/", **self._auth(token))
        self.assertEqual(resp.data["sample_count"], 1)
        self.assertIn(f"device-STF-BL2", resp.data["known_device_ids"])

    def test_non_clinical_role_forbidden(self):
        _staff, token = self._login("adminBaseline", "pw-baseline-3", "STF-BL3", Staff.Role.ADMIN)
        resp = self.client.get("/api/scoring/my-baseline/", **self._auth(token))
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)

    def test_unauthenticated_rejected(self):
        resp = self.client.get("/api/scoring/my-baseline/")
        self.assertEqual(resp.status_code, status.HTTP_401_UNAUTHORIZED)


class PatientRecordViewTests(APITestCase):
    """Exercises /api/scoring/patients/<id>/records/, which is only reachable after a
    decision already exists (same precedent DecideView sets for target-patient)."""

    databases = {"default", "ledger"}

    def _login(self, username, password, staff_id, role, ward="", on_duty=True):
        user = User.objects.create_user(username=username, password=password)
        staff = Staff.objects.create(
            user=user, staff_id=staff_id, full_name=username, role=role, ward=ward, on_duty=on_duty
        )
        resp = self.client.post(
            "/api/access/login/",
            {"username": username, "password": password, "device_id": f"device-{staff_id}", "device_type": "desktop"},
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED, resp.data)
        return staff, resp.data["token"]

    def _auth(self, token):
        return {"HTTP_AUTHORIZATION": f"Bearer {token}"}

    def test_records_endpoint_requires_a_decision_first(self):
        _staff, token = self._login("docRecordsApi1", "pw-records-1", "STF-R900", Staff.Role.DOCTOR, ward="Ward A")
        patient = Patient.objects.create(hospital_number="HN-R900", full_name="P", ward="Ward A")

        resp = self.client.get(f"/api/scoring/patients/{patient.id}/records/", **self._auth(token))
        self.assertEqual(resp.status_code, status.HTTP_404_NOT_FOUND)

    def test_records_endpoint_returns_only_granted_categories(self):
        _staff, token = self._login("docRecordsApi2", "pw-records-2", "STF-R901", Staff.Role.DOCTOR, ward="Ward A")
        patient = Patient.objects.create(hospital_number="HN-R901", full_name="P", ward="Ward A")
        PatientCategoryRecord.objects.bulk_create(
            PatientCategoryRecord(patient=patient, category=c, content={"notes": f"cat {c}"})
            for c, _ in PatientCategoryRecord.Category.choices
        )

        self.client.post(
            "/api/captures/contextual/target-patient/", {"patient_id": patient.id}, format="json", **self._auth(token)
        )
        decide_resp = self.client.post(
            "/api/scoring/decide/", {"patient_id": patient.id}, format="json", **self._auth(token)
        )
        self.assertEqual(decide_resp.status_code, status.HTTP_201_CREATED)
        self.assertEqual(decide_resp.data["decision_type"], AccessDecision.DecisionType.STANDARD_ACCESS)

        records_resp = self.client.get(f"/api/scoring/patients/{patient.id}/records/", **self._auth(token))
        self.assertEqual(records_resp.status_code, status.HTTP_200_OK)
        self.assertEqual(records_resp.data["granted_categories"], list(range(1, 14)))
        self.assertEqual(len(records_resp.data["records"]), 13)

    def test_records_endpoint_403_on_denied_decision(self):
        """Nurse rule case 3: neither assigned nor same ward -- hard denied."""
        _staff, token = self._login(
            "nurseRecordsApi", "pw-records-3", "STF-R902", Staff.Role.NURSE, ward="Ward A"
        )
        patient = Patient.objects.create(hospital_number="HN-R902", full_name="P", ward="Ward B")
        PatientCategoryRecord.objects.bulk_create(
            PatientCategoryRecord(patient=patient, category=c) for c, _ in PatientCategoryRecord.Category.choices
        )

        self.client.post(
            "/api/captures/contextual/target-patient/", {"patient_id": patient.id}, format="json", **self._auth(token)
        )
        decide_resp = self.client.post(
            "/api/scoring/decide/", {"patient_id": patient.id}, format="json", **self._auth(token)
        )
        self.assertEqual(decide_resp.data["decision_type"], AccessDecision.DecisionType.ACCESS_DENIED)

        records_resp = self.client.get(f"/api/scoring/patients/{patient.id}/records/", **self._auth(token))
        self.assertEqual(records_resp.status_code, status.HTTP_403_FORBIDDEN)


class StepUpVerificationTests(APITestCase):
    """Step-up verification for the 40-69% REDUCED_ACCESS band. CLAUDE.md's
    band table has always required it; originally enforced with a typed PIN
    (2026-09-06), replaced the same day with device biometrics (WebAuthn) +
    a colleague-vouches fallback -- see CLAUDE.md's amendment for why.

    The reduced-band decision is built directly rather than scored through the
    engine -- EngineFactorTests already covers the band arithmetic that
    produces one; what's under test here is the gate on top of it.

    Real biometric ceremonies can't be produced in a test, so
    verify_authentication_response is mocked, same convention as
    verify_registration_response in access.tests.WebAuthnRegistrationTests.
    """

    databases = {"default", "ledger"}

    def _login(self, username, password, staff_id, role):
        user = User.objects.create_user(username=username, password=password)
        staff = Staff.objects.create(
            user=user, staff_id=staff_id, full_name=username, role=role, ward="Ward A", on_duty=True,
        )
        resp = self.client.post(
            "/api/access/login/",
            {"username": username, "password": password, "device_id": f"device-{staff_id}", "device_type": "desktop"},
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED, resp.data)
        return staff, resp.data["token"]

    def _auth(self, token):
        return {"HTTP_AUTHORIZATION": f"Bearer {token}"}

    def _enroll_credential(self, staff, device_id, sign_count=0):
        device = Device.objects.get(staff=staff, device_id=device_id)
        return WebAuthnCredential.objects.create(
            staff=staff, device=device, credential_id=f"cred-{device.id}",
            public_key="fake-public-key", sign_count=sign_count,
        )

    def _reduced_decision(self, token, patient, decision_type=None):
        session = AccessSession.objects.get(token=token)
        return AccessDecision.objects.create(
            session=session,
            patient=patient,
            gate_passed=True,
            score=65.0,
            score_band=AccessDecision.ScoreBand.REDUCED,
            decision_type=decision_type or AccessDecision.DecisionType.REDUCED_ACCESS,
            granted_categories=[1, 2, 3, 4, 5, 6, 7, 12],
        )

    def _patient_with_records(self, hospital_number):
        patient = Patient.objects.create(hospital_number=hospital_number, full_name="P", ward="Ward A")
        PatientCategoryRecord.objects.bulk_create(
            PatientCategoryRecord(patient=patient, category=c)
            for c, _ in PatientCategoryRecord.Category.choices
        )
        return patient

    def test_records_blocked_until_webauthn_verified_then_released(self):
        staff, token = self._login("docStepUp1", "pw-stepup-1", "STF-SU1", Staff.Role.DOCTOR)
        self._enroll_credential(staff, "device-STF-SU1")
        patient = self._patient_with_records("HN-SU1")
        decision = self._reduced_decision(token, patient)

        blocked = self.client.get(f"/api/scoring/patients/{patient.id}/records/", **self._auth(token))
        self.assertEqual(blocked.status_code, status.HTTP_403_FORBIDDEN)
        self.assertTrue(blocked.data["step_up_required"])
        self.assertTrue(blocked.data["webauthn_available"])
        self.assertEqual(blocked.data["decision_id"], decision.id)

        options_resp = self.client.post(
            f"/api/scoring/decisions/{decision.id}/step-up/webauthn/options/", **self._auth(token)
        )
        self.assertEqual(options_resp.status_code, status.HTTP_200_OK)
        self.assertIn("challenge", options_resp.data)

        with patch(
            "scoring.views.verify_authentication_response",
            return_value=SimpleNamespace(new_sign_count=1),
        ):
            verified = self.client.post(
                f"/api/scoring/decisions/{decision.id}/step-up/webauthn/verify/",
                {"credential": {}}, format="json", **self._auth(token),
            )
        self.assertEqual(verified.status_code, status.HTTP_200_OK)
        self.assertTrue(verified.data["step_up_verified"])

        released = self.client.get(f"/api/scoring/patients/{patient.id}/records/", **self._auth(token))
        self.assertEqual(released.status_code, status.HTTP_200_OK)
        self.assertEqual(released.data["granted_categories"], [1, 2, 3, 4, 5, 6, 7, 12])
        self.assertEqual(len(released.data["records"]), 8)

        decision.refresh_from_db()
        self.assertTrue(decision.step_up_verified)
        self.assertIsNotNone(decision.step_up_verified_at)

        credential = WebAuthnCredential.objects.get(staff=staff)
        self.assertEqual(credential.sign_count, 1)
        self.assertIsNotNone(credential.last_used_at)

    def test_options_rejected_with_no_enrolled_credential(self):
        """No credential on this device -- the frontend should offer only
        the colleague-assist path in this case."""
        _staff, token = self._login("docStepUp2", "pw-stepup-2", "STF-SU2", Staff.Role.DOCTOR)
        patient = self._patient_with_records("HN-SU2")
        decision = self._reduced_decision(token, patient)

        resp = self.client.post(
            f"/api/scoring/decisions/{decision.id}/step-up/webauthn/options/", **self._auth(token)
        )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertFalse(resp.data["webauthn_available"])

        # The records gate itself reports the same thing, unprompted.
        blocked = self.client.get(f"/api/scoring/patients/{patient.id}/records/", **self._auth(token))
        self.assertFalse(blocked.data["webauthn_available"])

    def test_wrong_webauthn_response_counts_down_and_raises_an_alert(self):
        staff, token = self._login("docStepUp3", "pw-stepup-3", "STF-SU3", Staff.Role.DOCTOR)
        self._enroll_credential(staff, "device-STF-SU3")
        patient = self._patient_with_records("HN-SU3")
        decision = self._reduced_decision(token, patient)

        self.client.post(f"/api/scoring/decisions/{decision.id}/step-up/webauthn/options/", **self._auth(token))
        with patch(
            "scoring.views.verify_authentication_response",
            side_effect=InvalidAuthenticationResponse("Could not verify authentication signature"),
        ):
            resp = self.client.post(
                f"/api/scoring/decisions/{decision.id}/step-up/webauthn/verify/",
                {"credential": {}}, format="json", **self._auth(token),
            )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(resp.data["attempts_remaining"], 2)

        alert = SecurityAlert.objects.filter(alert_type=SecurityAlert.AlertType.STEP_UP_FAILED).first()
        self.assertIsNotNone(alert)
        self.assertEqual(alert.staff_id, "STF-SU3")
        self.assertEqual(alert.patient_hospital_number, "HN-SU3")
        self.assertEqual(alert.details["method"], "webauthn")
        self.assertFalse(alert.acknowledged)

        # Records still blocked; credential sign_count untouched by a failure.
        self.assertEqual(
            self.client.get(f"/api/scoring/patients/{patient.id}/records/", **self._auth(token)).status_code,
            status.HTTP_403_FORBIDDEN,
        )
        self.assertEqual(WebAuthnCredential.objects.get(staff=staff).sign_count, 0)

    def test_three_wrong_attempts_spend_the_decision(self):
        staff, token = self._login("docStepUp4", "pw-stepup-4", "STF-SU4", Staff.Role.DOCTOR)
        self._enroll_credential(staff, "device-STF-SU4")
        patient = self._patient_with_records("HN-SU4")
        decision = self._reduced_decision(token, patient)

        with patch(
            "scoring.views.verify_authentication_response",
            side_effect=InvalidAuthenticationResponse("bad signature"),
        ):
            for _ in range(3):
                self.client.post(
                    f"/api/scoring/decisions/{decision.id}/step-up/webauthn/options/", **self._auth(token)
                )
                self.client.post(
                    f"/api/scoring/decisions/{decision.id}/step-up/webauthn/verify/",
                    {"credential": {}}, format="json", **self._auth(token),
                )

        # Even a real success would be refused now -- they have to re-run /decide/.
        with patch(
            "scoring.views.verify_authentication_response",
            return_value=SimpleNamespace(new_sign_count=1),
        ):
            resp = self.client.post(
                f"/api/scoring/decisions/{decision.id}/step-up/webauthn/verify/",
                {"credential": {}}, format="json", **self._auth(token),
            )
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(resp.data["attempts_remaining"], 0)

        decision.refresh_from_db()
        self.assertFalse(decision.step_up_verified)
        self.assertEqual(
            SecurityAlert.objects.filter(alert_type=SecurityAlert.AlertType.STEP_UP_FAILED).count(), 3
        )

    def test_other_bands_are_unaffected(self):
        """Only the reduced band gates -- a full-access decision still returns
        records with no challenge, and so does Break the Glass."""
        _staff, token = self._login("docStepUp5", "pw-stepup-5", "STF-SU5", Staff.Role.DOCTOR)
        patient = self._patient_with_records("HN-SU5")
        session = AccessSession.objects.get(token=token)
        AccessDecision.objects.create(
            session=session, patient=patient, gate_passed=True, score=95.0,
            score_band=AccessDecision.ScoreBand.SILENT,
            decision_type=AccessDecision.DecisionType.STANDARD_ACCESS,
            granted_categories=list(range(1, 14)),
        )

        resp = self.client.get(f"/api/scoring/patients/{patient.id}/records/", **self._auth(token))
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(len(resp.data["records"]), 13)

    def test_webauthn_options_rejected_for_non_reduced_decision(self):
        _staff, token = self._login("docStepUp6", "pw-stepup-6", "STF-SU6", Staff.Role.DOCTOR)
        patient = self._patient_with_records("HN-SU6")
        decision = self._reduced_decision(
            token, patient, decision_type=AccessDecision.DecisionType.STANDARD_ACCESS
        )
        resp = self.client.post(
            f"/api/scoring/decisions/{decision.id}/step-up/webauthn/options/", **self._auth(token)
        )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_cannot_step_up_someone_elses_decision(self):
        """Scoped to the caller's own session -- and a 404, not a 403, so this
        can't be used to probe which decision IDs exist."""
        staff_a, token_a = self._login("docStepUp7", "pw-stepup-7", "STF-SU7", Staff.Role.DOCTOR)
        _staff_b, token_b = self._login("docStepUp8", "pw-stepup-8", "STF-SU8", Staff.Role.DOCTOR)
        self._enroll_credential(staff_a, "device-STF-SU7")
        patient = self._patient_with_records("HN-SU7")
        decision = self._reduced_decision(token_a, patient)

        resp = self.client.post(
            f"/api/scoring/decisions/{decision.id}/step-up/webauthn/options/", **self._auth(token_b)
        )
        self.assertEqual(resp.status_code, status.HTTP_404_NOT_FOUND)

    def test_decide_response_flags_step_up_required(self):
        staff, token = self._login("docStepUp9", "pw-stepup-9", "STF-SU9", Staff.Role.DOCTOR)
        self._enroll_credential(staff, "device-STF-SU9")
        patient = self._patient_with_records("HN-SU9")
        decision = self._reduced_decision(token, patient)

        blocked = self.client.get(f"/api/scoring/patients/{patient.id}/records/", **self._auth(token))
        self.assertTrue(blocked.data["step_up_required"])

        self.client.post(f"/api/scoring/decisions/{decision.id}/step-up/webauthn/options/", **self._auth(token))
        with patch(
            "scoring.views.verify_authentication_response", return_value=SimpleNamespace(new_sign_count=1)
        ):
            self.client.post(
                f"/api/scoring/decisions/{decision.id}/step-up/webauthn/verify/",
                {"credential": {}}, format="json", **self._auth(token),
            )
        decision.refresh_from_db()
        self.assertTrue(decision.step_up_verified)


class StepUpAssistTests(APITestCase):
    """The colleague-vouches fallback (added 2026-09-06) for a device with no
    biometric, or before the staff member has enrolled theirs."""

    databases = {"default", "ledger"}

    def _login(self, username, password, staff_id, role):
        user = User.objects.create_user(username=username, password=password)
        staff = Staff.objects.create(
            user=user, staff_id=staff_id, full_name=username, role=role, ward="Ward A", on_duty=True,
        )
        resp = self.client.post(
            "/api/access/login/",
            {"username": username, "password": password, "device_id": f"device-{staff_id}", "device_type": "desktop"},
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED, resp.data)
        return staff, resp.data["token"]

    def _auth(self, token):
        return {"HTTP_AUTHORIZATION": f"Bearer {token}"}

    def _reduced_decision(self, token, patient):
        session = AccessSession.objects.get(token=token)
        return AccessDecision.objects.create(
            session=session, patient=patient, gate_passed=True, score=65.0,
            score_band=AccessDecision.ScoreBand.REDUCED,
            decision_type=AccessDecision.DecisionType.REDUCED_ACCESS,
            granted_categories=[1, 2, 3, 4, 5, 6, 7, 12],
        )

    def test_request_creates_a_pending_row_visible_to_others_not_self(self):
        _requester, req_token = self._login("docAssist1", "pw-assist-1", "STF-AS1", Staff.Role.DOCTOR)
        _colleague, colleague_token = self._login("nurseAssist1", "pw-assist-2", "STF-AS2", Staff.Role.NURSE)
        patient = Patient.objects.create(hospital_number="HN-AS1", full_name="P", ward="Ward A")
        decision = self._reduced_decision(req_token, patient)

        resp = self.client.post(
            f"/api/scoring/decisions/{decision.id}/step-up/assist/request/", **self._auth(req_token)
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data["requesting_staff_id"], "STF-AS1")
        self.assertEqual(resp.data["patient_hospital_number"], "HN-AS1")
        self.assertEqual(resp.data["status"], "pending")

        # Visible to the colleague...
        colleague_view = self.client.get(
            "/api/scoring/step-up/assist-requests/", **self._auth(colleague_token)
        )
        self.assertEqual(len(colleague_view.data), 1)

        # ...but not to the requester themselves.
        own_view = self.client.get("/api/scoring/step-up/assist-requests/", **self._auth(req_token))
        self.assertEqual(len(own_view.data), 0)

    def test_duplicate_requests_do_not_pile_up(self):
        _requester, req_token = self._login("docAssist2", "pw-assist-3", "STF-AS3", Staff.Role.DOCTOR)
        patient = Patient.objects.create(hospital_number="HN-AS2", full_name="P", ward="Ward A")
        decision = self._reduced_decision(req_token, patient)

        self.client.post(f"/api/scoring/decisions/{decision.id}/step-up/assist/request/", **self._auth(req_token))
        self.client.post(f"/api/scoring/decisions/{decision.id}/step-up/assist/request/", **self._auth(req_token))

        self.assertEqual(
            StepUpAssistRequest.objects.filter(decision=decision, status="pending").count(), 1
        )

    def test_approve_verifies_the_decision_and_releases_records(self):
        _requester, req_token = self._login("docAssist3", "pw-assist-4", "STF-AS4", Staff.Role.DOCTOR)
        colleague, colleague_token = self._login("nurseAssist3", "pw-assist-5", "STF-AS5", Staff.Role.NURSE)
        patient = Patient.objects.create(hospital_number="HN-AS3", full_name="P", ward="Ward A")
        PatientCategoryRecord.objects.bulk_create(
            PatientCategoryRecord(patient=patient, category=c) for c, _ in PatientCategoryRecord.Category.choices
        )
        decision = self._reduced_decision(req_token, patient)

        req_resp = self.client.post(
            f"/api/scoring/decisions/{decision.id}/step-up/assist/request/", **self._auth(req_token)
        )
        assist_id = req_resp.data["id"]

        approve_resp = self.client.post(
            f"/api/scoring/step-up/assist-requests/{assist_id}/approve/", **self._auth(colleague_token)
        )
        self.assertEqual(approve_resp.status_code, status.HTTP_200_OK)
        self.assertEqual(approve_resp.data["status"], "approved")
        self.assertEqual(approve_resp.data["resolved_by_staff_id"], colleague.staff_id)

        decision.refresh_from_db()
        self.assertTrue(decision.step_up_verified)

        released = self.client.get(f"/api/scoring/patients/{patient.id}/records/", **self._auth(req_token))
        self.assertEqual(released.status_code, status.HTTP_200_OK)
        self.assertEqual(len(released.data["records"]), 8)

    def test_cannot_approve_own_request(self):
        _requester, req_token = self._login("docAssist4", "pw-assist-6", "STF-AS6", Staff.Role.DOCTOR)
        patient = Patient.objects.create(hospital_number="HN-AS4", full_name="P", ward="Ward A")
        decision = self._reduced_decision(req_token, patient)
        req_resp = self.client.post(
            f"/api/scoring/decisions/{decision.id}/step-up/assist/request/", **self._auth(req_token)
        )

        resp = self.client.post(
            f"/api/scoring/step-up/assist-requests/{req_resp.data['id']}/approve/", **self._auth(req_token)
        )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        decision.refresh_from_db()
        self.assertFalse(decision.step_up_verified)

    def test_decline_raises_an_alert_and_leaves_records_blocked(self):
        _requester, req_token = self._login("docAssist5", "pw-assist-7", "STF-AS7", Staff.Role.DOCTOR)
        colleague, colleague_token = self._login("nurseAssist5", "pw-assist-8", "STF-AS8", Staff.Role.NURSE)
        patient = Patient.objects.create(hospital_number="HN-AS5", full_name="P", ward="Ward A")
        decision = self._reduced_decision(req_token, patient)
        req_resp = self.client.post(
            f"/api/scoring/decisions/{decision.id}/step-up/assist/request/", **self._auth(req_token)
        )

        resp = self.client.post(
            f"/api/scoring/step-up/assist-requests/{req_resp.data['id']}/decline/", **self._auth(colleague_token)
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data["status"], "declined")

        decision.refresh_from_db()
        self.assertFalse(decision.step_up_verified)

        alert = SecurityAlert.objects.filter(alert_type=SecurityAlert.AlertType.STEP_UP_FAILED).first()
        self.assertIsNotNone(alert)
        self.assertEqual(alert.details["method"], "assist")
        self.assertEqual(alert.details["declined_by"], colleague.staff_id)

        self.assertEqual(
            self.client.get(f"/api/scoring/patients/{patient.id}/records/", **self._auth(req_token)).status_code,
            status.HTTP_403_FORBIDDEN,
        )

    def test_non_clinical_role_cannot_use_assist_endpoints(self):
        user = User.objects.create_user(username="assistAdmin", password="pw-assist-9")
        Staff.objects.create(user=user, staff_id="STF-AS9", full_name="Admin", role=Staff.Role.ADMIN)
        login = self.client.post(
            "/api/access/login/",
            {"username": "assistAdmin", "password": "pw-assist-9", "device_id": "device-STF-AS9", "device_type": "desktop"},
            format="json",
        )
        resp = self.client.get(
            "/api/scoring/step-up/assist-requests/",
            HTTP_AUTHORIZATION=f"Bearer {login.data['token']}",
        )
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)


class DeniedAccessAlertTests(ScoringTestBase):
    """CLAUDE.md: sub-40%/gate-failed means "ACCESS_DENIED, security alert
    triggered" -- the alert half, added 2026-09-06."""

    databases = {"default", "ledger"}

    def _login(self, username, password, staff_id, role, ward=""):
        user = User.objects.create_user(username=username, password=password)
        staff = Staff.objects.create(
            user=user, staff_id=staff_id, full_name=username, role=role, ward=ward, on_duty=True
        )
        resp = self.client.post(
            "/api/access/login/",
            {"username": username, "password": password, "device_id": f"device-{staff_id}", "device_type": "desktop"},
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED, resp.data)
        return staff, resp.data["token"]

    def _auth(self, token):
        return {"HTTP_AUTHORIZATION": f"Bearer {token}"}

    def test_denial_raises_an_alert_linked_to_its_ledger_entry(self):
        """Nurse rule case 3 (neither assigned nor same ward) -- a hard deny."""
        _staff, token = self._login("nurseAlertApi", "pw-denied-1", "STF-DA1", Staff.Role.NURSE, ward="Ward A")
        patient = Patient.objects.create(hospital_number="HN-DA1", full_name="P", ward="Ward B")

        self.client.post(
            "/api/captures/contextual/target-patient/", {"patient_id": patient.id}, format="json", **self._auth(token)
        )
        decide_resp = self.client.post(
            "/api/scoring/decide/", {"patient_id": patient.id}, format="json", **self._auth(token)
        )
        self.assertEqual(decide_resp.data["decision_type"], AccessDecision.DecisionType.ACCESS_DENIED)

        alert = SecurityAlert.objects.filter(alert_type=SecurityAlert.AlertType.ACCESS_DENIED).first()
        self.assertIsNotNone(alert)
        self.assertEqual(alert.staff_id, "STF-DA1")
        self.assertEqual(alert.patient_hospital_number, "HN-DA1")
        self.assertFalse(alert.acknowledged)

        # Linked back to the Ledger entry written for the same decision.
        entry = LedgerEntry.objects.using("ledger").order_by("-sequence").first()
        self.assertEqual(alert.ledger_sequence, entry.sequence)

    def test_granted_access_raises_no_alert(self):
        _staff, token = self._login("docAlertApi3", "pw-denied-2", "STF-DA2", Staff.Role.DOCTOR, ward="Ward A")
        patient = Patient.objects.create(hospital_number="HN-DA2", full_name="P", ward="Ward A")

        self.client.post(
            "/api/captures/contextual/target-patient/", {"patient_id": patient.id}, format="json", **self._auth(token)
        )
        decide_resp = self.client.post(
            "/api/scoring/decide/", {"patient_id": patient.id}, format="json", **self._auth(token)
        )
        self.assertNotEqual(decide_resp.data["decision_type"], AccessDecision.DecisionType.ACCESS_DENIED)
        self.assertEqual(SecurityAlert.objects.count(), 0)


class EmergencyOverrideTests(ScoringTestBase):
    """/api/scoring/emergency-override/ -- "Break the Glass" (CLAUDE.md Emergency
    Override). Always requires a logged-in session (IsClinicalStaff), still respects
    the role ceiling table, but bypasses the hard gate/score band/Nurse rule."""

    databases = {"default", "ledger"}

    def _login(self, username, password, staff_id, role, ward="", on_duty=True, on_call=False):
        user = User.objects.create_user(username=username, password=password)
        staff = Staff.objects.create(
            user=user, staff_id=staff_id, full_name=username, role=role, ward=ward,
            on_duty=on_duty, on_call=on_call,
        )
        resp = self.client.post(
            "/api/access/login/",
            {"username": username, "password": password, "device_id": f"device-{staff_id}", "device_type": "desktop"},
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED, resp.data)
        return staff, resp.data["token"]

    def _auth(self, token):
        return {"HTTP_AUTHORIZATION": f"Bearer {token}"}

    def test_override_is_the_only_path_for_nurse_case_3(self):
        """Nurse neither assigned nor on the patient's ward -- normal decide() hard-
        denies (engine.py's own comment says BTG is the only remaining path)."""
        staff, token = self._login("nurseBtg1", "pw-btg-1", "STF-BTG1", Staff.Role.NURSE, ward="Ward A")
        patient = Patient.objects.create(hospital_number="HN-BTG1", full_name="P", ward="Ward B")

        self.client.post(
            "/api/captures/contextual/target-patient/", {"patient_id": patient.id}, format="json", **self._auth(token)
        )
        decide_resp = self.client.post(
            "/api/scoring/decide/", {"patient_id": patient.id}, format="json", **self._auth(token)
        )
        self.assertEqual(decide_resp.data["decision_type"], AccessDecision.DecisionType.ACCESS_DENIED)

        override_resp = self.client.post(
            "/api/scoring/emergency-override/",
            {"patient_id": patient.id, "reason_category": "clinical_emergency", "reason": "Patient unresponsive, need immediate chart access"},
            format="json",
            **self._auth(token),
        )
        self.assertEqual(override_resp.status_code, status.HTTP_201_CREATED)
        self.assertEqual(override_resp.data["decision_type"], AccessDecision.DecisionType.EMERGENCY_OVERRIDE)
        self.assertEqual(override_resp.data["granted_categories"], list(range(1, 14)))
        self.assertIsNone(override_resp.data["score"])
        self.assertIsNone(override_resp.data["score_band"])

    def test_override_still_respects_role_ceiling(self):
        """A clerk invoking BTG still only gets categories 1-2 -- the role ceiling is
        the one boundary override doesn't cross."""
        staff, token = self._login("clerkBtg1", "pw-btg-2", "STF-BTG2", Staff.Role.CLERK)
        patient = Patient.objects.create(hospital_number="HN-BTG2", full_name="P", ward="Ward A")

        resp = self.client.post(
            "/api/scoring/emergency-override/",
            {"patient_id": patient.id, "reason_category": "clinical_emergency", "reason": "Need billing folder number urgently"},
            format="json",
            **self._auth(token),
        )
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
        self.assertEqual(resp.data["granted_categories"], [1, 2])

    def test_override_notifies_patient(self):
        """Patient SMS notifications (added 2026-09-14) -- every Break the
        Glass is unconditionally one of the four trigger types."""
        staff, token = self._login("docBtgNotify", "pw-btg-notify", "STF-BTGN", Staff.Role.DOCTOR, ward="Ward A")
        patient = Patient.objects.create(hospital_number="HN-BTGN", full_name="P", ward="Ward A")

        with patch("scoring.views.notify_patient") as mocked:
            resp = self.client.post(
                "/api/scoring/emergency-override/",
                {"patient_id": patient.id, "reason_category": "clinical_emergency", "reason": "Patient unresponsive, need immediate chart access"},
                format="json",
                **self._auth(token),
            )

        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
        mocked.assert_called_once()
        call_kwargs = mocked.call_args.kwargs
        self.assertEqual(call_kwargs["event_type"], AccessDecision.DecisionType.EMERGENCY_OVERRIDE)
        self.assertEqual(call_kwargs["patient"], patient)
        self.assertEqual(call_kwargs["staff"], staff)

    def test_override_bypasses_hard_behavioral_gate(self):
        """Same wildly-mismatched-typing setup as EngineFactorTests' hard-gate test
        (normal decide() would ACCESS_DENIED) -- BTG never even looks at behavioral
        similarity, so it must still succeed."""
        staff = self._make_staff("docBtgGate", "STF-BTG3", Staff.Role.DOCTOR, ward="Ward A", on_duty=True)
        session = self._make_session(staff)
        patient = Patient.objects.create(hospital_number="HN-BTG3", full_name="P", ward="Ward A")
        behavioral, contextual = self._make_captures(
            session, keystroke_features=dict(MISMATCHED_KEYSTROKE_FEATURES), patient=patient,
            assignment_status=ContextualCapture.PatientAssignmentStatus.ASSIGNED,
        )
        baseline_source = BehavioralCapture(keystroke_features={"login": dict(SAMPLE_KEYSTROKE_FEATURES), "session_windows": []})
        self._matching_baseline(staff, session, baseline_source)
        decision = compute_access_decision(session, patient)
        self.assertEqual(decision.decision_type, AccessDecision.DecisionType.ACCESS_DENIED)

        resp = self.client.post(
            "/api/access/login/",
            {"username": "docBtgGate", "password": "pw-scoring-test-1", "device_id": "dev-1", "device_type": "desktop"},
            format="json",
        )
        token = resp.data["token"]
        override_resp = self.client.post(
            "/api/scoring/emergency-override/",
            {"patient_id": patient.id, "reason_category": "clinical_emergency", "reason": "Hard gate false positive, verified identity in person"},
            format="json",
            **self._auth(token),
        )
        self.assertEqual(override_resp.status_code, status.HTTP_201_CREATED)
        self.assertEqual(override_resp.data["granted_categories"], list(range(1, 14)))

    def test_reason_required_and_must_meet_minimum_length(self):
        _staff, token = self._login("docBtg4", "pw-btg-4", "STF-BTG4", Staff.Role.DOCTOR, ward="Ward A")
        patient = Patient.objects.create(hospital_number="HN-BTG4", full_name="P", ward="Ward A")

        for body in [{"patient_id": patient.id}, {"patient_id": patient.id, "reason": "too short"}]:
            resp = self.client.post("/api/scoring/emergency-override/", body, format="json", **self._auth(token))
            self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_admin_and_security_officer_rejected(self):
        for role, suffix in [(Staff.Role.ADMIN, "adm"), (Staff.Role.SECURITY_OFFICER, "sec")]:
            _staff, token = self._login(f"nonClinicalBtg{suffix}", f"pw-btg-nc-{suffix}", f"STF-BTG-NC-{suffix}", role)
            patient = Patient.objects.create(hospital_number=f"HN-BTG-NC-{suffix}", full_name="P", ward="Ward A")
            resp = self.client.post(
                "/api/scoring/emergency-override/",
                {"patient_id": patient.id, "reason_category": "clinical_emergency", "reason": "Should never reach here"},
                format="json",
                **self._auth(token),
            )
            self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)

    def test_writes_exactly_one_ledger_entry_with_reason(self):
        staff, token = self._login("docBtg5", "pw-btg-5", "STF-BTG5", Staff.Role.DOCTOR, ward="Ward A")
        patient = Patient.objects.create(hospital_number="HN-BTG5", full_name="P", ward="Ward A")
        reason = "Trauma case, patient unconscious on arrival"

        resp = self.client.post(
            "/api/scoring/emergency-override/",
            {"patient_id": patient.id, "reason_category": "clinical_emergency", "reason": reason},
            format="json",
            **self._auth(token),
        )
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)

        entries = LedgerEntry.objects.using("ledger").filter(staff_id="STF-BTG5")
        self.assertEqual(entries.count(), 1)
        entry = entries.first()
        self.assertEqual(entry.event_type, LedgerEntry.EventType.EMERGENCY_OVERRIDE)
        self.assertEqual(entry.patient_hospital_number, "HN-BTG5")
        self.assertEqual(entry.details["reason"], reason)
        self.assertEqual(entry.details["reason_category"], "clinical_emergency")
        self.assertEqual(entry.details["granted_categories"], list(range(1, 14)))

    def test_baseline_not_reinforced_by_override(self):
        staff, token = self._login("docBtg6", "pw-btg-6", "STF-BTG6", Staff.Role.DOCTOR, ward="Ward A")
        patient = Patient.objects.create(hospital_number="HN-BTG6", full_name="P", ward="Ward A")
        BehavioralBaseline.objects.create(staff=staff, sample_count=3)

        self.client.post(
            "/api/scoring/emergency-override/",
            {"patient_id": patient.id, "reason_category": "clinical_emergency", "reason": "Confirming baseline stays untouched"},
            format="json",
            **self._auth(token),
        )

        baseline = BehavioralBaseline.objects.get(staff=staff)
        self.assertEqual(baseline.sample_count, 3)

    def test_records_endpoint_works_after_an_override(self):
        _staff, token = self._login("docBtg7", "pw-btg-7", "STF-BTG7", Staff.Role.DOCTOR, ward="Ward A")
        patient = Patient.objects.create(hospital_number="HN-BTG7", full_name="P", ward="Ward A")
        PatientCategoryRecord.objects.bulk_create(
            PatientCategoryRecord(patient=patient, category=c, content={"notes": f"cat {c}"})
            for c, _ in PatientCategoryRecord.Category.choices
        )

        override_resp = self.client.post(
            "/api/scoring/emergency-override/",
            {"patient_id": patient.id, "reason_category": "clinical_emergency", "reason": "Need full chart, code blue in progress"},
            format="json",
            **self._auth(token),
        )
        self.assertEqual(override_resp.status_code, status.HTTP_201_CREATED)

        records_resp = self.client.get(f"/api/scoring/patients/{patient.id}/records/", **self._auth(token))
        self.assertEqual(records_resp.status_code, status.HTTP_200_OK)
        self.assertEqual(records_resp.data["decision_type"], AccessDecision.DecisionType.EMERGENCY_OVERRIDE)
        self.assertEqual(len(records_resp.data["records"]), 13)

    # -- BTG availability gate (2026-08-29): blocked only when off duty AND neither
    # assigned nor on the patient's ward -- the same combination that now hard-denies
    # normal access. Every other combination keeps BTG available. --

    def test_btg_blocked_for_off_duty_unconnected_doctor(self):
        _staff, token = self._login(
            "docBtgBlocked", "pw-btg-8", "STF-BTG8", Staff.Role.DOCTOR, ward="Ward A", on_duty=False
        )
        patient = Patient.objects.create(hospital_number="HN-BTG8", full_name="P", ward="Ward B")

        resp = self.client.post(
            "/api/scoring/emergency-override/",
            {"patient_id": patient.id, "reason_category": "clinical_emergency", "reason": "Should be blocked before this is evaluated"},
            format="json",
            **self._auth(token),
        )
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)
        self.assertIn("off duty", resp.data["detail"])

    def test_btg_blocked_for_off_duty_unconnected_nurse(self):
        """New: unlike the normal Nurse rule (unaffected by duty status), BTG itself
        now additionally requires the nurse be on duty in her worst case."""
        _staff, token = self._login(
            "nurseBtgBlocked", "pw-btg-9", "STF-BTG9", Staff.Role.NURSE, ward="Ward A", on_duty=False
        )
        patient = Patient.objects.create(hospital_number="HN-BTG9", full_name="P", ward="Ward B")

        resp = self.client.post(
            "/api/scoring/emergency-override/",
            {"patient_id": patient.id, "reason_category": "clinical_emergency", "reason": "Should be blocked before this is evaluated"},
            format="json",
            **self._auth(token),
        )
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)

    def test_btg_available_for_on_duty_unconnected_doctor(self):
        _staff, token = self._login(
            "docBtgOnDuty", "pw-btg-10", "STF-BTG10", Staff.Role.DOCTOR, ward="Ward A", on_duty=True
        )
        patient = Patient.objects.create(hospital_number="HN-BTG10", full_name="P", ward="Ward B")

        resp = self.client.post(
            "/api/scoring/emergency-override/",
            {"patient_id": patient.id, "reason_category": "clinical_emergency", "reason": "On duty, so BTG stays available"},
            format="json",
            **self._auth(token),
        )
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)

    def test_btg_available_for_off_duty_assigned_doctor(self):
        staff, token = self._login(
            "docBtgAssigned", "pw-btg-11", "STF-BTG11", Staff.Role.DOCTOR, ward="Ward A", on_duty=False
        )
        patient = Patient.objects.create(hospital_number="HN-BTG11", full_name="P", ward="Ward B")
        PatientAssignment.objects.create(patient=patient, staff=staff, role_in_assignment="doctor")

        resp = self.client.post(
            "/api/scoring/emergency-override/",
            {"patient_id": patient.id, "reason_category": "clinical_emergency", "reason": "Off duty but assigned, BTG stays available"},
            format="json",
            **self._auth(token),
        )
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)

    def test_btg_available_for_off_duty_same_ward_doctor(self):
        _staff, token = self._login(
            "docBtgSameWard", "pw-btg-12", "STF-BTG12", Staff.Role.DOCTOR, ward="Ward A", on_duty=False
        )
        patient = Patient.objects.create(hospital_number="HN-BTG12", full_name="P", ward="Ward A")

        resp = self.client.post(
            "/api/scoring/emergency-override/",
            {"patient_id": patient.id, "reason_category": "clinical_emergency", "reason": "Off duty but same ward, BTG stays available"},
            format="json",
            **self._auth(token),
        )
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)

    def test_btg_available_for_on_duty_unconnected_nurse(self):
        _staff, token = self._login(
            "nurseBtgOnDuty", "pw-btg-13", "STF-BTG13", Staff.Role.NURSE, ward="Ward A", on_duty=True
        )
        patient = Patient.objects.create(hospital_number="HN-BTG13", full_name="P", ward="Ward B")

        resp = self.client.post(
            "/api/scoring/emergency-override/",
            {"patient_id": patient.id, "reason_category": "clinical_emergency", "reason": "On duty, her rescue path stays open"},
            format="json",
            **self._auth(token),
        )
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)

    def test_btg_available_for_off_duty_pharmacist(self):
        """Pharmacist/lab-tech/clerk have no assignment/ward concept -- the gate
        never applies to them, regardless of duty status."""
        _staff, token = self._login(
            "pharmBtgOffDuty", "pw-btg-14", "STF-BTG14", Staff.Role.PHARMACIST, on_duty=False
        )
        patient = Patient.objects.create(hospital_number="HN-BTG14", full_name="P", ward="Ward A")

        resp = self.client.post(
            "/api/scoring/emergency-override/",
            {"patient_id": patient.id, "reason_category": "clinical_emergency", "reason": "No assignment concept for this role"},
            format="json",
            **self._auth(token),
        )
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)

    # -- reason_category (2026-08-29): required; "cross_coverage" is the one value
    # that unlocks BTG through the off-duty+unconnected block on its own. --

    def test_reason_category_required_and_validated(self):
        _staff, token = self._login("docBtg15", "pw-btg-15", "STF-BTG15", Staff.Role.DOCTOR, ward="Ward A")
        patient = Patient.objects.create(hospital_number="HN-BTG15", full_name="P", ward="Ward A")

        for body in [
            {"patient_id": patient.id, "reason": "Missing category entirely here"},
            {"patient_id": patient.id, "reason_category": "not_a_real_category", "reason": "Invalid category value"},
        ]:
            resp = self.client.post("/api/scoring/emergency-override/", body, format="json", **self._auth(token))
            self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_on_call_unlocks_btg_for_off_duty_unconnected_doctor(self):
        _staff, token = self._login(
            "docBtgOnCall", "pw-btg-16", "STF-BTG16", Staff.Role.DOCTOR, ward="Ward A", on_duty=False, on_call=True
        )
        patient = Patient.objects.create(hospital_number="HN-BTG16", full_name="P", ward="Ward B")

        resp = self.client.post(
            "/api/scoring/emergency-override/",
            {"patient_id": patient.id, "reason_category": "clinical_emergency", "reason": "On call, reachable even though off duty"},
            format="json",
            **self._auth(token),
        )
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)

    def test_on_call_unlocks_btg_for_off_duty_unconnected_nurse(self):
        _staff, token = self._login(
            "nurseBtgOnCall", "pw-btg-17", "STF-BTG17", Staff.Role.NURSE, ward="Ward A", on_duty=False, on_call=True
        )
        patient = Patient.objects.create(hospital_number="HN-BTG17", full_name="P", ward="Ward B")

        resp = self.client.post(
            "/api/scoring/emergency-override/",
            {"patient_id": patient.id, "reason_category": "clinical_emergency", "reason": "On call, reachable even though off duty"},
            format="json",
            **self._auth(token),
        )
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)

    def test_cross_coverage_category_unlocks_btg_despite_off_duty_unconnected(self):
        """Self-attested: no location/time verification, the category itself is
        what lets it through (user's explicit design choice, 2026-08-29)."""
        _staff, token = self._login(
            "docBtgCrossCov", "pw-btg-18", "STF-BTG18", Staff.Role.DOCTOR, ward="Ward A", on_duty=False
        )
        patient = Patient.objects.create(hospital_number="HN-BTG18", full_name="P", ward="Ward B")

        resp = self.client.post(
            "/api/scoring/emergency-override/",
            {"patient_id": patient.id, "reason_category": "cross_coverage", "reason": "Covering for Dr. X, roster not updated yet"},
            format="json",
            **self._auth(token),
        )
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)

    def test_other_category_does_not_unlock_btg(self):
        _staff, token = self._login(
            "docBtgOther", "pw-btg-19", "STF-BTG19", Staff.Role.DOCTOR, ward="Ward A", on_duty=False
        )
        patient = Patient.objects.create(hospital_number="HN-BTG19", full_name="P", ward="Ward B")

        resp = self.client.post(
            "/api/scoring/emergency-override/",
            {"patient_id": patient.id, "reason_category": "other", "reason": "Some other justification here"},
            format="json",
            **self._auth(token),
        )
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)


class DisasterModeTests(ScoringTestBase):
    """/api/scoring/disaster-mode/(activate|deactivate)/ -- Admin-only hospital-wide
    switch (2026-08-29) that suspends the Doctor off-duty+unconnected hard-deny rule
    and BTG's availability gate. Audited in its own history table, not the Security
    Ledger (see DisasterModeEvent's docstring)."""

    databases = {"default", "ledger"}

    def _login(self, username, password, staff_id, role, ward="", on_duty=True):
        user = User.objects.create_user(username=username, password=password)
        staff = Staff.objects.create(
            user=user, staff_id=staff_id, full_name=username, role=role, ward=ward, on_duty=on_duty
        )
        resp = self.client.post(
            "/api/access/login/",
            {"username": username, "password": password, "device_id": f"device-{staff_id}", "device_type": "desktop"},
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED, resp.data)
        return staff, resp.data["token"]

    def _auth(self, token):
        return {"HTTP_AUTHORIZATION": f"Bearer {token}"}

    def test_non_admin_cannot_activate_or_deactivate(self):
        _staff, token = self._login("secDisaster1", "pw-dis-1", "STF-DIS1", Staff.Role.SECURITY_OFFICER)
        for path in ["activate", "deactivate"]:
            resp = self.client.post(
                f"/api/scoring/disaster-mode/{path}/", {"reason": "Should never reach here"},
                format="json", **self._auth(token),
            )
            self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)

    def test_reason_required_to_activate(self):
        _admin, token = self._login("adminDisaster1", "pw-dis-2", "STF-DIS2", Staff.Role.ADMIN)
        resp = self.client.post("/api/scoring/disaster-mode/activate/", {}, format="json", **self._auth(token))
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_activate_then_status_then_deactivate(self):
        admin, token = self._login("adminDisaster2", "pw-dis-3", "STF-DIS3", Staff.Role.ADMIN)

        status_resp = self.client.get("/api/scoring/disaster-mode/", **self._auth(token))
        self.assertFalse(status_resp.data["active"])
        self.assertIsNone(status_resp.data["last_event"])

        activate_resp = self.client.post(
            "/api/scoring/disaster-mode/activate/",
            {"reason": "Mass casualty incident, multi-vehicle collision"},
            format="json", **self._auth(token),
        )
        self.assertEqual(activate_resp.status_code, status.HTTP_201_CREATED)

        status_resp = self.client.get("/api/scoring/disaster-mode/", **self._auth(token))
        self.assertTrue(status_resp.data["active"])
        self.assertEqual(status_resp.data["last_event"]["staff_id"], "STF-DIS3")

        # Activating again while already active is rejected.
        double_activate_resp = self.client.post(
            "/api/scoring/disaster-mode/activate/",
            {"reason": "Trying to activate twice"},
            format="json", **self._auth(token),
        )
        self.assertEqual(double_activate_resp.status_code, status.HTTP_400_BAD_REQUEST)

        deactivate_resp = self.client.post(
            "/api/scoring/disaster-mode/deactivate/",
            {"reason": "Incident resolved, situation normal"},
            format="json", **self._auth(token),
        )
        self.assertEqual(deactivate_resp.status_code, status.HTTP_201_CREATED)

        status_resp = self.client.get("/api/scoring/disaster-mode/", **self._auth(token))
        self.assertFalse(status_resp.data["active"])

        # Deactivating again while already inactive is rejected.
        double_deactivate_resp = self.client.post(
            "/api/scoring/disaster-mode/deactivate/",
            {"reason": "Trying to deactivate twice"},
            format="json", **self._auth(token),
        )
        self.assertEqual(double_deactivate_resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_active_disaster_mode_suspends_doctor_hard_deny(self):
        admin, admin_token = self._login("adminDisaster3", "pw-dis-4", "STF-DIS4", Staff.Role.ADMIN)
        self.client.post(
            "/api/scoring/disaster-mode/activate/", {"reason": "Mass casualty, suspending duty checks"},
            format="json", **self._auth(admin_token),
        )

        staff = self._make_staff("docDisaster1", "STF-DIS5", Staff.Role.DOCTOR, ward="Ward A", on_duty=False)
        session = self._make_session(staff)
        patient = Patient.objects.create(hospital_number="HN-DIS5", full_name="P", ward="Ward B")
        behavioral, contextual = self._make_captures(
            session, patient=patient,
            assignment_status=ContextualCapture.PatientAssignmentStatus.NOT_ASSIGNED_NOT_SAME_WARD,
        )
        self._matching_baseline(staff, session, behavioral)

        decision = compute_access_decision(session, patient)
        self.assertEqual(decision.role_rule_path, "")
        self.assertNotEqual(decision.decision_type, AccessDecision.DecisionType.ACCESS_DENIED)

    def test_active_disaster_mode_suspends_btg_gate(self):
        admin, admin_token = self._login("adminDisaster4", "pw-dis-5", "STF-DIS6", Staff.Role.ADMIN)
        self.client.post(
            "/api/scoring/disaster-mode/activate/", {"reason": "Mass casualty, suspending BTG gate"},
            format="json", **self._auth(admin_token),
        )

        _staff, doc_token = self._login(
            "docDisaster2", "pw-dis-6", "STF-DIS7", Staff.Role.DOCTOR, ward="Ward A", on_duty=False
        )
        patient = Patient.objects.create(hospital_number="HN-DIS7", full_name="P", ward="Ward B")

        resp = self.client.post(
            "/api/scoring/emergency-override/",
            {"patient_id": patient.id, "reason_category": "clinical_emergency", "reason": "Disaster mode active, BTG unrestricted"},
            format="json", **self._auth(doc_token),
        )
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
