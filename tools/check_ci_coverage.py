#!/usr/bin/env python3
# SPDX-License-Identifier: CC0-1.0
"""Check that every host test in this repository is reachable from CI.

A test that nothing invokes is not coverage, and the build stays green while the
boundary it was written for is unguarded. On 2026-10-17 commit ``93909dc``
shipped ``tools/check_docs.py`` plus its tests and no CI step called it, so a
reader-visible dead link could still pass; ``e72d5f1`` added the invocation.
The same shape is not obvious by reading the workflow, because the host tests
run through three different entry points:

* ``./gradlew :<module>:test<Name>`` tasks registered in that module's
  ``build.gradle``,
* the shell harnesses ``tools/test-*.sh`` (which compile with ``javac`` and run
  the classes directly, so ``:app:testBleScanEvents`` and ``:app:testEvalOutcome``
  are covered even though the workflow's gradle line omits them), and
* ``python3 -m unittest discover -s <dir>`` for the Python suites.

This detector therefore fails when a Java test class under any module's
``src/test/java`` is invoked by no CI-run task or harness, when a directory
holding ``test_*.py`` is not discovered by the workflow, or when a
``tools/test-*.sh`` harness is never referenced. The listing is the tracked set
(``git ls-files``), so an untracked draft is not judged until it is added; a
tracked test with no CI caller always is.

Three shapes this detector was blind to before 2026-10-17, all real:

* It only knew ``app/src/test/`` and ``:app:`` tasks, so a second module was
  invisible: ``ble-probe/src/test/java/.../ProbeReportTest.java`` had a
  registered ``:ble-probe:testProbeReport`` task and no CI caller at all, yet
  the checker printed GREEN. Modules and their gradle files now come from the
  tracked listing, and ``tools/test-ble-probe.sh`` runs that class.
* A commented-out reference counted as a caller. Comments are stripped from
  every file that can supply credit before it is read -- workflow ``#``,
  harness ``#`` and gradle ``//``/``/* */`` -- so ``# tools/test-protocol.sh``
  no longer credits the harness it names, nor a commented ``java -cp "$OUT"``
  line its class.

* A root-module Java test file (``src/test/java/...`` with no module prefix)
  was invisible: the marker required the leading slash of a module path, so
  the file was not counted as a test at all and the checker printed GREEN
  with "0 java test class(es)". The marker now matches both shapes; the
  root-module ``:task`` rule below stays fail-closed.

The module prefix is part of the match, so a task name shared by two modules
cannot cross-credit. A root-module task (``./gradlew :testFoo`` with no module
prefix) is not matched and would read as uncovered: that is the fail-closed
direction, and the root ``build.gradle`` registers no test task today.

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
#: No leading slash: a root-module test file (``src/test/java/...``) must be
#: counted too, or it is invisible to the detector entirely. The slash
#: between ``test`` and ``java`` is part of the directory name.
JAVA_TEST_MARKER = "src/test/java/"
GRADLE_FILE = re.compile(r"(?:^|/)build\.gradle$")
GRADLE_TASK = re.compile(r"tasks\.register\('(\w+)',\s*JavaExec\)\s*\{(.*?)\n\}", re.S)
GRADLE_MAIN = re.compile(r"mainClass\s*=\s*'([\w.]+)'")
JAVA_MAIN = re.compile(r'java\s+-cp\s+"\$OUT"\s+([\w.]+)')
CI_GRADLE_TASK = re.compile(r":([\w-]+):(\w+)")
CI_SCRIPT = re.compile(r"\btools/[\w.-]+\.sh\b")
CI_DISCOVER = re.compile(r"-m unittest discover -s (\S+)")
HARNESS = re.compile(r"^tools/test-.*\.sh$")
PY_TEST_FILE = re.compile(r"(?:^|/)test_.*\.py$")


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _strip_hash(text: str) -> str:
    """Drop ``#``-to-end-of-line comments (workflow YAML, shell harnesses)."""
    return "\n".join(line.split("#", 1)[0] for line in text.splitlines())


def _strip_slashes(text: str) -> str:
    """Drop ``/* */`` blocks and ``//``-to-end-of-line comments (gradle files)."""
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    return "\n".join(line.split("//", 1)[0] for line in text.splitlines())


def _tracked(root: Path) -> tuple[list[str] | None, str]:
    """The repository's tracked paths, or ``(None, error)`` outside a work tree."""
    listed = subprocess.run(
        ["git", "-C", str(root), "ls-files"], capture_output=True, text=True
    )
    if listed.returncode != 0:
        return None, listed.stderr.strip()
    return listed.stdout.split(), ""


def _module_of(rel: str) -> str:
    """``app/build.gradle`` -> ``app``; a root ``build.gradle`` -> ``""``."""
    return rel[: -len("/build.gradle")] if "/" in rel else ""


def _fqcn_of(rel: str) -> str:
    """``app/src/test/java/org/androidbody/Foo.java`` -> ``org.androidbody.Foo``."""
    return rel.split(JAVA_TEST_MARKER, 1)[1][: -len(".java")].replace("/", ".")


def scan(root: Path = REPO, paths: list[str] | None = None) -> tuple[int, list[str]]:
    """Return ``(code, lines)`` for the repository at ``root``.

    ``paths`` overrides the tracked listing so tests can scan fixtures.
    """
    if paths is None:
        paths, error = _tracked(root)
        if paths is None:
            return UNKNOWN, ["could not list tracked files: " + error]
    try:
        workflow = _strip_hash(_read(root / WORKFLOW))
    except OSError as exc:
        return UNKNOWN, [f"could not read {WORKFLOW}: {exc}"]

    gradle_files = [p for p in paths if GRADLE_FILE.search(p)]
    if not gradle_files:
        return UNKNOWN, ["no build.gradle among the tracked files"]

    ci_tasks = set(CI_GRADLE_TASK.findall(workflow))
    ci_scripts = set(CI_SCRIPT.findall(workflow))
    ci_dirs = set(CI_DISCOVER.findall(workflow))

    covered: set[str] = set()
    for rel in sorted(gradle_files):
        try:
            gradle = _strip_slashes(_read(root / rel))
        except OSError as exc:
            return UNKNOWN, [f"could not read {rel}: {exc}"]
        module = _module_of(rel)
        for task, body in GRADLE_TASK.findall(gradle):
            main = GRADLE_MAIN.search(body)
            if main and (module, task) in ci_tasks:
                covered.add(main.group(1))
    for rel in sorted(ci_scripts):
        try:
            covered.update(JAVA_MAIN.findall(_strip_hash(_read(root / rel))))
        except OSError:
            # A missing harness fails its own CI step; this detector has no
            # claim about it and must not silently credit its classes.
            continue

    lines: list[str] = []
    problems = 0

    java_tests = [p for p in paths if JAVA_TEST_MARKER in p and p.endswith(".java")]
    for rel in sorted(java_tests):
        fqcn = _fqcn_of(rel)
        if fqcn not in covered:
            lines.append(f"FAIL {rel}: {fqcn} is invoked by no CI-run task or harness")
            problems += 1

    suites = sorted({str(Path(p).parent) for p in paths if PY_TEST_FILE.search(p)})
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
