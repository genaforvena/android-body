#!/usr/bin/env python3
# SPDX-License-Identifier: CC0-1.0
"""Bounded read-only probe runner — minimal-substrate first experiment.

A retained trivial text script for the minimal-substrate investigation: a
fixed allowlist of harmless read-only probes against the owned Note3, each
record labeled with its execution context. PROBES is the whole execution
surface — no arbitrary command execution, no device mutation except one
bounded app-private scratch file that is deleted again, no radio/camera/mic/
location, no downloaded code.

Contexts (discriminator bar 4):
  host    adb shell (uid 2000) — never APK-identity evidence
  run-as  org.androidbody app uid via debuggable run-as — never APK-uid
          evidence; UID/domain equality does not establish equal authority
  apk-uid observation produced inside the org.androidbody APK process: the
          session-start in-process identity probe (Process.myUid() +
          /proc/self/status), delivered through existing text delivery and
          retained in the durable consumer spool

apk-identity captures that retained in-process observation. apk-dex records
host-side installed-byte correlation (explicitly NOT execution evidence).
scratch-rerun writes one fixed trivial text script to app-private scratch
via run-as, re-executes it later, retains source/hash/provenance and deletes
it again (bounded storage teardown). host-interrupt observes a SIGINT-killed
child with a truthful receipt. runas-denied observes a denied read and
retains stderr; exit0 with an expected denial is not reported as failure,
and an unexpected success is flagged.

Bounds (env-overridable; tests rely on this):
  MINIMAL_SUBSTRATE_TIMEOUT_S     per-command timeout in seconds; on expiry
                                  the child is killed and the timeout is
                                  recorded truthfully (default 10)
  MINIMAL_SUBSTRATE_MAX_BYTES     total output cap in bytes (default 65536)
  MINIMAL_SUBSTRATE_MAX_LINE_BYTES per-line output cap in bytes (default
                                  1024, matching the text-delivery per-line
                                  limit)
  MINIMAL_SUBSTRATE_KEEP          retention: newest N artifact files
                                  (default 20; N<=0 keeps none)
  MINIMAL_SUBSTRATE_SPOOL         test override: consumer spool copy path
  MINIMAL_SUBSTRATE_APK_PATH      test override: local apk instead of pull

Usage: python3 probe.py [host-identity|host-environment|host-clock|
       runas-identity|runas-status|runas-selinux|runas-denied|host-interrupt|
       apk-identity|apk-dex|scratch-rerun|all]
Exit:  0 every probe reached its expected outcome · 1 any did not · 2 usage
"""

import hashlib
import io
import json
import os
import re
import signal
import subprocess
import sys
import tempfile
import time
import zipfile
from datetime import datetime, timezone
from pathlib import Path

ARTIFACT_DIR = Path(__file__).resolve().parent / "artifacts"
SITE_DIR = Path(__file__).resolve().parents[2] / ".mishe-tauftauf"
SPOOL_PATH = SITE_DIR / "body" / "queues" / "note3.observations.log"

SPOOL_MAX_BYTES = 16 * 1024 * 1024
APK_MAX_BYTES = 512 * 1024

SCRATCH_PATH = "/data/data/org.androidbody/files/minimal-substrate-probe.sh"
SCRATCH_SCRIPT = (
    "# minimal-substrate trivial probe script (host-authored, fixed text)\n"
    "echo \"probe script uid=$(id -u) cwd=$PWD\"\n"
)

HOST = "host"
RUNAS = "run-as"
APKUID = "apk-uid"

PROBES = {
    "host-identity":    {"args": ["shell", "id"], "context": HOST, "expect": "ok", "identity": True},
    "host-environment": {"args": ["shell", "dumpsys", "sensorservice"], "context": HOST, "expect": "ok"},
    "host-clock":       {"args": ["shell", "date", "-u", "+%Y-%m-%dT%H:%M:%SZ"], "context": HOST, "expect": "ok"},
    "runas-identity":   {"args": ["shell", "run-as", "org.androidbody", "id"], "context": RUNAS, "expect": "ok", "identity": True},
    "runas-status":     {"args": ["shell", "run-as", "org.androidbody", "cat", "/proc/self/status"], "context": RUNAS, "expect": "ok", "identity": True},
    "runas-selinux":    {"args": ["shell", "run-as", "org.androidbody", "cat", "/proc/self/attr/current"], "context": RUNAS, "expect": "ok"},
    "runas-denied":     {"args": ["shell", "run-as", "org.androidbody", "cat", "/data/system/packages.list"], "context": RUNAS, "expect": "denied"},
    "host-interrupt":   {"args": ["shell", "sleep", "30"], "context": HOST, "expect": "interrupted", "interrupt": True},
    "apk-identity":     {"context": APKUID, "expect": "ok", "apk": True},
    "apk-dex":          {"context": HOST, "expect": "ok", "apk_dex": True},
    "scratch-rerun":    {"context": RUNAS, "expect": "ok", "scratch": True},
}

