#!/usr/bin/env python3
# SPDX-License-Identifier: CC0-1.0
"""Report each rendezvous queue against the byte cap the live unit runs with.

``tools/health-check.sh`` §5 printed each queue's byte size with no bound, so a
queue quietly approaching its cap read exactly like an empty one. The rendezvous
appends forever -- ``rendezvous/minimal-server/README.md`` states "no automatic
log retention/deletion" -- and the only relief is an operator raising
``--max-queue-bytes`` or rotating to a new node ID. Reaching the cap is a dated
event, not a silent one: ``Queue.append`` then raises ``507 queue_full`` (the
phone's observations stop being accepted) and ``Queue.__init__`` raises on the
next start, so the rendezvous cannot come back up until the oversized queue is
rotated. This tool dates the fill instead of leaving it to be discovered at the
outage.

The cap is read from the live unit's ``ExecStart``
(``systemctl --user show android-body-rendezvous.service -p ExecStart``), which
the caller pipes on stdin so it owns the systemctl invocation and its failure
handling -- the same split as ``tools/tailnet_peer.py``. ``server.py``'s
``DEFAULT_QUEUE_BYTES`` is deliberately *not* a fallback: the deployed cap is
128 MiB, eight times that default, so substituting it would report a false RED
for a healthy queue. An unreadable cap is UNKNOWN (exit 2), never a pass.

Usage: ``systemctl --user show android-body-rendezvous.service -p ExecStart |
         queue_capacity.py QUEUES_DIR NAME [NAME ...]``

Exit: 0 every queue is below the warning threshold, 1 at least one is at/above
it or missing, 2 the cap could not be read.
"""

import sys
from pathlib import Path

#: ``server.py`` DEFAULT_QUEUE_BYTES, published only for provenance: never used
#: as a fallback cap (see the module docstring).
DEFAULT_QUEUE_BYTES = 16 * 1024 * 1024
#: Fraction of the cap at which a queue is RED. Below it the queue is GREEN.
WARN_PERCENT = 90


def parse_cap(text):
    """The ``--max-queue-bytes`` value in a systemd ``ExecStart`` dump, or None.

    Accepts both the rendered argv form (``--max-queue-bytes 134217728``) and the
    ``--max-queue-bytes=...`` form. A missing, non-numeric or non-positive value
    yields None: the caller must then report UNKNOWN, not assume a bound.
    """
    tokens = text.split()
    for index, token in enumerate(tokens):
        if token == "--max-queue-bytes" and index + 1 < len(tokens):
            return _positive(tokens[index + 1])
        if token.startswith("--max-queue-bytes="):
            return _positive(token.split("=", 1)[1])
    return None


def _positive(text):
    """*text* as a positive int, or None when it is not one."""
    try:
        value = int(text)
    except (TypeError, ValueError):
        return None
    return value if value > 0 else None


def verdict(size, cap, warn_percent=WARN_PERCENT):
    """``("GREEN"|"RED", percent)`` for a *size*-byte queue under *cap*."""
    if cap <= 0:
        raise ValueError("cap must be positive")
    percent = size * 100.0 / cap
    return ("RED" if percent >= warn_percent else "GREEN"), percent


def main(argv):
    if len(argv) < 3:
        print("usage: queue_capacity.py QUEUES_DIR NAME [NAME ...]", file=sys.stderr)
        return 2
    directory = Path(argv[1])
    sizes = []
    missing = False
    for name in argv[2:]:
        try:
            sizes.append((name, (directory / name).stat().st_size))
        except OSError:
            sizes.append((name, None))
            missing = True
    cap = parse_cap(sys.stdin.read())
    if cap is None:
        for name, size in sizes:
            print(f"UNKNOWN queue {name} "
                  f"{'MISSING' if size is None else f'{size}B'} (cap unreadable)")
        return 2
    failed = missing
    for name, size in sizes:
        if size is None:
            print(f"{'RED':<6} queue {name} MISSING")
            continue
        status, percent = verdict(size, cap)
        print(f"{status:<6} queue {name} {size}B/{cap}B ({percent:.0f}%)")
        failed = failed or status == "RED"
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
