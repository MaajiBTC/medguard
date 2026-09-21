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
// - `wardSummaries` -- the minimal emergency summary for every patient on
//                this clinician's own ward (plus anyone assigned to them),
//                encrypted, one row under a single key -- see
//                wardSummaryCache.js. Same "downloaded ahead of time"
//                reasoning as `fingerprints`, on a different axis: it's
//                what lets an offline clinician open a ward patient they
//                never viewed online and still see blood type/allergies.

import { openDB } from 'idb';

const DB_NAME = 'medguard-offline';
// Bumped 2026-09-17 (fingerprints store added), again 2026-09-21
// (wardSummaries store added) -- idb only runs upgrade() again on an
// existing device when this increases. The contains() guards below make
// the body idempotent, so a device on v1 or v2 both land correctly on v3.
const DB_VERSION = 3;

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
        if (!db.objectStoreNames.contains('wardSummaries')) db.createObjectStore('wardSummaries');
      },
    });
  }
  return dbPromise;
}

export { getDb };
