#!/usr/bin/env python3
# SPDX-License-Identifier: CC0-1.0
"""Tests for the volume-free detector (tools/disk_free.py).

The regression that matters: the host volume is 99% used with ~15 GiB free and a
~7 GiB/day drain (DM 123190), the core scan already declares ``sense.disk.trend``
DRIFT on the same level, and ``health-check.sh`` had no disk section at all -- so
no caller in this plant named the free bytes, and exhaustion would surface only
as failed record-store and queue writes. The detector must read one ``df`` row,
RED at or below the bound, and report an unreadable table as UNKNOWN (exit 2)
rather than as a pass.
"""

import subprocess
import sys
import unittest
from pathlib import Path

import disk_free

TOOL = Path(__file__).with_name("disk_free.py")

#: A real `df -B1 -P /` table, as this host prints it: header, then one row whose
#: Available column is index 3. Bytes are the shape, not a measurement.
TABLE = (
    "Filesystem                            1-blocks         Used   Available"
    " Capacity Mounted on\n"
    "/dev/mapper/ubuntu--vg-ubuntu--lv 980666998784 923257671680 16421289984"
    "      99% /\n"
)


class ParseFreeTest(unittest.TestCase):
    def test_reads_the_available_column(self):
        mount, available, reason = disk_free.parse_free(TABLE)
        self.assertIsNone(reason)
        self.assertEqual(mount, "/")
        self.assertEqual(available, 16421289984)

    def test_table_without_a_header_is_read(self):
        _head, row = TABLE.splitlines()
        mount, available, reason = disk_free.parse_free(row + "\n")
        self.assertIsNone(reason)
        self.assertEqual((mount, available), ("/", 16421289984))

    def test_empty_input_is_unavailable(self):
        self.assertEqual(disk_free.parse_free(""), (None, None, "df printed no table"))

    def test_two_filesystem_rows_are_unavailable(self):
        _head, row = TABLE.splitlines()
        parsed = disk_free.parse_free(f"{row}\n{row}\n")
        self.assertEqual(parsed[0], None)
        self.assertIn("2 filesystem rows", parsed[2])

    def test_a_non_numeric_column_is_unavailable(self):
        parsed = disk_free.parse_free(
            "Filesystem 1-blocks Used Available Capacity Mounted on\n"
            "/dev/sda1 1000 10 unknown 11% /\n")
        self.assertIsNone(parsed[0])
        self.assertIn("not a number", parsed[2])

    def test_a_negative_available_is_unavailable(self):
        parsed = disk_free.parse_free("/dev/sda1 1000 10 -1 11% /\n")
        self.assertIsNone(parsed[0])
        self.assertIn("negative", parsed[2])

    def test_a_short_row_is_unavailable(self):
        parsed = disk_free.parse_free("/dev/sda1 1000\n")
        self.assertIsNone(parsed[0])
        self.assertIn("no Available column", parsed[2])

    def test_a_df_error_line_is_unavailable_not_a_zero(self):
        # `df` on a path that does not exist prints one error line; that is not a
        # reading, and reading it as free=0 would assert the exact failure.
        parsed = disk_free.parse_free("df: /x: No such file or directory\n")
        self.assertIsNone(parsed[0])
        self.assertIsNotNone(parsed[2])


class CliTest(unittest.TestCase):
    def run_tool(self, stdin, *args):
        return subprocess.run(
            [sys.executable, str(TOOL), *args],
            input=stdin, capture_output=True, text=True, timeout=20)

    def test_above_the_bound_is_green(self):
        result = self.run_tool(TABLE, "--bound-bytes", "1000")
        self.assertEqual(result.returncode, 0)
        self.assertIn("GREEN  disk free 16421289984B/15.3GiB on / (bound 1000B/0.0GiB)",
                      result.stdout)
        self.assertIn(" on /", result.stdout)

    def test_at_the_bound_is_red(self):
        # The threshold is inclusive, like §5's queue warning: free exactly at the
        # bound is the level the bound names, not above it.
        result = self.run_tool(TABLE, "--bound-bytes", "16421289984")
        self.assertEqual(result.returncode, 1)
        self.assertIn("RED    disk free 16421289984B/15.3GiB on / at/below the bound 16421289984B/15.3GiB (100%)",
                      result.stdout)

    def test_below_the_bound_is_red(self):
        result = self.run_tool(TABLE, "--bound-bytes", "21474836480")
        self.assertEqual(result.returncode, 1)
        self.assertIn("RED    disk free 16421289984B/15.3GiB on / at/below the bound 21474836480B/20.0GiB (76%)",
                      result.stdout)

    def test_the_default_bound_is_the_core_near_threshold(self):
        # 20 GiB, `_DISK_TREND_NEAR_BYTES` in the pinned core's discovery.py -- not
        # its 10 GiB floor, which is only the countdown target.
        self.assertEqual(disk_free.DEFAULT_BOUND_BYTES, 20 * 1024 * 1024 * 1024)

    def test_unreadable_table_is_unknown_and_exits_two(self):
        result = self.run_tool("df: /x: No such file or directory\n")
        self.assertEqual(result.returncode, 2)
        self.assertIn("UNKNOWN disk free (", result.stdout)

    def test_empty_input_is_unknown_not_a_pass(self):
        result = self.run_tool("")
        self.assertEqual(result.returncode, 2)
        self.assertIn("UNKNOWN disk free (df printed no table)", result.stdout)

    def test_a_non_positive_bound_is_unknown_not_a_pass(self):
        # The caller owns the threshold, so a bad one is an unavailable reading:
        # the tool prints its own UNKNOWN line (exit 2) instead of argparse's
        # usage, which would leave the check with no verdict at all.
        for bound in ("0", "-1", "abc"):
            result = self.run_tool(TABLE, "--bound-bytes", bound)
            self.assertEqual(result.returncode, 2, bound)
            self.assertIn("UNKNOWN disk free (bound-bytes", result.stdout, bound)
            self.assertNotIn("GREEN", result.stdout)


if __name__ == "__main__":
    unittest.main()
