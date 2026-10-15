#!/usr/bin/env python3
# SPDX-License-Identifier: CC0-1.0
"""Tests for the bounded spool-summary publisher (tools/spool_read.py).

The regressions that matter: the document must carry exactly the agreed bounded
shape (no extra keys, no wrong status, unavailable must not carry data, ok must
carry data), spool_document with None result must produce unavailable with null
fields, spool_document with result must produce ok with correct counts/buckets,
publish must write valid JSON atomically with 0600 perms, light bucket regex
patterns must match expected lux values, and ALLOWED_KINDS must be exactly the
allowlisted set.
"""

import json
import os
import re
import stat
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import spool_read


LABEL = "note3"
NOW = 1791989019.5


def make_result():
    """A synthetic spool read result for spool_document()."""
    return {
        "spool_bytes": 3858200,
        "retention_window_s": 23400.0,
        "oldest_row_epoch_s": 1791892800.0,
        "newest_row_epoch_s": 1791916200.0,
        "counts": {
            "light": 4964,
            "battery": 12,
            "acceleration": 8320,
            "ble_status": 3,
            "wifi_link_rssi": 15,
            "spool": 1,
            "cap": 2,
            "hello": 1,
            "android": 1,
            "owner_checkboxes": 1,
            "probe": 5,
            "ble_scan": 42,
            "action": 7,
        },
        "light_buckets": {
            "dark_exact": 1386,
            "dim_0_9": 4982,
            "moderate_10_99": 549,
            "bright_100_999": 180,
            "very_bright_1000_plus": 0,
        },
        "overflow": {"dropped": 108040, "notice_epoch_s": 1792050926},
        "scan_state": {
            "epoch_s": 1792061943, "windows": 23, "phase": "gap",
            "last_error": "none", "sightings": 0,
            "window_ms": 60000, "gap_ms": 60000,
        },
    }


