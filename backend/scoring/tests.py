"""Scoring Engine tests. Built the same way the rest of the suite is: construct
Staff/AccessSession/BehavioralCapture/ContextualCapture/Patient/PatientAssignment
directly via the ORM -- no real enrollment data, per CLAUDE.md."""

from django.contrib.auth.models import User
from rest_framework import status
from rest_framework.test import APITestCase

from access.models import AccessSession
from captures.models import BehavioralCapture, ContextualCapture
from patients.models import Patient, PatientAssignment, PatientCategoryRecord
from staff.models import Staff

from .baseline import extract_keystroke_features, extract_mouse_features
from .engine import compute_access_decision
from .models import AccessDecision, BehavioralBaseline

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
    def _make_staff(self, username, staff_id, role, ward="", on_duty=True):
        user = User.objects.create_user(username=username, password="pw-scoring-test-1")
        return Staff.objects.create(
            user=user, staff_id=staff_id, full_name=username, role=role, ward=ward, on_duty=on_duty
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
        staff = self._make_staff("docReduced", "STF-703", Staff.Role.DOCTOR, ward="Ward A", on_duty=False)
        session = self._make_session(staff)
        patient = Patient.objects.create(hospital_number="HN-703", full_name="P4", ward="Ward B")
        behavioral, contextual = self._make_captures(
            session, patient=patient,
            assignment_status=ContextualCapture.PatientAssignmentStatus.NOT_ASSIGNED_NOT_SAME_WARD,
        )
        self._matching_baseline(staff, session, behavioral)
        # on_duty fails (-20), ward fails (-15) -> 65% -> reduced band.
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
        self.assertEqual(decision.nurse_path, "assigned")
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
        self.assertEqual(decision.nurse_path, "same_ward")
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
        self.assertEqual(decision.nurse_path, "neither")
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
