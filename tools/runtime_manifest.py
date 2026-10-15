#!/usr/bin/env python3
# SPDX-License-Identifier: CC0-1.0
"""Verify and record the activation fingerprint of the frozen body runtime.

``body/OPERATING.md`` tells readers that the physical services "run frozen
server/consumer bytes in ``body/runtime``, not unfinished checkout edits" and
that their "fingerprints are in ``body/runtime-manifest.json``". That record was
maintained by hand as the last step of a prose deploy procedure, so it drifted:
on 2026-10-14 the manifest still named a ``watch.py`` sha256 from 2026-10-12
while the deployed file had been replaced ten times since. A stale record is not
cosmetic: it is a false statement about which bytes are live, cited as evidence
by readers who never hashed the file. The same failure class was observed on
2026-10-11, when the file had been replaced but the running process still held
the old code and nothing reported it.

This tool makes the record checkable and the drift visible:

* ``check`` compares the recorded sha256 against the bytes actually deployed,
  against the declared repository source, and reports any deployed ``*.py`` that
  the record does not mention. The source of record is the committed blob at
  HEAD when the path is tracked, so a differing working-tree copy is a peer's
  undeployed edit, reported as such, never as deployment drift. For a file whose
  owning systemd unit is recorded, it also compares the unit's start time with
  the file's write time, because a process started before the bytes were written
  is running older code. Exit 0 GREEN / 1 RED / 2 UNKNOWN. A record that cannot
  be read or interpreted is UNKNOWN, never a pass.
* ``record`` rewrites the record from the deployed bytes (atomic replace,
  preserving unknown top-level and per-file keys). It refuses to record a file
  whose deployed bytes differ from its declared source unless
  ``--divergence NAME=TEXT`` states why, so "deployed == source" cannot silently
  become false. It refuses to publish an empty record, which would otherwise
  assert that there is nothing to verify.

Deployed bytes that differ from source are legitimate only when the difference is
declared (the light-cycle monitor's path line is adjusted for the ``body/runtime``
location). Undeclared difference is RED. A unit start time that cannot be read, a
manifest key that is not a bare file name, and a declared source outside the
repository are all refusals or UNKNOWN, never passes. A unit's start time is the
main process's exec time, with its active-period start as the fallback: systemd
clears ``ActiveEnterTimestamp`` when a ``Type=oneshot`` invocation finishes, so a
completed publication timer (``android-body-spool-read.service``, 2026-10-14) read
UNKNOWN forever although its process had run the recorded bytes.

Manifest schema 2 (schema 1 stored ``files`` as name -> sha256 string and is
still readable):

    {"checked": "<iso8601 +00:00>",
     "schema": 2,
     "source_commit": "<git HEAD sha1 at record time, or null>",
     "files": {"watch.py": {"sha256": "...", "source": "experiments/perception/watch.py",
                            "divergence": null, "unit": "android-body-perception.service"}},
     ...other keys preserved verbatim...}

Backups (``<name>.pre-deploy-<stamp>``, ``.pre-redeploy-...``) and
``__pycache__`` are not deployed bytes and are ignored.
"""

from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path, PurePath

RUNTIME_REL = Path("body") / "runtime"
MANIFEST_REL = Path("body") / "runtime-manifest.json"
BACKUP_RE = re.compile(r"\.pre-(?:deploy|redeploy)\d*-")

GREEN, RED, UNKNOWN = "GREEN", "RED", "UNKNOWN"

# systemd prints ActiveEnterTimestamp in local time with a zone abbreviation.
UNIT_TS = "%a %Y-%m-%d %H:%M:%S %Z"
UTC_ZONES = ("UTC", "GMT")
START_SKEW_TOLERANCE_S = 2.0


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 16), b""):
            digest.update(chunk)
    return digest.hexdigest()


