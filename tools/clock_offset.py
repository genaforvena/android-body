#!/usr/bin/env python3
# SPDX-License-Identifier: CC0-1.0
"""Publish a bounded phone/host clock-offset reading for the perception consumer.

The perception consumer bounds the phone/host clock skew from its retained
acquisition spans (``received - collected``) but cannot separate the two terms:
the span is ``transport latency + (host wall - phone wall)`` and latency is
non-negative, so the smallest span bounds the offset above and never resolves it.
That is why ``watch.py`` prints "skew/latency split unknown" (see
``clock_agreement_reason``).

This tool measures the offset directly, independently of delivery: it pairs the
phone's own wall clock (``adb shell date +%s``) with the host's (``time.time()``).
The result is a bounded reading with its own provenance, sample window, failure
state and validity, so the consumer can report the resolved split and any
wall-clock jump instead of an unresolvable bound.

Bounds, stated because they matter:

- ``adb shell date +%s`` prints whole seconds (``floor`` of the phone epoch), so a
  single pairing pins the true offset to a one-second interval:
  ``offset <= mid - phone_epoch`` and ``offset > mid - phone_epoch - 1``. The
  reported interval is the tightest intersection over the samples:
  ``offset_max_s = min(upper)``, ``offset_min_s = min(upper) - quantization_s``.
- ``mid`` is the midpoint of the host wall clock around the round trip, so the
  bound carries ``rtt_max_s / 2`` of extra uncertainty; it is published.
- The reading says nothing about which clock is *correct*. The host's NTP state is
  published as ``host_ntp_synchronized`` (best effort, ``null`` when unreadable),
  never as an assumption.

The document (exactly these keys, never the endpoint or the node secret):

    {"node": "note3",
     "source": "tools/clock_offset.py",
     "method": "adb-shell-date-minus-host-wall",
     "status": "ok|unavailable",
     "observed_at_epoch_s": 1791989019.5,
     "validity_seconds": 3600,
     "samples": 7,
     "quantization_s": 1.0,
     "rtt_max_s": 0.059,
     "offset_min_s": 24.175, "offset_max_s": 25.175, "offset_nominal_s": 24.675,
     "host_ntp_synchronized": false,
     "jump": null,
     "reason": null}

- ``offset_*`` are ``host wall - phone wall`` in seconds: a positive offset means
  the phone clock is *behind* the host. All three are ``null`` when ``status`` is
  ``unavailable``; a failed read never fabricates a number. ``offset_nominal_s`` is
  the midpoint of ``[offset_min_s, offset_max_s]`` -- the min-max-error point
  estimate inside the interval the document itself publishes, so a consumer may
  check ``min <= nominal <= max``. It used to be the *median* of the one-sided
  sample upper bounds, which is >= ``offset_max_s`` by construction and therefore
  could never satisfy that check; core senses gates clock agreement on it.
- ``jump`` is ``null`` or the bounded record of a wall-clock step against the
  previously published reading; it is the detector for the hazard a stable-offset
  assumption hides (a phone NTP correction invalidates the retained span bound).
- Written atomically (temp file + rename, 0600) to
  ``<site>/body/clock-domain-<node>.json`` -- deliberately *outside*
  ``body/perception/``: the consumer globs that directory for its own perception
  states and skips only the ``node-state-`` prefix, so a document published there
  would be parsed as a state and crash the consumer.
"""

from __future__ import annotations

import argparse
import json
import os
import shlex
import subprocess
import sys
import time
from pathlib import Path

SOURCE = "tools/clock_offset.py"
METHOD = "adb-shell-date-minus-host-wall"
STATUSES = frozenset({"ok", "unavailable"})
#: Whole-second resolution of the phone's ``date +%s`` stamp.
QUANTIZATION_S = 1.0
#: The smallest step reported as a jump: above the whole-second quantization.
JUMP_THRESHOLD_S = 2.0
ALLOWED_KEYS = frozenset(
    {
        "node", "source", "method", "status", "observed_at_epoch_s",
        "validity_seconds", "samples", "quantization_s", "rtt_max_s",
        "offset_min_s", "offset_max_s", "offset_nominal_s",
        "host_ntp_synchronized", "jump", "reason",
    }
)
MAX_REASON_CHARS = 200


def adb_argv(adb: str) -> list:
    """Split an adb command so a wrapper (e.g. ``rtk proxy adb``) is usable."""
    return shlex.split(adb) or ["adb"]


