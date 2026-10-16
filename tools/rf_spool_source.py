#!/usr/bin/env python3
# SPDX-License-Identifier: CC0-1.0
"""Real ``--src`` source for the core RF-timing harness liveness gate.

The harness ``scratch/rf-timing-check/bin/rf-timing-harness.sh`` (core site;
designed by discover 50437/51729) gates the start of a live RF trial on one line
printed by its ``--src`` command::

    epoch=<row epoch> row_age_s=<n> last_error=<token>

and fails the gate (``GATE_FAIL``, exit 104, control never started) when
``row_age_s >= 60`` or ``last_error != none``. Its only source is
``bin/stub-spool.sh``, a deterministic stand-in.

Why a stand-in cannot gate a real run: ``row_age_s`` has to be the age of the
latest ``ble_scan_state`` row *now*. android-body publishes that row only on the
``android-body-spool-read.timer`` cycle (``OnUnitActiveSec=5min``), so the
published copy sweeps 0..~305 s and the gate fails roughly 5/6 of the time with
no receiver fault (``docs/verification.md`` sections 304-313; senses 97291). A
real source must therefore force one bounded on-demand publication -- the same
oneshot unit the timer runs, with the same device command -- and then report the
row it just published. That is what this tool does; it adds no device command
and no new observation channel.

Failure is fail-closed. Any unusable input prints ``spool-source unusable:
<reason>`` with no ``row_age_s=``/``last_error=`` token and exits 0, so the
harness records the reason in its manifest (``gate_A raw='...'``) and returns
``parse_fail`` -- a DEFER, never a pass. A non-zero exit would instead collapse
to the harness's bare ``spool ERROR`` with the reason discarded.

Bounds: documents are read with a size cap; each publication runs under a
timeout; the clock-offset reading is used only while its own validity and the
host-side cap hold (a stale offset is UNKNOWN, never a number). The row age is
resolved in the host clock domain through the published offset exactly as the
perception consumer does (``experiments/perception/watch.py``,
``spool_scan_state_row_age``; the tests assert parity on shared fixtures).

Invocation (the harness passes no arguments to ``--src``)::

    tools/rf_spool_source.py

Defaults resolve from this file's location: site ``<repo>/.mishe-tauftauf``,
node ``note3``, reader ``systemctl --user start android-body-spool-read.service``,
clock reader ``systemctl --user start android-body-node-state.service``.
"""

from __future__ import annotations

import argparse
import json
import math
import shlex
import subprocess
import sys
import time
from pathlib import Path

SOURCE = "tools/rf_spool_source.py"

#: Site root directory name, resolved as ``<repo>/<SITE_DIRNAME>``.
SITE_DIRNAME = ".mishe-tauftauf"
DEFAULT_NODE = "note3"

#: Canonical on-demand publication: the oneshot units the timers run. The
#: summary reader carries the adb serial and adb wrapper in the unit, so the
#: tool needs no device arguments of its own.
DEFAULT_READER = "systemctl --user start android-body-spool-read.service"
DEFAULT_CLOCK_READER = "systemctl --user start android-body-node-state.service"

#: Refresh the summary when the row it carries is at least this old. The gate
#: fails at >= 60 s, so refreshing below the bound leaves headroom for the
#: reader's own run time (~7 s on this host).
REFRESH_BELOW_S = 60.0

#: Bound on one on-demand publication (the node-state unit runs two reads).
READER_TIMEOUT_S = 90.0

#: Bound on a published document read; the live summaries are ~1 KiB.
MAX_DOC_BYTES = 65536

#: Host-side cap on the clock-offset reading's age
#: (``watch.CLOCK_DOMAIN_MAX_AGE_SECONDS``).
CLOCK_DOMAIN_MAX_AGE_S = 3600.0

#: Admissible ``ble_scan_state`` phase tokens (BleScanEvents.stateEvent).
SCAN_STATE_PHASES = frozenset({"none", "window", "gap"})

#: Bound on the retained ``last_error`` string (``none`` or a short reason).
MAX_LAST_ERROR_CHARS = 64


def default_site(script_path=None):
    """The site root implied by this tool's location inside the repository."""
    return Path(script_path or __file__).resolve().parent.parent / SITE_DIRNAME


def _finite(value):
    """``float(value)`` for a finite number, else ``None`` (bool is not a number)."""
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return None
    if abs(value) > 1e308 or not math.isfinite(value):
        return None
    return float(value)