class AssertBoundedTests(unittest.TestCase):
    """assert_bounded must reject every deviation from the bounded shape."""

    def _valid_doc(self):
        doc = spool_read.spool_document(LABEL, make_result(), NOW)
        return doc

    def test_accepts_valid_ok_document(self):
        doc = self._valid_doc()
        spool_read.assert_bounded(doc)  # must not raise

    def test_accepts_valid_unavailable_document(self):
        doc = spool_read.spool_document(LABEL, None, NOW)
        spool_read.assert_bounded(doc)  # must not raise

    def test_rejects_extra_keys(self):
        doc = self._valid_doc()
        doc["unexpected"] = "value"
        with self.assertRaises(ValueError):
            spool_read.assert_bounded(doc)

    def test_rejects_missing_keys(self):
        doc = self._valid_doc()
        del doc["counts"]
        with self.assertRaises(ValueError):
            spool_read.assert_bounded(doc)

    def test_rejects_wrong_status(self):
        doc = self._valid_doc()
        doc["status"] = "calm"
        with self.assertRaises(ValueError):
            spool_read.assert_bounded(doc)

    def test_rejects_unavailable_carrying_spool_bytes(self):
        doc = spool_read.spool_document(LABEL, None, NOW)
        doc["spool_bytes"] = 12345
        with self.assertRaises(ValueError):
            spool_read.assert_bounded(doc)

    def test_rejects_unavailable_carrying_counts(self):
        doc = spool_read.spool_document(LABEL, None, NOW)
        doc["counts"] = {"light": 1}
        with self.assertRaises(ValueError):
            spool_read.assert_bounded(doc)

    def test_rejects_unavailable_carrying_light_buckets(self):
        doc = spool_read.spool_document(LABEL, None, NOW)
        doc["light_buckets"] = {"dark_exact": 0}
        with self.assertRaises(ValueError):
            spool_read.assert_bounded(doc)

    def test_rejects_unavailable_carrying_retention_window(self):
        doc = spool_read.spool_document(LABEL, None, NOW)
        doc["retention_window_s"] = 100.0
        with self.assertRaises(ValueError):
            spool_read.assert_bounded(doc)

    def test_rejects_unavailable_carrying_oldest_row(self):
        doc = spool_read.spool_document(LABEL, None, NOW)
        doc["oldest_row_epoch_s"] = 1000.0
        with self.assertRaises(ValueError):
            spool_read.assert_bounded(doc)

    def test_rejects_unavailable_carrying_newest_row(self):
        doc = spool_read.spool_document(LABEL, None, NOW)
        doc["newest_row_epoch_s"] = 2000.0
        with self.assertRaises(ValueError):
            spool_read.assert_bounded(doc)

    def test_rejects_ok_missing_spool_bytes(self):
        doc = self._valid_doc()
        doc["spool_bytes"] = None
        with self.assertRaises(ValueError):
            spool_read.assert_bounded(doc)

    def test_rejects_ok_zero_spool_bytes(self):
        doc = self._valid_doc()
        doc["spool_bytes"] = 0
        with self.assertRaises(ValueError):
            spool_read.assert_bounded(doc)

    def test_rejects_ok_missing_counts(self):
        doc = self._valid_doc()
        doc["counts"] = None
        with self.assertRaises(ValueError):
            spool_read.assert_bounded(doc)

    def test_rejects_ok_missing_light_buckets(self):
        doc = self._valid_doc()
        doc["light_buckets"] = None
        with self.assertRaises(ValueError):
            spool_read.assert_bounded(doc)

    def test_rejects_unavailable_carrying_overflow(self):
        doc = spool_read.spool_document(LABEL, None, NOW)
        doc["overflow"] = {"dropped": 5, "notice_epoch_s": 1792048648}
        with self.assertRaises(ValueError):
            spool_read.assert_bounded(doc)

    def test_rejects_ok_missing_overflow(self):
        doc = self._valid_doc()
        doc["overflow"] = None
        with self.assertRaises(ValueError):
            spool_read.assert_bounded(doc)

    def test_rejects_ok_negative_dropped(self):
        doc = self._valid_doc()
        doc["overflow"] = {"dropped": -1, "notice_epoch_s": None}
        with self.assertRaises(ValueError):
            spool_read.assert_bounded(doc)

    def test_rejects_ok_dropped_without_a_notice_epoch(self):
        doc = self._valid_doc()
        doc["overflow"] = {"dropped": 5, "notice_epoch_s": None}
        with self.assertRaises(ValueError):
            spool_read.assert_bounded(doc)

    def test_rejects_ok_notice_epoch_without_dropped(self):
        doc = self._valid_doc()
        doc["overflow"] = {"dropped": 0, "notice_epoch_s": 1792048648}
        with self.assertRaises(ValueError):
            spool_read.assert_bounded(doc)

    def test_rejects_reason_too_long(self):
        doc = self._valid_doc()
        doc["reason"] = "x" * (spool_read.MAX_REASON_CHARS + 1)
        with self.assertRaises(ValueError):
            spool_read.assert_bounded(doc)

    def test_accepts_reason_at_max_length(self):
        doc = self._valid_doc()
        doc["reason"] = "x" * spool_read.MAX_REASON_CHARS
        spool_read.assert_bounded(doc)  # must not raise

    def test_accepts_null_scan_state(self):
        doc = self._valid_doc()
        doc["scan_state"] = None
        spool_read.assert_bounded(doc)  # no retained scan-state row is valid

    def test_accepts_scan_state_with_a_spaced_failure_reason(self):
        doc = self._valid_doc()
        doc["scan_state"]["last_error"] = "scan_failed code=2"
        doc["scan_state"]["phase"] = "none"
        spool_read.assert_bounded(doc)  # must not raise

    def test_rejects_scan_state_with_an_unknown_phase(self):
        doc = self._valid_doc()
        doc["scan_state"]["phase"] = "scanning"
        with self.assertRaises(ValueError):
            spool_read.assert_bounded(doc)

    def test_rejects_scan_state_with_an_extra_field(self):
        doc = self._valid_doc()
        doc["scan_state"]["beacon"] = "MISHE-BEACON"
        with self.assertRaises(ValueError):
            spool_read.assert_bounded(doc)

    def test_rejects_scan_state_with_a_negative_counter(self):
        doc = self._valid_doc()
        doc["scan_state"]["sightings"] = -1
        with self.assertRaises(ValueError):
            spool_read.assert_bounded(doc)

    def test_rejects_scan_state_with_a_boolean_counter(self):
        doc = self._valid_doc()
        doc["scan_state"]["windows"] = True
        with self.assertRaises(ValueError):
            spool_read.assert_bounded(doc)

    def test_rejects_scan_state_with_an_implausible_epoch(self):
        doc = self._valid_doc()
        doc["scan_state"]["epoch_s"] = 42
        with self.assertRaises(ValueError):
            spool_read.assert_bounded(doc)

    def test_rejects_scan_state_with_an_overlong_last_error(self):
        doc = self._valid_doc()
        doc["scan_state"]["last_error"] = "x" * (spool_read.MAX_LAST_ERROR_CHARS + 1)
        with self.assertRaises(ValueError):
            spool_read.assert_bounded(doc)

    def test_rejects_unavailable_carrying_scan_state(self):
        doc = spool_read.spool_document(LABEL, None, NOW)
        doc["scan_state"] = {"epoch_s": 1792061943, "windows": 1, "phase": "gap",
                             "last_error": "none", "sightings": 0,
                             "window_ms": 60000, "gap_ms": 60000}
        with self.assertRaises(ValueError):
            spool_read.assert_bounded(doc)


