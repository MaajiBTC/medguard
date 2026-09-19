// Offline Mode's fingerprint gap (added 2026-09-17) -- a direct port of
// backend/identity/matching.py's similarity_score: spatial-grid-indexed
// rigid-alignment matching, the same real algorithm the server uses, not a
// simplified stand-in. See that file's own header comment for the full
// explanation of the technique and the 165s-per-comparison bug its spatial
// grid fixed.
//
// Tolerances are kept as separate named constants from the backend's
// (rather than importing/duplicating its exact values as one-time
// constants) because an offline probe is always matched against a
// template extracted by the *Python* pipeline (identity/extraction.py) --
// enrollment stays online-only, so there's no offline enrollment path to
// port. The two pipelines will not compute minutiae angle identically (the
// backend's angle comes from fingerprint_feature_extractor's own
// orientation estimation, not something a from-scratch client-side port
// can replicate exactly), so live testing may show these need loosening
// beyond the backend's own values -- that tuning, if needed, only touches
// this file.

const DISTANCE_TOLERANCE_PX = 20;
const ANGLE_TOLERANCE_DEG = 30;
const BUCKET_SIZE = DISTANCE_TOLERANCE_PX;

// Mirrors settings.FINGERPRINT_MATCH_THRESHOLD (backend/config/settings.py)
// -- not otherwise exposed to the frontend, so duplicated here the same way
// scoringEngine.js already duplicates other backend constants client-side.
const FINGERPRINT_MATCH_THRESHOLD = 40;

function angleDiff(a, b) {
  return Math.abs((((a - b + 180) % 360) + 360) % 360 - 180);
}

function rotateAbout(x, y, cx, cy, angleDeg) {
  const rad = (angleDeg * Math.PI) / 180;
  const dx = x - cx;
  const dy = y - cy;
  return [cx + dx * Math.cos(rad) - dy * Math.sin(rad), cy + dx * Math.sin(rad) + dy * Math.cos(rad)];
}

function bucketKey(type, x, y) {
  return `${type}|${Math.floor(x / BUCKET_SIZE)}|${Math.floor(y / BUCKET_SIZE)}`;
}

function buildGrid(template) {
  const grid = new Map();
  for (const t of template) {
    const key = bucketKey(t.type, t.x, t.y);
    if (!grid.has(key)) grid.set(key, []);
    grid.get(key).push(t);
  }
  return grid;
}

function* nearby(grid, type, x, y) {
  const bx = Math.floor(x / BUCKET_SIZE);
  const by = Math.floor(y / BUCKET_SIZE);
  for (let dx = -1; dx <= 1; dx += 1) {
    for (let dy = -1; dy <= 1; dy += 1) {
      const bucket = grid.get(`${type}|${bx + dx}|${by + dy}`);
      if (bucket) yield* bucket;
    }
  }
}

function countMatches(probe, grid, rotation, dx, dy, anchor) {
  let matched = 0;
  for (const p of probe) {
    let [rx, ry] = rotateAbout(p.x, p.y, anchor.x, anchor.y, rotation);
    rx += dx;
    ry += dy;
    const rotatedAngle = (((p.angle + rotation) % 360) + 360) % 360;
    for (const t of nearby(grid, p.type, rx, ry)) {
      if (Math.hypot(rx - t.x, ry - t.y) > DISTANCE_TOLERANCE_PX) continue;
      if (angleDiff(rotatedAngle, t.angle) > ANGLE_TOLERANCE_DEG) continue;
      matched += 1;
      break;
    }
  }
  return matched;
}

/** 0-100. Tries every same-type (probe minutia, template minutia) pair as a
 * candidate rigid-alignment anchor, scores each, keeps the best. */
function similarityScore(probe, template) {
  if (!probe.length || !template.length) return 0.0;

  const grid = buildGrid(template);
  const smallerSet = Math.min(probe.length, template.length);

  let bestMatched = 0;
  for (const p of probe) {
    for (const t of template) {
      if (p.type !== t.type) continue;
      const rotation = t.angle - p.angle;
      const dx = t.x - p.x;
      const dy = t.y - p.y;
      const matched = countMatches(probe, grid, rotation, dx, dy, p);
      if (matched > bestMatched) {
        bestMatched = matched;
        if (bestMatched >= smallerSet) return 100.0;
      }
    }
  }

  return smallerSet ? Math.round((100 * bestMatched) / smallerSet * 100) / 100 : 0.0;
}

export { DISTANCE_TOLERANCE_PX, ANGLE_TOLERANCE_DEG, FINGERPRINT_MATCH_THRESHOLD, similarityScore };
