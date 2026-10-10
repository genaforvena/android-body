#!/bin/sh
# SPDX-License-Identifier: CC0-1.0
set -eu
cd "$(dirname "$0")/.."
OUT=$(mktemp -d)
trap 'rm -rf "$OUT"' EXIT HUP INT TERM
if command -v javac >/dev/null 2>&1; then
  javac -encoding UTF-8 -source 8 -target 8 -d "$OUT" app/src/main/java/org/androidbody/Protocol.java app/src/main/java/org/androidbody/ExecutionProbe.java app/src/main/java/org/androidbody/WifiRssi.java app/src/test/java/org/androidbody/ProtocolTest.java
else
  java -m jdk.compiler/com.sun.tools.javac.Main -encoding UTF-8 -source 8 -target 8 -d "$OUT" app/src/main/java/org/androidbody/Protocol.java app/src/main/java/org/androidbody/ExecutionProbe.java app/src/main/java/org/androidbody/WifiRssi.java app/src/test/java/org/androidbody/ProtocolTest.java
fi
java -cp "$OUT" org.androidbody.ProtocolTest
