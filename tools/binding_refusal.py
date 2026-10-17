#!/usr/bin/env python3
# SPDX-License-Identifier: CC0-1.0
"""Read this site's binding-refusal audit log and report recent refusals.

The pinned core's ``validate_home_binding`` writes one JSON line per refused
cross-plant command to ``<bound-site>/logs/binding-refusal-audit.jsonl``
(``observations.py`` ``_audit_binding_refusal``). A refusal means a mind
followed a documented cross-plant command the guard rejects -- a dead route.
Nothing reads that log, so the class surfaces only when a mind happens to
open the file.

Measured 2026-10-17: this plant's own panes produced 12 refusals in
09:00-11:09Z (newest 3 min before this detector was written), because the
charter fix (witness wake 106367) is on disk but the running panes still
carry the pre-edit delivery. The core site's own log held 14 refusals, last
00:03Z -- the same dead form, before the fix.

This tool makes the class legible: count refusals within a reporting window
and report the age of the newest. RED when the window holds a refusal (a
documented route is being refused now); UNKNOWN when the log is missing or
unreadable, never a pass. Read-only: opens the log read-only, writes nothing.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

#: Where the guard writes the audit log, relative to the bound site.
AUDIT_REL = Path("logs") / "binding-refusal-audit.jsonl"

#: Default reporting window in hours. A refusal REDs the check for this long:
#: long enough that a single probe from a stale pane does not fade before a
#: mind sees it, short enough that a re-delivered site heals.
DEFAULT_WINDOW_HOURS = 24.0

GREEN, RED, UNKNOWN = "GREEN", "RED", "UNKNOWN"


def parse_ts(text):
    """Parse an ISO-8601 timestamp, or None when it is not one."""
    try:
        return datetime.fromisoformat(text)
    except (TypeError, ValueError):
        return None


def read_refusals(path):
    """Yield ``(entry, error)`` per line; exactly one of the two is None."""
    try:
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    yield json.loads(line), None
                except ValueError as exc:
                    yield None, f"malformed JSON: {exc}"
    except OSError as exc:
        yield None, f"unreadable: {exc}"


def check(site, now=None, window_hours=DEFAULT_WINDOW_HOURS):
    """``(rc, lines)`` for this site's binding refusals: 0 GREEN, 1 RED, 2 UNKNOWN."""
    now = datetime.now(timezone.utc) if now is None else now
    path = Path(site) / AUDIT_REL
    if not path.is_file():
        return 2, [f"{UNKNOWN:<7} binding refusals (no audit log at {path})"]
    total = 0
    recent = []
    errors = []
    for entry, error in read_refusals(path):
        if error is not None:
            errors.append(error)
            continue
        total += 1
        if not isinstance(entry, dict):
            errors.append(f"entry is {type(entry).__name__}, not an object")
            continue
        ts = parse_ts(entry.get("ts"))
        if ts is None:
            errors.append(f"malformed ts: {entry.get('ts')!r}")
            continue
        age = (now - ts).total_seconds()
        if 0 <= age <= window_hours * 3600:
            recent.append((entry, age))
    if errors:
        return 2, [f"{UNKNOWN:<7} binding refusals ({'; '.join(errors[:3])})"]
    if not recent:
        return 0, [f"{GREEN:<7} binding refusals: 0 in {window_hours:.0f}h "
                   f"({path}, {total} total)"]
    newest_age = min(age for _, age in recent)
    attempted = sorted({str(entry.get("attempted_home")) for entry, _ in recent})
    return 1, [f"{RED:<7} binding refusals: {len(recent)} in {window_hours:.0f}h, "
               f"newest {newest_age / 60:.1f}m ago "
               f"(attempted: {', '.join(attempted)}; {path}, {total} total)"]


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Report recent cross-plant binding refusals from this site's audit log.")
    parser.add_argument("--site", type=Path, required=True,
                        help="this site's home (the bound site whose log is read)")
    parser.add_argument("--window", type=float, default=DEFAULT_WINDOW_HOURS,
                        help="reporting window in hours (default 24)")
    args = parser.parse_args(argv)
    rc, lines = check(args.site, window_hours=args.window)
    for line in lines:
        print(line)
    return rc


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
