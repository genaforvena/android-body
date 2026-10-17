#!/usr/bin/env python3
# SPDX-License-Identifier: CC0-1.0
"""Tests for the stranded-clear detector (tools/channel_clear.py).

The regression that matters: on 2026-10-17 two android-body channels
(genome, senses) were stranded at the clear step from the 08:47:24Z boot -- the
supervisor printed 133/132 ``HOLD seed <role> clear: rotated mind process
changed; reconcile clear`` lines in 45 minutes and created no wake, so both
minds were dead while ``tools/health-check.sh`` printed ``HEALTH: GREEN``. The
detector must read ``checks/wall-clear-<role>-<settled>.json`` and RED on an
unsettled journal at or past the grace, name the role, settled turn, phase and the
age that measured it, stay GREEN for a rotation that is genuinely in flight, treat
the committed history as GREEN, read UNKNOWN -- never a pass -- for a journal it
cannot decode or a missing ``checks/`` directory, and print no GREEN summary line
when any journal is UNKNOWN. The grace is the pinned core's own stall threshold
(``seed_culture_views.CLEAR_JOURNAL_STALL_S``), so the boundary case is included.
The observed journals are replayed here as fixtures: the detector must call them RED.
"""

import contextlib
import io
import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path

import channel_clear

NOW = 1_790_000_000.0


def write_journal(checks, name, body, *, age):
    """Write *body* as JSON to *checks/name* with mtime *NOW - age*."""
    path = checks / name
    path.write_text(json.dumps(body) if not isinstance(body, str) else body, encoding="utf-8")
    stamp = NOW - age
    os.utime(path, (stamp, stamp))
    return path


def journal(role="genome", settled=104072, phase="rotated"):
    return {"after_pid": "840756", "before_pid": "767482", "phase": phase, "role": role,
            "session": "android-body", "settled": settled}


