#!/usr/bin/env python3
"""Read-only, bounded text-protocol perception. No physical actions or Mishe imports."""
import argparse
import datetime
import fcntl
import ipaddress
import json
import math
import os
from pathlib import Path
import re
import signal
import time
import urllib.error
import urllib.parse
import urllib.request
import subprocess

MAX_SEQUENCE = 9007199254740991
HISTORY = 32
EXCURSION_LOG_LINES = 128
EVENTS = 16
SENSORS = ("battery", "light", "acceleration")
CAPABILITIES = ("battery", "light", "accelerometer", "vibration", "wifi_link_rssi", "bluetooth_le")
OWNER_CHECKBOXES = ("battery", "light", "acceleration", "vibration")

NODE_STATUS_ENTER_MARGIN = 15.0
NODE_STATUS_EXIT_MARGIN = 10.0


def atomic(path, content):
    """Commit one private file, including its directory entry, on a local filesystem."""
    # The exclusive follower lock permits one fixed temporary per destination;
    # repeated crashes cannot accumulate an unbounded set of abandoned files.
    name = path.with_name("." + path.name + ".pending")
    fd = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
        directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def save(path, state):
    atomic(path, json.dumps(state, ensure_ascii=False, allow_nan=False) + "\n")


def initial(node, source):
    return {"version": 1, "node": node, "source": source, "cursor": 0,
            "session": None, "capabilities": {}, "owner_checkboxes": {}, "latest": {}, "history": [],
            "session_records": 0, "ble_scan_error_streak": 0,
            "actions": [], "events": [], "event_key": None,
            "last_light_sequence": None, "last_light_transition": None,
            "last_light_event_cursor": None, "poll_start_cursor": 0,
            "poll_at": None, "ok_at": None, "error": None, "has_more": False}


def load(path, node=None, source=None):
    if not path.exists():
        return initial(node, source)
    state = json.loads(path.read_text(encoding="utf-8"))
    if state["version"] != 1 or not 0 <= state["cursor"] <= MAX_SEQUENCE:
        raise ValueError("unsupported or corrupt perception state")
    if node is not None and (state["node"] != node or state["source"] != source):
        raise ValueError("state belongs to a different endpoint; reconcile explicitly")
    if "owner_checkboxes" not in state:
        state["owner_checkboxes"] = {}
    if ("_class_b_detected_session" in state and
            "_class_b_detected_light_sequence" not in state):
        # Pre-change state keyed class-B dedup on (cursor, session). Seed the
        # light-sequence identity from the retained history so a restart does
        # not re-fire the still-current gap.
        state["_class_b_detected_light_sequence"] = _last_light_sequence(state)
    return state


def parse_page(body, cursor):
    """Validate the complete envelope before advancing any durable state."""
    if len(body) > 65536:
        raise ValueError("oversized response")
    text = body.decode("utf-8")
    lines = text.removesuffix("\n").split("\n") if text else []
    if len(lines) > 128:
        raise ValueError("too many records")
    records = []
    for line in lines:
        line = line.removesuffix("\r")
        if len(line.encode("utf-8")) > 1024 or any(
                ord(c) < 32 or ord(c) == 127 or c in "\u0085\u2028\u2029\ufeff" for c in line):
            raise ValueError("invalid record envelope")
        match = re.fullmatch(r"([1-9][0-9]*) (.+)", line)
        if not match:
            raise ValueError("invalid sequence envelope")
        sequence = int(match[1])
        if not cursor < sequence <= MAX_SEQUENCE:
            raise ValueError("non-increasing sequence")
        records.append((sequence, match[2]))
        cursor = sequence
    return records


def record(sequence, raw, received, backlog_pending):
    words = raw.split(" ")
    collected = int(words[0]) if words[0].isdigit() and len(words[0]) <= 12 else None
    kind = words[1].split("=", 1)[0] if collected is not None and len(words) > 1 else "unknown"
    fields = dict(word.split("=", 1) for word in words[1:] if "=" in word)
    return {"sequence": sequence, "raw": raw, "collected": collected,
            "received": received, "kind": kind, "fields": fields,
            "backlog_page_pending_at_receipt": backlog_pending,
            "host_receipt_monotonic_ns": time.monotonic_ns(),
            "host_boot_id": host_boot_id()}


def apply_page(state, records, received, has_more, log_dir=None):
    """Validate the complete envelope before advancing any durable state.

    log_dir optionally enables excursion-log emission: when a hello finalizes
    an outgoing session, one bounded line for that session is appended before
    the state resets. States written before excursion logging lack
    session_records; seed it from the retained window so the truncation flag
    stays truthful.
    """
    if "session_records" not in state:
        state["session_records"] = len(state.get("history", []))
    state["poll_start_cursor"] = state["cursor"]
    for sequence, raw in records:
        item = record(sequence, raw, received, has_more)
        words = raw.split(" ")
        kind = item["kind"]
        if kind == "hello":
            session = item["fields"].get("session")
            if session != state["session"]:
                if log_dir is not None and state["session"] is not None:
                    emit_excursion(log_dir, state, received)
                state["session_records"] = 0
                state["capabilities"] = {}
                state["owner_checkboxes"] = {}
                state["latest"] = {}
                state["history"] = []
                state["session"] = session
                state["last_light_sequence"] = None
                state["last_light_transition"] = None
                state["ble_scan_error_streak"] = 0
        if kind == "cap" and len(words) >= 3:
            if words[2] in CAPABILITIES:
                state["capabilities"][words[2]] = "present"
        elif kind in ("sensor", "actuator") and len(words) >= 4 and words[3] == "absent":
            if words[2] in CAPABILITIES:
                state["capabilities"][words[2]] = "absent"
        if kind == "owner_checkboxes":
            checkboxes = {}
            for word in words[1:]:
                name, separator, value = word.partition("=")
                if separator and value in ("on", "off"):
                    checkboxes[name] = value
            state["owner_checkboxes"] = checkboxes
        if kind == "action":
            state["actions"].append(item)
            state["actions"] = state["actions"][-EVENTS:]
        if kind == "ble_scan":
            subtype = words[2] if len(words) > 2 and words[2] in BLE_SCAN_SUBTYPES else None
            if subtype == "error":
                state["ble_scan_error_streak"] = state.get("ble_scan_error_streak", 0) + 1
            else:
                state["ble_scan_error_streak"] = 0
        # Retain raw unknown names/fields, with a bounded latest-kind map and history.
        state["latest"].pop(kind, None)
        state["latest"][kind] = item
        if len(state["latest"]) > 32:
            del state["latest"][next(iter(state["latest"]))]
        state["history"].append(item)
        state["history"] = state["history"][-HISTORY:]
        state["session_records"] = state.get("session_records", 0) + 1
        state["cursor"] = sequence
    state.update(poll_at=received, ok_at=received, error=None, has_more=has_more)


def number(fields, key):
    try:
        value = float(fields[key])
        return value if math.isfinite(value) else None
    except (KeyError, ValueError):
        return None

_BOOT_ID_ATTEMPTED = False
_BOOT_ID = None


def host_boot_id():
    """Read the host boot identifier once per process; None when unreadable."""
    global _BOOT_ID_ATTEMPTED, _BOOT_ID
    if not _BOOT_ID_ATTEMPTED:
        _BOOT_ID_ATTEMPTED = True
        try:
            value = Path("/proc/sys/kernel/random/boot_id").read_text(
                encoding="utf-8").strip()
            if re.fullmatch(r"[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}", value):
                _BOOT_ID = value
        except OSError:
            _BOOT_ID = None
    return _BOOT_ID


def phone_elapsed_realtime(item):
    """Phone monotonic elapsedRealtime ms from a protocol v2 record, else None.

    Deltas are comparable only within one hello session (same phone boot); the
    value is not Unix time and not a host-clock quantity.
    """
    value = item["fields"].get("phone_elapsed_ms") if item else None
    if value is None or not re.fullmatch(r"(?:0|[1-9][0-9]*)", value):
        return None
    timestamp = int(value)
    if timestamp > 9223372036854775807:
        return None
    return timestamp


def sensor_time_scope(item, session):
    """Return raw per-sensor monotonic time only with a usable session boundary."""
    value = item["fields"].get("sensor_time_ns") if item else None
    if (not session or value is None or
            not re.fullmatch(r"(?:0|[1-9][0-9]*)", value)):
        return None
    timestamp = int(value)
    if timestamp > 9223372036854775807:
        return None
    return {"sensor_time_ns": timestamp, "scope": [item["kind"], session],
            "status": "same-sensor-session-only"}


def excursion_window(state):
    """Bounded phone-clock window over the retained history of the live session.

    phone_elapsed_ms is monotonic per hello session, so [min, max] over the
    retained records is well-defined; with window_truncated the bounds cover
    only the retained tail, not the whole session. The acquisition-span range
    is a separate cross-clock transport diagnostic, never folded into the
    phone window. The protocol v2.1 retention set (windowed standard
    deviations, oscillation/quantization and transient-revert evidence) and
    the calibration-free accel guard are computed over the same retained
    window; see retention_set and accel_guard.
    """
    history = state.get("history", [])
    values = [value for value in
              (phone_elapsed_realtime(item) for item in history) if value is not None]
    spans = [float(round((item["received"] - item["collected"]) * 1000, 1))
             for item in history if item["collected"] is not None]
    if not history:
        window, reason = None, "no retained records"
    elif not values:
        window, reason = None, "no phone_elapsed_ms in retained window"
    else:
        window, reason = [min(values), max(values)], None
    retention = retention_set(history)
    return {
        "sequence_start": history[0]["sequence"] if history else None,
        "sequence_end": history[-1]["sequence"] if history else None,
        "retained_count": len(history),
        "window_truncated": state.get("session_records", 0) > HISTORY,
        "phone_elapsed_ms_min": window[0] if window else None,
        "phone_elapsed_ms_max": window[1] if window else None,
        "phone_window_reason": reason,
        "acquisition_span_ms_min": min(spans) if spans else None,
        "acquisition_span_ms_max": max(spans) if spans else None,
        "light_std": retention["light_std"],
        "light_oscillation": retention["light_oscillation"],
        "accel_std": retention["accel_std"],
        "rssi_std": retention["rssi_std"],
        "light_transient": retention["light_transient"],
        "accel_guard": accel_guard(history),
    }


