#!/usr/bin/env python3
# SPDX-License-Identifier: CC0-1.0
"""Tests for the pane-lease frame-cycle detector (tools/pane_lease.py).

The regression that matters: the core sync holds a linked site and restarts
every channel when a mind pane's ``-- pane live`` footer is older than 20 s or
does not advance within 3 x 6 s, and ``tools/health-check.sh`` §1c only counted
the resulting restart churn -- a trailing-60-min count that decays on its own
between pin advances, so it read GREEN over a still-slow renderer. The detector
must read the frame cycle from the footer history, RED on a slow *current* cycle
even when the newest lease happens to be fresh, RED on silence past the core's
retried stale read, RED when a pane publishes no footer at all (the core raises
"no visible lease"), UNKNOWN -- never a pass -- when there is too little
retained history to measure, and it must never read a socket that is not this
site's own server.
"""

import contextlib
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

import pane_lease

TOOL = Path(__file__).with_name("pane_lease.py")
SITE = "/home/x/android-body/.mishe-tauftauf"
SITE_HOME = "/home/x/android-body/.mishe-tauftauf"
CALLER_SOCKET = "/tmp/tmux-1000/android-body/tmux-1000/default"
LEGACY_SOCKET = "/tmp/tmux-1000/default"

#: The footer the renderer writes, as the core's FOOTER_LEASE_RE matches it.
FOOTER = "-- pane live {stamp} \u00b7 refresh 5s \u00b7 ticks every frame --"


def frame(seconds_ago, now):
    stamp = datetime.fromtimestamp(now - seconds_ago, timezone.utc)
    return FOOTER.format(stamp=stamp.strftime("%Y-%m-%dT%H:%M:%S.%f") + "Z")


def capture_of(offsets, now):
    """Pane text whose lease footers are *offsets* seconds before *now*."""
    return "\n".join(["some frame body", *(frame(o, now) for o in offsets)])


class FakeResult:
    def __init__(self, returncode, stdout=b""):
        self.returncode = returncode
        self.stdout = stdout


def fake_run(answers):
    """A ``subprocess.run`` stand-in keyed by (socket, tmux subcommand)."""

    def run(cmd, capture_output=True, env=None):
        return FakeResult(*answers.get((cmd[2], cmd[3]), (1, b"")))

    return run


class LeaseStampsTest(unittest.TestCase):
    def test_reads_footers_oldest_first(self):
        now = 1_792_000_000.0
        stamps = pane_lease.lease_stamps(capture_of([40, 20, 0], now))
        self.assertEqual([s.timestamp() for s in stamps], [now - 40, now - 20, now])

    def test_ignores_non_footer_lines(self):
        now = 1_792_000_000.0
        text = "\n".join([
            "-- wake: 1 --",
            "-- ledger: 2 --",
            frame(10, now)[:-3],  # a truncated footer is not a lease
            "-- pane live not-a-stamp \u00b7 refresh 5s \u00b7 ticks every frame --",
        ])
        self.assertEqual(pane_lease.lease_stamps(text), [])

    def test_accepts_a_stamp_without_fractional_seconds(self):
        text = "-- pane live 2026-10-16T20:06:46Z \u00b7 refresh 5s \u00b7 ticks every frame --"
        self.assertEqual(len(pane_lease.lease_stamps(text)), 1)


class FrameIntervalsTest(unittest.TestCase):
    def test_returns_consecutive_gaps_oldest_first(self):
        now = 1_792_000_000.0
        stamps = pane_lease.lease_stamps(capture_of([30, 24, 6, 0], now))
        self.assertEqual(pane_lease.frame_intervals(stamps), [6.0, 18.0, 6.0])

    def test_fewer_than_two_stamps_has_no_interval(self):
        now = 1_792_000_000.0
        self.assertEqual(pane_lease.frame_intervals(pane_lease.lease_stamps(capture_of([3], now))), [])


