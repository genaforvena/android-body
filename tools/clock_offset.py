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
     "device_serial": "4d00553d61ab90b7", "device_model": "SM-N900",
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
- ``device_serial``/``device_model`` are the *measured* device's own ``getprop
  ro.serialno``/``ro.product.model``, read in one tagged round trip and ``null``
  when that read fails (never guessed). They name the device the offset came from,
  independently of the ``--label`` the operator passed.
- A run whose measured serial is recorded for a *different* node in the site's
  activation record publishes ``status="unavailable"`` with
  ``reason="label-serial-mismatch: ..."`` instead of an ``ok`` reading. The label is
  the operator's assertion and the serial is the device's; a document that
  contradicts itself is not a reading. The record is
  ``<site>/body/activation.json`` (its ``<node>_serial`` keys) and an absent or
  unreadable one only narrows the check, never fabricates a match.
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
import re
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
#: The device properties the document names its measurement with.
SERIAL_PROP = "ro.serialno"
MODEL_PROP = "ro.product.model"
#: Bounded shape of an identity value copied off the device: anything else (a
#: wrapper banner, an empty property) is dropped instead of entering the document.
SERIAL_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{3,63}\Z")
MODEL_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9 ._()/-]{0,63}\Z")
ALLOWED_KEYS = frozenset(
    {
        "node", "source", "method", "status", "observed_at_epoch_s",
        "validity_seconds", "samples", "quantization_s", "rtt_max_s",
        "offset_min_s", "offset_max_s", "offset_nominal_s",
        "device_serial", "device_model",
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


def _identity_value(text, pattern):
    """``text`` when it is a plausible identity value, else ``None``."""
    return text if text and pattern.match(text) else None


def sample_identity(argv, serial, timeout):
    """The measured device's own serial and model, or nulls when unreadable.

    One tagged ``getprop`` round trip on the same ``--serial`` the clock is read
    from, so the document can name the device it measured instead of only the label
    it was handed. The tags keep a wrapper's banner out of the values, and a value
    that is not a plausible identity stays ``None`` rather than entering the
    document verbatim. A failed identity read never costs the offset reading: it is
    provenance, so it degrades to ``null``.
    """
    command = f"echo S=$(getprop {SERIAL_PROP}); echo M=$(getprop {MODEL_PROP})"
    try:
        result = subprocess.run(
            [*argv, "-s", serial, "shell", command],
            capture_output=True, text=True, timeout=timeout, check=False,
        )
    except (OSError, ValueError, subprocess.SubprocessError):
        # ValueError covers the strict-UTF-8 decode of a wrapper's or the device's
        # non-UTF-8 bytes: provenance degrades to null, the offset reading stands.
        result = None
    values = {}
    if result is not None and result.returncode == 0:
        for line in (result.stdout or "").splitlines():
            for tag, key in (("S=", "device_serial"), ("M=", "device_model")):
                if line.startswith(tag):
                    values[key] = line[len(tag):].strip()
    return {"device_serial": _identity_value(values.get("device_serial"), SERIAL_RE),
            "device_model": _identity_value(values.get("device_model"), MODEL_RE)}


def node_serials(site):
    """The site's recorded adb serial -> node mapping, or ``{}`` when unavailable.

    ``<site>/body/activation.json`` is the site's own statement of which serial
    belongs to which node, as ``<node>_serial`` keys. It is read tolerantly: an
    unreadable or non-dict record and non-string entries only narrow the label
    check, they never invent a mapping.
    """
    try:
        record = json.loads(
            (Path(site) / "body" / "activation.json").read_text(encoding="utf-8")
        )
    except (OSError, ValueError):
        return {}
    if not isinstance(record, dict):
        return {}
    mapping = {}
    for key, value in record.items():
        if key.endswith("_serial") and isinstance(value, str) and value.strip():
            mapping[value.strip()] = key[: -len("_serial")]
    return mapping


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


def offset_document(label, pairs, now, previous=None, ntp=None, validity=3600.0,
                    identity=None):
    """The bounded clock-offset document for ``pairs``, or an unavailable one.

    ``pairs`` is ``None`` when the device could not be read; the document then
    carries ``status="unavailable"`` and null offsets rather than a stale number.
    ``identity`` is the measured device's ``device_serial``/``device_model`` or
    ``None`` when the device did not name itself.
    """
    observed = float(time.time() if now is None else now)
    identity = identity or {}
    if not pairs:
        return {
            "node": label, "source": SOURCE, "method": METHOD,
            "status": "unavailable", "observed_at_epoch_s": observed,
            "validity_seconds": float(validity), "samples": 0,
            "quantization_s": QUANTIZATION_S, "rtt_max_s": None,
            "offset_min_s": None, "offset_max_s": None, "offset_nominal_s": None,
            "device_serial": identity.get("device_serial"),
            "device_model": identity.get("device_model"),
            "reason": "no clock sample" if pairs is not None else "device unreadable",
            "host_ntp_synchronized": ntp, "jump": None,
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
        "device_serial": identity.get("device_serial"),
        "device_model": identity.get("device_model"),
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
    identity = sample_identity(adb_argv(args.adb), args.serial, args.timeout)
    owner = node_serials(args.site).get(identity["device_serial"])
    if owner is not None and owner != args.label:
        document = offset_document(args.label, None, None, ntp=host_ntp_synchronized(),
                                   validity=args.validity, identity=identity)
        document["reason"] = (
            f"label-serial-mismatch: serial {identity['device_serial']} is {owner}"
        )[:MAX_REASON_CHARS]
        publish(output, document)
        print(f"clock-domain {args.label}: unavailable ({document['reason']}) -> {output}")
        return 0
    document = offset_document(args.label, pairs, None, previous=previous,
                               ntp=host_ntp_synchronized(), validity=args.validity,
                               identity=identity)
    publish(output, document)
    line = (f"clock-domain {args.label}: phone {document['offset_nominal_s']:+.3f}s behind host "
            f"(bounds {document['offset_min_s']:+.3f}..{document['offset_max_s']:+.3f}s, "
            f"n={document['samples']}, rtt_max={document['rtt_max_s']}s, "
            f"host_ntp_synchronized={document['host_ntp_synchronized']}, "
            f"device={document['device_model'] or 'unknown'}/"
            f"{document['device_serial'] or 'unknown'})")
    if document["jump"]:
        line += f" JUMP delta={document['jump']['delta_s']:+.3f}s"
    print(f"{line} -> {output}")
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--site", required=True,
                        help="site root (writes body/clock-domain-<node>.json)")
    parser.add_argument("--serial", required=True, help="adb serial of the node")
    parser.add_argument("--label", default="note3",
                        help="node the reading is for; must be the node the "
                             "activation record attributes --serial to")
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
