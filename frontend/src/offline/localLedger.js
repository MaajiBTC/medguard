// Offline Mode (build step 6) -- the device-local hash chain queued events
// build while offline. This is a SEPARATE, simpler scheme from the real
// Ledger's own hash chain (ledger.services._compute_entry_hash) -- see the
// approved plan's design decision #2. Its only job is proving this device's
// queue wasn't tampered with before it reaches the server; the real,
// canonical chain is still built exactly as always, server-side, by
// replaying verified entries through ledger.services.record_event().
//
// canonicalJSON() below must byte-for-byte match Python's
// json.dumps(payload, sort_keys=True, default=str) -- offline_sync.
// verification.recompute_local_hash() recomputes this same hash in Python
// from the raw field values it receives, and compares it against what this
// file computed. That means matching Python's default json.dumps
// formatting exactly (", " / ": " separators, non-ASCII escaped as \uXXXX
// under ensure_ascii=True), not JSON.stringify's minified, non-ASCII-safe
// output.

const LOCAL_GENESIS_HASH = '0'.repeat(64);

function pyJsonString(value) {
  let out = '"';
  for (const ch of value) {
    const code = ch.codePointAt(0);
    if (ch === '"') out += '\\"';
    else if (ch === '\\') out += '\\\\';
    else if (ch === '\n') out += '\\n';
    else if (ch === '\r') out += '\\r';
    else if (ch === '\t') out += '\\t';
    else if (code < 0x20) out += `\\u${code.toString(16).padStart(4, '0')}`;
    else if (code > 0x7e) {
      if (code > 0xffff) {
        const c = code - 0x10000;
        const hi = 0xd800 + (c >> 10);
        const lo = 0xdc00 + (c & 0x3ff);
        out += `\\u${hi.toString(16).padStart(4, '0')}\\u${lo.toString(16).padStart(4, '0')}`;
      } else {
        out += `\\u${code.toString(16).padStart(4, '0')}`;
      }
    } else {
      out += ch;
    }
  }
  return `${out}"`;
}

function pyJsonValue(value) {
  if (value === null || value === undefined) return 'null';
  if (typeof value === 'boolean') return value ? 'true' : 'false';
  if (typeof value === 'number') return String(value);
  if (typeof value === 'string') return pyJsonString(value);
  if (Array.isArray(value)) return `[${value.map(pyJsonValue).join(', ')}]`;
  if (typeof value === 'object') {
    const keys = Object.keys(value).sort();
    return `{${keys.map((k) => `${pyJsonString(k)}: ${pyJsonValue(value[k])}`).join(', ')}}`;
  }
  return 'null';
}

function canonicalJSON(payload) {
  return pyJsonValue(payload);
}

async function sha256Hex(text) {
  const bytes = new TextEncoder().encode(text);
  const digest = await crypto.subtle.digest('SHA-256', bytes);
  return Array.from(new Uint8Array(digest))
    .map((b) => b.toString(16).padStart(2, '0'))
    .join('');
}

/** Mirrors offline_sync.verification.recompute_local_hash() field-for-field. */
async function computeLocalEntryHash({ prevLocalHash, clientSeq, occurredAt, eventType, patientHospitalNumber, details }) {
  const payload = {
    prev_local_hash: prevLocalHash,
    client_seq: clientSeq,
    occurred_at: occurredAt,
    event_type: eventType,
    patient_hospital_number: patientHospitalNumber,
    details,
  };
  return sha256Hex(canonicalJSON(payload));
}

export { LOCAL_GENESIS_HASH, canonicalJSON, computeLocalEntryHash };
