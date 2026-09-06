import { detectDeviceType, getOrCreateDeviceId } from '../capture/contextual/deviceInfo';
import { request, setToken } from './client';

/** POST /api/access/login/ — authenticates and, for the normal case, stores the
 * returned session token. Clinical-role accounts logging in from a device that
 * isn't their approved one instead get back `{status: 'pending_approval',
 * poll_token}` with no token — see pollDeviceRequest() below. Only the success
 * case stores a token; the caller (LoginPage) branches on `data.status`.
 * @param {object} [keystrokeFeatures] - derived, anonymized keystroke-dynamics
 *   features computed client-side from the login form (see keystrokeFeatures.js) —
 *   never raw key identity. */
async function login(username, password, keystrokeFeatures) {
  const deviceId = getOrCreateDeviceId();
  const deviceType = detectDeviceType();

  const data = await request('/access/login/', {
    method: 'POST',
    auth: false,
    body: {
      username,
      password,
      device_id: deviceId,
      device_type: deviceType,
      keystroke_features: keystrokeFeatures,
    },
  });

  if (data.token) {
    setToken(data.token);
  }
  return data;
}

/** GET /api/access/device-requests/<pollToken>/poll/ — unauthenticated; the device
 * waiting on approval has no token yet. Returns {status: 'pending'|'rejected'} or,
 * once approved, {status: 'approved', token, staff} exactly once. */
function pollDeviceRequest(pollToken) {
  return request(`/access/device-requests/${pollToken}/poll/`, { auth: false });
}

/** POST /api/access/logout/ — ends the current session, then clears the local token
 * regardless of whether the request succeeded (best-effort). */
async function logout() {
  try {
    await request('/access/logout/', { method: 'POST' });
  } finally {
    setToken(null);
  }
}

/** GET /api/access/session/current/ — debug view of the caller's own session. */
function getCurrentSession() {
  return request('/access/session/current/');
}

/** POST /api/access/change-password/ — the caller changes their own password.
 * No role restriction; any logged-in staff member can call this on themselves. */
function changePassword(currentPassword, newPassword) {
  return request('/access/change-password/', {
    method: 'POST',
    body: { current_password: currentPassword, new_password: newPassword },
  });
}

/** POST /api/access/webauthn/registration-options/ — self-service, first
 * step of enrolling THIS device's biometric (Face ID/fingerprint/Windows
 * Hello) as a step-up credential. Returns WebAuthn creation options for
 * @simplewebauthn/browser's startRegistration(). */
function getWebAuthnRegistrationOptions() {
  return request('/access/webauthn/registration-options/', { method: 'POST' });
}

/** POST /api/access/webauthn/register/ — second step: verifies
 * startRegistration()'s response and enrolls this device's credential. */
function registerWebAuthnCredential(credential) {
  return request('/access/webauthn/register/', { method: 'POST', body: { credential } });
}

/** POST /api/access/profile/photo/ (multipart) — uploads/replaces the caller's own
 * profile photo. Returns {photo_url}. */
function uploadProfilePhoto(file) {
  const formData = new FormData();
  formData.append('photo', file);
  return request('/access/profile/photo/', { method: 'POST', body: formData });
}

/** DELETE /api/access/profile/photo/ — removes the caller's own profile photo. */
function removeProfilePhoto() {
  return request('/access/profile/photo/', { method: 'DELETE' });
}

/** GET /api/access/devices/ — the caller's own approved devices + pending requests
 * (Profile > Devices panel). */
function listDevices() {
  return request('/access/devices/');
}

/** GET /api/access/devices/pending-count/ — cheap poll target for the header's
 * profile-icon badge. */
function getPendingDeviceCount() {
  return request('/access/devices/pending-count/');
}

/** POST /api/access/device-requests/<id>/approve/ */
function approveDevice(requestId) {
  return request(`/access/device-requests/${requestId}/approve/`, { method: 'POST' });
}

/** POST /api/access/device-requests/<id>/reject/ */
function rejectDevice(requestId) {
  return request(`/access/device-requests/${requestId}/reject/`, { method: 'POST' });
}

/** POST /api/access/devices/<id>/remove/ — 400s if the target is the primary
 * device (the backend enforces this; the UI just doesn't offer a Remove button
 * for it in the first place). */
function removeDevice(deviceId) {
  return request(`/access/devices/${deviceId}/remove/`, { method: 'POST' });
}

export {
  login,
  pollDeviceRequest,
  logout,
  getCurrentSession,
  changePassword,
  getWebAuthnRegistrationOptions,
  registerWebAuthnCredential,
  uploadProfilePhoto,
  removeProfilePhoto,
  listDevices,
  getPendingDeviceCount,
  approveDevice,
  rejectDevice,
  removeDevice,
};
