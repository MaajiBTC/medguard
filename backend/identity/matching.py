"""Minutiae matching -- SourceAFIS itself has no Python port (confirmed
during planning; see the approved plan), so this hand-writes the standard
simplified minutiae-pair alignment technique instead: real fingerprint
matching math, deliberately simpler than SourceAFIS's own approach, in the
same spirit CLAUDE.md already uses for the Scoring Engine's own behavioral
matching ("deliberately simple, explainable statistics... appropriate for a
hackathon demo").

Two independent scans of the same finger are never pixel-aligned -- the
probe and an enrolled template can be rotated and shifted relative to each
other. For every same-type (probe minutia, template minutia) pair, this
computes the rigid rotation+translation that would map one onto the other,
applies that candidate transform to every probe minutia, and counts how many
land within tolerance of some template minutia. The best-scoring candidate
transform wins.

**Spatial-grid indexed (added 2026-09-14, real bug fix):** a naive
implementation scores each candidate transform by scanning every probe point
against every template point -- O(n*m) per candidate, O(n*m) candidates, so
O((n*m)^2) overall. That's fine at the "dozens of minutiae" scale this was
first benchmarked against, but a real photographed fingerprint (not a clean
scanner image) extracts far more spurious minutiae than expected -- live
testing against a real enrolled print hit 188 minutiae, and the naive
version took 165 SECONDS for one comparison (confirmed by direct
benchmark), which is exactly what "stuck on Identifying..." in the UI was.
Fixed by bucketing the (static) template into a spatial grid once per
similarity_score() call, so each candidate's scan only has to check the
handful of nearby buckets instead of every template point -- turns the
per-candidate cost from O(m) into O(1)-ish, dropping overall complexity to
roughly O(n^2 * m) with a small constant. Confirmed via the same benchmark:
165s -> well under a second at the same 188-vs-188 minutiae count that
exposed the original bug.
"""

import math

# Coordinates are in extraction.py's fixed CANONICAL_SIZE (400x400) space,
# so these are meaningful relative to that, not raw photo pixels.
#
# History: 12px/20deg originally; loosened to 20px/30deg on 2026-09-14 on
# the reasoning that two handheld photos won't align as tightly as two
# scans off one purpose-built scanner. Put BACK to 12px on 2026-09-20 after
# measuring against two real enrolled prints: at 20px, two different
# fingers still scored 53% even with the one-to-one fix below (12px drops
# that to 36%, under the 40% threshold). 20px was simply too generous for a
# 400x400 frame in which the extractor packs ~70 mostly-noise minutiae into
# roughly a 200x170 region -- at that density almost any point lands within
# 20px of some template point, so the tolerance was matching texture rather
# than ridge features.
#
# ANGLE_TOLERANCE_DEG does much less work than it appears to: the
# extractor's angles come from atan2 over a 3x3 pixel neighbourhood, so a
# whole print only ever yields about 10 distinct angle values (measured).
# Removing the angle check entirely only moves a false match from 71% to
# 90%, i.e. it was rejecting very little. Left in place -- it costs nothing
# and does help -- but the distance tolerance and the one-to-one constraint
# are what actually separate two fingers here.
DISTANCE_TOLERANCE_PX = 12
ANGLE_TOLERANCE_DEG = 30
# Bucket size matches the distance tolerance -- a point can only ever match
# something in its own bucket or an immediately adjacent one, so checking
# the 3x3 neighborhood around a query point's bucket is always sufficient.
BUCKET_SIZE = DISTANCE_TOLERANCE_PX


def _angle_diff(a, b):
    return abs((a - b + 180) % 360 - 180)


def _rotate_about(x, y, cx, cy, angle_deg):
    rad = math.radians(angle_deg)
    dx, dy = x - cx, y - cy
    return (
        cx + dx * math.cos(rad) - dy * math.sin(rad),
        cy + dx * math.sin(rad) + dy * math.cos(rad),
    )


def _bucket_key(type_, x, y):
    return (type_, int(x // BUCKET_SIZE), int(y // BUCKET_SIZE))


def _build_grid(template):
    grid = {}
    for t in template:
        grid.setdefault(_bucket_key(t["type"], t["x"], t["y"]), []).append(t)
    return grid


def _nearby(grid, type_, x, y):
    bx, by = int(x // BUCKET_SIZE), int(y // BUCKET_SIZE)
    for dx in (-1, 0, 1):
        for dy in (-1, 0, 1):
            for t in grid.get((type_, bx + dx, by + dy), ()):
                yield t


def _count_matches(probe, grid, rotation, dx, dy, anchor):
    """How many probe minutiae land on a template minutia under this
    transform -- counting each template minutia AT MOST ONCE.

    That one-to-one constraint is the whole point (fixed 2026-09-20, real
    bug found against two real enrolled prints). The original took the
    first template point within tolerance and moved on, with no record of
    what had already been used -- so a dense cluster of probe minutiae
    could all claim the SAME template point and each be counted as a
    separate match. On real photographed prints, where the extractor
    returns mostly closely-packed noise rather than clean well-separated
    ridge features, that inflated two genuinely DIFFERENT fingers from 53%
    to 71% -- comfortably past the 40% match threshold, meaning the system
    would confidently return the wrong patient. A minutia pairing is by
    definition one-to-one: two ridge endings cannot both be the same ridge
    ending.

    Each probe point takes its NEAREST unclaimed candidate rather than the
    first one the grid happens to yield, so the pairing doesn't depend on
    bucket iteration order.
    """
    claimed = set()
    matched = 0
    for p in probe:
        rx, ry = _rotate_about(p["x"], p["y"], anchor["x"], anchor["y"], rotation)
        rx, ry = rx + dx, ry + dy
        rotated_angle = (p["angle"] + rotation) % 360

        nearest = None
        nearest_distance = None
        for t in _nearby(grid, p["type"], rx, ry):
            if id(t) in claimed:
                continue
            distance = math.hypot(rx - t["x"], ry - t["y"])
            if distance > DISTANCE_TOLERANCE_PX:
                continue
            if _angle_diff(rotated_angle, t["angle"]) > ANGLE_TOLERANCE_DEG:
                continue
            if nearest_distance is None or distance < nearest_distance:
                nearest, nearest_distance = t, distance

        if nearest is not None:
            matched += 1
            claimed.add(id(nearest))
    return matched


def similarity_score(probe, template):
    """0-100. Tries every same-type (probe minutia, template minutia) pair
    as a candidate rigid-alignment anchor, scores each, keeps the best."""
    if not probe or not template:
        return 0.0

    grid = _build_grid(template)
    smaller_set = min(len(probe), len(template))

    best_matched = 0
    for p in probe:
        for t in template:
            if p["type"] != t["type"]:
                continue
            rotation = t["angle"] - p["angle"]
            # Rotating the probe set about p leaves p itself in place, so
            # the translation needed is exactly t minus p.
            dx, dy = t["x"] - p["x"], t["y"] - p["y"]
            matched = _count_matches(probe, grid, rotation, dx, dy, anchor=p)
            if matched > best_matched:
                best_matched = matched
                if best_matched >= smaller_set:
                    # Can't possibly do better than matching every minutia
                    # in the smaller set -- stop early.
                    return 100.0

    return round(100 * best_matched / smaller_set, 2) if smaller_set else 0.0
