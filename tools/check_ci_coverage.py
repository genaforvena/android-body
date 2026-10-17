#!/usr/bin/env python3
# SPDX-License-Identifier: CC0-1.0
"""Check that every host test in this repository is reachable from CI.

A test that nothing invokes is not coverage, and the build stays green while the
boundary it was written for is unguarded. On 2026-10-17 commit ``93909dc``
shipped ``tools/check_docs.py`` plus its tests and no CI step called it, so a
reader-visible dead link could still pass; ``e72d5f1`` added the invocation.
The same shape is not obvious by reading the workflow, because the host tests
run through three different entry points:

* ``./gradlew :app:test<Name>`` tasks registered in ``app/build.gradle``,
* the shell harnesses ``tools/test-*.sh`` (which compile with ``javac`` and run
  the classes directly, so ``:app:testBleScanEvents`` and ``:app:testEvalOutcome``
  are covered even though the workflow's gradle line omits them), and
* ``python3 -m unittest discover -s <dir>`` for the Python suites.

This detector therefore fails when a Java test class under ``app/src/test`` is
invoked by no CI-run task or harness, when a directory holding ``test_*.py`` is
not discovered by the workflow, or when a ``tools/test-*.sh`` harness is never
referenced. In a clean checkout the tracked listing is the CI set; a local
in-flight new test file will also be reported, which is the intended signal.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
GREEN, RED, UNKNOWN = 0, 1, 2

WORKFLOW = ".github/workflows/check.yml"
GRADLE = "app/build.gradle"
JAVA_TEST_ROOT = "app/src/test/"
PY_SUITE_ROOTS = ("experiments/", "rendezvous/", "tools/")

GRADLE_TASK = re.compile(r"tasks\.register\('(\w+)',\s*JavaExec\)\s*\{(.*?)\n\}", re.S)
GRADLE_MAIN = re.compile(r"mainClass\s*=\s*'(org\.androidbody\.\w+)'")
JAVA_MAIN = re.compile(r'java\s+-cp\s+"\$OUT"\s+(org\.androidbody\.\w+)')
CI_GRADLE_TASK = re.compile(r":app:(\w+)")
CI_SCRIPT = re.compile(r"\btools/[\w.-]+\.sh\b")
CI_DISCOVER = re.compile(r"-m unittest discover -s (\S+)")
HARNESS = re.compile(r"^tools/test-.*\.sh$")
PY_TEST_FILE = re.compile(r"(?:^|/)test_.*\.py$")


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _tracked(root: Path) -> tuple[list[str] | None, str]:
    """The repository's tracked paths, or ``(None, error)`` outside a work tree."""
    listed = subprocess.run(
        ["git", "-C", str(root), "ls-files"], capture_output=True, text=True
    )
    if listed.returncode != 0:
        return None, listed.stderr.strip()
    return listed.stdout.split(), ""


def scan(root: Path = REPO, paths: list[str] | None = None) -> tuple[int, list[str]]:
    """Return ``(code, lines)`` for the repository at ``root``.

    ``paths`` overrides the tracked listing so tests can scan fixtures.
    """
    if paths is None:
        paths, error = _tracked(root)
        if paths is None:
            return UNKNOWN, ["could not list tracked files: " + error]
    try:
        workflow = _read(root / WORKFLOW)
    except OSError as exc:
        return UNKNOWN, [f"could not read {WORKFLOW}: {exc}"]
    try:
        gradle = _read(root / GRADLE)
    except OSError as exc:
        return UNKNOWN, [f"could not read {GRADLE}: {exc}"]

    ci_tasks = set(CI_GRADLE_TASK.findall(workflow))
    ci_scripts = set(CI_SCRIPT.findall(workflow))
    ci_dirs = set(CI_DISCOVER.findall(workflow))

    covered: set[str] = set()
    for task, body in GRADLE_TASK.findall(gradle):
        main = GRADLE_MAIN.search(body)
        if main and task in ci_tasks:
            covered.add(main.group(1))
    for rel in sorted(ci_scripts):
        try:
            covered.update(JAVA_MAIN.findall(_read(root / rel)))
        except OSError:
            # A missing harness fails its own CI step; this detector has no
            # claim about it and must not silently credit its classes.
            continue

    lines: list[str] = []
    problems = 0

    java_tests = [p for p in paths if p.startswith(JAVA_TEST_ROOT) and p.endswith(".java")]
    for rel in sorted(java_tests):
        fqcn = "org.androidbody." + Path(rel).stem
        if fqcn not in covered:
            lines.append(f"FAIL {rel}: {fqcn} is invoked by no CI-run task or harness")
            problems += 1

    suites = sorted(
        {
            str(Path(p).parent)
            for p in paths
            if PY_TEST_FILE.search(p) and p.startswith(PY_SUITE_ROOTS)
        }
    )
    for suite in suites:
        if suite not in ci_dirs:
            lines.append(f"FAIL {suite}: python tests are not discovered by {WORKFLOW}")
            problems += 1

    for rel in sorted(p for p in paths if HARNESS.match(p)):
        if rel not in ci_scripts:
            lines.append(f"FAIL {rel}: harness is not referenced by {WORKFLOW}")
            problems += 1

    if problems:
        return RED, lines
    return GREEN, [
        f"GREEN {len(java_tests)} java test class(es) and {len(suites)} python suite(s) "
        "reachable from CI"
    ]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", nargs="?", default=str(REPO), help="repository root")
    args = parser.parse_args(argv)
    code, lines = scan(Path(args.root))
    for line in lines:
        print(line)
    return code


if __name__ == "__main__":
    sys.exit(main())
