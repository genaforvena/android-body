# SPDX-License-Identifier: CC0-1.0
"""Tests for the bounded clock-offset publisher (tools/clock_offset.py).

The regressions that matter: the published interval must actually bound the true
offset (a wrong bound silently invalidates the consumer's latency arithmetic), an
unreadable device must publish ``unavailable`` with null offsets instead of a
stale number, and the document must land outside the consumer's state glob
(``body/perception/*.json``) so it can never be parsed as a perception state.
"""

import json
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

import clock_offset

SERIAL = "4d00553d61ab90b7"
SECRET = "DO-NOT-PRINT-SECRET"


def pairs(uppers, rtt=0.05, base=1000.0):
    """Synthetic sample pairs whose ``host_mid - phone_epoch`` equal ``uppers``."""
    return [
        {"host_mid": base + upper, "phone_epoch": int(base), "rtt_s": rtt}
        for upper in uppers
    ]


class ParseTests(unittest.TestCase):
    def test_whole_second_stamp(self):
        self.assertEqual(clock_offset.parse_phone_epoch("1791989015\n"), 1791989015)

    def test_non_numeric_output_is_rejected(self):
        for text in ("", "  ", "Sat Oct 14 14:44:00 UTC 2026", "17.5", "-3"):
            with self.assertRaises(ValueError):
                clock_offset.parse_phone_epoch(text)


class DocumentTests(unittest.TestCase):
    def test_interval_bounds_every_sample_upper(self):
        # Whole-second phone stamps make each pairing an upper bound; the tightest
        # interval is (min(upper) - 1, min(upper)] and must contain the true offset
        # used to generate the samples (25.0 here, drawn as uppers in [25, 26)).
        doc = clock_offset.offset_document("note3", pairs([25.9, 25.2, 25.7]), now=7)
        clock_offset.assert_bounded(doc)
        self.assertEqual(doc["status"], "ok")
        self.assertEqual(doc["samples"], 3)
        self.assertLess(doc["offset_min_s"], 25.0)
        self.assertGreaterEqual(doc["offset_max_s"], 25.0)
        self.assertEqual(doc["offset_min_s"], 25.2 - clock_offset.QUANTIZATION_S)
        self.assertEqual(doc["offset_max_s"], 25.2)
        self.assertIsNone(doc["jump"])
        self.assertIsNone(doc["reason"])

    def test_nominal_is_inside_the_published_interval(self):
        # A consumer checks min <= nominal <= max to accept the reading. The median
        # of the one-sided uppers used to be published here, which is >= the upper
        # bound by construction and so could never pass that check.
        for uppers in ([25.9, 25.2, 25.7], [25.5], [30.0, 40.0, 50.0, 60.0]):
            doc = clock_offset.offset_document("note3", pairs(uppers), now=7)
            clock_offset.assert_bounded(doc)
            self.assertLessEqual(doc["offset_min_s"], doc["offset_nominal_s"], uppers)
            self.assertLessEqual(doc["offset_nominal_s"], doc["offset_max_s"], uppers)
            self.assertEqual(doc["offset_nominal_s"],
                             round(doc["offset_max_s"] - clock_offset.QUANTIZATION_S / 2, 3))

    def test_a_nominal_outside_the_interval_is_refused(self):
        doc = clock_offset.offset_document("note3", pairs([25.5]), now=7)
        with self.assertRaises(ValueError):
            clock_offset.assert_bounded(dict(doc, offset_nominal_s=doc["offset_max_s"] + 0.5))
        with self.assertRaises(ValueError):
            clock_offset.assert_bounded(dict(doc, offset_nominal_s=doc["offset_min_s"] - 0.5))
        # The guard is inclusive: a nominal exactly at either bound is still inside
        # the interval it publishes, and must not start being rejected.
        clock_offset.assert_bounded(dict(doc, offset_nominal_s=doc["offset_min_s"]))
        clock_offset.assert_bounded(dict(doc, offset_nominal_s=doc["offset_max_s"]))

    def test_single_sample_still_bounds_and_reports_rtt(self):
        doc = clock_offset.offset_document("note3", pairs([25.5], rtt=0.08), now=7)
        self.assertEqual(doc["samples"], 1)
        self.assertEqual(doc["rtt_max_s"], 0.08)
        self.assertLess(doc["offset_min_s"], 25.5)
        self.assertEqual(doc["offset_max_s"], 25.5)

    def test_unreadable_device_publishes_unavailable_without_an_offset(self):
        doc = clock_offset.offset_document("note3", None, now=7, ntp=False)
        clock_offset.assert_bounded(doc)
        self.assertEqual(doc["status"], "unavailable")
        for key in ("offset_min_s", "offset_max_s", "offset_nominal_s", "rtt_max_s"):
            self.assertIsNone(doc[key])
        self.assertEqual(doc["samples"], 0)
        self.assertTrue(doc["reason"])

    def test_shape_is_exactly_the_bounded_contract(self):
        doc = clock_offset.offset_document("note3", pairs([25.5]), now=7)
        self.assertEqual(set(doc), set(clock_offset.ALLOWED_KEYS))
        with self.assertRaises(ValueError):
            clock_offset.assert_bounded(dict(doc, extra=1))

    def test_unavailable_document_may_not_carry_an_offset(self):
        doc = clock_offset.offset_document("note3", None, now=7)
        doc["offset_nominal_s"] = 25.5
        with self.assertRaises(ValueError):
            clock_offset.assert_bounded(doc)


