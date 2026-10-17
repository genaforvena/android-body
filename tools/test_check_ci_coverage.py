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

#: A second module: its task is registered but the workflow's `:app:` line never
#: runs it, so only a harness (or a `:ble-probe:` task in CI) can credit it.
GRADLE_BLE = """\
tasks.register('testProbeReport', JavaExec) {
    mainClass = 'org.androidbody.bleprobe.ProbeReportTest'
}
"""

CI_WITH_BLE_TASK = CI_WITH_ONE_TASK.replace(
    ":app:testProtocol", ":app:testProtocol :ble-probe:testProbeReport"
)

CI_WITH_BLE_HARNESS = CI_WITH_ONE_TASK + "          tools/test-ble-probe.sh\n"

#: The real shape: the harness is named only in a comment, which is not a caller.
CI_WITH_COMMENTED_HARNESS = CI_WITH_ONE_TASK.replace(
    "tools/test-protocol.sh", "# tools/test-protocol.sh"
)

BLE_PROBE_FILES = {
    "ble-probe/build.gradle": GRADLE_BLE,
    "ble-probe/src/test/java/org/androidbody/bleprobe/ProbeReportTest.java":
        "package org.androidbody.bleprobe;\n",
    "tools/test-ble-probe.sh":
        '#!/bin/sh\njava -cp "$OUT" org.androidbody.bleprobe.ProbeReportTest\n',
}


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

    def test_non_app_module_class_without_caller_is_red(self):
        # The real 2026-10-17 gap: ble-probe is a second module, so the
        # workflow's `:app:` line never ran its registered test task, and the
        # app-only detector printed GREEN while the class ran nowhere.
        code, lines = self.scan(
            CI_WITH_ONE_TASK,
            GRADLE_WITH_TWO_TASKS,
            {
                "app/src/test/java/org/androidbody/ProtocolTest.java": "package org.androidbody;\n",
                "tools/test-protocol.sh": HARNESS,
                "tools/test_dummy.py": "",
                **BLE_PROBE_FILES,
            },
        )
        self.assertEqual(code, checker.RED)
        self.assertTrue(
            any(
                "ProbeReportTest.java: org.androidbody.bleprobe.ProbeReportTest "
                "is invoked by no CI-run" in line
                for line in lines
            ),
            lines,
        )

    def test_non_app_module_task_in_ci_covers_its_class(self):
        code, lines = self.scan(
            CI_WITH_BLE_TASK,
            GRADLE_WITH_TWO_TASKS,
            {
                "app/src/test/java/org/androidbody/ProtocolTest.java": "package org.androidbody;\n",
                "tools/test-protocol.sh": HARNESS,
                "tools/test_dummy.py": "",
                "ble-probe/build.gradle": GRADLE_BLE,
                "ble-probe/src/test/java/org/androidbody/bleprobe/ProbeReportTest.java":
                    "package org.androidbody.bleprobe;\n",
            },
        )
        self.assertEqual(code, checker.GREEN, lines)

    def test_non_app_harness_credits_dotted_class(self):
        # tools/test-ble-probe.sh runs the class directly, like the app harnesses.
        code, lines = self.scan(
            CI_WITH_BLE_HARNESS,
            GRADLE_WITH_TWO_TASKS,
            {
                "app/src/test/java/org/androidbody/ProtocolTest.java": "package org.androidbody;\n",
                "tools/test-protocol.sh": HARNESS,
                "tools/test_dummy.py": "",
                **BLE_PROBE_FILES,
            },
        )
        self.assertEqual(code, checker.GREEN, lines)

    def test_commented_out_harness_is_not_a_caller(self):
        # `:app:testProtocol` still covers ProtocolTest, so use the class whose
        # only caller is the harness: if the comment counted, it would be GREEN.
        code, lines = self.scan(
            CI_WITH_COMMENTED_HARNESS,
            GRADLE_WITH_TWO_TASKS,
            {
                "app/src/test/java/org/androidbody/BleScanEventsTest.java":
                    "package org.androidbody;\n",
                "tools/test-protocol.sh": HARNESS_BLE,
                "tools/test_dummy.py": "",
            },
        )
        self.assertEqual(code, checker.RED)
        self.assertTrue(
            any("tools/test-protocol.sh: harness is not referenced" in line for line in lines),
            lines,
        )
        self.assertTrue(
            any("BleScanEventsTest is invoked by no CI-run" in line for line in lines), lines
        )

    def test_commented_java_main_in_harness_is_not_a_caller(self):
        # A harness line that is commented out runs nothing; the class must stay
        # uncovered even though its text appears in a CI-referenced file.
        code, lines = self.scan(
            CI_WITH_ONE_TASK,
            GRADLE_WITH_TWO_TASKS,
            {
                "app/src/test/java/org/androidbody/BleScanEventsTest.java":
                    "package org.androidbody;\n",
                "tools/test-protocol.sh":
                    '# java -cp "$OUT" org.androidbody.BleScanEventsTest\n',
                "tools/test_dummy.py": "",
            },
        )
        self.assertEqual(code, checker.RED)
        self.assertTrue(
            any("BleScanEventsTest is invoked by no CI-run" in line for line in lines), lines
        )

    def test_commented_mainclass_does_not_credit(self):
        code, lines = self.scan(
            CI_WITH_ONE_TASK,
            GRADLE_WITH_TWO_TASKS,
            {
                "app/src/test/java/org/androidbody/ProtocolTest.java": "package org.androidbody;\n",
                "tools/test_dummy.py": "",
                "tools/test-protocol.sh": HARNESS_BLE,
                "app/build.gradle": GRADLE_WITH_TWO_TASKS.replace(
                    "mainClass = 'org.androidbody.ProtocolTest'",
                    "// mainClass = 'org.androidbody.ProtocolTest'",
                ),
            },
        )
        self.assertEqual(code, checker.RED)
        self.assertTrue(
            any("ProtocolTest is invoked by no CI-run" in line for line in lines), lines
        )

    def test_same_task_name_in_another_module_does_not_cross_credit(self):
        # `:app:testThing` must credit only the app module's class; a same-named
        # task in ble-probe is a different task and its class stays uncovered.
        code, lines = self.scan(
            CI_WITH_ONE_TASK.replace(":app:testProtocol", ":app:testThing"),
            """\
tasks.register('testThing', JavaExec) {
    mainClass = 'org.androidbody.ProtocolTest'
}
""",
            {
                "app/src/test/java/org/androidbody/ProtocolTest.java": "package org.androidbody;\n",
                "ble-probe/build.gradle": """\
tasks.register('testThing', JavaExec) {
    mainClass = 'org.androidbody.bleprobe.ProbeReportTest'
}
""",
                "ble-probe/src/test/java/org/androidbody/bleprobe/ProbeReportTest.java":
                    "package org.androidbody.bleprobe;\n",
                "tools/test_dummy.py": "",
            },
        )
        self.assertEqual(code, checker.RED)
        self.assertTrue(
            any(
                "ProbeReportTest.java: org.androidbody.bleprobe.ProbeReportTest "
                "is invoked by no CI-run" in line
                for line in lines
            ),
            lines,
        )
        self.assertFalse(any("ProtocolTest.java" in line for line in lines), lines)


if __name__ == "__main__":
    unittest.main()
