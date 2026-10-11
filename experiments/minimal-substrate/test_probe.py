# SPDX-License-Identifier: CC0-1.0
"""Tests for probe.py — bounded read-only probe runner.

A stub `adb` (python) stands in for the real binary; behavior is driven by
env vars: STUB_QUIET (emit nothing), STUB_SLEEP (seconds to sleep),
STUB_BYTES (output chars of STUB_CHAR), STUB_CHAR (output character),
STUB_RAW (raw latin-1 bytes to stdout), STUB_ERR (stderr line), STUB_RC
(exit code). Module bounds are patched per test; artifacts go to a temp dir.
"""

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import probe  # noqa: E402

STUB = """#!/usr/bin/env python3
import os
import sys
import time

if os.environ.get("STUB_QUIET"):
    sys.exit(0)
sleep_s = float(os.environ.get("STUB_SLEEP", "0"))
if sleep_s:
    time.sleep(sleep_s)
n = int(os.environ.get("STUB_BYTES", "0"))
if n:
    sys.stdout.write(os.environ.get("STUB_CHAR", "x") * n)
    sys.stdout.write("\\n")
raw = os.environ.get("STUB_RAW")
if raw:
    sys.stdout.buffer.write(raw.encode("latin-1"))
    sys.stdout.buffer.flush()
    sys.exit(0)
err = os.environ.get("STUB_ERR")
if err:
    print(err, file=sys.stderr)
rc = os.environ.get("STUB_RC")
if rc is not None:
    sys.exit(int(rc))
args = " ".join(sys.argv[1:])
if "dumpsys package" in args:
    print("Package [org.androidbody] stub identity")
elif "dumpsys sensorservice" in args:
    print("Sensor List: stub sensors")
elif "date" in args:
    print("2026-10-11T00:00:00Z")
else:
    print("stub: unrecognized command " + args, file=sys.stderr)
    sys.exit(1)
"""


class ProbeTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.stub = self.tmp / "adb"
        self.stub.write_text(STUB, encoding="utf-8")
        self.stub.chmod(0o755)
        self._old_path = os.environ.get("PATH", "")
        os.environ["PATH"] = "{0}{1}{2}".format(self.tmp, os.pathsep, self._old_path)
        self._old_env = (os.environ.get("STUB_SLEEP"), os.environ.get("STUB_BYTES"),
                         os.environ.get("STUB_RC"), os.environ.get("STUB_CHAR"),
                         os.environ.get("STUB_QUIET"), os.environ.get("STUB_ERR"),
                         os.environ.get("STUB_RAW"))
        for key in ("STUB_SLEEP", "STUB_BYTES", "STUB_RC", "STUB_CHAR",
                    "STUB_QUIET", "STUB_ERR", "STUB_RAW"):
            os.environ.pop(key, None)
        self._old_dir = probe.ARTIFACT_DIR
        self._old_timeout = probe.TIMEOUT_S
        self._old_max = probe.MAX_BYTES
        self._old_keep = probe.KEEP
        probe.ARTIFACT_DIR = self.tmp / "artifacts"
        probe.TIMEOUT_S = 5.0
        probe.MAX_BYTES = 64 * 1024
        probe.KEEP = 20

    def tearDown(self):
        os.environ["PATH"] = self._old_path
        for key, value in zip(("STUB_SLEEP", "STUB_BYTES", "STUB_RC", "STUB_CHAR",
                              "STUB_QUIET", "STUB_ERR", "STUB_RAW"), self._old_env):
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        probe.ARTIFACT_DIR = self._old_dir
        probe.TIMEOUT_S = self._old_timeout
        probe.MAX_BYTES = self._old_max
        probe.KEEP = self._old_keep
        self._tmp.cleanup()

    def _artifacts(self):
        d = probe.ARTIFACT_DIR
        return sorted(d.glob("probes-*.json")) if d.exists() else []

    def _run_stub(self, *env):
        for key, value in env:
            os.environ[key] = value
        try:
            return probe.main(["all"])
        finally:
            for key, _ in env:
                os.environ.pop(key, None)

    def test_allowlist_is_readonly(self):
        readonly = {"shell", "dumpsys", "package", "sensorservice", "date", "-u"}
        for name, args in probe.PROBES.items():
            self.assertEqual(args[0], "shell", name)
            self.assertTrue(set(args) <= readonly | {"org.androidbody", "+%Y-%m-%dT%H:%M:%SZ"}, name)

    def test_run_all_writes_artifact(self):
        rc = probe.main(["all"])
        self.assertEqual(rc, 0)
        files = self._artifacts()
        self.assertEqual(len(files), 1)
        payload = json.loads(files[0].read_text(encoding="utf-8"))
        self.assertEqual(payload["outcome"], "ok")
        self.assertEqual([p["name"] for p in payload["probes"]],
                         ["identity", "environment", "clock"])
        expected = {
            "identity": "stub identity",
            "environment": "stub sensors",
            "clock": "2026-10-11T00:00:00Z",
        }
        for record in payload["probes"]:
            self.assertEqual(record["outcome"], "ok")
            self.assertIn(expected[record["name"]], record["output"])
            self.assertEqual(record["returncode"], 0)
            self.assertGreaterEqual(record["duration_s"], 0)

    def test_timeout_is_truthful(self):
        probe.TIMEOUT_S = 1.0
        rc = self._run_stub(("STUB_SLEEP", "30"))
        self.assertEqual(rc, 1)
        files = self._artifacts()
        self.assertEqual(len(files), 1)
        payload = json.loads(files[0].read_text(encoding="utf-8"))
        self.assertEqual(payload["outcome"], "error")
        for record in payload["probes"]:
            self.assertEqual(record["outcome"], "timeout")
            self.assertIn("timeout", record["output"])
            self.assertLess(record["duration_s"], 5)

    def test_output_is_capped(self):
        probe.MAX_BYTES = 4096
        rc = self._run_stub(("STUB_BYTES", "100000"))
        self.assertEqual(rc, 0)
        files = self._artifacts()
        self.assertEqual(len(files), 1)
        payload = json.loads(files[0].read_text(encoding="utf-8"))
        for record in payload["probes"]:
            self.assertEqual(record["outcome"], "ok")
            self.assertIn("truncated", record["output"])
            self.assertLessEqual(len(record["output"].encode("utf-8")), 4096 + 64)

    def test_output_cap_counts_bytes_not_chars(self):
        probe.MAX_BYTES = 96
        rc = self._run_stub(("STUB_CHAR", "€"), ("STUB_BYTES", "100"))
        self.assertEqual(rc, 0)
        files = self._artifacts()
        self.assertEqual(len(files), 1)
        payload = json.loads(files[0].read_text(encoding="utf-8"))
        for record in payload["probes"]:
            self.assertEqual(record["outcome"], "ok")
            self.assertIn("truncated", record["output"])
            self.assertLessEqual(len(record["output"].encode("utf-8")), 96 + 64)
            self.assertLess(len(record["output"]), 100)

    def test_non_utf8_output_is_replaced_not_crash(self):
        rc = self._run_stub(("STUB_RAW", "ÿþ"))
        self.assertEqual(rc, 0)
        files = self._artifacts()
        self.assertEqual(len(files), 1)
        payload = json.loads(files[0].read_text(encoding="utf-8"))
        for record in payload["probes"]:
            self.assertEqual(record["outcome"], "ok")
            self.assertIn("�", record["output"])

    def test_empty_stdout_ok(self):
        rc = self._run_stub(("STUB_QUIET", "1"))
        self.assertEqual(rc, 0)
        files = self._artifacts()
        self.assertEqual(len(files), 1)
        payload = json.loads(files[0].read_text(encoding="utf-8"))
        for record in payload["probes"]:
            self.assertEqual(record["outcome"], "ok")
            self.assertEqual(record["output"], "")

    def test_stderr_recorded_on_error(self):
        rc = self._run_stub(("STUB_ERR", "device not found"), ("STUB_RC", "1"))
        self.assertEqual(rc, 1)
        files = self._artifacts()
        self.assertEqual(len(files), 1)
        payload = json.loads(files[0].read_text(encoding="utf-8"))
        for record in payload["probes"]:
            self.assertEqual(record["outcome"], "error")
            self.assertEqual(record["returncode"], 1)
            self.assertIn("[stderr] device not found", record["output"])

    def test_nonzero_exit_recorded(self):
        rc = self._run_stub(("STUB_RC", "3"))
        self.assertEqual(rc, 1)
        files = self._artifacts()
        self.assertEqual(len(files), 1)
        payload = json.loads(files[0].read_text(encoding="utf-8"))
        for record in payload["probes"]:
            self.assertEqual(record["outcome"], "error")
            self.assertEqual(record["returncode"], 3)

    def test_retention_bounds_storage(self):
        probe.KEEP = 3
        for _ in range(5):
            self.assertEqual(probe.main(["clock"]), 0)
        self.assertEqual(len(self._artifacts()), 3)

    def test_retention_keeps_newest_files(self):
        probe.KEEP = 2
        for _ in range(3):
            self.assertEqual(probe.main(["clock"]), 0)
        names = [f.name for f in self._artifacts()]
        self.assertEqual(len(names), 2)
        self.assertEqual(names, sorted(names)[-2:])

    def test_keep_zero_removes_all(self):
        probe.KEEP = 0
        for _ in range(3):
            self.assertEqual(probe.main(["clock"]), 0)
        self.assertEqual(self._artifacts(), [])

    def test_unknown_probe_rejected(self):
        self.assertEqual(probe.main(["bogus"]), 2)
        self.assertEqual(self._artifacts(), [])


if __name__ == "__main__":
    unittest.main()
