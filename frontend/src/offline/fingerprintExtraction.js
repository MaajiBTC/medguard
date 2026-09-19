// Offline Mode's fingerprint gap (added 2026-09-17) -- a real, from-scratch
// port of what backend/identity/extraction.py does (resize -> CLAHE -> Otsu
// threshold -> skeletonize -> crossing-number minutiae detection), using
// only the Canvas 2D API. No client-side equivalent of
// fingerprint_feature_extractor/OpenCV/scikit-image exists, so each stage
// is hand-implemented here rather than simplified away -- see the approved
// plan's "Known risk" section for why cross-pipeline (JS probe vs
// Python-extracted template) matching is still expected to need a live
// tuning pass regardless.

// Matches extraction.py's CANONICAL_SIZE exactly -- this is what keeps
// probe/template coordinates comparable in fingerprintMatching.js.
const CANONICAL_SIZE = 400;
// Matches extraction.py's MAX_MINUTIAE.
const MAX_MINUTIAE = 70;
// CLAHE tile grid + clip limit, matching extraction.py's
// cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8, 8)).
const TILE_COUNT = 8;
const CLIP_LIMIT = 3.0;
// Minutiae within this many pixels of the canonical image's edge are
// dropped -- border/mask artifacts, not real ridge features. Real AFIS
// systems do the same (extraction.py's own comment notes
// fingerprint_feature_extractor does its own mask erosion for the same
// reason).
const BORDER_MARGIN = 15;

class UnreadableImage extends Error {}

const RING_OFFSETS = [
  [0, -1],
  [1, -1],
  [1, 0],
  [1, 1],
  [0, 1],
  [-1, 1],
  [-1, 0],
  [-1, -1],
];

/** Decodes the uploaded file, draws it into a CANONICAL_SIZE x CANONICAL_SIZE
 * canvas (removes scale mismatch between two independently-taken photos,
 * same reasoning as extraction.py's own resize step), and returns a flat
 * grayscale Float64Array (0-255) in row-major order. */
async function loadGrayscaleCanonical(file) {
  let bitmap;
  try {
    bitmap = await createImageBitmap(file);
  } catch {
    throw new UnreadableImage('Could not decode the uploaded file as an image.');
  }

  const canvas = document.createElement('canvas');
  canvas.width = CANONICAL_SIZE;
  canvas.height = CANONICAL_SIZE;
  const ctx = canvas.getContext('2d');
  ctx.imageSmoothingEnabled = true;
  ctx.imageSmoothingQuality = 'high';
  ctx.drawImage(bitmap, 0, 0, CANONICAL_SIZE, CANONICAL_SIZE);
  if (bitmap.close) bitmap.close();

  const { data } = ctx.getImageData(0, 0, CANONICAL_SIZE, CANONICAL_SIZE);
  const gray = new Float64Array(CANONICAL_SIZE * CANONICAL_SIZE);
  for (let i = 0; i < gray.length; i += 1) {
    const r = data[i * 4];
    const g = data[i * 4 + 1];
    const b = data[i * 4 + 2];
    gray[i] = 0.299 * r + 0.587 * g + 0.114 * b;
  }
  return gray;
}

/** Real tiled adaptive histogram equalization -- per-tile histogram, clip
 * at CLIP_LIMIT * (pixels-per-tile / 256), redistribute the clipped excess
 * uniformly, map via each tile's own CDF, then bilinearly blend between the
 * four nearest tile mappings per pixel. Kept in scope rather than
 * simplified to global equalization because CLAHE was the actual fix for a
 * real handheld-photo lighting bug on the backend already (see
 * extraction.py's own comment) -- skipping it here would likely
 * reintroduce that same failure mode. */
