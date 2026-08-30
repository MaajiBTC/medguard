import { detectDeviceType, getOrCreateDeviceId } from '../capture/contextual/deviceInfo';
import { request, setToken } from './client';

/** POST /api/access/login/ — authenticates and stores the returned session token.
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

  setToken(data.token);
  return data;
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

export { login, logout, getCurrentSession, changePassword };
