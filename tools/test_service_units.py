#!/usr/bin/env python3
# SPDX-License-Identifier: CC0-1.0
"""Tests for the unit load-state detector (tools/service_units.py).

The regression that matters: on 2026-10-16 ``android-body-silence.service``
loaded as ``bad-setting`` (its generated fragment had lost ``[Unit]`` and
``[Service]``) while still reading ``active (running)``, so
``tools/health-check.sh`` stayed ``HEALTH: GREEN`` through the core replant
holding on the refused restart and restarting every channel service with it. The
detector must read the LOAD column, flag every non-``loaded`` state, and report
an empty dump as UNKNOWN (exit 2) rather than as a healthy plant.
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


class ParseUnitsTest(unittest.TestCase):
    def test_reads_unit_and_load(self):
        self.assertEqual(
            service_units.parse_units(DUMP),
            [("android-body-health.service", "loaded"),
             ("android-body-silence.service", "bad-setting"),
             ("android-body-operator-view.service", "loaded")],
        )

    def test_description_with_spaces_does_not_leak_into_the_state(self):
        rows = service_units.parse_units(
            "android-body-docs.service loaded active running Mishe docs resident channel\n")
        self.assertEqual(rows, [("android-body-docs.service", "loaded")])

    def test_non_service_rows_are_dropped(self):
        self.assertEqual(service_units.parse_units(
            "android-body-spool-read.timer loaded active waiting timer\n"), [])

    def test_truncated_row_is_dropped(self):
        self.assertEqual(service_units.parse_units("android-body-docs.service\n"), [])

    def test_empty_dump_is_no_unit(self):
        self.assertEqual(service_units.parse_units(""), [])


class VerdictTest(unittest.TestCase):
    def test_loaded_is_green(self):
        self.assertEqual(service_units.verdict("loaded"), "GREEN")

    def test_every_other_state_is_red(self):
        for load in ("bad-setting", "masked", "error", "not-found", "alias"):
            self.assertEqual(service_units.verdict(load), "RED", load)


class MainTest(unittest.TestCase):
    def run_tool(self, stdin):
        return subprocess.run([sys.executable, str(TOOL)], input=stdin,
                              capture_output=True, text=True)

    def test_all_loaded_exits_zero(self):
        result = self.run_tool(DUMP.replace("bad-setting", "loaded"))
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("GREEN  unit android-body-health.service loads", result.stdout)

    def test_bad_setting_exits_one_and_names_the_unit(self):
        result = self.run_tool(DUMP)
        self.assertEqual(result.returncode, 1)
        self.assertIn("RED    unit android-body-silence.service load state bad-setting",
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
