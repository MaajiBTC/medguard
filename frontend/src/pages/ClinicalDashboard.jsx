import { startAuthentication } from '@simplewebauthn/browser';
import { useCallback, useEffect, useState } from 'react';

import { getCurrentSession } from '../api/auth';
import { identifyFingerprint } from '../api/identity';
import { getMyAssignedPatients, getPatientSummary, searchPatients } from '../api/patients';
import {
  approveStepUpAssist,
  declineStepUpAssist,
  decide,
  emergencyOverride,
  getMyBaseline,
  getPatientRecords,
  getStepUpAssistRequests,
  getStepUpWebAuthnOptions,
  requestStepUpAssist,
  verifyStepUpWebAuthn,
} from '../api/scoring';
import { useContextualCapture } from '../capture/contextual/useContextualCapture';
import { ROLE_CEILINGS, computeOfflineDecision, computePatientAssignmentStatus } from '../offline/scoringEngine';
import {
  cacheOwnProfile,
  getCachedPatient,
  getCachedSession,
  isOnline,
  queueLength,
  queueOfflineEvent,
  refreshOfflineCache,
  trySync,
} from '../offline/syncManager';
import { WARDS } from '../wards';
import DashboardShell, { PatientsIcon, SearchIcon } from './DashboardShell';

// Offline Mode (build step 6) -- how often the pending-sync badge refreshes
// and a resync is attempted regardless of the browser's own online/offline
// events. Needed because navigator.onLine only reflects link-layer state:
// if a demo simulates disconnection by stopping the local Django dev server
// rather than toggling network conditions, the browser's `online` event
// never fires at all, so a plain polling fallback is what actually recovers.
const OFFLINE_SYNC_POLL_MS = 10000;

const ASSIGNMENT_ROLES = new Set(['doctor', 'nurse']);
// Decision types where the session already has everything Break the Glass
// could possibly add -- STANDARD_ACCESS/AUDITED_DEVIATION already grant full
// role-permitted access, and EMERGENCY_OVERRIDE means it was already used.
const FULL_ACCESS_DECISION_TYPES = new Set(['STANDARD_ACCESS', 'AUDITED_DEVIATION', 'EMERGENCY_OVERRIDE']);
// Any-other-colleague's pending assist requests -- same cadence
// DashboardShell already uses for the pending-device badge.
const ASSIST_BANNER_POLL_MS = 10000;
// While waiting for a colleague to vouch for MY OWN request, same cadence
// the rest of this app already polls a live feed at.
const ASSIST_WAIT_POLL_MS = 5000;

function errorMessage(err) {
  return (err.data && (err.data.detail || JSON.stringify(err.data))) || err.message;
}

function formatRole(role) {
  return role.split('_').map((w) => w[0].toUpperCase() + w.slice(1)).join(' ');
}

function wardLabel(value) {
  return WARDS.find((w) => w.value === value)?.label || value;
}

// Offline Mode -- the `staff` prop is deliberately minimal (staff_id/
// full_name/role only, see App.jsx's AuthenticatedShell), but
// scoringEngine.js's offline decisions need the LIVE on_duty/on_call/ward
// fields too -- those only come from getCurrentSession(). Every place that
// caches "staff" for offline use must merge the two, or offline scores
// silently compute against undefined duty/ward and drift from the real
// online score.
function offlineStaffSnapshot(staff, session) {
  return {
    staff_id: staff.staff_id,
    full_name: staff.full_name,
    role: staff.role,
    on_duty: session ? session.on_duty : false,
    on_call: session ? session.on_call : false,
    ward: session ? session.ward : '',
  };
}

function timeAgo(isoString) {
  const minutes = Math.max(0, Math.round((Date.now() - new Date(isoString).getTime()) / 60000));
  if (minutes < 1) return 'just now';
  if (minutes === 1) return '1 minute ago';
  return `${minutes} minutes ago`;
}

