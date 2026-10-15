#!/usr/bin/env python3
# SPDX-License-Identifier: CC0-1.0
"""Report whether a named tailnet peer is currently reachable.

``tools/health-check.sh`` §3b decides RED vs UNKNOWN for a silent Redmi10 by
asking whether the phone is still on the tailnet. The first version read the
``tailscale status`` text and treated the literal word ``offline`` as "not
connected". That predicate is wrong for a phone on mobile data: tailscale's
coordination-server view (``Online``) can lag while the direct path keeps
working, so the same status line reads
``active; direct 91.79.90.43:33303; offline, last seen 12m ago`` for a peer that
is demonstrably writing every ~4s. A silent-but-connected phone then read
UNKNOWN ("device off") instead of RED ("app/transport fault") — the loss alert
went quiet exactly when it was needed.

Reachability is ``Online or Active`` from ``tailscale status --json``: ``Online``
is the coordination server's view, ``Active`` is whether this host is currently
passing traffic with the peer. Either is evidence the device is on the tailnet;
both false is the absent-device case (measured 2026-10-15: the delivering Redmi
is Online=False/Active=True, while every genuinely-absent peer is
False/False). The JSON is read on stdin so the caller owns the tailscale
invocation and its failure handling.

Usage: ``tailscale status --json | tailnet_peer.py NODE``

Prints ``yes`` (reachable), ``no`` (peer known, not reachable), or nothing when
the peer is absent or the view cannot be read — an unreadable view is unknown,
never a pass.
"""

import json
import sys


def reachable(document, node):
    """Return True/False for the peer whose DNS label is *node*, else None."""
    if not isinstance(document, dict):
        return None
    peers = document.get("Peer") or {}
    if not isinstance(peers, dict):
        return None
    for peer in peers.values():
        if not isinstance(peer, dict):
            continue
        label = (peer.get("DNSName") or "").split(".")[0]
        if label == node:
            return bool(peer.get("Online") or peer.get("Active"))
    return None


def main(argv):
    if len(argv) != 2:
        print("usage: tailnet_peer.py NODE", file=sys.stderr)
        return 2
    try:
        document = json.load(sys.stdin)
    except ValueError:
        return 0
    verdict = reachable(document, argv[1])
    if verdict is not None:
        print("yes" if verdict else "no")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
