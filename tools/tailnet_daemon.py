#!/usr/bin/env python3
# SPDX-License-Identifier: CC0-1.0
"""Report whether the host tailnet daemon is currently running.

``tools/health-check.sh`` §3b decides RED vs UNKNOWN for a silent Redmi10. It
already asks ``tools/tailnet_peer.py`` whether the phone peer is reachable, but
that predicate reads the *peer* view out of ``tailscale status --json`` — and
that document is a stale cached map while the daemon is stopped. Measured
2026-10-20T15:45Z: the daemon had been ``Stopped`` since 14:03:03Z, yet
``tailscale status --json`` still returned ``BackendState: "Stopped"`` with the
phone peer listed ``Online``, so §3b read ``yes`` and printed
``RED redmi10 silent 5142s over a live tailnet path`` — a live path that did
not exist. A silent phone during a stopped daemon is expected (it buffers and
dumps on resume, measured 9168 rows in 8.7 s), so the silence branch must not
assert a live path.

The daemon's own state is the fact that separates the two cases: ``Running``
means the ``tailscale serve`` front is up and a silent phone is a fault;
anything else (``Stopped``, ``Stopping``, ``Starting``, ``NoState``, ...)
means the host path is unverifiable and the silence is not attributable to the
device. The JSON is read on stdin so the caller owns the tailscale invocation
and its failure handling.

Usage: ``tailscale status --json | tailnet_daemon.py``

Prints ``running``, ``stopped`` or ``unknown`` (the field absent, or the view
unreadable) — an unreadable view is unknown, never a pass.
"""

import json
import sys

RUNNING = "Running"


def running(document):
    """Return True/False for the daemon state, else None when unreadable."""
    if not isinstance(document, dict):
        return None
    state = document.get("BackendState")
    if state == RUNNING:
        return True
    if isinstance(state, str) and state:
        return False
    return None


def main(argv):
    if argv:
        print("usage: tailnet_daemon.py < tailscale-status.json", file=sys.stderr)
        return 2
    try:
        document = json.load(sys.stdin)
    except ValueError:
        print("unknown")
        return 0
    verdict = running(document)
    print({True: "running", False: "stopped", None: "unknown"}[verdict])
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
