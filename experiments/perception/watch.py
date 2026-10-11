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

MAX_SEQUENCE = 9007199254740991
HISTORY = 32
EVENTS = 16
SENSORS = ("battery", "light", "acceleration")
CAPABILITIES = ("battery", "light", "accelerometer", "vibration", "wifi_link_rssi", "bluetooth_le")

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
            "session": None, "capabilities": {}, "latest": {}, "history": [],
            "actions": [], "events": [], "event_key": None, "last_light_sequence": None,
            "last_light_transition": None, "last_light_event_cursor": None,
            "poll_start_cursor": 0, "poll_at": None, "ok_at": None,
            "error": None, "has_more": False}


def load(path, node=None, source=None):
    if not path.exists():
        return initial(node, source)
    state = json.loads(path.read_text(encoding="utf-8"))
    if state["version"] != 1 or not 0 <= state["cursor"] <= MAX_SEQUENCE:
        raise ValueError("unsupported or corrupt perception state")
    if node is not None and (state["node"] != node or state["source"] != source):
        raise ValueError("state belongs to a different endpoint; reconcile explicitly")
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
            "backlog_page_pending_at_receipt": backlog_pending}


def apply_page(state, records, received, has_more):
    state["poll_start_cursor"] = state["cursor"]
    for sequence, raw in records:
        item = record(sequence, raw, received, has_more)
        words = raw.split(" ")
        kind = item["kind"]
        if kind == "hello":
            session = item["fields"].get("session")
            if session != state["session"]:
                state["capabilities"] = {}
                state["latest"] = {}
                state["history"] = []
                state["session"] = session
                state["last_light_sequence"] = None
                state["last_light_transition"] = None
        if kind == "cap" and len(words) >= 3:
            if words[2] in CAPABILITIES:
                state["capabilities"][words[2]] = "present"
        elif kind in ("sensor", "actuator") and len(words) >= 4 and words[3] == "absent":
            if words[2] in CAPABILITIES:
                state["capabilities"][words[2]] = "absent"
        if kind == "action":
            state["actions"].append(item)
            state["actions"] = state["actions"][-EVENTS:]
        # Retain raw unknown names/fields, with a bounded latest-kind map and history.
        state["latest"].pop(kind, None)
        state["latest"][kind] = item
        if len(state["latest"]) > 32:
            del state["latest"][next(iter(state["latest"]))]
        state["history"].append(item)
        state["history"] = state["history"][-HISTORY:]
        state["cursor"] = sequence
    state.update(poll_at=received, ok_at=received, error=None, has_more=has_more)


def number(fields, key):
    try:
        value = float(fields[key])
        return value if math.isfinite(value) else None
    except (KeyError, ValueError):
        return None


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


def freshness(item, now, stale):
    if item is None or item["collected"] is None:
        return "unknown"
    age = now - item["collected"]
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

STILLNESS_ACCEL_STD = 0.5
STILLNESS_LIGHT_STD = 0.1
STILLNESS_RSSI_STD = 2.0
STILLNESS_MIN_SAMPLES = 2


def stillness_snapshot(state, now, stale):
    """Composite stillness from joint variance of accel magnitude, light, wifi RSSI."""
    history = state.get("history", [])
    accel_values = []
    light_values = []
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




def node_status(state, now, stale):
    """Node liveness with hysteresis against publish-cadence flap.

    Enter stale only when the latest sample age exceeds the threshold by
    NODE_STATUS_ENTER_MARGIN; return fresh only once it falls back below the
    threshold minus NODE_STATUS_EXIT_MARGIN. Sensor-level freshness semantics
    are unchanged; only the node label is damped. The follower persists the
    emitted label in node state so the next poll applies the margins.
    """
    if not state["history"]:
        return "unknown/no-observations"
    if state["has_more"]:
        return "backlog/draining"
    # Battery snapshots provide collection heartbeat even when on-change sensors are old.
    recent = [item for item in state["history"] if item["collected"] is not None]
    if not recent:
        return "unknown/no-phone-clock"
    latest = max(recent, key=lambda item: item["collected"])
    status = freshness(latest, now, stale)
    previous = state.get("node_status")
    if status == "stale":
        status = "stale/phone-silent-or-delayed"
    if status == "unknown-clock-future" or previous not in (
            "fresh-clock-conditional", "stale/phone-silent-or-delayed"):
        return status
    age = now - latest["collected"]
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
    return [node_status(state, now, stale), transport(state, now, stale),
            state["session"], dict(state["capabilities"]), measured, actions,
            rssi_key, ble_key]


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


