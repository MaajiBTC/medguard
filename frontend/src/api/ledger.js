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

/** GET /api/ledger/my-activity/?year=&month= — the caller's OWN per-day
 * record-access counts, for the Clinical dashboard's calendar card. Returns
 * `{ year, month, days: { 'YYYY-MM-DD': { count, flagged } } }`; `flagged`
 * means at least one event that day was something other than a clean
 * STANDARD_ACCESS. Never includes patient identities or other staff. */
function getMyActivityCalendar(year, month) {
  return request(`/ledger/my-activity/?year=${year}&month=${month}`);
}

export { getLedgerEntries, explainLedgerEntry, verifyLedgerChain, getMyActivityCalendar };