function clahe(gray, size) {
  const tileSize = size / TILE_COUNT;
  const tileLUTs = [];

  for (let ty = 0; ty < TILE_COUNT; ty += 1) {
    const row = [];
    for (let tx = 0; tx < TILE_COUNT; tx += 1) {
      const hist = new Float64Array(256);
      const x0 = tx * tileSize;
      const y0 = ty * tileSize;
      for (let y = y0; y < y0 + tileSize; y += 1) {
        for (let x = x0; x < x0 + tileSize; x += 1) {
          const v = Math.min(255, Math.max(0, Math.round(gray[y * size + x])));
          hist[v] += 1;
        }
      }

      const pixelCount = tileSize * tileSize;
      const clipThresh = Math.max(1, (CLIP_LIMIT * pixelCount) / 256);
      let excess = 0;
      for (let i = 0; i < 256; i += 1) {
        if (hist[i] > clipThresh) {
          excess += hist[i] - clipThresh;
          hist[i] = clipThresh;
        }
      }
      const redistribute = excess / 256;
      for (let i = 0; i < 256; i += 1) hist[i] += redistribute;

      const lut = new Float64Array(256);
      let cumulative = 0;
      const scale = 255 / (pixelCount || 1);
      for (let i = 0; i < 256; i += 1) {
        cumulative += hist[i];
        lut[i] = cumulative * scale;
      }
      row.push(lut);
    }
    tileLUTs.push(row);
  }

  const out = new Float64Array(size * size);
  for (let y = 0; y < size; y += 1) {
    for (let x = 0; x < size; x += 1) {
      const v = Math.min(255, Math.max(0, Math.round(gray[y * size + x])));

      const txf = x / tileSize - 0.5;
      const tyf = y / tileSize - 0.5;
      const tx0 = Math.min(Math.max(Math.floor(txf), 0), TILE_COUNT - 1);
      const ty0 = Math.min(Math.max(Math.floor(tyf), 0), TILE_COUNT - 1);
      const tx1 = Math.min(tx0 + 1, TILE_COUNT - 1);
      const ty1 = Math.min(ty0 + 1, TILE_COUNT - 1);
      const fx = Math.min(Math.max(txf - Math.floor(txf), 0), 1);
      const fy = Math.min(Math.max(tyf - Math.floor(tyf), 0), 1);

      const v00 = tileLUTs[ty0][tx0][v];
      const v01 = tileLUTs[ty0][tx1][v];
      const v10 = tileLUTs[ty1][tx0][v];
      const v11 = tileLUTs[ty1][tx1][v];
      const top = v00 * (1 - fx) + v01 * fx;
      const bottom = v10 * (1 - fx) + v11 * fx;
      out[y * size + x] = top * (1 - fy) + bottom * fy;
    }
  }
  return out;
}

/** Standard between-class-variance-maximizing Otsu threshold over a 256-bin
 * histogram -- matches extraction.py's cv2.threshold(..., THRESH_OTSU). */
function otsuThreshold(gray, size) {
  const hist = new Float64Array(256);
  const total = size * size;
  for (let i = 0; i < total; i += 1) {
    hist[Math.min(255, Math.max(0, Math.round(gray[i])))] += 1;
  }

  let sum = 0;
  for (let i = 0; i < 256; i += 1) sum += i * hist[i];

  let sumB = 0;
  let weightB = 0;
  let maxVariance = 0;
  let threshold = 0;
  for (let t = 0; t < 256; t += 1) {
    weightB += hist[t];
    if (weightB === 0) continue;
    const weightF = total - weightB;
    if (weightF === 0) break;
    sumB += t * hist[t];
    const meanB = sumB / weightB;
    const meanF = (sum - sumB) / weightF;
    const variance = weightB * weightF * (meanB - meanF) * (meanB - meanF);
    if (variance > maxVariance) {
      maxVariance = variance;
      threshold = t;
    }
  }
  return threshold;
}

/** Ridges render as the darker ink pattern in a handheld photo (against
 * lighter skin/background) -- foreground (1) is below the Otsu threshold. */
function binarize(gray, size, threshold) {
  const out = new Uint8Array(size * size);
  for (let i = 0; i < out.length; i += 1) out[i] = gray[i] < threshold ? 1 : 0;
  return out;
}

/** Classic two-subiteration Zhang-Suen thinning -- reduces the binary ridge
 * mask to a 1px-wide skeleton, same job extraction.py gets from
 * skimage-based skeletonize() inside fingerprint_feature_extractor. */