def retention_set(history):
    """Protocol v2.1 per-excursion retention evidence over the retained window.

    The windowed standard deviations use the same population formula and
    minimum sample count as stillness_snapshot, so retained evidence and the
    live composite agree on the quantity. Oscillation evidence records an
    adjacent 0<->1 lux flip pair as the observed transition path, or a
    two-level quantization signature when no flip is present; transient
    records whether post-flip values return within the window. Missing values
    stay null/none: the scorer marks such excursions indeterminate, never
    silently excluded.
    """
    light_values = []
    accel_values = []
    rssi_values = []
    for item in history:
        kind = item["kind"]
        if kind == "acceleration":
            value = magnitude(item)
            if value is not None:
                accel_values.append(value)
        elif kind == "light":
            value = number(item["fields"], "lux")
            if value is not None:
                light_values.append(value)
        elif kind == "wifi_link_rssi_dbm":
            value = number(item["fields"], "wifi_link_rssi_dbm")
            if value is not None:
                rssi_values.append(value)

    def std(values):
        if len(values) < STILLNESS_MIN_SAMPLES:
            return None
        mean = sum(values) / len(values)
        variance = sum((value - mean) ** 2 for value in values) / len(values)
        return round(math.sqrt(variance), 3)

    oscillation = "none"
    transient = "none"
    flipped = any(
        {light_values[index - 1], light_values[index]} == {0, 1}
        for index in range(1, len(light_values)))
    if flipped:
        path = []
        for value in light_values:
            if value in (0, 1) and (not path or value != path[-1]):
                path.append(value)
        oscillation = "->".join(str(int(value)) for value in path)
        transient = ("revert" if len(path) > 1 and path[0] == path[-1]
                     else "open")
    elif (len(light_values) >= STILLNESS_MIN_SAMPLES and
          all(value in (0, 1) for value in light_values)):
        oscillation = "quantized"
    return {
        "light_std": std(light_values),
        "light_oscillation": oscillation,
        "accel_std": std(accel_values),
        "rssi_std": std(rssi_values),
        "light_transient": transient,
    }

ACCEL_GUARD_MIN_SAMPLES = 5
ACCEL_GUARD_GRAVITY = 9.80665
ACCEL_GUARD_MAGNITUDE_TOLERANCE = 0.20
ACCEL_GUARD_MAGNITUDE_STABILITY = 0.5


def median(values):
    """Median of a non-empty list of finite numbers."""
    ordered = sorted(values)
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[middle]
    return (ordered[middle - 1] + ordered[middle]) / 2


def accel_guard(history):
    """Calibration-free accel-channel guard over the retained window.

    A pinned axis (bit-identical values across the window) or a stable
    magnitude far from Earth gravity makes the accel leg indeterminate: a
    pinned axis yields std ~ 0, which a stillness/change scorer reads as
    "still", and a stable 1.6 g for hours is not real acceleration. Both
    regimes were observed on Note3 (research-methods wake 75303/75378).
    The pinned-axis test is offset-invariant (per-axis range); the magnitude
    test compares |a| to the nominal g and needs no per-device calibration.
    Both survive the baseline steps documented above: a shifted baseline is
    itself flagged implausible-magnitude, and a pinned axis is caught by range.
    No value is substituted: an indeterminate verdict never authorizes a stillness or a
    movement claim from the accel leg.
    """
    axes = {"x": [], "y": [], "z": []}
    magnitudes = []
    for item in history:
        if item["kind"] != "acceleration":
            continue
        fields = item.get("fields", {})
        values = [number(fields, key) for key in ("x", "y", "z")]
        if any(value is None for value in values):
            continue
        for key, value in zip(("x", "y", "z"), values):
            axes[key].append(value)
        magnitudes.append(math.hypot(*values))

    pinned = sorted(key for key, values in axes.items()
                    if values and max(values) == min(values))
    count = len(magnitudes)
    median_magnitude = round(median(magnitudes), 3) if magnitudes else None
    std_magnitude = None
    if magnitudes:
        mean = sum(magnitudes) / count
        variance = sum((value - mean) ** 2 for value in magnitudes) / count
        std_magnitude = round(math.sqrt(variance), 3)

    if count < ACCEL_GUARD_MIN_SAMPLES:
        status = "few-samples"
    elif pinned:
        status = "pinned-axis"
    elif (abs(median_magnitude - ACCEL_GUARD_GRAVITY) / ACCEL_GUARD_GRAVITY
          > ACCEL_GUARD_MAGNITUDE_TOLERANCE and
          std_magnitude < ACCEL_GUARD_MAGNITUDE_STABILITY):
        status = "implausible-magnitude"
    else:
        status = "ok"
    return {
        "status": status,
        "samples": count,
        "pinned_axes": pinned,
        "magnitude_median": median_magnitude,
        "magnitude_std": std_magnitude,
        "gravity": ACCEL_GUARD_GRAVITY,
        "tolerance": ACCEL_GUARD_MAGNITUDE_TOLERANCE,
        "stability": ACCEL_GUARD_MAGNITUDE_STABILITY,
        "indeterminate": status != "ok",
    }


def freeze_entries(path):
    """Documented freeze onsets from the discovery index; [] when absent/unreadable."""
    try:
        entries = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    if isinstance(entries, dict):
        return [entries]
    return entries if isinstance(entries, list) else []


def freeze_overlap(entries, session, start_sequence, end_sequence):
    """The documented freeze onset whose sequence falls inside the window range."""
    for entry in entries:
        if not isinstance(entry, dict) or entry.get("session") != session:
            continue
        sequence = entry.get("sequence")
        if (isinstance(sequence, int) and not isinstance(sequence, bool) and
                start_sequence <= sequence <= end_sequence):
            return entry
    return None


def emit_excursion(log_dir, state, now):
    """Persist one bounded line for the session a fresh hello is finalizing.

    Append-only and bounded per node; emission happens only at a session
    boundary, so a silent or frozen phone produces no churn. The outgoing
    session's retained window is emitted before the state resets.
    """
    if log_dir is None or state.get("session") is None:
        return
    window = excursion_window(state)
    freeze = None
    if window["sequence_start"] is not None:
        path = log_dir.parents[1] / "discovery" / "space-light-freeze.json"
        entries = freeze_entries(path)
        freeze = freeze_overlap(entries, state["session"], window["sequence_start"],
                              window["sequence_end"])

    def range_text(low, high):
        return "null" if low is None else f"{low},{high}"

    def optional_text(value):
        return "null" if value is None else str(value)

    freeze_class = (freeze.get("class") or "null") if freeze else "null"
    freeze_sequence = freeze.get("sequence") if freeze else "null"
    line = (f"excursion emitted={stamp(now)} node={state['node']} "
            f"session={state['session']} cursor_start={window['sequence_start']} "
            f"cursor_end={state['cursor']} sequence_start={window['sequence_start']} "
            f"sequence_end={window['sequence_end']} "
            f"retained_count={window['retained_count']} "
            f"window_truncated={str(window['window_truncated']).lower()} "
            f"phone_elapsed_ms="
            f"{range_text(window['phone_elapsed_ms_min'], window['phone_elapsed_ms_max'])} "
            f"phone_window_reason={window['phone_window_reason'] or 'null'} "
            f"acquisition_span_ms={range_text(window['acquisition_span_ms_min'], window['acquisition_span_ms_max'])} "
            f"light_std={optional_text(window['light_std'])} "
            f"light_oscillation={window['light_oscillation']} "
            f"accel_std={optional_text(window['accel_std'])} "
            f"accel_guard={window['accel_guard']['status']} "
            f"accel_samples={window['accel_guard']['samples']} "
            f"accel_pinned_axes={','.join(window['accel_guard']['pinned_axes']) or 'null'} "
            f"accel_magnitude_median={optional_text(window['accel_guard']['magnitude_median'])} "
            f"accel_magnitude_std={optional_text(window['accel_guard']['magnitude_std'])} "
            f"rssi_std={optional_text(window['rssi_std'])} "
            f"light_transient={window['light_transient']} "
            f"freeze_overlap={str(freeze is not None).lower()} "
            f"freeze_class={freeze_class} freeze_sequence={freeze_sequence}")

    path = log_dir / f"excursion-log-{state['node']}.txt"
    try:
        previous = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    except OSError:
        previous = []
    atomic(path, "\n".join([*previous, line][-EXCURSION_LOG_LINES:]) + "\n")

CLASS_B_MIN_NULL_LUX = 2
CLASS_B_DETECTOR_LINES = 128
CLASS_B_FREEZE_SECONDS = 30.0


