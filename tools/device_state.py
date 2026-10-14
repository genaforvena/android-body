#!/usr/bin/env python3
# SPDX-License-Identifier: CC0-1.0
"""Read-only classification of the Note3 app's durable session state.

From the rendezvous queue alone, three very different situations look identical:
the app is OFF, the app is in a durably enabled ON session with *collect-only*
selected (which issues no HTTP at all by design), or delivery has failed. This
module separates them from already-read device text so a silent producer is not
misreported as "OFF" or "app dead".

It never needs, reads or prints the endpoint or the node secret. The durable-ON
test follows the app's ``Settings.desiredOn()``: ``desired_on==true`` AND a
``run-enabled`` marker of the form ``cursor_<sha256>``. The exact marker/endpoint
match is confirmed only when the endpoint's ``cursor_*`` preference is on record
(written only after an action executes); a well-formed but unmatched marker is
reported as enabled with ``marker_match=unconfirmed`` because ``Settings.disarm``
deletes the marker before clearing the preference and the UI disarms before an
endpoint edit.
"""

from __future__ import annotations

import argparse
import re
import shlex
import subprocess
import sys
from typing import NamedTuple

OFF = "OFF"
ON_SENDING = "ON_SENDING"
ON_COLLECT_ONLY = "ON_COLLECT_ONLY"
ON_NOT_RUNNING = "ON_NOT_RUNNING"
UNKNOWN = "UNKNOWN"

#: Preference keys that must never be surfaced by this tool.
SECRET_KEYS = frozenset({"secret", "endpoint"})

#: The run-enabled marker holds ``cursor_<sha256(endpoint)>`` (Settings.cursorKey).
_MARKER = re.compile(r"cursor_[0-9a-f]{64}\Z")

_VALUE_ENTRY = re.compile(
    r'<(?P<kind>boolean|string|long|int|float)\s+name="(?P<name>[^"]*)"'
    r'\s+value="(?P<value>[^"]*)"'
)
_TEXT_ENTRY = re.compile(
    r'<string\s+name="(?P<name>[^"]*)">(?P<text>[^<]*)</string>'
)


class DeviceState(NamedTuple):
    state: str
    desired_on: bool
    collect_only: bool
    run_enabled: bool
    marker_match_confirmed: bool
    process_present: bool
    service_foreground: bool
    reasons: tuple[str, ...]

    def line(self, label: str) -> str:
        return (
            f"device-state {label}: {self.state}"
            f" desired_on={str(self.desired_on).lower()}"
            f" collect_only={str(self.collect_only).lower()}"
            f" run_enabled={str(self.run_enabled).lower()}"
            f" marker_match={'confirmed' if self.marker_match_confirmed else 'unconfirmed'}"
            f" process={'present' if self.process_present else 'absent'}"
            f" service={'foreground' if self.service_foreground else 'not-foreground'}"
        )


def parse_prefs(xml_text: str) -> dict:
    """Return non-secret preference entries as {name: raw value text}.

    Secret and endpoint values are dropped, not merely hidden from output.
    """
    prefs: dict = {}
    for match in _VALUE_ENTRY.finditer(xml_text or ""):
        name = match.group("name")
        if name in SECRET_KEYS:
            continue
        prefs[name] = match.group("value").strip()
    for match in _TEXT_ENTRY.finditer(xml_text or ""):
        name = match.group("name")
        if name in SECRET_KEYS:
            continue
        prefs.setdefault(name, match.group("text").strip())
    return prefs


