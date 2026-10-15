# SPDX-License-Identifier: CC0-1.0
"""Tests for the tailnet peer reachability predicate (tools/tailnet_peer.py).

The regression that matters: ``health-check.sh`` §3b treated the literal word
``offline`` in ``tailscale status`` as "device not connected". A phone on mobile
data keeps a working direct path while the coordination server's ``Online`` view
lags, so its status line still says ``offline`` for a peer that is actively
writing. The predicate must read that peer as reachable (so a silence is RED,
an app/transport fault) and must read a genuinely absent peer as not reachable
(UNKNOWN, device off), never conflating the two.
"""

import json
import subprocess
import sys
import unittest
from pathlib import Path

import tailnet_peer

TOOL = Path(__file__).with_name("tailnet_peer.py")


def peer(dns, online, active):
    return {"HostName": dns.split(".")[0], "DNSName": dns,
            "Online": online, "Active": active}


def document(*peers):
    return {"Peer": {str(i): p for i, p in enumerate(peers)}}


class ReachableTest(unittest.TestCase):
    def test_online_peer_is_reachable(self):
        doc = document(peer("redmi-10.tail3e4555.ts.net.", True, True))
        self.assertIs(tailnet_peer.reachable(doc, "redmi-10"), True)

    def test_active_peer_with_lagging_control_plane_is_reachable(self):
        # The regression: delivering phone, Online=False, Active=True.
        doc = document(peer("redmi-10.tail3e4555.ts.net.", False, True))
        self.assertIs(tailnet_peer.reachable(doc, "redmi-10"), True)

    def test_absent_peer_is_unknown_not_unreachable(self):
        doc = document(peer("redmi-10.tail3e4555.ts.net.", False, True))
        self.assertIsNone(tailnet_peer.reachable(doc, "other-node"))

    def test_offline_and_inactive_peer_is_not_reachable(self):
        doc = document(peer("redmi-10.tail3e4555.ts.net.", False, False))
        self.assertIs(tailnet_peer.reachable(doc, "redmi-10"), False)

    def test_other_peers_do_not_mask_the_target(self):
        doc = document(peer("iphone-13-mini.tail3e4555.ts.net.", False, False),
                       peer("redmi-10.tail3e4555.ts.net.", False, True))
        self.assertIs(tailnet_peer.reachable(doc, "redmi-10"), True)

    def test_non_object_document_is_unknown(self):
        for bad in ([], "no", 7, None, {"Peer": []}):
            self.assertIsNone(tailnet_peer.reachable(bad, "redmi-10"))


class CliTest(unittest.TestCase):
    def run_tool(self, stdin, node="redmi-10"):
        return subprocess.run([sys.executable, str(TOOL), node], input=stdin,
                              capture_output=True, text=True, timeout=20)

    def test_prints_yes_for_active_peer(self):
        result = self.run_tool(json.dumps(
            document(peer("redmi-10.tail3e4555.ts.net.", False, True))))
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout.strip(), "yes")

    def test_prints_nothing_for_absent_peer(self):
        result = self.run_tool(json.dumps(document()))
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout.strip(), "")

    def test_unreadable_input_is_silent_success(self):
        result = self.run_tool("not json")
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout.strip(), "")


if __name__ == "__main__":
    unittest.main()