def detect_class_b_delivery_gap(state, log_dir, node_state=None):
    """Detect class-B delivery gap: emission halt with null-lux reads across time.

    Fires on (session change with null-lux) OR (cursor freeze with null-lux).
    Null-lux = light=0.0 persists across >= CLASS_B_MIN_NULL_LUX consecutive
    retention events. Emits bounded JSONL to log_dir/class-b-delivery-gap-detectors.jsonl.

    Dedup keys on (session, newest retained light sequence): the null-lux light
    evidence is the quantity that must be unmoving for two onsets to be the
    same gap. A non-producer write (an authenticated POST of a malformed queue
    line) advances the cursor without adding light evidence, so it can no
    longer re-arm a spurious second onset for one continuous gap. The cursor's
    observed state is recorded as provenance, never used as identity.
    The host-side node mode (sending / collect-only / OFF) is recorded as
    provenance so a gap names *why* the producer is silent, never as part of
    the dedup identity.
    """
    if log_dir is None:
        return None

    cursor = state["cursor"]
    session = state["session"]
    prev_cursor = state.get("_class_b_prev_cursor")
    prev_session = state.get("_class_b_prev_session")

    if prev_cursor is not None and cursor != prev_cursor:
        state["_class_b_last_cursor_advance_at"] = time.time()

    state["_class_b_prev_cursor"] = cursor
    state["_class_b_prev_session"] = session

    if prev_cursor is None or prev_session is None:
        return None

    last_light_sequence = _last_light_sequence(state)
    if (last_light_sequence == state.get("_class_b_detected_light_sequence") and
            session == state.get("_class_b_detected_session")):
        return None

    max_consecutive = _max_consecutive_null_lux(state)
    if max_consecutive < CLASS_B_MIN_NULL_LUX:
        return None

    session_changed = (session is not None and session != prev_session)
    last_advance = state.get("_class_b_last_cursor_advance_at", time.time())
    cursor_frozen = (cursor == prev_cursor and
                     time.time() - last_advance > CLASS_B_FREEZE_SECONDS)

    if not (session_changed or cursor_frozen):
        return None

    state["_class_b_detected_session"] = session
    state["_class_b_detected_light_sequence"] = last_light_sequence

    detection = {
        "kind": "class-b-delivery-gap",
        "detected_at": stamp(time.time()),
        "cursor": cursor,
        "cursor_state": ("advanced" if cursor != prev_cursor
                         else "frozen" if cursor_frozen else "unknown"),
        "session": session,
        "light_sequence": last_light_sequence,
        "trigger": "session-change" if session_changed else "cursor-freeze",
        "null_lux_consecutive": max_consecutive,
        "node_mode": (node_state or {}).get("mode", "UNKNOWN"),
        "node_state_status": (node_state or {}).get("status", "unknown"),
    }

    path = log_dir / "class-b-delivery-gap-detectors.jsonl"
    previous = []
    if path.exists():
        text = path.read_text(encoding="utf-8").strip()
        if text:
            previous = text.split("\n")
    line = json.dumps(detection, ensure_ascii=False, allow_nan=False, sort_keys=True)
    atomic(path, "\n".join([*previous, line][-CLASS_B_DETECTOR_LINES:]) + "\n")

    return detection

CLASS_A_WINDOW_SECONDS = 300
CLASS_A_DETECTOR_LINES = 128


def _emit_class_a(log_dir, detection):
    path = log_dir / "class-a-detectors.jsonl"
    previous = []
    if path.exists():
        text = path.read_text(encoding="utf-8").strip()
        if text:
            previous = text.split("\n")
    line = json.dumps(detection, ensure_ascii=False, allow_nan=False, sort_keys=True)
    atomic(path, "\n".join([*previous, line][-CLASS_A_DETECTOR_LINES:]) + "\n")


def _latest_code2(state):
    """The latest ble_scan item when it is a code=2 error, else None.

    latest is keyed by kind and survives the bounded history window, so a
    code=2 observed earlier in the session stays armable until a newer
    ble_scan event or a session change replaces it.
    """
    item = state["latest"].get("ble_scan")
    if item is None:
        return None
    words = item["raw"].split(" ")
    subtype = words[2] if len(words) > 2 and words[2] in BLE_SCAN_SUBTYPES else None
    if subtype == "error" and item.get("fields", {}).get("code") == "2":
        return item
    return None


def detect_class_a_freeze(state, log_dir):
    """Detect class-A freeze: BLE scan code=2 followed by sensor silence.

    Arms when the latest ble_scan event is a code=2 error; the arm persists
    while no newer ble_scan event or session change replaces it, even after
    the code=2 record ages out of the bounded history. The freeze is
    confirmed when delivery stops for CLASS_A_WINDOW_SECONDS and the
    silence began within CLASS_A_WINDOW_SECONDS of the code=2 receipt
    (5min window agreed with discover; freeze #5 observed gap ~1.3min).
    Delivery continuing past the window rejects the instance. Emits bounded
    JSONL to log_dir/class-a-detectors.jsonl.
    """
    if log_dir is None:
        return None

    now = time.time()
    code2_item = _latest_code2(state)

    if code2_item is None:
        state["_class_a_code2_cursor"] = None
        state["_class_a_code2_received"] = None
        state["_class_a_detection_emitted"] = False
        return None

    code2_cursor = code2_item["sequence"]
    code2_received = code2_item["received"]

    if code2_cursor != state.get("_class_a_code2_cursor"):
        state["_class_a_code2_cursor"] = code2_cursor
        state["_class_a_code2_received"] = code2_received
        state["_class_a_detection_emitted"] = False
        return None

    if state.get("_class_a_detection_emitted"):
        return None

    after = [item["received"] for item in state["history"]
             if item["sequence"] > code2_cursor]
    last_after = max(after) if after else None
    silence_onset = code2_received if last_after is None else last_after

    if (now - silence_onset >= CLASS_A_WINDOW_SECONDS and
            silence_onset - code2_received <= CLASS_A_WINDOW_SECONDS):
        state["_class_a_detection_emitted"] = True
        detection = {
            "kind": "class-a-freeze",
            "detected_at": stamp(now),
            "cursor": state["cursor"],
            "code2_cursor": code2_cursor,
            "silence_onset_epoch_s": silence_onset,
            "code2_received_epoch_s": code2_received,
            "window_seconds": CLASS_A_WINDOW_SECONDS,
            "reason": "delivery halted for window with silence onset within window of code=2",
        }
        _emit_class_a(log_dir, detection)
        return detection

    if last_after is not None and last_after > code2_received + CLASS_A_WINDOW_SECONDS:
        state["_class_a_detection_emitted"] = True
        detection = {
            "kind": "class-a-rejected",
            "detected_at": stamp(now),
            "cursor": state["cursor"],
            "code2_cursor": code2_cursor,
            "last_delivery_after_code2_epoch_s": last_after,
            "code2_received_epoch_s": code2_received,
            "window_seconds": CLASS_A_WINDOW_SECONDS,
            "reason": "delivery continued past window after code=2",
        }
        _emit_class_a(log_dir, detection)
        return detection

    return None


CLASS_C_WINDOW_SECONDS = 120.0
CLASS_C_DETECTOR_LINES = 128


def _emit_class_c(log_dir, detection):
    path = log_dir / "class-c-delivery-gap-detectors.jsonl"
    previous = []
    if path.exists():
        text = path.read_text(encoding="utf-8").strip()
        if text:
            previous = text.split("\n")
    line = json.dumps(detection, ensure_ascii=False, allow_nan=False, sort_keys=True)
    atomic(path, "\n".join([*previous, line][-CLASS_C_DETECTOR_LINES:]) + "\n")


def _last_light_sequence(state):
    """Sequence of the newest retained light observation, or None."""
    for item in reversed(state.get("history", [])):
        if item["kind"] == "light":
            return item.get("sequence")
    return None


def _max_consecutive_null_lux(state):
    """Max consecutive null-lux reads across the retained light history."""
    light_items = [item for item in state["history"] if item["kind"] == "light"]
    max_consecutive = 0
    current = 0
    for item in light_items:
        lux = number(item.get("fields", {}), "lux")
        if lux == 0.0:
            current += 1
            max_consecutive = max(max_consecutive, current)
        else:
            current = 0
    return max_consecutive


def _host_stopped_state():
    """Check if org.androidbody is force-stopped via host-side adb.

    Returns True if stopped=true, False if stopped=false, None if unknown.
    Bounded: 5-second timeout on adb command. Never raises.
    """
    try:
        result = subprocess.run(
            ["adb", "shell", "dumpsys", "package", "org.androidbody"],
            capture_output=True, text=True, timeout=5
        )
        if result.returncode != 0:
            return None
        for line in result.stdout.splitlines():
            if "stopped=" in line:
                if "stopped=true" in line:
                    return True
                if "stopped=false" in line:
                    return False
        return None
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return None

def detect_class_c_delivery_gap(state, log_dir):
    """Detect class-C delivery gap: delivery halt with no known cause.

    Fires when no new record has been received for CLASS_C_WINDOW_SECONDS
    while polls keep succeeding, AND the latest ble_scan is not a code=2
    error (class-A not armed), AND the class-B null-lux condition is not
    met (no null-lux freeze). Non-deterministic: phone asleep, force-stopped
    app, or other causes. The deterministic complement is the host-side adb
    check (dumpsys package stopped), owned by health/genome. Emits bounded
    JSONL to log_dir/class-c-delivery-gap-detectors.jsonl.
    """
    if log_dir is None:
        return None

    now = time.time()
    history = state["history"]
    if not history:
        return None

    last_received = max(item["received"] for item in history)
    if now - last_received < CLASS_C_WINDOW_SECONDS:
        return None

    ok_at = state.get("ok_at")
    if ok_at is None or now - ok_at >= CLASS_C_WINDOW_SECONDS:
        return None

    if _latest_code2(state) is not None:
        return None

    if _max_consecutive_null_lux(state) >= CLASS_B_MIN_NULL_LUX:
        return None

    cursor = state["cursor"]
    session = state["session"]
    if (_last_light_sequence(state) == state.get("_class_b_detected_light_sequence") and
            session == state.get("_class_b_detected_session")):
        return None
    if (cursor == state.get("_class_c_detected_cursor") and
            session == state.get("_class_c_detected_session")):
        return None

    state["_class_c_detected_cursor"] = cursor
    state["_class_c_detected_session"] = session

    host_stopped = _host_stopped_state()

    detection = {
        "kind": "class-c-delivery-gap",
        "detected_at": stamp(now),
        "cursor": cursor,
        "session": session,
        "last_received_epoch_s": last_received,
        "window_seconds": CLASS_C_WINDOW_SECONDS,
        "reason": "delivery halted with polls succeeding; no code=2, no null-lux freeze",
        "host_stopped": host_stopped,
    }

    _emit_class_c(log_dir, detection)
    return detection



