#!/usr/bin/env python3
# SPDX-License-Identifier: CC0-1.0
"""Tests for the CI-reachability detector (tools/check_ci_coverage.py).

The regression that matters: a host test exists in the tree but no CI step runs
it, so the boundary it guards is unguarded while the build stays green -- the
2026-10-17 ``93909dc`` shape, where ``tools/check_docs.py`` was committed with
tests and nothing invoked it until ``e72d5f1``. The detector must also credit
the two non-gradle paths (shell harnesses, ``unittest discover``) rather than
demand a gradle task for every class.
"""

import tempfile
import unittest
from pathlib import Path

import check_ci_coverage as checker  # noqa: E402

WORKFLOW = ".github/workflows/check.yml"
GRADLE = "app/build.gradle"

CI_WITH_ONE_TASK = """\
jobs:
  check:
    steps:
      - name: Boundary tests
        run: |
          tools/test-protocol.sh
          python3 -m unittest discover -s tools
      - name: Build and lint
        run: ./gradlew --no-daemon :app:testProtocol
"""

GRADLE_WITH_TWO_TASKS = """\
tasks.register('testProtocol', JavaExec) {
    mainClass = 'org.androidbody.ProtocolTest'
}

tasks.register('testBleScanEvents', JavaExec) {
    mainClass = 'org.androidbody.BleScanEventsTest'
}
"""

HARNESS = """\
#!/bin/sh
set -eu
java -cp "$OUT" org.androidbody.ProtocolTest
"""

#: The harness credits whichever class it actually runs.
HARNESS_BLE = HARNESS.replace("ProtocolTest", "BleScanEventsTest")


class DetectorTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def write(self, rel: str, text: str) -> None:
        path = self.root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

    def scan(self, workflow: str | None, gradle: str, extra: dict[str, str]):
        paths = [GRADLE]
        if workflow is not None:
            self.write(WORKFLOW, workflow)
            paths.append(WORKFLOW)
        self.write(GRADLE, gradle)
        for rel, text in extra.items():
            self.write(rel, text)
            paths.append(rel)
        return checker.scan(self.root, sorted(paths))

    def test_ci_gradle_task_covers_its_class(self):
        code, lines = self.scan(
            CI_WITH_ONE_TASK,
            GRADLE_WITH_TWO_TASKS,
            {
                "app/src/test/java/org/androidbody/ProtocolTest.java": "package org.androidbody;\n",
                "tools/test-protocol.sh": HARNESS,
                "tools/test_dummy.py": "",
            },
        )
        self.assertEqual(code, checker.GREEN, lines)

    def test_class_with_no_entry_point_is_red(self):
        code, lines = self.scan(
            CI_WITH_ONE_TASK,
            GRADLE_WITH_TWO_TASKS,
            {
                "app/src/test/java/org/androidbody/ProtocolTest.java": "package org.androidbody;\n",
                "app/src/test/java/org/androidbody/OrphanTest.java": "package org.androidbody;\n",
                "tools/test-protocol.sh": HARNESS,
                "tools/test_dummy.py": "",
            },
        )
        self.assertEqual(code, checker.RED)
        self.assertTrue(any("OrphanTest is invoked by no CI-run" in line for line in lines), lines)

    def test_registered_task_absent_from_workflow_is_red(self):
        # The class is wired to a gradle task, but the workflow never runs that
        # task and no harness runs the class either.
        code, lines = self.scan(
            CI_WITH_ONE_TASK,
            GRADLE_WITH_TWO_TASKS,
            {
                "app/src/test/java/org/androidbody/ProtocolTest.java": "package org.androidbody;\n",
                "app/src/test/java/org/androidbody/BleScanEventsTest.java": "package org.androidbody;\n",
                "tools/test-protocol.sh": HARNESS,
                "tools/test_dummy.py": "",
            },
        )
        self.assertEqual(code, checker.RED)
        self.assertTrue(
            any("BleScanEventsTest is invoked by no CI-run" in line for line in lines), lines
        )

    def test_harness_credits_a_class_whose_gradle_task_is_not_in_ci(self):
        # The real shape: `:app:testBleScanEvents` is absent from the workflow's
        # gradle line, but tools/test-protocol.sh runs the same class.
        code, lines = self.scan(
            CI_WITH_ONE_TASK,
            GRADLE_WITH_TWO_TASKS,
            {
                "app/src/test/java/org/androidbody/ProtocolTest.java": "package org.androidbody;\n",
                "app/src/test/java/org/androidbody/BleScanEventsTest.java": "package org.androidbody;\n",
                "tools/test-protocol.sh": HARNESS_BLE,
                "tools/test_dummy.py": "",
            },
        )
        self.assertEqual(code, checker.GREEN, lines)

    def test_undiscovered_python_suite_is_red(self):
        code, lines = self.scan(
            CI_WITH_ONE_TASK,
            GRADLE_WITH_TWO_TASKS,
            {
                "app/src/test/java/org/androidbody/ProtocolTest.java": "package org.androidbody;\n",
                "tools/test-protocol.sh": HARNESS,
                "tools/test_dummy.py": "",
                "experiments/orphan/test_orphan.py": "import unittest\n",
            },
        )
        self.assertEqual(code, checker.RED)
        self.assertTrue(
            any("experiments/orphan: python tests are not discovered" in line for line in lines),
            lines,
        )

    def test_harness_not_referenced_by_workflow_is_red(self):
        code, lines = self.scan(
            CI_WITH_ONE_TASK,
            GRADLE_WITH_TWO_TASKS,
            {
                "app/src/test/java/org/androidbody/ProtocolTest.java": "package org.androidbody;\n",
                "tools/test-protocol.sh": HARNESS,
                "tools/test_check_ci_coverage.py": "",
                "tools/test-orphan.sh": "#!/bin/sh\njava -cp \"$OUT\" org.androidbody.ProtocolTest\n",
            },
        )
        self.assertEqual(code, checker.RED)
        self.assertTrue(
            any("tools/test-orphan.sh: harness is not referenced" in line for line in lines), lines
        )

    def test_missing_workflow_is_unknown(self):
        code, lines = self.scan(
            None,
            GRADLE_WITH_TWO_TASKS,
            {"app/src/test/java/org/androidbody/ProtocolTest.java": "package org.androidbody;\n"},
        )
        self.assertEqual(code, checker.UNKNOWN)
        self.assertTrue(any("could not read" in line for line in lines), lines)


if __name__ == "__main__":
    unittest.main()
