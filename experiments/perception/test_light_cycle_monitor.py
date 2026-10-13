"""Regression tests for light_cycle_monitor transition logic."""
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import light_cycle_monitor


class TestLightCycleMonitor(unittest.TestCase):
    def _run_monitor(self, lux_sequence):
        """Run monitor with mocked readings; return (returncode, log_entries)."""
        with tempfile.TemporaryDirectory() as tmpdir:
            log_file = Path(tmpdir) / "test-log.jsonl"
            seq = list(lux_sequence)

            def mock_read():
                return seq.pop(0) if seq else None

            with patch.object(light_cycle_monitor, "read_light_lux", side_effect=mock_read), \
                 patch.object(light_cycle_monitor, "LOG_FILE", log_file):
                old_argv = sys.argv
                sys.argv = ["light_cycle_monitor.py", "--interval", "0", "--max-polls", "10"]
                try:
                    ret = light_cycle_monitor.main()
                finally:
                    sys.argv = old_argv

                lines = log_file.read_text().strip().split("\n") if log_file.exists() else []
                return ret, [json.loads(line) for line in lines if line]

    def test_no_false_positive_first_poll_light_on(self):
        """Bug fix: first poll with light already on must NOT log transition."""
        ret, entries = self._run_monitor([11.4, 11.5, 11.6])
        self.assertEqual(len(entries), 0)

    def test_transition_dark_to_light(self):
        """Transition logged when lux goes from <=0.5 to >0.5."""
        ret, entries = self._run_monitor([0.1, 0.2, 3.0])
        self.assertEqual(ret, 0)
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["event"], "light-cycle-resumed")
        self.assertEqual(entries[0]["lux"], 3.0)
        self.assertEqual(entries[0]["prev_lux"], 0.2)

    def test_no_transition_light_stays_on(self):
        """No transition when lux stays above threshold."""
        ret, entries = self._run_monitor([5.0, 5.1, 5.2])
        self.assertEqual(len(entries), 0)

    def test_no_transition_light_stays_dark(self):
        """No transition when lux stays below threshold."""
        ret, entries = self._run_monitor([0.1, 0.2, 0.3])
        self.assertEqual(len(entries), 0)

    def test_transition_after_extended_dark(self):
        """Transition after multiple dark polls."""
        ret, entries = self._run_monitor([0.0, 0.0, 0.0, 2.5])
        self.assertEqual(ret, 0)
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["lux"], 2.5)
        self.assertEqual(entries[0]["prev_lux"], 0.0)

    def test_none_readings_do_not_trigger(self):
        """None readings (space.json unavailable) never trigger transition."""
        ret, entries = self._run_monitor([None, None, None])
        self.assertEqual(len(entries), 0)

    def test_dark_none_light_is_transition(self):
        """Dark -> None -> light is a valid transition."""
        ret, entries = self._run_monitor([0.1, None, 3.0])
        self.assertEqual(ret, 0)
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["lux"], 3.0)
        self.assertEqual(entries[0]["prev_lux"], 0.1)


if __name__ == "__main__":
    unittest.main()
