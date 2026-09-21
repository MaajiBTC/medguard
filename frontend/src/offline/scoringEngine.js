// Offline Mode (build step 6) -- a JS port of backend/scoring/engine.py's
// role-ceiling/band/role-rule logic, for use when the network is down (see
// the approved plan's design decisions #4-#6). This is the single highest-
// risk piece of Offline Mode: there's no JS test runner in this frontend,
// so parity is verified by spot-checking real historical decisions rather
// than an automated suite (flagged in the plan).
//
// IMPORTANT SIMPLIFICATION (not in engine.py, specific to offline use): of
// the engine's 7 weighted factors, only two -- on_duty (20%) and
// ward_assignment (15%) -- actually vary per patient within one login
// session; the other five (keystroke_touch, mouse, device, login_time,
// location) all depend only on session/staff/baseline data that's fixed
// for the whole session. So rather than re-deriving keystroke/mouse
// dynamics offline (which would need the full raw event history cached,
// not just the baseline), this reuses the *session-level* factor scores
// from the most recent successful online decision this session (cached
// whenever one succeeds -- see syncManager.js's refreshOfflineCache), and
// only recomputes the two genuinely patient-dependent factors fresh.

const ROLE_CEILINGS = {
  doctor: new Set([1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13]),
  nurse: new Set([1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13]),
  pharmacist: new Set([1, 4, 5, 6, 7]),
  lab_technician: new Set([1]),
  clerk: new Set([1, 2]),
};
const REDUCED_BAND_EXCLUDED_CATEGORIES = new Set([8, 9, 10, 11, 13]);

function scoreBand(score) {
  if (score >= 90) return 'SILENT';
  if (score >= 70) return 'AUDITED_DEVIATION';
  if (score >= 40) return 'REDUCED';
  return 'DENIED';
}

function bandToDecisionType(band) {
  return {
    SILENT: 'STANDARD_ACCESS',
    AUDITED_DEVIATION: 'AUDITED_DEVIATION',
    REDUCED: 'REDUCED_ACCESS',
    DENIED: 'ACCESS_DENIED',
  }[band];
}

/** Mirrors captures.services.compute_patient_assignment_status, using
 * cached data instead of a live query: `assignedPatientIds` is the set of
 * patient ids from the last-synced getMyAssignedPatients() call. */
function computePatientAssignmentStatus({ staffRole, staffWard, patientWard, patientId, assignedPatientIds }) {
  if (staffRole !== 'doctor' && staffRole !== 'nurse') return 'not_applicable';
  if (assignedPatientIds.has(patientId)) return 'assigned';
  const sameWard = Boolean(staffWard) && Boolean(patientWard) && staffWard.trim().toLowerCase() === patientWard.trim().toLowerCase();
  return sameWard ? 'same_ward_not_assigned' : 'not_assigned_not_same_ward';
}

/**
 * @param staff {{role: string, ward: string, on_duty: boolean, on_call: boolean}}
 * @param patient {{id: number, ward: string}}
 * @param assignedPatientIds {Set<number>}
 * @param sessionFactors - the last successful online decision's
 *   {gate_passed, factor_breakdown: {weights, factor_scores}} -- see the
 *   simplification note above. A decision computed fully offline (no prior
 *   online decision this session) can't reuse these and is refused instead
 *   of guessing (see ClinicalDashboard.jsx's caller).
 * @param disasterModeActive {boolean}
 */
