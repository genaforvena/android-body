#!/usr/bin/env python3
# SPDX-License-Identifier: CC0-1.0
"""Detect a mind channel stranded at the clear step: settled, never cleared.

Measured 2026-10-17T09:38Z: ``android-body-genome.service`` and
``android-body-senses.service`` were in a permanent clear-HOLD from the
08:47:24Z boot -- 133 and 132 ``HOLD seed <role> clear: rotated mind process
changed; reconcile clear`` lines in 45 minutes, both minds ``pending=none``
while their peers held wakes. ``wall.tick`` (pinned core ``wall.py``) creates no
wake while ``settled != cleared``, so a clear that cannot commit is a mind that
can never be woken again; the observed instance left two minds dead 47 minutes.

``wall.clear`` writes ``checks/wall-clear-<role>-<settled>.json`` with
``phase`` ``rotating`` before the respawn and ``rotated`` after it, and commits
(``committed``) inside the same call, under the seed lock. Every stranded exit
in ``wall.clear`` raises without a further write, so the journal's mtime freezes
at the phase it reached: an unsettled journal past the grace below is not in
flight, the guard is refusing every tick. The observed instance: both journals
named the pre-replant launcher (``PYTHONPATH=.../releases/db764959.../src``)
while the live panes ran the pin the 08:47Z kernel-sync replant installed
(``14963f76fc38``), and ``wall._rotated_by_resurrection``'s exact-launcher
comparison can never match again -- its documented recovery (a hand
reconciliation) is the only way out.

Nothing else in ``tools/health-check.sh`` reads this state, so the check
reported ``HEALTH: GREEN`` over two dead minds for 47 minutes. The pinned core
does compute the same stall for its own witness view
(``seed_culture_views._clear_journal_stalls``, ``CLEAR_JOURNAL_STALL_S``); this
tool is the plant's own verdict on its own journals, and takes that constant's
value and comparison rather than inventing a second threshold. It reads the
journals' ``phase`` and mtime only: no tmux, no feed scan, no wait. RED names
each stranded journal with the age that measured it; UNKNOWN never passes. It
cannot see a mind starved by a *committed* clear or by a wake the sensor never
assigned -- those are different signals with different resolvers.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

#: ``seed run --interval`` for this plant's channels (5 s). A rotation and its
#: feed commit happen inside one ``wall.clear`` call, so the grace below is
#: counted in these intervals rather than in wall-clock guesswork.
SUPERVISOR_INTERVAL_SECONDS = 5.0

#: Grace before an unsettled journal is called stranded, and the comparison
#: applied to it. Both are the pinned core's own stall predicate
#: (``seed_culture_views.CLEAR_JOURNAL_STALL_S = 60.0``, ``age < grace``
#: continues): a rotation normally commits inside one supervisor tick, so a
#: journal still unsettled after a minute means the receipt guard keeps
#: rejecting the live pane. The core's witness CLEAR STALL budget is 120 s and
#: the supervisor's own ``--clear-grace-seconds`` is 30 s; 60 s is the tighter
#: of the two and is 12 supervisor intervals.
STRANDED_AFTER_SECONDS = 60.0

#: The phases ``wall.clear`` writes before it commits. ``committed`` is done.
UNSETTLED_PHASES = ("rotating", "rotated")


def read_journal(path):
    """``(role, settled, phase)`` for a clear journal, or None when unreadable.

    The journal's own fields are authoritative; the file name is only the
    ``wall.clear`` naming convention. A journal that does not decode, or that
    names no phase, is unknown rather than settled.
    """
    try:
        body = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(body, dict):
        return None
    phase = body.get("phase")
    if not isinstance(phase, str):
        return None
    role = body.get("role")
    settled = body.get("settled")
    return (role if isinstance(role, str) else path.name, settled, phase)


def journal_report(path, *, now, grace=STRANDED_AFTER_SECONDS):
    """``(status, unsettled, detail)`` for one clear journal.

    RED when an unsettled journal has reached *grace*, GREEN while a rotation is
    in flight (``unsettled`` true, so the caller can print it), and GREEN for a
    committed journal of any age (the bulk of ``checks/`` is history). An
    unreadable or phase-less journal is UNKNOWN, never a pass.
    """
    try:
        age = now - path.stat().st_mtime
    except OSError:
        return "UNKNOWN", False, f"{path.name} unreadable (stat failed)"
    parsed = read_journal(path)
    if parsed is None:
        return "UNKNOWN", False, f"{path.name} unreadable (no decodable phase)"
    role, settled, phase = parsed
    label = f"channel clear {role} settled={settled} phase={phase}"
    if phase not in UNSETTLED_PHASES:
        return "GREEN", False, f"{label} age={age:.0f}s (committed)"
    if age >= grace:
        return "RED", True, (
            f"{label} age={age:.0f}s reaches the {grace:.0f}s "
            f"({grace / SUPERVISOR_INTERVAL_SECONDS:.0f} x {SUPERVISOR_INTERVAL_SECONDS:.0f}s "
            "supervisor interval) clear grace: the supervisor cannot commit this clear "
            "and creates no new wake")
    return "GREEN", True, f"{label} age={age:.0f}s (in flight)"


def journal_paths(site):
    """Every clear journal in *site*, newest first, or None when unreadable."""
    checks = Path(site) / "checks"
    if not checks.is_dir():
        return None
    try:
        return sorted(checks.glob("wall-clear-*.json"),
                      key=lambda path: path.stat().st_mtime, reverse=True)
    except OSError:
        return None


def main(argv=None, *, now=None):
    parser = argparse.ArgumentParser(
        description="Detect a mind channel stranded at the clear step (settled, never cleared).")
    parser.add_argument("--site", required=True, help="site root (reads checks/wall-clear-*.json)")
    parser.add_argument("--grace", type=float, default=STRANDED_AFTER_SECONDS,
                        help="seconds an unsettled clear journal may stay unsettled (default: 60)")
    parser.add_argument("--all", action="store_true",
                        help="print every journal, not only the unsettled ones")
    args = parser.parse_args(argv)
    paths = journal_paths(args.site)
    if paths is None:
        print(f"UNKNOWN channel clear: no readable checks/ directory under {Path(args.site).resolve()}")
        return 2
    if not paths:
        print("UNKNOWN channel clear: no wall-clear journal in checks/ "
              "(no channel has rotated yet; not a pass)")
        return 2

    now = time.time() if now is None else now
    failed = unknown = unsettled = 0
    for path in paths:
        status, pending, detail = journal_report(path, now=now, grace=args.grace)
        failed += 1 if status == "RED" else 0
        unknown += 1 if status == "UNKNOWN" else 0
        unsettled += 1 if pending else 0
        if status != "GREEN" or args.all or pending:
            print(f"{status:<6} {detail}")
    # The summary asserts a fact about every journal, so it is printed only when
    # every journal was readable: an all-UNKNOWN run must not carry a GREEN line
    # (health-check.sh echoes this stdout verbatim before its own verdict).
    if not unsettled and not unknown:
        print(f"GREEN  channel clear: 0 of {len(paths)} journals unsettled "
              f"(newest {paths[0].name}, grace {args.grace:.0f}s)")
    return 1 if failed else (2 if unknown else 0)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
