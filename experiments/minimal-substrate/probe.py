#!/usr/bin/env python3
# SPDX-License-Identifier: CC0-1.0
"""Bounded read-only probe runner — minimal-substrate first experiment.

A retained trivial text script for the minimal-substrate investigation: a
fixed allowlist of harmless read-only adb shell probes against the owned
Note3. PROBES below is the whole execution surface — no arbitrary command
execution, no device mutation, no radio/camera/mic/location, no persistent
state. Running the script is the only ON; not running is OFF; nothing
survives the process except bounded artifact files.

Bounds (env-overridable; tests rely on this):
  MINIMAL_SUBSTRATE_TIMEOUT_S  per-command timeout in seconds; on expiry the
                               child is killed and the timeout is recorded
                               truthfully (default 10)
  MINIMAL_SUBSTRATE_MAX_BYTES   per-probe output cap in bytes (default 65536)
  MINIMAL_SUBSTRATE_KEEP        retention: newest N artifact files
                               (default 20; N<=0 keeps none)

The fixed allowlist also bounds what a probe can emit: only these three
small dumpsys/date outputs can be captured, so capture memory is bounded
structurally and the byte cap bounds what is retained per probe.

Usage: python3 probe.py [identity|environment|clock|all]
Exit:  0 all probes ok · 1 any probe timed out or errored · 2 usage error
"""

import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ARTIFACT_DIR = Path(__file__).resolve().parent / "artifacts"

PROBES = {
    "identity": ["shell", "dumpsys", "package", "org.androidbody"],
    "environment": ["shell", "dumpsys", "sensorservice"],
    "clock": ["shell", "date", "-u", "+%Y-%m-%dT%H:%M:%SZ"],
}

TIMEOUT_S = max(0.1, float(os.environ.get("MINIMAL_SUBSTRATE_TIMEOUT_S", "10")))
MAX_BYTES = max(1, int(os.environ.get("MINIMAL_SUBSTRATE_MAX_BYTES", str(64 * 1024))))
KEEP = max(0, int(os.environ.get("MINIMAL_SUBSTRATE_KEEP", "20")))


def _utcnow():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _cap(text):
    """Byte-bound truncation: retained output never exceeds MAX_BYTES bytes."""
    encoded = text.encode("utf-8", errors="replace")
    if len(encoded) <= MAX_BYTES:
        return text
    truncated = encoded[:MAX_BYTES].decode("utf-8", errors="replace")
    return truncated + "\n...[truncated at {0} bytes]".format(MAX_BYTES)


def run_probe(name):
    args = ["adb", *PROBES[name]]
    started = time.monotonic()
    record = {
        "name": name,
        "command": " ".join(args),
        "started_utc": _utcnow(),
        "duration_s": None,
        "outcome": None,
        "returncode": None,
        "output": None,
    }
    try:
        proc = subprocess.run(
            args, capture_output=True, text=True, errors="replace",
            timeout=TIMEOUT_S,
        )
    except subprocess.TimeoutExpired as exc:
        record["duration_s"] = round(time.monotonic() - started, 3)
        record["outcome"] = "timeout"
        note = "timeout after {0}s; child killed; no retry".format(TIMEOUT_S)
        if exc.output:
            note += "; partial output before kill:\n" + _cap(exc.output)
        record["output"] = note
        return record
    except OSError as exc:
        record["duration_s"] = round(time.monotonic() - started, 3)
        record["outcome"] = "error"
        record["output"] = "probe execution failed: {0}".format(exc)
        return record
    record["duration_s"] = round(time.monotonic() - started, 3)
    record["returncode"] = proc.returncode
    output = proc.stdout or ""
    if proc.stderr:
        output += "\n[stderr] " + proc.stderr.strip()
    record["output"] = _cap(output)
    record["outcome"] = "ok" if proc.returncode == 0 else "error"
    return record


def write_artifact(records, argv):
    ARTIFACT_DIR.mkdir(exist_ok=True)
    payload = {
        "schema": 1,
        "runner": "experiments/minimal-substrate/probe.py",
        "started_utc": records[0]["started_utc"] if records else _utcnow(),
        "finished_utc": _utcnow(),
        "argv": argv,
        "outcome": "ok" if all(r["outcome"] == "ok" for r in records) else "error",
        "bounds": {"timeout_s": TIMEOUT_S, "max_bytes": MAX_BYTES, "keep": KEEP},
        "probes": records,
    }
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    path = ARTIFACT_DIR / ("probes-{0}.json".format(stamp))
    tmp = ARTIFACT_DIR / (path.name + ".tmp")
    try:
        tmp.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        os.replace(tmp, path)
    except Exception:
        tmp.unlink(missing_ok=True)
        raise
    return path


def enforce_retention():
    files = sorted(ARTIFACT_DIR.glob("probes-*.json"))
    keep = max(KEEP, 0)
    if keep == 0:
        for old in files:
            old.unlink()
        return
    for old in files[:-keep] if len(files) > keep else []:
        old.unlink()


def main(argv):
    if len(argv) != 1 or (argv[0] not in PROBES and argv[0] != "all"):
        print(__doc__)
        return 2
    names = list(PROBES) if argv[0] == "all" else [argv[0]]
    records = [run_probe(name) for name in names]
    path = write_artifact(records, argv)
    enforce_retention()
    for record in records:
        print("{0}: {1} ({2}s) -> {3}".format(
            record["name"], record["outcome"], record["duration_s"], path))
    return 0 if all(r["outcome"] == "ok" for r in records) else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
