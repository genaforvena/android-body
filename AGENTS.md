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