class SpoolDocumentNoneTests(unittest.TestCase):
    """spool_document with None result produces unavailable with null fields."""

    def test_status_is_unavailable(self):
        doc = spool_read.spool_document(LABEL, None, NOW)
        self.assertEqual(doc["status"], "unavailable")

    def test_null_data_fields(self):
        doc = spool_read.spool_document(LABEL, None, NOW)
        self.assertIsNone(doc["spool_bytes"])
        self.assertIsNone(doc["retention_window_s"])
        self.assertIsNone(doc["oldest_row_epoch_s"])
        self.assertIsNone(doc["newest_row_epoch_s"])
        self.assertIsNone(doc["counts"])
        self.assertIsNone(doc["light_buckets"])
        self.assertIsNone(doc["overflow"])
        self.assertIsNone(doc["scan_state"])

    def test_reason_is_populated(self):
        doc = spool_read.spool_document(LABEL, None, NOW)
        self.assertIsInstance(doc["reason"], str)
        self.assertTrue(doc["reason"])

    def test_metadata_fields_present(self):
        doc = spool_read.spool_document(LABEL, None, NOW)
        self.assertEqual(doc["node"], LABEL)
        self.assertEqual(doc["source"], spool_read.SOURCE)
        self.assertEqual(doc["method"], spool_read.METHOD)
        self.assertEqual(doc["observed_at_epoch_s"], NOW)
        self.assertEqual(doc["validity_seconds"], 300.0)

    def test_document_is_bounded(self):
        doc = spool_read.spool_document(LABEL, None, NOW)
        spool_read.assert_bounded(doc)  # must not raise


class SpoolDocumentResultTests(unittest.TestCase):
    """spool_document with result produces ok with correct counts/buckets."""

    def test_status_is_ok(self):
        doc = spool_read.spool_document(LABEL, make_result(), NOW)
        self.assertEqual(doc["status"], "ok")

    def test_counts_match_result(self):
        result = make_result()
        doc = spool_read.spool_document(LABEL, result, NOW)
        self.assertEqual(doc["counts"], result["counts"])

    def test_light_buckets_match_result(self):
        result = make_result()
        doc = spool_read.spool_document(LABEL, result, NOW)
        self.assertEqual(doc["light_buckets"], result["light_buckets"])

    def test_overflow_matches_result(self):
        result = make_result()
        doc = spool_read.spool_document(LABEL, result, NOW)
        self.assertEqual(doc["overflow"], result["overflow"])

    def test_scan_state_matches_result(self):
        result = make_result()
        doc = spool_read.spool_document(LABEL, result, NOW)
        self.assertEqual(doc["scan_state"], result["scan_state"])

    def test_no_retained_scan_state_row_is_published_as_null(self):
        result = make_result()
        result["scan_state"] = None
        doc = spool_read.spool_document(LABEL, result, NOW)
        spool_read.assert_bounded(doc)  # must not raise
        self.assertIsNone(doc["scan_state"])

    def test_truthful_zero_overflow_is_published(self):
        result = make_result()
        result["overflow"] = {"dropped": 0, "notice_epoch_s": None}
        doc = spool_read.spool_document(LABEL, result, NOW)
        spool_read.assert_bounded(doc)  # a never-evicted spool is valid
        self.assertEqual(doc["overflow"], {"dropped": 0, "notice_epoch_s": None})

    def test_spool_bytes_match_result(self):
        result = make_result()
        doc = spool_read.spool_document(LABEL, result, NOW)
        self.assertEqual(doc["spool_bytes"], result["spool_bytes"])

    def test_retention_window_rounded(self):
        result = make_result()
        result["retention_window_s"] = 100.12
        doc = spool_read.spool_document(LABEL, result, NOW)
        self.assertEqual(doc["retention_window_s"], 100.1)

    def test_oldest_row_rounded(self):
        result = make_result()
        result["oldest_row_epoch_s"] = 1791892800.04
        doc = spool_read.spool_document(LABEL, result, NOW)
        self.assertEqual(doc["oldest_row_epoch_s"], 1791892800.0)

    def test_newest_row_rounded(self):
        result = make_result()
        result["newest_row_epoch_s"] = 1791916200.06
        doc = spool_read.spool_document(LABEL, result, NOW)
        self.assertEqual(doc["newest_row_epoch_s"], 1791916200.1)

    def test_reason_is_none(self):
        doc = spool_read.spool_document(LABEL, make_result(), NOW)
        self.assertIsNone(doc["reason"])

    def test_metadata_fields_present(self):
        doc = spool_read.spool_document(LABEL, make_result(), NOW)
        self.assertEqual(doc["node"], LABEL)
        self.assertEqual(doc["source"], spool_read.SOURCE)
        self.assertEqual(doc["method"], spool_read.METHOD)
        self.assertEqual(doc["observed_at_epoch_s"], NOW)
        self.assertEqual(doc["validity_seconds"], 300.0)

    def test_document_is_bounded(self):
        doc = spool_read.spool_document(LABEL, make_result(), NOW)
        spool_read.assert_bounded(doc)  # must not raise

    def test_custom_validity(self):
        doc = spool_read.spool_document(LABEL, make_result(), NOW, validity=60.0)
        self.assertEqual(doc["validity_seconds"], 60.0)


