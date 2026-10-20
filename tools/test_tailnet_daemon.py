# SPDX-License-Identifier: CC0-1.0
"""Tests for the tailnet daemon-state predicate (tools/tailnet_daemon.py).

The regression that matters: ``health-check.sh`` §3b decided RED vs UNKNOWN for a
silent Redmi10 from the *peer* view in ``tailscale status --json``. That document
is a stale cached map while the daemon is stopped, so with the daemon ``Stopped``
since 14:03:03Z the check still read the phone peer as reachable and printed
``RED redmi10 silent 5142s over a live tailnet path`` — a live path that did not
exist. A silent phone during a stopped daemon is expected (it buffers and dumps
on resume), so the predicate must key on the daemon's own ``BackendState``: only
``Running`` makes a silence a fault; every other state leaves the host path
unverifiable and the silence unattributable to the device.
"""

import json
import subprocess
import sys
import unittest
from pathlib import Path

import tailnet_daemon

TOOL = Path(__file__).with_name("tailnet_daemon.py")


def document(state):
    return {"BackendState": state}


class RunningTest(unittest.TestCase):
    def test_running_daemon_is_running(self):
        self.assertIs(tailnet_daemon.running(document("Running")), True)

    def test_stopped_daemon_is_not_running(self):
        # The regression: the cached map says Stopped while the peer is Online.
        self.assertIs(tailnet_daemon.running(document("Stopped")), False)

    def test_transitional_states_are_not_running(self):
        # Starting/Stopping/NoState leave the serve path unverifiable.
        for state in ("Starting", "Stopping", "NoState", "NeedsLogin", "Disconnected"):
            self.assertIs(tailnet_daemon.running(document(state)), False, state)

    def test_absent_state_is_unknown(self):
        for doc in ({}, {"Peer": {}}, document(None), document("")):
            self.assertIsNone(tailnet_daemon.running(doc))

    def test_non_object_document_is_unknown(self):
        for bad in ([], "no", 7, None, {"BackendState": ["Running"]}):
            self.assertIsNone(tailnet_daemon.running(bad))


class CliTest(unittest.TestCase):
    def run_tool(self, stdin):
        return subprocess.run([sys.executable, str(TOOL)], input=stdin,
                              capture_output=True, text=True, timeout=20)

    def test_prints_running(self):
        result = self.run_tool(json.dumps(document("Running")))
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout.strip(), "running")

    def test_prints_stopped(self):
        result = self.run_tool(json.dumps(document("Stopped")))
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout.strip(), "stopped")

    def test_prints_unknown_for_absent_state(self):
        result = self.run_tool(json.dumps({}))
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout.strip(), "unknown")

    def test_unreadable_input_is_unknown_not_a_crash(self):
        result = self.run_tool("not json")
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout.strip(), "unknown")

    def test_argument_is_a_usage_error(self):
        result = subprocess.run([sys.executable, str(TOOL), "extra"],
                                capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 2)
        self.assertIn("usage", result.stderr)


if __name__ == "__main__":
    unittest.main()
