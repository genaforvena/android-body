"""Regression tests for the light-cycle resumption monitor.

The monitor tails a node's retained ``light`` rows and applies that node's frozen rule, so
the tests cover the rule state machine, the tail reader and the run wiring separately.
"""
import argparse
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import light_cycle_monitor


def rows(*samples):
    """Render ``(seq, epoch, lux)`` samples as retained log lines."""
    return "".join("%d %d light lux=%s accuracy=3\n" % sample for sample in samples)


class TestRules(unittest.TestCase):
    def _events(self, node, samples):
        detector = light_cycle_monitor.ResumptionDetector(node)
        out = []
        for seq, epoch, lux in samples:
            event = detector.step(seq, epoch, lux)
            if event is not None:
                out.append(event)
        return out, detector

    def test_note3_rule_fires_once_on_dark_to_lit(self):
        events, _ = self._events("note3", [(1, 1000, 0.2), (2, 1005, 12.0)])
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["rule"], "single-sample")
        self.assertEqual(events[0]["prev_lux"], 0.2)
        self.assertEqual(events[0]["threshold_lux"], 7.0)

    def test_note3_rule_does_not_fire_on_the_first_lit_sample(self):
        events, _ = self._events("note3", [(1, 1000, 12.0), (2, 1005, 13.0)])
        self.assertEqual(events, [])

    def test_note3_rule_ignores_none_like_and_stale_rows(self):
        # Rows without a lux never reach step(); a lit reading after a dark one still fires.
        events, _ = self._events("note3", [(1, 1000, 0.1), (2, 1005, 9.0), (3, 1010, 9.5)])
        self.assertEqual(len(events), 1)

    def test_redmi10_rule_needs_the_full_dark_dwell(self):
        events, _ = self._events("redmi10", [(1, 1000, 0.0), (2, 1005, 1.0), (3, 1010, 12.0)])
        self.assertEqual(events, [])  # only two dark samples: not armed

    def test_redmi10_rule_fires_after_three_dark_samples(self):
        events, detector = self._events(
            "redmi10", [(1, 1000, 0.0), (2, 1005, 1.0), (3, 1010, 2.0), (4, 1015, 12.0)])
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["rule"], "dark-dwell")
        self.assertEqual(events[0]["rule_constants"],
                         {"arm_lux_max": 6.0, "resume_lux_min": 10.0,
                          "dark_dwell_samples": 3})
        self.assertEqual(events[0]["prev_lux"], 2.0)
        self.assertEqual(events[0]["prev_observed_unix"], 1000)
        self.assertEqual([sample[2] for sample in events[0]["baseline_samples"]], [0.0, 1.0, 2.0])
        self.assertFalse(detector.armed)  # a fire disarms until the dwell is rebuilt

    def test_redmi10_rule_rejects_the_observed_oscillation_cluster(self):
        # The retained failure mode: dim readings straddling the old 7.0 threshold
        # (5,5,2,1,5,5,4,1 -> 7,10,7,7,11,7,38,7). A 7-lux sample is at or above the
        # arm ceiling, so it resets the dark run instead of accumulating it.
        samples = [(i, 1000 + 5 * i, lux) for i, lux in
                   enumerate([5, 7, 5, 7, 2, 10, 1, 7, 5, 11, 5, 7, 4, 38, 1, 7])]
        events, _ = self._events("redmi10", samples)
        self.assertEqual(events, [])

    def test_redmi10_rule_disarms_after_a_fire(self):
        samples = [(1, 1000, 0.0), (2, 1005, 0.0), (3, 1010, 0.0), (4, 1015, 20.0),
                   (5, 1020, 20.0), (6, 1025, 0.0), (7, 1030, 0.0), (8, 1035, 20.0)]
        events, _ = self._events("redmi10", samples)
        self.assertEqual(len(events), 1)  # the second rise has only two dark samples

    def test_redmi10_rule_never_fires_from_a_lit_baseline(self):
        events, _ = self._events("redmi10", [(1, 1000, 30.0), (2, 1005, 40.0), (3, 1010, 50.0)])
        self.assertEqual(events, [])

    def test_unknown_node_is_rejected(self):
        with self.assertRaises(ValueError):
            light_cycle_monitor.ResumptionDetector("pixel")