def committed_source_hash(repo: Path, source: str) -> str | None:
    """sha256 of ``source`` as committed at HEAD, or None.

    None when the path is not tracked at HEAD (a new, uncommitted source), HEAD
    is unborn, or git cannot be read. The caller then falls back to the
    working-tree file, the only copy that exists.
    """
    try:
        out = subprocess.run(
            ["git", "-C", str(repo), "show", f"HEAD:{source}"],
            capture_output=True, timeout=10, check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if out.returncode != 0:
        return None
    return hashlib.sha256(out.stdout).hexdigest()


def is_bare_name(name: object) -> bool:
    """A record key must be a single path segment: no separators, no ``..``."""
    return (isinstance(name, str) and bool(name) and name not in (".", "..")
            and PurePath(name).name == name)


def deployed_names(runtime_dir: Path) -> list[str]:
    """Deployed runtime modules: top-level ``*.py`` that are not pre-deploy backups."""
    if not runtime_dir.is_dir():
        return []
    return sorted(
        entry.name
        for entry in runtime_dir.iterdir()
        if entry.is_file() and entry.suffix == ".py" and not BACKUP_RE.search(entry.name)
    )


def load_manifest(path: Path) -> dict:
    with open(path, "r", encoding="utf-8") as handle:
        doc = json.load(handle)
    if not isinstance(doc, dict):
        raise ValueError(f"{path}: manifest root is not an object")
    return doc


def recorded_files(doc: dict) -> dict[str, dict]:
    """Normalize ``files`` across schema 1 (string sha256) and schema 2 (object).

    Raises ValueError for a record that cannot be interpreted: a key that is not
    a bare file name, a non-string sha256/source/unit, or a value that is neither
    a string nor an object. Callers report UNKNOWN rather than a pass.
    """
    raw = doc.get("files")
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise ValueError("manifest 'files' is not an object")
    normalized: dict[str, dict] = {}
    for name, value in raw.items():
        if not is_bare_name(name):
            raise ValueError(f"manifest key {name!r} is not a bare file name")
        if isinstance(value, str):
            entry = {"sha256": value, "source": None, "divergence": None, "unit": None}
        elif isinstance(value, dict):
            entry = {key: value.get(key) for key in ("sha256", "source", "divergence", "unit")}
        else:
            raise ValueError(f"manifest entry {name!r} is neither a string nor an object")
        for field in ("sha256", "source", "divergence", "unit"):
            if entry[field] is not None and not isinstance(entry[field], str):
                raise ValueError(f"manifest entry {name!r} field {field!r} is not a string")
        normalized[name] = entry
    return normalized


def resolve_source(repo: Path, source: str) -> Path | None:
    """The declared source inside the repository, or None when it escapes it."""
    if PurePath(source).is_absolute():
        return None
    root = repo.resolve()
    candidate = (repo / source).resolve()
    if candidate != root and root not in candidate.parents:
        return None
    return candidate


def parse_unit_timestamp(text: str) -> datetime.datetime | None:
    """Parse a systemd local-time unit timestamp as UTC, or None.

    systemd prints local time with a zone abbreviation. Only ``UTC``/``GMT`` are
    treated as UTC directly; an abbreviation matching the host's own zone is
    converted from local time, and anything else returns None (UNKNOWN) rather
    than being misread as UTC, which would hide a unit that started before its
    bytes were written.
    """
    text = text.strip()
    if not text:
        return None
    try:
        stamp = datetime.datetime.strptime(text, UNIT_TS)
    except ValueError:
        return None
    zone = text.rsplit(" ", 1)[-1]
    if zone in UTC_ZONES:
        return stamp.replace(tzinfo=datetime.timezone.utc)
    if zone in time.tzname:
        return stamp.replace(tzinfo=None).astimezone(datetime.timezone.utc)
    return None


#: systemd properties that name when the unit's main process started, most
#: authoritative first. ``ExecMainStartTimestamp`` is the exec time of the last
#: main process (kept after a ``Type=oneshot`` invocation finishes and updated on
#: a restart, so it is tighter than the unit's active period);
#: ``ActiveEnterTimestamp`` covers a unit that is active without a main process.
UNIT_START_PROPERTIES = ("ExecMainStartTimestamp", "ActiveEnterTimestamp")


def unit_entered(unit: str) -> datetime.datetime | None:
    """Unit start time as UTC, or None when it cannot be read."""
    for prop in UNIT_START_PROPERTIES:
        try:
            out = subprocess.run(
                ["systemctl", "--user", "show", "-p", prop, "--value", unit],
                capture_output=True, text=True, timeout=10, check=False,
            )
        except (OSError, subprocess.SubprocessError):
            return None
        stamp = parse_unit_timestamp(out.stdout)
        if stamp is not None:
            return stamp
    return None


def git_head(repo: Path) -> str | None:
    try:
        out = subprocess.run(
            ["git", "-C", str(repo), "rev-parse", "HEAD"],
            capture_output=True, text=True, timeout=10, check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return out.stdout.strip() or None if out.returncode == 0 else None


def _mtime_utc(path: Path) -> datetime.datetime:
    return datetime.datetime.fromtimestamp(path.stat().st_mtime, tz=datetime.timezone.utc)


def check(site: Path, repo: Path, unit_entered_fn=None) -> tuple[int, list[str]]:
    """Compare the record with the deployed bytes and the live processes."""
    if unit_entered_fn is None:
        unit_entered_fn = unit_entered
    runtime_dir = site / RUNTIME_REL
    manifest_path = site / MANIFEST_REL
    lines: list[str] = []
    if not manifest_path.is_file():
        return 2, [f"{UNKNOWN} no runtime manifest at {manifest_path}"]
    if not runtime_dir.is_dir():
        return 2, [f"{UNKNOWN} no deployed runtime directory at {runtime_dir}"]
    try:
        doc = load_manifest(manifest_path)
        recorded = recorded_files(doc)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        return 2, [f"{UNKNOWN} unreadable manifest: {exc}"]

    worst = 0  # 0 GREEN, 1 RED, 2 UNKNOWN
    unit_checks = 0

    def note(level: str, text: str) -> None:
        nonlocal worst
        lines.append(f"{level:<7} {text}")
        if level == RED:
            worst = 1
        elif level == UNKNOWN and worst == 0:
            worst = 2

    deployed = set(deployed_names(runtime_dir))
    for name in sorted(recorded):
        entry = recorded[name]
        path = runtime_dir / name
        if not path.is_file():
            note(RED, f"{name}: recorded but not deployed ({path})")
            continue
        actual = sha256_file(path)
        expected = entry["sha256"]
        if expected is None:
            note(RED, f"{name}: record has no sha256")
            continue
        if actual != expected:
            note(RED, f"{name}: deployed sha256 {actual[:16]} != recorded {expected[:16]}")
            continue
        source = entry["source"]
        if not source:
            note(GREEN, f"{name}: site-local, sha256 {actual[:16]} matches the record")
        else:
            source_path = resolve_source(repo, source)
            if source_path is None:
                note(RED, f"{name}: recorded source {source} is outside the repository")
            elif not source_path.is_file():
                note(RED, f"{name}: recorded source {source} is missing")
            else:
                source_hash = sha256_file(source_path)
                committed = committed_source_hash(repo, source)
                if committed is not None and committed == actual:
                    # The deployed bytes are the committed source. A differing
                    # working-tree copy is a peer's undeployed edit, not
                    # deployment drift: the shared checkout is routinely dirty
                    # while a deployed module's source is being edited, and
                    # calling that drift sends readers after a redeploy that is
                    # not owed.
                    if source_hash == committed:
                        note(GREEN, f"{name}: deployed == source {source} (sha256 {actual[:16]})")
                    else:
                        note(GREEN, f"{name}: deployed == committed source {source} "
                                   f"(sha256 {actual[:16]}); working tree has undeployed edits "
                                   f"(HEAD {committed[:16]}, worktree {source_hash[:16]})")
                elif source_hash == actual:
                    note(GREEN, f"{name}: deployed == source {source} (sha256 {actual[:16]})")
                elif entry["divergence"]:
                    note(GREEN, f"{name}: deployed != source {source} "
                               f"(recorded divergence: {entry['divergence']})")
                else:
                    note(RED, f"{name}: deployed != source {source} with no recorded divergence "
                              f"(source {source_hash[:16]})")
        unit = entry["unit"]
        if unit:
            started = unit_entered_fn(unit)
            written = _mtime_utc(path)
            unit_checks += 1
            if started is None:
                note(UNKNOWN, f"{name}: {unit} start time unavailable, cannot prove the process "
                              f"runs the recorded bytes")
            elif started < written - datetime.timedelta(seconds=START_SKEW_TOLERANCE_S):
                note(RED, f"{name}: {unit} started {started.strftime(UNIT_TS)} before the deployed "
                          f"bytes were written {written.strftime(UNIT_TS)} -- the process is "
                          f"running older code")
            else:
                note(GREEN, f"{name}: {unit} started {started.strftime(UNIT_TS)}, after the "
                            f"deployed bytes were written {written.strftime(UNIT_TS)}")

    for name in sorted(deployed - set(recorded)):
        note(RED, f"{name}: deployed but unrecorded")

    if worst == 0:
        lines.append(f"{GREEN:<7} {len(recorded)} recorded runtime file(s) match the deployed bytes"
                     + (f"; {unit_checks} unit start(s) checked" if unit_checks else ""))
    return worst, lines


def record(site: Path, repo: Path, names: list[str] | None, sources: dict[str, str],
           divergences: dict[str, str], verified: str | None,
           units: dict[str, str] | None = None) -> tuple[int, list[str]]:
    """Rewrite the record from the deployed bytes; refuse an undeclared divergence."""
    units = units or {}
    runtime_dir = site / RUNTIME_REL
    manifest_path = site / MANIFEST_REL
    if not runtime_dir.is_dir():
        return 2, [f"{UNKNOWN} no deployed runtime directory at {runtime_dir}"]
    doc: dict = {}
    raw_files: dict = {}
    if manifest_path.is_file():
        try:
            doc = load_manifest(manifest_path)
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            return 2, [f"{UNKNOWN} refusing to overwrite unreadable manifest: {exc}"]
    try:
        recorded = recorded_files(doc)
    except ValueError as exc:
        return 2, [f"{UNKNOWN} refusing to overwrite malformed manifest: {exc}"]
    if isinstance(doc.get("files"), dict):
        raw_files = doc["files"]

    if names:
        targets = list(names)
    else:
        targets = sorted(set(recorded) | set(deployed_names(runtime_dir)))

    lines: list[str] = []
    entries: dict[str, dict] = {}
    for name in targets:
        if not is_bare_name(name):
            return 1, lines + [f"{RED:<7} {name!r}: not a bare file name, refusing to record"]
        path = runtime_dir / name
        if not path.is_file():
            return 1, lines + [f"{RED:<7} {name}: not deployed, refusing to record"]
        actual = sha256_file(path)
        source = sources.get(name, recorded.get(name, {}).get("source"))
        divergence = divergences.get(name, recorded.get(name, {}).get("divergence"))
        unit = units.get(name, recorded.get(name, {}).get("unit"))
        if source:
            source_path = resolve_source(repo, source)
            if source_path is None:
                return 1, lines + [f"{RED:<7} {name}: declared source {source} is outside "
                                          f"the repository, refusing to record"]
            if not source_path.is_file():
                return 1, lines + [f"{RED:<7} {name}: declared source {source} is missing"]
            source_hash = sha256_file(source_path)
            committed = committed_source_hash(repo, source)
            if committed is not None and committed == actual:
                # The deployed bytes are the committed source. A differing
                # working-tree copy is a peer's undeployed edit, not an
                # undeclared divergence -- the same rule check() applies. Refusing
                # here would block recording a deploy of committed bytes for as
                # long as any peer has the shared checkout dirty.
                divergence = None
                if source_hash == committed:
                    lines.append(f"{GREEN:<7} {name}: deployed == source {source} "
                                 f"(sha256 {actual[:16]})")
                else:
                    lines.append(f"{GREEN:<7} {name}: deployed == committed source {source} "
                                 f"(sha256 {actual[:16]}); working tree has undeployed edits "
                                 f"(HEAD {committed[:16]}, worktree {source_hash[:16]})")
            elif source_hash != actual:
                if not divergence:
                    return 1, lines + [
                        f"{RED:<7} {name}: deployed differs from source {source} "
                        f"({source_hash[:16]}); pass --divergence {name}=TEXT to declare why",
                    ]
                lines.append(f"{GREEN:<7} {name}: recorded with divergence ({divergence})")
            else:
                divergence = None
                lines.append(f"{GREEN:<7} {name}: deployed == source {source} (sha256 {actual[:16]})")
        else:
            divergence = None
            lines.append(f"{GREEN:<7} {name}: site-local, sha256 {actual[:16]}")
        # Merge over any existing per-file keys so metadata written by hand survives.
        entry = dict(raw_files.get(name)) if isinstance(raw_files.get(name), dict) else {}
        entry.update({"sha256": actual, "source": source, "divergence": divergence, "unit": unit})
        entries[name] = entry

    for name, entry in recorded.items():
        if name not in entries:
            entries[name] = dict(raw_files[name]) if isinstance(raw_files.get(name), dict) else entry

    if not entries:
        return 1, lines + [f"{RED:<7} refusing to record an empty runtime "
                                  f"(no deployed *.py under {runtime_dir})"]

    out = dict(doc)
    out["schema"] = 2
    out["checked"] = datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0).isoformat()
    out["source_commit"] = git_head(repo)
    out["files"] = {name: entries[name] for name in sorted(entries)}
    if verified is not None:
        out["verification"] = verified

    payload = json.dumps(out, indent=2, sort_keys=False) + "\n"
    # Write through a symlink instead of replacing the link with a regular file.
    target = manifest_path.resolve() if manifest_path.is_symlink() else manifest_path
    mode = target.stat().st_mode & 0o777 if target.exists() else 0o644
    handle = tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=str(target.parent),
        prefix=target.name + ".", suffix=".tmp", delete=False,
    )
    tmp_name = handle.name
    try:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())
        handle.close()
        os.chmod(tmp_name, mode)
        os.replace(tmp_name, target)
    except BaseException:
        handle.close()
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise
    lines.append(f"{GREEN:<7} wrote {target} (checked {out['checked']}, "
                 f"source_commit {out['source_commit'] or 'unknown'})")
    return 0, lines