def read_document(path, limit=MAX_DOC_BYTES):
    """Read one bounded JSON document; return ``(document, reason)``.

    ``reason`` is ``None`` on success, else one of ``absent``, ``unreadable``,
    ``oversized``, ``malformed``. The size cap is enforced before parsing, so a
    runaway file cannot be pulled into memory.
    """
    try:
        with open(path, "rb") as handle:
            raw = handle.read(limit + 1)
    except FileNotFoundError:
        return None, "absent"
    except OSError:
        return None, "unreadable"
    if len(raw) > limit:
        return None, "oversized"
    try:
        return json.loads(raw.decode("utf-8")), None
    except (UnicodeDecodeError, ValueError):
        return None, "malformed"


def read_clock_domain(path, node, now, max_age=CLOCK_DOMAIN_MAX_AGE_S):
    """The bounded phone/host clock-offset reading for ``node``, or an unknown.

    Mirrors ``watch.read_clock_domain``'s result shape and status vocabulary so
    the age resolver below can be checked against the consumer on the same
    fixtures. A missing, unreadable, oversized, malformed, foreign, invalid or
    expired document never yields an offset.
    """
    def unknown(status, reason):
        return {"status": status, "offset_min_s": None, "offset_max_s": None,
                "offset_nominal_s": None, "observed_at_epoch_s": None,
                "age_s": None, "validity_seconds": None, "samples": 0,
                "jump": None, "source": None, "reason": reason}

    document, reason = read_document(path)
    if document is None:
        if reason == "absent":
            return unknown("absent", "no-clock-domain-file")
        return unknown("invalid", "clock-domain-unreadable")
    if (not isinstance(document, dict) or document.get("node") != node
            or document.get("status") != "ok"):
        return unknown("invalid", "clock-domain-invalid")

    numbers = {key: _finite(document.get(key)) for key in
               ("offset_min_s", "offset_max_s", "offset_nominal_s",
                "observed_at_epoch_s")}
    validity = _finite(document.get("validity_seconds"))
    if any(value is None for value in numbers.values()) or validity is None or validity <= 0:
        return unknown("invalid", "clock-domain-invalid")
    if numbers["offset_min_s"] > numbers["offset_max_s"]:
        return unknown("invalid", "clock-domain-invalid")
    age = now - numbers["observed_at_epoch_s"]
    if age > min(validity, max_age):
        return unknown("stale", "clock-domain-stale")
    samples = document.get("samples")
    jump = document.get("jump")
    source = document.get("source")
    return {"status": "ok",
            "offset_min_s": numbers["offset_min_s"],
            "offset_max_s": numbers["offset_max_s"],
            "offset_nominal_s": numbers["offset_nominal_s"],
            "observed_at_epoch_s": numbers["observed_at_epoch_s"],
            "age_s": round(max(age, 0.0), 1),
            "validity_seconds": validity,
            "samples": samples if isinstance(samples, int) and not isinstance(samples, bool) else 0,
            "jump": jump if isinstance(jump, dict) else None,
            "source": source if isinstance(source, str) else None,
            "reason": None}


def scan_state_row_age(scan_state, now, clock):
    """Host-domain age of the latest scan-state row, or a reason.

    Byte-for-byte the guard set and reason tokens of
    ``watch.spool_scan_state_row_age``: the row epoch is the PHONE's clock, so
    the age is ``now - (epoch + offset)`` and an unresolvable clock domain is
    UNKNOWN, never a number.
    """
    if not isinstance(scan_state, dict):
        return None, "no-scan-state-row"
    epoch = _finite(scan_state.get("epoch_s"))
    if epoch is None:
        return None, "no-row-epoch"
    reference = _finite(now)
    if reference is None:
        return None, "no-reference-time"
    if not clock or clock.get("status") != "ok":
        return None, "clock-domain-unresolved"
    if clock.get("jump"):
        return None, "clock-domain-jump"
    offset = _finite(clock.get("offset_nominal_s"))
    low = _finite(clock.get("offset_min_s"))
    high = _finite(clock.get("offset_max_s"))
    if offset is None or low is None or high is None or high < low:
        return None, "clock-domain-invalid"
    age = reference - (epoch + offset)
    if age < -max(offset - low, 0.0):
        return None, "row-epoch-in-future"
    return max(age, 0.0), None


