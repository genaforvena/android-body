#!/usr/bin/env python3
# SPDX-License-Identifier: CC0-1.0
"""Tests for the present-anchored disk rate (tools/disk_rate.py).

The regression that matters: on 2026-10-21 the host volume drained 12.6-38.5
MiB/min from 02:35Z to 03:06Z and then went flat, while every published figure
was a window that could not contain it -- ``tools/disk_free.py`` names the level
only and the core scan's shortest slope window is 2 days
(``_DISK_TREND_SLOPE_WINDOWS_DAYS``). A rate is a statement about a named window,
so the tool must anchor every window at the newest sample, report a
non-draining window as ``not-draining`` rather than as a large countdown, and
refuse a malformed log instead of computing a rate from the lines that parsed.
"""

import subprocess
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

import disk_rate

TOOL = Path(__file__).with_name("disk_rate.py")
GIB = 2**30

#: A fixed instant, so no test depends on the wall clock.
T0 = datetime(2026, 10, 21, 2, 0, tzinfo=timezone.utc)


def log(*rows):
    """A sample log body from ``(minutes_after_T0, available_bytes)`` pairs."""
    return "".join(
        f"{(T0 + timedelta(minutes=minutes)).isoformat().replace('+00:00', 'Z')} {available}\n"
        for minutes, available in rows)


def run_stdin(body, *args):
    return subprocess.run([sys.executable, str(TOOL), *args], input=body,
                          capture_output=True, text=True, timeout=30)


class ParseSamplesTest(unittest.TestCase):
    def test_reads_a_sample_per_line(self):
        samples, reason = disk_rate.parse_samples(log((0, 20 * GIB), (10, 19 * GIB)))
        self.assertIsNone(reason)
        self.assertEqual(samples, [(T0, 20 * GIB), (T0 + timedelta(minutes=10), 19 * GIB)])

    def test_blank_lines_are_skipped(self):
        samples, reason = disk_rate.parse_samples("\n" + log((0, 20 * GIB)) + "\n\n")
        self.assertIsNone(reason)
        self.assertEqual(len(samples), 1)

    def test_a_newest_first_log_is_sorted(self):
        samples, reason = disk_rate.parse_samples(log((10, 19 * GIB), (0, 20 * GIB)))
        self.assertIsNone(reason)
        self.assertEqual([stamp for stamp, _bytes in samples], [T0, T0 + timedelta(minutes=10)])

    def test_a_malformed_line_is_unavailable(self):
        # A dropped line would silently change the window, so it is not skipped.
        samples, reason = disk_rate.parse_samples(log((0, 20 * GIB)) + "2026-10-21T02:10:00Z\n")
        self.assertIsNone(samples)
        self.assertIn("not '<timestamp> <bytes>'", reason)

    def test_a_naive_timestamp_is_unavailable(self):
        samples, reason = disk_rate.parse_samples("2026-10-21T02:00:00 20000000000\n")
        self.assertIsNone(samples)
        self.assertIn("without a zone", reason)

    def test_a_non_numeric_count_is_unavailable(self):
        samples, reason = disk_rate.parse_samples("2026-10-21T02:00:00Z plenty\n")
        self.assertIsNone(samples)
        self.assertIn("non-numeric", reason)

    def test_no_samples_is_unavailable(self):
        self.assertEqual(disk_rate.parse_samples(""), (None, "no samples"))