class TestTailReader(unittest.TestCase):
    def _read(self, text, offset=0):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "redmi10.observations.log"
            path.write_text(text)
            return light_cycle_monitor.read_new_rows(path, offset)

    def test_reads_only_complete_light_rows(self):
        found, offset = self._read("1 1000 light lux=0.0 accuracy=3\n"
                                   "2 1005 light unavailable reason=stale\n"
                                   "3 1010 light lux=12.0 accuracy=3\n")
        self.assertEqual([lux for _, _, lux in found], [0.0, 12.0])
        self.assertEqual(found[1][0], 3)

    def test_leaves_a_half_written_final_line_for_the_next_check(self):
        text = "1 1000 light lux=0.0 accuracy=3\n2 1005 light lux=1"
        found, offset = self._read(text)
        self.assertEqual([lux for _, _, lux in found], [0.0])
        again, _ = self._read(text[:offset] + "2.0 accuracy=3\n", offset)
        self.assertEqual([lux for _, _, lux in again], [12.0 - 10.8])  # 12.0 written as "12.0"

    def test_missing_file_yields_no_rows(self):
        with tempfile.TemporaryDirectory() as folder:
            found, offset = light_cycle_monitor.read_new_rows(Path(folder) / "absent.log", 7)
        self.assertEqual((found, offset), ([], 7))

    def test_truncated_file_is_re_read_from_the_start(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "redmi10.observations.log"
            path.write_text("1 1000 light lux=0.0 accuracy=3\n")
            found, offset = light_cycle_monitor.read_new_rows(path, 999)
        self.assertEqual([lux for _, _, lux in found], [0.0])


    def test_leaves_a_half_written_final_line_for_the_next_check(self):
        text = "1 1000 light lux=0.0 accuracy=3\n2 1005 light lux=1"
        found, offset = self._read(text)
        self.assertEqual([lux for _, _, lux in found], [0.0])
        again, _ = self._read(text + "2.0 accuracy=3\n", offset)
        self.assertEqual([lux for _, _, lux in again], [12.0])


class TestHeartbeat(unittest.TestCase):
    def test_write_heartbeat_is_atomic_and_leaves_no_pending_file(self):
        with tempfile.TemporaryDirectory() as folder:
            heartbeat = Path(folder) / "light-cycle-monitor-state.json"
            with patch.object(light_cycle_monitor, "HEARTBEAT_FILE", heartbeat):
                light_cycle_monitor.write_heartbeat({"armed": False, "lux": None})
            self.assertTrue(json.loads(heartbeat.read_text())["armed"] is False)
            self.assertEqual([p.name for p in Path(folder).iterdir() if p.name.endswith(".pending")],
                             [])

class TestRun(unittest.TestCase):
    def _run(self, log_text, node="redmi10", stale_seconds=30.0, max_polls=1):
        with tempfile.TemporaryDirectory() as folder:
            folder = Path(folder)
            queues = folder / "body" / "queues"
            queues.mkdir(parents=True)
            (queues / ("%s.observations.log" % node)).write_text(log_text)
            log_file = folder / "resumed.jsonl"
            heartbeat = folder / "state.json"
            args = argparse.Namespace(node=node, site=folder, interval=0.0,
                                      max_polls=max_polls, stale_seconds=stale_seconds)
            with patch.object(light_cycle_monitor, "LOG_FILE", log_file), \
                 patch.object(light_cycle_monitor, "HEARTBEAT_FILE", heartbeat), \
                 patch.object(light_cycle_monitor, "initial_offset", lambda path: 0):
                status = light_cycle_monitor.run(args)
            events = ([json.loads(line) for line in log_file.read_text().splitlines()]
                      if log_file.exists() else [])
            state = (json.loads(heartbeat.read_text()) if heartbeat.exists() else None)
            return status, events, state

    def test_run_writes_a_fire_row_and_a_heartbeat(self):
        status, events, state = self._run(rows((1, 1000, 0.0), (2, 1005, 0.0),
                                              (3, 1010, 0.0), (4, 1015, 12.0)))
        self.assertEqual(status, 1)  # one check, then the bounded run ends
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["lux"], 12.0)
        self.assertEqual(state["node"], "redmi10")
        self.assertEqual(state["rule"], "dark-dwell")
        self.assertEqual(state["threshold_lux"], 10.0)
        self.assertEqual(state["cursor_seq"], 4)
        self.assertEqual(state["samples"], 4)

    def test_run_reports_a_stale_source_as_no_fresh_reading(self):
        # The newest sample is far older than the freshness window: the detector is live
        # but the source is not, so lux must be null rather than a stale number. The
        # sequence stays dark, so no resumption is claimed either.
        status, events, state = self._run(rows((1, 1000, 0.0), (2, 1005, 0.0),
                                              (3, 1010, 0.0), (4, 1015, 1.0)),
                                         stale_seconds=1.0)
        self.assertEqual(events, [])
        self.assertIsNone(state["lux"])
        self.assertEqual(state["prev_lux"], 1.0)
        self.assertGreater(state["source_age_seconds"], 1.0)

    def test_run_without_a_site_queue_directory_fails_loudly(self):
        with tempfile.TemporaryDirectory() as folder:
            args = argparse.Namespace(node="redmi10", site=Path(folder), interval=0.0,
                                      max_polls=1, stale_seconds=30.0)
            with self.assertRaises(SystemExit):
                light_cycle_monitor.run(args)


if __name__ == "__main__":
    unittest.main()