def freshness(item, now, stale):
    if item is None or item["received"] is None:
        return "unknown"
    age = now - item["received"]
    if age < -5:
        return "unknown-clock-future"
    if age > stale:
        return "stale"
    return "fresh-clock-conditional"


def sensor_status(item, now, stale):
    if item is None:
        return "unknown"
    status = freshness(item, now, stale)
    if " unavailable" in item["raw"]:
        return "unavailable/" + status
    fields = item["fields"]
    required = {"battery": ("level",), "light": ("lux",),
                "acceleration": ("x", "y", "z")}[item["kind"]]
    values = [number(fields, key) for key in required]
    if any(value is None for value in values):
        return "unknown/" + status
    if item["kind"] == "battery" and not 0 <= values[0] <= 1:
        return "invalid/" + status
    if item["kind"] == "light" and values[0] < 0:
        return "invalid/" + status
    if item["kind"] == "acceleration" and not math.isfinite(math.hypot(*values)):
        return "invalid/" + status
    if "age_ms" in fields:
        age = number(fields, "age_ms")
        if age is None or age < 0:
            return "unknown-age/" + status
        if age > stale * 1000:
            return "stale"
    return status


def wifi_rssi_status(item, now, stale):
    if item is None:
        return "unknown/no-observation"
    fields = item["fields"]
    if fields.get("source") != "androidbody_wifi_api":
        return "unknown/unrecognized-source"
    if " unavailable" in item["raw"]:
        return "unavailable/" + freshness(item, now, stale)
    value = number(fields, "wifi_link_rssi_dbm")
    if value is None or not -126 <= value < 0:
        return "unknown/invalid-or-missing-rssi"
    return freshness(item, now, stale)


def wifi_rssi_snapshot(item, now, stale):
    fields = item["fields"] if item else {}
    unavailable = item is not None and " unavailable" in item["raw"]
    return {
        "status": wifi_rssi_status(item, now, stale),
        "sequence": item["sequence"] if item else None,
        "source": fields.get("source") if item else None,
        "rssi_dbm": (number(fields, "wifi_link_rssi_dbm")
                     if item and not unavailable and
                     wifi_rssi_status(item, now, stale) == "fresh-clock-conditional"
                     else None),
        "units": "dBm",
        "protocol_event_time_epoch_s": item["collected"] if item else None,
        "consumer_receipt_epoch_s": item["received"] if item else None,
        "observed_at_api_read_time": fields.get("observed_at") if item else None,
        "acquisition_age": None,
        "acquisition_age_reason": "not provided; observed_at is API read time, not measurement age",
        "unavailable_reason": fields.get("reason") if unavailable else None
    }

BLE_STATES = {
    "feature_ble": {"present", "absent", "query_error"},
    "adapter": {"enabled", "disabled", "unavailable", "error"},
    "scanner_api": {"present", "absent", "unavailable", "error"},
    "advertiser_api": {"present", "absent", "unavailable", "error"},
    "scanner_getter": {"returned", "null", "unavailable", "error"},
    "advertiser_getter": {"returned", "null", "unavailable", "error"},
    "advertiser_supported": {"supported", "unsupported", "unavailable", "error"},
}

# Accel magnitude baseline on Note3 stepped from ~10.21 to ~15.93 m/s² at
# 2026-10-11T03:14:41Z (discrete 5-second step, cause UNKNOWN: sensor fault
# vs fixture force). Std-based composite is baseline-shift-immune: std of a
# constant stream is zero regardless of baseline. Absolute-magnitude thresholds
# (e.g. "still if |a| < 11") would be unsound on this device in its current
# state and are not deployed.
STILLNESS_ACCEL_STD = 0.5
STILLNESS_LIGHT_STD = 0.1
STILLNESS_RSSI_STD = 2.0
STILLNESS_MIN_SAMPLES = 2


def stillness_snapshot(state, now, stale):
    """Composite stillness from joint variance of accel magnitude, light, wifi RSSI.

    When the most recent sample for any required sensor type is stale, the
    history window contains only pre-frozen samples.  Computing std over
    them would report a misleading still/moving verdict, so return
    unknown/frozen instead.
    """
    history = state.get("history", [])
    accel_values = []
    light_values = []
    rssi_values = []
    latest = {}
    for item in history:
        kind = item["kind"]
        if kind == "acceleration":
            value = magnitude(item)
            if value is not None:
                accel_values.append(value)
            latest["acceleration"] = item
        elif kind == "light":
            value = number(item["fields"], "lux")
            if value is not None:
                light_values.append(value)
            latest["light"] = item
        elif kind == "wifi_link_rssi_dbm":
            value = number(item["fields"], "wifi_link_rssi_dbm")
            if value is not None:
                rssi_values.append(value)
            latest["wifi_link_rssi_dbm"] = item

    stale_sensors = []
    for kind in ("acceleration", "light", "wifi_link_rssi_dbm"):
        item = latest.get(kind)
        if item is None:
            continue
        if freshness(item, now, stale) == "stale":
            stale_sensors.append(kind)
    if stale_sensors:
        return {
            "status": "unknown/frozen",
            "basis": "joint std of accel magnitude + light + wifi RSSI over history window",
            "thresholds": {"accel_std_m_s2": STILLNESS_ACCEL_STD,
                           "light_std_lux": STILLNESS_LIGHT_STD,
                           "rssi_std_dbm": STILLNESS_RSSI_STD},
            "accel": None,
            "light": None,
            "wifi_rssi": None,
            "stale_sensors": stale_sensors,
            "consumer": "space-perception programme (not human presence)",
        }

    def stats(vals):
        if len(vals) < STILLNESS_MIN_SAMPLES:
            return None
        mean = sum(vals) / len(vals)
        variance = sum((v - mean) ** 2 for v in vals) / len(vals)
        return {"count": len(vals), "mean": round(mean, 3),
                "std": round(math.sqrt(variance), 3)}

    accel_stats = stats(accel_values)
    light_stats = stats(light_values)
    rssi_stats = stats(rssi_values)
    if accel_stats is None or light_stats is None or rssi_stats is None:
        status = "unknown/insufficient-samples"
    elif (accel_stats["std"] <= STILLNESS_ACCEL_STD and
          light_stats["std"] <= STILLNESS_LIGHT_STD and
          rssi_stats["std"] <= STILLNESS_RSSI_STD):
        status = "still"
    else:
        status = "moving"
    return {
        "status": status,
        "basis": "joint std of accel magnitude + light + wifi RSSI over history window",
        "thresholds": {"accel_std_m_s2": STILLNESS_ACCEL_STD,
                       "light_std_lux": STILLNESS_LIGHT_STD,
                       "rssi_std_dbm": STILLNESS_RSSI_STD},
        "accel": accel_stats,
        "light": light_stats,
        "wifi_rssi": rssi_stats,
        "consumer": "space-perception programme (not human presence)",
    }

MONITOR_ARTIFACTS = Path(__file__).resolve().parent / "artifacts"
MONITOR_STATE_FILE = MONITOR_ARTIFACTS / "light-cycle-monitor-state.json"
MONITOR_LOG_FILE = MONITOR_ARTIFACTS / "light-cycle-resumed.jsonl"
MONITOR_LOG_TAIL_BYTES = 4096


def _read_json_file(path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, ValueError):
        return None


def _last_monitor_row(path, limit=MONITOR_LOG_TAIL_BYTES):
    """Last complete detector row, or None. Reads only a bounded tail.

    A partial or unparseable line (crash mid-append, or the tail read starting mid-line)
    is skipped rather than reported as "no row", so an earlier complete row is still read.
    """
    try:
        with open(path, "rb") as stream:
            stream.seek(0, os.SEEK_END)
            stream.seek(max(0, stream.tell() - limit))
            chunk = stream.read()
    except OSError:
        return None
    for line in reversed(chunk.split(b"\n")):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except (json.JSONDecodeError, UnicodeDecodeError):
            continue
        return row if isinstance(row, dict) else None
    return None


def _monitor_row_text(row):
    if row is None:
        return "none (no resumption claimed in the retained detector log)"
    gap = "-"
    if (isinstance(row.get("timestamp_unix"), (int, float)) and
            isinstance(row.get("prev_observed_unix"), (int, float))):
        gap = f"{row['timestamp_unix'] - row['prev_observed_unix']:.0f}s"
    return (f"lux={row.get('lux')} prev_lux={row.get('prev_lux')} "
            f"threshold_lux={row.get('threshold_lux')} poll={row.get('poll')} "
            f"prev_observed_gap={gap}")


def light_resumption_view(now, stale, compact=False):
    """Host-side light-resumption detector: liveness, armed state and last row.

    The detector is a separate bounded monitor; its heartbeat is the only signal that
    separates "armed, nothing observed yet" from "detector silent". A missing or stale
    heartbeat is UNKNOWN/stale, never calm.
    """
    state = _read_json_file(MONITOR_STATE_FILE)
    row = _last_monitor_row(MONITOR_LOG_FILE)
    have_heartbeat = (isinstance(state, dict) and
                      isinstance(state.get("timestamp_unix"), (int, float)))
    if have_heartbeat:
        age = now - state["timestamp_unix"]
        status = ("unknown-clock-future" if age < -5 else
                  "fresh-clock-conditional" if age <= stale else "stale/detector-silent")
    else:
        age = None
        status = "unknown/no-monitor-heartbeat"
    if compact:
        # No per-poll age here: the compact view caches to events.txt and must not churn
        # every poll the way view.txt does.
        return (f"light-resumption-detector status={status} "
                f"armed={state.get('armed') if have_heartbeat else None} "
                f"last_row={_monitor_row_text(row)}")
    lines = ["Light-cycle resumption detector (host-side bounded monitor over the Note3 "
             "light channel; no phone, transport or actuator effect):",
             f"  status={status}" +
             ("" if age is None else f" heartbeat_age={age:.1f}s (stale>{stale:g}s)")]
    if not have_heartbeat:
        lines.append("  a missing heartbeat means detector liveness is UNKNOWN, not calm")
    else:
        lines.append(f"  armed={state.get('armed')} poll={state.get('poll')} "
                     f"lux={state.get('lux')} prev_lux={state.get('prev_lux')} "
                     f"threshold_lux={state.get('threshold_lux')} pid={state.get('pid')} "
                     f"interval={state.get('interval_seconds')}s "
                     f"max_polls={state.get('max_polls')}")
        if not state.get("armed"):
            lines.append("  armed=false: no fresh sub-threshold baseline this run, so no "
                         "resumption can be claimed yet (not a fault)")
    lines.append(f"  last_row={_monitor_row_text(row)}")
    if row is not None and "threshold_lux" not in row:
        lines.append("  last_row predates the 7.0-lux rule (no threshold_lux field); it is "
                     "retained historical evidence, not an admissible resumption")
    lines.append("  resumption rows are scored by research-methods' pre-registered milestone-5 "
                 "rule; this view reports the fields verbatim and does not rescore them")
    return "\n".join(lines)


