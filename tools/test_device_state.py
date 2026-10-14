# SPDX-License-Identifier: CC0-1.0
"""Tests for the read-only device-state classifier (tools/device_state.py).

The regression that matters: a durably enabled ON session in collect-only mode
writes no ``cursor_*`` preference (BodyService.execute() early-returns while
collect-only), so a classifier that keys the ON test on a recorded cursor key
reports OFF for exactly the state it exists to distinguish.
"""

import unittest

import device_state

CURSOR = "cursor_a45cc61a430735a43f23085fea855492283cf063407324326a5f5dc08b7fb36c"
OTHER = "cursor_" + "0" * 64

# A collect-only session: enabled, marker armed, but no action has ever executed.
COLLECT_ONLY_PREFS = """<?xml version='1.0' encoding='utf-8' standalone='yes' ?>
<map>
    <boolean name="owner_vibration" value="true" />
    <boolean name="desired_on" value="true" />
    <boolean name="owner_acceleration" value="true" />
    <long name="exit_baseline" value="0" />
    <boolean name="allow_http" value="true" />
    <boolean name="collect_only" value="true" />
    <string name="secret">DO-NOT-PRINT-SECRET</string>
    <string name="endpoint">http://user:DO-NOT-PRINT-SECRET@host:8765/node/note3</string>
    <boolean name="owner_battery" value="true" />
    <boolean name="owner_light" value="true" />
</map>
"""

# The same session after one action has executed: the cursor_* key now exists.
SENDING_PREFS = COLLECT_ONLY_PREFS.replace(
    '<boolean name="collect_only" value="true" />',
    f'<boolean name="collect_only" value="false" />\n    <long name="{CURSOR}" value="265956" />',
)


class ParsePrefsTests(unittest.TestCase):
    def test_secret_and_endpoint_values_are_dropped_not_hidden(self):
        prefs = device_state.parse_prefs(COLLECT_ONLY_PREFS)
        self.assertNotIn("secret", prefs)
        self.assertNotIn("endpoint", prefs)
        self.assertNotIn("DO-NOT-PRINT-SECRET", " ".join(prefs.values()))
        self.assertNotIn("DO-NOT-PRINT-SECRET", " ".join(prefs))

    def test_non_secret_entries_are_read(self):
        prefs = device_state.parse_prefs(SENDING_PREFS)
        self.assertEqual(prefs["desired_on"], "true")
        self.assertEqual(prefs["collect_only"], "false")
        self.assertEqual(prefs["exit_baseline"], "0")
        self.assertIn(CURSOR, prefs)


class ClassifyTests(unittest.TestCase):
    def setUp(self):
        self.collect_only = device_state.parse_prefs(COLLECT_ONLY_PREFS)
        self.sending = device_state.parse_prefs(SENDING_PREFS)

    def test_collect_only_without_recorded_cursor_is_on_not_off(self):
        state = device_state.classify(self.collect_only, CURSOR, True, True)
        self.assertEqual(state.state, device_state.ON_COLLECT_ONLY)
        self.assertTrue(state.run_enabled)
        self.assertFalse(state.marker_match_confirmed)

    def test_collect_only_with_recorded_cursor_confirms_match(self):
        prefs = dict(self.collect_only, **{CURSOR: "265956"})
        state = device_state.classify(prefs, CURSOR, True, True)
        self.assertEqual(state.state, device_state.ON_COLLECT_ONLY)
        self.assertTrue(state.marker_match_confirmed)

    def test_disabled_is_off(self):
        prefs = dict(self.collect_only, desired_on="false")
        state = device_state.classify(prefs, CURSOR, True, True)
        self.assertEqual(state.state, device_state.OFF)
        self.assertFalse(state.run_enabled)

    def test_missing_marker_is_off(self):
        state = device_state.classify(self.collect_only, "", True, True)
        self.assertEqual(state.state, device_state.OFF)
        self.assertTrue(state.desired_on)
        self.assertFalse(state.run_enabled)

    def test_malformed_marker_is_off(self):
        state = device_state.classify(self.collect_only, "cursor_not-hex", True, True)
        self.assertEqual(state.state, device_state.OFF)

    def test_enabled_sending(self):
        state = device_state.classify(self.sending, CURSOR, True, True)
        self.assertEqual(state.state, device_state.ON_SENDING)
        self.assertTrue(state.marker_match_confirmed)

    def test_enabled_but_process_absent_is_distinct(self):
        state = device_state.classify(self.collect_only, CURSOR, False, False)
        self.assertEqual(state.state, device_state.ON_NOT_RUNNING)

    def test_unrelated_wellformed_marker_still_reads_enabled(self):
        # Marker/endpoint equality needs the secret endpoint; the UI disarms before
        # an endpoint edit, so a well-formed marker is accepted, flagged unconfirmed.
        state = device_state.classify(self.collect_only, OTHER, True, True)
        self.assertEqual(state.state, device_state.ON_COLLECT_ONLY)
        self.assertFalse(state.marker_match_confirmed)

    def test_rendered_line_never_leaks_secret(self):
        state = device_state.classify(self.collect_only, CURSOR, True, True)
        line = state.line("note3")
        self.assertNotIn("DO-NOT-PRINT-SECRET", line)
        self.assertNotIn(CURSOR, line)
        self.assertIn("ON_COLLECT_ONLY", line)


class AdbArgvTests(unittest.TestCase):
    def test_plain_command(self):
        self.assertEqual(device_state.adb_argv("adb"), ["adb"])

    def test_wrapped_command_splits_into_argv(self):
        # The transport bridge and the node-state publisher run adb through the
        # plant wrapper; the classifier must not hand it to subprocess as one word.
        self.assertEqual(
            device_state.adb_argv("rtk proxy adb"), ["rtk", "proxy", "adb"]
        )

    def test_blank_falls_back_to_adb(self):
        self.assertEqual(device_state.adb_argv("   "), ["adb"])



if __name__ == "__main__":
    unittest.main()