/** MedGuard Identity (CLAUDE.md bonus, step 7, added 2026-09-14) --
 * identifies an *unknown* patient (unconscious, or otherwise unable to give
 * their hospital number) from a fingerprint photo. This is a scan-to-find
 * step, not gated behind an existing patient selection -- it doubles as
 * one, via `onView`. Deliberately doesn't try to work offline: real
 * minutiae extraction/matching needs image-processing that has no ready
 * client-side port (see the approved plan) -- this only ever calls the
 * server.
 *
 * Rendering is controlled by the parent (a button beside Search toggles
 * `open`, added 2026-09-14 per the user -- previously this owned its own
 * <details> toggle sitting above the whole "Find a patient" section; moved
 * to live inside it, right next to the normal search entry point, since
 * this is really just a second way into the same "find a patient" job).
 *
 * A match (the backend's best-scoring enrolled template above
 * settings.FINGERPRINT_MATCH_THRESHOLD -- not literally 100%, whatever the
 * closest real match is) opens the patient's record automatically and
 * closes this dropdown, same day, per the user -- no separate "View full
 * record" click needed. */
function FingerprintLookup({ open, onView, onClose }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const [result, setResult] = useState(null);

  if (!open) return null;

  const handleFile = async (event) => {
    const file = event.target.files && event.target.files[0];
    event.target.value = '';
    if (!file) return;
    setBusy(true);
    setError(null);
    setResult(null);
    try {
      const data = await identifyFingerprint(file);
      setResult(data);
      if (data.matched) {
        onView(data.patient);
        onClose();
      }
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="panel-card assist-banner">
      <p className="meta-line">
        For a patient who can't otherwise be identified (unconscious, or the
        network's down and they aren't already cached). Scans against every
        enrolled fingerprint and opens their record automatically on a
        match, using a minimal emergency summary until the full record loads.
      </p>
      <label className="btn-secondary file-label">
        {busy ? 'Identifying…' : 'Scan / upload fingerprint'}
        <input type="file" accept="image/*" onChange={handleFile} disabled={busy} hidden />
      </label>

      {error && <p role="alert" className="dev-error">{error}</p>}

      {/* A match closes this dropdown and opens the record immediately
          (see handleFile above) -- so by the time a render could show a
          "matched" card here, this component has already unmounted. Only
          the no-match case is ever actually seen. */}
      {result && !result.matched && (
        <p className="meta-line">No match found (best score: {result.score}%).</p>
      )}
    </div>
  );
}

/** Any *other* clinical colleague's pending step-up assist requests (added
 * 2026-09-06) -- the fallback path for a device with no enrolled biometric.
 * Lives at the top of this dashboard, independent of whatever patient (if
 * any) the viewing clinician has open, since a colleague could need help at
 * any moment. */
function AssistRequestsBanner() {
  const [requests, setRequests] = useState([]);
  const [error, setError] = useState(null);
  const [actioningId, setActioningId] = useState(null);

  const fetchRequests = useCallback(async () => {
    try {
      setRequests(await getStepUpAssistRequests());
      setError(null);
    } catch (err) {
      setError(errorMessage(err));
    }
  }, []);

  useEffect(() => {
    fetchRequests();
    const intervalId = setInterval(fetchRequests, ASSIST_BANNER_POLL_MS);
    return () => clearInterval(intervalId);
  }, [fetchRequests]);

  const respond = async (id, action) => {
    setActioningId(id);
    try {
      await action(id);
      await fetchRequests();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setActioningId(null);
    }
  };

  if (requests.length === 0 && !error) return null;

  return (
    <section className="panel-card assist-banner">
      <h3>Colleagues asking for step-up verification</h3>
      {error && <p role="alert" className="dev-error">{error}</p>}
      {requests.map((r) => (
        <div className="card-row" key={r.id}>
          <div className="card-row-main">
            <div className="name-line">
              {r.requesting_staff_name} ({formatRole(r.requesting_staff_role)})
            </div>
            <div className="meta-line">
              Patient {r.patient_hospital_number} · requested {timeAgo(r.requested_at)}
            </div>
          </div>
          <div className="card-row-actions">
            <button
              type="button"
              className="btn-primary"
              disabled={actioningId === r.id}
              onClick={() => respond(r.id, approveStepUpAssist)}
            >
              Approve
            </button>
            <button
              type="button"
              className="btn-secondary"
              disabled={actioningId === r.id}
              onClick={() => respond(r.id, declineStepUpAssist)}
            >
              Decline
            </button>
          </div>
        </div>
      ))}
    </section>
  );
}

/**
 * The real step-4 search -> view flow: search a patient, set them as the session's
 * target (useContextualCapture, already built for step 1), request a decision
 * (scoring.decide), then render only the categories that decision actually granted.
 */