def scan_state_fields(summary):
    """The gate's fields from a published summary, or ``(None, reason)``.

    The harness needs ``epoch`` (provenance), ``last_error`` (its own gate
    input) and, for a caller that can use them, ``phase``/``windows`` -- the
    signals that expose a stopped *scan loop*, which keeps re-stamping the row
    with ``phase=none`` and frozen counters (``docs/verification.md`` 310).
    """
    if not isinstance(summary, dict) or summary.get("status") != "ok":
        return None, "summary-unavailable"
    row = summary.get("scan_state")
    if not isinstance(row, dict):
        return None, "no-scan-state-row"
    epoch = _finite(row.get("epoch_s"))
    if epoch is None:
        return None, "no-row-epoch"
    phase = row.get("phase")
    windows = row.get("windows")
    last_error = row.get("last_error")
    # ``phase`` is an arbitrary JSON value; membership in a frozenset raises TypeError on an
    # unhashable one (a JSON array/object), which would escape scan_state_fields as a traceback
    # (rc 1, empty stdout) instead of the documented unusable-input reason.
    if not isinstance(phase, str) or phase not in SCAN_STATE_PHASES:
        return None, "scan-state-invalid"
    if not isinstance(windows, int) or isinstance(windows, bool) or windows < 0:
        return None, "scan-state-invalid"
    if (not isinstance(last_error, str) or not last_error
            or len(last_error) > MAX_LAST_ERROR_CHARS or " " in last_error):
        return None, "scan-state-invalid"
    return {"epoch_s": epoch, "phase": phase, "windows": windows,
            "last_error": last_error}, None


def summary_age(summary, now):
    """Age of the summary document itself in host seconds, or ``None``."""
    observed = _finite(summary.get("observed_at_epoch_s")) if isinstance(summary, dict) else None
    reference = _finite(now)
    if observed is None or reference is None:
        return None
    return max(reference - observed, 0.0)


def emitted_age(age):
    """The age as the harness will read it: the value the line prints.

    The refresh decision must use this and not the raw float. The gate parses
    the printed ``%.1f``, so a raw 59.975 prints as ``60.0`` and fails the gate
    while still comparing below a raw 60 s bound -- the tool would then hand the
    harness a line it believes is fresh and the gate rejects.
    """
    return float(f"{age:.1f}")


def run_publication(command, timeout):
    """Run one bounded on-demand publication; return ``(ok, reason)``."""
    try:
        argv = shlex.split(command)
    except ValueError:
        return False, "reader-unparsable"
    if not argv:
        return False, "reader-empty"
    try:
        result = subprocess.run(argv, stdout=subprocess.DEVNULL,
                                stderr=subprocess.DEVNULL, timeout=timeout)
    except FileNotFoundError:
        return False, "reader-missing"
    except subprocess.TimeoutExpired:
        return False, "refresh-timeout"
    except OSError:
        return False, "refresh-failed"
    if result.returncode != 0:
        return False, f"refresh-failed rc={result.returncode}"
    return True, None


class Source:
    """Read the published pair, refreshing whatever is not fresh enough."""

    def __init__(self, site, node, summary_path=None, clock_path=None,
                 reader=DEFAULT_READER, clock_reader=DEFAULT_CLOCK_READER,
                 refresh_below=REFRESH_BELOW_S, timeout=READER_TIMEOUT_S,
                 allow_refresh=True, limit=MAX_DOC_BYTES, now_fn=time.time):
        body = Path(site) / "body"
        self.node = node
        self.summary_path = Path(summary_path) if summary_path else body / f"spool-summary-{node}.json"
        self.clock_path = Path(clock_path) if clock_path else body / f"clock-domain-{node}.json"
        self.reader = reader
        self.clock_reader = clock_reader
        self.refresh_below = refresh_below
        self.timeout = timeout
        self.allow_refresh = allow_refresh
        self.limit = limit
        self.now_fn = now_fn

    def read(self):
        """One published reading: ``(summary, clock, refreshed, problem, now)``.

        A publication is attempted only when the value it would refresh is not
        usable. A failed attempt is reported as ``problem`` when the value is
        *still* not usable afterwards, so a broken reader is named instead of
        being disguised as a stale row; a value that became usable anyway (the
        timer's own cycle landed in between) is reported as a reading.

        The reference clock is re-sampled after every publication. A publication
        takes seconds, so a reference taken before it ages a row that the
        publication itself wrote: the freshly stamped row then reads as a
        negative age and the guard rejects the line as ``row-epoch-in-future``
        (found by the first live run of this tool).
        """
        refreshed = []
        problem = None
        now = self.now_fn()
        summary, _ = read_document(self.summary_path, self.limit)
        clock = read_clock_domain(self.clock_path, self.node, now)
        if self.allow_refresh and clock["status"] != "ok":
            ok, error = run_publication(self.clock_reader, self.timeout)
            clock = read_clock_domain(self.clock_path, self.node, self.now_fn())
            if ok:
                refreshed.append("clock")
            elif clock["status"] != "ok":
                problem = f"clock-{error}"
        now = self.now_fn()
        age, _ = self._row_age(summary, clock, now)
        if (problem is None and self.allow_refresh
                and (age is None or emitted_age(age) >= self.refresh_below)):
            ok, error = run_publication(self.reader, self.timeout)
            summary, _ = read_document(self.summary_path, self.limit)
            now = self.now_fn()
            age, _ = self._row_age(summary, clock, now)
            if ok:
                refreshed.append("summary")
            elif age is None or emitted_age(age) >= self.refresh_below:
                problem = error
        return summary, clock, refreshed, problem, now

    @staticmethod
    def _row_age(summary, clock, now):
        row = summary.get("scan_state") if isinstance(summary, dict) else None
        return scan_state_row_age(row, now, clock)