TIMEOUT_S = max(0.1, float(os.environ.get("MINIMAL_SUBSTRATE_TIMEOUT_S", "10")))
MAX_BYTES = max(1, int(os.environ.get("MINIMAL_SUBSTRATE_MAX_BYTES", str(64 * 1024))))
MAX_LINE_BYTES = max(1, int(os.environ.get("MINIMAL_SUBSTRATE_MAX_LINE_BYTES", "1024")))
KEEP = max(0, int(os.environ.get("MINIMAL_SUBSTRATE_KEEP", "20")))


def _utcnow():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _cap_line(text):
    """Per-line byte cap matching the text-delivery per-line limit."""
    encoded = text.encode("utf-8", errors="replace")
    if len(encoded) <= MAX_LINE_BYTES:
        return text
    truncated = encoded[:MAX_LINE_BYTES].decode("utf-8", errors="replace")
    return truncated + "...[line truncated at {0} bytes]".format(MAX_LINE_BYTES)


def _cap(text):
    """Per-line then total byte-bound truncation of retained output."""
    capped = "\n".join(_cap_line(line) for line in text.split("\n"))
    encoded = capped.encode("utf-8", errors="replace")
    if len(encoded) <= MAX_BYTES:
        return capped
    truncated = encoded[:MAX_BYTES].decode("utf-8", errors="replace")
    return truncated + "\n...[truncated at {0} bytes]".format(MAX_BYTES)


def _identity_fields(stdout):
    """Parse uid/groups/SELinux domain from `id` or /proc/self/status output."""
    fields = {}
    uid = re.search(r"\buid=(\d+)", stdout)
    gid = re.search(r"\bgid=(\d+)", stdout)
    groups = re.search(r"\bgroups=([0-9 ]+)", stdout)
    context = re.search(r"\bcontext=(\S+)", stdout)
    if uid:
        fields["uid"] = uid.group(1)
    if gid:
        fields["gid"] = gid.group(1)
    if groups:
        fields["groups"] = groups.group(1).strip()
    if context:
        fields["context"] = context.group(1)
    if not fields:
        for line in stdout.splitlines():
            if line.startswith("Groups:"):
                value = line.split(":", 1)[1].strip()
                if value:
                    fields["groups"] = value
    return fields or None


def _new_record(name, spec, command):
    return {
        "name": name,
        "context": spec["context"],
        "command": command,
        "expect": spec["expect"],
        "started_utc": _utcnow(),
        "duration_s": None,
        "outcome": None,
        "returncode": None,
        "output": None,
    }


def _adbrun(args, input_text=None):
    """Run one fixed adb command; return a truthful result dict.

    run-as can exit 0 while reporting failure (observed: "corrupt
    installation"); exit0 is never recorded as success for such a command.
    """
    try:
        kwargs = dict(capture_output=True, text=True, errors="replace", timeout=TIMEOUT_S)
        if input_text is None:
            proc = subprocess.run(["adb", *args], **kwargs)
        else:
            proc = subprocess.run(["adb", *args], input=input_text, **kwargs)
        note = None
        if proc.returncode == 0 and "corrupt installation" in ((proc.stdout or "") + (proc.stderr or "")):
            note = "[exit0-failure] run-as reported corrupt installation; exit0 is not success"
        return {"rc": proc.returncode, "stdout": proc.stdout or "",
                "stderr": proc.stderr or "", "note": note}
    except subprocess.TimeoutExpired:
        return {"rc": None, "stdout": "", "stderr": "",
                "note": "timeout after {0}s; child killed; no retry".format(TIMEOUT_S)}
    except OSError as exc:
        return {"rc": None, "stdout": "", "stderr": "", "note": "probe execution failed: {0}".format(exc)}

def _compose_output(res):
    output = res["stdout"]
    if res["stderr"].strip():
        output += "\n[stderr] " + res["stderr"].strip()
    if res["note"]:
        output += "\n" + res["note"] if output else res["note"]
    return output