def render(state, now, stale):
    lines = [f"NODE {state['node']} source={state['source']} cursor={state['cursor']}",
             f"phone={node_status(state, now, stale)} transport={transport(state, now, stale)} "
             f"backlog_page_pending={str(state['has_more']).lower()} last_poll={stamp(state['poll_at'])}",
             "capabilities: " + " ".join(f"{key}={state['capabilities'].get(key, 'unknown')}" for key in CAPABILITIES)]
    lines.append("raw units: battery level=fraction, light lux=lux, acceleration x/y/z=m/s²; "
                 "phone clocks are not synchronized; receipt is consumer fetch, not server receipt")
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
    stillness = stillness_snapshot(state, now, stale)
    lines.append("Composite stillness (joint variance of accel magnitude + light + wifi RSSI):")
    lines.append(f"  status={stillness['status']} basis={stillness['basis']}")
    if stillness.get("accel"):
        lines.append(f"  accel_std={stillness['accel']['std']:.3f} m/s² (n={stillness['accel']['count']})")
    if stillness.get("light"):
        lines.append(f"  light_std={stillness['light']['std']:.3f} lux (n={stillness['light']['count']})")
    if stillness.get("wifi_rssi"):
        lines.append(f"  rssi_std={stillness['wifi_rssi']['std']:.3f} dBm (n={stillness['wifi_rssi']['count']})")
    lines.append(f"  consumer={stillness['consumer']}")
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


def render_events(state, now, stale):
    # Recompute this heading even if the follower died; never label cached data current.
    key = compact_key(state, now, stale)
    lines = [f"{state['node']} source={state['source']} phone={key[0]} "
             f"transport={key[1]} caps=" +
             ",".join(f"{cap}:{state['capabilities'].get(cap, 'unknown')}" for cap in CAPABILITIES)]
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
    lines.extend("  " + event for event in state["events"][-4:])
    if state["actions"]:
        lines.append("  receipt: " + state["actions"][-1]["raw"])
    return "\n".join(lines)



def space_snapshot(states, now, stale):
    nodes = []
    for state in states:
        item = state["latest"].get("light")
        status = ("backlog/draining" if state["has_more"]
                  else sensor_status(item, now, stale))
        fields = item["fields"] if item else {}
        nodes.append({
            "node": state["node"], "source": state["source"], "session": state["session"],
            "cursor": state["cursor"], "phone_status": node_status(state, now, stale),
            "transport": transport(state, now, stale), "last_error": state["error"],
            "last_poll_utc": stamp(state["poll_at"]),
            "backlog_page_pending": state["has_more"],
            "capabilities": {key: state["capabilities"].get(key, "unknown")
                             for key in CAPABILITIES},
            "wifi_link_rssi": wifi_rssi_snapshot(
                state["latest"].get("wifi_link_rssi_dbm"), now, stale),
            "bluetooth_le": ble_status_snapshot(
                state["latest"].get("ble_status"), now, stale),
            "stillness": stillness_snapshot(state, now, stale),
            "light": {
                "status": status,
                "status_reason": (fields.get("reason") or
                                  ("no-light-observation" if item is None else
                                   status if status != "fresh-clock-conditional" else
                                   "phone/host clock agreement is unverified")),
                "validity_seconds": stale,
                "freshness_basis": "phone event time and age_ms compared with host clock",
                "sequence": item["sequence"] if item else None,
                "lux": number(fields, "lux") if status == "fresh-clock-conditional" else None,
                "units": "lux", "accuracy": fields.get("accuracy") if item else None,
                "age_ms_at_phone_collection": number(fields, "age_ms") if item else None,
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
                "phone_elapsed_realtime_ms": None,
                "phone_elapsed_realtime_reason": "not provided by protocol v1",
                "host_receipt_monotonic_ns": None,
                "host_boot_id": None,
                "server_receipt_utc": None,
                "acquisition_span_ms": None
            },
            "last_light_transition": state.get("last_light_transition")
        })
    return {"schema_version": 1, "generated_at_utc": stamp(now),
            "producer": {"name": "android-body-perception", "entry_point": "watch.py",
                         "mode": "space", "contract": 1},
            "nodes": nodes}


def read_space(directory, now, stale):
    paths = sorted(directory.glob("*.json")) if directory.exists() else []
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


def poll(opener, state, secret, timeout):
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
    apply_page(state, records, time.time(), more == "1")


def read_views(directory, now, stale, compact=False):
    paths = sorted(directory.glob("*.json")) if directory.exists() else []
    if not paths:
        return "UNKNOWN: no perception state; follower has not received evidence\n"
    view = render_events if compact else render
    return "\n\n".join(view(load(path), now, stale) for path in paths) + "\n"


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
                    poll(opener, state, secret, args.timeout)
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
