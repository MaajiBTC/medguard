"""Baseline storage/update helpers, kept separate from engine.py's decision logic.

Stats are stored as {mean, stdev} per feature and updated incrementally via Welford's
online algorithm, reconstructing M2 from the stored stdev each time (M2 = stdev^2 * n)
rather than persisting M2 separately -- keeps the schema small at the cost of a little
float round-trip, which is fine for this scale.
"""

import math

LEARNING_MODE_SAMPLE_THRESHOLD = 5


def _welford_update(stat, n_before, new_value):
    """stat: {"mean": float, "stdev": float} or {} for a not-yet-seen feature."""
    if not stat:
        return {"mean": new_value, "stdev": 0.0}

    mean_before = stat["mean"]
    m2_before = stat["stdev"] ** 2 * n_before

    n_after = n_before + 1
    delta = new_value - mean_before
    mean_after = mean_before + delta / n_after
    delta2 = new_value - mean_after
    m2_after = m2_before + delta * delta2

    stdev_after = math.sqrt(m2_after / n_after) if n_after > 1 else 0.0
    return {"mean": mean_after, "stdev": stdev_after}


def _mean(values):
    return sum(values) / len(values) if values else None


def extract_mouse_features(mouse_events):
    """Returns {"speed": float, "click_duration": float} or {} if not enough data."""
    if not mouse_events:
        return {}

    moves = [e for e in mouse_events if e.get("event") == "mousemove"]
    speeds = []
    for a, b in zip(moves, moves[1:]):
        dt = b["t"] - a["t"]
        if dt <= 0:
            continue
        dist = math.hypot(b["x"] - a["x"], b["y"] - a["y"])
        speeds.append(dist / dt)

    downs = {}
    click_durations = []
    for e in mouse_events:
        if e.get("event") == "mousedown":
            downs[e.get("button", 0)] = e["t"]
        elif e.get("event") == "mouseup" and e.get("button", 0) in downs:
            click_durations.append(e["t"] - downs.pop(e.get("button", 0)))

    features = {}
    speed_mean = _mean(speeds)
    if speed_mean is not None:
        features["speed"] = speed_mean
    duration_mean = _mean(click_durations)
    if duration_mean is not None:
        features["click_duration"] = duration_mean
    return features


def extract_keystroke_features(behavioral_capture):
    """Averages every keystroke_features entry captured this session (the login
    baseline plus any session_windows so far) into scalar samples per feature."""
    entries = []
    login = behavioral_capture.keystroke_features.get("login")
    if login:
        entries.append(login)
    entries.extend(behavioral_capture.keystroke_features.get("session_windows", []))

    if not entries:
        return {}

    features = {}
    for list_field, name in [
        ("flight_times", "flight_time"),
        ("digraph_latencies", "digraph_latency"),
        ("trigraph_latencies", "trigraph_latency"),
    ]:
        samples = [_mean(e[list_field]) for e in entries if e.get(list_field)]
        samples = [s for s in samples if s is not None]
        if samples:
            features[name] = _mean(samples)

    rhythm_samples = [e["rhythm_consistency"] for e in entries if "rhythm_consistency" in e]
    if rhythm_samples:
        features["rhythm_consistency"] = _mean(rhythm_samples)

    error_samples = [e["error_correction_rate"] for e in entries if "error_correction_rate" in e]
    if error_samples:
        features["error_correction_rate"] = _mean(error_samples)

    return features


def update_baseline(baseline, session):
    """Folds this session's signals into the rolling baseline. Only called for
    non-denied decisions (see engine.py) -- an attacker's failed attempts never
    reinforce the profile they're trying to spoof."""
    n_before = baseline.sample_count

    keystroke_samples = extract_keystroke_features(session.behavioral_capture)
    for feature, value in keystroke_samples.items():
        baseline.keystroke_stats[feature] = _welford_update(
            baseline.keystroke_stats.get(feature, {}), n_before, value
        )

    mouse_samples = extract_mouse_features(session.behavioral_capture.mouse_events)
    for feature, value in mouse_samples.items():
        baseline.mouse_stats[feature] = _welford_update(
            baseline.mouse_stats.get(feature, {}), n_before, value
        )

    login_hour = session.started_at.hour + session.started_at.minute / 60
    baseline.login_hour_stats = _welford_update(baseline.login_hour_stats, n_before, login_hour)

    if session.device_id not in baseline.known_device_ids:
        baseline.known_device_ids.append(session.device_id)
    if session.network_segment not in baseline.known_network_segments:
        baseline.known_network_segments.append(session.network_segment)

    baseline.sample_count = n_before + 1
    baseline.save()