def _step_ok(res):
    """A step succeeded only with rc 0 and no reported failure (exit0 != success)."""
    return res["rc"] == 0 and not (res["note"] and "exit0-failure" in res["note"])


def _run_simple(name):
    spec = PROBES[name]
    args = ["adb", *spec["args"]]
    started = time.monotonic()
    record = _new_record(name, spec, " ".join(args))
    res = _adbrun(spec["args"])
    record["duration_s"] = round(time.monotonic() - started, 3)
    record["returncode"] = res["rc"]
    output = _compose_output(res)
    if res["note"] and "timeout" in res["note"]:
        record["outcome"] = "timeout"
    elif res["rc"] == 0 and res["note"]:
        record["outcome"] = "error"
    elif res["rc"] == 0:
        record["outcome"] = "ok"
    elif spec["expect"] == "denied":
        record["outcome"] = "denied"
    else:
        record["outcome"] = "error"
    if spec["expect"] == "denied" and res["rc"] == 0:
        output += "\n[unexpected] denial expected but command succeeded"
    if spec.get("identity"):
        record["identity"] = _identity_fields(res["stdout"])
    record["output"] = _cap(output)
    return record


def _run_interrupt(name):
    spec = PROBES[name]
    args = ["adb", *spec["args"]]
    started = time.monotonic()
    record = _new_record(name, spec, " ".join(args))
    try:
        proc = subprocess.Popen(
            args, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, errors="replace",
        )
    except OSError as exc:
        record["duration_s"] = round(time.monotonic() - started, 3)
        record["outcome"] = "error"
        record["output"] = "probe execution failed: {0}".format(exc)
        return record
    time.sleep(min(0.5, TIMEOUT_S / 2.0))
    if proc.poll() is None:
        proc.send_signal(signal.SIGINT)
    try:
        out, err = proc.communicate(timeout=TIMEOUT_S)
        rc = proc.returncode
    except subprocess.TimeoutExpired:
        proc.kill()
        out, err = proc.communicate()
        rc = proc.returncode
    record["duration_s"] = round(time.monotonic() - started, 3)
    record["returncode"] = rc
    record["signal_sent"] = "SIGINT"
    if rc is not None and rc < 0:
        record["outcome"] = "interrupted"
    elif rc == 0:
        record["outcome"] = "ok"
    else:
        record["outcome"] = "error"
    output = out or ""
    if err.strip():
        output += "\n[stderr] " + err.strip()
    if record["outcome"] == "interrupted":
        output += ("\n[note] local child killed by SIGINT mid-run; no retry; "
                   "remote command may outlive the adb client")
    record["output"] = _cap(output)
    return record

def _scratch_write_arg():
    """Fixed sh -c argument writing SCRATCH_SCRIPT via echo (no stdin pipe).
    The entire echo+redirect sequence is wrapped as a single device-shell
    token so the redirects evaluate inside the run-as context, not the
    device shell. The inner command's exit code is echoed as RC=N for
    explicit capture. Uses the echo builtin: this device has no printf
    applet and its sh (toybox ash) has no printf builtin either
    (verified on-device 2026-10-12: `type printf` silent, echo a builtin).
    """
    parts = []
    for i, line in enumerate(SCRATCH_SCRIPT.splitlines()):
        quoted = "'" + line.replace("'", "'\\''") + "'"
        parts.append("echo {0} {1} {2}".format(quoted, ">" if i == 0 else ">>", SCRATCH_PATH))
    cmd = " && ".join(parts) + "; echo RC=$?"
    # Wrap in single quotes so the device shell passes the whole command
    # (including redirects) as one argument to sh -c
    return "'" + cmd.replace("'", "'\\''") + "'"


