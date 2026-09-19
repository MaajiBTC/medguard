// Offline Mode's fingerprint gap (added 2026-09-17) -- caches the whole
// enrolled-patient fingerprint roster on-device, encrypted at rest via the
// same AES-GCM key crypto.js already uses for every other cached store.
// Stored as one blob under a single key ('bundle'), not one row per
// patient -- identify-mode matching always scans the whole roster anyway
// (mirrors identity.views.IdentifyFingerprintView's own
// `for template in FingerprintTemplate.objects...` loop), so there's no
// per-patient lookup this would need to support.

import { getOfflineFingerprintBundle } from '../api/identity';
import { getDb } from './db';
import { decryptJSON, encryptJSON, getOrCreateEncryptionKey } from './crypto';

const BUNDLE_KEY = 'bundle';

async function cacheFingerprintBundle(templates) {
  const db = await getDb();
  const key = await getOrCreateEncryptionKey();
  await db.put('fingerprints', await encryptJSON(key, templates), BUNDLE_KEY);
}

async function getCachedFingerprintBundle() {
  const db = await getDb();
  const blob = await db.get('fingerprints', BUNDLE_KEY);
  if (!blob) return null;
  const key = await getOrCreateEncryptionKey();
  return decryptJSON(key, blob);
}

/** Best-effort refresh, called on mount/reconnect (see ClinicalDashboard.jsx's
 * existing online/offline effect) -- same silent-failure posture as
 * ensureSigningKeyRegistered() in App.jsx. A later reconnect just tries
 * again; a device that's never been online yet simply has no bundle, which
 * getCachedFingerprintBundle()'s null return already handles. */
async function refreshFingerprintBundle() {
  const { templates } = await getOfflineFingerprintBundle();
  await cacheFingerprintBundle(templates);
}

export { cacheFingerprintBundle, getCachedFingerprintBundle, refreshFingerprintBundle };
