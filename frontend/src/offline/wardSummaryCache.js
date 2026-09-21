/** Offline Mode's ward roster (added 2026-09-21, per the user).
 *
 * syncManager.js's refreshOfflineCache() caches a patient's FULL record, but
 * only once that clinician has actually opened them online -- so offline, a
 * patient they simply hadn't got to yet was a dead end. This roster fills
 * that gap: the minimal emergency summary (blood type, allergies, current
 * medication, current diagnoses, next of kin) for every patient on the
 * clinician's own ward, plus anyone assigned to them, downloaded ahead of
 * time and re-encrypted at rest here on receipt.
 *
 * Same shape and same whole-blob storage as fingerprintCache.js -- matching
 * always scans the whole roster anyway, so there's nothing to gain from a
 * row per patient. The backend derives the ward from the caller's own
 * session (patients.views.WardEmergencySummaryView), so there's no ward
 * argument to pass and nothing here can widen the scope.
 */

import { getWardEmergencySummaries } from '../api/patients';
import { decryptJSON, encryptJSON, getOrCreateEncryptionKey } from './crypto';
import { getDb } from './db';

const ROSTER_KEY = 'roster';

async function cacheWardSummaries(patients) {
  const db = await getDb();
  const key = await getOrCreateEncryptionKey();
  await db.put('wardSummaries', await encryptJSON(key, patients), ROSTER_KEY);
}

async function getCachedWardSummaries() {
  const db = await getDb();
  const blob = await db.get('wardSummaries', ROSTER_KEY);
  if (!blob) return null;
  const key = await getOrCreateEncryptionKey();
  return decryptJSON(key, blob);
}

/** The cached entry for one patient id, or null. Callers get null both when
 * no roster has ever been downloaded and when this patient isn't on it --
 * the same dead end either way, so they don't need to tell the two apart. */
async function getCachedWardSummaryFor(patientId) {
  const roster = await getCachedWardSummaries();
  if (!roster || !roster.length) return null;
  return roster.find((row) => row.patient && row.patient.id === patientId) || null;
}

/** Best-effort refresh, called on mount/reconnect from ClinicalDashboard's
 * online/offline effect -- same silent-failure posture as
 * refreshFingerprintBundle() and ensureSigningKeyRegistered(). A device
 * whose clinician isn't a doctor or nurse gets a 403 here, which is a
 * normal outcome, not an error worth surfacing: they simply hold no roster. */
async function refreshWardSummaries() {
  const { patients } = await getWardEmergencySummaries();
  await cacheWardSummaries(patients);
}

export {
  cacheWardSummaries,
  getCachedWardSummaries,
  getCachedWardSummaryFor,
  refreshWardSummaries,
};