def ble_status_snapshot(item, now, stale):
    fields = item["fields"] if item else {}
    recognized = item is not None and fields.get("source") == "androidbody_bluetooth_api"
    status = (freshness(item, now, stale) if recognized else
              "unknown/unrecognized-source" if item else "unknown/no-observation")
    current = status == "fresh-clock-conditional"
    values = {key: fields.get(key) if current and fields.get(key) in states else None
              for key, states in BLE_STATES.items()}
    return {
        "status": status,
        "sequence": item["sequence"] if item else None,
        "source": fields.get("source") if item else None,
        "api": fields.get("api") if item else None,
        "api_surface": (fields.get("api_surface")
                        if current and fields.get("api_surface") == "platform_sdk"
                        else None),
        **values,
        "errors": ({key[:-6]: value for key, value in fields.items()
                    if key.endswith("_error")} if current else {}),
    }

def ble_sighting_snapshot(item, now, stale):
    fields = item["fields"] if item else {}
    status = freshness(item, now, stale) if item else "unknown/no-observation"
    current = status == "fresh-clock-conditional"
    return {
        "status": status,
        "sequence": item["sequence"] if item else None,
        "name": fields.get("name") if item else None,
        "rssi_dbm": number(fields, "rssi") if current else None,
    }


BLE_SCAN_SUBTYPES = {"start", "stop", "error", "unavailable"}


def _ble_scan_consecutive_error_count(state):
    """Durable session count of back-to-back ble_scan error events.

    Maintained by apply_page, not derived from history: the sensor-dominated
    32-item window evicts sparse ble_scan events (~120s cycle) long before
    the next error arrives, so a history scan reads 0 between cycles and
    the count vanishes from the view. Resets on any non-error ble_scan
    event or session change. Surfaces what compact_key dedup hides.
    """
    return state.get("ble_scan_error_streak", 0)


def ble_scan_snapshot(item, now, stale, consecutive_errors=None):
    fields = item["fields"] if item else {}
    status = freshness(item, now, stale) if item else "unknown/no-observation"
    current = status == "fresh-clock-conditional"
    words = item["raw"].split(" ") if item else []
    subtype = words[2] if len(words) > 2 and words[2] in BLE_SCAN_SUBTYPES else None
    return {
        "status": status,
        "sequence": item["sequence"] if item else None,
        "subtype": subtype,
        "reason": fields.get("reason") if item else None,
        "beacon": fields.get("beacon") if current else None,
        "window_ms": number(fields, "window_ms") if current else None,
        "gap_ms": number(fields, "gap_ms") if current else None,
        "consecutive_errors": consecutive_errors,
    }




def node_status(state, now, stale):
    """Node liveness with hysteresis against publish-cadence flap.

    Enter stale only when the latest sample age exceeds the threshold by
    NODE_STATUS_ENTER_MARGIN; return fresh only once it falls back below the
    threshold minus NODE_STATUS_EXIT_MARGIN. Sensor-level freshness semantics
    are unchanged; only the node label is damped. The follower persists the
    emitted label in node state so the next poll applies the margins.

    Age is measured from the consumer receipt time, not the phone event
    time, so host/phone clock skew and transport lag do not pin the label
    stale. The receipt time is the consumer's own observation of liveness.
    """
    if not state["history"]:
        return "unknown/no-observations"
    if state["has_more"]:
        return "backlog/draining"
    # Battery snapshots provide collection heartbeat even when on-change sensors are old.
    recent = [item for item in state["history"] if item["received"] is not None]
    if not recent:
        return "unknown/no-phone-clock"
    latest = max(recent, key=lambda item: item["received"])
    age = now - latest["received"]
    if age < 0:
        return "unknown-clock-future"
    if age > stale:
        status = "stale/phone-silent-or-delayed"
    else:
        status = "fresh-clock-conditional"
    previous = state.get("node_status")
    if previous not in ("fresh-clock-conditional", "stale/phone-silent-or-delayed"):
        return status
    if previous == "stale/phone-silent-or-delayed":
        if status == "fresh-clock-conditional" and age < stale - NODE_STATUS_EXIT_MARGIN:
            return "fresh-clock-conditional"
        return previous
    if status == "stale/phone-silent-or-delayed" and age > stale + NODE_STATUS_ENTER_MARGIN:
        return "stale/phone-silent-or-delayed"
    return previous


def transport(state, now, stale):
    if state["poll_at"] is None:
        return "unknown/not-polled"
    if now - state["poll_at"] > stale:
        detail = "/last-error=" + state["error"] if state["error"] else ""
        return "unknown/consumer-not-refreshing" + detail
    if state["error"]:
        return "offline-or-rejected/" + state["error"]
    return "reachable"


def magnitude(item):
    if not item:
        return None
    values = [number(item["fields"], axis) for axis in ("x", "y", "z")]
    if any(value is None for value in values):
        return None
    value = math.hypot(*values)
    return value if math.isfinite(value) else None


def compact_key(state, now, stale):
    """Evidence changes, not sequence/sample/receipt timestamp churn, drive events."""
    measured = []
    for kind in SENSORS:
        item = state["latest"].get(kind)
        status = sensor_status(item, now, stale)
        bucket = None
        if status == "fresh-clock-conditional":
            fields = item["fields"]
            if kind == "battery":
                bucket = [math.floor(number(fields, "level") * 20), fields.get("charging", "unknown")]
            elif kind == "light":
                bucket = math.floor(math.log2(1 + number(fields, "lux")))
            else:
                bucket = math.floor(magnitude(item))
        reason = item["fields"].get("reason") if item else None
        measured.append([kind, status, bucket, reason])
    actions = [item["raw"] for item in state["actions"]]
    rssi = wifi_rssi_snapshot(state["latest"].get("wifi_link_rssi_dbm"), now, stale)
    rssi_key = [rssi["status"], rssi["rssi_dbm"], rssi["unavailable_reason"],
                rssi["source"]]
    ble = ble_status_snapshot(state["latest"].get("ble_status"), now, stale)
    ble_key = [ble["status"], ble["source"], ble["api"], ble["api_surface"],
               *(ble[field] for field in BLE_STATES),
               sorted(ble["errors"].items())]
    sighting = ble_sighting_snapshot(state["latest"].get("ble_sighting"), now, stale)
    scan = ble_scan_snapshot(state["latest"].get("ble_scan"), now, stale,
                              _ble_scan_consecutive_error_count(state))
    rf_key = [sighting["status"], sighting["name"], sighting["rssi_dbm"],
              scan["status"], scan["subtype"], scan["reason"]]
    return [node_status(state, now, stale), transport(state, now, stale),
            state["session"], dict(state["capabilities"]), measured, actions,
            rssi_key, ble_key, rf_key, dict(state["owner_checkboxes"])]


def light_bucket_transition(state, previous, current, now, stale):
    if (state["has_more"] or state["session"] is None or previous is None or
            previous.get("backlog_page_pending_at_receipt", False) or
            current.get("backlog_page_pending_at_receipt", False) or
            sensor_status(previous, now, stale) != "fresh-clock-conditional" or
            sensor_status(current, now, stale) != "fresh-clock-conditional"):
        return None
    if any(item["collected"] is None or item["received"] - item["collected"] > stale
           for item in (previous, current)):
        return None
    previous_lux = number(previous["fields"], "lux")
    current_lux = number(current["fields"], "lux")
    previous_bucket = math.floor(math.log2(1 + previous_lux))
    current_bucket = math.floor(math.log2(1 + current_lux))
    if current_bucket == previous_bucket:
        return None
    if not 0 <= current["collected"] - previous["collected"] <= stale:
        return None
    def endpoint(item, lux):
        return {"sequence": item["sequence"], "lux": lux,
                "phone_sample_epoch_s": item["collected"],
                "phone_sample_utc": stamp(item["collected"]),
                "consumer_receipt_epoch_s": item["received"],
                "consumer_receipt_utc": stamp(item["received"])}
    event_id = f"{state['node']}:{state['session']}:{current['sequence']}"
    return {"event_id": event_id, "kind": "measured_light_bucket_transition",
            "source": state["source"], "session": state["session"],
            "bucket_from": previous_bucket, "bucket_to": current_bucket,
            "from": endpoint(previous, previous_lux), "to": endpoint(current, current_lux),
            "freshness_at_detection": "fresh-clock-conditional",
            "validity_seconds": stale,
            "claim": "historical-measured-light-change-only"}


def transition_text(event, node):
    start, end = event["from"], event["to"]
    return (f"measured-light-bucket-transition id={event['event_id']} {node} "
            f"source={event['source']} session={event['session']} "
            f"bucket={event['bucket_from']}->{event['bucket_to']}; "
            f"from=#{start['sequence']} lux={start['lux']} "
            f"phone_sample={start['phone_sample_utc']} "
            f"consumer_receipt={start['consumer_receipt_utc']}; "
            f"to=#{end['sequence']} lux={end['lux']} "
            f"phone_sample={end['phone_sample_utc']} "
            f"consumer_receipt={end['consumer_receipt_utc']} "
            "freshness=fresh-clock-conditional; historical-measurement-only")


