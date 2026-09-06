import { request } from './client';

/** GET /api/ledger/entries/ — security-officer-only. `filters` may include
 * event_type, staff_id, staff_role, patient_hospital_number, since, until,
 * before. */
function getLedgerEntries(filters = {}) {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(filters)) {
    if (value) params.set(key, value);
  }
  const qs = params.toString();
  return request(`/ledger/entries/${qs ? `?${qs}` : ''}`);
}

/** POST /api/ledger/entries/<sequence>/explain/ — security-officer-only.
 * Translates that entry's raw factor breakdown into a plain-English
 * explanation via Gemini (see backend ledger/gemini.py). Returns
 * `{ explanation }`. */
function explainLedgerEntry(sequence) {
  return request(`/ledger/entries/${sequence}/explain/`, { method: 'POST' });
}

/** GET /api/ledger/verify/ — security-officer-only. Re-walks the whole
 * hash chain and reports whether it's intact. Returns
 * `{ valid, bad_sequence, entries_checked, verified_at }` — `bad_sequence`
 * is null when valid, otherwise the first entry that failed. */
function verifyLedgerChain() {
  return request('/ledger/verify/');
}

export { getLedgerEntries, explainLedgerEntry, verifyLedgerChain };
