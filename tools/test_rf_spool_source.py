#!/usr/bin/env python3
# SPDX-License-Identifier: CC0-1.0
"""Tests for the RF-harness spool source (tools/rf_spool_source.py).

The regressions that matter: the emitted line must carry the harness's
``row_age_s=``/``last_error=`` tokens from the *fresh* published pair; a stale
row must force exactly one bounded publication and then report the refreshed
row; a fresh row must not cause a publication; an unusable input must print no
gate token and still exit 0 (fail closed, reason recorded by the harness); a
failed publication must not be laundered into a number; and the age resolver
must agree with the perception consumer's on the same fixtures, so the two
host-domain readings cannot drift apart.
"""

import contextlib
import importlib.util
import io
import json
import os
import shlex
import sys
import tempfile
import unittest
from pathlib import Path

import rf_spool_source

NODE = "note3"
NOW = 1792139374.0
OFFSET = 25.025
PERCEPTION = Path(__file__).resolve().parent.parent / "experiments" / "perception" / "watch.py"


def clock_document(observed_at=None, **overrides):
    document = {"node": NODE, "source": "tools/clock_offset.py",
                "method": "adb-shell-date-minus-host-wall", "status": "ok",
                "observed_at_epoch_s": NOW - 10.0, "validity_seconds": 3600.0,
                "samples": 3, "quantization_s": 1.0, "rtt_max_s": 0.06,
                "offset_min_s": OFFSET - 0.5, "offset_max_s": OFFSET + 0.5,
                "offset_nominal_s": OFFSET, "host_ntp_synchronized": False,
                "jump": None, "reason": None}
    if observed_at is not None:
        document["observed_at_epoch_s"] = observed_at
    document.update(overrides)
    return document


def summary_document(row_age=2.0, summary_age=1.0, **overrides):
    document = {"node": NODE, "source": "tools/spool_read.py",
                "method": "adb-run-as-grep-counts", "status": "ok",
                "observed_at_epoch_s": NOW - summary_age,
                "validity_seconds": 300.0, "spool_bytes": 3858200,
                "retention_window_s": 14489.0,
                "oldest_row_epoch_s": NOW - 14489.0,
                "newest_row_epoch_s": NOW - 60.0,
                "counts": {"light": 2848}, "light_buckets": {"dark_exact": 200},
                "overflow": {"dropped": 210441, "notice_epoch_s": NOW - 160},
                "scan_state": {"epoch_s": round(NOW - row_age - OFFSET),
                               "windows": 269, "phase": "window",
                               "last_error": "none", "sightings": 155,
                               "window_ms": 60000, "gap_ms": 60000},
                "reason": None}
    document.update(overrides)
    return document

def write_json(path, document):
    Path(path).write_text(json.dumps(document), encoding="utf-8")
    return Path(path)


def rewrite_command(path, document):
    """A reader command that replaces ``path`` with ``document``."""
    code = "import json,sys;json.dump(json.loads(sys.argv[2]),open(sys.argv[1],'w'))"
    return " ".join([shlex.quote(sys.executable), "-c", shlex.quote(code),
                     shlex.quote(str(path)), shlex.quote(json.dumps(document))])


def marker_command(marker):
    """A reader command that records that it ran."""
    return f"sh -c {shlex.quote('echo ran >> ' + str(marker))}"


def fail_command():
    return f"sh -c {shlex.quote('exit 7')}"


def load_watch():
    spec = importlib.util.spec_from_file_location("perception_watch", PERCEPTION)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class SourceTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.site = Path(self.tmp.name)
        (self.site / "body").mkdir()
        self.summary = self.site / "body" / f"spool-summary-{NODE}.json"
        self.clock = self.site / "body" / f"clock-domain-{NODE}.json"
        self.marker = self.site / "reader-ran"
        write_json(self.clock, clock_document())

    def run_tool(self, *argv):
        """Run main() with a fixed clock; return (rc, stdout)."""
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            rc = rf_spool_source.main(["--site", str(self.site), "--node", NODE,
                                       "--now", str(NOW), *argv])
        return rc, out.getvalue()

    def tokens(self, line):
        fields = {}
        for token in line.split():
            if "=" in token:
                key, _, value = token.partition("=")
                fields[key] = value
        return fields