def _run_scratch(name):
    spec = PROBES[name]
    started = time.monotonic()
    command = ("adb shell run-as org.androidbody sh -c 'echo ... > {0}; echo RC=$?' (write); "
               "adb shell run-as org.androidbody sh {0} (run 1 and run 2); "
               "adb shell run-as org.androidbody rm {0} (delete); "
               "adb shell run-as org.androidbody ls {0} (verify absent)").format(SCRATCH_PATH)
    record = _new_record(name, spec, command)
    write = _adbrun(["shell", "run-as", "org.androidbody", "sh", "-c", _scratch_write_arg()])
    # Parse inner rc from stdout (adb exit codes are unreliable on this device)
    write_rc = None
    for line in write["stdout"].splitlines():
        if line.startswith("RC="):
            try:
                write_rc = int(line[3:])
            except ValueError:
                pass
    if write_rc is None:
        write_rc = write["rc"]  # fallback to adb rc if inner rc not found
    write_ok = (write_rc == 0 and not (write["note"] and "exit0-failure" in write["note"]))
    run1 = _adbrun(["shell", "run-as", "org.androidbody", "sh", SCRATCH_PATH])
    run2 = _adbrun(["shell", "run-as", "org.androidbody", "sh", SCRATCH_PATH])
    delete = _adbrun(["shell", "run-as", "org.androidbody", "rm", SCRATCH_PATH])
    verify = _adbrun(["shell", "run-as", "org.androidbody", "ls", SCRATCH_PATH])
    record["duration_s"] = round(time.monotonic() - started, 3)
    record["script"] = SCRATCH_SCRIPT
    record["script_sha256"] = hashlib.sha256(SCRATCH_SCRIPT.encode("utf-8")).hexdigest()
    record["script_path"] = SCRATCH_PATH
    record["write_returncode"] = write_rc
    record["run1_output"] = _cap(_compose_output(run1))
    record["run2_output"] = _cap(_compose_output(run2))
    record["rerun_matches"] = (_step_ok(run1) and _step_ok(run2)
                               and run1["stdout"] == run2["stdout"])
    record["delete_returncode"] = delete["rc"]
    if verify["rc"] is None:
        record["verify_outcome"] = "timeout"
    elif verify["note"] and "exit0-failure" in verify["note"]:
        record["verify_outcome"] = "error"
    elif verify["rc"] == 0:
        record["verify_outcome"] = "ok"
    else:
        record["verify_outcome"] = "denied"
    ok = (write_ok and _step_ok(run1) and _step_ok(run2)
          and record["rerun_matches"] and _step_ok(delete)
          and record["verify_outcome"] == "denied")
    record["outcome"] = "ok" if ok else "error"
    record["output"] = ("write rc={0}; run1 rc={1}; run2 rc={2}; rerun matches={3}; "
                        "delete rc={4}; verify={5}").format(
        write_rc, run1["rc"], run2["rc"], record["rerun_matches"],
        delete["rc"], record["verify_outcome"])
    record["note"] = ("device-side persisted trivial script rerun; run-as context, "
                      "NOT apk-uid evidence; script deleted after experiment "
                      "(bounded storage teardown)")
    return record


