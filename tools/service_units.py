#!/usr/bin/env python3
# SPDX-License-Identifier: CC0-1.0
"""Report each covered android-body unit's systemd load and active state.

``tools/health-check.sh`` §1 asked only ``systemctl is-active`` for three units
and reported ``HEALTH: GREEN`` through a whole-plant failure on 2026-10-16: the
core-generated ``android-body-silence.service`` fragment had lost its ``[Unit]``
and ``[Service]`` sections, so systemd loaded it as ``bad-setting`` ("Service has
no ExecStart=, ExecStop=, or SuccessAction=. Refusing.") and refused every
restart. The unit still read ``active (running)`` from an earlier valid
generation, so an activity-only check cannot see it -- but the core replant that
restarts each channel held on the refusal (``plant.py`` ``reconcile_services``
raises ``CalledProcessError``) and retried in a loop, restarting every channel
service with it. A load-state read is the fact that separates the two.

The LOAD column alone is not enough either. On 2026-10-16
``android-body-crosssite-check.service`` sat at ``loaded failed`` for over nine
hours -- a health-owned detector whose ``Type=oneshot`` unit is deliberately left
``failed`` so a detected cross-site CLI selection stays visible instead of being
retried away -- while this tool read it ``GREEN`` and so did the dashboard's own
service line. The ACTIVE column is the fact that separates a failed oneshot from a
healthy one; ``inactive``/``dead`` is the normal between-runs state of a
timer-triggered oneshot and must stay GREEN.

The caller owns the systemctl invocation and its failure handling -- the same
split as ``tools/queue_capacity.py`` and ``tools/tailnet_peer.py`` -- and pipes
``systemctl --user list-units 'android-body-*.service' --all --full --plain
--no-legend`` on stdin. An unreadable or empty dump is UNKNOWN (exit 2), never a
pass: no unit line means the reading failed, not that every unit is healthy.

Usage: ``systemctl --user list-units 'android-body-*.service' --all --full
         --plain --no-legend | service_units.py``

Exit: 0 every listed unit loads and none failed, 1 at least one does not, 2 no
unit could be read.
"""

import sys

#: The only LOAD value that means systemd accepted the fragment. Every other
#: value (``bad-setting``, ``masked``, ``error``, ``not-found``, ``alias``) is a
#: state in which the unit cannot be started or restarted.
LOADED = "loaded"

#: The only ACTIVE value that means the unit's last start failed. A oneshot that
#: is simply between timer runs reads ``inactive``/``dead``, which is normal.
FAILED = "failed"


def parse_units(text):
    """``[(unit, load, active, sub)]`` for the ``.service`` rows of a ``list-units`` dump.

    Rows are ``UNIT LOAD ACTIVE SUB DESCRIPTION``; the description may contain
    spaces, so only the first four fields are read. Rows that are not service
    units, or that carry fewer than four fields, are dropped rather than guessed.
    """
    units = []
    for line in text.splitlines():
        fields = line.split()
        if len(fields) < 4 or not fields[0].endswith(".service"):
            continue
        units.append((fields[0], fields[1], fields[2], fields[3]))
    return units


def verdict(load, active=None):
    """``"GREEN"`` when systemd accepted the fragment and the unit did not fail.

    ``active`` is optional so a caller holding only the LOAD column still gets the
    load-state verdict; ``inactive``/``dead`` is not a failure.
    """
    if load != LOADED or active == FAILED:
        return "RED"
    return "GREEN"


def main(argv):
    if len(argv) > 1:
        print("usage: list-units output on stdin; no arguments", file=sys.stderr)
        return 2
    units = parse_units(sys.stdin.read())
    if not units:
        print("UNKNOWN no unit row could be read from the list-units dump")
        return 2
    failed = False
    for unit, load, active, sub in units:
        state = verdict(load, active)
        if state == "RED":
            failed = True
            if load != LOADED:
                print(f"RED    unit {unit} load state {load} active {active} sub {sub}")
            else:
                print(f"RED    unit {unit} active state {active} sub {sub} (last start failed)")
        else:
            print(f"GREEN  unit {unit} loads active={active} sub={sub}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
