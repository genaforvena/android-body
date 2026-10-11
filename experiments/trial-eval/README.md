# trial-eval — Milestone-5 artifact-signature scorer

Deterministic evaluation-side scoring for the space-perception programme.
Implements the exclusion rule pre-registered in DM 35076 (2026-10-11T07:18:48Z):
composite-stillness excursions matching the known light-quantization artifact
signature (light_std > 0.1 lux with 0↔1 lux oscillation, accel_std < 0.5 m/s²,
rssi_std < 2.0 dBm, transient revert) are logged with timestamps and excluded
from classifier-error counts. They never trigger falsification. Failure
criteria from DM 32902 are unchanged and are evaluated separately against
labeled sessions.

This is scoring tooling only — not APK consumer logic (PRESERVE stance).

## Freeze-affected windows

An excursion log may mark a window `freeze_affected: true` when the
light stream satisfied the discovery space-light-freeze naming cadence
(same light identity unmoving for >=1 min). Frozen light evidence is
untrustworthy — absence of evidence is not evidence of stillness — so an
all-pass window scores `indeterminate` instead of `artifact`: reported,
never silently excluded from classifier-error counts. A failing condition
still reports `non_artifact`; the marker never hides a fail. The marker
is per-instance and explicit-positive; absent means no marker, never an
assumed-clean window.

## Files

- `artifact_signature.py` — the rule; per-condition pass/fail/missing with
  per-instance fields overriding set-level characterization; missing data is
  reported as `indeterminate`, never silently excluded. Freeze-affected
  windows (`freeze_affected: true`) score `indeterminate` even when all
  conditions pass; a failing condition still reports `non_artifact`.
- `retained-instances-20261011.json` — derived perception statistics for the 9
  retained 2026-10-11 FP instances (05:11Z–07:02Z, ~1 per 12 min) and 6
  quiet-path negatives, each field carrying its retention source. No raw
  samples, no secrets.
- `test_artifact_signature.py` — invariants: quiet path never fires, census
  has no failing condition, missing data is indeterminate, any fail forces
  non-artifact, freeze-affected windows veto artifact classification,
  accounting consistent, output deterministic.

## Run

```sh
python3 -m unittest discover -s experiments/trial-eval
python3 experiments/trial-eval/artifact_signature.py \
  experiments/trial-eval/retained-instances-20261011.json --json
```

## Retained run (2026-10-11)

- 3 instances classify `artifact` with full per-instance evidence
  (05:11Z, 07:01:39Z, 07:02:17Z).
- 6 census instances are `indeterminate`: consistent with the artifact
  mechanism at set level, but per-instance rssi_std was not retained; the
  scorer refuses silent exclusion. Consequence: the labeled-session excursion
  log must retain all five conditions per excursion.
- 6/6 quiet-path negatives correctly non-artifact.

The 9 instances are unlabeled observations; per the trial protocol
(.mishe-tauftauf/research/research-methods-space-trial-protocol.md) they
cannot be used for TP/FP/FN scoring until a labeled session exists.