def _run_apk_identity(name):
    spec = PROBES[name]
    path = Path(os.environ.get("MINIMAL_SUBSTRATE_SPOOL", str(SPOOL_PATH)))
    started = time.monotonic()
    record = _new_record(name, spec, "read durable consumer spool copy (existing text delivery): " + str(path))
    try:
        if not path.exists():
            raise OSError("spool copy not found")
        if path.stat().st_size > SPOOL_MAX_BYTES:
            record["duration_s"] = round(time.monotonic() - started, 3)
            record["outcome"] = "error"
            record["output"] = "spool exceeds read bound {0} bytes".format(SPOOL_MAX_BYTES)
            return record
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        record["duration_s"] = round(time.monotonic() - started, 3)
        record["outcome"] = "error"
        record["output"] = "spool read failed: {0}".format(exc)
        return record
    record["duration_s"] = round(time.monotonic() - started, 3)
    lines = [line for line in text.splitlines() if "probe identity uid=" in line]
    if not lines:
        record["outcome"] = "error"
        record["output"] = "no probe identity event found in spool"
        return record
    line = lines[-1]
    record["output"] = _cap(line)
    record["source"] = ("durable spool copy of phone-emitted event; produced inside the "
                        "org.androidbody APK process at session start")
    record["captured_utc"] = _utcnow()
    parts = line.split(None, 2)
    if parts and parts[0].isdigit():
        record["event_id"] = int(parts[0])
    if len(parts) > 1 and parts[1].isdigit():
        record["phone_timestamp_utc"] = datetime.fromtimestamp(
            int(parts[1]), tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    record["outcome"] = "ok"
    return record


def _run_apk_dex(name):
    spec = PROBES[name]
    started = time.monotonic()
    record = _new_record(name, spec,
                         "host-side installed-byte correlation: pull installed base.apk, search "
                         "classes*.dex for ExecutionProbe and the identity format string "
                         "(correlation only, NOT execution evidence)")
    tmp_path = None
    try:
        src = os.environ.get("MINIMAL_SUBSTRATE_APK_PATH")
        if src:
            apk_path = Path(src)
        else:
            fd, tmp_path = tempfile.mkstemp(suffix=".apk")
            os.close(fd)
            pull = subprocess.run(
                ["adb", "pull", "/data/app/org.androidbody-1/base.apk", tmp_path],
                capture_output=True, text=True, errors="replace", timeout=TIMEOUT_S,
            )
            if pull.returncode != 0:
                record["duration_s"] = round(time.monotonic() - started, 3)
                record["outcome"] = "error"
                record["output"] = "installed apk pull failed: " + (pull.stderr or "").strip()
                return record
            apk_path = Path(tmp_path)
        data = apk_path.read_bytes()
        if len(data) > APK_MAX_BYTES:
            record["duration_s"] = round(time.monotonic() - started, 3)
            record["outcome"] = "error"
            record["output"] = "installed apk exceeds read bound {0} bytes".format(APK_MAX_BYTES)
            return record
        record["apk_size"] = len(data)
        record["apk_sha256"] = hashlib.sha256(data).hexdigest()
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            dex_names = sorted(n for n in zf.namelist() if n.endswith(".dex"))
            probe_class = False
            format_string = False
            for dex_name in dex_names:
                blob = zf.read(dex_name)
                if b"ExecutionProbe" in blob:
                    probe_class = True
                if b"probe identity uid=" in blob:
                    format_string = True
        record["dex_files"] = dex_names
        record["contains_execution_probe_class"] = probe_class
        record["contains_identity_format_string"] = format_string
        record["duration_s"] = round(time.monotonic() - started, 3)
        record["outcome"] = "ok"
        record["output"] = ("installed apk sha256={0} bytes={1} dex_files={2} "
                            "ExecutionProbe class={3} identity format string={4}".format(
                                record["apk_sha256"][:16] + "...", record["apk_size"],
                                len(dex_names), probe_class, format_string))
        record["note"] = "host-side installed-byte correlation; not execution evidence"
    except (OSError, zipfile.BadZipFile) as exc:
        record["duration_s"] = round(time.monotonic() - started, 3)
        record["outcome"] = "error"
        record["output"] = "installed apk inspection failed: {0}".format(exc)
    finally:
        if tmp_path:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
    return record


def run_probe(name):
    spec = PROBES[name]
    if spec.get("interrupt"):
        return _run_interrupt(name)
    if spec.get("scratch"):
        return _run_scratch(name)
    if spec.get("apk"):
        return _run_apk_identity(name)
    if spec.get("apk_dex"):
        return _run_apk_dex(name)
    return _run_simple(name)


def write_artifact(records, argv):
    ARTIFACT_DIR.mkdir(exist_ok=True)
    outcome = "ok" if all(r["outcome"] == r["expect"] for r in records) else "partial"
    payload = {
        "schema": 2,
        "runner": "experiments/minimal-substrate/probe.py",
        "started_utc": records[0]["started_utc"] if records else _utcnow(),
        "finished_utc": _utcnow(),
        "argv": argv,
        "outcome": outcome,
        "bounds": {"timeout_s": TIMEOUT_S, "max_bytes": MAX_BYTES,
                   "max_line_bytes": MAX_LINE_BYTES, "keep": KEEP},
        "probes": records,
    }
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    path = ARTIFACT_DIR / ("probes-{0}.json".format(stamp))
    tmp = ARTIFACT_DIR / (path.name + ".tmp")
    try:
        tmp.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        os.replace(tmp, path)
    except Exception:
        tmp.unlink(missing_ok=True)
        raise
    return path


def enforce_retention():
    files = sorted(ARTIFACT_DIR.glob("probes-*.json"))
    keep = max(KEEP, 0)
    if keep == 0:
        for old in files:
            old.unlink()
        return
    for old in files[:-keep] if len(files) > keep else []:
        old.unlink()


def main(argv):
    if len(argv) != 1 or (argv[0] not in PROBES and argv[0] != "all"):
        print(__doc__)
        return 2
    names = list(PROBES) if argv[0] == "all" else [argv[0]]
    records = [run_probe(name) for name in names]
    path = write_artifact(records, argv)
    enforce_retention()
    for record in records:
        print("{0}: {1} (expect {2}, {3}s) -> {4}".format(
            record["name"], record["outcome"], record["expect"],
            record["duration_s"], path))
    return 0 if all(r["outcome"] == r["expect"] for r in records) else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