class DrainTest(unittest.TestCase):
    def test_rate_is_anchored_at_the_newest_sample(self):
        # 1 GiB lost over the last hour = 24 GiB/day; the identical older hour must
        # not dilute it, because the window named "1h" is the hour before the present.
        samples = [(T0, 30 * GIB), (T0 + timedelta(hours=1), 29 * GIB),
                   (T0 + timedelta(hours=2), 28 * GIB)]
        rate, span = disk_rate.drain_per_day(samples, 3600)
        self.assertEqual(span, 3600)
        self.assertAlmostEqual(rate, 24 * GIB, delta=1)

    def test_the_same_window_moves_when_the_present_moves(self):
        # A 2 h window over this log is the whole log (24 GiB/day); a 1 h window is
        # the last hour. The pair is why the window has to be named.
        samples = [(T0, 30 * GIB), (T0 + timedelta(hours=1), 29 * GIB),
                   (T0 + timedelta(hours=2), 28 * GIB)]
        self.assertAlmostEqual(disk_rate.drain_per_day(samples, 7200)[0], 24 * GIB, delta=1)

    def test_a_window_longer_than_the_log_has_no_anchor(self):
        samples = [(T0, 20 * GIB), (T0 + timedelta(minutes=10), 19 * GIB)]
        self.assertEqual(disk_rate.drain_per_day(samples, 86400), (None, None))

    def test_a_window_below_the_minimum_span_has_no_rate(self):
        # A window narrower than the minimum is timing noise, not a rate; the
        # anchor exists, so the span is reported and only the rate is withheld.
        samples = [(T0, 20 * GIB), (T0 + timedelta(seconds=5), 19 * GIB),
                   (T0 + timedelta(seconds=30), 18 * GIB)]
        rate, span = disk_rate.drain_per_day(samples, 10)
        self.assertIsNone(rate)
        self.assertEqual(span, 25)

    def test_filling_reads_negative(self):
        samples = [(T0, 20 * GIB), (T0 + timedelta(hours=1), 21 * GIB)]
        rate, _span = disk_rate.drain_per_day(samples, 3600)
        self.assertLess(rate, 0)

    def test_eta_is_none_when_not_draining_or_at_the_floor(self):
        self.assertIsNone(disk_rate.eta_hours(3 * GIB, -1.0))
        self.assertIsNone(disk_rate.eta_hours(3 * GIB, 0.0))
        self.assertIsNone(disk_rate.eta_hours(0, 1.0))

    def test_eta_is_headroom_over_rate(self):
        # 1 GiB/day with 2 GiB of headroom is 48 h.
        self.assertAlmostEqual(disk_rate.eta_hours(2 * GIB, 1 * GIB), 48.0)


class ReportTest(unittest.TestCase):
    def test_a_flat_log_is_green_with_no_eta(self):
        # The exact shape of the 03:06Z->03:19Z window: +0.4 MiB/min, i.e. flat.
        samples = [(T0, 13 * GIB), (T0 + timedelta(hours=1), 13 * GIB)]
        lines, code = disk_rate.report(samples, 10 * GIB, [3600], 24.0)
        self.assertEqual(code, 0)
        self.assertIn("not-draining", "\n".join(lines))
        self.assertIn("no floor ETA", "\n".join(lines))

    def test_a_burst_within_the_horizon_is_red(self):
        # 2 GiB/h = 48 GiB/day with the newest sample at 11 GiB: 1 GiB of headroom
        # to the 10 GiB floor, so ~0.5 h, inside 24 h. The level is the newest
        # sample, not the oldest.
        samples = [(T0, 13 * GIB), (T0 + timedelta(hours=1), 11 * GIB)]
        lines, code = disk_rate.report(samples, 10 * GIB, [3600], 24.0)
        self.assertEqual(code, 1)
        self.assertIn("floor in 0.50h", "\n".join(lines))

    def test_a_slow_rate_outside_the_horizon_is_green(self):
        # 1 GiB/day with the newest sample at 12 GiB: 2 GiB of headroom, 48 h,
        # outside a 24 h horizon.
        samples = [(T0, 13 * GIB), (T0 + timedelta(days=1), 12 * GIB)]
        lines, code = disk_rate.report(samples, 10 * GIB, [86400], 24.0)
        self.assertEqual(code, 0)
        self.assertIn("48.00h", "\n".join(lines))

    def test_disagreeing_windows_publish_a_range_and_say_so(self):
        samples = [(T0, 14 * GIB), (T0 + timedelta(hours=1), 12 * GIB),
                   (T0 + timedelta(hours=2), 11 * GIB)]
        lines, _code = disk_rate.report(samples, 10 * GIB, [3600, 7200], 24.0)
        body = "\n".join(lines)
        self.assertIn("windows disagree: window-only projection", body)
        self.assertIn("-", body.split("floor in ")[1].split("h")[0])

    def test_below_the_floor_is_red_without_a_countdown(self):
        samples = [(T0, 9 * GIB), (T0 + timedelta(hours=1), 8 * GIB)]
        lines, code = disk_rate.report(samples, 10 * GIB, [3600], 24.0)
        self.assertEqual(code, 1)
        self.assertIn("below the floor by 2.00GiB", "\n".join(lines))

    def test_a_sparse_log_annotates_the_span_it_measured(self):
        # A 10-minute log cannot support a 1m label: the anchor is the newest sample
        # at or before newest - 1m, which is 10 minutes back. The rate is a 10-minute
        # rate, so the span is printed rather than a window the label overstates.
        samples = [(T0, 20 * GIB), (T0 + timedelta(minutes=10), 19 * GIB)]
        lines, _code = disk_rate.report(samples, 10 * GIB, [60], 24.0)
        self.assertIn("1m: +144.00GiB/day (span 10.00min)", "\n".join(lines))

    def test_a_dense_log_does_not_annotate_a_matching_span(self):
        # The anchor's own granularity is not a defect: an hourly sample measured over
        # a 1h window keeps its label.
        samples = [(T0, 13 * GIB), (T0 + timedelta(hours=1), 12 * GIB),
                   (T0 + timedelta(hours=2), 11 * GIB)]
        lines, _code = disk_rate.report(samples, 10 * GIB, [3600], 24.0)
        self.assertNotIn("(span", "\n".join(lines))

    def test_a_gap_in_the_log_is_named_on_the_long_window(self):
        # The newest sample at or before newest - 2d is 2.52d back, so the span
        # crosses a gap and the label must not read as a 2-day measurement.
        samples = [(T0, 30 * GIB), (T0 + timedelta(days=0.48), 20 * GIB),
                   (T0 + timedelta(days=3), 12 * GIB)]
        lines, _code = disk_rate.report(samples, 10 * GIB, [2 * 86400], 24.0)
        self.assertIn("(span 2.52d)", "\n".join(lines))

    def test_the_level_line_carries_the_newest_sample_time(self):
        # The tool has no clock, so this timestamp is the reader's staleness reference.
        samples = [(T0, 13 * GIB), (T0 + timedelta(hours=1), 12 * GIB)]
        lines, _code = disk_rate.report(samples, 10 * GIB, [3600], 24.0)
        self.assertIn("newest sample 2026-10-21T03:00:00Z", lines[0])

    def test_a_not_draining_window_disagrees_with_a_draining_one(self):
        # Witness wake 123952 case G: 1h flat, 7d draining. The countdown used to
        # print as unanimous; now the disagreement is named.
        samples = [(T0, 30 * GIB), (T0 + timedelta(hours=1), 29 * GIB),
                   (T0 + timedelta(days=7), 29 * GIB)]
        lines, code = disk_rate.report(samples, 10 * GIB, [3600, 604800], 24.0)
        body = "\n".join(lines)
        self.assertEqual(code, 0)
        self.assertIn("not-draining", body)
        self.assertIn("windows disagree: window-only projection", body)


