"""Tests for the Milestone-5 artifact-signature scorer.

Invariants covered:
  - Quiet-path samples must never classify as artifact (the light_std>0.1
    term is load-bearing; dropping it must fail a test).
  - Retained FP-census instances must have no failing condition (the rule
    must not contradict the independent senses/discover characterization).
  - Missing data yields indeterminate, never a silent artifact exclusion.
  - Report accounting is consistent and the scorer is deterministic.
  - Freeze-affected windows score indeterminate even when all
    conditions pass; the marker never hides a failing condition.
"""

import json
import os
import subprocess
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from artifact_signature import evaluate, score_evidence  # noqa: E402


def load_evidence():
    with open(os.path.join(HERE, "retained-instances-20261011.json"), encoding="utf-8") as fh:
        return json.load(fh)


class TestArtifactSignature(unittest.TestCase):
    def test_quiet_path_never_fires(self):
        evidence = load_evidence()
        set_level = evidence["set_characterization"]
        for instance in evidence["quiet_negatives"]:
            classification, states = evaluate(instance, set_level)
            self.assertEqual(classification, "non_artifact", instance["id"])
            self.assertEqual(states[0], "fail", instance["id"])

    def test_fp_census_has_no_failing_condition(self):
        evidence = load_evidence()
        set_level = evidence["set_characterization"]
        for instance in evidence["instances"]:
            classification, states = evaluate(instance, set_level)
            self.assertNotEqual(classification, "non_artifact", instance["id"])
            self.assertNotIn("fail", states, instance["id"])

    def test_missing_data_is_indeterminate_not_silent_pass(self):
        classification, states = evaluate({"light_std": 0.5}, {})
        self.assertEqual(classification, "indeterminate")
        self.assertIn("missing", states)

    def test_any_fail_forces_non_artifact(self):
        instance = {
            "light_std": 0.5,
            "oscillation": "0->1->0",
            "accel_std": 0.9,
            "rssi_std": 0.0,
            "transient": True,
        }
        classification, _ = evaluate(instance, {})
        self.assertEqual(classification, "non_artifact")

    def test_per_instance_overrides_set_level(self):
        set_level = {
            "quantization_mechanism": True,
            "accel_std_small": True,
            "transient_reverts": True,
        }
        instance = {"light_std": 0.5, "accel_std": 0.9}
        classification, _ = evaluate(instance, set_level)
        self.assertEqual(classification, "non_artifact")

    def test_freeze_affected_vetoes_artifact(self):
        instance = {
            "id": "fp-freeze",
            "light_std": 0.646,
            "accel_std": 0.054,
            "rssi_std": 0.373,
            "oscillation": "0->1->0",
            "transient": True,
            "freeze_affected": True,
        }
        classification, _ = evaluate(instance, {})
        self.assertEqual(classification, "indeterminate")

    def test_freeze_affected_does_not_hide_fail(self):
        instance = {
            "id": "fp-freeze-fail",
            "light_std": 0.646,
            "accel_std": 0.9,
            "freeze_affected": True,
        }
        classification, states = evaluate(instance, {})
        self.assertEqual(classification, "non_artifact")
        self.assertIn("fail", states)

    def test_absent_freeze_marker_still_classifies(self):
        instance = {
            "id": "fp-nofreeze",
            "light_std": 0.646,
            "accel_std": 0.054,
            "rssi_std": 0.373,
            "oscillation": "0->1->0",
            "transient": True,
        }
        classification, _ = evaluate(instance, {})
        self.assertEqual(classification, "artifact")

    def test_report_accounting_is_consistent(self):
        report = score_evidence(load_evidence())
        counts = report["counts"]
        self.assertEqual(
            counts["artifact"] + counts["non_artifact"] + counts["indeterminate"],
            len(report["rows"]),
        )
        self.assertEqual(
            len(report["artifact_timestamps"]), counts["artifact"]
        )
        for row in report["rows"]:
            self.assertEqual(len(row["states"]), 5)

    def test_scorer_is_deterministic(self):
        script = os.path.join(HERE, "artifact_signature.py")
        evidence = os.path.join(HERE, "retained-instances-20261011.json")
        runs = [
            subprocess.run(
                [sys.executable, script, evidence, "--json"],
                capture_output=True,
                text=True,
                check=True,
            ).stdout
            for _ in range(2)
        ]
        self.assertEqual(runs[0], runs[1])
        parsed = json.loads(runs[0])
        self.assertEqual(
            parsed["counts"]["artifact"]
            + parsed["counts"]["non_artifact"]
            + parsed["counts"]["indeterminate"],
            15,
        )


if __name__ == "__main__":
    unittest.main()
