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

    def test_rejects_reason_too_long(self):
        doc = self._valid_doc()
        doc["reason"] = "x" * (spool_read.MAX_REASON_CHARS + 1)
        with self.assertRaises(ValueError):
            spool_read.assert_bounded(doc)

    def test_accepts_reason_at_max_length(self):
        doc = self._valid_doc()
        doc["reason"] = "x" * spool_read.MAX_REASON_CHARS
        spool_read.assert_bounded(doc)  # must not raise


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
    """Light bucket regex patterns match expected lux values."""

    def _match_bucket(self, lux_str):
        """Return the first bucket name whose device-BRE pattern matches lux_str.

        The device runs toybox grep (BRE), where ``\\{``/``\\}`` are interval
        delimiters; Python re reads the same source as literal braces. The
        bridge strips the backslashes, so the checked string is the exact
        pattern the device receives.
        """
        for name, bre in spool_read.LIGHT_BUCKETS:
            py = re.compile(bre.replace(r"\{", "{").replace(r"\}", "}"))
            if py.search(lux_str):
                return name
        return None

    def test_dark_exact_matches_0_0(self):
        self.assertEqual(self._match_bucket("lux=0.0"), "dark_exact")

    def test_faint_0_1_matches_0_5(self):
        self.assertEqual(self._match_bucket("lux=0.5"), "faint_0_1")

    def test_faint_0_1_matches_0_505(self):
        self.assertEqual(self._match_bucket("lux=0.505"), "faint_0_1")

    def test_faint_0_1_does_not_match_exact_zero(self):
        self.assertNotEqual(self._match_bucket("lux=0.0"), "faint_0_1")

    def test_dim_0_9_matches_5_5(self):
        self.assertEqual(self._match_bucket("lux=5.5"), "dim_0_9")

    def test_moderate_10_99_matches_42_3(self):
        self.assertEqual(self._match_bucket("lux=42.3"), "moderate_10_99")

    def test_bright_100_999_matches_250_7(self):
        self.assertEqual(self._match_bucket("lux=250.7"), "bright_100_999")

    def test_very_bright_1000_plus_matches_1500_0(self):
        self.assertEqual(self._match_bucket("lux=1500.0"), "very_bright_1000_plus")

    def test_dark_exact_does_not_match_nonzero(self):
        self.assertNotEqual(self._match_bucket("lux=1.0"), "dark_exact")

    def test_dim_does_not_match_two_digit_integer(self):
        self.assertNotEqual(self._match_bucket("lux=10.0"), "dim_0_9")

    def test_dim_does_not_match_dark_or_sub_1(self):
        """Partition defect (discover 81172): the old dim pattern
        ``lux=[0-9]\.[0-9]`` also matched ``lux=0.0`` (its ``[0-9]`` class
        matched the dark leading zero), so dark rows were double-counted,
        and a future ``lux=0.5`` row must land in faint_0_1, not dim."""
        self.assertNotEqual(self._match_bucket("lux=0.0"), "dim_0_9")
        self.assertNotEqual(self._match_bucket("lux=0.5"), "dim_0_9")

    def test_buckets_partition_every_lux_shape(self):
        """Each lux string shape the app can emit matches exactly one
        bucket: the buckets are disjoint and exhaustive over non-negative
        Java float strings (``"lux=" + float``), so their counts sum to
        the ``lux=`` row count."""
        shapes = ["lux=0.0", "lux=0.5", "lux=0.505", "lux=0.999",
                  "lux=1.0", "lux=5.5", "lux=9.9", "lux=2.505",
                  "lux=10.0", "lux=42.3", "lux=99.9",
                  "lux=100.0", "lux=250.7", "lux=999.9",
                  "lux=1000.0", "lux=1500.0", "lux=12345.6",
                  "lux=1.0E-45", "lux=1.2E5"]
        for shape in shapes:
            matches = [name for name, bre in spool_read.LIGHT_BUCKETS
                       if re.compile(bre.replace(r"\{", "{")
                                     .replace(r"\}", "}")).search(shape)]
            self.assertEqual(len(matches), 1,
                             f"{shape} matched {matches}")

    def test_moderate_does_not_match_three_digit(self):
        self.assertNotEqual(self._match_bucket("lux=100.0"), "moderate_10_99")

    def test_bright_does_not_match_four_digit(self):
        self.assertNotEqual(self._match_bucket("lux=1000.0"), "bright_100_999")

    def test_very_bright_does_not_match_three_digit(self):
        self.assertNotEqual(self._match_bucket("lux=999.9"), "very_bright_1000_plus")

    def test_very_bright_interval_is_escaped_for_device_bre(self):
        """Defect 4 regression: device grep is BRE, so the interval must reach
        it brace-escaped; a raw ``{3,}`` is a literal there and the bucket
        silently counts zero on-device."""
        bre = dict(spool_read.LIGHT_BUCKETS)["very_bright_1000_plus"]
        self.assertEqual(bre, r"lux=[1-9][0-9]\{3,\}")

    def test_bucket_names_are_exactly_expected(self):
        names = [name for name, _ in spool_read.LIGHT_BUCKETS]
        self.assertEqual(names, [
            "dark_exact", "faint_0_1", "dim_0_9", "moderate_10_99",
            "bright_100_999", "very_bright_1000_plus",
        ])



class CountKindTests(unittest.TestCase):
    """_count_kind counts rows of exactly one kind via epoch + kind match."""

    def test_command_matches_row_epoch_and_kind(self):
        with mock.patch.object(spool_read, "_run", return_value="7") as run:
            result = spool_read._count_kind(["adb"], "S", "PATH", "light", 5.0)
        command = run.call_args[0][2]
        self.assertIn(f"'{spool_read.ROW_EPOCH_BRE} light'", command)
        self.assertIn("grep -a -c", command)

    def test_unparseable_output_raises(self):
        with mock.patch.object(spool_read, "_run", return_value="not-a-count"):
            with self.assertRaises(RuntimeError):
                spool_read._count_kind(["adb"], "S", "PATH", "light", 5.0)


class AllowedKindsTests(unittest.TestCase):
    """ALLOWED_KINDS is exactly the allowlisted set."""

    EXPECTED = frozenset({
        "battery", "light", "acceleration", "ble_status", "wifi_link_rssi",
        "spool", "cap", "hello", "android", "owner_checkboxes", "probe",
        "ble_scan", "ble_sighting", "action",
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
        self.assertEqual(len(spool_read.ALLOWED_KINDS), 14)


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
    """Row-leading tokens cover every counted kind, but no field key name."""

    def test_every_counted_kind_is_a_row_token(self):
        self.assertEqual(
            spool_read.ALLOWED_KINDS - spool_read.ROW_KIND_TOKENS, frozenset())

    def test_wifi_row_token_is_accepted(self):
        self.assertIn("wifi_link_rssi_dbm", spool_read.ROW_KIND_TOKENS)

    def test_field_key_names_are_not_row_tokens(self):
        for key in ("phone_elapsed_ms", "observed_at", "sensor_time_ns",
                    "spool_bytes", "lux"):
            self.assertNotIn(key, spool_read.ROW_KIND_TOKENS)


if __name__ == "__main__":
    unittest.main()