class ContractLineTests(SourceTestCase):
    def test_emits_the_harness_line_from_the_published_pair(self):
        write_json(self.summary, summary_document())
        rc, out = self.run_tool("--no-refresh")
        self.assertEqual(rc, 0)
        fields = self.tokens(out)
        self.assertEqual(fields["row_age_s"], "2.0")
        self.assertEqual(fields["last_error"], "none")
        self.assertEqual(fields["phase"], "window")
        self.assertEqual(fields["windows"], "269")
        self.assertEqual(fields["refreshed"], "no")
        self.assertTrue(out.startswith(f"epoch={round(NOW - 2.0 - OFFSET)} "), out)

    def test_reports_the_summary_age_separately_from_the_row_age(self):
        write_json(self.summary, summary_document(row_age=150.0, summary_age=1.0))
        rc, out = self.run_tool("--no-refresh")
        self.assertEqual(rc, 0)
        fields = self.tokens(out)
        self.assertEqual(fields["row_age_s"], "150.0")
        self.assertEqual(fields["summary_age_s"], "1.0")

    def test_unusable_row_prints_no_gate_token_and_still_exits_zero(self):
        write_json(self.summary, summary_document(status="unavailable", scan_state=None))
        rc, out = self.run_tool("--no-refresh")
        self.assertEqual(rc, 0)
        self.assertIn("spool-source unusable: summary-unavailable", out)
        self.assertNotIn("row_age_s=", out)
        self.assertNotIn("last_error=", out)

    def test_a_stopped_scan_loop_is_still_visible_as_phase_none(self):
        write_json(self.summary, summary_document())
        document = summary_document()
        document["scan_state"]["phase"] = "none"
        document["scan_state"]["windows"] = 146
        write_json(self.summary, document)
        rc, out = self.run_tool("--no-refresh")
        self.assertEqual(rc, 0)
        fields = self.tokens(out)
        self.assertEqual(fields["phase"], "none")
        self.assertEqual(fields["windows"], "146")
        self.assertEqual(fields["row_age_s"], "2.0")

    def test_an_unhashable_phase_is_unusable_not_a_traceback(self):
        # A JSON array/object phase is unhashable; ``phase not in frozenset`` raised
        # TypeError (rc 1, empty stdout, reason discarded), violating the documented
        # unusable-input contract (docs/verification.md:320).
        for phase in (["window"], {"phase": "window"}):
            document = summary_document()
            document["scan_state"]["phase"] = phase
            write_json(self.summary, document)
            rc, out = self.run_tool("--no-refresh")
            self.assertEqual(rc, 0)
            self.assertIn("spool-source unusable: scan-state-invalid", out)
            self.assertNotIn("row_age_s=", out)
            self.assertNotIn("last_error=", out)
            self.assertNotIn("Traceback", out)


class RefreshTests(SourceTestCase):
    def test_a_stale_row_forces_one_publication_and_reports_the_fresh_row(self):
        write_json(self.summary, summary_document(row_age=168.0, summary_age=162.0))
        fresh = summary_document(row_age=1.0, summary_age=0.0)
        rc, out = self.run_tool("--reader", rewrite_command(self.summary, fresh),
                                "--refresh-below", "60")
        self.assertEqual(rc, 0)
        fields = self.tokens(out)
        self.assertEqual(fields["refreshed"], "summary")
        self.assertEqual(fields["row_age_s"], "1.0")
        self.assertEqual(fields["windows"], "269")

    def test_a_fresh_row_does_not_run_the_reader(self):
        write_json(self.summary, summary_document(row_age=5.0))
        rc, out = self.run_tool("--reader", marker_command(self.marker))
        self.assertEqual(rc, 0)
        self.assertEqual(self.tokens(out)["refreshed"], "no")
        self.assertFalse(self.marker.exists())

    def test_the_refresh_boundary_is_the_gate_bound(self):
        write_json(self.summary, summary_document(row_age=59.0))
        rc, out = self.run_tool("--reader", marker_command(self.marker))
        self.assertEqual(self.tokens(out)["refreshed"], "no")
        self.assertFalse(self.marker.exists())

        write_json(self.summary, summary_document(row_age=60.0))
        rc, out = self.run_tool("--reader", marker_command(self.marker))
        self.assertEqual(self.tokens(out)["refreshed"], "summary")
        self.assertTrue(self.marker.exists())

    def test_a_failed_publication_is_not_laundered_into_a_number(self):
        write_json(self.summary, summary_document(row_age=168.0))
        rc, out = self.run_tool("--reader", fail_command())
        self.assertEqual(rc, 0)
        self.assertIn("spool-source unusable: refresh-failed rc=7", out)
        self.assertNotIn("row_age_s=", out)

    def test_a_missing_summary_is_refreshed_before_giving_up(self):
        fresh = summary_document(row_age=1.0)
        rc, out = self.run_tool("--reader", rewrite_command(self.summary, fresh))
        self.assertEqual(rc, 0)
        self.assertEqual(self.tokens(out)["refreshed"], "summary")
        self.assertEqual(self.tokens(out)["row_age_s"], "1.0")

    def test_a_stale_clock_reading_is_refreshed_before_the_summary(self):
        write_json(self.clock, clock_document(observed_at=NOW - 4000.0))
        write_json(self.summary, summary_document(row_age=1.0))
        fresh_clock = clock_document(observed_at=NOW - 2.0)
        rc, out = self.run_tool("--clock-reader", rewrite_command(self.clock, fresh_clock),
                                "--reader", marker_command(self.marker))
        self.assertEqual(rc, 0)
        self.assertEqual(self.tokens(out)["refreshed"], "clock")
        self.assertEqual(self.tokens(out)["row_age_s"], "1.0")
        self.assertFalse(self.marker.exists())

    def test_a_failed_clock_publication_is_named_not_hidden(self):
        write_json(self.clock, clock_document(observed_at=NOW - 4000.0))
        write_json(self.summary, summary_document())
        rc, out = self.run_tool("--clock-reader", fail_command())
        self.assertEqual(rc, 0)
        self.assertIn("spool-source unusable: clock-refresh-failed rc=7", out)
        self.assertNotIn("row_age_s=", out)

    def test_no_refresh_never_runs_a_publication(self):
        write_json(self.summary, summary_document(row_age=168.0))
        rc, out = self.run_tool("--no-refresh", "--reader", marker_command(self.marker),
                                "--clock-reader", marker_command(self.marker))
        self.assertEqual(rc, 0)
        self.assertEqual(self.tokens(out)["row_age_s"], "168.0")
        self.assertFalse(self.marker.exists())

    def test_a_timeout_is_bounded_and_reported(self):
        write_json(self.summary, summary_document(row_age=168.0))
        rc, out = self.run_tool("--reader", "sleep 30", "--timeout", "0.5")
        self.assertEqual(rc, 0)
        self.assertIn("spool-source unusable: refresh-timeout", out)



