# SPDX-License-Identifier: CC0-1.0
"""Tests for the frozen-runtime activation record (tools/runtime_manifest.py).

The regression that matters: the record was maintained by hand as the last step of
a prose deploy procedure, so it named bytes that were no longer deployed while
readers treated it as the fingerprint source. These tests pin the detector that
makes that drift RED and the recorder that cannot write an undeclared divergence.
"""

import contextlib
import datetime
import io
import json
import os
import subprocess
import tempfile
import time
import unittest
from pathlib import Path

import runtime_manifest

SOURCE_WATCH = "experiments/perception/watch.py"
SOURCE_SERVER = "rendezvous/minimal-server/server.py"


def write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


@contextlib.contextmanager
def stub_systemctl(**properties: str):
    """Put a stub ``systemctl`` first on PATH that prints the named property values.

    ``unit_entered`` asks ``systemctl --user show -p PROP --value UNIT``; a real
    completed oneshot cannot be staged in a unit test, so the stub answers that
    query shape from ``properties`` and every other property with an empty value.
    """
    with tempfile.TemporaryDirectory() as tmp:
        stub = Path(tmp) / "systemctl"
        stub.write_text(
            "#!/usr/bin/env python3\n"
            "import os, sys\n"
            "args = sys.argv[1:]\n"
            "prop = args[args.index('-p') + 1]\n"
            "print(os.environ.get('STUB_' + prop, ''))\n",
            encoding="utf-8",
        )
        stub.chmod(0o755)
        old_path = os.environ.get("PATH", "")
        saved = {key: os.environ.get("STUB_" + key) for key in properties}
        os.environ["PATH"] = str(tmp) + os.pathsep + old_path
        for key, value in properties.items():
            os.environ["STUB_" + key] = value
        try:
            yield
        finally:
            os.environ["PATH"] = old_path
            for key, value in saved.items():
                if value is None:
                    os.environ.pop("STUB_" + key, None)
                else:
                    os.environ["STUB_" + key] = value


class ManifestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.repo = Path(self.tmp.name) / "repo"
        self.site = self.repo / ".mishe-tauftauf"
        self.runtime = self.site / "body" / "runtime"
        self.manifest = self.site / "body" / "runtime-manifest.json"
        self.runtime.mkdir(parents=True)
        (self.repo / "experiments" / "perception").mkdir(parents=True)
        (self.repo / "rendezvous" / "minimal-server").mkdir(parents=True)
        subprocess.run(["git", "init", "-q", str(self.repo)], check=True,
                       capture_output=True)
        for key, value in (("user.email", "t@example.invalid"), ("user.name", "t")):
            subprocess.run(["git", "-C", str(self.repo), "config", key, value], check=True)

    def deploy(self, name: str, text: str) -> Path:
        return write(self.runtime / name, text)

    def source(self, rel: str, text: str) -> Path:
        return write(self.repo / rel, text)

    def commit(self) -> None:
        subprocess.run(["git", "-C", str(self.repo), "add", "-A"], check=True)
        subprocess.run(["git", "-C", str(self.repo), "commit", "-qm", "fixture"], check=True)

    def record_doc(self, files: dict, **extra) -> None:
        doc = {"checked": "2026-10-12T04:51:30+00:00", "schema": 2,
               "core_pin_source": "../health/runtime-release.json", "files": files}
        doc.update(extra)
        write(self.manifest, json.dumps(doc))

    def run_check(self) -> tuple[int, list[str]]:
        return runtime_manifest.check(self.site, self.repo)

    def levels(self, lines: list[str]) -> dict[str, str]:
        return {line.split()[1].rstrip(":"): line.split()[0] for line in lines if line[0].isupper()}

    def test_green_when_deployed_matches_record_and_source(self) -> None:
        self.source(SOURCE_WATCH, "print('v1')\n")
        self.deploy("watch.py", "print('v1')\n")
        self.commit()
        self.record_doc({"watch.py": {"sha256": runtime_manifest.sha256_file(self.runtime / "watch.py"),
                                      "source": SOURCE_WATCH, "divergence": None}})
        code, lines = self.run_check()
        self.assertEqual(0, code, lines)

    def test_red_when_deployed_drifts_from_record(self) -> None:
        self.source(SOURCE_WATCH, "print('v2')\n")
        self.deploy("watch.py", "print('v2')\n")
        self.commit()
        self.record_doc({"watch.py": {"sha256": "0" * 64, "source": SOURCE_WATCH,
                                      "divergence": None}})
        code, lines = self.run_check()
        self.assertEqual(1, code, lines)
        self.assertTrue(any("!=" in line and "recorded" in line for line in lines), lines)

    def test_red_when_source_differs_without_declared_divergence(self) -> None:
        self.source(SOURCE_WATCH, "print('source')\n")
        self.deploy("watch.py", "print('deployed')\n")
        self.commit()
        self.record_doc({"watch.py": {"sha256": runtime_manifest.sha256_file(self.runtime / "watch.py"),
                                      "source": SOURCE_WATCH, "divergence": None}})
        code, lines = self.run_check()
        self.assertEqual(1, code, lines)
        self.assertTrue(any("no recorded divergence" in line for line in lines), lines)

    def test_green_when_worktree_source_has_undeployed_edits(self) -> None:
        # The shared checkout is routinely dirty while a peer edits a deployed
        # module's source. The deployed bytes still equal the committed source,
        # so this is undeployed work, not deployment drift.
        self.source(SOURCE_WATCH, "print('v1')\n")
        self.deploy("watch.py", "print('v1')\n")
        self.commit()
        self.record_doc({"watch.py": {"sha256": runtime_manifest.sha256_file(self.runtime / "watch.py"),
                                      "source": SOURCE_WATCH, "divergence": None}})
        self.source(SOURCE_WATCH, "print('v2-uncommitted')\n")
        code, lines = self.run_check()
        self.assertEqual(0, code, lines)
        self.assertTrue(any("undeployed edits" in line for line in lines), lines)

    def test_record_succeeds_when_worktree_source_has_undeployed_edits(self) -> None:
        # A peer's undeployed edit must not block recording a deploy of the
        # committed bytes: record() compares against the committed blob at HEAD,
        # as check() does. Otherwise every activation of committed bytes waits
        # for a clean shared checkout.
        self.source(SOURCE_WATCH, "print('v1')\n")
        self.deploy("watch.py", "print('v1')\n")
        self.commit()
        self.source(SOURCE_WATCH, "print('v2-uncommitted')\n")
        self.record_doc({})
        code, lines = runtime_manifest.record(
            self.site, self.repo, None, {"watch.py": SOURCE_WATCH}, {}, None)
        self.assertEqual(0, code, lines)
        self.assertTrue(any("undeployed edits" in line for line in lines), lines)
        doc = json.loads(self.manifest.read_text(encoding="utf-8"))
        self.assertIsNone(doc["files"]["watch.py"]["divergence"])
        self.assertEqual(runtime_manifest.sha256_file(self.runtime / "watch.py"),
                         doc["files"]["watch.py"]["sha256"])
        self.assertEqual(0, self.run_check()[0])

    def test_green_when_deployed_bytes_are_an_uncommitted_edit(self) -> None:
        # The deploy-then-commit window: the live bytes match the working tree but
        # not yet HEAD. That stays GREEN, as it did before, rather than becoming
        # a new RED.
        self.source(SOURCE_WATCH, "print('v1')\n")
        self.commit()
        self.source(SOURCE_WATCH, "print('v2')\n")
        self.deploy("watch.py", "print('v2')\n")
        self.record_doc({"watch.py": {"sha256": runtime_manifest.sha256_file(self.runtime / "watch.py"),
                                      "source": SOURCE_WATCH, "divergence": None}})
        code, lines = self.run_check()
        self.assertEqual(0, code, lines)

    def test_red_when_deployed_matches_neither_head_nor_worktree(self) -> None:
        self.source(SOURCE_WATCH, "print('v1')\n")
        self.commit()
        self.source(SOURCE_WATCH, "print('v2')\n")
        self.deploy("watch.py", "print('v3-deployed')\n")
        self.record_doc({"watch.py": {"sha256": runtime_manifest.sha256_file(self.runtime / "watch.py"),
                                      "source": SOURCE_WATCH, "divergence": None}})
        code, lines = self.run_check()
        self.assertEqual(1, code, lines)
        self.assertTrue(any("no recorded divergence" in line for line in lines), lines)

    def test_green_when_divergence_is_declared(self) -> None:
        self.source(SOURCE_WATCH, "print('source')\n")
        self.deploy("watch.py", "print('deployed, path line adjusted')\n")
        self.commit()
        self.record_doc({"watch.py": {"sha256": runtime_manifest.sha256_file(self.runtime / "watch.py"),
                                      "source": SOURCE_WATCH,
                                      "divergence": "path line adjusted for body/runtime/"}})
        code, lines = self.run_check()
        self.assertEqual(0, code, lines)

    def test_red_when_deployed_file_is_unrecorded_and_backups_ignored(self) -> None:
        self.deploy("watch.py", "print('v1')\n")
        self.deploy("server.py", "print('s')\n")
        self.deploy("watch.py.pre-deploy-20261014-1136Z", "print('old')\n")
        self.record_doc({"watch.py": {"sha256": runtime_manifest.sha256_file(self.runtime / "watch.py"),
                                      "source": None, "divergence": None}})
        code, lines = self.run_check()
        self.assertEqual(1, code, lines)
        self.assertTrue(any("server.py: deployed but unrecorded" in line for line in lines), lines)
        self.assertFalse(any("pre-deploy" in line for line in lines), lines)

    def test_unknown_without_manifest_or_site(self) -> None:
        code, lines = self.run_check()
        self.assertEqual(2, code, lines)
        self.assertEqual(["UNKNOWN"], [line.split()[0] for line in lines])

    def test_schema1_string_hashes_still_read(self) -> None:
        self.deploy("watch.py", "print('v1')\n")
        self.record_doc({"watch.py": runtime_manifest.sha256_file(self.runtime / "watch.py")})
        code, lines = self.run_check()
        self.assertEqual(0, code, lines)
        self.assertTrue(any("site-local" in line for line in lines), lines)

    def test_record_writes_hashes_and_preserves_unknown_keys(self) -> None:
        self.source(SOURCE_WATCH, "print('v1')\n")
        self.deploy("watch.py", "print('v1')\n")
        self.commit()
        self.record_doc({}, verification="old")
        code, lines = runtime_manifest.record(
            self.site, self.repo, None, {"watch.py": SOURCE_WATCH}, {}, "new")
        self.assertEqual(0, code, lines)
        doc = json.loads(self.manifest.read_text(encoding="utf-8"))
        self.assertEqual(2, doc["schema"])
        self.assertEqual("new", doc["verification"])
        self.assertEqual("../health/runtime-release.json", doc["core_pin_source"])
        self.assertEqual(runtime_manifest.sha256_file(self.runtime / "watch.py"),
                         doc["files"]["watch.py"]["sha256"])
        self.assertEqual(SOURCE_WATCH, doc["files"]["watch.py"]["source"])
        self.assertIsNone(doc["files"]["watch.py"]["divergence"])
        self.assertEqual(subprocess.run(["git", "-C", str(self.repo), "rev-parse", "HEAD"],
                                        capture_output=True, text=True).stdout.strip(),
                         doc["source_commit"])
        self.assertEqual(0, self.run_check()[0])
        # A later record without --source keeps the declared provenance.
        code, lines = runtime_manifest.record(self.site, self.repo, None, {}, {}, None)
        self.assertEqual(0, code, lines)
        doc = json.loads(self.manifest.read_text(encoding="utf-8"))
        self.assertEqual(SOURCE_WATCH, doc["files"]["watch.py"]["source"])

    def test_record_refuses_undeclared_divergence(self) -> None:
        self.source(SOURCE_WATCH, "print('source')\n")
        self.deploy("watch.py", "print('deployed')\n")
        self.commit()
        code, lines = runtime_manifest.record(
            self.site, self.repo, None, {"watch.py": SOURCE_WATCH}, {}, None)
        self.assertEqual(1, code, lines)
        self.assertFalse(self.manifest.exists())
        code, lines = runtime_manifest.record(
            self.site, self.repo, None, {"watch.py": SOURCE_WATCH},
            {"watch.py": "path line adjusted"}, None)
        self.assertEqual(0, code, lines)
        doc = json.loads(self.manifest.read_text(encoding="utf-8"))
        self.assertEqual("path line adjusted", doc["files"]["watch.py"]["divergence"])

    def test_record_refuses_missing_deployed_file(self) -> None:
        code, lines = runtime_manifest.record(self.site, self.repo, ["absent.py"], {}, {}, None)
        self.assertEqual(1, code, lines)
        self.assertFalse(self.manifest.exists())

    def test_record_keeps_recorded_files_not_named_in_targets(self) -> None:
        self.deploy("watch.py", "print('v1')\n")
        self.deploy("server.py", "print('s')\n")
        self.record_doc({"server.py": {"sha256": runtime_manifest.sha256_file(self.runtime / "server.py"),
                                       "source": None, "divergence": None}})
        code, lines = runtime_manifest.record(self.site, self.repo, ["watch.py"], {}, {}, None)
        self.assertEqual(0, code, lines)
        doc = json.loads(self.manifest.read_text(encoding="utf-8"))
        self.assertEqual(["server.py", "watch.py"], sorted(doc["files"]))

    def test_record_preserves_the_superseded_manifest(self) -> None:
        # 2026-10-15: the 15:16:55Z widening replaced a four-file record with a
        # seven-file one and kept no copy, so the previous coverage list
        # survived only in chat evidence.
        self.deploy("watch.py", "print('v1')\n")
        code, lines = runtime_manifest.record(self.site, self.repo, None, {}, {}, None)
        self.assertEqual(0, code, lines)
        self.assertEqual([], sorted(self.manifest.parent.glob("runtime-manifest.json.pre-record-*")),
                         lines)
        first = self.manifest.read_text(encoding="utf-8")
        code, lines = runtime_manifest.record(self.site, self.repo, None, {}, {}, None)
        self.assertEqual(0, code, lines)
        backups = sorted(self.manifest.parent.glob("runtime-manifest.json.pre-record-*"))
        self.assertEqual(1, len(backups), lines)
        self.assertEqual(first, backups[0].read_text(encoding="utf-8"))
        self.assertTrue(any("preserved the superseded record" in line for line in lines), lines)
        self.assertEqual(0, self.run_check()[0])

    def unit_case(self, offset_s: float | None) -> tuple[int, list[str]]:
        self.deploy("watch.py", "print('v1')\n")
        self.record_doc({"watch.py": {"sha256": runtime_manifest.sha256_file(self.runtime / "watch.py"),
                                      "source": None, "divergence": None,
                                      "unit": "android-body-perception.service"}})
        written = (self.runtime / "watch.py").stat().st_mtime
        started = None if offset_s is None else datetime.datetime.fromtimestamp(
            written + offset_s, tz=datetime.timezone.utc)
        return runtime_manifest.check(self.site, self.repo, unit_entered_fn=lambda unit: started)

    def test_red_when_unit_started_before_the_bytes_were_written(self) -> None:
        # The 2026-10-11 failure: deployed bytes on disk, process still running old code.
        code, lines = self.unit_case(-3600)
        self.assertEqual(1, code, lines)
        self.assertTrue(any("running older code" in line for line in lines), lines)

    def test_green_when_unit_started_after_the_bytes_were_written(self) -> None:
        code, lines = self.unit_case(+5)
        self.assertEqual(0, code, lines)
        self.assertTrue(any("android-body-perception.service started" in line for line in lines), lines)

    def test_unknown_when_unit_start_time_is_unavailable(self) -> None:
        code, lines = self.unit_case(None)
        self.assertEqual(2, code, lines)
        self.assertTrue(any("cannot prove the process runs the recorded bytes" in line
                            for line in lines), lines)

    def test_unit_entered_falls_back_to_the_exec_start_of_a_completed_oneshot(self) -> None:
        # systemd clears ActiveEnterTimestamp when a Type=oneshot invocation
        # finishes, so android-body-spool-read.service read UNKNOWN forever
        # (2026-10-14) although its process had run the recorded bytes.
        with stub_systemctl(ActiveEnterTimestamp="",
                            ExecMainStartTimestamp="Wed 2026-10-14 19:58:34 UTC"):
            self.assertEqual(
                datetime.datetime(2026, 10, 14, 19, 58, 34, tzinfo=datetime.timezone.utc),
                runtime_manifest.unit_entered("android-body-spool-read.service"))

    def test_unit_entered_prefers_the_exec_start_over_the_active_period(self) -> None:
        # A main process that restarts inside one active period (Restart=on-failure)
        # moves ExecMainStartTimestamp without moving ActiveEnterTimestamp, so the
        # exec time is the tighter fact.
        with stub_systemctl(ActiveEnterTimestamp="Wed 2026-10-14 14:00:00 UTC",
                            ExecMainStartTimestamp="Wed 2026-10-14 19:00:00 UTC"):
            self.assertEqual(
                datetime.datetime(2026, 10, 14, 19, 0, 0, tzinfo=datetime.timezone.utc),
                runtime_manifest.unit_entered("android-body-perception.service"))

    def test_unit_entered_uses_the_active_period_when_the_exec_start_is_empty(self) -> None:
        with stub_systemctl(ActiveEnterTimestamp="Wed 2026-10-14 14:00:00 UTC",
                            ExecMainStartTimestamp=""):
            self.assertEqual(
                datetime.datetime(2026, 10, 14, 14, 0, 0, tzinfo=datetime.timezone.utc),
                runtime_manifest.unit_entered("android-body-perception.service"))

    def test_unit_entered_is_unknown_when_neither_timestamp_is_readable(self) -> None:
        with stub_systemctl(ActiveEnterTimestamp="", ExecMainStartTimestamp=""):
            self.assertIsNone(runtime_manifest.unit_entered("android-body-spool-read.service"))

    def test_green_when_a_completed_oneshot_left_only_the_exec_start(self) -> None:
        # The observed defect end to end: check() returned 2 (UNKNOWN) for a
        # publication timer whose ActiveEnterTimestamp systemd had cleared.
        self.deploy("watch.py", "print('v1')\n")
        written = (self.runtime / "watch.py").stat().st_mtime
        started = datetime.datetime.fromtimestamp(written + 60, tz=datetime.timezone.utc)
        self.record_doc({"watch.py": {
            "sha256": runtime_manifest.sha256_file(self.runtime / "watch.py"),
            "source": None, "divergence": None,
            "unit": "android-body-spool-read.service"}})
        with stub_systemctl(ActiveEnterTimestamp="",
                            ExecMainStartTimestamp=started.strftime("%a %Y-%m-%d %H:%M:%S UTC")):
            code, lines = runtime_manifest.check(self.site, self.repo)
        self.assertEqual(0, code, lines)
        self.assertTrue(any("android-body-spool-read.service started" in line for line in lines),
                        lines)

    def test_record_writes_and_preserves_the_declared_unit(self) -> None:
        self.deploy("watch.py", "print('v1')\n")
        code, lines = runtime_manifest.record(
            self.site, self.repo, None, {}, {}, None,
            {"watch.py": "android-body-perception.service"})
        self.assertEqual(0, code, lines)
        doc = json.loads(self.manifest.read_text(encoding="utf-8"))
        self.assertEqual("android-body-perception.service", doc["files"]["watch.py"]["unit"])
        code, lines = runtime_manifest.record(self.site, self.repo, None, {}, {}, None)
        self.assertEqual(0, code, lines)
        doc = json.loads(self.manifest.read_text(encoding="utf-8"))
        self.assertEqual("android-body-perception.service", doc["files"]["watch.py"]["unit"])

    def test_red_when_record_has_no_sha256(self) -> None:
        self.deploy("watch.py", "print('v1')\n")
        self.record_doc({"watch.py": {"sha256": None, "source": None, "divergence": None}})
        code, lines = self.run_check()
        self.assertEqual(1, code, lines)
        self.assertTrue(any("record has no sha256" in line for line in lines), lines)

    def test_red_when_recorded_file_is_not_deployed(self) -> None:
        self.deploy("server.py", "print('s')\n")
        self.record_doc({"watch.py": {"sha256": "0" * 64, "source": None, "divergence": None},
                         "server.py": {"sha256": runtime_manifest.sha256_file(self.runtime / "server.py"),
                                       "source": None, "divergence": None}})
        code, lines = self.run_check()
        self.assertEqual(1, code, lines)
        self.assertTrue(any("recorded but not deployed" in line for line in lines), lines)

    def test_red_when_recorded_source_is_missing(self) -> None:
        self.deploy("watch.py", "print('v1')\n")
        self.record_doc({"watch.py": {"sha256": runtime_manifest.sha256_file(self.runtime / "watch.py"),
                                      "source": SOURCE_WATCH, "divergence": None}})
        code, lines = self.run_check()
        self.assertEqual(1, code, lines)
        self.assertTrue(any("recorded source" in line and "missing" in line for line in lines), lines)

    def test_red_when_recorded_source_escapes_the_repository(self) -> None:
        self.deploy("watch.py", "print('v1')\n")
        write(Path(self.tmp.name) / "outside.py", "print('v1')\n")
        self.record_doc({"watch.py": {"sha256": runtime_manifest.sha256_file(self.runtime / "watch.py"),
                                      "source": "../outside.py", "divergence": None}})
        code, lines = self.run_check()
        self.assertEqual(1, code, lines)
        self.assertTrue(any("outside the repository" in line for line in lines), lines)
        code, lines = runtime_manifest.record(
            self.site, self.repo, None, {"watch.py": "../outside.py"}, {}, None)
        self.assertEqual(1, code, lines)

    def test_unknown_when_manifest_key_is_not_a_bare_name(self) -> None:
        # A key with a separator would make check hash and GREEN bytes outside body/runtime.
        self.deploy("watch.py", "print('v1')\n")
        write(self.site / "body" / "outside.py", "print('v1')\n")
        self.record_doc({"../outside.py": {"sha256": runtime_manifest.sha256_file(self.runtime / "watch.py"),
                                           "source": None, "divergence": None}})
        code, lines = self.run_check()
        self.assertEqual(2, code, lines)
        self.assertTrue(any("not a bare file name" in line for line in lines), lines)

    def test_unknown_when_a_field_is_not_a_string(self) -> None:
        self.deploy("watch.py", "print('v1')\n")
        self.record_doc({"watch.py": {"sha256": runtime_manifest.sha256_file(self.runtime / "watch.py"),
                                      "source": [], "divergence": None, "unit": []}})
        code, lines = self.run_check()
        self.assertEqual(2, code, lines)
        self.assertTrue(any("is not a string" in line for line in lines), lines)

    def test_record_refuses_an_empty_runtime(self) -> None:
        code, lines = runtime_manifest.record(self.site, self.repo, None, {}, {}, None)
        self.assertEqual(1, code, lines)
        self.assertFalse(self.manifest.exists())

    def test_record_writes_through_a_symlinked_manifest(self) -> None:
        self.deploy("watch.py", "print('v1')\n")
        shared = write(self.site / "body" / "shared-manifest.json", json.dumps({"files": {}}))
        self.manifest.symlink_to(shared)
        code, lines = runtime_manifest.record(self.site, self.repo, None, {}, {}, None)
        self.assertEqual(0, code, lines)
        self.assertTrue(self.manifest.is_symlink(), lines)
        self.assertIn("watch.py", json.loads(shared.read_text(encoding="utf-8"))["files"])

    def test_record_preserves_per_file_extra_keys(self) -> None:
        self.deploy("watch.py", "print('v1')\n")
        self.record_doc({"watch.py": {"sha256": runtime_manifest.sha256_file(self.runtime / "watch.py"),
                                      "source": None, "divergence": None,
                                      "note": "owned by deploy 2026-10-14"}})
        code, lines = runtime_manifest.record(self.site, self.repo, None, {}, {}, None)
        self.assertEqual(0, code, lines)
        doc = json.loads(self.manifest.read_text(encoding="utf-8"))
        self.assertEqual("owned by deploy 2026-10-14", doc["files"]["watch.py"]["note"])

    def test_unit_timestamp_in_a_non_utc_local_zone_is_converted(self) -> None:
        # systemd prints local time; reading it as UTC hides a unit that started early.
        old_tz = os.environ.get("TZ")
        try:
            os.environ["TZ"] = "Asia/Tokyo"
            time.tzset()
            if "JST" not in time.tzname:
                self.skipTest("Asia/Tokyo tzdata unavailable")
            parsed = runtime_manifest.parse_unit_timestamp("Wed 2026-10-14 14:57:20 JST")
        finally:
            if old_tz is None:
                os.environ.pop("TZ", None)
            else:
                os.environ["TZ"] = old_tz
            time.tzset()
        self.assertEqual(datetime.datetime(2026, 10, 14, 5, 57, 20, tzinfo=datetime.timezone.utc),
                         parsed)

    def test_unit_timestamp_in_an_unknown_zone_is_unknown(self) -> None:
        old_tz = os.environ.get("TZ")
        try:
            os.environ["TZ"] = "UTC"
            time.tzset()
            parsed = runtime_manifest.parse_unit_timestamp("Wed 2026-10-14 14:57:20 JST")
            utc = runtime_manifest.parse_unit_timestamp("Wed 2026-10-14 14:57:20 UTC")
        finally:
            if old_tz is None:
                os.environ.pop("TZ", None)
            else:
                os.environ["TZ"] = old_tz
            time.tzset()
        self.assertIsNone(parsed)
        self.assertEqual(datetime.datetime(2026, 10, 14, 14, 57, 20, tzinfo=datetime.timezone.utc),
                         utc)

    def test_cli_check_and_record_end_to_end(self) -> None:
        self.deploy("watch.py", "print('v1')\n")
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(0, runtime_manifest.main(["record", "--repo", str(self.repo)]))
            self.assertTrue(self.manifest.is_file())
            self.assertEqual(0, runtime_manifest.main(["check", "--repo", str(self.repo)]))
            self.assertEqual(1, runtime_manifest.main(
                ["record", "--repo", str(self.repo), "--file", "absent.py"]))
            self.assertEqual(2, runtime_manifest.main(
                ["check", "--repo", str(self.repo), "--site", str(self.repo / "no-site")]))


if __name__ == "__main__":
    unittest.main()
