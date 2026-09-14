// Offline Mode (build step 6) -- ties together the cache, the local hash
// chain, and the signed sync call. This is the module ClinicalDashboard.jsx
// actually talks to; it doesn't touch IndexedDB/crypto directly itself.

import { registerSigningKey, syncOfflineBatch } from '../api/offline';
import { getOrCreateDeviceId } from '../capture/contextual/deviceInfo';
import { getDb } from './db';
import {
  decryptJSON,
  encryptJSON,
  exportPublicKeySPKI,
  getOrCreateEncryptionKey,
  getOrCreateSigningKeyPair,
  signBytes,
} from './crypto';
import { LOCAL_GENESIS_HASH, canonicalJSON, computeLocalEntryHash } from './localLedger';

const SESSION_KEY = 'self';

/** Best-effort reachability check -- navigator.onLine only reflects
 * link-layer state (e.g. still true on a wifi network with no real
 * internet), so callers that are about to try a real request don't need
 * this; it's for the passive header badge / periodic sync trigger. */
function isOnline() {
  return navigator.onLine;
}

async function cachePatient(patientId, value) {
  const db = await getDb();
  const key = await getOrCreateEncryptionKey();
  await db.put('cache', await encryptJSON(key, value), patientId);
}

async function getCachedPatient(patientId) {
  const db = await getDb();
  const blob = await db.get('cache', patientId);
  if (!blob) return null;
  const key = await getOrCreateEncryptionKey();
  return decryptJSON(key, blob);
}

async function cacheSession(value) {
  const db = await getDb();
  const key = await getOrCreateEncryptionKey();
  await db.put('session', await encryptJSON(key, value), SESSION_KEY);
}

async function getCachedSession() {
  const db = await getDb();
  const blob = await db.get('session', SESSION_KEY);
  if (!blob) return null;
  const key = await getOrCreateEncryptionKey();
  return decryptJSON(key, blob);
}

/** Caches the caller's own staff/session/baseline/assignment info,
 * independent of any specific patient -- called on login/mount (while
 * online) so a device that's disconnected before ever viewing a patient
 * still has *something* cached, and again after every successful decide()
 * (see refreshOfflineCache below) to keep it current. Does not touch
 * `sessionFactors` -- that only ever comes from a real decide() response. */
async function cacheOwnProfile({ staff, session, assignedPatientIds, disasterModeActive, baseline }) {
  const cachedSession = (await getCachedSession()) || {};
  await cacheSession({
    ...cachedSession,
    staff,
    session,
    assignedPatientIds: [...assignedPatientIds],
    disasterModeActive,
    baseline,
    updatedAt: new Date().toISOString(),
  });
}

/** Called after every successful ONLINE decide()+records fetch -- this is
 * how "last synced cache" builds up from normal use (CLAUDE.md), no
 * separate "download for offline" step. `sessionFactors` is the
 * session-level factor cache scoringEngine.js's simplification relies on
 * (see its own top comment) -- refreshed on every successful decide() with
 * gate_passed !== false, independent of which patient it was for.
 * `disasterModeActive` is optional -- omit it to carry forward whatever
 * cacheOwnProfile last stored, so a caller on the hot online path doesn't
 * need its own extra IndexedDB round trip just to preserve that one flag. */
async function refreshOfflineCache({ patient, decision, records, staff, session, assignedPatientIds, disasterModeActive }) {
  await cachePatient(patient.id, { patient, decision, records, cachedAt: new Date().toISOString() });

  if (decision.gate_passed !== false) {
    const cachedSession = (await getCachedSession()) || {};
    await cacheSession({
      ...cachedSession,
      staff,
      session,
      assignedPatientIds: [...assignedPatientIds],
      disasterModeActive: disasterModeActive !== undefined ? disasterModeActive : cachedSession.disasterModeActive,
      sessionFactors: { gate_passed: decision.gate_passed, factor_breakdown: decision.factor_breakdown },
      updatedAt: new Date().toISOString(),
    });
  }
}

async function queueLength() {
  const db = await getDb();
  return db.count('queue');
}

/** Appends one event to the local hash chain, keyed by client_seq (the
 * queue's own position, distinct from the real Ledger's sequence -- see the
 * approved plan's design decision #2). */
async function queueOfflineEvent({ eventType, patientHospitalNumber, details }) {
  const db = await getDb();
  const existing = await db.getAll('queue');
  const prevLocalHash = existing.length > 0 ? existing[existing.length - 1].entry_local_hash : LOCAL_GENESIS_HASH;
  const clientSeq = existing.length > 0 ? existing[existing.length - 1].client_seq + 1 : 1;
  const occurredAt = new Date().toISOString();

  const entryLocalHash = await computeLocalEntryHash({
    prevLocalHash,
    clientSeq,
    occurredAt,
    eventType,
    patientHospitalNumber,
    details,
  });

  const entry = {
    client_seq: clientSeq,
    occurred_at: occurredAt,
    event_type: eventType,
    patient_hospital_number: patientHospitalNumber,
    details,
    prev_local_hash: prevLocalHash,
    entry_local_hash: entryLocalHash,
  };
  await db.put('queue', entry);
  return entry;
}

/** Posts the whole queue as one signed batch. Clears the queue only once
 * the server has confirmed the merge -- a failed sync (still offline, or a
 * transient error) leaves everything queued for the next attempt. */
async function trySync() {
  const pending = await queueLength();
  if (pending === 0) return { merged: 0 };

  const db = await getDb();
  const entries = await db.getAll('queue');
  const batchId = crypto.randomUUID();
  const { privateKey } = await getOrCreateSigningKeyPair();
  const signature = await signBytes(privateKey, new TextEncoder().encode(canonicalJSON({ batch_id: batchId, entries })));

  const deviceId = getOrCreateDeviceId();
  const result = await syncOfflineBatch({ device_id: deviceId, batch_id: batchId, signature, entries });

  const tx = db.transaction('queue', 'readwrite');
  await Promise.all(entries.map((e) => tx.store.delete(e.client_seq)));
  await tx.done;

  return result;
}

/** Registers this device's signing public key with the backend, once --
 * called right after login (see App.jsx). Safe to call repeatedly: the
 * backend just overwrites the same value, and a device already registered
 * simply re-registers the same key pair (getOrCreateSigningKeyPair returns
 * the existing one from IndexedDB rather than generating a new one). */
async function ensureSigningKeyRegistered() {
  const { publicKey } = await getOrCreateSigningKeyPair();
  const publicKeyB64 = await exportPublicKeySPKI(publicKey);
  await registerSigningKey(getOrCreateDeviceId(), publicKeyB64);
}

export {
  isOnline,
  cacheOwnProfile,
  refreshOfflineCache,
  getCachedPatient,
  getCachedSession,
  queueOfflineEvent,
  queueLength,
  trySync,
  ensureSigningKeyRegistered,
};
