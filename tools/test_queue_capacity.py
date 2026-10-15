#!/usr/bin/env python3
# SPDX-License-Identifier: CC0-1.0
"""Tests for the rendezvous queue-capacity detector (tools/queue_capacity.py).

The regression that matters: §5 of ``health-check.sh`` printed a queue's byte
size with no bound, so a queue approaching ``--max-queue-bytes`` read exactly
like an empty one until ``append`` started returning ``507 queue_full`` and the
next start could not open the oversized file. The detector must read the live
cap, flag a queue at/above the warning fraction, and report an unreadable cap as
UNKNOWN (exit 2) rather than falling back to ``DEFAULT_QUEUE_BYTES`` -- the
deployed cap is 128 MiB, so that fallback would RED a healthy 25 MiB queue.
"""

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import queue_capacity

TOOL = Path(__file__).with_name("queue_capacity.py")

#: The live unit's ExecStart, as `systemctl show -p ExecStart` renders it. Node
#: secrets are environment-variable *names* here, never values.
EXEC_START = (
    "ExecStart={ path=/usr/bin/python3 ; argv[]=/usr/bin/python3 "
    "/home/mesh-home/android-body/.mishe-tauftauf/body/runtime/server.py "
    "--host 127.0.0.1 --port 8765 --node note3:NOTE3_SECRET "
    "--node redmi10:REDMI10_SECRET "
    "--data-dir /home/mesh-home/android-body/.mishe-tauftauf/body/queues "
    "--max-queue-bytes 134217728 ; ignore_errors=no ; start_time=[n/a] ; "
    "stop_time=[n/a] ; pid=0 ; code=(null) ; status=0/0 }\n"
)


class ParseCapTest(unittest.TestCase):
    def test_reads_the_rendered_argv_value(self):
        self.assertEqual(queue_capacity.parse_cap(EXEC_START), 134217728)

    def test_reads_the_equals_form(self):
        self.assertEqual(queue_capacity.parse_cap("ExecStart=... --max-queue-bytes=1024 ;"), 1024)

    def test_absent_flag_is_none(self):
        self.assertIsNone(queue_capacity.parse_cap("ExecStart={ path=/usr/bin/python3 ; }"))

    def test_non_numeric_value_is_none(self):
        self.assertIsNone(queue_capacity.parse_cap("--max-queue-bytes ${CAP}"))

    def test_non_positive_value_is_none(self):
        self.assertIsNone(queue_capacity.parse_cap("--max-queue-bytes 0"))
        self.assertIsNone(queue_capacity.parse_cap("--max-queue-bytes -5"))

    def test_flag_without_value_is_none(self):
        self.assertIsNone(queue_capacity.parse_cap("--max-queue-bytes"))

    def test_equals_form_with_empty_value_is_none(self):
        self.assertIsNone(queue_capacity.parse_cap("--max-queue-bytes="))


class SecretLeakTest(unittest.TestCase):
    def test_execstart_dump_is_never_echoed(self):
        # The live ExecStart carries the node env-var names; the tool must only
        # ever print the extracted cap, never the dump it was read from.
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "note3.observations.log").write_bytes(b"x" * 10)
            result = subprocess.run(
                [sys.executable, str(TOOL), str(tmp), "note3.observations.log"],
                input=EXEC_START, capture_output=True, text=True, timeout=20)
            self.assertEqual(result.returncode, 0)
            for stream in (result.stdout, result.stderr):
                self.assertNotIn("NOTE3_SECRET", stream)
                self.assertNotIn("REDMI10_SECRET", stream)
                self.assertNotIn("ExecStart", stream)


class VerdictTest(unittest.TestCase):
    def test_below_threshold_is_green(self):
        status, percent = queue_capacity.verdict(899, 1000)
        self.assertEqual(status, "GREEN")
        self.assertAlmostEqual(percent, 89.9)

    def test_at_threshold_is_red(self):
        status, percent = queue_capacity.verdict(900, 1000)
        self.assertEqual(status, "RED")
        self.assertAlmostEqual(percent, 90.0)

    def test_over_cap_is_red(self):
        status, percent = queue_capacity.verdict(1280, 1000)
        self.assertEqual(status, "RED")
        self.assertAlmostEqual(percent, 128.0)

    def test_healthy_deployed_queue_is_green(self):
        # The observed note3 queue (25 MiB) under the deployed 128 MiB cap: the
        # exact case a DEFAULT_QUEUE_BYTES fallback would misreport as RED.
        status, _ = queue_capacity.verdict(25_259_073, 134_217_728)
        self.assertEqual(status, "GREEN")

    def test_zero_cap_is_rejected(self):
        with self.assertRaises(ValueError):
            queue_capacity.verdict(1, 0)


class CliTest(unittest.TestCase):
    def run_tool(self, stdin, directory, *names):
        return subprocess.run(
            [sys.executable, str(TOOL), str(directory), *names],
            input=stdin, capture_output=True, text=True, timeout=20)

    def test_green_queue_reports_fraction(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "note3.observations.log").write_bytes(b"x" * 100)
            result = self.run_tool("--max-queue-bytes 1000", tmp, "note3.observations.log")
            self.assertEqual(result.returncode, 0)
            self.assertIn("GREEN  queue note3.observations.log 100B/1000B (10%)", result.stdout)

    def test_full_queue_is_red_and_exits_one(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "redmi10.observations.log").write_bytes(b"x" * 950)
            result = self.run_tool("--max-queue-bytes 1000", tmp, "redmi10.observations.log")
            self.assertEqual(result.returncode, 1)
            self.assertIn("RED    queue redmi10.observations.log 950B/1000B (95%)", result.stdout)

    def test_missing_queue_is_red(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = self.run_tool("--max-queue-bytes 1000", tmp, "note3.actions.log")
            self.assertEqual(result.returncode, 1)
            self.assertIn("RED    queue note3.actions.log MISSING", result.stdout)

    def test_unreadable_cap_is_unknown_not_a_pass(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "note3.observations.log").write_bytes(b"x" * 100)
            result = self.run_tool("ExecStart={ path=/usr/bin/python3 ; }", tmp,
                                   "note3.observations.log")
            self.assertEqual(result.returncode, 2)
            self.assertIn("UNKNOWN queue note3.observations.log 100B (cap unreadable)",
                          result.stdout)

    def test_usage_without_names_exits_two(self):
        result = subprocess.run([sys.executable, str(TOOL), "/tmp"],
                                input="", capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 2)


if __name__ == "__main__":
    unittest.main()
