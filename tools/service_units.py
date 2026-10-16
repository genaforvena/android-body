#!/usr/bin/env python3
# SPDX-License-Identifier: CC0-1.0
"""Report each covered android-body unit's systemd load state.

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

The caller owns the systemctl invocation and its failure handling -- the same
split as ``tools/queue_capacity.py`` and ``tools/tailnet_peer.py`` -- and pipes
``systemctl --user list-units 'android-body-*.service' --all --full --plain
--no-legend`` on stdin. An unreadable or empty dump is UNKNOWN (exit 2), never a
pass: no unit line means the reading failed, not that every unit is healthy.

Usage: ``systemctl --user list-units 'android-body-*.service' --all --full
         --plain --no-legend | service_units.py``

Exit: 0 every listed unit loads, 1 at least one does not, 2 no unit could be
read.
"""

import sys

#: The only LOAD value that means systemd accepted the fragment. Every other
#: value (``bad-setting``, ``masked``, ``error``, ``not-found``, ``alias``) is a
#: state in which the unit cannot be started or restarted.
LOADED = "loaded"


def parse_units(text):
    """``[(unit, load)]`` for the ``.service`` rows of a ``list-units`` dump.

    Rows are ``UNIT LOAD ACTIVE SUB DESCRIPTION``; the description may contain
    spaces, so only the first two fields are read. Rows that are not service
    units, or that carry fewer than two fields, are dropped rather than guessed.
    """
    units = []
    for line in text.splitlines():
        fields = line.split()
        if len(fields) < 2 or not fields[0].endswith(".service"):
            continue
        units.append((fields[0], fields[1]))
    return units


def verdict(load):
    """``"GREEN"`` when systemd accepted the fragment, else ``"RED"``."""
    return "GREEN" if load == LOADED else "RED"


def main(argv):
    if len(argv) > 1:
        print("usage: list-units output on stdin; no arguments", file=sys.stderr)
        return 2
    units = parse_units(sys.stdin.read())
    if not units:
        print("UNKNOWN no unit row could be read from the list-units dump")
        return 2
    failed = False
    for unit, load in units:
        state = verdict(load)
        if state == "RED":
            failed = True
            print(f"RED    unit {unit} load state {load}")
        else:
            print(f"GREEN  unit {unit} loads")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
