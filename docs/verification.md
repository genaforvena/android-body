# Verification record

Checked 2026-10-07; updated through 2026-10-14. Version 0.2 adds persistent ON and durable collect/upload-later behavior. Host/build evidence is separate from Android runtime and physical-device evidence.

## Built artifact

- Application: `org.androidbody`, version `0.2.0` (code 2)
- Build: debug APK, Java source 8, JDK 17+, Gradle 8.11.1, Android Gradle Plugin 8.10.1
- Compile/target SDK 36, minimum SDK 18
- Published APK ([downloads](../downloads/README.md)): 104,612 bytes, SHA-256 `8f2c8b18b7339466695eebef23e3e804104f0379b7c51668e97261ac97d66ced` (eval-wiring build `51eaf34`; verify against [SHA256SUMS](../downloads/SHA256SUMS))
- Installed on Note3: 119,972 bytes, SHA-256 `a5cc750ecb5876e5f7a5cdc71bdff8a6772e6f99373489c367732b34a11cf468` — BleStatus-wiring build `079db2e`, installed 2026-10-13 ~09:34Z, byte-identical to the current local build of the same source (pulled and `cmp`-checked). Supersedes, in order: BLE-fix `efc78fd` build `1bb5029f` (installed 2026-10-13 ~04:03Z), onScanFailed-fix `b163324` build `27dc42c9` (~07:30Z), BleScan build `7eb54e9b` (2026-10-11 17:35Z) and the earlier 0.1/0.2 lineage APKs.
- `apksigner verify --verbose`: PASS, v1 and v2 signatures verified
- `aapt dump badging`: confirms version 2, minimum 18, target 36 and the intended permissions, including boot completion

The signer certificate SHA-256 `d23dcc9d24fbdce556150931f54051b44fdf45c465694710d687c88464be028a` has been constant across the current lineage since the 2026-10-11 signing-blocker resolution (self-heal checkpoint and every Note3 redeploy since), preserving signing continuity for in-place upgrades. The private key is not in the repository. `apksigner` reports the usual v1 warning that Gradle's `META-INF/com/android/build/gradle/app-metadata.properties` is not covered by the v1 JAR signature; the complete APK's v2 signature verifies. This is not a production release-signing identity or device certification.

Session start wires BleScan (`ble_scan start` spool events in every session since the BleScan build) and the eval route (`executeEval` since the eval-wiring build `8f2c8b18`, installed 2026-10-12T21:05Z; every eval probe since executes in-app). Both are present in the current installed APK. Per-run deployment detail is in Git history.

## Checks actually executed

| Check | Result |
|---|---|
| `:app:assembleDebug` | PASS |
| `:app:lintDebug` | PASS, zero errors and two warnings |
| `:app:testProtocol` / standalone protocol harness | PASS, 68 assertions |
| `:app:testSpool` / standalone spool harness | PASS, 2,788 assertions |
| Rendezvous unittest suite | PASS, 18 tests |
| Shell/awk demo unittest suite | PASS, 8 tests |
| Additional independent spool/reload checks | PASS, 1,711 checks |
| Additional independent journal truncation/CRC checks | PASS, 189 checks |
| Additional independent persistent-settings checks | PASS, 24 checks |

The lint report for run 37593836353 lists two warnings: `UnusedAttribute` because API18 ignores manifest `usesCleartextTraffic` (transport validation still requires explicit HTTP opt-in), and `AndroidGradlePluginVersion` because the pinned Gradle wrapper 8.11.1 is older than the reported 8.14.5. Neither is an Android source finding; legacy service/vibration paths are intentionally guarded by SDK checks and compilation also reports deprecation notes.

The queue tests cover process exit/reopen, per-endpoint isolation, durable append/acknowledgment, immutable in-flight tokens, overflow bounds/loss notices, every incomplete transaction tail, complete corruption rejection, compaction, single-owner locks, explicit corrupted-queue discard, and randomized state replay. File-descriptor checks establish that ordinary enqueue/ACK extends the journal instead of rewriting the retained data. The full queue is compacted only at its bounded threshold.

Persistent-state checks cover endpoint-matching enable markers, failed preference OFF with independent marker deletion, newer user-stop records and explicit-ON overrides, API18 guards and the eight-destination limit. Source review also covered stopped-session ordering, OFF/clear races, mode-save failures, notification modes, local-storage errors versus network errors, and durable action receipts. No remaining known high/medium source blocker was found in this freeze. These checks do not certify OEM survival or physical effects.