class PublishTests(unittest.TestCase):
    """publish writes valid JSON atomically with 0600 perms."""

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.output = Path(self.tmpdir.name) / "spool-summary.json"

    def tearDown(self):
        self.tmpdir.cleanup()

    def test_writes_valid_json(self):
        doc = spool_read.spool_document(LABEL, make_result(), NOW)
        spool_read.publish(self.output, doc)
        text = self.output.read_text(encoding="utf-8")
        parsed = json.loads(text)
        self.assertEqual(parsed["status"], "ok")
        self.assertEqual(parsed["node"], LABEL)

    def test_creates_parent_directories(self):
        doc = spool_read.spool_document(LABEL, make_result(), NOW)
        nested = self.output.parent / "body" / "nested"
        spool_read.publish(nested, doc)
        self.assertTrue(nested.exists())

    def test_file_permissions_0600(self):
        doc = spool_read.spool_document(LABEL, make_result(), NOW)
        spool_read.publish(self.output, doc)
        mode = stat.S_IMODE(self.output.stat().st_mode)
        self.assertEqual(mode, 0o600)

    def test_no_temp_file_left_behind(self):
        doc = spool_read.spool_document(LABEL, make_result(), NOW)
        spool_read.publish(self.output, doc)
        leftovers = list(self.output.parent.glob("*.tmp*"))
        self.assertEqual(leftovers, [])

    def test_overwrites_existing_file(self):
        doc1 = spool_read.spool_document(LABEL, make_result(), NOW)
        spool_read.publish(self.output, doc1)
        doc2 = spool_read.spool_document(LABEL, None, NOW)
        spool_read.publish(self.output, doc2)
        parsed = json.loads(self.output.read_text(encoding="utf-8"))
        self.assertEqual(parsed["status"], "unavailable")

    def test_rejects_unbounded_document(self):
        doc = spool_read.spool_document(LABEL, make_result(), NOW)
        doc["extra"] = "key"
        with self.assertRaises(ValueError):
            spool_read.publish(self.output, doc)
        self.assertFalse(self.output.exists())


class LightBucketRegexTests(unittest.TestCase):
    """Light bucket patterns classify every lux string the app can emit.

    ``_matches`` searches a canonical spool light row, so the value/field
    boundary the device grep sees (``lux=<v> accuracy=<a>``) is part of every
    assertion. The patterns are ERE and the device command passes ``-E``.
    """

    ROW = "1792095553 light {value} accuracy=3 age_ms=12 sensor_time_ns=1"

    #: (emitted value string, correct bucket) over the Java ``Float.toString``
    #: shapes the app can emit: fixed notation for 1e-3 <= x < 1e7, scientific
    #: notation below 1e-3 and at or above 1e7, and ``0.0`` for exact zero.
    #: Sensors.java rejects ``!finite`` and ``< 0`` samples, so every emitted
    #: value is a finite non-negative float.
    SHAPES = (
        ("lux=0.0", "dark_exact"),
        ("lux=1.0E-45", "faint_0_1"),
        ("lux=1.0E-4", "faint_0_1"),
        ("lux=5.0E-4", "faint_0_1"),
        ("lux=9.999999E-4", "faint_0_1"),
        ("lux=0.001", "faint_0_1"),
        ("lux=0.05", "faint_0_1"),
        ("lux=0.099", "faint_0_1"),
        ("lux=0.5", "faint_0_1"),
        ("lux=0.505", "faint_0_1"),
        ("lux=0.999", "faint_0_1"),
        ("lux=1.0", "dim_0_9"),
        ("lux=1.251", "dim_0_9"),
        ("lux=2.505", "dim_0_9"),
        ("lux=5.5", "dim_0_9"),
        ("lux=5.9506", "dim_0_9"),
        ("lux=9.9", "dim_0_9"),
        ("lux=10.0", "moderate_10_99"),
        ("lux=42.3", "moderate_10_99"),
        ("lux=99.9", "moderate_10_99"),
        ("lux=100.0", "bright_100_999"),
        ("lux=250.7", "bright_100_999"),
        ("lux=999.9", "bright_100_999"),
        ("lux=1000.0", "very_bright_1000_plus"),
        ("lux=12345.6", "very_bright_1000_plus"),
        ("lux=9999999.0", "very_bright_1000_plus"),
        ("lux=1.0E7", "very_bright_1000_plus"),
        ("lux=1.2E7", "very_bright_1000_plus"),
        ("lux=3.4028235E38", "very_bright_1000_plus"),
    )

    def _matches(self, value):
        """Bucket names whose pattern matches a real row carrying ``value``."""
        row = self.ROW.format(value=value)
        return [name for name, ere in spool_read.LIGHT_BUCKETS
                if re.compile(ere).search(row)]

    def _match_bucket(self, value):
        matches = self._matches(value)
        return matches[0] if matches else None

    def test_every_lux_shape_lands_in_its_magnitude_bucket(self):
        """Assert the bucket, not just the count: the old patterns put
        ``lux=0.05``/``lux=0.099`` in dark_exact and the scientific shapes
        (``lux=1.0E-4``, ``lux=1.2E7``) in dim_0_9 (discover 91782)."""
        for value, expected in self.SHAPES:
            self.assertEqual(self._match_bucket(value), expected, value)

    def test_buckets_partition_every_lux_shape(self):
        """Each lux string shape the app can emit matches exactly one
        bucket: the buckets are disjoint and exhaustive over finite
        non-negative Java float strings (``"lux=" + float``), so their
        counts sum to the ``lux=`` row count."""
        for value, _ in self.SHAPES:
            self.assertEqual(len(self._matches(value)), 1, value)

    def test_bucket_patterns_use_device_supported_ere(self):
        """The device grep is invoked with ``-E``, so the patterns must be ERE.

        This device's toybox grep does not implement BRE alternation ``\\|``
        and counts zero rows for it (probed on the live Note3 spool
        2026-10-15: ``lux=\\(0\\.0\\|5\\.9506\\)`` -> 0 rows,
        ``-E 'lux=(0\\.0|5\\.9506) '`` -> 2961 rows), so a BRE-only construct
        here would silently zero a bucket. In ERE ``{m,}`` is an unescaped
        interval; an escaped ``\\{`` would be a literal brace.
        """
        for name, ere in spool_read.LIGHT_BUCKETS:
            for bre_only in (r"\|", r"\{", r"\}", r"\+", r"\?"):
                self.assertNotIn(bre_only, ere, name)
            re.compile(ere)

    def test_bucket_patterns_are_sent_to_grep_with_dash_e(self):
        """The patterns use ERE alternation, so the device command must pass
        ``-E``; without it toybox grep reads ``|`` literally and the bucket
        silently counts zero."""
        pattern = dict(spool_read.LIGHT_BUCKETS)["faint_0_1"]
        with mock.patch.object(spool_read, "_run", return_value="7\n") as run:
            spool_read._count_light_bucket(["adb"], "S", "PATH", pattern, 5.0)
        self.assertIn("-E", run.call_args[0][2].split())

    def test_bucket_names_are_exactly_expected(self):
        names = [name for name, _ in spool_read.LIGHT_BUCKETS]
        self.assertEqual(names, [
            "dark_exact", "faint_0_1", "dim_0_9", "moderate_10_99",
            "bright_100_999", "very_bright_1000_plus",
        ])




