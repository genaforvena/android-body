#!/usr/bin/env python3
# SPDX-License-Identifier: CC0-1.0
"""Publish a bounded app-spool summary for the perception consumer.

The app's local spool (``files/observations/cursor_<sha256>/observations.spool``)
retains collected sensor rows independently of delivery. Under collect-only the
delivered stream is frozen by design, so the spool is the only delivery-independent
evidence of what the producer actually collected. This tool reads it read-only via
``adb shell run-as org.androidbody grep -a`` and publishes a bounded summary.

Constraints (from the spool-channel ruling, artifacts/senses-wake79358-spool-channel-ruling.md):

- Bounded fields only: counts per allowlisted protocol kind, light magnitude
  buckets, spool byte size, and retention window (oldest/newest row timestamps
  converted to host epoch). No full dump, no shared_prefs, no secret/endpoint.
  The cursor_<sha256> directory name is not republished.
- Read-only, no mutation of the spool or the app.
- Never presented as a delivered observation: the document carries
  ``source=app-private-spool`` and the consumer renders it as collection-side.
- Failure is UNKNOWN (status=unavailable), never calm or fabricated.
- Collection loss is reported, not inferred: ``overflow.dropped`` is the app's
  cumulative eviction count, read from the last ``spool overflow dropped=``
  notice (never counted, never summed). A live collector with a stale consumer
  is therefore not mistaken for a lossless one. ``dropped=0`` with a null
  ``notice_epoch_s`` is a truthful zero (nothing evicted yet), not an absent
  field.
- Repeatable via this owned tool, not a per-wake ad-hoc command.

The document (exactly these keys, never the endpoint or the node secret):

    {"node": "note3",
     "source": "tools/spool_read.py",
     "method": "adb-run-as-grep-counts",
     "status": "ok|unavailable",
     "observed_at_epoch_s": 1791989019.5,
     "validity_seconds": 300,
     "spool_bytes": 3858200,
     "retention_window_s": 23400.0,
     "oldest_row_epoch_s": 1791892800.0,
     "newest_row_epoch_s": 1791916200.0,
     "counts": {"light": 4964, "battery": 12, ...},
     "light_buckets": {"dark_exact": 1386, "faint_0_1": 4, "dim_0_9": 4982,
                       "moderate_10_99": 549, "bright_100_999": 180,
                       "very_bright_1000_plus": 0},
     "overflow": {"dropped": 108040, "notice_epoch_s": 1792050926},
     "reason": null}

Written atomically (temp file + rename, 0600) to
``<site>/body/spool-summary-<node>.json`` -- deliberately *outside*
``body/perception/``: the consumer globs that directory for its own perception
states and skips only the ``node-state-`` prefix, so a document published there
would be parsed as a state and crash the consumer.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import shlex
import subprocess
import sys
import time
from pathlib import Path

SOURCE = "tools/spool_read.py"
METHOD = "adb-run-as-grep-counts"
STATUSES = frozenset({"ok", "unavailable"})
MAX_REASON_CHARS = 200

#: BRE matching a spool row's leading 10-digit epoch; sent to device grep as-is.
ROW_EPOCH_BRE = r"[0-9]\{10\}"

#: BRE matching a row's leading epoch plus the kind token that follows it.
#: The spool is binary-framed (ObservationSpool.writeRecord: an 8-byte record
#: id and a 4-byte text length precede the ``<epoch> <kind> ...\n`` payload),
#: so a row's epoch never starts a text line and a ``^`` anchor cannot reach
#: it. A bare ``[0-9]\{10\}`` instead matches any 10-digit substring --
#: including ``sensor_time_ns=<10 digits>`` on a freshly booted phone and the
#: epoch-valued ``observed_at`` of Wi-Fi rows -- which published a 6.4-year
#: retention window where the rows span ~5.7 h (senses, 2026-10-15).
ROW_EPOCH_TOKEN_BRE = r"[0-9]\{10\} [a-z_]\{1,\}"

#: Ceiling for a plausible row span. The app's documented retention is ~10 h
#: (protocol README: queue bounds); a larger span means the extraction picked
#: up a field value, so report the read as failed rather than publish it.
MAX_RETENTION_WINDOW_S = 30 * 86400

#: BRE for the app's overflow notice row: ``<epoch> spool overflow dropped=N
#: policy=oldest`` (ObservationSpool.overflowText). ``N`` is the *cumulative*
#: count of ordinary rows evicted by bounded retention, and notices are never
#: trimmed (ObservationSpool.trim skips them), so the file keeps every notice
#: ever written -- 1,451 of them on Note3 2026-10-15 for one live count.
#: Counting or summing notices therefore over-reports the loss by ~100x; the
#: value that matters is the LAST match in append order.
OVERFLOW_NOTICE_BRE = r"[0-9]\{10\} spool overflow dropped=[0-9]\{1,\}"

#: Python parse of one device ``grep -o`` match (full match: the pattern above
#: emits the row-leading epoch, so a bare ``dropped=`` field cannot pass).
OVERFLOW_NOTICE_RE = re.compile(r"([0-9]{10}) spool overflow dropped=([0-9]+)")

#: Marker appended after the overflow grep so the *device-side* status is
#: visible in stdout. This workstation's adb returns 0 for a device-side
#: ``exit 7``, so a host-side return code cannot tell "grep matched nothing"
#: (device rc 1: a truthful zero) from a broken read. The probe can.
OVERFLOW_PROBE_MARKER = "spool-overflow-probe rc="

#: Allowlisted protocol record kinds (verified from spool snapshot
#: 2026-10-14T13:10Z and the protocol README; ``ble_sighting`` is emitted
#: by BleScanEvents.sighting while a session is ON, ``ble_scan_state`` is the
#: per-cycle sampler-lane scan-loop state row, BleScanEvents.stateEvent).
ALLOWED_KINDS = frozenset({
    "battery", "light", "acceleration", "ble_status", "wifi_link_rssi",
    "spool", "cap", "hello", "android", "owner_checkboxes", "probe",
    "ble_scan", "ble_scan_state", "ble_sighting", "action",
})

#: Tokens that begin a spool row: the kind written immediately after the
#: epoch. Three groups differ from the counted names. Wi-Fi rows carry the kind
#: ``wifi_link_rssi_dbm`` (device census 2026-10-15), not the counted
#: ``wifi_link_rssi``. ``owner``/``sensor``/``actuator`` begin the
#: session-start rows the app writes when a checkbox is off, a sensor is
#: absent or no actuator exists (Sensors.capabilities, BodyService: ``owner
#: battery off``, ``sensor light absent``, ``actuator vibration absent``);
#: they are not counted kinds, but they are row epochs, so excluding them
#: would silently narrow the retention span.
ROW_KIND_TOKENS = ALLOWED_KINDS | {
    "wifi_link_rssi_dbm", "owner", "sensor", "actuator",
}

#: Kinds counted but not sensor-data (protocol/control kinds).
NON_SENSOR_KINDS = frozenset({"cap", "hello", "android", "owner_checkboxes", "probe", "action"})

#: Light magnitude buckets (lux ranges), disjoint by construction: every
#: non-negative Java float string the app can emit (``"lux=" + float``)
#: matches exactly one bucket, so the bucket counts partition the light
#: rows and their sum equals the ``lux=`` row count. Each pattern is the
#: exact BRE string sent to the device's ``grep -a -c``: toybox grep is BRE
#: by default, so intervals must be brace-escaped (``\{3,\}``), like the
#: epoch pattern above. ``faint_0_1`` covers the open interval (0, 1) that
#: the dim bucket's ``[1-9]`` leading digit excludes (discover 81172).
LIGHT_BUCKETS = (
    ("dark_exact", r"lux=0\.0"),
    ("faint_0_1", r"lux=0\.[1-9]"),
    ("dim_0_9", r"lux=[1-9]\.[0-9]"),
    ("moderate_10_99", r"lux=[1-9][0-9]\.[0-9]"),
    ("bright_100_999", r"lux=[1-9][0-9][0-9]\.[0-9]"),
    ("very_bright_1000_plus", r"lux=[1-9][0-9]\{3,\}"),
)

#: Pattern to extract the spool path from run-as ls output.
SPOOL_PATH_RE = re.compile(r"observations\.spool$")

#: Pattern to extract lux value from a grep-matched line (for verification).
LUX_VALUE_RE = re.compile(r"lux=([0-9.]+)")

ALLOWED_KEYS = frozenset({
    "node", "source", "method", "status", "observed_at_epoch_s",
    "validity_seconds", "spool_bytes", "retention_window_s",
    "oldest_row_epoch_s", "newest_row_epoch_s", "counts",
    "light_buckets", "overflow", "reason",
})


def adb_argv(adb: str) -> list:
    """Split an adb command so a wrapper (e.g. ``rtk proxy adb``) is usable."""
    return shlex.split(adb) or ["adb"]


def _run(argv, serial, commands, timeout):
    """Run a shell command on the device via adb; return stdout or raise."""
    full = [*argv, "-s", serial, "shell", commands]
    result = subprocess.run(full, capture_output=True, text=True, timeout=timeout, check=False)
    if result.returncode != 0:
        raise RuntimeError(f"adb shell rc={result.returncode}: {result.stderr[:120]}")
    return result.stdout


def _parse_int(text, label):
    """Parse a non-negative integer from command output."""
    cleaned = (text or "").strip()
    if not cleaned.isdigit():
        raise ValueError(f"unexpected {label} output: {cleaned[:60]!r}")
    return int(cleaned)


def _parse_float(text, label):
    """Parse a non-negative float from command output."""
    cleaned = (text or "").strip()
    try:
        value = float(cleaned)
        if not math.isfinite(value) or value < 0:
            raise ValueError
        return value
    except ValueError:
        raise ValueError(f"unexpected {label} output: {cleaned[:60]!r}")


def _find_spool_dir(argv, serial, timeout):
    """Find the cursor_* spool directory path on the device, or raise."""
    try:
        listing = _run(argv, serial,
                       "run-as org.androidbody ls files/observations/", timeout)
    except (OSError, subprocess.SubprocessError, RuntimeError, ValueError) as e:
        raise RuntimeError(f"spool-dir-listing-failed: {e}") from e
    for line in listing.splitlines():
        line = line.strip()
        if line.startswith("cursor_"):
            return line
    raise RuntimeError("no cursor_* spool directory found")


def _count_kind(argv, serial, spool_path, kind, timeout):
    """Count rows of one kind in the spool via grep -a -c.

    Rows are ``<epoch> <kind> <fields>``; the pattern matches the row's
    10-digit epoch followed by the kind, so only rows of exactly that kind
    are counted. A bare-substring count also matches rows that merely
    mention the kind — ``source=androidbody_wifi_api`` made ``android``
    count wifi and bluetooth rows. The epoch anchor also tolerates the
    app's varying kind/field separator (space or glued underscore) and the
    binary row prefix, which defeats a line-start ``^`` anchor.

    ``ble_scan`` is a prefix of ``ble_scan_state``, so the lifecycle kind is
    anchored with a trailing space: every ble_scan row carries fields after
    the kind (start/stop/error/unavailable plus a reason), while
    ble_scan_state rows then count only themselves.
    """
    try:
        output = _run(argv, serial,
                      f"run-as org.androidbody grep -a -c '{ROW_EPOCH_BRE} {kind}"
                      f"{' ' if kind == 'ble_scan' else ''}' {spool_path}",
                      timeout)
        return _parse_int(output, f"grep-count-{kind}")
    except (OSError, subprocess.SubprocessError, RuntimeError, ValueError) as e:
        raise RuntimeError(f"count-{kind}-failed: {e}") from e


def _count_light_bucket(argv, serial, spool_path, pattern, timeout):
    """Count light rows matching a magnitude bucket regex."""
    try:
        output = _run(argv, serial,
                      f"run-as org.androidbody grep -a -c '{pattern}' {spool_path}",
                      timeout)
        return _parse_int(output, f"grep-bucket-{pattern[:20]}")
    except (OSError, subprocess.SubprocessError, RuntimeError, ValueError) as e:
        raise RuntimeError(f"light-bucket-{pattern[:20]}-failed: {e}") from e


def _spool_size(argv, serial, spool_path, timeout):
    """Get the spool file size in bytes via run-as ls -l."""
    try:
        output = _run(argv, serial,
                      f"run-as org.androidbody ls -l {spool_path}", timeout)
        # ls -l output varies by device:
        #   "-rw------- 1 u0_a123 u0_a123 3858200 Oct 14 18:06 observations.spool"
        #   "-rw------- u0_a225 u0_a225 4085104 2026-10-14 18:29 observations.spool"
        # The size is the largest all-digit token; prefer non-year values.
        parts = output.strip().split()
        digit_values = []
        for part in parts:
            if part.isdigit():
                digit_values.append(int(part))
        if not digit_values:
            raise ValueError(f"no size found in ls output: {output.strip()[:80]!r}")
        # Prefer non-year values (file sizes are rarely in year range)
        non_year = [v for v in digit_values if not (1970 <= v <= 2100)]
        if non_year:
            return max(non_year)
        return max(digit_values)
    except (OSError, subprocess.SubprocessError, RuntimeError, ValueError) as e:
        raise RuntimeError(f"spool-size-failed: {e}") from e


def _row_epochs(match_output):
    """Row epochs from ``grep -a -o '<epoch> <token>'`` output.

    Only candidates whose token is a known row kind survive. The same
    10-digit shape appears in field values followed by a key name
    (``sensor_time_ns=<n> phone_elapsed_ms=``, ``observed_at=<n>
    phone_elapsed_ms=``); those are not row timestamps and would otherwise
    set the window to years. The epoch range drops values that cannot be a
    phone wall clock (2023-11 .. 2033-05) as a second guard.
    """
    epochs = []
    for line in match_output.splitlines():
        parts = line.split()
        if len(parts) != 2 or parts[1] not in ROW_KIND_TOKENS:
            continue
        try:
            value = int(parts[0])
        except ValueError:
            continue
        if 1700000000 <= value <= 2000000000:
            epochs.append(value)
    return epochs


def _retention_window(argv, serial, spool_path, timeout):
    """Get the spool retention window from the oldest and newest row timestamps.

    Each spool row's payload begins with its epoch timestamp (Unix seconds).
    We extract epoch candidates with ``grep -a -o`` (one per row plus the
    field values that share the 10-digit shape), keep the ones whose trailing
    token is a row kind, then compute min/max in Python, avoiding a full dump.
    The retention window (~6.5h) bounds the match count (~20K).

    Returns ``(oldest_epoch_host, newest_epoch_host, window_seconds)`` or raises.
    """
    try:
        out = _run(argv, serial,
                   f"run-as org.androidbody grep -a -o '{ROW_EPOCH_TOKEN_BRE}' {spool_path}",
                   timeout)
        epochs = _row_epochs(out)
        if not epochs:
            raise ValueError("no row epoch matched the kind anchor")
        oldest_epoch = min(epochs)
        newest_epoch = max(epochs)
        window = newest_epoch - oldest_epoch
        if window > MAX_RETENTION_WINDOW_S:
            raise ValueError(f"implausible retention window: {window}s")
        return oldest_epoch, newest_epoch, window
    except (OSError, subprocess.SubprocessError, RuntimeError, ValueError) as e:
        raise RuntimeError(f"retention-window-failed: {e}") from e


def _overflow_notice(argv, serial, spool_path, timeout):
    """The app's cumulative eviction count and the notice row's epoch.

    Returns ``(dropped, notice_epoch_s)``, or ``(0, None)`` when the spool has
    never evicted. The notice is a row like any other, appended in order, so
    the last match is the current value.

    A read that is neither "matched" nor "matched nothing" raises, so a broken
    channel stays UNKNOWN instead of publishing a calm zero. Two device facts
    drive the shape of the command: this workstation's adb reports 0 for any
    device-side status, so the status is echoed as an explicit probe line; and
    a device-side failure (run-as denied, unreadable path) exits 1 -- the same
    status as "no match" -- so stderr is merged into the channel and any
    diagnostic line fails the read rather than reading as zero evictions.
    """
    try:
        out = _run(argv, serial,
                   f"run-as org.androidbody grep -a -o '{OVERFLOW_NOTICE_BRE}' "
                   f"{spool_path} 2>&1; echo '{OVERFLOW_PROBE_MARKER}'$?",
                   timeout)
        lines = out.splitlines()
        if not lines or not lines[-1].startswith(OVERFLOW_PROBE_MARKER):
            raise ValueError(f"no overflow probe in output: {out[:60]!r}")
        status = lines[-1][len(OVERFLOW_PROBE_MARKER):].strip()
        reported = [line.strip() for line in lines[:-1] if line.strip()]
        if status == "1":
            if reported:
                raise ValueError(
                    f"overflow grep reported no match but said {reported[0][:60]!r}")
            return 0, None
        if status != "0":
            raise ValueError(f"overflow grep status {status!r}")
        dropped, notice_epoch = 0, None
        for line in reported:
            match = OVERFLOW_NOTICE_RE.fullmatch(line)
            if not match:
                raise ValueError(f"unparsable overflow line {line[:60]!r}")
            notice_epoch, dropped = int(match.group(1)), int(match.group(2))
        if notice_epoch is None:
            raise ValueError("overflow grep matched nothing parsable")
        return dropped, notice_epoch
    except (OSError, subprocess.SubprocessError, RuntimeError, ValueError) as e:
        raise RuntimeError(f"overflow-notice-failed: {e}") from e


def _phone_ts_to_epoch(phone_ts):
    """Convert a phone-local ISO timestamp to a naive epoch (seconds).

    The phone clock is ~25s behind host; this returns the phone's own epoch,
    and the consumer applies the measured offset to compare with host time.
    """
    import datetime
    try:
        dt = datetime.datetime.strptime(phone_ts, "%Y-%m-%dT%H:%M:%S")
        return dt.replace(tzinfo=datetime.timezone.utc).timestamp()
    except ValueError as e:
        raise ValueError(f"unexpected spool timestamp: {phone_ts!r}") from e


def spool_document(label, result, now, validity=300.0):
    """The bounded spool-summary document for ``result``, or an unavailable one.

    ``result`` is ``None`` when the spool could not be read; the document then
    carries ``status="unavailable"`` and null counts rather than fabricated data.
    """
    observed = float(time.time() if now is None else now)
    if result is None:
        return {
            "node": label, "source": SOURCE, "method": METHOD,
            "status": "unavailable", "observed_at_epoch_s": observed,
            "validity_seconds": float(validity),
            "spool_bytes": None, "retention_window_s": None,
            "oldest_row_epoch_s": None, "newest_row_epoch_s": None,
            "counts": None, "light_buckets": None, "overflow": None,
            "reason": "spool read failed",
        }
    return {
        "node": label, "source": SOURCE, "method": METHOD,
        "status": "ok", "observed_at_epoch_s": observed,
        "validity_seconds": float(validity),
        "spool_bytes": result["spool_bytes"],
        "retention_window_s": round(result["retention_window_s"], 1),
        "oldest_row_epoch_s": round(result["oldest_row_epoch_s"], 1),
        "newest_row_epoch_s": round(result["newest_row_epoch_s"], 1),
        "counts": result["counts"],
        "light_buckets": result["light_buckets"],
        "overflow": result["overflow"],
        "reason": None,
    }


def assert_bounded(document):
    """Reject a document that is not the agreed bounded shape."""
    keys = set(document)
    if keys != set(ALLOWED_KEYS):
        raise ValueError(f"unexpected spool-summary keys: {sorted(keys ^ set(ALLOWED_KEYS))}")
    if document["status"] not in STATUSES:
        raise ValueError(f"unknown spool-summary status: {document['status']!r}")
    if document["status"] == "unavailable":
        if any(document[key] is not None for key in
               ("spool_bytes", "retention_window_s", "oldest_row_epoch_s",
                "newest_row_epoch_s", "counts", "light_buckets", "overflow")):
            raise ValueError("unavailable spool-summary document carries data")
    else:
        if not isinstance(document["spool_bytes"], int) or document["spool_bytes"] <= 0:
            raise ValueError("ok spool-summary document is missing spool_bytes")
        if not isinstance(document["counts"], dict):
            raise ValueError("ok spool-summary document is missing counts")
        if not isinstance(document["light_buckets"], dict):
            raise ValueError("ok spool-summary document is missing light_buckets")
        overflow = document["overflow"]
        dropped = overflow.get("dropped") if isinstance(overflow, dict) else None
        notice = (overflow.get("notice_epoch_s")
                  if isinstance(overflow, dict) else None)
        if (not isinstance(overflow, dict)
                or set(overflow) != {"dropped", "notice_epoch_s"}
                or not isinstance(dropped, int) or isinstance(dropped, bool)
                or dropped < 0
                or not (notice is None
                        or (isinstance(notice, int) and not isinstance(notice, bool)))):
            raise ValueError("ok spool-summary document has a malformed overflow field")
        if (dropped > 0) != (notice is not None):
            raise ValueError("overflow dropped and notice_epoch_s disagree")
    if document["reason"] is not None and (
        not isinstance(document["reason"], str)
        or len(document["reason"]) > MAX_REASON_CHARS
    ):
        raise ValueError("spool-summary reason is not a bounded string")


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


def default_output(site, label):
    return Path(site) / "body" / f"spool-summary-{label}.json"


def run_once(args):
    """Read once, publish one document, print one bounded line. Exit status."""
    output = Path(args.output) if args.output else default_output(args.site, args.label)
    try:
        argv = adb_argv(args.adb)
        spool_dir = _find_spool_dir(argv, args.serial, args.timeout)
        spool_path = f"files/observations/{spool_dir}/observations.spool"
        counts = {}
        for kind in sorted(ALLOWED_KINDS):
            counts[kind] = _count_kind(argv, args.serial, spool_path, kind, args.timeout)
        light_buckets = {}
        for bucket_name, pattern in LIGHT_BUCKETS:
            light_buckets[bucket_name] = _count_light_bucket(
                argv, args.serial, spool_path, pattern, args.timeout)
        spool_bytes = _spool_size(argv, args.serial, spool_path, args.timeout)
        oldest, newest, window = _retention_window(
            argv, args.serial, spool_path, args.timeout)
        dropped, notice_epoch = _overflow_notice(
            argv, args.serial, spool_path, args.timeout)
        result = {
            "spool_bytes": spool_bytes,
            "retention_window_s": window,
            "oldest_row_epoch_s": oldest,
            "newest_row_epoch_s": newest,
            "counts": counts,
            "light_buckets": light_buckets,
            "overflow": {"dropped": dropped, "notice_epoch_s": notice_epoch},
        }
        reason = None
    except (OSError, subprocess.SubprocessError, RuntimeError, ValueError) as error:
        result = None
        reason = str(error)[:MAX_REASON_CHARS]
    document = spool_document(args.label, result, None, validity=args.validity)
    if reason is not None:
        document["reason"] = reason
    publish(output, document)
    if result is None:
        print(f"spool-summary {args.label}: unavailable ({reason}) -> {output}")
    else:
        total_rows = sum(result["counts"].values())
        light_total = result["counts"].get("light", 0)
        print(f"spool-summary {args.label}: {total_rows} rows, light={light_total}, "
              f"{result['spool_bytes']} B, window={result['retention_window_s']}s, "
              f"overflow dropped={result['overflow']['dropped']} -> {output}")
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--site", required=True,
                        help="site root (writes body/spool-summary-<node>.json)")
    parser.add_argument("--serial", required=True, help="adb serial of the node")
    parser.add_argument("--label", default="note3")
    parser.add_argument("--adb", default="adb", help="adb command; may be multi-word")
    parser.add_argument("--timeout", type=float, default=30.0, help="per-command seconds")
    parser.add_argument("--validity", type=float, default=300.0,
                        help="seconds the reading stays current for its consumer")
    parser.add_argument("--output", help="explicit document path (default: site/body/)")
    args = parser.parse_args(argv)
    if args.timeout <= 0:
        parser.error("--timeout must be positive")
    if args.validity <= 0:
        parser.error("--validity must be positive")
    # One document per invocation: the 5-min cadence is the systemd timer's job.
    return run_once(args)


if __name__ == "__main__":
    sys.exit(main())
