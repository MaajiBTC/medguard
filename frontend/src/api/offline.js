import { request } from './client';

/** POST /api/access/devices/register-signing-key/ — {device_id, public_key}.
 * Registers this device's ECDSA P-256 public key (base64 SPKI) so a later
 * offline sync batch signed by its matching private key can be trusted (see
 * offline_sync.OfflineSyncView). The private key never leaves the device —
 * see frontend/src/offline/crypto.js. */
function registerSigningKey(deviceId, publicKeyB64) {
  return request('/access/devices/register-signing-key/', {
    method: 'POST',
    body: { device_id: deviceId, public_key: publicKeyB64 },
  });
}

/** POST /api/offline/sync/ — {device_id, batch_id, signature, entries}.
 * Merges a signed batch of locally-queued offline events into the real
 * Security Ledger. See frontend/src/offline/syncManager.js. */
function syncOfflineBatch(payload) {
  return request('/offline/sync/', { method: 'POST', body: payload });
}

export { registerSigningKey, syncOfflineBatch };
