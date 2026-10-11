#!/usr/bin/env python3
"""Milestone-5 artifact-signature scorer (rule pre-registered DM 35076, 2026-10-11).

Evaluation-side exclusion of known light-quantization false-positive
excursions of the Note3 composite stillness classifier. Scoring logic only;
deliberately NOT part of the APK consumer (PRESERVE stance: no consumer
threshold change).

Rule: an excursion is a known-quantization artifact iff ALL hold:
  1. light_std > 0.1 lux
  2. adjacent-level light oscillation (0 <-> 1 lux); a documented
     light-quantization mechanism counts as retained evidence
  3. accel_std < 0.5 m/s^2
  4. rssi_std < 2.0 dBm
  5. transient: composite returns to still within the history window

Each condition evaluates to pass / fail / missing. Per-instance fields
override the evidence file's set-level characterization; set-level covers
instances lacking the field. Classification:
  any fail                      -> non_artifact (reported; NOT excluded)
  all pass                      -> artifact (logged with timestamp, excluded
                                   from classifier-error counts, never
                                   triggers falsification)
  none fail, some missing,
  condition 1 passes            -> indeterminate (reported with missing
                                   conditions; NOT silently excluded)

Usage:
  python3 artifact_signature.py [evidence.json] [--json]
Exit 0 on successful scoring regardless of classifications.
"""

import json
import sys

LIGHT_STD_MAX = 0.1
ACCEL_STD_MAX = 0.5
RSSI_STD_MAX = 2.0

CONDITION_LABELS = (
    "light_std>0.1",
    "oscillation",
    "accel_std<0.5",
    "rssi_std<2.0",
    "transient",
)


def _is_num(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def evaluate(instance, set_level):
    """Classify one instance. Returns (classification, per-condition states)."""
    states = []

    # Condition 1: light_std (per-instance only; no set-level substitute).
    value = instance.get("light_std")
    if _is_num(value):
        states.append("pass" if value > LIGHT_STD_MAX else "fail")
    else:
        states.append("missing")

    # Condition 2: adjacent-level oscillation or documented quantization.
    mechanism = str(instance.get("mechanism", ""))
    if instance.get("oscillation") or "quantiz" in mechanism.lower():
        states.append("pass")
    elif set_level.get("quantization_mechanism"):
        states.append("pass")
    else:
        states.append("missing")

    # Condition 3: accel_std.
    value = instance.get("accel_std")
    if _is_num(value):
        states.append("pass" if value < ACCEL_STD_MAX else "fail")
    elif set_level.get("accel_std_small"):
        states.append("pass")
    else:
        states.append("missing")

    # Condition 4: rssi_std (per-instance only; no set-level substitute).
    value = instance.get("rssi_std")
    if _is_num(value):
        states.append("pass" if value < RSSI_STD_MAX else "fail")
    else:
        states.append("missing")

    # Condition 5: transient revert.
    if instance.get("transient") is True or instance.get("revert_evidence"):
        states.append("pass")
    elif set_level.get("transient_reverts"):
        states.append("pass")
    else:
        states.append("missing")

    if "fail" in states:
        return "non_artifact", states
    if "missing" in states:
        return "indeterminate", states
    return "artifact", states


def score_evidence(evidence):
    """Score all instances in an evidence dict. Returns a report dict."""
    set_level = evidence.get("set_characterization", {})
    rows = []
    for group in ("instances", "quiet_negatives"):
        for instance in evidence.get(group, []):
            classification, states = evaluate(instance, set_level)
            rows.append(
                {
                    "id": instance.get("id", "unknown"),
                    "time": instance.get("time", "unknown"),
                    "group": group,
                    "classification": classification,
                    "states": dict(zip(CONDITION_LABELS, states)),
                    "sources": instance.get("sources", []),
                }
            )

    counts = {"artifact": 0, "non_artifact": 0, "indeterminate": 0}
    for row in rows:
        counts[row["classification"]] += 1

    return {
        "set_characterization_source": set_level.get("source", "none"),
        "rows": rows,
        "counts": counts,
        "artifact_timestamps": [
            row["time"] for row in rows if row["classification"] == "artifact"
        ],
    }


def render_text(report):
    lines = [
        "Milestone-5 artifact-signature scoring (pre-registered rule, DM 35076)",
        "Set-level characterization: {}".format(report["set_characterization_source"]),
        "",
        "Per-instance:",
    ]
    for row in report["rows"]:
        marks = " ".join(
            "{}={}".format(label, state) for label, state in row["states"].items()
        )
        lines.append(
            "  {:10s} {:28s} -> {:13s} [{}]".format(
                row["id"], row["time"], row["classification"], marks
            )
        )
    lines += [
        "",
        "Summary:",
        "  instances scored: {}".format(len(report["rows"])),
        "  artifact (excluded from error counts): {}".format(report["counts"]["artifact"]),
        "  non-artifact (reported, not excluded): {}".format(
            report["counts"]["non_artifact"]
        ),
        "  indeterminate (missing conditions; not silently excluded): {}".format(
            report["counts"]["indeterminate"]
        ),
        "  artifact timestamps: {}".format(", ".join(report["artifact_timestamps"])),
    ]
    return "\n".join(lines)


def main(argv):
    args = [a for a in argv if not a.startswith("--")]
    as_json = "--json" in argv
    path = args[0] if args else "retained-instances-20261011.json"
    with open(path, "r", encoding="utf-8") as handle:
        evidence = json.load(handle)
    report = score_evidence(evidence)
    if as_json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print(render_text(report))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
