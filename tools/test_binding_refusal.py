#!/usr/bin/env python3
# SPDX-License-Identifier: CC0-1.0
"""Tests for the binding-refusal detector (tools/binding_refusal.py).

The regression that matters: on 2026-10-17 this plant's own panes produced 12
binding refusals in 09:00-11:09Z because the charter fix (witness wake 106367)
is on disk but the running panes still carry the pre-edit delivery. The guard
writes every refusal to ``<bound-site>/logs/binding-refusal-audit.jsonl`` and
nothing read that log, so the dead route surfaced only when a mind happened to
open the file. The detector must RED on a non-zero refusal count inside the
window, GREEN on zero, and UNKNOWN -- never a pass -- when the log is missing
or malformed. The fixtures write real audit-log lines because the format is
the guard's own.
"""

import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

import binding_refusal


def entry(ts, attempted="/home/mesh-home/mishe-tauftauf/.mishe-tauftauf",
          bound="/home/mesh-home/android-body/.mishe-tauftauf"):
    return {"ts": ts, "attempted_home": attempted, "bound_home": bound,
            "command": "probe", "pid": 1, "ppid": 2, "uid": 1000}


class RefusalCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.site = Path(self.tmp.name)
        self.log = self.site / binding_refusal.AUDIT_REL

    def write(self, *entries):
        self.log.parent.mkdir(parents=True, exist_ok=True)
        with open(self.log, "w", encoding="utf-8") as fh:
            for item in entries:
                fh.write((item if isinstance(item, str)
                          else json.dumps(item)) + "\n")

    def test_no_log_is_unknown(self):
        rc, lines = binding_refusal.check(self.site)
        self.assertEqual(rc, 2)
        self.assertIn("UNKNOWN", lines[0])

    def test_empty_log_is_green(self):
        self.write()
        rc, lines = binding_refusal.check(self.site)
        self.assertEqual(rc, 0)
        self.assertIn("GREEN", lines[0])
        self.assertIn("0 in 24h", lines[0])

    def test_old_entries_are_green(self):
        old = datetime.now(timezone.utc) - timedelta(hours=25)
        self.write(entry(old.isoformat()))
        rc, _ = binding_refusal.check(self.site)
        self.assertEqual(rc, 0)

    def test_recent_entry_is_red(self):
        recent = datetime.now(timezone.utc) - timedelta(minutes=5)
        self.write(entry(recent.isoformat()))
        rc, lines = binding_refusal.check(self.site)
        self.assertEqual(rc, 1)
        self.assertIn("RED", lines[0])
        self.assertIn("1 in 24h", lines[0])
        self.assertIn("5.0m ago", lines[0])

    def test_count_and_newest_age(self):
        now = datetime.now(timezone.utc)
        self.write(entry((now - timedelta(minutes=30)).isoformat()),
                   entry((now - timedelta(minutes=2)).isoformat()),
                   entry((now - timedelta(minutes=10)).isoformat()))
        rc, lines = binding_refusal.check(self.site)
        self.assertEqual(rc, 1)
        self.assertIn("3 in 24h", lines[0])
        self.assertIn("2.0m ago", lines[0])

    def test_window_excludes_older(self):
        now = datetime.now(timezone.utc)
        self.write(entry((now - timedelta(hours=23)).isoformat()),
                   entry((now - timedelta(hours=25)).isoformat()))
        rc, lines = binding_refusal.check(self.site)
        self.assertEqual(rc, 1)
        self.assertIn("1 in 24h", lines[0])

    def test_window_boundary_inclusive(self):
        now = datetime.now(timezone.utc)
        self.write(entry((now - timedelta(hours=24)).isoformat()))
        rc, _ = binding_refusal.check(self.site, now=now)
        self.assertEqual(rc, 1)

    def test_future_entry_not_counted(self):
        future = datetime.now(timezone.utc) + timedelta(minutes=5)
        self.write(entry(future.isoformat()))
        rc, _ = binding_refusal.check(self.site)
        self.assertEqual(rc, 0)

    def test_malformed_json_is_unknown(self):
        self.write("{not json")
        rc, lines = binding_refusal.check(self.site)
        self.assertEqual(rc, 2)
        self.assertIn("UNKNOWN", lines[0])

    def test_missing_ts_is_unknown(self):
        e = entry("2026-01-01T00:00:00+00:00")
        del e["ts"]
        self.write(e)
        rc, _ = binding_refusal.check(self.site)
        self.assertEqual(rc, 2)

    def test_malformed_ts_is_unknown(self):
        self.write(entry("not-a-timestamp"))
        rc, _ = binding_refusal.check(self.site)
        self.assertEqual(rc, 2)
    def test_naive_ts_is_unknown(self):
        self.write(entry("2026-10-17T09:00:00"))
        rc, _ = binding_refusal.check(self.site)
        self.assertEqual(rc, 2)

    def test_errors_take_precedence_over_recent(self):
        now = datetime.now(timezone.utc)
        self.write("{not json",
                   entry((now - timedelta(minutes=5)).isoformat()))
        rc, _ = binding_refusal.check(self.site)
        self.assertEqual(rc, 2)

    def test_invalid_utf8_is_unknown(self):
        self.log.parent.mkdir(parents=True, exist_ok=True)
        with open(self.log, "wb") as fh:
            fh.write(b'{"ts": "2026-10-17T09:00:00+00:00", "attempted_home": "\xff\xfe"}')
        rc, _ = binding_refusal.check(self.site)
        self.assertEqual(rc, 2)

    def test_missing_attempted_home_renders_question_mark(self):
        now = datetime.now(timezone.utc)
        e = entry((now - timedelta(minutes=5)).isoformat())
        del e["attempted_home"]
        self.write(e)
        rc, lines = binding_refusal.check(self.site)
        self.assertEqual(rc, 1)
        self.assertIn("?", lines[0])
        self.assertNotIn("None", lines[0])

    def test_non_object_entry_is_unknown(self):
        self.write("[1, 2]")
        rc, _ = binding_refusal.check(self.site)
        self.assertEqual(rc, 2)

    def test_attempted_homes_listed(self):
        now = datetime.now(timezone.utc)
        self.write(entry((now - timedelta(minutes=5)).isoformat(),
                          attempted="/home/mesh-home/mishe-tauftauf/.mishe-tauftauf"),
                   entry((now - timedelta(minutes=3)).isoformat(),
                          attempted="/home/mesh-home/other-site/.mishe-tauftauf"))
        rc, lines = binding_refusal.check(self.site)
        self.assertEqual(rc, 1)
        self.assertIn("mishe-tauftauf", lines[0])
        self.assertIn("other-site", lines[0])

    def test_custom_window(self):
        now = datetime.now(timezone.utc)
        self.write(entry((now - timedelta(hours=2)).isoformat()))
        rc, _ = binding_refusal.check(self.site, window_hours=1.0)
        self.assertEqual(rc, 0)
        rc, _ = binding_refusal.check(self.site, window_hours=3.0)
        self.assertEqual(rc, 1)

    def test_total_count_reports_all_entries(self):
        now = datetime.now(timezone.utc)
        self.write(entry((now - timedelta(hours=48)).isoformat()),
                   entry((now - timedelta(minutes=5)).isoformat()))
        rc, lines = binding_refusal.check(self.site)
        self.assertEqual(rc, 1)
        self.assertIn("2 total", lines[0])

    def test_blank_lines_skipped(self):
        now = datetime.now(timezone.utc)
        self.log.parent.mkdir(parents=True, exist_ok=True)
        with open(self.log, "w", encoding="utf-8") as fh:
            fh.write("\n" + json.dumps(entry((now - timedelta(minutes=5)).isoformat())) + "\n\n")
        rc, lines = binding_refusal.check(self.site)
        self.assertEqual(rc, 1)
        self.assertIn("1 in 24h", lines[0])


if __name__ == "__main__":
    unittest.main()
