#!/usr/bin/env python3
"""Monitor Note3 light channel for cycle resumption (0 -> >0 lux transition).

Bounded: polls space.json every 30s, logs to light-cycle-resumed.jsonl, exits
on transition or after --max-polls. No physical actions, no phone mutation.
"""
import argparse
import json
import time
from pathlib import Path

SPACE_JSON = Path(__file__).resolve().parents[2] / ".mishe-tauftauf" / "body" / "space.json"
LOG_FILE = Path(__file__).resolve().parent / "artifacts" / "light-cycle-resumed.jsonl"

DARK_PHASE_LUX_MAX = 0.5


def read_light_lux():
    """Read current Note3 light lux from deployed space.json. None on error."""
    try:
        data = json.loads(SPACE_JSON.read_text())
        for node in data.get("nodes", []):
            if node.get("node") == "note3":
                light = node.get("light", {})
                if light.get("status") == "fresh-clock-conditional":
                    return light.get("lux")
    except (OSError, json.JSONDecodeError, KeyError, TypeError):
        pass
    return None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--interval", type=float, default=30.0, help="Seconds between polls")
    parser.add_argument("--max-polls", type=int, default=240, help="Max polls (240 = 2h at 30s)")
    args = parser.parse_args()

    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    prev_lux = None

    for poll in range(args.max_polls):
        lux = read_light_lux()
        now = time.time()

        if (lux is not None and lux > DARK_PHASE_LUX_MAX and
                (prev_lux is None or prev_lux <= DARK_PHASE_LUX_MAX)):
            record = {
                "event": "light-cycle-resumed",
                "lux": lux,
                "prev_lux": prev_lux,
                "poll": poll,
                "timestamp_unix": now,
            }
            with open(LOG_FILE, "a") as f:
                f.write(json.dumps(record, sort_keys=True) + "\n")
            print(f"RESUMED lux={lux} prev={prev_lux} poll={poll}")
            return 0

        if lux is not None:
            prev_lux = lux

        time.sleep(args.interval)

    print(f"NO_RESUMPTION after {args.max_polls} polls")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
