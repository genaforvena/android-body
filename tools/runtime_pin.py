#!/usr/bin/env python3
# SPDX-License-Identifier: CC0-1.0
"""Verify the site's runtime pin names a clean exact-SHA git worktree.

Every ``seed run`` channel resolves the bytes it will import through
``<site>/health/runtime-release.json`` (pinned core
``mishe_tauftauf.runtime_source.source_for``) and refuses to start unless that
document names a git worktree whose toplevel is the pinned path, whose HEAD is
the pinned sha and whose working tree is clean (``checked_source``). The refusal
is a startup failure, not a warning: the channel exits 2 and systemd restarts it
every 15 s forever, and the only message is the one line on stderr.

Measured 2026-10-17: a hand edit inside the *pinned release itself*
(``releases/1543b3a0.../src/mishe_tauftauf/session_watch.py``, +8/-1, mtime
01:00:32Z) left that worktree dirty while ``health/runtime-release.json`` still
named it. All ten of the co-resident core plant's channel units
(``mishe-self-development-current-<role>.service``) exited 2 with ``runtime pin
invalid: runtime source changed or is not a clean exact-SHA worktree`` on every
restart -- NRestarts=478 by 10:48Z, that plant's last wall write 01:06:59Z --
and nothing in this plant's check read the pin at all. This plant's own pin
(``releases/14963f76fc38``) stayed clean, so the check below is the difference
between "a channel will not start, and here is why" and a restart storm whose
cause no line names.

RED names the fact that fails: a pin the kernel's own ``version``/``sha`` checks
reject (unreadable, non-UTF8, not an object, wrong version, bad sha, non-string
source), a pin path that exists but cannot be read as a document (a directory,
where ``source_for`` raises ``IsADirectoryError`` and every channel refuses),
a source path whitespace cannot carry into a generated unit, a source that
cannot be resolved, a git that runs and fails or cannot be executed at all
(``checked_source`` lets ``OSError``/``TimeoutExpired`` propagate, so that is a
refusal too), a source that is not a worktree root, a HEAD that is not the pin,
a dirty working tree, or a missing package. The one UNKNOWN is a site that
declares no pin: ``source_for`` returns its default there, so the channel does
start -- on the respawner's tree, which is not a pass and never a GREEN.
Read-only: ``rev-parse`` and ``status --porcelain``, both with
``--no-optional-locks`` so git does not refresh the index it reads (the
kernel's own ``checked_source`` takes that lock at every channel start; this
check leaves the worktree byte-identical), and no write of its own.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

#: Where the pinned core reads this site's declared byte-set
#: (``runtime_source.source_for``: ``home / "health/runtime-release.json"``).
PIN_REL = Path("health") / "runtime-release.json"

#: ``checked_source``'s last predicate: the pinned tree must hold the package.
PACKAGE_REL = Path("src") / "mishe_tauftauf" / "__init__.py"

#: ``checked_source`` bounds each git call at 10 s; the same bound here keeps a
#: hung ``status`` from holding the whole check open.
GIT_TIMEOUT = 10.0

GREEN, RED, UNKNOWN = "GREEN", "RED", "UNKNOWN"


def run_git(source, *args):
    """``(rc, stdout, stderr)`` for git in *source*, or None when git cannot run."""
    try:
        out = subprocess.run(
            ["git", "--no-optional-locks", "-C", str(source), *args],
            capture_output=True, text=True, timeout=GIT_TIMEOUT, check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return out.returncode, out.stdout, out.stderr


def load_pin(path):
    """``(source, sha)`` for the pin document, or None when the site declares none.

    Raises ValueError for a document the kernel's own checks reject -- a version
    that is not 1, a sha that is not a 40-character string, a source that is not
    a string -- because ``source_for`` raises there and every channel refuses to
    start. A path that is absent (including a dangling symlink, which
    ``source_for``'s ``pin.exists()`` also rejects) is the one case it tolerates,
    and it is *not* returned as a pin; a path that exists but is not a readable
    document is a refusal like any other.
    """
    if not path.exists():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    if data["version"] != 1:
        raise ValueError(f"version {data['version']!r} is not 1")
    sha = data["sha"]
    if not isinstance(sha, str) or len(sha) != 40:
        raise ValueError(f"sha {sha!r} is not a 40-character string")
    source = data["source"]
    if not isinstance(source, str):
        raise ValueError(f"source {source!r} is not a string")
    return Path(source), sha


def check(site, git=run_git):
    """``(rc, lines)`` for the site's runtime pin: 0 GREEN, 1 RED, 2 UNKNOWN."""
    site = Path(site)
    pin_path = site / PIN_REL
    try:
        pin = load_pin(pin_path)
    except (OSError, ValueError, TypeError, KeyError, RecursionError,
            json.JSONDecodeError) as exc:
        return 1, [f"{RED:<7} runtime pin {pin_path} is not one the kernel accepts: {exc}"]

    if pin is None:
        return 2, [f"{UNKNOWN:<7} runtime pin: no {PIN_REL} under {site} "
                   "(the core falls back to the respawner's tree; not a pass)"]

    source, sha = pin
    try:
        source = source.resolve()
    except (OSError, RuntimeError) as exc:
        return 1, [f"{RED:<7} runtime pin source {source} cannot be resolved: {exc}"]
    if any(char.isspace() for char in str(source)):
        return 1, [f"{RED:<7} runtime pin source {source} contains whitespace "
                   "(a generated systemd unit cannot carry it)"]

    probes = {}
    for name, args in (("head", ("rev-parse", "HEAD")),
                       ("root", ("rev-parse", "--show-toplevel")),
                       ("dirty", ("status", "--porcelain"))):
        result = git(source, *args)
        if result is None:
            return 1, [f"{RED:<7} runtime pin {source}: git {' '.join(args)} could not run "
                       "(the kernel refuses to start every channel there)"]
        rc, out, err = result
        if rc != 0:
            first = err.strip().splitlines()[0] if err.strip() else "no stderr"
            return 1, [f"{RED:<7} runtime pin {source}: git {' '.join(args)} "
                       f"failed (rc {rc}): {first}"]
        probes[name] = out

    root = Path(probes["root"].strip()).resolve()
    if root != source:
        return 1, [f"{RED:<7} runtime pin {source} is not a worktree root "
                   f"(git toplevel {root})"]
    head = probes["head"].strip()
    if head != sha:
        return 1, [f"{RED:<7} runtime pin {source} HEAD {head[:12]} != pin {sha[:12]}"]
    dirty = [line for line in probes["dirty"].splitlines() if line.strip()]
    if dirty:
        return 1, [f"{RED:<7} runtime pin {source} worktree dirty "
                   f"({len(dirty)} path(s); first: {dirty[0][:120]}) -- "
                   "every channel refuses to start"]
    if not (source / PACKAGE_REL).is_file():
        return 1, [f"{RED:<7} runtime pin {source} has no {PACKAGE_REL} "
                   "(runtime source package is missing)"]
    return 0, [f"{GREEN:<7} runtime pin {sha[:12]} clean exact-SHA worktree ({source})"]


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Verify the site's runtime pin names a clean exact-SHA git worktree.")
    parser.add_argument("--site", required=True,
                        help="site root (reads health/runtime-release.json)")
    args = parser.parse_args(argv)
    rc, lines = check(args.site)
    for line in lines:
        print(line)
    return rc


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