class ReferenceClockTests(SourceTestCase):
    """A publication takes seconds; the reference must follow it.

    The row a publication writes is stamped after the reference taken before
    it, so a fixed reference ages a perfectly fresh row as negative and the
    guard rejects the line as ``row-epoch-in-future``. Found by this tool's
    first live run; both directions are pinned here.
    """

    def build(self, ticks, fallback=NOW + 7.0):
        write_json(self.summary, summary_document(row_age=168.0))
        fresh = summary_document(row_age=-7.0)
        return rf_spool_source.Source(
            self.site, NODE, reader=rewrite_command(self.summary, fresh),
            clock_reader=fail_command(),
            now_fn=lambda: next(ticks, fallback))

    def test_the_reference_clock_is_resampled_after_a_publication(self):
        source = self.build(iter([NOW, NOW, NOW + 7.0, NOW + 7.0]))
        summary, clock, refreshed, problem, now = source.read()
        self.assertIsNone(problem)
        self.assertEqual(refreshed, ["summary"])
        age, reason = rf_spool_source.scan_state_row_age(summary["scan_state"], now, clock)
        self.assertIsNone(reason)
        self.assertAlmostEqual(age, 0.0, places=1)

    def test_a_pre_publication_reference_would_reject_that_row(self):
        source = self.build(iter([NOW] * 8))
        summary, clock, refreshed, problem, now = source.read()
        age, reason = rf_spool_source.scan_state_row_age(summary["scan_state"], now, clock)
        self.assertIsNone(age)
        self.assertEqual(reason, "row-epoch-in-future")


class ClockDomainTests(SourceTestCase):
    def test_a_missing_clock_reading_is_unknown_not_a_number(self):
        write_json(self.summary, summary_document())
        os.remove(self.clock)
        rc, out = self.run_tool("--no-refresh")
        self.assertEqual(rc, 0)
        self.assertIn("spool-source unusable: clock-domain-unresolved", out)

    def test_a_jumped_clock_reading_is_unknown(self):
        write_json(self.clock, clock_document(jump={"delta_s": 30.0}))
        write_json(self.summary, summary_document())
        rc, out = self.run_tool("--no-refresh")
        self.assertEqual(rc, 0)
        self.assertIn("spool-source unusable: clock-domain-jump", out)

    def test_a_row_stamped_after_the_host_is_unknown(self):
        document = summary_document()
        document["scan_state"]["epoch_s"] = int(NOW - OFFSET + 5)
        write_json(self.summary, document)
        rc, out = self.run_tool("--no-refresh")
        self.assertEqual(rc, 0)
        self.assertIn("spool-source unusable: row-epoch-in-future", out)

    def test_a_row_inside_the_offset_band_clamps_to_zero(self):
        document = summary_document()
        document["scan_state"]["epoch_s"] = int(NOW - OFFSET + 0.25)
        write_json(self.summary, document)
        rc, out = self.run_tool("--no-refresh")
        self.assertEqual(rc, 0)
        self.assertEqual(self.tokens(out)["row_age_s"], "0.0")