function ClinicalDashboard({ staff, onLogout }) {
  const [session, setSession] = useState(null);
  const [assignedPatients, setAssignedPatients] = useState([]);

  const [query, setQuery] = useState('');
  const [results, setResults] = useState([]);
  const [searching, setSearching] = useState(false);
  // MedGuard Identity's fingerprint lookup dropdown (added 2026-09-14,
  // moved beside Search per the user -- was its own always-visible section
  // above "Find a patient").
  const [fingerprintOpen, setFingerprintOpen] = useState(false);
  // Browse-by-ward (added 2026-09-12), same pattern as AdminDashboard.jsx's
  // PatientPanel -- ward tiles by default, drill into a ward's patient list,
  // search scoped to whichever ward (if any) is currently selected.
  const [selectedWard, setSelectedWard] = useState(null);
  const [wardCounts, setWardCounts] = useState(null);
  const [wardCountsError, setWardCountsError] = useState(null);

  const [selectedPatient, setSelectedPatient] = useState(null);
  const [decision, setDecision] = useState(null);
  const [records, setRecords] = useState(null);
  const [viewError, setViewError] = useState(null);
  const [viewLoading, setViewLoading] = useState(false);

  const [overrideOpen, setOverrideOpen] = useState(false);
  const [overrideCategory, setOverrideCategory] = useState('');
  const [overrideReason, setOverrideReason] = useState('');
  const [overrideSubmitting, setOverrideSubmitting] = useState(false);
  const [overrideError, setOverrideError] = useState(null);

  // stepUpMode: null (choosing a method) | 'assist-waiting' (request sent,
  // polling for a colleague's response).
  const [stepUpMode, setStepUpMode] = useState(null);
  const [stepUpSubmitting, setStepUpSubmitting] = useState(false);
  const [stepUpError, setStepUpError] = useState(null);

  // Offline Mode (build step 6) -- `online` mirrors navigator.onLine (link
  // layer only, see syncManager.js's isOnline() comment); the actual
  // offline *behavior* (falling back to cached data) is triggered by a real
  // failed request, not this flag, so it stays correct even when the flag
  // itself lags (e.g. the backend, not the network, is what's down).
  const [online, setOnline] = useState(isOnline());
  const [offlinePendingCount, setOfflinePendingCount] = useState(0);

  const { setTargetPatient } = useContextualCapture();

  useEffect(() => {
    let assignedIds = new Set();
    const loadAssigned =
      staff && ASSIGNMENT_ROLES.has(staff.role)
        ? getMyAssignedPatients()
            .then((data) => {
              setAssignedPatients(data);
              assignedIds = new Set(data.map((p) => p.patient_id));
              return data;
            })
            .catch(() => [])
        : Promise.resolve([]);

    Promise.all([getCurrentSession().catch(() => null), loadAssigned, getMyBaseline().catch(() => null)]).then(
      ([sessionData, _assigned, baselineData]) => {
        if (sessionData) setSession(sessionData);
        // Cached even before any decide() this session, so a device that
        // disconnects before viewing a single patient still has its own
        // profile/assignment/ward data available offline (see
        // ClinicalDashboard's offline branches below) -- just not yet a
        // sessionFactors snapshot, which only a real decide() can produce.
        if (sessionData && baselineData) {
          cacheOwnProfile({
            staff: offlineStaffSnapshot(staff, sessionData),
            session: sessionData,
            assignedPatientIds: assignedIds,
            disasterModeActive: baselineData.disaster_mode_active,
            baseline: baselineData,
          }).catch(() => {});
        }
      }
    );

    getPatientSummary()
      .then(setWardCounts)
      .catch((err) => setWardCountsError(errorMessage(err)));
  }, [staff]);

  // Offline Mode -- keeps the header's pending-sync badge current and
  // resyncs on a plain timer (see OFFLINE_SYNC_POLL_MS above) as well as on
  // the browser's own online event, so a queued batch doesn't just sit
  // there until the next manual page action.
  useEffect(() => {
    const refreshPending = () => queueLength().then(setOfflinePendingCount).catch(() => {});
    refreshPending();

    const attemptSync = async () => {
      try {
        await trySync();
      } catch {
        // Still unreachable -- stays queued for the next attempt.
      }
      refreshPending();
    };

    const handleOnline = () => {
      setOnline(true);
      attemptSync();
    };
    const handleOffline = () => setOnline(false);

    window.addEventListener('online', handleOnline);
    window.addEventListener('offline', handleOffline);
    const intervalId = setInterval(attemptSync, OFFLINE_SYNC_POLL_MS);
    return () => {
      window.removeEventListener('online', handleOnline);
      window.removeEventListener('offline', handleOffline);
      clearInterval(intervalId);
    };
  }, []);

  // Ward-scoped, mirrors AdminDashboard.jsx's PatientPanel.runSearch --
  // minus its 'unassigned' tile (deliberately not offered here, see the
  // ward-tile grid below), so this only ever needs the one real ward filter.
  const handleSearch = async (event) => {
    event.preventDefault();
    closePatientDetail();
    setSearching(true);
    try {
      setResults(await searchPatients(query, selectedWard || undefined));
    } catch {
      setResults([]);
    } finally {
      setSearching(false);
    }
  };

  // Closes whichever patient's detail panel is open, if any -- same fields
  // openPatient() resets when it opens a new one, but nothing previously
  // reset them when navigating *away* within Find a patient, so a
  // previously viewed patient stayed rendered underneath the ward tiles/
  // list even after going back. Called by every navigation action below.
  const closePatientDetail = () => {
    setSelectedPatient(null);
    setDecision(null);
    setRecords(null);
    setViewError(null);
    setOverrideOpen(false);
    setOverrideCategory('');
    setOverrideReason('');
    setOverrideError(null);
    setStepUpMode(null);
    setStepUpError(null);
  };

  const selectWardCategory = async (wardValue) => {
    closePatientDetail();
    setSelectedWard(wardValue);
    setQuery('');
    try {
      setResults(await searchPatients('', wardValue));
    } catch {
      setResults([]);
    }
  };

  const backToWards = () => {
    closePatientDetail();
    setSelectedWard(null);
    setQuery('');
    setResults([]);
  };

  const showingWards = selectedWard === null && !query.trim();

  // Offline Mode -- serves a decision + records from the last-synced cache
  // when there's genuinely no network to reach, rather than just failing.
  // See scoringEngine.js's top comment for the session-level-factor-reuse
  // simplification this depends on, and offline/syncManager.js for the
  // cache/queue mechanics.
  const openPatientOffline = async (patient) => {
    const [cachedPatient, cachedSession] = await Promise.all([
      getCachedPatient(patient.id),
      getCachedSession(),
    ]);

    if (!cachedSession || !cachedSession.sessionFactors) {
      setViewError({
        detail: 'No offline data available yet for this account — connect and view a patient once first.',
      });
      return;
    }
    if (!cachedPatient) {
      setViewError({
        detail: "This patient hasn't been made available offline yet — view them once while connected first.",
      });
      return;
    }

    const assignedIds = new Set(cachedSession.assignedPatientIds || []);
    const decisionData = computeOfflineDecision({
      staff: cachedSession.staff,
      patient: { id: patient.id, ward: cachedPatient.patient.ward },
      assignedPatientIds: assignedIds,
      sessionFactors: cachedSession.sessionFactors,
      disasterModeActive: cachedSession.disasterModeActive,
    });
    setDecision(decisionData);

    if (decisionData.decision_type !== 'ACCESS_DENIED') {
      // The currently-granted set can be narrower than what was cached
      // (e.g. the cached fetch happened during a full AUDITED_DEVIATION,
      // but going/duty status has since changed) -- filter again here so
      // offline access never shows more than this decision just granted.
      const grantedSet = new Set(decisionData.granted_categories);
      setRecords({
        ...cachedPatient.records,
        records: cachedPatient.records.records.filter((r) => grantedSet.has(r.category)),
      });
    }

    await queueOfflineEvent({
      eventType: decisionData.decision_type,
      patientHospitalNumber: patient.hospital_number,
      details: {
        score: decisionData.score,
        score_band: decisionData.score_band,
        granted_categories: decisionData.granted_categories,
        role_rule_path: decisionData.role_rule_path,
        factor_breakdown: decisionData.factor_breakdown,
        step_up_deferred_offline: decisionData.step_up_deferred_offline,
        computed_offline: true,
      },
    });
    setOfflinePendingCount(await queueLength());
  };

  const openPatient = async (patient) => {
    setSelectedPatient(patient);
    setDecision(null);
    setRecords(null);
    setViewError(null);
    setViewLoading(true);
    setOverrideOpen(false);
    setOverrideCategory('');
    setOverrideReason('');
    setOverrideError(null);
    setStepUpMode(null);
    setStepUpError(null);

    if (!online) {
      await openPatientOffline(patient);
      setViewLoading(false);
      return;
    }

    try {
      await setTargetPatient(patient.id);
      const decisionData = await decide(patient.id);
      setDecision(decisionData);
      // A reduced-access decision releases nothing until the step-up PIN is
      // entered (CLAUDE.md's 40-69% band). The backend enforces this too --
      // getPatientRecords() would 403 -- so we simply don't ask yet.
      if (decisionData.decision_type !== 'ACCESS_DENIED' && !decisionData.step_up_required) {
        const recordsData = await getPatientRecords(patient.id);
        setRecords(recordsData);
        // Fire-and-forget: caching for offline use must never block the
        // (already-successful) online view on IndexedDB -- disasterModeActive
        // isn't re-looked-up here, it's carried forward from whatever
        // cacheOwnProfile last stored (refreshOfflineCache merges rather than
        // overwriting the cached session row).
        refreshOfflineCache({
          patient,
          decision: decisionData,
          records: recordsData,
          staff: offlineStaffSnapshot(staff, session),
          session,
          assignedPatientIds: new Set(assignedPatients.map((p) => p.patient_id)),
        }).catch(() => {});
      }
    } catch (err) {
      if (err.status === undefined) {
        // A real network failure (fetch never got a response), not a
        // server-side rejection -- fall back to the offline cache.
        await openPatientOffline(patient);
      } else {
        setViewError(err.data || { detail: err.message });
      }
    } finally {
      setViewLoading(false);
    }
  };

  // Poll while waiting for a colleague to vouch (added 2026-09-06) -- reuses
  // the existing records endpoint rather than a dedicated poll endpoint: it
  // starts returning 200 the instant step_up_verified flips, same as any
  // other 5s-poll pattern already used in this app.
  useEffect(() => {
    if (stepUpMode !== 'assist-waiting' || !selectedPatient) return undefined;
    const intervalId = setInterval(async () => {
      try {
        const recordsData = await getPatientRecords(selectedPatient.id);
        setRecords(recordsData);
        setDecision((d) => (d ? { ...d, step_up_required: false, step_up_verified: true } : d));
        setStepUpMode(null);
      } catch {
        /* still waiting -- not an error worth surfacing on every poll tick */
      }
    }, ASSIST_WAIT_POLL_MS);
    return () => clearInterval(intervalId);
  }, [stepUpMode, selectedPatient]);

  const handleWebAuthnStepUp = async () => {
    if (!decision || !selectedPatient) return;
    setStepUpSubmitting(true);
    setStepUpError(null);
    try {
      const optionsJSON = await getStepUpWebAuthnOptions(decision.id);
      const credential = await startAuthentication({ optionsJSON });
      await verifyStepUpWebAuthn(decision.id, credential);
      setDecision({ ...decision, step_up_required: false, step_up_verified: true });
      const recordsData = await getPatientRecords(selectedPatient.id);
      setRecords(recordsData);
    } catch (err) {
      setStepUpError(err.data || { detail: err.message });
    } finally {
      setStepUpSubmitting(false);
    }
  };

  const handleRequestAssist = async () => {
    if (!decision) return;
    setStepUpError(null);
    try {
      await requestStepUpAssist(decision.id);
      setStepUpMode('assist-waiting');
    } catch (err) {
      setStepUpError(err.data || { detail: err.message });
    }
  };

  // Offline Mode -- Break the Glass needs no scoring at all (role ceiling +
  // assignment/ward + reason), so this is simpler than openPatientOffline.
  // Mirrors EmergencyOverrideView's own off-duty+unconnected block exactly
  // (see CLAUDE.md's Emergency Override section) using cached data instead
  // of a live query.
  const emergencyOverrideOffline = async () => {
    const cachedSession = await getCachedSession();
    if (!cachedSession) {
      setOverrideError({ detail: 'No offline data available yet — connect once first.' });
      return;
    }
    const cachedPatient = await getCachedPatient(selectedPatient.id);
    const patientWard = cachedPatient ? cachedPatient.patient.ward : '';
    const assignedIds = new Set(cachedSession.assignedPatientIds || []);
    const { staff: cachedStaff, disasterModeActive } = cachedSession;

    const assignmentStatus = computePatientAssignmentStatus({
      staffRole: cachedStaff.role,
      staffWard: cachedStaff.ward,
      patientWard,
      patientId: selectedPatient.id,
      assignedPatientIds: assignedIds,
    });
    const effectivelyOnDuty = cachedStaff.on_duty || cachedStaff.on_call;
    const blocked =
      (cachedStaff.role === 'doctor' || cachedStaff.role === 'nurse') &&
      !effectivelyOnDuty &&
      assignmentStatus === 'not_assigned_not_same_ward' &&
      !disasterModeActive &&
      overrideCategory !== 'cross_coverage';

    if (blocked) {
      setOverrideError({
        detail:
          'Break the Glass is unavailable offline for an off-duty session with no connection to this patient — select "Cross-coverage" if that applies, or try again once reconnected.',
      });
      return;
    }

    const grantedCategories = [...ROLE_CEILINGS[cachedStaff.role]].sort((a, b) => a - b);
    setDecision({ decision_type: 'EMERGENCY_OVERRIDE', granted_categories: grantedCategories, computed_offline: true });
    setViewError(null);

    if (cachedPatient) {
      const grantedSet = new Set(grantedCategories);
      setRecords({
        ...cachedPatient.records,
        records: cachedPatient.records.records.filter((r) => grantedSet.has(r.category)),
      });
    }

    await queueOfflineEvent({
      eventType: 'EMERGENCY_OVERRIDE',
      patientHospitalNumber: selectedPatient.hospital_number,
      details: {
        reason_category: overrideCategory,
        reason: overrideReason,
        granted_categories: grantedCategories,
        computed_offline: true,
      },
    });
    setOfflinePendingCount(await queueLength());
    setOverrideOpen(false);
    setOverrideCategory('');
    setOverrideReason('');
  };

  const handleEmergencyOverride = async (event) => {
    event.preventDefault();
    if (!selectedPatient) return;
    setOverrideSubmitting(true);
    setOverrideError(null);

    if (!online) {
      await emergencyOverrideOffline();
      setOverrideSubmitting(false);
      return;
    }

    try {
      const decisionData = await emergencyOverride(selectedPatient.id, overrideCategory, overrideReason);
      setDecision(decisionData);
      setViewError(null);
      const recordsData = await getPatientRecords(selectedPatient.id);
      setRecords(recordsData);
      setOverrideOpen(false);
      setOverrideCategory('');
      setOverrideReason('');
    } catch (err) {
      if (err.status === undefined) {
        await emergencyOverrideOffline();
      } else {
        setOverrideError(err.data || { detail: err.message });
      }
    } finally {
      setOverrideSubmitting(false);
    }
  };

  // Break the Glass makes no sense once the session already has everything
  // it's going to get: STANDARD_ACCESS/AUDITED_DEVIATION already grant full
  // role-permitted access, and EMERGENCY_OVERRIDE means BTG was already used
  // for this session/patient. Only REDUCED_ACCESS and ACCESS_DENIED (or no
  // decision yet) leave something for it to actually rescue.
  const hideBreakGlass = decision && FULL_ACCESS_DECISION_TYPES.has(decision.decision_type);

  // Offline Mode -- shown in the header while disconnected or while queued
  // events from an earlier disconnection still haven't synced.
  let offlineStatus = null;
  if (!online) {
    offlineStatus = offlinePendingCount > 0 ? `Offline — ${offlinePendingCount} pending` : 'Offline';
  } else if (offlinePendingCount > 0) {
    offlineStatus = `${offlinePendingCount} pending sync`;
  }

  return (
    <DashboardShell
      navItems={[{ key: 'patients', label: 'Patients', icon: <PatientsIcon /> }]}
      activeItem="patients"
      onNavChange={() => {}}
      staff={staff}
      onLogout={onLogout}
      title="Patients"
      offlineStatus={offlineStatus}
    >
      {session && (
        <p className="meta-line">
          {session.on_duty ? 'On duty' : 'Off duty'}
          {session.ward ? ` · ${session.ward}` : ''}
        </p>
      )}

      <AssistRequestsBanner />

      <section>
        <h2>Find a patient</h2>

        {selectedWard !== null && (
          <button type="button" className="back-link" onClick={backToWards}>
            ← Back to wards
          </button>
        )}

        <div className="search-row">
          <form className="search-bar" onSubmit={handleSearch} role="search">
            <SearchIcon />
            <input
              type="text"
              placeholder={selectedWard ? 'Search within this ward' : 'Hospital number or name'}
              value={query}
              onChange={(e) => setQuery(e.target.value)}
            />
          </form>
          <button type="button" className="btn-primary" onClick={handleSearch} disabled={searching}>
            {searching ? 'Searching…' : 'Search'}
          </button>
          <button
            type="button"
            className="btn-secondary btn-outline-bold"
            onClick={() => setFingerprintOpen((open) => !open)}
          >
            Search by fingerprint
          </button>
        </div>

        <FingerprintLookup
          open={fingerprintOpen}
          onView={openPatient}
          onClose={() => setFingerprintOpen(false)}
        />

        {wardCountsError && <p role="alert" className="dev-error">{wardCountsError}</p>}

        {showingWards ? (
          <>
            <div className="category-grid">
              {WARDS.map((w) => (
                <button
                  key={w.value}
                  type="button"
                  className="category-tile"
                  onClick={() => selectWardCategory(w.value)}
                >
                  <span className="category-tile-label">{w.label}</span>
                  <span className="category-tile-count">
                    {wardCounts ? wardCounts.by_ward[w.value] ?? 0 : '—'}
                  </span>
                </button>
              ))}
            </div>

            {assignedPatients.length > 0 && (
              <div className="assigned-to-you">
                <h3>Assigned to you</h3>
                {assignedPatients.map((p) => (
                  <div className="card-row" key={`${p.patient_id}-${p.role_in_assignment}`}>
                    <div className="card-row-main">
                      <div className="name-line">{p.full_name}</div>
                      <div className="meta-line">
                        {p.hospital_number} · {p.role_in_assignment}
                      </div>
                    </div>
                    <div className="card-row-actions">
                      <button
                        type="button"
                        className="btn-secondary"
                        onClick={() =>
                          openPatient({
                            id: p.patient_id,
                            hospital_number: p.hospital_number,
                            full_name: p.full_name,
                          })
                        }
                      >
                        View
                      </button>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </>
        ) : (
          results.map((p) => (
            <div className="card-row" key={p.id}>
              <div className="card-row-main">
                <div className="name-line">{p.full_name}</div>
                <div className="meta-line">
                  {p.hospital_number}
                  {p.ward ? ` · ${wardLabel(p.ward)}` : ' · Unassigned'}
                </div>
              </div>
              <div className="card-row-actions">
                <button type="button" className="btn-secondary" onClick={() => openPatient(p)}>
                  View
                </button>
              </div>
            </div>
          ))
        )}
      </section>

      {selectedPatient && (
        <section className="panel-card">
          <h2>
            {selectedPatient.full_name} ({selectedPatient.hospital_number})
          </h2>

          {viewLoading && <p>Checking access…</p>}

          {decision && decision.computed_offline && (
            <p className="meta-line">
              Computed offline from the last-synced cache — this access has been
              queued and will be permanently logged to the Security Ledger once
              reconnected.
            </p>
          )}

          {viewError && (
            <p role="alert" className="dev-error">
              {viewError.detail || 'Access could not be determined.'}
              {typeof viewError.score === 'number' && ` (score: ${viewError.score.toFixed(0)}%)`}
            </p>
          )}

          {decision && decision.decision_type === 'ACCESS_DENIED' && (
            <p role="alert" className="access-denied">
              Access denied. Score: {decision.score.toFixed(0)}%.
            </p>
          )}

          {decision && decision.decision_type === 'REDUCED_ACCESS' && (
            <p role="alert" className="access-reduced">
              Reduced access (score: {decision.score.toFixed(0)}%). Highly sensitive
              categories are hidden
              {decision.step_up_deferred_offline
                ? ', and step-up verification was deferred (unavailable offline) — flagged for review in the Security Ledger.'
                : ', and step-up verification is required before any records will open.'}
            </p>
          )}

          {/* Step-up challenge (added 2026-09-06, mechanism replaced the same
              day -- was a typed PIN, now device biometrics with a
              colleague-vouches fallback; see CLAUDE.md). The backend
              enforces this too (the records endpoint 403s until it's done),
              so this UI isn't the security boundary, just where the
              clinician satisfies it. */}
          {decision && decision.step_up_required && (
            <div className="step-up-control">
              {stepUpMode !== 'assist-waiting' ? (
                <>
                  <div className="button-row">
                    {session?.has_webauthn_credential && (
                      <button
                        type="button"
                        className="btn-primary"
                        disabled={stepUpSubmitting}
                        onClick={handleWebAuthnStepUp}
                      >
                        {stepUpSubmitting ? 'Waiting for your device…' : 'Verify with your device'}
                      </button>
                    )}
                    <button
                      type="button"
                      className="btn-secondary"
                      disabled={stepUpSubmitting}
                      onClick={handleRequestAssist}
                    >
                      Ask a colleague to verify
                    </button>
                  </div>
                  {!session?.has_webauthn_credential && (
                    <p className="meta-line">
                      This device has no biometric enrolled yet — set one up from your
                      Profile page, or ask a logged-in colleague to verify this session
                      for you now.
                    </p>
                  )}
                </>
              ) : (
                <p className="meta-line">
                  Waiting for a colleague to verify this session — this checks
                  automatically.{' '}
                  <button type="button" className="link-button" onClick={() => setStepUpMode(null)}>
                    Cancel and try something else
                  </button>
                </p>
              )}
              {stepUpError && (
                <p role="alert" className="dev-error">
                  {stepUpError.detail || 'Verification failed.'}
                  {typeof stepUpError.attempts_remaining === 'number' &&
                    ` ${stepUpError.attempts_remaining} attempt${stepUpError.attempts_remaining === 1 ? '' : 's'} remaining.`}
                </p>
              )}
            </div>
          )}

          {decision && decision.decision_type === 'AUDITED_DEVIATION' && (
            <p className="access-audited">
              Access granted, but this session has been flagged for audit (score:{' '}
              {decision.score.toFixed(0)}%).
            </p>
          )}

          {decision && decision.decision_type === 'EMERGENCY_OVERRIDE' && (
            <p className="access-override">
              Break the Glass: emergency access granted and permanently logged to the
              Security Ledger.
            </p>
          )}

          {!hideBreakGlass && (
            <div className="override-control">
              {!overrideOpen ? (
                <button type="button" className="override-button" onClick={() => setOverrideOpen(true)}>
                  Break the Glass (Emergency Override)
                </button>
              ) : (
                <form className="override-form" onSubmit={handleEmergencyOverride}>
                  <label className="form-label" htmlFor="override-category">
                    Reason category (required)
                    <select
                      id="override-category"
                      className="form-input"
                      value={overrideCategory}
                      onChange={(e) => setOverrideCategory(e.target.value)}
                      required
                    >
                      <option value="" disabled>
                        Select a reason category…
                      </option>
                      <option value="clinical_emergency">Clinical emergency / direct patient care</option>
                      <option value="cross_coverage">Cross-coverage (covering an unrostered shift)</option>
                      <option value="other">Other</option>
                    </select>
                  </label>
                  <label className="form-label" htmlFor="override-reason">
                    Reason detail (required, min 10 characters)
                    <textarea
                      id="override-reason"
                      className="form-input"
                      value={overrideReason}
                      onChange={(e) => setOverrideReason(e.target.value)}
                      rows={3}
                      required
                      minLength={10}
                    />
                  </label>
                  {overrideError && (
                    <p role="alert" className="dev-error">
                      {overrideError.detail || 'Could not grant emergency access.'}
                    </p>
                  )}
                  <div className="button-row">
                    <button
                      type="submit"
                      className="btn-primary"
                      disabled={overrideSubmitting || !overrideCategory || overrideReason.trim().length < 10}
                    >
                      {overrideSubmitting ? 'Granting…' : 'Confirm Break the Glass'}
                    </button>
                    <button
                      type="button"
                      className="btn-secondary"
                      onClick={() => {
                        setOverrideOpen(false);
                        setOverrideCategory('');
                        setOverrideReason('');
                        setOverrideError(null);
                      }}
                    >
                      Cancel
                    </button>
                  </div>
                </form>
              )}
            </div>
          )}

          {records && (
            <div className="category-list">
              {records.records.map((r) => {
                const filledFields = r.field_defs.filter((f) => r.content?.[f.name]);
                return (
                  <details key={r.category} className="detail-block" open>
                    <summary>{r.category_name}</summary>
                    {filledFields.length === 0 ? (
                      <p>(no information recorded)</p>
                    ) : (
                      filledFields.map((f) => (
                        <p key={f.name}>
                          <span className="detail-label">{f.label}:</span> {r.content[f.name]}
                        </p>
                      ))
                    )}
                  </details>
                );
              })}
            </div>
          )}
        </section>
      )}
    </DashboardShell>
  );
}

export default ClinicalDashboard;
