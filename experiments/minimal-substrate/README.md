# minimal-substrate

Retained bounded read-only probe runner for the minimal-substrate
investigation: harmless identity/environment/clock probes against the owned
Note3, each record labeled with its execution context, plus a device-side
persisted trivial-script rerun and a capture of the in-process identity
observation delivered through existing text delivery.

`probe.py` runs a fixed allowlist of read-only `adb shell` probes — no
arbitrary command execution, no device mutation except one bounded
app-private scratch file that is deleted again, no radio/camera/mic/
location, no downloaded code. Running the script is the only ON; not
running is OFF; nothing survives the process except bounded artifact files.

Contexts (discriminator bar 4): `host` = adb shell (uid 2000), never
APK-identity evidence; `run-as` = org.androidbody app uid via debuggable
run-as, never APK-uid evidence; `apk-uid` = observation produced inside the
org.androidbody APK process (session-start in-process identity probe,
delivered through existing text delivery, retained in the durable consumer
spool). `apk-dex` records host-side installed-byte correlation —
explicitly not execution evidence. run-as exit0-with-failure ("corrupt
installation") is detected and never recorded as success.

Probes: `host-identity` (`id`), `host-environment` (`dumpsys sensorservice`),
`host-clock` (`date -u`), `runas-identity` (`run-as … id`),
`runas-status` (`/proc/self/status`), `runas-selinux` (`/proc/self/attr/current`),
`runas-denied` (another app's private file; denial expected, stderr retained),
`host-interrupt` (`sleep 30` + runner SIGINT, truthful receipt),
`apk-identity` (retained in-process observation from the spool copy),
`apk-dex` (installed APK dex correlation), `scratch-rerun` (fixed trivial
text script written to app-private scratch via run-as, run twice, deleted,
source+SHA-256+provenance retained).

Since the 2026-10-16 install the APK itself also emits a class-4 session-start row —
`probe exec uid=<app uid> cmd=<files>/probe.txt output=hello exit=0` — executing the
app-written 0700 script under the app UID: SELinux `untrusted_app` ALLOW on the Note3
(API 21). It is bounded (≤4,096 B merged output, ≤5 s, one file, child destroyed on
timeout), runs in every session including collect-only, and is one observed exec shape
rather than a general execution capability. Evidence and limits: [verification
record](../../docs/verification.md).

Row shapes and consumer semantics (recorded 2026-10-16, genome DM 99948 handoff):

- ALLOW: `probe exec uid=<app uid> cmd=<app-private path> output=<bounded> exit=0
  session=<id>`. `cmd=` names the app-written probe file — a constant the APK rewrites
  every session; no client input reaches it. Consumers MUST NOT render it as a
  client-reachable command.
- DENY: `probe exec unavailable reason=<exception class + message> session=<id>` —
  e.g. `IOException Cannot run program "/data/data/org.androidbody/files/probe.txt":
  error=13, Permission denied`. `reason=` is variable-length and may carry a quoted
  path; never assume the old single-token shape when parsing.
- DAC-setup: `probe exec unavailable reason=dac-setup session=<id>` — probe-setup
  failure (`setExecutable` could not set 0700 before the run), distinct from a MAC
  denial; never collapse the two when classifying.
- TIMEOUT: `probe exec timeout reason=no-exit destroyed=<true|false> session=<id>`
  (unchanged).

All four observed shapes are ≤~130 B, far under the 1,007 B spool-line bound
(`ObservationSpool.MAX_LINE_BYTES`, epoch prefix included). The bound constrains any
future write receipt exactly as eval outcomes are clamped (`EvalOutcome.java`): the
receipt line must fit the budget or be truncated with `truncated=true`, never silently.

Bounds (env-overridable): per-command timeout with child kill (default 10s),
per-line output cap (default 1024 bytes, matching the text-delivery per-line
limit), total output cap (default 64 KiB), artifact retention (newest 20;
N<=0 keeps none). Interrupted outcomes (timeout, non-zero exit, missing adb,
undecodable output, exit0-with-failed-operation) are recorded truthfully in
a dated artifact; nothing is retried or hidden.

Usage: `python3 probe.py [host-identity|host-environment|host-clock|runas-identity|runas-status|runas-selinux|runas-denied|host-interrupt|apk-identity|apk-dex|scratch-rerun|all]`
Exit: `0` every probe reached its expected outcome · `1` any did not · `2` usage error.

Tests: `python3 -m unittest discover -s experiments/minimal-substrate`

## Bounded evaluator

The minimal-substrate investigation includes a bounded execution evaluator
(`app/src/main/java/org/androidbody/BoundedEvaluator.java`) for the fixed
grammar `identity`, `clock`, `read <path>`, `env`, plus the consumer
`write <path> <content>` and `exec <path>` verbs added by `d54b382` and shipped
in the published download (not in the Note3 install; row shapes
and limits in [actions](../../docs/actions.md#bounded-eval-probes)). It was independently
reviewed by witness (wake 37709, 2026-10-08) and found "NOT ready for
phone trial" with truthfulness defects (stub read returning the path string,
fabricated identity, wall-clock instead of elapsedRealtime, no session state).
Subsequent commits fixed the identified defects: `b82dab0` (API-1 bounded
read), `9863007` (daemon thread pool), `e69d798` (wire into
`BodyService.execute` as `eval` action branch with collect-only skip,
failure classification, result identity hash, truncation marking, and
session close). The evaluator is now live in the app. A bounded phone
	trial on the owned Note3 (2026-10-12, discover wake 48948) executed
	10 of 11 expected probes; the scratch-rerun failure was root-caused to
	adb argv rejoining (harness quoting, not device denial). The harness
	was corrected (echo builtin instead of absent printf; inner-rc capture
	for unreliable adb exit codes) and re-verified on Note3 2026-10-12:
	all 11 probes demonstrated on-device. Physical acceptance CLOSED.
