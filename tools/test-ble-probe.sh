#!/bin/sh
# SPDX-License-Identifier: CC0-1.0
# JVM-only harness for the ble-probe report/result regression test.
#
# `ble-probe` is a second Gradle module, so the workflow's `:app:` gradle line
# never compiles or runs it, and nothing else did either:
# `ble-probe/src/test/java/org/androidbody/bleprobe/ProbeReportTest.java` had a
# registered `:ble-probe:testProbeReport` task and no CI caller at all -- the
# same "test with no CI caller" shape as `93909dc`'s `check_docs.py`, and one
# the app-only `tools/check_ci_coverage.py` could not see. The classes under
# test (`ProbeReport`, `ProbeResult`) are Android-free, so this compiles just
# those with `javac` and runs the test directly, the way
# `tools/test-protocol.sh` covers `BleScanEventsTest` without the Android SDK.
set -eu
cd "$(dirname "$0")/.."
OUT=$(mktemp -d)
trap 'rm -rf "$OUT"' EXIT HUP INT TERM
SRC="ble-probe/src/main/java/org/androidbody/bleprobe/ProbeReport.java ble-probe/src/main/java/org/androidbody/bleprobe/ProbeResult.java ble-probe/src/test/java/org/androidbody/bleprobe/ProbeReportTest.java"
if command -v javac >/dev/null 2>&1; then
  javac -encoding UTF-8 -source 8 -target 8 -d "$OUT" $SRC
else
  java -m jdk.compiler/com.sun.tools.javac.Main -encoding UTF-8 -source 8 -target 8 -d "$OUT" $SRC
fi
java -cp "$OUT" org.androidbody.bleprobe.ProbeReportTest
