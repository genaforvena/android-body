#!/bin/sh
# SPDX-License-Identifier: CC0-1.0
set -eu
cd "$(dirname "$0")/.."
OUT=$(mktemp -d)
trap 'rm -rf "$OUT"' EXIT HUP INT TERM
if command -v javac >/dev/null 2>&1; then
  javac -encoding UTF-8 -source 8 -target 8 -sourcepath app/src/main/java -d "$OUT" app/src/main/java/org/androidbody/Protocol.java app/src/main/java/org/androidbody/ExecutionProbe.java app/src/main/java/org/androidbody/ExecProbe.java app/src/main/java/org/androidbody/WifiRssi.java app/src/main/java/org/androidbody/BoundedEvaluator.java app/src/main/java/org/androidbody/BoundedExec.java app/src/main/java/org/androidbody/ObservationSpool.java app/src/main/java/org/androidbody/EvalOutcome.java app/src/main/java/org/androidbody/BleScanEvents.java app/src/test/java/org/androidbody/ProtocolTest.java app/src/test/java/org/androidbody/BoundedEvaluatorTest.java app/src/test/java/org/androidbody/EvalOutcomeTest.java app/src/test/java/org/androidbody/BleScanEventsTest.java
else
  java -m jdk.compiler/com.sun.tools.javac.Main -encoding UTF-8 -source 8 -target 8 -sourcepath app/src/main/java -d "$OUT" app/src/main/java/org/androidbody/Protocol.java app/src/main/java/org/androidbody/ExecutionProbe.java app/src/main/java/org/androidbody/ExecProbe.java app/src/main/java/org/androidbody/WifiRssi.java app/src/main/java/org/androidbody/BoundedEvaluator.java app/src/main/java/org/androidbody/BoundedExec.java app/src/main/java/org/androidbody/ObservationSpool.java app/src/main/java/org/androidbody/EvalOutcome.java app/src/main/java/org/androidbody/BleScanEvents.java app/src/test/java/org/androidbody/ProtocolTest.java app/src/test/java/org/androidbody/BoundedEvaluatorTest.java app/src/test/java/org/androidbody/EvalOutcomeTest.java app/src/test/java/org/androidbody/BleScanEventsTest.java
fi
java -cp "$OUT" org.androidbody.ProtocolTest
java -cp "$OUT" org.androidbody.BoundedEvaluatorTest
java -cp "$OUT" org.androidbody.BleScanEventsTest
java -cp "$OUT" org.androidbody.EvalOutcomeTest
