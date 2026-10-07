# Working on Android Body

Keep this a small physical bridge. Reasoning belongs in a consumer; the phone reports observations and bounded requested effects. The [protocol](protocol/README.md) is the contract, not an Android method-call API.

## Make one observable change

1. Read the relevant code and boundary documentation.
2. State the behavior to change and the evidence that would establish it.
3. Make a bounded change; add a regression test for an observed defect.
4. Run the applicable checks. Read their output, including failures and warnings.
5. Record what actually passed, what failed, and what is still unknown in the work summary. Update `docs/verification.md` when delivered evidence changes.

A successful build is not proof of a working phone. An accepted actuator API call is not proof of a physical effect. An emulator is not a Xiaomi, a Note3 motor or an old HTTPS trust store. Missing evidence stays unknown.

## Fast checks

```sh
tools/test-protocol.sh
tools/test-spool.sh
python3 -m unittest discover -s rendezvous/minimal-server
python3 -m unittest discover -s experiments/light-vibrate
./gradlew --no-daemon :app:assembleDebug :app:lintDebug :app:testProtocol :app:testSpool
```

Use the exact final APK for installation checks. Record its SHA-256 and verify v1 signing for API18 devices. Recheck after source/resource changes. Physical validation lives in `docs/compatibility.md`; leave unrun checks visibly unrun.

## Preserve these boundaries

- Platform APIs and a small APK; minSdk18, guarded newer APIs, no phone-side external runtime.
- User-visible ON/OFF. Restore only a durably user-enabled ON session, visibly in the foreground where Android allows. Explicit OFF must disarm all restoration. Clean up sensor listeners, vibration, network work and the CPU wake lock on every stop path.
- Text HTTP with per-node authentication, explicit insecure-HTTP opt-in, normal TLS/hostname validation, no redirects carrying credentials.
- Durable bounded endpoint-scoped observation storage, independent of network retries; acknowledge only confirmed batches and report overflow. Collect-only must make no network requests or physical actions.
- Bounded input, exact actuator grammar, persisted action cursor before effects, truthful interrupted outcomes. Never “fix” uncertainty by replaying a physical effect.
- No invented sensor values, inferred motion presented as measurement, or fabricated device passes.
- No secrets, private signing keys, live device logs or rendezvous data in Git.
- Do not add a sensor, actuator, dependency or distributed-system abstraction merely because it is available. Require a concrete need and a testable boundary.

The consumer can be awk or [Mishe](https://github.com/genaforvena/mishe-tauftauf); keep that choice outside the APK. Short, inspectable feedback loops and explicit unknowns matter more than more framework.

<!-- mishe-tauftauf plant contract -->

# Working in Mishe

Read this repository's AGENTS.md, doctrine, role charter and restored notes.
Start from the chat trigger and read the full dashboard through
mishe-tauftauf --home SITE pain read ROLE --launcher dashboard.
Tmux and its lease establish presentation liveness only. Missing, stale or failed
observations remain UNKNOWN or RED.

Choose useful work from observations, edited walls and addressed chat. Planning,
investigation, docs editing and handoff are valid turns. Keep your plate, findings
and next action in SITE/walls/ROLE.md. Coordinate overlapping edits and preserve
peers' work. Ask peers through addressed messages on the visible shared tape.
System 1 advice can help choose an approach; it is not a planning gate.

Each blocker names resolver, missing evidence, one bounded action to produce it
and disposition time. Address the resolver and at cutoff resolve, escalate or
explicitly defer to a named trigger. Continue useful independent work. Diagnose
owned dependencies and permitted alternatives before requesting genuinely
missing authority. permit recover and permit resolve record recovery; they add
no selection or settlement gate. The operator is the human owner, not a pane or
role. Never park authorized work waiting on an operator window or routine approval.

Try ambitious initiatives live within granted owned scope. Name prediction,
observation and keep/revise/revert decision. Running-code changes require
deterministic checks, independent reading, observable snapshot activation with
visible failures and a tested revert path. Use the reviewed verify recovery
exercise before claiming verified delivery. Make successful experiments canonical
and remove superseded code paths; Git history preserves the route back.
Preserve frozen registrations, resource budgets, provenance and external authority.

Use one shared Git checkout and only main, locally and remotely. Authors check
and commit their scoped work; Genome pushes main and checks exact-SHA CI and live
consumers without authoring or gating another mind's commit. Source edits do not
silently change running code. Check activated bytes, actual caller and live pane.

Append readable chat through the canonical CLI with event, evidence and next
action. No inline JSON. Keep evidence, notes, experiments and snapshots under the
gitignored site; never commit them. wall outcome records evidenced contributions;
unchanged reconciliation is not an outcome.

Settle only the actual wake using seed yield --slug ROLE --wake N --file NOTES
--result changed|verified|blocked. Use --continue for concrete useful follow-up,
not unchanged polling. Settlement is a transport fact, not proof of success.
Reconcile prior effects after a crash before retrying. Stay within the owned site;
no other node, account or device authority is implied.
<!-- end mishe-tauftauf plant contract -->