def new_light_transitions(state, now, stale):
    lights = [item for item in state["history"] if item["kind"] == "light"]
    last_sequence = state.get("last_light_sequence")
    prior_index = next((i for i, item in enumerate(lights)
                        if item["sequence"] == last_sequence), None)
    continuous = (state.get("last_light_event_cursor") ==
                  state.get("poll_start_cursor"))
    if not lights or not continuous or prior_index is None:
        state["last_light_sequence"] = lights[-1]["sequence"] if lights else None
        state["last_light_event_cursor"] = state["cursor"]
        return []
    transitions = []
    for previous, current in zip(lights[prior_index:], lights[prior_index + 1:]):
        event = light_bucket_transition(state, previous, current, now, stale)
        if event:
            transitions.append(event)
    # Advance the watermark past every examined pair: a pair already checked
    # must not be re-examined (and re-emitted) on later polls while it stays
    # fresh. Without this the normal branch re-emitted the same transition on
    # every poll until the older sample went stale.
    state["last_light_sequence"] = lights[-1]["sequence"]
    state["last_light_event_cursor"] = state["cursor"]
    return transitions

def update_events(state, now, stale):
    key = compact_key(state, now, stale)
    changed = key != state["event_key"]
    if changed:
        state["event_key"] = key
        rssi_status, rssi_dbm, rssi_reason, rssi_source = key[6]
        rssi_text = (f"wifi_link_rssi={rssi_status} rssi_dbm={rssi_dbm} "
                     f"reason={rssi_reason or 'unspecified'} "
                     f"source={rssi_source or 'unknown'}")
        (ble_status, ble_source, ble_api, ble_surface, feature, adapter,
         scanner, advertiser, scanner_getter, advertiser_getter, supported, errors) = key[7]
        ble_text = (f"bluetooth_le={ble_status} source={ble_source or 'unknown'} "
                    f"api={ble_api or 'unknown'} surface={ble_surface or 'unknown'} "
                    f"feature={feature or 'unknown'} adapter={adapter or 'unknown'} "
                    f"scanner={scanner or 'unknown'} advertiser={advertiser or 'unknown'} "
                    f"scanner_getter={scanner_getter or 'unknown'} "
                    f"advertiser_getter={advertiser_getter or 'unknown'} "
                    f"advertiser_supported={supported or 'unknown'} "
                    f"errors={dict(errors)}")
        summary = (f"{stamp(now)} {state['node']} phone={key[0]} transport={key[1]} "
                   f"battery={key[4][0][1:]} light={key[4][1][1:]} "
                   f"acceleration={key[4][2][1:]} {rssi_text} {ble_text} "
                   f"ble_sighting={key[8][0]}/{key[8][4] or 'unknown'} rssi_dbm={key[8][2] if key[8][2] is not None else 'unknown'} "
                   f"caps={state['capabilities']} action_receipts={len(state['actions'])}")
        state["events"].append(summary)
    transitions = new_light_transitions(state, now, stale)
    for event in transitions:
        state["last_light_transition"] = event
        state["events"].append(transition_text(event, state["node"]))
    state["events"] = state["events"][-EVENTS:]
    return changed or bool(transitions)


def stamp(value):
    if value is None:
        return "unknown"
    try:
        return datetime.datetime.fromtimestamp(value, datetime.timezone.utc).isoformat(timespec="seconds")
    except (ValueError, OverflowError, OSError):
        return "out-of-range"


def describe(item, now, stale):
    delayed = item["collected"] is not None and item["received"] - item["collected"] > stale
    return (f"#{item['sequence']} {item['raw']} | phone_sample/event={stamp(item['collected'])} "
            f"consumer_receipt={stamp(item['received'])} delayed_at_receipt={str(delayed).lower()}")


def render(state, now, stale, node_state=None):
    lines = [f"NODE {state['node']} source={state['source']} cursor={state['cursor']}",
             f"phone={state.get('node_status') or node_status(state, now, stale)} transport={transport(state, now, stale)} "
             f"backlog_page_pending={str(state['has_more']).lower()} last_poll={stamp(state['poll_at'])}",
             "capabilities: " + " ".join(f"{key}={state['capabilities'].get(key, 'unknown')}" for key in CAPABILITIES)]
    state_line = node_state_line(node_state)
    if state_line is not None:
        lines.append(state_line)
    lines.append("owner checkboxes: " + " ".join(
        f"{key}={state['owner_checkboxes'].get(key, 'unknown')}" for key in OWNER_CHECKBOXES))
    lines.append("compact: caps=" +
                 ",".join(f"{cap}:{state['capabilities'].get(cap, 'unknown')}" for cap in CAPABILITIES) +
                 " owner=" +
                 ",".join(f"{name}:{state['owner_checkboxes'].get(name, 'unknown')}"
                          for name in OWNER_CHECKBOXES))
    span_stats = acquisition_span_stats(state)
    lines.append("raw units: battery level=fraction, light lux=lux, acceleration x/y/z=m/s²; "
                 + clock_agreement_reason(span_stats) +
                 "; receipt is consumer fetch, not server receipt")
    for kind in SENSORS:
        item = state["latest"].get(kind)
        lines.append(f"{kind} [{sensor_status(item, now, stale)}]: " +
                     (describe(item, now, stale) if item else "unknown; no observation"))
    rssi = state["latest"].get("wifi_link_rssi_dbm")
    lines.append("Wi-Fi link RSSI (connected-link API observation; not room proximity):")
    lines.append("  status=" + wifi_rssi_status(rssi, now, stale) +
                 ("; " + describe(rssi, now, stale) if rssi else
                  "; unknown; no observation"))
    lines.append("  observed_at is API read time; acquisition age=unknown")
    ble = state["latest"].get("ble_status")
    ble_view = ble_status_snapshot(ble, now, stale)
    lines.append("Bluetooth LE status (scanner_api/advertiser_api are SDK API surface only; "
                 "not device or RF availability; no scan/advertise performed):")
    lines.append(f"  status={ble_view['status']} " +
                 (describe(ble, now, stale) if ble else "unknown; no observation"))
    lines.append(f"  api_surface={ble_view['api_surface'] or 'unknown'} "
                 "(SDK surface only; not usable hardware)")
    lines.append("  scanner_getter/advertiser_getter report accessor outcomes only; "
                 "returned is not scan/advertising success or RF evidence")
    lines.append("  " + " ".join(
        f"{key}={ble_view[key] if ble_view[key] is not None else 'unknown'}"
        for key in BLE_STATES))
    sighting = state["latest"].get("ble_sighting")
    scan = state["latest"].get("ble_scan")
    sighting_view = ble_sighting_snapshot(sighting, now, stale)
    scan_view = ble_scan_snapshot(scan, now, stale, _ble_scan_consecutive_error_count(state))
    lines.append("Bluetooth LE sightings (allowlisted-beacon scanner-visible evidence; "
                 "NOT presence, occupancy or proximity proof):")
    if sighting:
        lines.append(f"  status={sighting_view['status']} " +
                     describe(sighting, now, stale))
    else:
        lines.append("  status=unknown/no-observation")
    lines.append("  sightings_in_history_window=" +
                 str(sum(1 for item in state["history"]
                         if item["kind"] == "ble_sighting")) +
                 " (bounded window; count is not a rate or duration)")
    lines.append(f"  scan_lifecycle status={scan_view['status']} "
                 f"latest={scan_view['subtype'] or 'unknown'} "
                 f"reason={scan_view['reason'] or 'unspecified'}")
    lines.append("  scans run in bounded windows with idle gaps; lifecycle age bounds "
                 "interpretation of the latest event")
    if scan_view.get("consecutive_errors"):
        lines.append(f"  consecutive_errors={scan_view['consecutive_errors']} "
                     "(session count of back-to-back scan error events)")
    stillness = stillness_snapshot(state, now, stale)
    lines.append("Composite stillness (joint variance of accel magnitude + light + wifi RSSI):")
    lines.append(f"  status={stillness['status']} basis={stillness['basis']}")
    if stillness.get("accel"):
        lines.append(f"  accel_std={stillness['accel']['std']:.3f} m/s² (n={stillness['accel']['count']})")
    if stillness.get("light"):
        lines.append(f"  light_std={stillness['light']['std']:.3f} lux (n={stillness['light']['count']})")
    if stillness.get("wifi_rssi"):
        lines.append(f"  rssi_std={stillness['wifi_rssi']['std']:.3f} dBm (n={stillness['wifi_rssi']['count']})")
    if stillness.get("stale_sensors"):
        lines.append(f"  stale_sensors={','.join(stillness['stale_sensors'])} "
                     "(history window contains pre-frozen samples; std not computed)")
    lines.append(f"  consumer={stillness['consumer']}")
    guard = accel_guard(state.get("history", []))
    median_text = ("null" if guard["magnitude_median"] is None
                   else f"{guard['magnitude_median']:.3f}")
    std_text = ("null" if guard["magnitude_std"] is None
                else f"{guard['magnitude_std']:.3f}")
    lines.append("Accel guard (retained window; calibration-free, baseline-step-immune):")
    lines.append(f"  status={guard['status']} samples={guard['samples']} "
                 f"pinned_axes={','.join(guard['pinned_axes']) or 'null'} "
                 f"magnitude_median={median_text} m/s² magnitude_std={std_text} m/s² "
                 f"(g={guard['gravity']}, tolerance={guard['tolerance']}, "
                 f"stability<{guard['stability']})")
    if guard["indeterminate"]:
        lines.append("  accel leg indeterminate: no stillness or movement claim from accel; "
                     "magnitude is not a motion or occupancy proof")
    acceleration = state["latest"].get("acceleration")
    norm = magnitude(acceleration)
    if norm is not None and sensor_status(acceleration, now, stale) == "fresh-clock-conditional":
        lines.append(f"derived: acceleration magnitude={norm:.3f} m/s² = sqrt(x²+y²+z²), "
                     f"evidence=#{acceleration['sequence']}; includes gravity, not motion/occupancy proof")
    else:
        lines.append("derived: acceleration magnitude unknown/currently unusable; no substituted values")
    lines.append("action receipts (API return is not physical verification):")
    lines.extend("  " + describe(item, now, stale) for item in state["actions"])
    if not state["actions"]:
        lines.append("  unknown; no receipts observed")
    extras = [item for kind, item in state["latest"].items() if kind not in SENSORS and kind != "action"]
    lines.append("other latest events (raw fields preserved; bounded history in state):")
    lines.extend("  " + describe(item, now, stale) for item in extras)
    return "\n".join(lines)


