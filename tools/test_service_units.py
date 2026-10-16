#!/usr/bin/env python3
# SPDX-License-Identifier: CC0-1.0
"""Tests for the unit load/active-state detector (tools/service_units.py).

Two regressions matter. (1) On 2026-10-16 ``android-body-silence.service``
loaded as ``bad-setting`` (its generated fragment had lost ``[Unit]`` and
``[Service]``) while still reading ``active (running)``, so
``tools/health-check.sh`` stayed ``HEALTH: GREEN`` through the core replant
holding on the refused restart and restarting every channel service with it; the
detector must read the LOAD column and flag every non-``loaded`` state. (2) The
same day ``android-body-crosssite-check.service`` sat at ``loaded failed`` for
over nine hours -- a health-owned detector whose oneshot unit is deliberately
left failed so a detected cross-site CLI selection stays visible -- while the
LOAD-only read called it GREEN and so did the dashboard; the detector must read
the ACTIVE column too. An empty dump is UNKNOWN (exit 2), never a healthy plant.
"""

import subprocess
import sys
import unittest
from pathlib import Path

import service_units

TOOL = Path(__file__).with_name("service_units.py")

#: `systemctl --user list-units 'android-body-*.service' --all --full --plain
#: --no-legend` as it renders today: the bad-setting unit's description falls
#: back to its own name, because the mangled fragment has no ``Description=``.
DUMP = (
    "android-body-health.service                                loaded    active   running Mishe health resident channel\n"
    "android-body-silence.service                               bad-setting active running android-body-silence.service\n"
    "android-body-operator-view.service                         loaded    active   running Mishe operator-view resident channel\n"
)

#: The same dump shape with the health-owned oneshot that failed, and a normal
#: timer oneshot sitting between runs at ``inactive``/``dead``.
DUMP_FAILED = (
    "android-body-crosssite-check.service                       loaded    failed   failed Android Body cross-site CLI selection check\n"
    "android-body-spool-read.service                            loaded    inactive dead  Android Body spool summary publisher\n"
)


class ParseUnitsTest(unittest.TestCase):
    def test_reads_unit_load_active_and_sub(self):
        self.assertEqual(
            service_units.parse_units(DUMP),
            [("android-body-health.service", "loaded", "active", "running"),
             ("android-body-silence.service", "bad-setting", "active", "running"),
             ("android-body-operator-view.service", "loaded", "active", "running")],
        )

    def test_description_with_spaces_does_not_leak_into_the_state(self):
        rows = service_units.parse_units(
            "android-body-docs.service loaded active running Mishe docs resident channel\n")
        self.assertEqual(rows, [("android-body-docs.service", "loaded", "active", "running")])

    def test_non_service_rows_are_dropped(self):
        self.assertEqual(service_units.parse_units(
            "android-body-spool-read.timer loaded active waiting timer\n"), [])

    def test_row_without_the_state_columns_is_dropped(self):
        self.assertEqual(service_units.parse_units("android-body-docs.service\n"), [])
        self.assertEqual(service_units.parse_units("android-body-docs.service loaded\n"), [])
        self.assertEqual(service_units.parse_units("android-body-docs.service loaded active\n"), [])

    def test_empty_dump_is_no_unit(self):
        self.assertEqual(service_units.parse_units(""), [])


class VerdictTest(unittest.TestCase):
    def test_loaded_and_active_is_green(self):
        self.assertEqual(service_units.verdict("loaded", "active"), "GREEN")

    def test_inactive_and_dead_are_green(self):
        for active in ("inactive", "dead"):
            self.assertEqual(service_units.verdict("loaded", active), "GREEN", active)

    def test_failed_active_is_red(self):
        self.assertEqual(service_units.verdict("loaded", "failed"), "RED")

    def test_every_other_load_is_red(self):
        for load in ("bad-setting", "masked", "error", "not-found", "alias"):
            self.assertEqual(service_units.verdict(load, "active"), "RED", load)

    def test_a_load_only_call_still_gets_the_load_verdict(self):
        self.assertEqual(service_units.verdict("loaded"), "GREEN")
        self.assertEqual(service_units.verdict("bad-setting"), "RED")


class MainTest(unittest.TestCase):
    def run_tool(self, stdin):
        return subprocess.run([sys.executable, str(TOOL)], input=stdin,
                              capture_output=True, text=True)

    def test_all_loaded_and_active_exits_zero(self):
        result = self.run_tool(DUMP.replace("bad-setting", "loaded"))
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("GREEN  unit android-body-health.service loads active=active sub=running",
                      result.stdout)

    def test_bad_setting_exits_one_and_names_the_unit(self):
        result = self.run_tool(DUMP)
        self.assertEqual(result.returncode, 1)
        self.assertIn("RED    unit android-body-silence.service load state bad-setting",
                      result.stdout)

    def test_failed_oneshot_exits_one_and_names_the_unit(self):
        result = self.run_tool(DUMP_FAILED)
        self.assertEqual(result.returncode, 1)
        self.assertIn(
            "RED    unit android-body-crosssite-check.service active state failed sub failed "
            "(last start failed)", result.stdout)
        self.assertIn("GREEN  unit android-body-spool-read.service loads active=inactive sub=dead",
                      result.stdout)

    def test_empty_dump_is_unknown_not_a_pass(self):
        result = self.run_tool("")
        self.assertEqual(result.returncode, 2)
        self.assertIn("UNKNOWN", result.stdout)

    def test_arguments_are_refused(self):
        result = subprocess.run([sys.executable, str(TOOL), "extra"],
                                input=DUMP, capture_output=True, text=True)
        self.assertEqual(result.returncode, 2)


if __name__ == "__main__":
    unittest.main()