class ScanStateRowTests(unittest.TestCase):
    """_scan_state_row extracts the latest ble_scan_state row's bounded fields."""

    ROW = ("1792061943 ble_scan_state windows=23 phase=gap last_error=none "
           "sightings=0 window_ms=60000 gap_ms=60000")

    def _run_output(self, rows, status="0"):
        body = "".join(row + "\n" for row in rows)
        return body + f"{spool_read.SCAN_STATE_PROBE_MARKER}{status}\n"

    def test_command_uses_bounded_grep_and_probe(self):
        with mock.patch.object(
                spool_read, "_run",
                return_value=self._run_output([self.ROW])) as run:
            spool_read._scan_state_row(["adb"], "S", "PATH", 5.0)
        command = run.call_args[0][2]
        self.assertIn("grep -a -o", command)
        self.assertIn(spool_read.SCAN_STATE_ROW_BRE, command)
        self.assertIn(spool_read.SCAN_STATE_PROBE_MARKER, command)
        self.assertIn("2>&1", command)

    def test_parses_last_row_as_current_state(self):
        rows = [
            "1792061000 ble_scan_state windows=1 phase=window last_error=none "
            "sightings=0 window_ms=60000 gap_ms=60000",
            "1792061943 ble_scan_state windows=23 phase=gap last_error=none "
            "sightings=4 window_ms=60000 gap_ms=60000",
        ]
        with mock.patch.object(spool_read, "_run",
                               return_value=self._run_output(rows)):
            row = spool_read._scan_state_row(["adb"], "S", "PATH", 5.0)
        self.assertEqual(row, {
            "epoch_s": 1792061943, "windows": 23, "phase": "gap",
            "last_error": "none", "sightings": 4,
            "window_ms": 60000, "gap_ms": 60000,
        })

    def test_parses_spaced_failure_reason(self):
        rows = ["1792061943 ble_scan_state windows=28 phase=none "
                "last_error=scan_failed code=2 sightings=0 "
                "window_ms=60000 gap_ms=60000"]
        with mock.patch.object(spool_read, "_run",
                               return_value=self._run_output(rows)):
            row = spool_read._scan_state_row(["adb"], "S", "PATH", 5.0)
        self.assertEqual(row["last_error"], "scan_failed code=2")
        self.assertEqual(row["windows"], 28)

    def test_no_match_is_none_not_zero(self):
        with mock.patch.object(spool_read, "_run",
                               return_value=self._run_output([], status="1")):
            self.assertIsNone(spool_read._scan_state_row(["adb"], "S", "PATH", 5.0))

    def test_no_match_with_output_is_a_broken_read(self):
        with mock.patch.object(
                spool_read, "_run",
                return_value=self._run_output([self.ROW], status="1")):
            with self.assertRaises(RuntimeError):
                spool_read._scan_state_row(["adb"], "S", "PATH", 5.0)

    def test_device_diagnostic_fails_the_read(self):
        out = ("run-as: package not debuggable\n"
               + f"{spool_read.SCAN_STATE_PROBE_MARKER}0\n")
        with mock.patch.object(spool_read, "_run", return_value=out):
            with self.assertRaises(RuntimeError):
                spool_read._scan_state_row(["adb"], "S", "PATH", 5.0)

    def test_nonzero_non_match_status_fails_the_read(self):
        with mock.patch.object(spool_read, "_run",
                               return_value=self._run_output([], status="2")):
            with self.assertRaises(RuntimeError):
                spool_read._scan_state_row(["adb"], "S", "PATH", 5.0)

    def test_missing_probe_line_fails_the_read(self):
        with mock.patch.object(spool_read, "_run", return_value="garbage\n"):
            with self.assertRaises(RuntimeError):
                spool_read._scan_state_row(["adb"], "S", "PATH", 5.0)

    def test_parse_failure_is_a_broken_read(self):
        out = ("1792061943 ble_scan_state windows=x phase=gap last_error=none "
               "sightings=0 window_ms=60000 gap_ms=60000\n"
               + f"{spool_read.SCAN_STATE_PROBE_MARKER}0\n")
        with mock.patch.object(spool_read, "_run", return_value=out):
            with self.assertRaises(RuntimeError):
                spool_read._scan_state_row(["adb"], "S", "PATH", 5.0)