class PaneReportTest(unittest.TestCase):
    NOW = 1_792_000_000.0

    def test_healthy_pane_is_green(self):
        status, detail = pane_lease.pane_report(capture_of([18, 12, 6, 0], self.NOW), now=self.NOW)
        self.assertEqual(status, "GREEN")
        self.assertIn("newest_interval=6.000s median=6.000s", detail)

    def test_slow_current_cycle_is_red_while_the_newest_lease_is_fresh(self):
        # The durable case §1c cannot see: age 1 s, but the cycle is 22 s.
        status, detail = pane_lease.pane_report(capture_of([89, 67, 45, 23, 1], self.NOW), now=self.NOW)
        self.assertEqual(status, "RED")
        self.assertIn("newest_interval=22.000s exceeds the 18.000s advance bound by 4.000s", detail)

    def test_replant_respawn_gaps_age_out_of_the_verdict(self):
        # The core tolerates one respawn gap (RENDERER_FRAME) and this check
        # reports the current cycle, so old multi-cycle gaps must not hold it RED.
        status, detail = pane_lease.pane_report(capture_of([120, 60, 40, 20, 10, 0], self.NOW), now=self.NOW)
        self.assertEqual(status, "GREEN")
        self.assertIn("newest_interval=10.000s", detail)

    def test_boundary_red_prints_the_measured_cycle_apart_from_the_bound(self):
        # Measured 2026-10-17T09:08Z: the witness pane's newest cycle was
        # 18.01 s against the 18.0 s advance bound, and ``%.1f`` printed both as
        # "18.0s", so a real 0.01 s excursion read as a broken tool. The
        # measured cycle and the bound must be distinguishable, and the
        # retained median must show the pane is normally inside the bound.
        status, detail = pane_lease.pane_report(capture_of([66, 54, 42, 30, 18.01, 0], self.NOW), now=self.NOW)
        self.assertEqual(status, "RED")
        self.assertIn("newest_interval=18.010s exceeds the 18.000s advance bound by 0.010s", detail)
        self.assertIn("median=12.000s", detail)

    def test_silence_past_the_stale_bound_is_red(self):
        status, detail = pane_lease.pane_report(capture_of([80, 74, 68, 62], self.NOW), now=self.NOW)
        self.assertEqual(status, "RED")
        self.assertIn("age=62.000s exceeds the 20.000s stale bound by 42.000s", detail)

    def test_a_stuck_pane_inside_the_retry_window_is_still_red(self):
        # The core's retry applies the same 20 s threshold, so a pane already
        # stale at the first read is held unless it publishes within 27 s; a
        # single read of that age is the safe direction, not a pass.
        status, detail = pane_lease.pane_report(capture_of([36, 30, 24], self.NOW), now=self.NOW)
        self.assertEqual(status, "RED")
        self.assertIn("age=24.000s exceeds the 20.000s stale bound by 4.000s", detail)

    def test_silence_at_the_stale_bound_is_not_red(self):
        status, detail = pane_lease.pane_report(capture_of([26, 20], self.NOW), now=self.NOW)
        self.assertEqual(status, "GREEN")
        self.assertIn("age=20.0s", detail)

    def test_advance_bound_is_exclusive(self):
        self.assertEqual(pane_lease.pane_report(capture_of([40, 18, 0], self.NOW), now=self.NOW)[0], "GREEN")
        self.assertEqual(pane_lease.pane_report(capture_of([40.5, 18.5, 0], self.NOW), now=self.NOW)[0], "RED")

    def test_no_footer_is_red_not_unknown(self):
        # The core raises "top pane has no visible lease" and holds the site.
        status, detail = pane_lease.pane_report("body only\nno footer here\n", now=self.NOW)
        self.assertEqual(status, "RED")
        self.assertIn("no visible lease", detail)

    def test_one_footer_with_a_fresh_age_is_unknown(self):
        status, detail = pane_lease.pane_report(capture_of([1], self.NOW), now=self.NOW)
        self.assertEqual(status, "UNKNOWN")
        self.assertIn("interval unmeasurable", detail)

    def test_one_footer_past_the_stale_bound_is_red(self):
        status, detail = pane_lease.pane_report(capture_of([60], self.NOW), now=self.NOW)
        self.assertEqual(status, "RED")
        self.assertIn("exceeds the 20.000s stale bound by 40.000s; no frame interval retained", detail)

    def test_failed_capture_is_unknown(self):
        self.assertEqual(pane_lease.pane_report(None, now=self.NOW)[0], "UNKNOWN")


class ExpectedPanesTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.site = Path(self.tmp.name)
        (self.site / "health").mkdir()

    def tearDown(self):
        self.tmp.cleanup()

    def _windows(self, names):
        (self.site / "health" / "windows.json").write_text(json.dumps(names), encoding="utf-8")

    def test_keeps_only_core_leased_roles(self):
        self._windows(["operator", "health", "witness", "not-a-pane"])
        self.assertEqual(pane_lease.expected_panes(self.site), ["witness", "health"])

    def test_operator_only_declares_no_leased_pane(self):
        self._windows(["operator"])
        self.assertIsNone(pane_lease.expected_panes(self.site))

    def test_missing_windows_file_is_none(self):
        self.assertIsNone(pane_lease.expected_panes(self.site))

    def test_malformed_or_non_list_windows_file_is_none(self):
        (self.site / "health" / "windows.json").write_text("{not json", encoding="utf-8")
        self.assertIsNone(pane_lease.expected_panes(self.site))
        (self.site / "health" / "windows.json").write_text('{"a": 1}', encoding="utf-8")
        self.assertIsNone(pane_lease.expected_panes(self.site))


class SocketTest(unittest.TestCase):
    def test_candidates_are_the_cores_order_without_the_ambient_socket(self):
        candidates = pane_lease.socket_candidates(
            SITE,
            environ={"TMUX_TMPDIR": "/tmp/tmux-1000/android-body",
                     "TMUX": "/tmp/other-site/tmux-1000/default,123,0"},
            uid=1000,
        )
        # The caller's own socket and the home-derived one coincide here.
        self.assertEqual(candidates, (CALLER_SOCKET, LEGACY_SOCKET))
        self.assertNotIn("/tmp/other-site/tmux-1000/default", candidates)

    def test_foreign_tmux_tmpdir_still_reaches_the_home_derived_socket(self):
        candidates = pane_lease.socket_candidates(
            SITE, environ={"TMUX_TMPDIR": "/tmp/tmux-1000/mishe-tauftauf"}, uid=1000)
        self.assertEqual(candidates, (
            "/tmp/tmux-1000/mishe-tauftauf/tmux-1000/default",
            LEGACY_SOCKET,
            CALLER_SOCKET,
        ))

    def test_without_env_only_the_site_derived_and_legacy_sockets(self):
        self.assertEqual(pane_lease.socket_candidates(SITE, environ={}, uid=1000),
                         (CALLER_SOCKET, LEGACY_SOCKET))

    def test_resolve_accepts_the_socket_recording_this_home(self):
        run = fake_run({
            (CALLER_SOCKET, "has-session"): (0, b""),
            (CALLER_SOCKET, "show-option"): (0, SITE_HOME.encode()),
        })
        self.assertEqual(pane_lease.resolve_socket(SITE, "android-body", environ={}, uid=1000, run=run),
                         CALLER_SOCKET)

    def test_resolve_skips_a_server_owned_by_another_home(self):
        # Another plant's same-named session must never be measured.
        run = fake_run({
            (CALLER_SOCKET, "has-session"): (0, b""),
            (CALLER_SOCKET, "show-option"): (0, b"/home/x/other-site/.mishe-tauftauf"),
        })
        self.assertIsNone(pane_lease.resolve_socket(SITE, "android-body", environ={}, uid=1000, run=run))

    def test_resolve_rejects_an_unset_owner_on_a_site_derived_socket(self):
        # The first candidate is the caller's own TMUX_TMPDIR, and session names
        # collide across sites, so a record without the owner option is not
        # evidence of this site (the core's owned_socket requires the match too).
        run = fake_run({(CALLER_SOCKET, "has-session"): (0, b"")})
        self.assertIsNone(pane_lease.resolve_socket(SITE, "android-body", environ={}, uid=1000, run=run))

    def test_resolve_falls_through_to_a_candidate_that_records_this_home(self):
        run = fake_run({
            (CALLER_SOCKET, "has-session"): (0, b""),
            (CALLER_SOCKET, "show-option"): (0, b"/home/x/other-site/.mishe-tauftauf"),
            (LEGACY_SOCKET, "has-session"): (0, b""),
            (LEGACY_SOCKET, "show-option"): (0, SITE_HOME.encode()),
        })
        self.assertEqual(pane_lease.resolve_socket(SITE, "android-body", environ={}, uid=1000, run=run),
                         LEGACY_SOCKET)

    def test_resolve_returns_none_when_no_server_answers(self):
        run = fake_run({})
        self.assertIsNone(pane_lease.resolve_socket(SITE, "android-body", environ={}, uid=1000, run=run))

    def test_resolve_returns_none_when_tmux_is_unavailable(self):
        def run(*a, **k):
            raise FileNotFoundError("tmux")

        self.assertIsNone(pane_lease.resolve_socket(SITE, "android-body", environ={}, uid=1000, run=run))