class CliTest(unittest.TestCase):
    def test_a_burst_log_exits_red(self):
        result = run_stdin(log((0, 13 * GIB), (60, 11 * GIB)))
        self.assertEqual(result.returncode, 1)
        self.assertIn("GiB/day", result.stdout)

    def test_an_unreadable_log_exits_two(self):
        result = run_stdin("")
        self.assertEqual(result.returncode, 2)
        self.assertTrue(result.stdout.startswith("UNKNOWN disk rate"))

    def test_a_bad_window_exits_two(self):
        result = run_stdin(log((0, 13 * GIB), (60, 12 * GIB)), "--windows", "soon")
        self.assertEqual(result.returncode, 2)
        self.assertTrue(result.stdout.startswith("UNKNOWN disk rate"))

    def test_a_bad_bound_exits_two(self):
        result = run_stdin(log((0, 13 * GIB)), "--floor-bytes", "plenty")
        self.assertEqual(result.returncode, 2)

    def test_a_log_shorter_than_every_window_is_unknown_not_green(self):
        # Nothing was measured, so nothing is claimed: the pre-change bytes printed
        # "no window is draining" here, which reads as a volume that is holding.
        result = run_stdin(log((0, 20 * GIB), (10, 19 * GIB)), "--windows", "7d,14d")
        self.assertEqual(result.returncode, 2)
        self.assertIn("UNKNOWN no window anchored", result.stdout)

    def test_a_window_longer_than_the_log_is_reported_not_invented(self):
        # The 10-minute log supports "1m" and not "7d"; the unsupported window is
        # named as such rather than anchored at the oldest sample.
        result = run_stdin(log((0, 20 * GIB), (10, 19 * GIB)), "--windows", "1m,7d")
        self.assertEqual(result.returncode, 1)
        self.assertIn("log shorter than the window", result.stdout)
        self.assertIn("1m: +144.00GiB/day (span 10.00min)", result.stdout)


if __name__ == "__main__":
    unittest.main()