def render_events(state, now, stale, node_state=None):
    # Recompute this heading even if the follower died; never label cached data current.
    key = compact_key(state, now, stale)
    lines = [f"{state['node']} source={state['source']} phone={key[0]} "
             f"transport={key[1]} caps=" +
             ",".join(f"{cap}:{state['capabilities'].get(cap, 'unknown')}" for cap in CAPABILITIES) +
             " owner=" +
             ",".join(f"{name}:{state['owner_checkboxes'].get(name, 'unknown')}"
                      for name in OWNER_CHECKBOXES)]
    state_line = node_state_line(node_state)
    if state_line is not None:
        lines.append("  " + state_line)
    rssi_status, rssi_dbm, rssi_reason, rssi_source = key[6]
    lines.append(f"  wifi_link_rssi {rssi_status} rssi_dbm={rssi_dbm} "
                 f"reason={rssi_reason or 'unspecified'} source={rssi_source or 'unknown'}")
    (ble_status, ble_source, ble_api, ble_surface, feature, adapter,
     scanner, advertiser, scanner_getter, advertiser_getter, supported, errors) = key[7]
    lines.append(
        f"  bluetooth_le {ble_status} source={ble_source or 'unknown'} "
        f"api={ble_api or 'unknown'} surface={ble_surface or 'unknown'} "
        f"feature={feature or 'unknown'} adapter={adapter or 'unknown'} "
        f"scanner={scanner or 'unknown'} advertiser={advertiser or 'unknown'} "
        f"scanner_getter={scanner_getter or 'unknown'} "
        f"advertiser_getter={advertiser_getter or 'unknown'} "
        f"advertiser_supported={supported or 'unknown'} errors={dict(errors)}")
    (sighting_status, sighting_name, sighting_rssi,
     scan_status, scan_subtype, scan_reason) = key[8]
    lines.append(f"  ble_sighting {sighting_status} name={sighting_name or 'unknown'} "
                 f"rssi_dbm={sighting_rssi if sighting_rssi is not None else 'unknown'} "
                 f"scan={scan_status}/{scan_subtype or 'unknown'} "
                 f"reason={scan_reason or 'unspecified'}")
    lines.extend("  " + event for event in state["events"][-4:])
    if state["actions"]:
        lines.append("  receipt: " + state["actions"][-1]["raw"])
    return "\n".join(lines)



def acquisition_span_stats(state):
    """Bound phone/host clock skew from retained receipt spans.

    received - collected = transport latency + (host wall - phone wall), and
    latency is non-negative, so the smallest observed span bounds how far
    behind the host clock the phone clock can be. The skew/latency split
    stays unknown and the bound covers only the retained window.
    """
    spans = [round((item["received"] - item["collected"]) * 1000, 1)
             for item in state.get("history", [])
             if item.get("collected") is not None]
    if not spans:
        return None
    ordered = sorted(spans)
    middle = len(ordered) // 2
    median = (ordered[middle] if len(ordered) % 2 else
              round((ordered[middle - 1] + ordered[middle]) / 2, 1))
    return {"min_ms": min(spans), "max_ms": max(spans),
            "median_ms": median, "n": len(spans)}


def clock_agreement_reason(span_stats):
    if span_stats is None:
        return "phone/host clock agreement is unverified"
    return ("phone/host clock skew <=%.0fms behind host (acquisition span "
            "%.0f-%.0fms, n=%d retained); skew/latency split unknown"
            % (span_stats["min_ms"], span_stats["min_ms"],
               span_stats["max_ms"], span_stats["n"]))

def space_snapshot(states, now, stale):
    nodes = []
    for state in states:
        item = state["latest"].get("light")
        status = ("backlog/draining" if state["has_more"]
                  else sensor_status(item, now, stale))
        fields = item["fields"] if item else {}
        phone_elapsed = phone_elapsed_realtime(item)
        phone_elapsed_reason = (
            "no-light-observation" if item is None else
            "not provided by protocol v1" if "phone_elapsed_ms" not in fields else
            None if phone_elapsed is not None else
            "invalid phone_elapsed_ms value")
        acquisition_span = (round((item["received"] - item["collected"]) * 1000, 1)
                            if item and item["collected"] is not None else None)
        span_stats = acquisition_span_stats(state)
        real_age_upper_bound_ms = (round(acquisition_span - span_stats["min_ms"], 1)
                                   if acquisition_span is not None and span_stats else None)
        is_fresh_at_host = (real_age_upper_bound_ms / 1000 < stale
                            if real_age_upper_bound_ms is not None else None)
        nodes.append({
            "node": state["node"], "source": state["source"], "session": state["session"],
            "cursor": state["cursor"], "phone_status": state.get("node_status") or node_status(state, now, stale),
            "transport": transport(state, now, stale), "last_error": state["error"],
            "last_poll_utc": stamp(state["poll_at"]),
            "backlog_page_pending": state["has_more"],
            "capabilities": {key: state["capabilities"].get(key, "unknown")
                             for key in CAPABILITIES},
            "owner_checkboxes": dict(state.get("owner_checkboxes") or {}),
            "wifi_link_rssi": wifi_rssi_snapshot(
                state["latest"].get("wifi_link_rssi_dbm"), now, stale),
            "bluetooth_le": ble_status_snapshot(
                state["latest"].get("ble_status"), now, stale),
            "ble_sighting": ble_sighting_snapshot(
                state["latest"].get("ble_sighting"), now, stale),
            "ble_scan": ble_scan_snapshot(
                state["latest"].get("ble_scan"), now, stale,
                _ble_scan_consecutive_error_count(state)),
            "stillness": stillness_snapshot(state, now, stale),
            "light": {
                "status": status,
                "status_reason": (fields.get("reason") or
                                  ("no-light-observation" if item is None else
                                   status if status != "fresh-clock-conditional" else
                                   clock_agreement_reason(span_stats))),
                "freshness_basis": "host receipt time; phone event time and age_ms retained for provenance",
                "validity_seconds": stale,
                "sequence": item["sequence"] if item else None,
                "lux": number(fields, "lux") if status == "fresh-clock-conditional" else None,
                "units": "lux", "accuracy": fields.get("accuracy") if item else None,
                "age_ms_at_phone_collection": number(fields, "age_ms") if item else None,
                "real_age_upper_bound_ms": real_age_upper_bound_ms,
                "is_fresh_at_host": is_fresh_at_host,
                "phone_sample_epoch_s": item["collected"] if item else None,
                "phone_sample_utc": stamp(item["collected"]) if item else None,
                "consumer_receipt_epoch_s": item["received"] if item else None,
                "sensor_time": sensor_time_scope(item, state["session"]) if item else None,
                "sensor_time_reason": (
                    "missing/invalid timestamp or session; incomparable"
                    if item and sensor_time_scope(item, state["session"]) is None
                    else None),
                "consumer_receipt_utc": stamp(item["received"]) if item else None,
                "delayed_at_receipt": (item["received"] - item["collected"] > stale)
                                      if item and item["collected"] is not None else None,
                "phone_elapsed_realtime_ms": phone_elapsed,
                "phone_elapsed_realtime_reason": phone_elapsed_reason,
                "host_receipt_monotonic_ns": item.get("host_receipt_monotonic_ns")
                                           if item else None,
                "host_boot_id": item.get("host_boot_id") if item else None,
                "host_boot_id_reason": ("no-light-observation" if item is None else
                                        "receipt metadata not recorded"
                                        if "host_boot_id" not in item else
                                        None if item["host_boot_id"] else
                                        "host boot id unreadable"),
                "server_receipt_utc": None,
                "server_receipt_utc_reason": (
                    "no-light-observation" if item is None else
                    "not provided by protocol v1"),
                "acquisition_span_ms": acquisition_span
            },
            "last_light_transition": state.get("last_light_transition")
        })
    return {"schema_version": 1, "generated_at_utc": stamp(now),
            "producer": {"name": "android-body-perception", "entry_point": "watch.py",
                         "mode": "space", "contract": 1},
            "nodes": nodes}


NODE_STATE_PREFIX = "node-state-"
NODE_STATE_MAX_AGE_SECONDS = 300.0
NODE_MODES = ("ON_SENDING", "ON_COLLECT_ONLY", "ON_NOT_RUNNING", "OFF", "UNKNOWN")
NODE_STATE_MAX_REASONS = 4
NODE_STATE_MAX_REASON_CHARS = 200


def state_paths(directory):
    """Perception state files only.

    The host-side node-state documents (tools/node_state.py) live in the same
    directory by contract (chat 75665); they are not perception states and must
    not be parsed as one.
    """
    if not directory.exists():
        return []
    return sorted(path for path in directory.glob("*.json")
                  if not path.name.startswith(NODE_STATE_PREFIX))