function zhangSuenThin(binary, size) {
  const img = Uint8Array.from(binary);
  const get = (x, y) => (x < 0 || y < 0 || x >= size || y >= size ? 0 : img[y * size + x]);

  const passOnce = (checkA, checkB) => {
    const toRemove = [];
    for (let y = 1; y < size - 1; y += 1) {
      for (let x = 1; x < size - 1; x += 1) {
        if (!get(x, y)) continue;
        const ring = RING_OFFSETS.map(([dx, dy]) => get(x + dx, y + dy));
        // Named per the standard Zhang-Suen p2..p9 numbering -- ring[0] is
        // p2 (the neighbor directly above), proceeding clockwise.
        const [p2, , p4, , p6, , p8] = ring;
        const blackNeighbors = ring.reduce((a, b) => a + b, 0);
        if (blackNeighbors < 2 || blackNeighbors > 6) continue;
        let transitions = 0;
        for (let i = 0; i < 8; i += 1) {
          if (ring[i] === 0 && ring[(i + 1) % 8] === 1) transitions += 1;
        }
        if (transitions !== 1) continue;
        if (checkA(p2, p4, p6, p8) !== 0) continue;
        if (checkB(p2, p4, p6, p8) !== 0) continue;
        toRemove.push(y * size + x);
      }
    }
    for (const idx of toRemove) img[idx] = 0;
    return toRemove.length > 0;
  };

  let changed = true;
  while (changed) {
    changed = false;
    if (passOnce((p2, p4, p6) => p2 * p4 * p6, (p2, p4, p6, p8) => p4 * p6 * p8)) changed = true;
    if (passOnce((p2, p4, p6, p8) => p2 * p4 * p8, (p2, p4, p6, p8) => p2 * p6 * p8)) changed = true;
  }
  return img;
}

function angleFromOffset(dx, dy) {
  const deg = (Math.atan2(dy, dx) * 180) / Math.PI;
  return deg < 0 ? deg + 360 : deg;
}

/** Crossing-number minutiae detection: for each foreground skeleton pixel,
 * walk its 8-neighborhood in ring order and count 0->1 transitions (CN).
 * CN==1 -> ridge ending, CN==3 -> bifurcation (2 is an ordinary ridge
 * point, not a minutia). Angle is the direction to the minutia's ridge
 * neighbor(s) -- termination: its one neighbor; bifurcation: the averaged
 * direction to its three. */
function extractMinutiaeFromSkeleton(skeleton, size, margin) {
  const get = (x, y) => (x < 0 || y < 0 || x >= size || y >= size ? 0 : skeleton[y * size + x]);
  const minutiae = [];

  for (let y = margin; y < size - margin; y += 1) {
    for (let x = margin; x < size - margin; x += 1) {
      if (!get(x, y)) continue;
      const ring = RING_OFFSETS.map(([dx, dy]) => get(x + dx, y + dy));
      let cn = 0;
      for (let i = 0; i < 8; i += 1) cn += Math.abs(ring[i] - ring[(i + 1) % 8]);
      cn /= 2;

      if (cn === 1) {
        const idx = ring.findIndex((v) => v === 1);
        const [dx, dy] = RING_OFFSETS[idx];
        minutiae.push({ x, y, angle: angleFromOffset(dx, dy), type: 'termination' });
      } else if (cn === 3) {
        let sumX = 0;
        let sumY = 0;
        for (let i = 0; i < 8; i += 1) {
          if (ring[i] === 1) {
            sumX += RING_OFFSETS[i][0];
            sumY += RING_OFFSETS[i][1];
          }
        }
        minutiae.push({ x, y, angle: angleFromOffset(sumX, sumY), type: 'bifurcation' });
      }
    }
  }
  return minutiae;
}

/** Direct port of extraction.py's _cap_to_strongest -- keeps the `limit`
 * most well-separated minutiae, ranked by distance to their nearest
 * same-type neighbor. */
function capToStrongest(minutiae, limit) {
  if (minutiae.length <= limit) return minutiae;

  function nearestNeighborDistance(m, others) {
    let best = Infinity;
    for (const o of others) {
      if (o === m || o.type !== m.type) continue;
      const d = Math.hypot(m.x - o.x, m.y - o.y);
      if (d < best) best = d;
    }
    return best;
  }

  return minutiae
    .map((m) => [nearestNeighborDistance(m, minutiae), m])
    .sort((a, b) => b[0] - a[0])
    .slice(0, limit)
    .map(([, m]) => m);
}

/** Returns a list of {x, y, angle, type} minutiae -- the same shape
 * extraction.py produces, so it plugs directly into fingerprintMatching.js
 * without an adapter. Throws UnreadableImage for anything the browser can't
 * decode as an image. */
async function extractMinutiae(file) {
  const gray = await loadGrayscaleCanonical(file);
  const enhanced = clahe(gray, CANONICAL_SIZE);
  const threshold = otsuThreshold(enhanced, CANONICAL_SIZE);
  const binary = binarize(enhanced, CANONICAL_SIZE, threshold);
  const skeleton = zhangSuenThin(binary, CANONICAL_SIZE);
  const raw = extractMinutiaeFromSkeleton(skeleton, CANONICAL_SIZE, BORDER_MARGIN);
  return capToStrongest(raw, MAX_MINUTIAE);
}

export { CANONICAL_SIZE, MAX_MINUTIAE, UnreadableImage, extractMinutiae };