class CountKindTests(unittest.TestCase):
    """_count_kind counts rows of exactly one kind via epoch + kind match."""

    def test_command_matches_row_epoch_and_kind(self):
        with mock.patch.object(spool_read, "_run", return_value="7") as run:
            result = spool_read._count_kind(["adb"], "S", "PATH", "light", 5.0)
        command = run.call_args[0][2]
        self.assertIn(f"'{spool_read.ROW_EPOCH_BRE} light'", command)
        self.assertIn("grep -a -c", command)

    def test_ble_scan_pattern_excludes_scan_state_rows(self):
        # ble_scan is a prefix of ble_scan_state; without the trailing-space
        # anchor the lifecycle count would include the per-cycle state rows.
        with mock.patch.object(spool_read, "_run", return_value="7") as run:
            spool_read._count_kind(["adb"], "S", "PATH", "ble_scan", 5.0)
        command = run.call_args[0][2]
        self.assertIn(f"'{spool_read.ROW_EPOCH_BRE} ble_scan '", command)
        self.assertNotIn(f"'{spool_read.ROW_EPOCH_BRE} ble_scan'", command)

    def test_scan_state_pattern_counts_only_itself(self):
        with mock.patch.object(spool_read, "_run", return_value="7") as run:
            spool_read._count_kind(["adb"], "S", "PATH", "ble_scan_state", 5.0)
        command = run.call_args[0][2]
        self.assertIn(f"'{spool_read.ROW_EPOCH_BRE} ble_scan_state'", command)
        self.assertNotIn("ble_scan '", command)

    def test_unparseable_output_raises(self):
        with mock.patch.object(spool_read, "_run", return_value="not-a-count"):
            with self.assertRaises(RuntimeError):
                spool_read._count_kind(["adb"], "S", "PATH", "light", 5.0)


class AllowedKindsTests(unittest.TestCase):
    """ALLOWED_KINDS is exactly the allowlisted set."""

    EXPECTED = frozenset({
        "battery", "light", "acceleration", "ble_status", "wifi_link_rssi",
        "spool", "cap", "hello", "android", "owner_checkboxes", "probe",
        "ble_scan", "ble_scan_state", "ble_sighting", "action",
    })

    def test_exact_set(self):
        self.assertEqual(spool_read.ALLOWED_KINDS, self.EXPECTED)

    def test_no_extra_kinds(self):
        extra = spool_read.ALLOWED_KINDS - self.EXPECTED
        self.assertEqual(extra, frozenset())

    def test_no_missing_kinds(self):
        missing = self.EXPECTED - spool_read.ALLOWED_KINDS
        self.assertEqual(missing, frozenset())

    def test_kind_count(self):
        self.assertEqual(len(spool_read.ALLOWED_KINDS), 15)


