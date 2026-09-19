// Offline Mode (build step 6) -- the on-device store CLAUDE.md's Offline
// Mode section calls "encrypted browser storage" (this app is a browser SPA,
// so there's no separate local agent process to build -- see the approved
// plan's design decision #7). One IndexedDB database, four object stores:
//
// - `cache`   -- per-patient last-synced decision + records (encrypted, see
//                crypto.js), keyed by patient id.
// - `session` -- one row ('self') holding the caller's own staff/session
//                snapshot, behavioral baseline snapshot, assigned-patient
//                list, and disaster-mode flag (encrypted).
// - `queue`   -- pending locally-hash-chained ledger events, ordered by
//                client_seq, waiting to be signed and synced.
// - `keys`    -- the device's ECDSA signing key pair + AES encryption key,
//                stored as native non-extractable CryptoKey objects (never
//                exported as raw bytes except the *public* signing key,
//                which WebAuthn-style key pairs always allow exporting
//                regardless of the `extractable` flag).
// - `fingerprints` -- the whole enrolled-patient fingerprint roster
//                (template minutiae + emergency summary per patient),
//                encrypted, one row under a single key -- see
//                fingerprintCache.js. Unlike `cache`, this isn't built
//                organically per-patient-viewed: identification mode can't
//                know which patient it's looking for in advance, so the
//                whole roster is downloaded ahead of time instead.

import { openDB } from 'idb';

const DB_NAME = 'medguard-offline';
// Bumped 2026-09-17 (fingerprints store added) -- idb only runs upgrade()
// again on an existing device when this increases.
const DB_VERSION = 2;

let dbPromise = null;

function getDb() {
  if (!dbPromise) {
    dbPromise = openDB(DB_NAME, DB_VERSION, {
      upgrade(db) {
        if (!db.objectStoreNames.contains('cache')) db.createObjectStore('cache');
        if (!db.objectStoreNames.contains('session')) db.createObjectStore('session');
        if (!db.objectStoreNames.contains('queue')) db.createObjectStore('queue', { keyPath: 'client_seq' });
        if (!db.objectStoreNames.contains('keys')) db.createObjectStore('keys');
        if (!db.objectStoreNames.contains('fingerprints')) db.createObjectStore('fingerprints');
      },
    });
  }
  return dbPromise;
}

export { getDb };
