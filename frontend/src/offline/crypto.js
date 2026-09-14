// Offline Mode (build step 6) -- device signing key (proves a synced batch
// really came from a registered device) and the AES key that keeps
// everything cached in IndexedDB encrypted at rest (CLAUDE.md: "All locally
// cached data... encrypted at rest"). Both keys are generated once per
// device and stored as native, non-extractable CryptoKey objects (see
// db.js) -- raw key material never touches application code, let alone the
// network. The one exception is the *public* half of the signing key pair,
// which Web Crypto always allows exporting regardless of `extractable`
// (public keys aren't sensitive) -- that's what gets registered server-side
// via api/offline.js's registerSigningKey().

import { getDb } from './db';

function arrayBufferToBase64(buf) {
  let binary = '';
  const bytes = new Uint8Array(buf);
  for (let i = 0; i < bytes.length; i += 1) binary += String.fromCharCode(bytes[i]);
  return btoa(binary);
}

function base64ToArrayBuffer(b64) {
  const binary = atob(b64);
  const bytes = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i += 1) bytes[i] = binary.charCodeAt(i);
  return bytes.buffer;
}

async function getOrCreateSigningKeyPair() {
  const db = await getDb();
  const existing = await db.get('keys', 'signing');
  if (existing) return existing;

  const keyPair = await crypto.subtle.generateKey({ name: 'ECDSA', namedCurve: 'P-256' }, false, [
    'sign',
    'verify',
  ]);
  await db.put('keys', keyPair, 'signing');
  return keyPair;
}

async function getOrCreateEncryptionKey() {
  const db = await getDb();
  const existing = await db.get('keys', 'encryption');
  if (existing) return existing;

  const key = await crypto.subtle.generateKey({ name: 'AES-GCM', length: 256 }, false, [
    'encrypt',
    'decrypt',
  ]);
  await db.put('keys', key, 'encryption');
  return key;
}

async function exportPublicKeySPKI(publicKey) {
  const raw = await crypto.subtle.exportKey('spki', publicKey);
  return arrayBufferToBase64(raw);
}

/** AES-GCM with a random 12-byte IV per call -- IV travels alongside the
 * ciphertext (it isn't secret, just must never repeat under the same key). */
async function encryptJSON(key, value) {
  const iv = crypto.getRandomValues(new Uint8Array(12));
  const data = new TextEncoder().encode(JSON.stringify(value));
  const ciphertext = await crypto.subtle.encrypt({ name: 'AES-GCM', iv }, key, data);
  return { iv: arrayBufferToBase64(iv.buffer), ciphertext: arrayBufferToBase64(ciphertext) };
}

async function decryptJSON(key, blob) {
  const iv = new Uint8Array(base64ToArrayBuffer(blob.iv));
  const ciphertext = base64ToArrayBuffer(blob.ciphertext);
  const plaintext = await crypto.subtle.decrypt({ name: 'AES-GCM', iv }, key, ciphertext);
  return JSON.parse(new TextDecoder().decode(plaintext));
}

/** ECDSA/SHA-256 over raw bytes -- Web Crypto produces the IEEE P1363 (raw
 * r||s) signature format, which offline_sync.verification.verify_batch_signature
 * on the backend expects and converts to DER for the `cryptography` package. */
async function signBytes(privateKey, bytes) {
  const signature = await crypto.subtle.sign({ name: 'ECDSA', hash: 'SHA-256' }, privateKey, bytes);
  return arrayBufferToBase64(signature);
}

export {
  getOrCreateSigningKeyPair,
  getOrCreateEncryptionKey,
  exportPublicKeySPKI,
  encryptJSON,
  decryptJSON,
  signBytes,
};