class RetentionWindowTests(unittest.TestCase):
    """_retention_window reads row epochs, not same-shaped field values.

    Defect (senses, 2026-10-15): a bare ``[0-9]\\{10\\}`` match took the leading
    ten digits of any field value. On a freshly booted phone
    ``sensor_time_ns=<10 digits>`` landed inside the accepted epoch range and
    published a 6.4-year window (56,254.1 h) where the rows span ~5.7 h.
    """

    #: Real ``grep -a -o`` output shape, CRLF included: one candidate per row
    #: plus field values that a key name follows.
    MATCHES = (
        "1792028662 light\r\n"
        "1792028662 phone_elapsed_ms\r\n"
        "1791958404 wifi_link_rssi_dbm\r\n"
        "1994543295 phone_elapsed_ms\r\n"
        "0000646651 phone_elapsed_ms\r\n"
        "1792049063 spool\r\n"
    )

    def test_command_uses_the_epoch_token_pattern(self):
        with mock.patch.object(spool_read, "_run", return_value="") as run:
            with self.assertRaises(RuntimeError):
                spool_read._retention_window(["adb"], "S", "PATH", 5.0)
        command = run.call_args[0][2]
        self.assertIn(f"'{spool_read.ROW_EPOCH_TOKEN_BRE}'", command)
        self.assertIn("grep -a -o", command)

    def test_field_values_do_not_set_the_window(self):
        with mock.patch.object(spool_read, "_run", return_value=self.MATCHES):
            oldest, newest, window = spool_read._retention_window(
                ["adb"], "S", "PATH", 5.0)
        self.assertEqual(oldest, 1791958404)
        self.assertEqual(newest, 1792049063)
        self.assertEqual(window, 90659)

    def test_field_values_alone_are_unavailable(self):
        matches = "1994543295 phone_elapsed_ms\r\n0000646651 phone_elapsed_ms\r\n"
        with mock.patch.object(spool_read, "_run", return_value=matches):
            with self.assertRaises(RuntimeError) as caught:
                spool_read._retention_window(["adb"], "S", "PATH", 5.0)
        self.assertIn("no row epoch matched the kind anchor", str(caught.exception))

    def test_implausible_window_is_unavailable(self):
        matches = "1792028662 light\r\n1794707062 light\r\n"
        with mock.patch.object(spool_read, "_run", return_value=matches):
            with self.assertRaises(RuntimeError) as caught:
                spool_read._retention_window(["adb"], "S", "PATH", 5.0)
        self.assertIn("implausible retention window", str(caught.exception))

    def test_row_epochs_keeps_only_kind_tokens_in_epoch_range(self):
        text = ("1792028662 light\r\n1792028662 phone_elapsed_ms\r\n"
                "9999894006 light\r\n123 light\r\nnotanumber light\r\n")
        self.assertEqual(spool_read._row_epochs(text), [1792028662])


class RowKindTokensTests(unittest.TestCase):
    """Every token the app writes after a row epoch is a row token.

    The damaging failure is a row epoch silently dropped from the retention
    span, so the direction that matters is app row tokens -> ROW_KIND_TOKENS.
    A field key can also satisfy the ``<10 digits> <token>`` shape: the
    ``owner_checkboxes`` row carries ``battery=``/``light=``/``acceleration=``
    keys and all three are row tokens, so the guard must rest on the value
    shape -- those keys only ever carry ``on``/``off`` (BodyService.onOff), so
    no 10-digit value precedes them.
    """

    #: Row-leading tokens the app writes, traced in app/src/main/java: hello
    #: and android (BodyService session start), cap/owner/sensor
    #: (Sensors.capabilities), actuator (BodyService vibrator line),
    #: owner_checkboxes and probe, action, the BLE kinds, the sensor kinds,
    #: the Wi-Fi row token, and the spool overflow notice.
    APP_ROW_TOKENS = frozenset({
        "hello", "android", "cap", "owner", "sensor", "actuator",
        "owner_checkboxes", "probe", "action", "ble_scan", "ble_scan_state",
        "ble_sighting", "ble_status", "battery", "light", "acceleration",
        "wifi_link_rssi_dbm", "spool",
    })

    def test_every_app_row_token_is_accepted(self):
        self.assertEqual(
            self.APP_ROW_TOKENS - spool_read.ROW_KIND_TOKENS, frozenset())

    def test_shape_guard_accepts_a_row_token_used_as_a_key(self):
        """The guard is the value shape, not key exclusion, so a 10-digit value
        followed by ``battery``/``light``/``acceleration`` is accepted even
        where they are keys. No producer emits a 10-digit value before those
        keys (the ``owner_checkboxes`` row carries ``on``/``off``), so the
        exposure is bounded and recorded here rather than denied."""
        self.assertEqual(spool_read._row_epochs("1792028662 battery\r\n"),
                         [1792028662])

    def test_non_kind_field_keys_are_not_row_tokens(self):
        for key in ("phone_elapsed_ms", "observed_at", "sensor_time_ns",
                    "spool_bytes", "lux"):
            self.assertNotIn(key, spool_read.ROW_KIND_TOKENS)


