import { request } from './client';

/** GET /api/staff/?q=...&role=... — admin-only staff search by staff_id or
 * full_name, optionally filtered to an exact role (Admin dashboard's role-category
 * drill-down). */
function searchStaff(q, role) {
  const params = new URLSearchParams();
  if (q) params.set('q', q);
  if (role) params.set('role', role);
  const qs = params.toString();
  return request(`/staff/${qs ? `?${qs}` : ''}`);
}

/** GET /api/staff/summary/ — admin-only real counts (total, on_duty, by_role) for
 * the Overview page and role-category tiles. */
function getStaffSummary() {
  return request('/staff/summary/');
}

/** POST /api/staff/create/ — admin-only. Creates the auth.User + Staff row together. */
function createStaff(data) {
  return request('/staff/create/', { method: 'POST', body: data });
}

/** PATCH /api/staff/<id>/duty/ — admin-only. {ward?, on_duty?, on_call?} */
function updateStaffDuty(staffId, data) {
  return request(`/staff/${staffId}/duty/`, { method: 'PATCH', body: data });
}

/** POST /api/staff/<id>/deactivate/ — admin-only. Blocks login without deleting the row. */
function deactivateStaff(staffId) {
  return request(`/staff/${staffId}/deactivate/`, { method: 'POST' });
}

/** POST /api/staff/<id>/reactivate/ — admin-only. */
function reactivateStaff(staffId) {
  return request(`/staff/${staffId}/reactivate/`, { method: 'POST' });
}

export { searchStaff, getStaffSummary, createStaff, updateStaffDuty, deactivateStaff, reactivateStaff };