def parse_pairs(values: list[str] | None, flag: str) -> dict[str, str]:
    pairs: dict[str, str] = {}
    for value in values or []:
        name, sep, text = value.partition("=")
        if not sep or not name or not text:
            raise SystemExit(f"{flag} expects NAME=VALUE, got {value!r}")
        pairs[name] = text
    return pairs


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("mode", choices=("check", "record"))
    parser.add_argument("--repo", default=".", help="repository root (default: .)")
    parser.add_argument("--site", default=None, help="site root (default: <repo>/.mishe-tauftauf)")
    parser.add_argument("--file", action="append", dest="files", default=None,
                        help="record only this deployed file (repeatable)")
    parser.add_argument("--source", action="append", default=None, metavar="NAME=PATH",
                        help="declare the repository source of a deployed file (repeatable)")
    parser.add_argument("--unit", action="append", default=None, metavar="NAME=UNIT",
                        help="declare the systemd unit that runs a deployed file (repeatable)")
    parser.add_argument("--divergence", action="append", default=None, metavar="NAME=TEXT",
                        help="declare why deployed bytes differ from source (repeatable)")
    parser.add_argument("--verified", default=None, help="replace the manifest's verification line")
    args = parser.parse_args(argv)

    repo = Path(args.repo).resolve()
    site = Path(args.site).resolve() if args.site else repo / ".mishe-tauftauf"
    if args.mode == "check":
        code, lines = check(site, repo)
    else:
        code, lines = record(
            site, repo, args.files,
            parse_pairs(args.source, "--source"),
            parse_pairs(args.divergence, "--divergence"),
            args.verified,
            parse_pairs(args.unit, "--unit"),
        )
    for line in lines:
        print(line)
    return code


if __name__ == "__main__":
    sys.exit(main())