def classify(
    prefs: dict,
    marker_text: str,
    process_present: bool,
    service_foreground: bool,
) -> DeviceState:
    """Classify the durable session state from already-read device text."""
    desired_on = prefs.get("desired_on", "").strip().lower() == "true"
    collect_only = prefs.get("collect_only", "").strip().lower() == "true"
    marker = (marker_text or "").strip()
    # The app (Settings.desiredOn) compares the marker to cursorKey(endpoint). That
    # hash needs the secret endpoint, which this tool never reads, so the match is
    # confirmed only when the endpoint's cursor_* preference is on record -- and the
    # app writes that key only in BodyService.execute(), which collect-only never
    # reaches. A well-formed marker is therefore accepted as enabled on its own:
    # Settings.disarm() deletes the marker before clearing the preference, and the
    # UI disarms before an endpoint edit, so a present marker belongs to the saved
    # endpoint. A malformed or absent marker is the app's durable-OFF state.
    run_enabled = desired_on and bool(_MARKER.match(marker))
    match_confirmed = run_enabled and marker in {
        name for name in prefs if name.startswith("cursor_")
    }

    def state(name, reasons=()):
        return DeviceState(
            name, desired_on, collect_only, run_enabled, match_confirmed,
            process_present, service_foreground, tuple(reasons),
        )

    if not run_enabled:
        reason = (
            "desired_on=false" if not desired_on
            else "run-enabled marker absent or malformed"
        )
        return state(OFF, [reason])
    match_note = (
        "marker matches the recorded endpoint cursor"
        if match_confirmed
        else "marker well-formed but unmatched: no cursor_* preference recorded yet "
             "(expected for collect-only or a session that has executed no action)"
    )
    if not process_present:
        return state(ON_NOT_RUNNING, [match_note, "durably enabled; app process absent (restore expected)"])
    if collect_only:
        return state(ON_COLLECT_ONLY, [match_note, "collect-only: no HTTP by design"])
    return state(ON_SENDING, [match_note])


def adb_argv(adb: str) -> list:
    """Split an adb command so a wrapper (e.g. ``rtk proxy adb``) is usable."""
    return shlex.split(adb) or ["adb"]


def _adb(argv: list, args: list, timeout: float, allow_missing: bool = False) -> str:
    result = subprocess.run(
        [*argv, *args], capture_output=True, text=True, timeout=timeout, check=False
    )
    if result.returncode != 0:
        if allow_missing:
            # An absent file is meaningful: Settings.disarm() deletes the marker.
            return ""
        raise RuntimeError(f"{' '.join(argv)} {' '.join(args)} rc={result.returncode}")
    return result.stdout


def read_device(
    adb: str,
    serial: str,
    package: str,
    timeout: float,
) -> DeviceState:
    """Read the device over adb and classify. Raises RuntimeError when unreadable."""
    argv = adb_argv(adb)
    devices = _adb(argv, ["devices"], timeout)
    attached = any(
        line.split()[:2] == [serial, "device"] for line in devices.splitlines()
    )
    if not attached:
        raise RuntimeError(f"device {serial} not attached/authorized")

    base = f"/data/data/{package}"
    prefs_text = _adb(
        argv,
        ["-s", serial, "shell", f"run-as {package} cat {base}/shared_prefs/body.xml"],
        timeout,
    )
    marker_text = _adb(
        argv,
        ["-s", serial, "shell", f"run-as {package} cat {base}/files/run-enabled"],
        timeout,
        allow_missing=True,
    )
    processes = _adb(argv, ["-s", serial, "shell", "ps"], timeout)
    process_present = any(
        row.split()[-1] == package for row in processes.splitlines()[1:] if row.split()
    )
    services = _adb(
        argv,
        ["-s", serial, "shell", f"dumpsys activity services {package}"],
        timeout,
    )
    service_foreground = "isForeground=true" in services
    return classify(
        parse_prefs(prefs_text), marker_text, process_present, service_foreground
    )


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--serial", required=True, help="adb serial of the node")
    parser.add_argument("--package", default="org.androidbody")
    parser.add_argument("--label", default="note3")
    parser.add_argument("--adb", default="adb", help="adb command; may be multi-word (default: adb)")
    parser.add_argument("--timeout", type=float, default=15.0, help="per-command seconds")
    args = parser.parse_args(argv)

    try:
        device = read_device(args.adb, args.serial, args.package, args.timeout)
    except (OSError, subprocess.SubprocessError, RuntimeError) as error:
        print(f"device-state {args.label}: {UNKNOWN} ({error})")
        return 3
    print(device.line(args.label))
    for reason in device.reasons:
        print(f"  {reason}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
