"""Wraps fingerprint_feature_extractor (real ridge-skeletonization +
crossing-number minutiae detection, verified by reading its source during
planning -- see the approved plan). The uploaded image is decoded entirely
in memory via OpenCV and never written to disk, not even a temp file, before
being discarded -- CLAUDE.md: "store encrypted templates... never raw
images."
"""

import math

import cv2
import numpy as np
from fingerprint_feature_extractor import extract_minutiae_features

# A real photographed fingerprint (not a clean scanner image) extracts far
# more minutiae than a "dozens per print" assumption expects -- live testing
# against a real enrolled print hit 188, most of it texture noise rather
# than real ridge features, and made matching.similarity_score() take 165
# SECONDS per comparison (confirmed by direct benchmark) before this cap and
# a matching-side spatial index (identity/matching.py) fixed it. Real AFIS
# systems don't match on every last detected point either -- a curated
# subset of strong, well-separated minutiae is standard practice, not a
# corner cut for this project specifically.
MAX_MINUTIAE = 70

# Two photos of the same finger, taken separately, are never at the same
# zoom/distance -- and matching.py only searches rotation+translation, not
# scale, so two genuinely-matching prints at different pixel scales would
# never align. Resizing every image to the same canonical size before
# extraction (added 2026-09-14, after live testing showed a real finger's
# SECOND photo scoring far lower than its first) removes that mismatch, as
# long as both photos frame the fingertip similarly (per the enrollment
# instructions this app already gives -- "fill the frame with just the
# fingertip"). Not a full fix for arbitrary scale/rotation/perspective --
# real AFIS hardware controls capture conditions far more tightly than a
# handheld photo ever will -- but it removes the single biggest avoidable
# source of mismatch between two independent photos.
CANONICAL_SIZE = 400


class UnreadableImage(Exception):
    pass


def _clean_angle(orientation):
    if not orientation:
        return 0.0
    value = orientation[0]
    return 0.0 if math.isnan(value) else float(value)


def _cap_to_strongest(minutiae, limit):
    """Keeps the `limit` most well-separated minutiae -- ranked by distance
    to their nearest same-type neighbor (an isolated point is a much more
    reliable, unambiguous match target than one crowded against noise)."""
    if len(minutiae) <= limit:
        return minutiae

    def nearest_neighbor_distance(m, others):
        best = math.inf
        for o in others:
            if o is m or o["type"] != m["type"]:
                continue
            d = math.hypot(m["x"] - o["x"], m["y"] - o["y"])
            if d < best:
                best = d
        return best

    scored = [(nearest_neighbor_distance(m, minutiae), m) for m in minutiae]
    scored.sort(key=lambda pair: pair[0], reverse=True)
    return [m for _, m in scored[:limit]]


def extract_minutiae(image_bytes):
    """Returns a list of {"x", "y", "angle", "type"} dicts -- real extracted
    minutiae, not a placeholder. Raises UnreadableImage for anything OpenCV
    can't decode as an image (bad upload, not a real error case worth a
    500)."""
    array = np.frombuffer(image_bytes, dtype=np.uint8)
    img = cv2.imdecode(array, cv2.IMREAD_GRAYSCALE)
    if img is None:
        raise UnreadableImage("Could not decode the uploaded file as an image.")

    # See CANONICAL_SIZE's comment -- removes scale mismatch between two
    # independently-taken photos before anything else runs.
    img = cv2.resize(img, (CANONICAL_SIZE, CANONICAL_SIZE), interpolation=cv2.INTER_AREA)

    # CLAHE (adaptive local contrast) before thresholding -- a real
    # handheld photo has uneven lighting across the frame in a way a
    # flatbed/optical scanner never does; a single global contrast
    # correction leaves dim corners under-thresholded. Standard real
    # preprocessing step for photographed (not scanner) fingerprint images.
    img = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8, 8)).apply(img)

    # The extractor's own skeletonization step is a flat `img > 128`
    # threshold -- Otsu binarization first makes that robust to real-world
    # lighting/contrast variation in an uploaded photo, rather than assuming
    # a pre-thresholded scanner image.
    _, binary = cv2.threshold(img, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)

    features_term, features_bif = extract_minutiae_features(
        binary, spuriousMinutiaeThresh=10, invertImage=False, showResult=False, saveResult=False
    )

    minutiae = []
    for f in features_term:
        minutiae.append(
            {"x": int(f.locX), "y": int(f.locY), "angle": _clean_angle(f.Orientation), "type": "termination"}
        )
    for f in features_bif:
        minutiae.append(
            {"x": int(f.locX), "y": int(f.locY), "angle": _clean_angle(f.Orientation), "type": "bifurcation"}
        )
    return _cap_to_strongest(minutiae, MAX_MINUTIAE)
