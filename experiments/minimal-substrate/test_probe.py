# SPDX-License-Identifier: CC0-1.0
"""Tests for probe.py — bounded read-only probe runner.

A stub `adb` (python) stands in for the real binary; behavior is driven by
env vars: STUB_QUIET (emit nothing), STUB_SLEEP (seconds to sleep),
STUB_BYTES (output chars of STUB_CHAR), STUB_CHAR (output character),
STUB_RAW (raw latin-1 bytes to stdout), STUB_ERR (stderr line), STUB_RC
(exit code). The stub also simulates run-as commands (id, /proc reads,
denied read, scratch write/run/delete/verify). Module bounds are patched
per test; artifacts go to a temp dir; spool/apk fixtures are temp files.
"""

import hashlib
import json
import os
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import probe  # noqa: E402

STUB = """#!/usr/bin/env python3
import os
import signal
import sys
import time

if os.environ.get("STUB_CORRUPT") and "run-as" in sys.argv[1:]:
    print("run-as: Package 'org.androidbody' has corrupt installation")
    sys.exit(0)

signal.signal(signal.SIGINT, signal.SIG_DFL)

if os.environ.get("STUB_QUIET"):
    sys.exit(0)
sleep_s = float(os.environ.get("STUB_SLEEP", "0"))
if sleep_s > 0 or "sleep" in sys.argv[1:]:
    time.sleep(sleep_s or 30)
    sys.exit(0)
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
args = sys.argv[1:]
joined = " ".join(args)
if "run-as" in joined:
    rest = args[args.index("run-as") + 2:]
    if rest[:1] == ["id"]:
        print("uid=10224(u0_a224) gid=10224(u0_a224) groups=1003(graphics),1004(input),"
              "1007(log),1011(adb),1015(sdcard_rw),1028(sdcard_r),3001(net_bt_admin),"
              "3002(net_bt),3003(inet),3006(net_bw_stats) context=u:r:untrusted_app:s0")
        sys.exit(0)
    if rest[:1] == ["cat"]:
        target = rest[1] if len(rest) > 1 else ""
        if target == "/proc/self/status":
            sys.stdout.write("Name:\\tapp\\nGroups:\\t1003 1004 1007 1011 1015 1028 3001 3002 3003 3006\\n")
            sys.exit(0)
        if target == "/proc/self/attr/current":
            print("u:r:untrusted_app:s0")
            sys.exit(0)
        print("Permission denied", file=sys.stderr)
        sys.exit(1)
    if rest[:2] == ["sh", "-c"] and ("printf" in rest[2] or "cat >" in rest[2]):
        sys.exit(0)
    if rest[:1] == ["sh"]:
        print("probe script uid=10224 cwd=/data/data/org.androidbody")
        sys.exit(0)
    if rest[:1] == ["rm"]:
        sys.exit(0)
    if rest[:1] == ["ls"]:
        print("No such file or directory", file=sys.stderr)
        sys.exit(1)
    print("stub: unrecognized run-as command", file=sys.stderr)
    sys.exit(1)
if "id" in joined:
    print("uid=2000(shell) gid=2000(shell) groups=1003(graphics),1004(input),1007(log),"
          "1011(adb),1015(sdcard_rw),1028(sdcard_r),3001(net_bt_admin),3002(net_bt),"
          "3003(inet),3006(net_bw_stats) context=u:r:shell:s0")
    sys.exit(0)
if "dumpsys package" in joined:
    print("Package [org.androidbody] stub identity")
elif "dumpsys sensorservice" in joined:
    print("Sensor List: stub sensors")
elif "date" in joined:
    print("2026-10-11T00:00:00Z")
else:
    print("stub: unrecognized command " + joined, file=sys.stderr)
    sys.exit(1)
if rc is not None:
    sys.exit(int(rc))
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
        self._old_max_line = probe.MAX_LINE_BYTES
        self._old_keep = probe.KEEP
        probe.ARTIFACT_DIR = self.tmp / "artifacts"
        probe.TIMEOUT_S = 5.0
        probe.MAX_BYTES = 64 * 1024
        probe.MAX_LINE_BYTES = 1024
        probe.KEEP = 20
        self._old_spool = os.environ.get("MINIMAL_SUBSTRATE_SPOOL")
        self._old_apk = os.environ.get("MINIMAL_SUBSTRATE_APK_PATH")
        self.spool = self.tmp / "note3.observations.log"
        self.spool.write_text(
            "104569 1791685181 probe identity uid=10224 groups=3002 3003 9997 50224 session=90cc9bdc\n",
            encoding="utf-8")
        os.environ["MINIMAL_SUBSTRATE_SPOOL"] = str(self.spool)
        self.apk = self.tmp / "installed.apk"
        with zipfile.ZipFile(self.apk, "w") as zf:
            zf.writestr("classes.dex", b"fake dex Lorg/androidbody/ExecutionProbe; probe identity uid=")
        os.environ["MINIMAL_SUBSTRATE_APK_PATH"] = str(self.apk)

    def tearDown(self):
        os.environ["PATH"] = self._old_path
        for key, value in zip(("STUB_SLEEP", "STUB_BYTES", "STUB_RC", "STUB_CHAR",
                              "STUB_QUIET", "STUB_ERR", "STUB_RAW"), self._old_env):
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        for key, value in (("MINIMAL_SUBSTRATE_SPOOL", self._old_spool),
                           ("MINIMAL_SUBSTRATE_APK_PATH", self._old_apk)):
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        probe.ARTIFACT_DIR = self._old_dir
        probe.TIMEOUT_S = self._old_timeout
        probe.MAX_BYTES = self._old_max
    def _run_stub(self, *env):
        for key, value in env:
            os.environ[key] = value
        try:
            return probe.main(["host-clock"])
        finally:
            for key, _ in env:
                os.environ.pop(key, None)

    def _artifacts(self):
        d = probe.ARTIFACT_DIR
        return sorted(d.glob("probes-*.json")) if d.exists() else []

    def _last_payload(self):
        files = self._artifacts()
        self.assertEqual(len(files), 1)
        return json.loads(files[0].read_text(encoding="utf-8"))

    def test_allowlist_is_readonly(self):
        readonly = {"shell", "id", "date", "-u", "+%Y-%m-%dT%H:%M:%SZ", "dumpsys",
                    "package", "sensorservice", "run-as", "org.androidbody", "cat",
                    "/proc/self/status", "/proc/self/attr/current",
                    "/data/data/com.android.settings/databases/settings.db", "sleep", "30"}
        for name, spec in probe.PROBES.items():
            self.assertIn(spec["context"], {"host", "run-as", "apk-uid"}, name)
            self.assertIn(spec["expect"], {"ok", "denied", "interrupted"}, name)
            if "args" in spec:
                self.assertEqual(spec["args"][0], "shell", name)
                self.assertTrue(set(spec["args"]) <= readonly, name)

    def test_run_all_writes_artifact(self):
        rc = probe.main(["all"])
        self.assertEqual(rc, 0)
        payload = self._last_payload()
        self.assertEqual(payload["outcome"], "ok")
        self.assertEqual([p["name"] for p in payload["probes"]], list(probe.PROBES))
        expected = {
            "host-identity": "uid=2000(shell)",
            "host-environment": "stub sensors",
            "host-clock": "2026-10-11T00:00:00Z",
            "runas-identity": "uid=10224",
            "runas-status": "Groups:",
            "runas-selinux": "u:r:untrusted_app:s0",
            "runas-denied": "Permission denied",

            "host-interrupt": "SIGINT",
            "apk-identity": "probe identity uid=10224",
            "apk-dex": "ExecutionProbe class=True",
            "scratch-rerun": "rerun matches=True",
        }
        for record in payload["probes"]:
            self.assertEqual(record["outcome"], record["expect"], record["name"])
            self.assertIn(expected[record["name"]], record["output"], record["name"])
            self.assertGreaterEqual(record["duration_s"], 0)

    def test_context_labels_present(self):
        self.assertEqual(probe.main(["all"]), 0)
        payload = self._last_payload()
        contexts = {p["name"]: p["context"] for p in payload["probes"]}
        self.assertEqual(contexts["host-identity"], "host")
        self.assertEqual(contexts["runas-identity"], "run-as")
        self.assertEqual(contexts["scratch-rerun"], "run-as")
        self.assertEqual(contexts["apk-identity"], "apk-uid")
        self.assertEqual(contexts["apk-dex"], "host")
        self.assertNotIn("emulator", contexts.values())

    def test_identity_fields_parsed(self):
        self.assertEqual(probe.main(["all"]), 0)
        payload = self._last_payload()
        records = {p["name"]: p for p in payload["probes"]}
        host = records["host-identity"]["identity"]
        self.assertEqual(host["uid"], "2000")
        self.assertEqual(host["context"], "u:r:shell:s0")
        self.assertIn("1003", host["groups"])
        runas = records["runas-identity"]["identity"]
        self.assertEqual(runas["uid"], "10224")

        status = records["runas-status"]["identity"]
        self.assertIn("3003", status["groups"])

    def test_per_line_cap_enforced(self):
        probe.MAX_LINE_BYTES = 32
        rc = self._run_stub(("STUB_BYTES", "100"))
        self.assertEqual(rc, 0)
        for record in self._last_payload()["probes"]:
            for line in record["output"].split("\n"):
                self.assertLessEqual(len(line.encode("utf-8")), 32 + 64, line)

    def test_timeout_is_truthful(self):
        probe.TIMEOUT_S = 1.0
        rc = self._run_stub(("STUB_SLEEP", "30"))
        self.assertEqual(rc, 1)
        payload = self._last_payload()
        self.assertEqual(payload["outcome"], "partial")
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

    def test_denial_retained_as_denied(self):
        record = probe.run_probe("runas-denied")
        self.assertEqual(record["context"], "run-as")
        self.assertEqual(record["expect"], "denied")
        self.assertEqual(record["outcome"], "denied")
        self.assertEqual(record["returncode"], 1)
        self.assertIn("Permission denied", record["output"])
        self.assertEqual(probe.main(["runas-denied"]), 0)

    def test_exit0_corrupt_installation_not_success(self):
        os.environ["STUB_CORRUPT"] = "1"
        try:
            record = probe.run_probe("runas-identity")
            scratch = probe.run_probe("scratch-rerun")
            self.assertEqual(probe.main(["runas-identity"]), 1)
        finally:
            os.environ.pop("STUB_CORRUPT", None)
        self.assertEqual(record["context"], "run-as")
        self.assertEqual(record["returncode"], 0)
        self.assertEqual(record["outcome"], "error")
        self.assertIn("corrupt installation", record["output"])
        self.assertIn("exit0", record["output"])
        self.assertEqual(scratch["outcome"], "error")
        self.assertFalse(scratch["rerun_matches"])
        self.assertEqual(scratch["verify_outcome"], "error")

    def test_interrupt_observed_truthful(self):
        record = probe.run_probe("host-interrupt")
        self.assertEqual(record["context"], "host")
        self.assertEqual(record["expect"], "interrupted")
        self.assertEqual(record["outcome"], "interrupted")
        self.assertEqual(record["returncode"], -2)
        self.assertEqual(record["signal_sent"], "SIGINT")
        self.assertIn("SIGINT", record["output"])
        self.assertIn("no retry", record["output"])

    def test_scratch_persisted_rerun_and_teardown(self):
        record = probe.run_probe("scratch-rerun")
        self.assertEqual(record["context"], "run-as")
        self.assertEqual(record["outcome"], "ok")
        self.assertEqual(record["script"], probe.SCRATCH_SCRIPT)
        self.assertEqual(record["script_sha256"],
                         hashlib.sha256(probe.SCRATCH_SCRIPT.encode("utf-8")).hexdigest())
        self.assertEqual(record["script_path"], probe.SCRATCH_PATH)
        self.assertEqual(record["write_returncode"], 0)
        self.assertIn("probe script uid=10224", record["run1_output"])
        self.assertEqual(record["run1_output"], record["run2_output"])
        self.assertTrue(record["rerun_matches"])
        self.assertEqual(record["delete_returncode"], 0)
        self.assertEqual(record["verify_outcome"], "denied")
        self.assertIn("NOT apk-uid evidence", record["note"])
        self.assertEqual(probe.main(["scratch-rerun"]), 0)

    def test_apk_identity_captured_from_spool(self):
        record = probe.run_probe("apk-identity")
        self.assertEqual(record["context"], "apk-uid")
        self.assertEqual(record["outcome"], "ok")
        self.assertIn("probe identity uid=10224 groups=3002 3003 9997 50224", record["output"])
        self.assertEqual(record["event_id"], 104569)
        self.assertEqual(record["phone_timestamp_utc"], "2026-10-11T02:19:41Z")
        self.assertIn("APK process", record["source"])

    def test_apk_identity_absent_is_truthful(self):
        self.spool.write_text("125856 1791706278 acceleration x=1 y=2 z=3\n", encoding="utf-8")
        record = probe.run_probe("apk-identity")
        self.assertEqual(record["outcome"], "error")
        self.assertIn("no probe identity event found", record["output"])
        self.assertEqual(probe.main(["apk-identity"]), 1)

    def test_apk_dex_correlation(self):
        record = probe.run_probe("apk-dex")
        self.assertEqual(record["context"], "host")
        self.assertEqual(record["outcome"], "ok")
        self.assertEqual(record["apk_sha256"], hashlib.sha256(self.apk.read_bytes()).hexdigest())
        self.assertTrue(record["contains_execution_probe_class"])
        self.assertTrue(record["contains_identity_format_string"])
        self.assertIn("not execution evidence", record["note"])

    def test_apk_dex_absence_retained(self):
        plain = self.tmp / "plain.apk"
        with zipfile.ZipFile(plain, "w") as zf:
            zf.writestr("classes.dex", b"fake dex without the probe")
        os.environ["MINIMAL_SUBSTRATE_APK_PATH"] = str(plain)
        record = probe.run_probe("apk-dex")
        self.assertEqual(record["outcome"], "ok")
        self.assertFalse(record["contains_execution_probe_class"])
        self.assertFalse(record["contains_identity_format_string"])

    def test_retention_bounds_storage(self):
        probe.KEEP = 3
        for _ in range(5):
            self.assertEqual(probe.main(["host-clock"]), 0)
        self.assertEqual(len(self._artifacts()), 3)

    def test_retention_keeps_newest_files(self):
        probe.KEEP = 2
        for _ in range(3):
            self.assertEqual(probe.main(["host-clock"]), 0)
        names = [f.name for f in self._artifacts()]
        self.assertEqual(len(names), 2)
        self.assertEqual(names, sorted(names)[-2:])

    def test_keep_zero_removes_all(self):
        probe.KEEP = 0
        for _ in range(3):
            self.assertEqual(probe.main(["host-clock"]), 0)
        self.assertEqual(self._artifacts(), [])

    def test_unknown_probe_rejected(self):
        self.assertEqual(probe.main(["bogus"]), 2)
        self.assertEqual(self._artifacts(), [])


if __name__ == "__main__":
    unittest.main()
