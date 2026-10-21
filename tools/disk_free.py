#!/usr/bin/env python3
# SPDX-License-Identifier: CC0-1.0
"""Report the free bytes on the volume holding this plant's site against a bound.

The host volume is 99% used with ~15 GiB free and a ~7 GiB/day drain measured by
``android-body/discover`` (DM 123190). Exhaustion breaks every plant on the host,
including this plant's record store and the queue files the rendezvous appends to.
The *trend* is the core scan's own ``sense.disk.trend``
(``mishe_tauftauf/discovery.py``: trailing-24h minimum, per-window slopes, and a
projection published only when the windows agree); it needs the retained scan
corpus and runs on the discover channel, so a plant-local check that only names
the free bytes had no caller anywhere. This tool is that point check.

It takes the caller's own ``df -B1 -P`` table on stdin -- the same split as
``tools/queue_capacity.py`` and ``tools/tailnet_peer.py``, so the caller owns the
invocation and its failure handling -- and compares one number against a bound.

The default bound is the core scan's own *near* threshold, 20 GiB
(``_DISK_TREND_NEAR_BYTES``), not its 10 GiB *floor* (``_DISK_TREND_FLOOR_BYTES``,
the countdown target): the core declares ``drift`` when the trailing-24h minimum
is below the near threshold, so a point at or below 20 GiB agrees with the verdict
the dashboard already publishes instead of contradicting it. The threshold is
policy, not measurement, so it is overridable with ``--bound-bytes``.

An unreadable table is UNKNOWN (exit 2), never a pass: an absent ``df``, an error
line in place of a table, more than one filesystem row, or a non-numeric
``Available`` column all read as "the reading is unavailable".

Usage: ``df -B1 -P / | disk_free.py [--bound-bytes N]``

Exit: 0 free above the bound, 1 at or below it, 2 the reading is unavailable.
"""

import argparse
import sys

#: ``_DISK_TREND_NEAR_BYTES`` in the pinned core's ``discovery.py``.
DEFAULT_BOUND_BYTES = 20 * 1024 * 1024 * 1024

#: The header row GNU ``df -B1 -P`` prints. It is skipped only when it matches
#: exactly, so a foreign header is not silently mistaken for a filesystem row.
_HEADER = ("Filesystem", "1-blocks")


def _positive_or_none(text):
    """*text* as a positive int, or None when it is not one.

    A bound that is not a positive integer is a caller error, but it is still an
    unavailable *reading* for this check: the caller owns the threshold, so the
    tool prints its own UNKNOWN line rather than argparse's usage, which would
    leave the check's output with no verdict at all.
    """
    try:
        value = int(text)
    except (TypeError, ValueError):
        return None
    return value if value > 0 else None


def parse_free(text):
    """``(mount, available, reason)`` from one ``df -B1 -P`` table.

    The table is the caller's, so it is read as given: a header row is skipped
    when present, exactly one filesystem row is required, and the ``Available``
    column (index 3) must be a non-negative integer. Anything else yields
    ``(None, None, reason)`` -- the caller reports UNKNOWN, never a bound.
    """
    rows = [line.split() for line in text.splitlines() if line.strip()]
    if not rows:
        return None, None, "df printed no table"
    if tuple(rows[0][:2]) == _HEADER:
        rows = rows[1:]
    if len(rows) != 1:
        return None, None, f"df reported {len(rows)} filesystem rows; pass one path"
    row = rows[0]
    if len(row) < 5:
        return None, None, "df row has no Available column"
    try:
        available = int(row[3])
    except ValueError:
        return None, None, "df Available column is not a number"
    if available < 0:
        return None, None, "df Available column is negative"
    return (row[5] if len(row) > 5 else ""), available, None


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Free bytes on the caller's df table against a bound.")
    parser.add_argument(
        "--bound-bytes", default=str(DEFAULT_BOUND_BYTES), metavar="N",
        help="RED when the available bytes are at or below this bound "
             f"(default: {DEFAULT_BOUND_BYTES}, the core scan's near threshold)")
    args = parser.parse_args(argv)
    bound = _positive_or_none(args.bound_bytes)
    if bound is None:
        print(f"UNKNOWN disk free (bound-bytes {args.bound_bytes!r} "
              "is not a positive integer)")
        return 2
    mount, available, reason = parse_free(sys.stdin.read())
    if available is None:
        print(f"UNKNOWN disk free ({reason})")
        return 2
    status = "RED" if available <= bound else "GREEN"
    size = f"{available}B/{available / 2**30:.1f}GiB"
    limit = f"{bound}B/{bound / 2**30:.1f}GiB"
    where = f" on {mount}" if mount else ""
    if status == "RED":
        percent = available * 100.0 / bound
        print(f"{status:<6} disk free {size}{where} at/below the bound {limit} ({percent:.0f}%)")
    else:
        # The fraction of the bound is only read when it can be at or under 100%;
        # a free level many times the bound is the size, not a ratio.
        print(f"{status:<6} disk free {size}{where} (bound {limit})")
    return 1 if status == "RED" else 0


if __name__ == "__main__":
    sys.exit(main())