def _bounded_reasons(value):
    """Reasons from the node-state document, bounded to one printable line.

    The publisher (tools/node_state.py) already caps each reason, but the reader
    must not trust a future or foreign publisher: non-strings and blanks are
    dropped, whitespace is collapsed and non-printable characters (control,
    format, surrogate) are removed so a reason can neither forge extra view
    lines nor make the utf-8 state write raise, an over-long reason is
    truncated, and the list is capped.
    """
    if not isinstance(value, list):
        return []
    reasons = []
    for item in value:
        if not isinstance(item, str):
            continue
        printable = "".join(
            " " if ch.isspace() else ch for ch in item
            if ch.isspace() or ch.isprintable())
        text = " ".join(printable.split())
        if not text:
            continue
        if len(text) > NODE_STATE_MAX_REASON_CHARS:
            text = text[:NODE_STATE_MAX_REASON_CHARS - 3] + "..."
        reasons.append(text)
        if len(reasons) >= NODE_STATE_MAX_REASONS:
            break
    return reasons


def read_node_state(directory, node, now, max_age=NODE_STATE_MAX_AGE_SECONDS):
    """Read the bounded host-side node-state file for one node.

    Returns mode "UNKNOWN" with status absent/stale/invalid when the file is
    missing, unreadable, malformed, names another node, or is older than
    ``max_age``. A failed or stale read is never OFF: only an explicit OFF the
    publisher wrote is reported as OFF.
    """
    def unknown(status, reason):
        return {"status": status, "mode": "UNKNOWN", "desired_on": None,
                "collect_only": None, "observed_at_epoch_s": None,
                "age_s": None, "reason": reason, "reasons": []}

    path = directory / f"{NODE_STATE_PREFIX}{node}.json"
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return unknown("absent", "no-node-state-file")
    except (OSError, ValueError):
        return unknown("invalid", "node-state-unreadable")
    if (not isinstance(document, dict) or document.get("node") != node
            or document.get("mode") not in NODE_MODES):
        return unknown("invalid", "node-state-invalid")
    observed = document.get("observed_at_epoch_s")
    if (not isinstance(observed, (int, float)) or isinstance(observed, bool)
            or not math.isfinite(observed)):
        return unknown("invalid", "node-state-invalid")
    age = now - observed
    if age > max_age:
        return unknown("stale", "node-state-stale")
    desired = document.get("desired_on")
    collect = document.get("collect_only")
    return {"status": "ok", "mode": document["mode"],
            "desired_on": desired if isinstance(desired, bool) else None,
            "collect_only": collect if isinstance(collect, bool) else None,
            "observed_at_epoch_s": observed,
            "age_s": round(max(age, 0.0), 1),
            "reason": None,
            "reasons": _bounded_reasons(document.get("reasons"))}


def node_state_line(node_state):
    """One human-readable line for the node-state verdict, or None without one."""
    if node_state is None:
        return None
    if node_state["status"] != "ok":
        return (f"node state (host-side, tools/node_state.py): mode=UNKNOWN "
                f"status={node_state['status']} reason={node_state['reason']} "
                f"(unknown is never OFF)")

    def flag(value):
        return "unknown" if value is None else str(value).lower()

    line = (f"node state (host-side, tools/node_state.py): mode={node_state['mode']} "
            f"desired_on={flag(node_state['desired_on'])} "
            f"collect_only={flag(node_state['collect_only'])} "
            f"observed={stamp(node_state['observed_at_epoch_s'])} "
            f"age={node_state['age_s']}s status=ok")
    reasons = node_state.get("reasons") or []
    if reasons:
        line += " reasons=" + "; ".join(reasons)
    return line


def read_space(directory, now, stale):
    paths = state_paths(directory)
    if not paths:
        return {"schema_version": 1, "generated_at_utc": stamp(now),
                "producer": {"name": "android-body-perception", "entry_point": "watch.py",
                             "mode": "space", "contract": 1},
                "nodes": [], "status": "unknown/no-perception-state"}
    return space_snapshot([load(path) for path in paths], now, stale)


def render_space(directory, now, stale):
    return json.dumps(read_space(directory, now, stale), ensure_ascii=False,
                      allow_nan=False, sort_keys=True) + "\n"
class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def endpoint(url):
    parsed = urllib.parse.urlsplit(url)
    if (parsed.scheme not in ("http", "https") or not parsed.hostname or parsed.username or
            parsed.password or parsed.query or parsed.fragment or parsed.path not in ("", "/")):
        raise ValueError("URL must be an HTTP(S) rendezvous root without credentials/query/fragment")
    if parsed.scheme == "http":
        try:
            local = ipaddress.ip_address(parsed.hostname).is_loopback
        except ValueError:
            local = parsed.hostname == "localhost"
        if not local:
            raise ValueError("cleartext consumer access is restricted to loopback; use HTTPS remotely")
    return url.rstrip("/")


def poll(opener, state, secret, timeout, log_dir=None):
    request = urllib.request.Request(
        f"{state['source']}/observations?after={state['cursor']}",
        headers={"Authorization": "Bearer " + secret, "Accept": "text/plain"})
    with opener.open(request, timeout=timeout) as response:
        if response.status != 200:
            raise ValueError("unexpected HTTP status")
        body = response.read(65537)
        more = response.headers.get("X-Has-More", "0")
        if more not in ("0", "1"):
            raise ValueError("invalid pagination header")
        records = parse_page(body, state["cursor"])
        if more == "1" and not records:
            raise ValueError("empty pending page")
    apply_page(state, records, time.time(), more == "1", log_dir=log_dir)


def read_views(directory, now, stale, compact=False):
    paths = state_paths(directory)
    if not paths:
        return "UNKNOWN: no perception state; follower has not received evidence\n"
    view = render_events if compact else render
    parts = []
    for path in paths:
        state = load(path)
        parts.append(view(state, now, stale,
                          read_node_state(directory, state["node"], now)))
    parts.append(light_resumption_view(now, stale, compact))
    return "\n\n".join(parts) + "\n"


def publish_space(directory, nodes, now, stale):
    path = directory.parent / "space.json"
    content = render_space(directory, now, stale)
    if not path.exists() or path.read_text(encoding="utf-8") != content:
        atomic(path, content)


def follow(args, directory):
    root = endpoint(args.url)
    nodes = []
    seen = set()
    for spec in args.node:
        node, separator, variable = spec.partition(":")
        if (not separator or not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,63}", node) or
                not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", variable) or node in seen):
            raise ValueError("--node must be unique NODE:SECRET_ENV_NAME")
        secret = os.environ.get(variable, "")
        if not re.fullmatch(r"[A-Za-z0-9._~-]{32,256}", secret):
            raise ValueError(f"missing or invalid credential environment variable {variable}")
        seen.add(node)
        path = directory / (node + ".json")
        nodes.append((path, load(path, node, root + "/node/" + node), secret))
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    running = True

    def stop(signum, frame):
        nonlocal running
        running = False

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    with (directory / "follow.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        for path, state, _ in nodes:
            if not path.exists():
                save(path, state)
        publish_space(directory, nodes, time.time(), args.stale_seconds)
        while running:
            for path, state, secret in nodes:
                if not running:
                    break
                try:
                    poll(opener, state, secret, args.timeout, log_dir=directory)
                except urllib.error.HTTPError as error:
                    state.update(poll_at=time.time(), error=f"http-{error.code}")
                except (urllib.error.URLError, TimeoutError, OSError):
                    state.update(poll_at=time.time(), error="network-error")
                except (ValueError, UnicodeError):
                    state.update(poll_at=time.time(), error="invalid-response")
                now = time.time()
                changed = update_events(state, now, args.stale_seconds)
                state["node_status"] = node_status(state, now, args.stale_seconds)
                save(path, state)
                detection = detect_class_b_delivery_gap(
                    state, directory, read_node_state(directory, state["node"], now))
                if detection:
                    print(f"class-b-delivery-gap: {detection}", flush=True)
                detection_a = detect_class_a_freeze(state, directory)
                if detection_a:
                    print(f"class-a-freeze: {detection_a}", flush=True)
                detection_c = detect_class_c_delivery_gap(state, directory)
                if detection_c:
                    print(f"class-c-delivery-gap: {detection_c}", flush=True)
                if changed:
                    print(state["events"][-1], flush=True)
                # Publish each durable node result before polling the next node.
                # A slow later request must not hide an earlier node's new error.
                publish_space(directory, nodes, time.time(), args.stale_seconds)
            now = time.time()
            atomic(directory / "view.txt", read_views(directory, now, args.stale_seconds))
            compact = read_views(directory, now, args.stale_seconds, compact=True)
            cached = directory / "events.txt"
            if not cached.exists() or cached.read_text(encoding="utf-8") != compact:
                atomic(cached, compact)
            # Bounded one page per node per cycle; backlog cannot starve another node.
            until = time.monotonic() + args.poll_seconds
            while running and time.monotonic() < until:
                time.sleep(min(0.2, max(0, until - time.monotonic())))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("follow", "view", "events", "space"))
    parser.add_argument("--site", type=Path, required=True)
    parser.add_argument("--url", default="http://127.0.0.1:8765")
    parser.add_argument("--node", action="append", default=[], metavar="NODE:SECRET_ENV_NAME")
    parser.add_argument("--poll-seconds", type=float, default=2)
    parser.add_argument("--timeout", type=float, default=5)
    parser.add_argument("--stale-seconds", type=float, default=30)
    args = parser.parse_args()
    if not all(math.isfinite(value) and value > 0 for value in
               (args.poll_seconds, args.timeout, args.stale_seconds)):
        parser.error("timings must be finite and positive")
    directory = args.site / "body" / "perception"
    try:
        if args.mode == "follow":
            if not args.node:
                parser.error("follow requires at least one --node")
            follow(args, directory)
        elif args.mode == "space":
            print(render_space(directory, time.time(), args.stale_seconds), end="")
        else:
            print(read_views(directory, time.time(), args.stale_seconds,
                             args.mode == "events"), end="")
    except (OSError, ValueError, KeyError, TypeError) as error:
        parser.exit(1, f"perception: {error}\n")


if __name__ == "__main__":
    main()