def gate_line(summary, clock, now, refreshed):
    """The harness line, or ``(None, reason)`` when the gate input is unusable."""
    fields, reason = scan_state_fields(summary)
    if fields is None:
        return None, reason
    age, reason = scan_state_row_age(summary["scan_state"], now, clock)
    if age is None:
        return None, reason
    document_age = summary_age(summary, now)
    age_text = f"summary_age_s={document_age:.1f}" if document_age is not None else "summary_age_s=unknown"
    return (f"epoch={int(fields['epoch_s'])} row_age_s={age:.1f} "
            f"last_error={fields['last_error']} phase={fields['phase']} "
            f"windows={fields['windows']} {age_text} "
            f"refreshed={'+'.join(refreshed) if refreshed else 'no'}"), None


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--site", default=None,
                        help="site root (default: <repo>/%s)" % SITE_DIRNAME)
    parser.add_argument("--node", default=DEFAULT_NODE)
    parser.add_argument("--summary", help="explicit summary document path")
    parser.add_argument("--clock", help="explicit clock-domain document path")
    parser.add_argument("--reader", default=DEFAULT_READER,
                        help="on-demand summary publication command")
    parser.add_argument("--clock-reader", default=DEFAULT_CLOCK_READER,
                        help="on-demand clock-domain publication command")
    parser.add_argument("--refresh-below", type=float, default=REFRESH_BELOW_S,
                        help="refresh when the published row is at least this old")
    parser.add_argument("--timeout", type=float, default=READER_TIMEOUT_S,
                        help="seconds one publication may take")
    parser.add_argument("--max-bytes", type=int, default=MAX_DOC_BYTES,
                        help="size cap for one published document")
    parser.add_argument("--now", type=float, default=None,
                        help="reference epoch (default: this host's clock)")
    parser.add_argument("--no-refresh", action="store_true",
                        help="read what is published; never run a publication")
    args = parser.parse_args(argv)
    if args.refresh_below < 0:
        parser.error("--refresh-below must not be negative")
    if args.timeout <= 0:
        parser.error("--timeout must be positive")
    if args.max_bytes <= 0:
        parser.error("--max-bytes must be positive")
    site = Path(args.site) if args.site else default_site()
    now_fn = time.time if args.now is None else (lambda: float(args.now))
    source = Source(site, args.node, args.summary, args.clock, args.reader,
                    args.clock_reader, args.refresh_below, args.timeout,
                    not args.no_refresh, args.max_bytes, now_fn)
    summary, clock, refreshed, problem, now = source.read()
    if problem is not None:
        print(f"spool-source unusable: {problem}")
        return 0
    line, reason = gate_line(summary, clock, now, refreshed)
    if line is None:
        # Fail closed, with the reason visible in the harness manifest: no
        # row_age_s=/last_error= token, so the gate reads parse_fail (DEFER).
        print(f"spool-source unusable: {reason}")
        return 0
    print(line)
    return 0


if __name__ == "__main__":
    sys.exit(main())