class MainTest(unittest.TestCase):
    NOW = 1_792_000_000.0

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.site = Path(self.tmp.name)
        (self.site / "health").mkdir()
        (self.site / "health" / "windows.json").write_text(json.dumps(["genome", "witness"]), encoding="utf-8")

    def tearDown(self):
        self.tmp.cleanup()

    def _run(self, text, extra=()):
        argv = ["--site", str(self.site), "--socket", "/tmp/fake", *extra]
        captured = io.StringIO()
        with contextlib.redirect_stdout(captured):
            self.status = pane_lease.main(argv, capture_fn=lambda *a: text, now=self.NOW, load=12.5)
        self.output = captured.getvalue()
        return self.status

    def test_report_lines_carry_the_prefix_health_check_maps(self):
        self._run(capture_of([89, 67, 45, 23, 1], self.NOW))
        self.assertIn("RED    pane lease witness age=1.0s newest_interval=22.000s exceeds the 18.000s advance bound "
                      "by 4.000s (n=4, median=22.000s, worst=22.000s) load1=12.5", self.output)
        self._run(capture_of([18, 12, 6, 0], self.NOW))
        self.assertIn("GREEN  pane lease genome age=0.0s newest_interval=6.000s median=6.000s "
                      "(n=3, advance 18.000s) load1=12.5", self.output)

    def test_relative_site_path_still_derives_the_session(self):
        # A relative --site must not leave the session name empty (the pane name
        # comes from the site's parent directory).
        seen = []
        argv = ["--site", os.path.relpath(self.site), "--socket", "/tmp/fake"]
        with contextlib.redirect_stdout(io.StringIO()):
            pane_lease.main(argv, capture_fn=lambda socket, session, pane, depth: seen.append(session) or "",
                            now=self.NOW, load=1.0)
        self.assertEqual(seen, [self.site.parent.name, self.site.parent.name])

    def test_green_exit(self):
        self.assertEqual(self._run(capture_of([18, 12, 6, 0], self.NOW)), 0)

    def test_red_exit(self):
        self.assertEqual(self._run(capture_of([89, 67, 45, 23, 1], self.NOW)), 1)

    def test_unknown_exit_when_history_is_short(self):
        self.assertEqual(self._run(capture_of([1], self.NOW)), 2)

    def test_unknown_exit_when_nothing_is_declared(self):
        (self.site / "health" / "windows.json").write_text("[]", encoding="utf-8")
        self.assertEqual(self._run(capture_of([0], self.NOW)), 2)

    def test_panes_override_skips_the_declaration(self):
        (self.site / "health" / "windows.json").write_text("[]", encoding="utf-8")
        self.assertEqual(self._run(capture_of([6, 0], self.NOW), extra=["--panes", "genome"]), 0)


class LiveInvocationTest(unittest.TestCase):
    """The real tool, no tmux session: UNKNOWN and exit 2, never a pass."""

    def test_unreadable_panes_read_unknown(self):
        with tempfile.TemporaryDirectory() as tmp:
            site = Path(tmp)
            (site / "health").mkdir()
            (site / "health" / "windows.json").write_text(json.dumps(["operator", "genome"]), encoding="utf-8")
            result = subprocess.run(
                [sys.executable, str(TOOL), "--site", str(site),
                 "--socket", str(site / "no-such-socket"), "--session", "no-such-session"],
                capture_output=True, text=True)
            self.assertEqual(result.returncode, 2)
            self.assertIn("UNKNOWN pane lease genome", result.stdout)
            self.assertNotIn("operator", result.stdout)


if __name__ == "__main__":
    unittest.main()