class BoundsTests(SourceTestCase):
    def test_an_oversized_document_is_rejected_before_parsing(self):
        write_json(self.summary, summary_document())
        with open(self.summary, "ab") as handle:
            handle.write(b" " * 4096)
        rc, out = self.run_tool("--no-refresh", "--max-bytes", "1024")
        self.assertEqual(rc, 0)
        self.assertIn("spool-source unusable: summary-unavailable", out)

    def test_default_site_is_derived_from_the_tool_location(self):
        self.assertEqual(rf_spool_source.default_site("/repo/tools/rf_spool_source.py"),
                         Path("/repo/.mishe-tauftauf"))


class PerceptionParityTests(unittest.TestCase):
    """The two host-domain age resolvers must not drift apart."""

    @classmethod
    def setUpClass(cls):
        cls.watch = load_watch()

    def parity(self, scan_state, clock_document_value, present=True):
        with tempfile.TemporaryDirectory() as tmp:
            body = Path(tmp) / "body"
            (body / "perception").mkdir(parents=True)
            clock_path = body / f"clock-domain-{NODE}.json"
            if present:
                write_json(clock_path, clock_document_value)
            consumer_clock = self.watch.read_clock_domain(body / "perception", NODE, NOW)
            mine = rf_spool_source.read_clock_domain(clock_path, NODE, NOW)
            self.assertEqual(mine["status"], consumer_clock["status"])
            self.assertEqual(mine["reason"], consumer_clock["reason"])
            self.assertEqual(mine["age_s"], consumer_clock["age_s"])
            self.assertEqual(mine["jump"], consumer_clock["jump"])
            self.assertEqual(rf_spool_source.scan_state_row_age(scan_state, NOW, mine),
                             self.watch.spool_scan_state_row_age(scan_state, NOW, consumer_clock))

    def test_fresh_clock_agrees(self):
        self.parity(summary_document()["scan_state"], clock_document())

    def test_stale_clock_agrees(self):
        self.parity(summary_document()["scan_state"],
                    clock_document(observed_at=NOW - 4000.0))

    def test_inverted_offset_bounds_agree(self):
        self.parity(summary_document()["scan_state"],
                    clock_document(offset_min_s=30.0, offset_max_s=20.0))

    def test_missing_clock_file_agrees(self):
        self.parity(summary_document()["scan_state"], clock_document(), present=False)

    def test_malformed_clock_file_agrees(self):
        with tempfile.TemporaryDirectory() as tmp:
            body = Path(tmp) / "body"
            (body / "perception").mkdir(parents=True)
            clock_path = body / f"clock-domain-{NODE}.json"
            clock_path.write_text("{not json", encoding="utf-8")
            consumer_clock = self.watch.read_clock_domain(body / "perception", NODE, NOW)
            mine = rf_spool_source.read_clock_domain(clock_path, NODE, NOW)
            self.assertEqual((mine["status"], mine["reason"]),
                             (consumer_clock["status"], consumer_clock["reason"]))
            self.assertEqual(rf_spool_source.scan_state_row_age(None, NOW, mine),
                             self.watch.spool_scan_state_row_age(None, NOW, consumer_clock))

    def test_foreign_node_agrees(self):
        self.parity(summary_document()["scan_state"], clock_document(node="redmi10"))

    def test_producer_declared_absence_agrees(self):
        # The producer's status="unavailable" is an absent reading carrying its own
        # bounded reason; both readers must agree on that, not call it invalid.
        self.parity(summary_document()["scan_state"],
                    clock_document(status="unavailable", samples=0, reason="no adb path",
                                   offset_min_s=None, offset_max_s=None,
                                   offset_nominal_s=None))

    def test_producer_declared_absence_drops_a_forged_reason_identically(self):
        # The reason guard (bounded, printable) is duplicated verbatim in the mirror,
        # and the mirror is the reader the RF harness runs. A fixture that only carries
        # a well-formed reason would let the two copies drift apart on exactly the
        # hand-written cases the guard exists for, so every drop path is compared.
        for reason in ("no adb path\nclock-domain alarm: forged", "\x1b[2Jno adb path",
                       "x" * 201, "", 7):
            with self.subTest(reason=reason):
                self.parity(summary_document()["scan_state"],
                            clock_document(status="unavailable", samples=0, reason=reason,
                                           offset_min_s=None, offset_max_s=None,
                                           offset_nominal_s=None))

    def test_absent_row_agrees(self):
        self.parity(None, clock_document())

    def test_absent_row_epoch_agrees(self):
        self.parity({"windows": 1, "phase": "gap"}, clock_document())

    def test_future_row_agrees(self):
        self.parity({"epoch_s": int(NOW - OFFSET + 5)}, clock_document())


if __name__ == "__main__":
    unittest.main()
