import { request } from './client';

/** GET /api/staff/?q=... — admin-only staff search by staff_id or full_name. */
function searchStaff(q) {
  const params = q ? `?q=${encodeURIComponent(q)}` : '';
  return request(`/staff/${params}`);
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

export { searchStaff, createStaff, updateStaffDuty, deactivateStaff, reactivateStaff };
