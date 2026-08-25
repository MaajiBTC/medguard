// Generates/persists a device_id in localStorage (deliberately localStorage, not
// sessionStorage: a device's identity should survive across sessions/tabs, unlike
// the per-login auth token) and heuristically detects device_type for the
// Contextual capture module's login-time snapshot.

const DEVICE_ID_STORAGE_KEY = 'medguard_device_id';

function createDeviceId() {
  if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
    return crypto.randomUUID();
  }
  // Fallback for environments without crypto.randomUUID (older browsers).
  return `dev-${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

function getOrCreateDeviceId() {
  let deviceId = localStorage.getItem(DEVICE_ID_STORAGE_KEY);
  if (!deviceId) {
    deviceId = createDeviceId();
    localStorage.setItem(DEVICE_ID_STORAGE_KEY, deviceId);
  }
  return deviceId;
}

/** Heuristic only — good enough for the Contextual capture snapshot, not a
 * security boundary. Returns "mobile" | "tablet" | "desktop". */
function detectDeviceType() {
  const ua = (navigator.userAgent || '').toLowerCase();
  const hasCoarsePointer =
    typeof window.matchMedia === 'function' && window.matchMedia('(pointer: coarse)').matches;
  const hasTouch = 'ontouchstart' in window || (navigator.maxTouchPoints || 0) > 0;

  if (/ipad|tablet/.test(ua) || (hasTouch && /android/.test(ua) && !/mobile/.test(ua))) {
    return 'tablet';
  }
  if (/iphone|ipod|android|mobi/.test(ua) || (hasTouch && hasCoarsePointer)) {
    return 'mobile';
  }
  return 'desktop';
}

export { getOrCreateDeviceId, detectDeviceType };
