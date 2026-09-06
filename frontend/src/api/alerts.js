import { request } from './client';

/** GET /api/alerts/ — security-officer-only. `filters` may include
 * alert_type (ACCESS_DENIED | LOGIN_LOCKOUT | STEP_UP_FAILED) and
 * acknowledged ('true' | 'false'). Newest first. */
function getAlerts(filters = {}) {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(filters)) {
    if (value) params.set(key, value);
  }
  const qs = params.toString();
  return request(`/alerts/${qs ? `?${qs}` : ''}`);
}

/** GET /api/alerts/unacknowledged-count/ — security-officer-only. Cheap poll
 * target for the nav badge. Returns `{ count }`. */
function getUnacknowledgedAlertCount() {
  return request('/alerts/unacknowledged-count/');
}

/** POST /api/alerts/<id>/acknowledge/ — security-officer-only. Records that
 * this officer has reviewed the alert, with an optional note. */
function acknowledgeAlert(alertId, note = '') {
  return request(`/alerts/${alertId}/acknowledge/`, { method: 'POST', body: { note } });
}

export { getAlerts, getUnacknowledgedAlertCount, acknowledgeAlert };