class OverflowNoticeTests(unittest.TestCase):
    """The eviction count is the LAST notice, never a count or a sum.

    The app appends ``<epoch> spool overflow dropped=N policy=oldest`` per
    eviction batch with ``N`` cumulative, and never trims notices
    (ObservationSpool.overflowText/trim), so the file keeps every notice ever
    written: 1,451 of them on Note3 2026-10-15 for the one live count. Summing
    them reports ~100x the real loss, and counting them reports the number of
    batches as if it were the number of lost rows.
    """

    #: Real ``grep -a -o`` output shape, CRLF included, oldest first.
    NOTICES = ("1792048648 spool overflow dropped=106097\r\n"
               "1792049129 spool overflow dropped=108030\r\n"
               "1792050926 spool overflow dropped=108040\r\n")

    def _probe(self, status):
        return f"{spool_read.OVERFLOW_PROBE_MARKER}{status}\r\n"

    def test_command_anchors_the_epoch_and_reads_the_device_status(self):
        with mock.patch.object(spool_read, "_run",
                               return_value=self._probe("1")) as run:
            spool_read._overflow_notice(["adb"], "S", "PATH", 5.0)
        command = run.call_args[0][2]
        self.assertIn("grep -a -o", command)
        self.assertIn(f"'{spool_read.OVERFLOW_NOTICE_BRE}'", command)
        # The status must be expanded by the device shell, so ``$?`` sits
        # outside the single quotes: inside them the probe echoes "$?" and
        # every read fails as an unparsable status (found on-device).
        self.assertIn(f"echo '{spool_read.OVERFLOW_PROBE_MARKER}'$?", command)
        # stderr is merged so a device-side diagnostic is visible on the same
        # channel as the matches.
        self.assertIn("2>&1", command)

    def test_last_notice_wins_over_sum_and_max(self):
        with mock.patch.object(spool_read, "_run",
                               return_value=self.NOTICES + self._probe("0")):
            dropped, epoch = spool_read._overflow_notice(["adb"], "S", "PATH", 5.0)
        self.assertEqual(dropped, 108040)
        self.assertEqual(epoch, 1792050926)
        self.assertNotEqual(dropped, 106097 + 108030 + 108040)

    def test_no_notice_is_a_truthful_zero(self):
        with mock.patch.object(spool_read, "_run",
                               return_value=self._probe("1")):
            self.assertEqual(
                spool_read._overflow_notice(["adb"], "S", "PATH", 5.0), (0, None))

    def test_a_broken_read_is_not_a_calm_zero(self):
        # A channel that died before the shell reached the echo: no probe line
        # at all. (A denied run-as is a different mode -- it exits 1 *with* the
        # probe line, so it is caught by the merged-diagnostic check below, not
        # here.) Publishing 0 on either would read as "nothing evicted".
        with mock.patch.object(spool_read, "_run",
                               return_value="run-as: permission denied\r\n"):
            with self.assertRaises(RuntimeError):
                spool_read._overflow_notice(["adb"], "S", "PATH", 5.0)

    def test_a_device_diagnostic_with_no_match_status_is_not_a_zero(self):
        """Measured on Note3 2026-10-15: a denied run-as or an unreadable path
        exits 1 -- the same device status as "grep matched nothing" -- and
        prints only a diagnostic. Reading that as zero would publish a calm
        "nothing evicted" over a broken channel."""
        for diagnostic in ("run-as: Package 'org.androidbody' is unknown",
                           "grep: files/observations/x.spool: Permission denied"):
            with mock.patch.object(spool_read, "_run",
                                   return_value=diagnostic + "\r\n" + self._probe("1")):
                with self.assertRaises(RuntimeError):
                    spool_read._overflow_notice(["adb"], "S", "PATH", 5.0)

    def test_a_diagnostic_after_a_match_fails_the_read(self):
        with mock.patch.object(spool_read, "_run",
                               return_value=self.NOTICES
                               + "grep: write error\r\n" + self._probe("0")):
            with self.assertRaises(RuntimeError):
                spool_read._overflow_notice(["adb"], "S", "PATH", 5.0)

    def test_an_unexpected_device_status_fails_the_read(self):
        with mock.patch.object(spool_read, "_run",
                               return_value=self._probe("127")):
            with self.assertRaises(RuntimeError):
                spool_read._overflow_notice(["adb"], "S", "PATH", 5.0)

    def test_match_status_without_a_parsable_notice_fails_the_read(self):
        with mock.patch.object(spool_read, "_run",
                               return_value="108040 spool overflow dropped=108040\r\n"
                                            + self._probe("0")):
            with self.assertRaises(RuntimeError):
                spool_read._overflow_notice(["adb"], "S", "PATH", 5.0)

    def test_pattern_needs_the_row_leading_ten_digit_epoch(self):
        # A bare ``dropped=`` field or a short number must not be read as a
        # notice: the epoch anchor is what makes the value a row timestamp.
        self.assertIsNone(spool_read.OVERFLOW_NOTICE_RE.fullmatch(
            "108040 spool overflow dropped=108040"))
        self.assertIsNone(spool_read.OVERFLOW_NOTICE_RE.fullmatch(
            "spool overflow dropped=108040"))


if __name__ == "__main__":
    unittest.main()
