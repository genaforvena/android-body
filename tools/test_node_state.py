# SPDX-License-Identifier: CC0-1.0
"""Tests for the bounded node-state publisher (tools/node_state.py).

The regressions that matter: an unreadable device must publish UNKNOWN with a
reason and never a fabricated ``false`` (a consumer reading ``desired_on=false``
would render a real ON session as OFF), and the published bytes must never carry
the endpoint or the node secret.
"""

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import device_state
import node_state

CURSOR = "cursor_a45cc61a430735a43f23085fea855492283cf063407324326a5f5dc08b7fb36c"
SECRET = "DO-NOT-PRINT-SECRET"

STATE = device_state.DeviceState(
    state=device_state.ON_COLLECT_ONLY,
    desired_on=True,
    collect_only=True,
    run_enabled=True,
    marker_match_confirmed=True,
    process_present=True,
    service_foreground=True,
    reasons=("marker matches the recorded endpoint cursor", "collect-only: no HTTP by design"),
)


class DocumentTests(unittest.TestCase):
    def test_shape_and_values(self):
        doc = node_state.document("note3", STATE, now=1760439327.5)
        self.assertEqual(
            set(doc),
            {"node", "mode", "desired_on", "collect_only", "observed_at_epoch_s",
             "source", "reasons"},
        )
        self.assertEqual(doc["node"], "note3")
        self.assertEqual(doc["mode"], "ON_COLLECT_ONLY")
        self.assertIs(doc["desired_on"], True)
        self.assertIs(doc["collect_only"], True)
        self.assertEqual(doc["observed_at_epoch_s"], 1760439327.5)
        self.assertEqual(doc["source"], "tools/node_state.py")
        self.assertEqual(len(doc["reasons"]), 2)
        node_state.assert_bounded(doc)

    def test_unreadable_device_publishes_unknown_with_reason_not_false(self):
        doc = node_state.document("note3", None, error=RuntimeError("device not attached"), now=1)
        self.assertEqual(doc["mode"], "UNKNOWN")
        self.assertIsNone(doc["desired_on"])
        self.assertIsNone(doc["collect_only"])
        self.assertEqual(doc["reasons"], ["device not attached"])
        node_state.assert_bounded(doc)

    def test_observe_maps_read_failure_to_unknown(self):
        with mock.patch.object(
            node_state.device_state, "read_device",
            side_effect=RuntimeError("device not attached"),
        ):
            doc, state = node_state.observe("adb", "serial", "org.androidbody", 1.0, "note3", now=5)
        self.assertIsNone(state)
        self.assertEqual(doc["mode"], "UNKNOWN")

    def test_observe_publishes_the_classified_state(self):
        with mock.patch.object(node_state.device_state, "read_device", return_value=STATE):
            doc, state = node_state.observe("adb", "serial", "org.androidbody", 1.0, "note3", now=5)
        self.assertIs(state, STATE)
        self.assertEqual(doc["mode"], "ON_COLLECT_ONLY")

    def test_unbounded_reason_is_rejected(self):
        doc = node_state.document("note3", None, error="x" * 500, now=1)
        with self.assertRaises(ValueError):
            node_state.assert_bounded(doc)


class PublishTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.output = Path(self.tmp.name) / "perception" / "node-state-note3.json"

    def test_publishes_private_json_and_leaves_no_temp(self):
        node_state.publish(self.output, node_state.document("note3", STATE, now=7))
        doc = json.loads(self.output.read_text(encoding="utf-8"))
        self.assertEqual(doc["mode"], "ON_COLLECT_ONLY")
        self.assertEqual(os.stat(self.output).st_mode & 0o777, 0o600)
        leftovers = [p.name for p in self.output.parent.iterdir() if p.name != self.output.name]
        self.assertEqual(leftovers, [])

    def test_bytes_never_carry_secret_values_or_credential_keys(self):
        doc = node_state.document("note3", STATE, now=7)
        node_state.publish(self.output, doc)
        text = self.output.read_text(encoding="utf-8")
        self.assertNotIn(SECRET, text)
        self.assertNotIn(CURSOR, text)
        published = json.loads(text)
        self.assertNotIn("secret", published)
        self.assertNotIn("endpoint", published)

    def test_failed_write_leaves_no_temp_file(self):
        doc = node_state.document("note3", STATE, now=7)
        with mock.patch.object(node_state.os, "replace", side_effect=OSError("boom")):
            with self.assertRaises(OSError):
                node_state.publish(self.output, doc)
        self.assertFalse(self.output.exists())
        self.assertEqual(list(self.output.parent.iterdir()), [])

    def test_default_output_uses_the_prefix_the_consumer_skips(self):
        # watch.py globs body/perception/*.json for its own node state and skips
        # the "node-state-" prefix (watch.py:1640); without the prefix the
        # document is parsed as a perception state and crashes the consumer.
        output = node_state.default_output("/site", "note3")
        self.assertEqual(output, Path("/site/body/perception/node-state-note3.json"))
        self.assertTrue(output.name.startswith(node_state.NODE_STATE_PREFIX))


if __name__ == "__main__":
    unittest.main()