function computeOfflineDecision({ staff, patient, assignedPatientIds, sessionFactors, disasterModeActive }) {
  const assignmentStatus = computePatientAssignmentStatus({
    staffRole: staff.role,
    staffWard: staff.ward,
    patientWard: patient.ward,
    patientId: patient.id,
    assignedPatientIds,
  });

  const { weights, factor_scores: cachedFactorScores } = sessionFactors.factor_breakdown;
  const onDutyScore = staff.on_duty ? 100.0 : 0.0;
  const wardOk = ['assigned', 'same_ward_not_assigned', 'not_applicable'].includes(assignmentStatus);
  const wardScore = wardOk ? 100.0 : 0.0;

  const factorScores = { ...cachedFactorScores, on_duty: onDutyScore, ward_assignment: wardScore };
  const score = Object.entries(weights).reduce((sum, [factor, weight]) => sum + (factorScores[factor] ?? 0) * (weight / 100), 0);

  const band = scoreBand(score);
  let decisionType = bandToDecisionType(band);
  let grantedCategories = [...ROLE_CEILINGS[staff.role]].sort((a, b) => a - b);
  if (band === 'REDUCED') {
    grantedCategories = grantedCategories.filter((c) => !REDUCED_BAND_EXCLUDED_CATEGORIES.has(c));
  }
  if (band === 'DENIED') {
    grantedCategories = [];
  }

  let roleRulePath = '';
  // on_call counts the same as on_duty, as everywhere else in this app. Shared by
  // both role rules below, mirroring engine.py.
  const effectivelyOnDuty = staff.on_duty || staff.on_call;

  if (staff.role === 'nurse') {
    if (assignmentStatus === 'assigned') {
      roleRulePath = 'assigned';
    } else if (assignmentStatus === 'same_ward_not_assigned') {
      if (effectivelyOnDuty || disasterModeActive) {
        roleRulePath = 'same_ward';
        decisionType = 'AUDITED_DEVIATION';
        grantedCategories = [...ROLE_CEILINGS.nurse].sort((a, b) => a - b);
      } else {
        // Off duty and not on call -- denied like the equivalent doctor case,
        // Break the Glass still available (added 2026-09-20).
        roleRulePath = 'off_duty_same_ward_denied';
        decisionType = 'ACCESS_DENIED';
        grantedCategories = [];
      }
    } else {
      roleRulePath = 'neither';
      decisionType = 'ACCESS_DENIED';
      grantedCategories = [];
    }
  } else if (staff.role === 'doctor') {
    // Mirrors engine.py's doctor rule: an off-duty (and not on-call) doctor who
    // isn't assigned is denied in BOTH unassigned cases. Same-ward keeps Break
    // the Glass available (added 2026-09-20); no-connection-at-all doesn't.
    if (!effectivelyOnDuty && !disasterModeActive) {
      if (assignmentStatus === 'not_assigned_not_same_ward') {
        roleRulePath = 'off_duty_denied';
        decisionType = 'ACCESS_DENIED';
        grantedCategories = [];
      } else if (assignmentStatus === 'same_ward_not_assigned') {
        roleRulePath = 'off_duty_same_ward_denied';
        decisionType = 'ACCESS_DENIED';
        grantedCategories = [];
      }
    }
  }

  // Step-up can't happen offline (WebAuthn and colleague-assist both need
  // the server) -- see design decision #4. The sensitivity exclusion above
  // still applies; this only flags that step-up itself was skipped.
  const stepUpDeferredOffline = decisionType === 'REDUCED_ACCESS';

  // Mirrors scoring/serializers.py's get_break_glass_blocked (added
  // 2026-09-20) so the Break the Glass button stays hidden in the same one
  // state offline as it is online: off duty, not on call, no assignment and
  // not the patient's ward. Disaster Mode suspends it, same as the server.
  const breakGlassBlocked =
    !staff.on_duty &&
    !staff.on_call &&
    !disasterModeActive &&
    assignmentStatus === 'not_assigned_not_same_ward';

  return {
    decision_type: decisionType,
    score,
    score_band: band,
    granted_categories: grantedCategories,
    role_rule_path: roleRulePath,
    gate_passed: sessionFactors.gate_passed,
    step_up_deferred_offline: stepUpDeferredOffline,
    break_glass_blocked: breakGlassBlocked,
    factor_breakdown: { weights, factor_scores: factorScores },
    computed_offline: true,
  };
}

export { ROLE_CEILINGS, REDUCED_BAND_EXCLUDED_CATEGORIES, computePatientAssignmentStatus, computeOfflineDecision };