def parse_phone_epoch(text: str) -> int:
    """The phone's whole-second epoch from ``date +%s`` output."""
    stamp = (text or "").strip()
    if not stamp.isdigit():
        raise ValueError(f"unexpected phone date output: {stamp[:40]!r}")
    return int(stamp)


def sample_offset(argv, serial, samples, interval, timeout):
    """Pair the phone clock with the host clock ``samples`` times.

    Returns a list of ``{"host_mid": float, "phone_epoch": int, "rtt_s": float}``.
    Raises ``RuntimeError`` when the device is unreadable or returns nonsense.
    """
    pairs = []
    for index in range(samples):
        before = time.time()
        result = subprocess.run(
            [*argv, "-s", serial, "shell", "date", "+%s"],
            capture_output=True, text=True, timeout=timeout, check=False,
        )
        after = time.time()
        if result.returncode != 0:
            raise RuntimeError(
                f"{' '.join(argv)} -s {serial} shell date rc={result.returncode}"
            )
        pairs.append({
            "host_mid": (before + after) / 2,
            "phone_epoch": parse_phone_epoch(result.stdout),
            "rtt_s": after - before,
        })
        if index + 1 < samples and interval > 0:
            time.sleep(interval)
    return pairs


def host_ntp_synchronized(run=subprocess.run):
    """The host's own NTP verdict, or ``None`` when it cannot be read.

    Published as provenance, never used to trust either clock: the phone is
    behind the host by ~25 s here while the host reports unsynchronized, so
    "which clock is closer to true UTC" is exactly what this field refuses to
    assume.
    """
    try:
        result = run(
            ["timedatectl", "show", "--property=NTPSynchronized", "--value"],
            capture_output=True, text=True, timeout=5, check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    value = result.stdout.strip().lower()
    if value == "yes":
        return True
    if value == "no":
        return False
    return None


def offset_document(label, pairs, now, previous=None, ntp=None, validity=3600.0):
    """The bounded clock-offset document for ``pairs``, or an unavailable one.

    ``pairs`` is ``None`` when the device could not be read; the document then
    carries ``status="unavailable"`` and null offsets rather than a stale number.
    """
    observed = float(time.time() if now is None else now)
    if not pairs:
        return {
            "node": label, "source": SOURCE, "method": METHOD,
            "status": "unavailable", "observed_at_epoch_s": observed,
            "validity_seconds": float(validity), "samples": 0,
            "quantization_s": QUANTIZATION_S, "rtt_max_s": None,
            "offset_min_s": None, "offset_max_s": None, "offset_nominal_s": None,
            "host_ntp_synchronized": ntp, "jump": None,
            "reason": "no clock sample" if pairs is not None else "device unreadable",
        }
    uppers = sorted(pair["host_mid"] - pair["phone_epoch"] for pair in pairs)
    tight_upper = uppers[0]
    # The tight interval is (tight_upper - QUANTIZATION_S, tight_upper]; its midpoint
    # is the min-max-error point estimate and lies inside it by construction. The
    # median of the one-sided uppers used to be published here, which is >=
    # tight_upper and so outside the interval this same document publishes.
    nominal = tight_upper - QUANTIZATION_S / 2
    return {
        "node": label, "source": SOURCE, "method": METHOD,
        "status": "ok", "observed_at_epoch_s": observed,
        "validity_seconds": float(validity), "samples": len(uppers),
        "quantization_s": QUANTIZATION_S,
        "rtt_max_s": round(max(pair["rtt_s"] for pair in pairs), 3),
        "offset_min_s": round(tight_upper - QUANTIZATION_S, 3),
        "offset_max_s": round(tight_upper, 3),
        "offset_nominal_s": round(nominal, 3),
        "host_ntp_synchronized": ntp,
        "jump": jump_record(nominal, previous, observed),
        "reason": None,
    }


def jump_record(nominal, previous, now):
    """A bounded wall-clock-step record against ``previous``, or ``None``.

    The previous reading is only comparable while it is inside its own validity
    window; a jump against an expired reading is not claimed, because the clock
    may legitimately have been corrected (or the device re-flashed) since.
    """
    if not isinstance(previous, dict) or previous.get("status") != "ok":
        return None
    prior = previous.get("offset_nominal_s")
    prior_at = previous.get("observed_at_epoch_s")
    validity = previous.get("validity_seconds")
    if not all(isinstance(value, (int, float)) and not isinstance(value, bool)
               for value in (prior, prior_at, validity)):
        return None
    if now - prior_at > validity:
        return None
    delta = nominal - prior
    if abs(delta) < JUMP_THRESHOLD_S:
        return None
    return {
        "previous_offset_nominal_s": round(prior, 3),
        "previous_observed_at_epoch_s": prior_at,
        "delta_s": round(delta, 3),
        "threshold_s": JUMP_THRESHOLD_S,
    }


def assert_bounded(document):
    """Reject a document that is not the agreed bounded shape."""
    keys = set(document)
    if keys != set(ALLOWED_KEYS):
        raise ValueError(f"unexpected clock-domain keys: {sorted(keys ^ set(ALLOWED_KEYS))}")
    if document["status"] not in STATUSES:
        raise ValueError(f"unknown clock-domain status: {document['status']!r}")
    numbers = ("offset_min_s", "offset_max_s", "offset_nominal_s")
    if document["status"] == "unavailable":
        if any(document[key] is not None for key in numbers):
            raise ValueError("unavailable clock-domain document carries an offset")
    elif any(not isinstance(document[key], (int, float)) for key in numbers):
        raise ValueError("ok clock-domain document is missing an offset")
    elif not document["offset_min_s"] <= document["offset_nominal_s"] <= document["offset_max_s"]:
        raise ValueError("clock-domain nominal offset is outside the published interval")
    if document["reason"] is not None and (
        not isinstance(document["reason"], str)
        or len(document["reason"]) > MAX_REASON_CHARS
    ):
        raise ValueError("clock-domain reason is not a bounded string")


def publish(output, document):
    """Write ``document`` to ``output`` atomically as 0600 JSON."""
    assert_bounded(document)
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(document, sort_keys=True) + "\n"
    tmp = output.with_name(f"{output.name}.tmp{os.getpid()}")
    try:
        descriptor = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, output)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def read_previous(output):
    """The previously published document, or ``None`` when absent/unreadable."""
    try:
        document = json.loads(Path(output).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return document if isinstance(document, dict) else None


def default_output(site, label):
    return Path(site) / "body" / f"clock-domain-{label}.json"


def run_once(args):
    """Sample once, publish one document, print one bounded line. Exit status."""
    output = Path(args.output) if args.output else default_output(args.site, args.label)
    previous = read_previous(output)
    try:
        pairs = sample_offset(
            adb_argv(args.adb), args.serial, args.samples, args.interval, args.timeout
        )
    except (OSError, subprocess.SubprocessError, RuntimeError, ValueError) as error:
        document = offset_document(args.label, None, None, ntp=host_ntp_synchronized(),
                                   validity=args.validity)
        document["reason"] = str(error)[:MAX_REASON_CHARS]
        publish(output, document)
        print(f"clock-domain {args.label}: unavailable ({document['reason']}) -> {output}")
        return 0
    document = offset_document(args.label, pairs, None, previous=previous,
                               ntp=host_ntp_synchronized(), validity=args.validity)
    publish(output, document)
    line = (f"clock-domain {args.label}: phone {document['offset_nominal_s']:+.3f}s behind host "
            f"(bounds {document['offset_min_s']:+.3f}..{document['offset_max_s']:+.3f}s, "
            f"n={document['samples']}, rtt_max={document['rtt_max_s']}s, "
            f"host_ntp_synchronized={document['host_ntp_synchronized']})")
    if document["jump"]:
        line += f" JUMP delta={document['jump']['delta_s']:+.3f}s"
    print(f"{line} -> {output}")
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--site", required=True,
                        help="site root (writes body/clock-domain-<node>.json)")
    parser.add_argument("--serial", required=True, help="adb serial of the node")
    parser.add_argument("--label", default="note3")
    parser.add_argument("--adb", default="adb", help="adb command; may be multi-word")
    parser.add_argument("--samples", type=int, default=3, help="paired samples per run")
    parser.add_argument("--interval", type=float, default=0.5, help="seconds between samples")
    parser.add_argument("--timeout", type=float, default=10.0, help="per-command seconds")
    parser.add_argument("--validity", type=float, default=3600.0,
                        help="seconds the reading stays current for its consumer")
    parser.add_argument("--output", help="explicit document path (default: site/body/)")
    args = parser.parse_args(argv)
    if args.samples < 1:
        parser.error("--samples must be at least 1")
    if not all(value >= 0 for value in (args.interval, args.timeout, args.validity)):
        parser.error("timings must be non-negative")
    # One document per invocation: the 60s cadence is the systemd timer's job
    # (android-body-node-state.timer), not a loop in this tool.
    return run_once(args)


if __name__ == "__main__":
    sys.exit(main())