## Published repository and CI

The public [GitHub repository](https://github.com/genaforvena/android-body) carries the source, CC0 license, third-party notices and the installable debug APK. `.github/workflows/check.yml` runs on every push and pull request: the protocol and spool shell harnesses, the rendezvous, light/vibrate and perception unittest suites, then `:app:assembleDebug :app:lintDebug :app:testProtocol :app:testSpool :app:testRestore`, uploading the debug APK (`android-body-debug`) and the lint report.

Latest recorded checkpoint: `fcfb546` (docs: correct the light-resumption detector entry for the review follow-up), exact-SHA [run 38540724420](https://github.com/genaforvena/android-body/actions/runs/38540724420) completed successfully 2026-10-14T09:13Z; its tree contains `45950b2` (docs: CI checkpoint refresh + pre-landing clamp correction), `57ec309` (truncated-final-line fix; compact view dropped the detector's per-second heartbeat age), `ad5895e` (light-resumption detector; exact-SHA [run 38538988829](https://github.com/genaforvena/android-body/actions/runs/38538988829) success), `eff74d6` ([run 38533078593](https://github.com/genaforvena/android-body/actions/runs/38533078593) success) and `e54e0db` ([run 38532527398](https://github.com/genaforvena/android-body/actions/runs/38532527398) success). CI runs on the pushed tip, so `45950b2` and `57ec309` share the `fcfb546` run. Earlier recorded checkpoints each passed exact-SHA CI with the same boundary suites, Android build/lint and artifact uploads: `0c37202` ([run 38539426861](https://github.com/genaforvena/android-body/actions/runs/38539426861)), `ca210ac` ([run 38522055819](https://github.com/genaforvena/android-body/actions/runs/38522055819)), `6b8148d` ([run 38404873352](https://github.com/genaforvena/android-body/actions/runs/38404873352)), `c852d27` ([run 37597970027](https://github.com/genaforvena/android-body/actions/runs/37597970027)), `a0aa853` ([run 37593836353](https://github.com/genaforvena/android-body/actions/runs/37593836353)).

Uploaded APK members from several of those runs were independently measured and `apksigner`-checked: manifest-range v1/v2 with explicit API18 v1 and API24 v2 ranges; a changed-`classes.dex` API18 negative control was rejected for manifest digest mismatch, and no v2 tamper test is claimed for the rebuilt ZIP. The `a0aa8532` run's uploaded member was not independently measured or signature-checked. The measured CI APK bytes and public signer fingerprints differed from the then-published APK's (Android Debug subjects on both sides, so signer equality is not established either way); no update acceptance, API18 installation or physical-device behavior follows. CI builds its own debug-signed APK each run; it is not the published download.

The published APK download has been exercised through GitHub and byte-checked (current value under [Built artifact](#built-artifact)); the earlier 88,103-byte published APK was checked the same way.

## Android runtime evidence for this version

The full **API18 / Android 4.3.1 emulator** acceptance suite below ran on the preliminary version 0.2 APK `ff03c32eccb690fb330ec2b3c22167938c0e4f4ff2905c7bfe0dc1a260dd8ee7`. The final APK above changes only the queue's default retention constants to 2 MiB / 24,576 lines; queue format, algorithms, service and UI logic are unchanged. The final defaults passed both Java suites and a bounded-heap host stress test. The focused final-artifact smoke **PASSED** on API18: install, ON, observation/vibration roundtrip, live collect-only (nine saved records and zero HTTP after transition), live backlog drain and OFF. After OFF there was no queue growth, upload, running service or held CPU wake lock. The queue inspector used the final constants. The full complex suite before the constants change also passed: install/cold launch, native ON and actual notification OFF; offline records survived process SIGKILL from Home (the service restarted with a new PID, retained the original 12 lines, continued to 27, and delivered all 27 on reconnection); sampling continued while HTTP was held (3 to 9 saved); rapid OFF/ON/OFF/ON with an old blocked request left the new session operational; live collect-only saved 15 lines with zero HTTP requests after mode transition settled and did not execute the queued command; endpoint A's 18 pending lines stayed separate while endpoint B was active, and returning to A drained all 18 and resumed its queued action without restarting the process.

These are emulator runtime/transport observations; a vibration receipt remains physically unverified. Saved ON restored automatically after a cold power cycle of the same persisted emulator data, without opening the activity. Explicit OFF stopped both sampling and network work and stayed OFF after another cold start and manual app launch. An in-guest API18 adb-reboot command separately crashed the QEMU engine before Android boot; that command is not claimed as a pass. The cold-start boot-receiver scenarios did pass. **API34 / Android 14:** the preliminary version 0.2 APK installed and the app/permission UI rendered. A bounded recovery attempt still encountered system-wide ANRs involving System UI, system, Bluetooth, launcher and phone processes. ON/collection behavior on API34 is not established.

## Retention memory check

A temporary host build with the final 2 MiB/24,576-line limits passed fill, near-full 4 MiB journal reopen, overflow, compaction and drain under a 32 MiB JVM heap plus an 8 MiB synthetic live reserve for the rest of the app. Both 80-byte and 120-byte record workloads passed in about one second. Sampled heap peaks were about 27 MiB, with roughly 12–13 MiB live after GC including the reserve. These are host JVM measurements, not an Android device memory certification.

The larger 4 MiB option was not shipped: under the same 32 MiB heap plus reserve its near-full journal reopen stalled. The chosen 2 MiB buffer holds approximately 10 hours at representative 80-byte records (metadata counts toward the byte limit), with actual retention dependent on record sizes and traffic. Overflow is explicit; it is not a lossless time-window guarantee.

## Physical boundaries

**Samsung SM-N900 (Note3), Android5/API21, firmware `LRX21V.N900XXSEBRH3`: bounded physical smoke ran on 2026-10-07.** The installed final 0.2.0 APK matched the SHA-256 above and passed v1/v2 signature verification. Connection was authenticated HTTP through authorized USB reverse forwarding to a host-loopback listener; no LAN exposure, TLS bypass or battery/security-policy changes.

Native ON/OFF controls exercised through fresh accessibility selectors; actual battery, ambient-light and accelerometer records reached the text rendezvous and read-only consumer. Startup `no_sample` remained unavailable rather than becoming zero. One 200ms vibration request produced requested/succeeded receipts with `evidence=api_return verification=unverified`. Motor movement was **not independently verified**; the request was not retried. Collect-only saved observations while the server queue stayed unchanged after transition; displayed saved count increased from 3 to 15. Returning to sending drained the retained records with original times. OFF produced no queue additions during a 10s observation, no running Body service or held `AndroidBody:session` wake lock, and no persistent enable marker. The consumer aged its evidence to stale and suppressed current derived magnitude. ON restored fresh-clock-conditional observations. Killing the app's own process from Home restored it with a new PID and a new session; delivery resumed. This is process-loss evidence, not a reboot/OEM-survival claim. With the display confirmed OFF, collection and delivery continued through a 15s charging interval. Multi-hour, unplugged and thermal behavior remain untested. A 35s deliberate USB mapping outage left the host observation cursor unchanged and current perception stale; restarting the bridge restored backlog delivery and subsequent current readings without another action request. Repeated transport loss occurred during old Samsung `adb reverse --list` polling. That probe was removed; generation-based connection observation and mapping creation kept the transport stable across subsequent physical checks. The debugging-daemon cause was not independently established. The phone clock was approximately 17s behind the host. The consumer did not alter or calibrate it; freshness remains explicitly clock-conditional.

The integrated host checks passed: protocol 68 assertions, spool 2,788 assertions, rendezvous 18 tests, light/vibration 8 tests, and perception 7 tests. Android source and APK were unchanged in this integration; no new Android build/lint pass is claimed.

Real Xiaomi/Redmi10 and contemporary physical Android validation are **NOT RUN**. Actual motor behavior, sensor calibration, old firmware HTTPS trust, Xiaomi process retention, heat/battery drain, reboot restoration on this handset, and multi-hour screen-off continuity remain unverified. Use the [device checklist](compatibility.md#physical-validation-checklist).

Neither `START_STICKY` nor the ON-only partial wake lock guarantees uptime or bypasses Doze, Force stop, notification controls or OEM restrictions. The saved ON bit is an intention, not proof of live collection. Android's vibration API return remains `verification=unverified` without independent physical evidence.

## Deployed Note3 APK — emitted channels and recorded device history

The frozen deployed consumer (`body/runtime/watch.py`) has observed the installed Note3 APK's emissions across 2026-10-10..14; per-snapshot detail remains in Git history. Current deployed bytes == source `57ec309` (sha256 `bb9a71c85bdc09500edaeda77cf8bda60b91f10ae938c2a2d2e5087075a11293`, deployed 2026-10-14 09:12Z).

Emitted channels (consumer-view evidence of the installed APK's emissions, not server-side receipt, motor proof, calibration or clock synchronization):

- Battery (level/charging), ambient light (lux, accuracy), accelerometer (x/y/z with derived magnitude and its source), Wi-Fi RSSI, protocol-v2 clock fields (`sensor_time_ns`/`phone_elapsed_ms`), `ble_status` getter fields (`scanner_api`/`advertiser_api` SDK surface vs `scanner_getter`/`advertiser_getter` read-only getter access; API<21 and null adapter report `unavailable`), `ble_scan` lifecycle events, allowlisted-beacon `ble_sighting` rows while ON (scanner-visible evidence, not presence), and bounded eval probes (identity, clock, allowlisted `/proc` reads, env).
- Note3 reports `advertiser_supported=unsupported`: it cannot advertise BLE (milestone-5 decision input, 2026-10-13).
- BLE scan failures on Note3 API21 return code=2 (`SCAN_FAILED_APPLICATION_REGISTRATION_FAILED`); the Xiaomi >5-scans/30s literature cause does not explain the observed 1/120s cadence — cause UNKNOWN. Recovery has been observed only at session boundaries (app restarts).
- The light channel detects genuine environmental change: 61 transitions in ~17 min on 2026-10-13 (rapid ~5–10s oscillation, not a stable ON/OFF cycle) — environmental oscillation, not presence/occupancy proof.

Recorded freezes (user-gated stalls, all resolved; consumer-view evidence, not motor proof):

- Freeze #3 (~64 min), #4 (~6h36m; root cause: data-wiping reinstall 28s before onset), #5 (~4h01m; resolved by phone restart), #6 (~2h50m; crash `IllegalStateException Spool is closed` at `BleScan.loop`, recovered by app restart + tunnel repair), #7 (~20 min; mid-eval stall, one interrupted outcome, no replay issued).

Deployed software current state (deployment chains and per-run checks in Git history):

- `watch.py` has carried, in order: the BLE evidence channel, Wi-Fi/BLE RF + node-status hysteresis, protocol-v2 clock fields (`phone_elapsed_ms` on every sensor event; pre-v2 spooled records render null with reasons, never interpolated), clock-skew bounds (`acquisition_span_stats`/`clock_agreement_reason`/`freshness_basis`), the per-session excursion log (bounded 128 lines/node; v2.1 retention fields live since 2026-10-11T19:54Z), the class-B stop detector (deployed and independently verified live 2026-10-12) and the light-resumption detector below. Each deployment exercised its backup/revert path and live activation under health-owned service restarts.
- The view's clock note is the computed bounded reason (commit `ee7fd7a`); a hardcoded "UTC-aligned <0.2s" string was removed as a fabricated device pass, with regression test `test_view_clock_note_is_computed_not_hardcoded` keeping it computed.
- `BoundedEvaluator.readBoundedBytes()` streams 1 KiB chunks capped at `maxBytes` (commit `b82dab0`), replacing API26+ `Files.readAllBytes` on the bounded path.
- BLE scanning on Note3 no longer immediately fails after the `BLUETOOTH_ADMIN` permission fix (`efc78fd`); `onScanFailed` sets `stopped=true` (`b163324`) so a scan failure exits the loop within ~1s instead of sleeping 60s and retrying indefinitely — the next-failure exit remains a prediction until observed.
- Bounded host snapshot lifecycle (per-node publication repair, byte-switch under lock, revert/reapply) was exercised with independent witness acceptance on 2026-10-07; the publication repair has been live since.
- Isolated `:ble-probe` diagnostic (2026-10-07): JVM report formatting and Android compile/package/lint/signature verified; no APK installation or device BLE result.
- Host reboot 2026-10-14 (~15h downtime): all 16 `android-body*` units auto-restarted with no failures; the durable spool preserved every phone-generated record and the backlog drained completely on reconnect — zero data loss; installed APK re-confirmed `a5cc750e`.

## Bounded probe runner

`experiments/minimal-substrate/probe.py` is canonical in the shared checkout with `test_probe.py` and its README: a fixed allowlist of read-only `adb shell` probes (`dumpsys package org.androidbody`, `dumpsys sensorservice`, `date -u`) — no arbitrary command execution, device mutation, radio/camera/mic/location or persistent state. Bounds: per-command timeout with child kill (default 10s), per-line 1,024-byte and per-probe 64 KiB output caps, artifact retention (newest 20). Interrupted outcomes are recorded truthfully; nothing is retried or hidden.

Extended 2026-10-11 with execution-context labels (`host`/`run-as`/`apk-uid`), expected-denial semantics with stderr retained, a SIGINT interrupt probe with truthful receipt, a device-side persisted scratch write/run1/run2/delete/verify sequence with source+SHA-256+provenance, an `apk-identity` capture, and an `apk-dex` host-side installed-byte correlation (explicitly not execution evidence). 24 unit tests pass.

Executed on Note3 2026-10-12 (~08:18–08:28Z): 10 of 11 expected probes ok; `scratch-rerun` failed on adb argv rejoining (harness quoting, not device denial — a single-invocation control succeeded), and `adb shell` exit codes proved unreliable on this device (`adb shell false` → rc=0), so device-side rc must be captured explicitly. A 2026-10-11 identity probe (`dumpsys package`) reported `userId=10224 gids=[3002, 3003]`, `versionCode=2 targetSdk=36`, `versionName=0.2.0`; later probes show uid 10225 with supplementary groups including 3001, consistent with the deployed `BLUETOOTH_ADMIN` permission. run-as app uid 10225 (`untrusted_app`) is functional for id/status/selinux reads and in-context script exec; `run-as` exit0-with-failure ("corrupt installation") is detected and never recorded as success.

## Reproduce the host checks

```sh
# The system default java is JDK 8 without javac; export a JDK 17+ install first:
#   export JAVA_HOME=/home/mesh-home/.local/jdk21
#   export ANDROID_HOME=/home/mesh-home/.local/android-sdk
tools/test-protocol.sh
tools/test-spool.sh
python3 -m unittest discover -s rendezvous/minimal-server
python3 -m unittest discover -s experiments/light-vibrate
python3 -m unittest discover -s experiments/minimal-substrate
python3 -m unittest discover -s experiments/perception
./gradlew --no-daemon :app:assembleDebug :app:lintDebug :app:testProtocol :app:testSpool
"$ANDROID_HOME/build-tools/35.0.0/apksigner" verify --verbose \
  app/build/outputs/apk/debug/app-debug.apk
```

Install dependencies from official vendors, accept the SDK agreement, and keep generated signing keys outside version control. The Gradle distribution checksum is pinned. Recheck APK size/hash after source/resource changes; independently signed/debug-built artifacts can have different bytes and upgrade identities.

## Eval outcome line bound — confirmed latent defect; post-gate fix owned by genome — 2026-10-14T08:37Z

- Trigger: discover DM 74716 + genome DM 74745/74746 — eval outcome lines can exceed the observation spool's per-line bound and disarm the session.
- Confirmed by two independent host-JVM probes (real shipped `Protocol`/`BoundedEvaluator`/`ObservationSpool` classes): eval caps command output at 1024 B, but the spool accepts observation lines only up to 1007 B. Measured: `read /proc/meminfo` 1143 B, `/proc/self/status` 1089 B, `env` 1068 B REJECTED (`Invalid observation line length`); `identity` 180 B / `clock` 124 B accepted. The rejection throws `IllegalArgumentException` inside `BodyService.enqueue`; `network()` does not catch it, so `fail()` disarms ON.
- Second reachable overflow (genome): `read_denied path=<client path>` echoes the whole client path (`BodyService.java:402-404`); any path > 956 B overflows the 1024 B wire cap. Reproduced 1000 B -> 1051 B rejected.
- Clamp must be UTF-8-byte-based (genome): `encodeLine` enforces a byte limit and `read` decodes US-ASCII, so bytes >= 0x80 become U+FFFD (3 B each); reproduced 400 U+FFFD chars = 1200 B rejected.
- Disposition: accepted into the milestone-5 gate base as a documented hazard + contract correction, NOT a gate blocker (research-methods). Eval is the only spool enqueue producer with variable-length content, so the defect stays latent; pre-registered gate constraint: no eval verb whose output can reach 1024 B in a label-carrying session until the fix ships.
- Fix (genome, post-gate): clamp the eval outcome line to <=1007 B + permanent host test + `protocol/README.md:120` line-level-invariant amendment. Gated on M5 gate passage (2026-10-14T18:00Z) + APK-churn clearance (DM 70790); no APK churn before then.
- Fix design corrected before landing (genome wake 74788; docs re-ran the probes 2026-10-14T09:06Z): the first recorded clamp diff fails its own goal in two ways — it clamped the tail after `Protocol.event`'s trailing LF (`Protocol.java:114`), so every clamped outcome became three spool records with a prefix-less tail line (reachable by any long output, ASCII included), and it counted a surrogate half as 1 UTF-8 byte, so a 500-emoji `read_denied` path clamped to 1905 B and was rejected (`Observation line too large`). The corrected form clamps the line content with the epoch inside the byte budget, counts code points and appends the LF last (`artifacts/genome-wake74788-clamp-astral/EvalOutcome.java`). Docs re-compiled and ran genome's two probes against the real classes: probe output byte-identical to genome's recorded output; dry-run 7/7 PASS, 2 records per outcome, max line 1007 B. Host-JVM only; on-device reachability UNKNOWN (Note3 OFF).
- Unknown: on-device confirmation — Note3 OFF (last receipt 06:13:52Z); device `/proc/meminfo` size and the denied-path trigger unverified on hardware.
- Scope: docs record only. No source/APK/device/transport/actuator/cursor mutation.

## Light-cycle resumption monitor and detector

- Rule: `RESUME_LUX_MIN = 7.0` lux (`floor(log2(1+lux)) >= 3`, the consumer's own coarse-bucket boundary); predicate `lux >= RESUME_LUX_MIN and prev_lux is not None and prev_lux < RESUME_LUX_MIN`; log records carry `threshold_lux` and `prev_observed_unix`. The earlier 0.5-lux threshold sat inside the Note3's dim oscillation band (0.0 <-> ~1.24–1.35 lux; 751 unique bucket-transition rows with both endpoints <5 lux, 2026-10-07..13) and fired on routine dim oscillation; the entries the old rule fired on (lux 1.3224/1.2758 with prev 0.0) no longer fire.
- Known limitation: a genuinely dim (2–6 lux) resumption is not claimed — indistinguishable from the dim band at one poll. A resumption observed across a phone-silence gap is claimed, with the gap visible in `prev_observed_unix` (transition bounded by the gap, not measured inside it).
- Liveness: the monitor publishes an atomic heartbeat (`artifacts/light-cycle-monitor-state.json`); `watch.py` renders a `Light-cycle resumption detector` section — the full view reports status, heartbeat age, armed state and the last retained row verbatim; the compact view (cached to `events.txt`) reports status, armed state and last row without the per-second age. A stale/absent heartbeat renders `stale/detector-silent` or `unknown/no-monitor-heartbeat` — never calm.
- Unit `Restart=on-failure` -> `Restart=always` so a fired monitor (rc=0) re-arms instead of silently stopping.
- Deterministic exercise of the deployed bytes (9/9 scenarios PASS, synthetic space.json): dim->lit row; dim oscillation no row; silence->lit with no prior dim baseline no row; ramp 2.5->6.68->7.05 row at prev_lux 6.68. Live detection+routing exercised: stop -> pane `stale/detector-silent`; `kill -9` -> `Restart=always` re-armed with fresh heartbeat and new pid.
- Follow-up `57ec309` (independent review of `ad5895e`): `_last_monitor_row` no longer returns None on a partial final line, so a crash mid-append cannot hide complete rows; the compact view dropped its per-second `heartbeat_age`. 115 tests OK.
- Deployed bytes: `body/runtime/light_cycle_monitor.py` sha256 `96abef81…` (differs from source only by the documented `SPACE_JSON` path line and deploy note); service running with `--interval 30 --max-polls 3300` (past the 18:00Z gate); revert = `light_cycle_monitor.py.pre-deploy-20261014-0749Z` + restart.
- Retained log carries one superseded-rule row (lux 2.505, prev_lux null, no threshold_lux, 2026-10-13T07:12Z), preserved as historical evidence and labelled in the pane as predating the 7.0-lux rule; inadmissible under every check of research-methods' pre-registered M5 rule. Zero admissible resumption rows on record.
- Unknown: no live resumption has ever fired (Note3 OFF by explicit user action since 06:13:24Z); the heartbeat/armed path is exercised only on synthetic input and a dead-monitor drill.
- Evidence: `.mishe-tauftauf/artifacts/senses-wake74767-light-detector-controlled-exercise/`.