class JournalReport(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.checks = Path(self.tmp.name) / "checks"
        self.checks.mkdir()

    def report(self, name, body, *, age, grace=channel_clear.STRANDED_AFTER_SECONDS):
        path = write_journal(self.checks, name, body, age=age)
        return channel_clear.journal_report(path, now=NOW, grace=grace)

    def test_rotated_past_grace_is_red_and_names_the_excess(self):
        status, pending, detail = self.report("wall-clear-genome-104072.json", journal(), age=300)
        self.assertEqual(status, "RED")
        self.assertTrue(pending)
        self.assertIn("channel clear genome settled=104072 phase=rotated", detail)
        self.assertIn("age=300s reaches the 60s", detail)
        self.assertIn("creates no new wake", detail)

    def test_rotating_past_grace_is_red(self):
        status, pending, _ = self.report("wall-clear-senses-104006.json",
                                         journal("senses", 104006, "rotating"), age=61)
        self.assertEqual((status, pending), ("RED", True))

    def test_within_grace_is_in_flight_not_red(self):
        status, pending, detail = self.report("wall-clear-genome-104072.json", journal(), age=10)
        self.assertEqual((status, pending), ("GREEN", True))
        self.assertIn("in flight", detail)

    def test_grace_boundary_is_inclusive_as_the_core_compares_it(self):
        # The core skips only age < CLEAR_JOURNAL_STALL_S, so age == grace is a stall.
        status, pending, _ = self.report("wall-clear-genome-104072.json", journal(), age=60)
        self.assertEqual((status, pending), ("RED", True))
        status, _, _ = self.report("wall-clear-genome-104072.json", journal(), age=59.999)
        self.assertEqual(status, "GREEN")

    def test_committed_history_is_green_and_not_unsettled(self):
        status, pending, detail = self.report("wall-clear-genome-100050.json",
                                              journal(settled=100050, phase="committed"), age=999_999)
        self.assertEqual((status, pending), ("GREEN", False))
        self.assertIn("committed", detail)

    def test_undecodable_journal_is_unknown_never_pass(self):
        status, pending, detail = self.report("wall-clear-genome-104072.json", "{not json", age=10_000)
        self.assertEqual((status, pending), ("UNKNOWN", False))
        self.assertIn("no decodable phase", detail)

    def test_phaseless_journal_is_unknown(self):
        status, pending, _ = self.report("wall-clear-genome-104072.json",
                                         {"role": "genome", "settled": 104072}, age=10_000)
        self.assertEqual((status, pending), ("UNKNOWN", False))

    def test_observed_20261017_journals_replay_red(self):
        """The two journals that stranded genome and senses, as recorded."""
        pin = "PYTHONPATH=/home/mesh-home/mishe-tauftauf/.mishe-tauftauf/releases/" \
              "db76495964952f0b67648fd701f166c253a7fcbf/src"
        for role, settled, after in (("genome", 104072, "840756"), ("senses", 104006, "831724")):
            body = dict(journal(role, settled), after_pid=after, launch_command=["env", pin])
            status, pending, detail = self.report(f"wall-clear-{role}-{settled}.json", body, age=2830)
            self.assertEqual((status, pending), ("RED", True), detail)
            self.assertIn(f"channel clear {role} settled={settled} phase=rotated", detail)


class Main(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.site = Path(self.tmp.name)
        self.checks = self.site / "checks"
        self.checks.mkdir()

    def run_main(self, *argv):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            rc = channel_clear.main(["--site", str(self.site), *argv], now=NOW)
        return rc, out.getvalue()

    def test_red_exit_and_line_for_a_stranded_journal(self):
        write_journal(self.checks, "wall-clear-genome-104072.json", journal(), age=300)
        write_journal(self.checks, "wall-clear-genome-100050.json",
                      journal(settled=100050, phase="committed"), age=900_000)
        rc, out = self.run_main()
        self.assertEqual(rc, 1)
        self.assertIn("RED    channel clear genome settled=104072 phase=rotated", out)
        self.assertNotIn("settled=100050", out)

    def test_green_when_only_committed_history(self):
        write_journal(self.checks, "wall-clear-genome-100050.json",
                      journal(settled=100050, phase="committed"), age=900_000)
        rc, out = self.run_main()
        self.assertEqual(rc, 0)
        self.assertIn("GREEN  channel clear: 0 of 1 journals unsettled", out)

    def test_unknown_exit_for_an_undecodable_journal(self):
        write_journal(self.checks, "wall-clear-genome-104072.json", "{", age=10)
        rc, out = self.run_main()
        self.assertEqual(rc, 2)
        self.assertIn("UNKNOWN", out)

    def test_all_unknown_run_prints_no_green_summary(self):
        write_journal(self.checks, "wall-clear-genome-104072.json", "{", age=10)
        write_journal(self.checks, "wall-clear-senses-104006.json", "{", age=10)
        rc, out = self.run_main()
        self.assertEqual(rc, 2)
        self.assertNotIn("GREEN", out)
        self.assertIn("no decodable phase", out)

    def test_missing_checks_directory_is_unknown(self):
        self.checks.rmdir()
        rc, out = self.run_main()
        self.assertEqual(rc, 2)
        self.assertIn("UNKNOWN channel clear", out)

    def test_empty_checks_directory_is_unknown_never_pass(self):
        rc, out = self.run_main()
        self.assertEqual(rc, 2)
        self.assertIn("no channel has rotated yet; not a pass", out)

    def test_all_flag_prints_committed_history(self):
        write_journal(self.checks, "wall-clear-genome-100050.json",
                      journal(settled=100050, phase="committed"), age=900_000)
        rc, out = self.run_main("--all")
        self.assertEqual(rc, 0)
        self.assertIn("committed", out)

    def test_grace_flag_is_honoured(self):
        write_journal(self.checks, "wall-clear-genome-104072.json", journal(), age=30)
        self.assertEqual(self.run_main()[0], 0)
        self.assertEqual(self.run_main("--grace", "10")[0], 1)

    def test_paths_are_newest_first(self):
        write_journal(self.checks, "wall-clear-genome-100050.json", journal(settled=100050), age=900)
        write_journal(self.checks, "wall-clear-senses-104006.json", journal("senses", 104006), age=10)
        names = [path.name for path in channel_clear.journal_paths(self.site)]
        self.assertEqual(names, ["wall-clear-senses-104006.json", "wall-clear-genome-100050.json"])


if __name__ == "__main__":
    unittest.main()
