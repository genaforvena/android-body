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
        """Return the first bucket name whose pattern matches lux_str."""
        for name, pattern in spool_read.LIGHT_BUCKETS:
            if pattern.search(lux_str):
                return name
        return None

    def test_dark_exact_matches_0_0(self):
        self.assertEqual(self._match_bucket("lux=0.0"), "dark_exact")

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

    def test_moderate_does_not_match_three_digit(self):
        self.assertNotEqual(self._match_bucket("lux=100.0"), "moderate_10_99")

    def test_bright_does_not_match_four_digit(self):
        self.assertNotEqual(self._match_bucket("lux=1000.0"), "bright_100_999")

    def test_very_bright_does_not_match_three_digit(self):
        self.assertNotEqual(self._match_bucket("lux=999.9"), "very_bright_1000_plus")

    def test_bucket_names_are_exactly_expected(self):
        names = [name for name, _ in spool_read.LIGHT_BUCKETS]
        self.assertEqual(names, [
            "dark_exact", "dim_0_9", "moderate_10_99",
            "bright_100_999", "very_bright_1000_plus",
        ])


class AllowedKindsTests(unittest.TestCase):
    """ALLOWED_KINDS is exactly the allowlisted set."""

    EXPECTED = frozenset({
        "battery", "light", "acceleration", "ble_status", "wifi_link_rssi",
        "spool", "cap", "hello", "android", "owner_checkboxes", "probe",
        "ble_scan", "action",
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
        self.assertEqual(len(spool_read.ALLOWED_KINDS), 13)


if __name__ == "__main__":
    unittest.main()
