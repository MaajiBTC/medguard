import { detectDeviceType, getOrCreateDeviceId } from '../capture/contextual/deviceInfo';
import { request, setToken } from './client';

/** POST /api/access/login/ — authenticates and stores the returned session token. */
async function login(username, password) {
  const deviceId = getOrCreateDeviceId();
  const deviceType = detectDeviceType();

  const data = await request('/access/login/', {
    method: 'POST',
    auth: false,
    body: { username, password, device_id: deviceId, device_type: deviceType },
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

export { login, logout, getCurrentSession };
