import { request } from './client';

/** GET /api/ledger/entries/ — security-officer-only. `filters` may include
 * event_type, staff_id, patient_hospital_number, since, until, before. */
function getLedgerEntries(filters = {}) {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(filters)) {
    if (value) params.set(key, value);
  }
  const qs = params.toString();
  return request(`/ledger/entries/${qs ? `?${qs}` : ''}`);
}

export { getLedgerEntries };