class JumpTests(unittest.TestCase):
    def previous(self, nominal, observed, validity=3600.0, status="ok"):
        return {"status": status, "offset_nominal_s": nominal,
                "observed_at_epoch_s": observed, "validity_seconds": validity}

    def test_step_above_threshold_within_validity_is_reported(self):
        record = clock_offset.jump_record(27.0, self.previous(25.0, 1000.0), 1100.0)
        self.assertEqual(record["delta_s"], 2.0)
        self.assertEqual(record["previous_offset_nominal_s"], 25.0)
        self.assertEqual(record["threshold_s"], clock_offset.JUMP_THRESHOLD_S)

    def test_quantization_noise_is_not_a_jump(self):
        self.assertIsNone(clock_offset.jump_record(25.9, self.previous(25.0, 1000.0), 1100.0))

    def test_expired_previous_reading_cannot_claim_a_jump(self):
        self.assertIsNone(clock_offset.jump_record(27.0, self.previous(25.0, 1000.0), 999999.0))

    def test_unavailable_or_absent_previous_is_not_a_jump(self):
        self.assertIsNone(clock_offset.jump_record(27.0, None, 1100.0))
        self.assertIsNone(clock_offset.jump_record(27.0, self.previous(25.0, 1000.0, status="unavailable"), 1100.0))
        self.assertIsNone(clock_offset.jump_record(27.0, {"status": "ok"}, 1100.0))


class PublishTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.output = Path(self.tmp.name) / "body" / "clock-domain-note3.json"

    def test_publishes_private_json_and_leaves_no_temp(self):
        clock_offset.publish(self.output, clock_offset.offset_document("note3", pairs([25.5]), now=7))
        doc = json.loads(self.output.read_text(encoding="utf-8"))
        self.assertEqual(doc["status"], "ok")
        self.assertEqual(os.stat(self.output).st_mode & 0o777, 0o600)
        leftovers = [p.name for p in self.output.parent.iterdir() if p.name != self.output.name]
        self.assertEqual(leftovers, [])

    def test_bytes_never_carry_secret_values(self):
        clock_offset.publish(self.output, clock_offset.offset_document("note3", pairs([25.5]), now=7))
        text = self.output.read_text(encoding="utf-8")
        self.assertNotIn(SECRET, text)
        self.assertNotIn("secret", text)
        self.assertNotIn("endpoint", text)

    def test_failed_write_leaves_no_temp_file(self):
        with mock.patch.object(clock_offset.os, "replace", side_effect=OSError("boom")):
            with self.assertRaises(OSError):
                clock_offset.publish(self.output, clock_offset.offset_document("note3", pairs([25.5]), now=7))
        self.assertFalse(self.output.exists())
        self.assertEqual(list(self.output.parent.iterdir()), [])

    def test_default_output_is_outside_the_consumer_state_glob(self):
        # watch.py globs body/perception/*.json for its own states and skips only
        # the "node-state-" prefix, so this document must not land there.
        output = clock_offset.default_output("/site", "note3")
        self.assertEqual(output, Path("/site/body/clock-domain-note3.json"))
        self.assertNotEqual(output.parent.name, "perception")


class SampleTests(unittest.TestCase):
    def test_pairs_phone_and_host_clock(self):
        result = mock.Mock(returncode=0, stdout="1791989015\n")
        with mock.patch.object(clock_offset.subprocess, "run", return_value=result):
            with mock.patch.object(clock_offset.time, "time", side_effect=[1000.0, 1000.1, 1000.7, 1000.8]):
                with mock.patch.object(clock_offset.time, "sleep"):
                    got = clock_offset.sample_offset(["adb"], SERIAL, 2, 0.0, 5.0)
        self.assertEqual([pair["phone_epoch"] for pair in got], [1791989015, 1791989015])
        self.assertAlmostEqual(got[0]["host_mid"], 1000.05)
        self.assertAlmostEqual(got[1]["host_mid"], 1000.75)
        self.assertAlmostEqual(got[0]["rtt_s"], 0.1, places=6)

    def test_adb_failure_raises(self):
        result = mock.Mock(returncode=1, stdout="")
        with mock.patch.object(clock_offset.subprocess, "run", return_value=result):
            with self.assertRaises(RuntimeError):
                clock_offset.sample_offset(["adb"], SERIAL, 1, 0.0, 5.0)

    def test_adb_command_wrapper_is_split(self):
        self.assertEqual(clock_offset.adb_argv("rtk proxy adb"), ["rtk", "proxy", "adb"])


class RunOnceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.site = Path(self.tmp.name)
        self.args = mock.Mock(
            site=str(self.site), serial=SERIAL, label="note3", adb="adb",
            samples=3, interval=0.0, timeout=5.0, validity=3600.0, output=None,
        )

    def test_run_once_publishes_and_prints_one_bounded_line(self):
        with mock.patch.object(clock_offset, "sample_offset", return_value=pairs([25.9, 25.2, 25.7])):
            with mock.patch.object(clock_offset, "host_ntp_synchronized", return_value=False):
                status = clock_offset.run_once(self.args)
        self.assertEqual(status, 0)
        doc = json.loads((self.site / "body" / "clock-domain-note3.json").read_text(encoding="utf-8"))
        self.assertEqual(doc["status"], "ok")
        self.assertFalse(doc["host_ntp_synchronized"])

    def test_run_once_records_an_unreadable_device_without_an_offset(self):
        with mock.patch.object(clock_offset, "sample_offset", side_effect=RuntimeError("device not attached")):
            with mock.patch.object(clock_offset, "host_ntp_synchronized", return_value=None):
                status = clock_offset.run_once(self.args)
        self.assertEqual(status, 0)
        doc = json.loads((self.site / "body" / "clock-domain-note3.json").read_text(encoding="utf-8"))
        self.assertEqual(doc["status"], "unavailable")
        self.assertIsNone(doc["offset_nominal_s"])
        self.assertIn("device not attached", doc["reason"])

    def test_run_once_flags_a_step_against_the_previous_reading(self):
        output = self.site / "body" / "clock-domain-note3.json"
        clock_offset.publish(output, clock_offset.offset_document(
            "note3", pairs([25.2]), now=time.time(), validity=3600.0))
        with mock.patch.object(clock_offset, "sample_offset", return_value=pairs([28.4])):
            with mock.patch.object(clock_offset, "host_ntp_synchronized", return_value=None):
                clock_offset.run_once(self.args)
        doc = json.loads(output.read_text(encoding="utf-8"))
        self.assertIsNotNone(doc["jump"])
        self.assertGreater(abs(doc["jump"]["delta_s"]), clock_offset.JUMP_THRESHOLD_S)


if __name__ == "__main__":
    unittest.main()
