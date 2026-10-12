# Verification record

Checked 2026-10-07; updated through 2026-10-11. Version 0.2 adds persistent ON and durable collect/upload-later behavior. Host/build evidence is separate from Android runtime and physical-device evidence.

## Built artifact

- Application: `org.androidbody`, version `0.2.0` (code 2)
- Build: debug APK, Java source 8, JDK 17, Gradle 8.11.1, Android Gradle Plugin 8.10.1
- Compile/target SDK 36, minimum SDK 18
- Published APK (installed on Note3): 100,245 bytes, SHA-256 `7eb54e9b682c0d3211b46f2f5d67ef8cd2fbc955c6c9cbeef73f03215335b1f4` (BleScan build installed 2026-10-11T17:35Z; prior installed APK was 88,103 bytes, SHA-256 `417719c5811ca0acf9546577b8ef54bd80e212d18a5acfa28fe139203d8a261b`)
- Current on-disk build (`app/build/outputs/apk/debug/app-debug.apk`, built 2026-10-11T14:20:39Z): 100,245 bytes, SHA-256 `7eb54e9b682c0d3211b46f2f5d67ef8cd2fbc955c6c9cbeef73f03215335b1f4`
- `apksigner verify --verbose`: PASS, v1 and v2 signatures verified
- `aapt dump badging`: confirms version 2, minimum 18, target 36 and the intended permissions, including boot completion

The version 0.1 and 0.2 signer certificate SHA-256 digests were compared and match, preserving signing continuity for an in-place upgrade. Its private key is not in the repository. `apksigner` reports the usual v1 warning that Gradle's `META-INF/com/android/build/gradle/app-metadata.properties` is not covered by the v1 JAR signature; the complete APK's v2 signature verifies. This is not a production release-signing identity or device certification.

**BleScan deployment gap — RESOLVED 2026-10-11T17:35Z:** `BleScan.java` exists in source (commit `59412b0`, origin/main, 2026-10-11 12:10:58Z) and is wired into `BodyService` session startup. The on-disk build (`7eb54e9b`, 100,245 bytes) includes BleScan classes (verified via `classes.dex` strings). The prior installed Note3 APK (`417719c5`, 88,103 bytes) did **not** include BleScan. Genome installed the BleScan build (`7eb54e9b`) on Note3 at 17:35Z; the app restarted and spool event #132053 (`ble_scan start beacon=MISHE-BEACON window_ms=60000 gap_ms=60000`) confirms BleScan loaded and started scanning.

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
The latest published checkpoint is `8c1e0e2` (docs: record class-B detector live-activation status — not live, restart pending; no source, APK or consumer change). Exact-SHA [GitHub Actions run 38186873600](https://github.com/genaforvena/android-body/actions/runs/38186873600) completed successfully. The prior completed checkpoint was `1c06c27` (docs: record class-B stop detector consumer deployment; no source, APK or consumer change). The prior completed checkpoint was `5eaeaa4` (docs: update freeze #5 duration and latest published checkpoint; no source, APK or consumer change). The prior completed checkpoint was `b0025d6` (docs: update freeze #5 duration in verification record; no source, APK or consumer change). The prior completed checkpoint was `365e9ff` (docs: record class-B stop detector in perception README; no source, APK or consumer change). The prior completed checkpoint was `e69d798` (feat(eval): wire BoundedEvaluator into BodyService.execute as eval branch; no APK change). Exact-SHA [GitHub Actions run 38181569370](https://github.com/genaforvena/android-body/actions/runs/38181569370) completed successfully. The prior completed checkpoint was `9863007`
The prior published checkpoint was `b82dab0` (BoundedEvaluator: API-1 bounded read to fix the minSdk18 lint failure; no APK change). Exact-SHA [GitHub Actions run 38167999951](https://github.com/genaforvena/android-body/actions/runs/38167999951) completed successfully. The prior completed checkpoint was `feaba79` (perception: retain protocol v2.1 evidence set per excursion window; no APK change). Exact-SHA [GitHub Actions run 38163909866](https://github.com/genaforvena/android-body/actions/runs/38163909866) completed successfully. The prior completed checkpoint was `a4719b9` (perception: emit bounded per-session excursion log at hello boundary; no APK change). Exact-SHA [GitHub Actions run 38162584354](https://github.com/genaforvena/android-body/actions/runs/38162584354) completed successfully. The prior feature checkpoint was `be5881c279f54f68327c71ebb39daf38f81cca72` (perception: name absent phone_elapsed field as protocol v1). Exact-SHA [GitHub Actions run 38149570660](https://github.com/genaforvena/android-body/actions/runs/38149570660) completed successfully.
Fifteen commits were published between `b8a4369` and `be5881c`, including the protocol v2 clock-agreement landing (`5806bb6` APK emission, `e3c0805` consumer parse, `625831d` docs) and the BLE evidence channel redeploy (`713f2b0`). Batch-final exact-SHA CI runs: `5806bb6` ([run 38146873239](https://github.com/genaforvena/android-body/actions/runs/38146873239)), `625831d` ([run 38148892320](https://github.com/genaforvena/android-body/actions/runs/38148892320)) and `be5881c` ([run 38149570660](https://github.com/genaforvena/android-body/actions/runs/38149570660)).

Origin/main then advanced to the docs-only commit `06d599bb6e7bd0030e418f8f3487af33768d7a1a` (this record; no source, APK or consumer change). Exact-SHA [GitHub Actions run 38152848401](https://github.com/genaforvena/android-body/actions/runs/38152848401) completed successfully on 2026-10-11T15:48:47Z.
Origin/main then advanced to the docs-only commit `75331013f843f43007f5f5fdae040d610ef2467a` (Note3 app reactivation record; no source, APK or consumer change). Exact-SHA [GitHub Actions run 38154268096](https://github.com/genaforvena/android-body/actions/runs/38154268096) completed successfully on 2026-10-11T16:09:23Z.
Origin/main then advanced to the docs-only commit `4113428` (distinguish published APK from current on-disk build; no source, APK or consumer change). Exact-SHA [GitHub Actions run 38155797367](https://github.com/genaforvena/android-body/actions/runs/38155797367) completed successfully.

The preceding checkpoint, `c852d27b4cc7c9fbdff3ce8b6ddb00d40cf6103e`, passed exact-SHA [run 37597970027](https://github.com/genaforvena/android-body/actions/runs/37597970027): protocol (68 assertions), spool (2,788), rendezvous (18 tests), light/vibration (8), perception (7), Android build/lint and both artifact uploads. Observed warnings included Java 8 bootstrap/deprecation, Node 20-to-24 action migration, setup-java v4 retirement, Ubuntu 26 migration and Node `punycode`/`url.parse` deprecations.
For run 37597970027, the downloaded APK member measured 54,109 bytes, SHA-256 `9f2608e69d1f3c6b734ef4af129bb6736416d330544da12fe490a783bca9b2d7`. Retained `apksigner` verified manifest-range v1/v2, explicit API18 v1 and API24 v2. The RSA-2048 debug signer fingerprint `995af7d19c614ca4bdd51585a7df3fa6f6638e882f0f535c7bf6fe331d5cdec7` differs from installed/published signer `039da4473796b1851e2546219e1ab005387956ba85425cea30cad9558f00c071` and preceding CI signer `a03eee7f5f810f8bb303fb033be36cc91626b99061eb0d7a037fa0d5a1e9bfbd`; no signing continuity, update acceptance or actual API18 installation follows. A changed-`classes.dex` API18 negative control was rejected for manifest digest mismatch; the rebuilt ZIP lacked a v2 block, so no v2 tamper test is claimed.

The preceding checkpoint, `43f17c36063c2337d4361fe2f5b0715e65cefd61`, passed exact-SHA run 37597457853. Neither checkpoint's CI success establishes physical-device behavior.

For the preceding checkpoint's run 37596299457, the downloaded APK member was 54,107 bytes, SHA-256 `ad8ae0e2baca6e76ea4553bbebe76a9912bc147cb1b8eae92d6c095e0e0c624b`. Retained Ubuntu `apksigner` 31.0.2-1ubuntu1 verified v1/v2 signatures, including explicit API18 v1 and API24 v2 checks. Its RSA-2048 debug signer certificate SHA-256 `a03eee7f5f810f8bb303fb033be36cc91626b99061eb0d7a037fa0d5a1e9bfbd` differs from both the prior CI signer and installed/published signer `039da4473796b1851e2546219e1ab005387956ba85425cea30cad9558f00c071`; no signing continuity or update acceptance follows. An API18 v1 negative control with a changed `classes.dex` byte was rejected for manifest digest mismatch; this does not test v2 tampering. The rebuilt negative-control ZIP lacked a v2 block.
The artifact ZIP's reported size/digest are upload metadata, not APK-member measurements. The APK member and lint report were separately inspected; these results apply only to this CI run.

The preceding published source checkpoint recorded here is commit `eb911611b23344394449426d97f931dc794fb66c`. [GitHub Actions run 37594711578](https://github.com/genaforvena/android-body/actions/runs/37594711578) **PASSED** for that exact SHA: protocol (68 assertions), spool (2,788), rendezvous (18 tests), light/vibration (8), perception (7), Android build/lint and both artifact uploads. Observed warnings included Java 8 bootstrap/deprecation, Node 20-to-24 action migration, setup-java v4 retirement, Ubuntu 26 migration and Node `punycode`/`url.parse` deprecations. Subsequent inspection measured the APK member at 54,110 bytes, SHA-256 `960f86c82057cee8f47a7611765a433328ff4ac1c81c81c6033f35f276069522`; its extracted public-certificate fingerprint `3c066a90c38979…

The preceding published checkpoint `a0aa8532d0b827c0785f46e9c9f4c8682ae976b8` passed [run 37593836353](https://github.com/genaforvena/android-body/actions/runs/37593836353) for that exact SHA, with the same listed test counts, Android build/lint and artifact uploads. Its lint report listed the same two warnings: API18 ignores manifest `usesCleartextTraffic`, and the pinned Gradle wrapper 8.11.1 is older than lint's 8.14.5 recommendation. Source independently gates HTTP on explicit user opt-in; no security test, upgrade or suppression is claimed. Its uploaded APK member was not independently measured or signature-checked.


The public [GitHub repository](https://github.com/genaforvena/android-body) contains the full source, CC0 license, third-party notices and the installable debug APK. The initial 54-file upload was verified against the staged Git tree, including executable modes and binary blob hashes.

[GitHub Actions run 37584419974](https://github.com/genaforvena/android-body/actions/runs/37584419974) **PASSED** for commit `d76f9badcd427ee102ad1d0ea923fe85525a76bc`: SDK setup, the boundary tests, Android build, lint and artifact uploads. The first run stopped before tests because the setup action tried to install the obsolete SDK package `tools`; the workflow now requests only `platform-tools` and avoids blanket acceptance of unrelated SDK add-on agreements.

The committed APK's download was exercised through GitHub and independently checked at 88,103 bytes with the SHA-256 above. The CI workflow builds another debug-signed APK; its bytes/signing identity are not claimed to match the committed download. A green build does not add physical-device evidence.

An independent comparison of the retained published APK and a retained APK member from run 37592181603 found different APK SHA-256 values and different public signer-certificate SHA-256 fingerprints: published APK `417719c5811ca0acf9546577b8ef54bd80e212d18a5acfa28fe139203d8a261b` / certificate `039da4473796b1851e2546219e1ab005387956ba85425cea30cad9558f00c071`; CI APK `e7c1f9f8df6d1896fd6045b2f1c14f2e60045ebad6c7509ea738669263913c72` / certificate `f4b34bd34b10374d7ea574048da8b00f7b316273e74ded581b65d9e57a19eb79`. Both certificates have an Android Debug subject, which does not establish signer equality. This comparison concerns that earlier CI artifact only; no update attempt, signature-validation result for that CI APK, or device acceptance is claimed.

## Self-heal checkpoint and Note3 redeploy signing blocker — 2026-10-11

Genome pushed two commits with exact-SHA CI this wake:

- `6b4861974f7c` (node-liveness hysteresis; not genome-authored): [run 38105784078](https://github.com/genaforvena/android-body/actions/runs/38105784078) **PASSED**.
- `460c8ecfd78d` (activity-side self-heal; genome): [run 38106141887](https://github.com/genaforvena/android-body/actions/runs/38106141887) **PASSED** — protocol 81 assertions, spool 2,788, rendezvous 18 tests, light/vibrate 8, perception 26, `:app:assembleDebug :app:lintDebug :app:testProtocol :app:testSpool` successful.

The self-heal re-starts `BodyService` from `MainActivity.onResume` when the persisted desired-on preference and run-enabled marker are both present, covering fresh installs (where `MY_PACKAGE_REPLACED` never fires), force-stop and process kill. Explicit OFF still disarms all restoration; the service re-checks desired-on and is idempotent. No JVM unit test covers the activity hook; it reuses the same start path as `RestoreReceiver`.

Host build evidence for `460c8ecfd78d`: the same Gradle tasks passed locally under JDK 21 (Temurin 21.0.12 at `/home/mesh-home/.local/jdk21`); built APK 57,099 bytes, SHA-256 `0a76234ec648a56fefe630791a3b8e4182221d8d3116b6b2391b6953ca97320f`. The system default `java` is JDK 8 without `javac`, and the site toolchain JDK 17 extraction has an empty `conf/security/policy/unlimited` directory, failing TLS initialization; neither can run Gradle 8.11.1. This repairs the 2026-10-08 attempt recorded below that could not build.

Install-over of `460c8ecfd78d` completed 2026-10-11 11:02:25Z (permit 36417): APK 56,995 bytes, SHA-256 `9e4fdc281c22e353bb42070a7c091a6adfc477255ac54c31081b77b44ca381b2`, v1+v2 signatures, signer cert `d23dcc9d24fbdce556150931f54051b44fdf45c465694710d687c88464be028a`. Installed bytes match built APK (exact-byte match). Sensing remained user-gated after install (desired_on=false from data-wiping reinstall). The signing blocker is resolved; no original keystore is needed.

## Android runtime evidence for this version

The full **API18 / Android 4.3.1 emulator** acceptance suite below ran on the preliminary version 0.2 APK `ff03c32eccb690fb330ec2b3c22167938c0e4f4ff2905c7bfe0dc1a260dd8ee7`. The final APK above changes only the queue's default retention constants to 2 MiB / 24,576 lines; queue format, algorithms, service and UI logic are unchanged. The final defaults passed both Java suites and a bounded-heap host stress test. The focused final-artifact smoke **PASSED** on API18: install, ON, observation/vibration roundtrip, live collect-only (nine saved records and zero HTTP after transition), live backlog drain and OFF. After OFF there was no queue growth, upload, running service or held CPU wake lock. The queue inspector used the final constants. The full complex suite below was not silently claimed as repeated against the final bytes.

- Install/cold launch, native ON and actual notification OFF
- Offline records survived process SIGKILL from Home: Android recreated the service with a new PID, retained the original 12 lines, continued to 27, and delivered all 27 on reconnection
- Sampling continued while HTTP was held: saved observations increased from 3 to 9
- Rapid OFF/ON/OFF/ON with an old blocked request left the new session operational
- Live collect-only saved 15 lines with zero HTTP requests after mode transition settled, and did not execute the queued command
- Endpoint A's 18 pending lines stayed separate while endpoint B was active; no A data was uploaded to B
- Returning to A and unchecking collect-only drained all 18 saved lines and resumed its queued action without restarting the process

These are emulator runtime/transport observations; a vibration receipt remains physically unverified. Saved ON restored automatically after a cold power cycle of the same persisted emulator data, without opening the activity. Explicit OFF stopped both sampling and network work and stayed OFF after another cold start and manual app launch. An in-guest API18 adb-reboot command separately crashed the QEMU engine before Android boot; that command is not claimed as a pass. The cold-start boot-receiver scenarios did pass. **API34 / Android 14:** the preliminary version 0.2 APK installed and the app/permission UI rendered. A bounded recovery attempt still encountered system-wide ANRs involving System UI, system, Bluetooth, launcher and phone processes. ON/collection runtime remains unverified on this emulator; this is neither a service-flow pass nor evidence of an Android Body failure. The emulator was stopped rather than retried indefinitely. Earlier version 0.1 results are not reused as version 0.2 persistence evidence.

## Retention memory check

A temporary host build with the final 2 MiB/24,576-line limits passed fill, near-full 4 MiB journal reopen, overflow, compaction and drain under a 32 MiB JVM heap plus an 8 MiB synthetic live reserve for the rest of the app. Both 80-byte and 120-byte record workloads passed in about one second. Sampled heap peaks were about 27 MiB, with roughly 12–13 MiB live after GC including the reserve. These are host JVM measurements, not an Android device memory certification.

The larger 4 MiB option was not shipped: under the same 32 MiB heap plus reserve its near-full journal reopen stalled. The chosen 2 MiB buffer holds approximately 10 hours at representative 80-byte records (metadata counts toward the byte limit), with actual retention dependent on record sizes and traffic. Overflow is explicit; it is not a lossless time-window guarantee.

## Physical boundaries

**Samsung SM-N900 (Note3), Android5/API21, firmware `LRX21V.N900XXSEBRH3`: bounded physical smoke ran on 2026-10-07.** The installed final 0.2.0 APK matched the SHA-256 above and passed v1/v2 signature verification. Connection was authenticated HTTP through authorized USB reverse forwarding to a host-loopback listener; no LAN exposure, TLS bypass or battery/security-policy changes.

- Native ON/OFF controls exercised through fresh accessibility selectors; actual battery, ambient-light and accelerometer records reached the text rendezvous and read-only consumer. Startup `no_sample` remained unavailable rather than becoming zero.
- One 200ms vibration request produced requested/succeeded receipts with `evidence=api_return verification=unverified`. Motor movement was **not independently verified**; the request was not retried.
- Collect-only saved observations while the server queue stayed unchanged after transition; displayed saved count increased from 3 to 15. Returning to sending drained the retained records with original times.
- OFF produced no queue additions during a 10s observation, no running Body service or held `AndroidBody:session` wake lock, and no persistent enable marker. The consumer aged its evidence to stale and suppressed current derived magnitude. ON restored fresh-clock-conditional observations.
- Killing the app's own process from Home restored it with a new PID and a new session; delivery resumed. This is process-loss evidence, not a reboot/OEM-survival claim.
- With the display confirmed OFF, collection and delivery continued through a 15s charging interval. Multi-hour, unplugged and thermal behavior remain untested.
- A 35s deliberate USB mapping outage left the host observation cursor unchanged and current perception stale; restarting the bridge restored backlog delivery and subsequent current readings without another action request.
- Repeated transport loss occurred during old Samsung `adb reverse --list` polling. That probe was removed; generation-based connection observation and mapping creation kept the transport stable across subsequent physical checks. The debugging-daemon cause was not independently established.
- The phone clock was approximately 17s behind the host. The consumer did not alter or calibrate it; freshness remains explicitly clock-conditional.

The integrated host checks passed: protocol 68 assertions, spool 2,788 assertions, rendezvous 18 tests, light/vibration 8 tests, and perception 7 tests. Android source and APK were unchanged in this integration; no new Android build/lint pass is claimed.

Real Xiaomi/Redmi10 and contemporary physical Android validation are **NOT RUN**. Actual motor behavior, sensor calibration, old firmware HTTPS trust, Xiaomi process retention, heat/battery drain, reboot restoration on this handset, and multi-hour screen-off continuity remain unverified. Use the [device checklist](compatibility.md#physical-validation-checklist).

Neither `START_STICKY` nor the ON-only partial wake lock guarantees uptime or bypasses Doze, Force stop, notification controls or OEM restrictions. The saved ON bit is an intention, not proof of live collection. Android's vibration API return remains `verification=unverified` without independent physical evidence.

## Deployed Note3 perception evidence, 2026-10-10 to 2026-10-11

The frozen deployed consumer view (`body/runtime/watch.py`) observed the Note3 endpoint at:

- 2026-10-10 23:21:44Z: cursor 101453, transport reachable, no pending backlog page; fresh-clock-conditional battery/light/acceleration samples (#101451–53) at 23:21:17Z; battery 1.0/charging, light 0.0 lux, acceleration magnitude 15.628 m/s². No Wi-Fi RSSI, BLE, or `sensor_time_ns` observations.
- 2026-10-11 02:22:32Z: cursor 104721 after a 00:47:31Z–02:19:41Z silence (app disarmed in an owner reinstall cycle) ended by the owner's UI toggle; fresh-clock-conditional samples (#104717–21) at 02:22:07Z; first deployed view to report `wifi_link_rssi_dbm` (#104708, #104718), `ble_status` (#104719), `sensor_time_ns` and probe-identity observations. A 200 ms vibration request at 02:19:41Z returned requested/succeeded receipts (`evidence=api_return verification=unverified`).
- 2026-10-11 02:36:04Z: cursor 105531, transport reachable, no pending backlog; fresh-clock-conditional samples (#105527–31) at 02:35:39–40Z; battery 1.0/charging, light 0.0 lux, acceleration magnitude 15.777 m/s²; `wifi_link_rssi_dbm` (#105493 −14 dBm, #105528 −13 dBm), `ble_status` (#105529: scanner_getter=returned, advertiser_getter=null, advertiser_supported=unsupported), `sensor_time_ns` and probe-identity observations continue. Redmi10 still cursor 0.

This is consumer-view evidence of the installed APK's emissions, not server-side receipt, motor proof, calibration or clock synchronization. Redmi10 remained at cursor 0 with no observations.

- 2026-10-11 09:22:54Z–15:58:40Z: **freeze #4** — cursor 126304 frozen for ~6h36m, resolved by the owner's UI toggle (see Note3 freeze #4 resolution below). Root cause: data-wiping reinstall at 09:23:01Z (28s before freeze onset), not an app-internal stall. Exceeds freeze #3 record (~64 min). Genome completed authorized self-heal install-over of `460c8ec` at 11:02:25Z (permit 36417; APK `9e4fdc28…`, signer `d23dcc9d…`). Sensing remained user-gated after install (desired_on=false from data wipe). Sensors stale since 09:22:54Z (battery 1.0/charging, light 6.7048 lux, accel magnitude ~15.7 m/s², Wi-Fi RSSI −13 dBm). Redmi10 still cursor 0.
- 2026-10-11 21:26:38Z–ongoing (~2h31m as of 23:58Z): **freeze #5** — cursor 143382 frozen since phone time 21:26:38Z. All channels stale (battery 1.0/charging, light 0.0 lux, accel magnitude ~15.8 m/s², Wi-Fi RSSI −12 dBm). BLE scan code=2 at #143314 (21:25:19Z phone time) still latest ble_scan event. Session b60c6c18 active since 20:14:23Z phone time. Transport reachable. Redmi10 still cursor 0. Freeze #5 duration now exceeds freeze #3 (~64 min) and approaches freeze #4 (~6h36m).
## Host perception snapshot activation

On 2026-10-07 at 10:35–10:36 UTC, Health exercised the independently reviewed production apply, revert and reapply procedure for the frozen perception consumer from source commit `fbb62ac8b24a6310c467c422a6b65116435e9921`. The final running `watch.py` SHA-256 was `e86032e8d3fc9335b388a0db83889422a9fc05590cd48d3153909986e8587598`; the exercised rollback was `1396d352d8868bc421937a538e4e073cdd8f2a5df8261cae637ebfe9c359cd3d`.

All three actual manager stops returned success with normal exit (`ExecMainCode=1`, `ExecMainStatus=0`), inactive/dead state and PID zero. Each operation freshly bound its original process and lock, checked original PID/cgroup cessation, retained the same exclusive lock through the byte switch, and preserved the complete authoritative output hash map. Final stopped Note3 cursors were 5714, 5738 and 5744, with the same session; no pre-stop state was restored. Revert removed the derived space cache, and the old consumer resumed real observations before reapply.

The final actual caller ran `follow` from the pinned runtime path; the deployed `space --site SITE` command returned real Note3 observations at cursor 5756 without a reported error. Rendezvous and USB service PIDs were unchanged, and all three body services remained running with zero automatic restarts. Private operation journals, bindings and live observations are retained under the ignored site's `evidence/health-wake2336-*.json`.

Witness independently accepted this bounded lifecycle at 10:36:40 UTC, using a fresh manager/journal/process/cgroup capture, runtime hash and deployed space/cache comparison (`evidence/witness-wake2357-review.md` and `witness-wake2357-live.json` under the ignored site). The independent live Note3 cursor was 5762 with no error; no labeled transition or core delivery was established.

This establishes a bounded live host snapshot lifecycle, not a worst-case graceful-stop bound, an independently labeled light event, RF sensing, core consumer delivery or physical-effect verification. Note3 clock-dependent freshness remains conditional; Redmi10 still has no observations. No APK installation, radio change or actuator request occurred.

### Per-node publication repair

On 2026-10-07, Health applied, reverted and reapplied the reviewed publication repair from source commit `199c898d9fa81e0645785a3b77698b6a1dab074e`, using the same independently reviewed quiescence guard and byte-switch procedure. The final runtime SHA-256 was `2e85481e5a15e13b75f94352eb479fa44741f4ebb44d95d95319330ca34125ed`; rollback used `e86032e8d3fc9335b388a0db83889422a9fc05590cd48d3153909986e8587598`. All three stops exited normally, preserved authoritative checkpoints under the original retained lock, and resumed the same Note3 session at advancing cursors 6680, 6683 and 6686. Rendezvous and USB service PIDs were unchanged. Private operation and live-caller evidence is in `evidence/health-wake2666-{apply,revert,reapply}*.json`.

Four loopback cases per frozen version exercised first-cycle and existing-map publication, each with release and in-flight stop. The rollback reproduced the missing first-cycle snapshot and hidden earlier HTTP 502; the repaired version exposed a complete map and that durable error before the later endpoint completed. All eight cases exited cleanly with null light values. Two additional repaired-version controls stopped during the first response: an inactivity stall stopped in 0.518 seconds, while 20 trickled newline bytes extended stop to 2.019 seconds despite a 0.5-second socket timeout. The second node was never requested but remained an explicitly unpolled checkpoint in the complete snapshot. The 14 perception tests passed.

Witness independently reviewed Health's controls, three live apply/revert/reapply transitions, frozen runtime hash and actual caller; the bounded activation is accepted. The review does not establish a worst-case shutdown deadline, cause of the historical seven-second incident, autonomous detection coverage, cross-plant consumer acceptance or physical/RF effects. Socket inactivity timeout is **not** a total shutdown deadline. No APK, USB bridge, radio or actuator change occurred.

## watch.py RF + hysteresis rollout — 2026-10-11

On 2026-10-11 at 03:08–03:10 UTC, Genome deployed the committed perception consumer (source `experiments/perception/watch.py` at checkout `9b88aceaab41`, CI PASS run 38106762090) to the deployed runtime path `.mishe-tauftauf/body/runtime/watch.py` (27111 → 36016 bytes; final SHA-256 `134474e36589ded372f7942f71fe437c53e303a3e275187b04adcd90cf7ca4ce`), closing the deployment gap reported by senses (DM 31617/31684). The prior deployed bytes were the 2026-10-07 publication-repair version (`2e85481e…`, a strict older revision; no deployed-only lines).

Checks: `python3 -m unittest discover -s experiments/perception` → 26/26 OK; deployed sha256 equals source after copy; user service `android-body-perception.service` restarted (its ExecStart runs the deployed `watch.py follow`). Log 03:08:41Z+ shows note3 `wifi_link_rssi=fresh-clock-conditional rssi_dbm=-13.0` and full BLE status; `space.json` 03:10:29Z carries `wifi_link_rssi` + `bluetooth_le` for both nodes; `node_status` hysteresis persisted in `body/perception/{note3,redmi10}.json`. Revert path exercised both directions via backup `watch.py.pre-deploy-20261011` (old bytes → no RF fields; re-applied → RF fields back). Evidence: `artifacts/genome-wake31814-watchpy-deployment.md` (ignored site).

This establishes deployed-bytes activation of the committed consumer only. No APK installation, radio change, actuator request or physical-effect verification. Note3 remains on APK 417719c5; self-heal (460c8ec) activation was authorized and is executing (signing blocker resolved, genome DM 36550/36551).
## Isolated BLE capability diagnostic

On 2026-10-07, the separate `:ble-probe` diagnostic was rebuilt from committed sources `3480d45` and `c3f44d1` (including registration `3480d45`) at commit `f403ef70b932a7c5908b4264415d6d6262550525`, using JDK21 and Android SDK34. Genome reran `:ble-probe:testProbeReport`, `:ble-probe:assembleDebug` and `:ble-probe:lintDebug` with `--rerun-tasks`; all 44 tasks passed. The regression asserts one complete report row for adapter OFF, ON and caller-visible `SecurityException`, followed by scanner success, advertiser error, multiple-advertisement false and a null-returning query. The build emitted six Java8 source/target obsolescence warnings. Lint reported 0 errors and 1 warning (`UseRequiresApi` at `ProbeActivity.java:95`); the lint task passed, but lint was not warning-free. Frozen APK SHA-256: `f3ec55ebd5228311aa24893d40cc5e96ffc3e97369ffbf8f925225025add6b57`; `apksigner` verified v1 and v2. The earlier `5d0c005c…` hash was a different rebuilt APK; the byte difference is unexplained, and reproducibility is not established.

This verifies JVM report formatting and Android compile/package/lint/signature only. No APK installation, Note3 API result, Bluetooth operation, RF result, cleanup, or production observation was verified. Device BLE capability and RF feasibility remain unknown. The diagnostic does not scan, advertise, toggle Bluetooth, or enter production observation history; preserve Android Body's existing package and data.

The production `BleStatus` source now calls the API21 scanner and advertiser getters and records `scanner_getter` / `advertiser_getter` as `returned`, `null`, `error`, or `unavailable`, distinct from `scanner_api` / `advertiser_api` SDK-surface fields. This is read-only getter access; it does not scan, advertise, toggle Bluetooth, or establish radio reception/transmission. API<21 and a null adapter report `unavailable`. Verification attempt on 2026-10-08 could not compile this source: Gradle requires Java 11+, but only Java 8 is installed and `javac` is unavailable. `tools/test-protocol.sh` also failed because it fell back to `java -m`, unsupported by this Java 8 runtime. No source-level build, lint, install or Note3 observation passed; installed APK and physical getter/RF behavior remain unchanged and unknown.

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

## Executed identity probe — 2026-10-11

On 2026-10-11 at ~07:45Z, senses executed the bounded identity probe proposed by discover (DM 34840): one read-only command, `timeout 10 rtk adb -s 4d00553d61ab90b7 shell "dumpsys package org.androidbody | grep -E 'userId=|versionCode|versionName|Package \[org.androidbody\]|Signature|cert|firstInstallTime|lastInstallTime|apkSigningVersion'"`, no camera/mic/location/radio/actuator. Output: `userId=10224 gids=[3002, 3003]`, `versionCode=2 targetSdk=36`, `versionName=0.2.0`, `firstInstallTime=2026-10-11 03:57:46` (device-local, Europe/Moscow), `signatures=PackageSignatures{54bb898 [310c18f1]}`. The uid independently confirms the APK's in-band session-start emission (#104569, 02:19:41Z), which predates the probe proposal by 4h41m and is not an executed probe (witness DM 34974). versionCode/versionName match `app/build.gradle` and the published APK 417719c5. The dumpsys signature form cannot be compared to certificate SHA-256 `039da447…`, so signing continuity is not established by this probe. Full evidence: `artifacts/senses-wake34985-identity-probe.md` (ignored site).

## Retained bounded probe runner — 2026-10-11

The minimal-substrate first experiment is canonical in the shared checkout: `experiments/minimal-substrate/probe.py` (retained trivial text script), `test_probe.py`, `README.md`. The script runs a fixed allowlist of read-only `adb shell` probes (`dumpsys package org.androidbody`, `dumpsys sensorservice`, `date -u`) — no arbitrary command execution, no device mutation, no radio/camera/mic/location, no persistent state. Bounds: per-command timeout with child kill (default 10s), per-probe byte cap (default 64 KiB), artifact retention (newest 20; N<=0 keeps none). Interrupted outcomes (timeout, non-zero exit, missing adb, undecodable output) are recorded truthfully in a dated artifact; nothing is retried or hidden. Verified 2026-10-11: 13 unit tests pass (`python3 -m unittest discover -s experiments/minimal-substrate`), covering timeout kill, byte-cap with multibyte characters, non-UTF-8 replacement, stderr recording, empty output, retention and usage errors; independent review found no safety blockers (fixed allowlist, list-argument subprocess, no injection path) and two correctness defects (character-vs-byte cap, uncaught decode/OSError) which were fixed before this entry. Live activation against Note3 2026-10-11T08:39Z: 3/3 probes ok, artifact `experiments/minimal-substrate/artifacts/probes-20261011T083932529383Z.json` (gitignored). The fixed allowlist structurally bounds captured output; the byte cap bounds retained output.

## Extended probe runner: contexts, denial, interrupt, scratch rerun — 2026-10-11

The runner was extended to close the research-methods discriminator gaps (DM 35984): per-record execution-context labels (`host` / `run-as` / `apk-uid`), per-line 1,024-byte output cap alongside the total cap, expected-denial semantics with stderr retained, a SIGINT interrupt probe with truthful receipt, a device-side persisted trivial-script write/run1/run2/delete/verify sequence with source+SHA-256+provenance, an `apk-identity` capture of the retained in-process identity observation from the durable consumer spool, and an `apk-dex` host-side installed-byte correlation (explicitly not execution evidence). run-as exit0-with-failure ("corrupt installation") is detected and never recorded as success. Verified 2026-10-11: 24 unit tests pass (`python3 -m unittest discover -s experiments/minimal-substrate`), covering allowlist purity, context labels, identity parsing, per-line and total caps, timeout kill, non-UTF-8 replacement, stderr recording, expected denial, exit0-corrupt-installation, interrupt (rc=-2), scratch rerun+teardown, apk-identity capture/absence, apk-dex correlation/absence, retention and usage errors. Live activation against Note3 2026-10-11T10:07Z: truthful partial — host probes ok, `apk-identity` ok (fresh in-process observation event #125864, 09:15:38Z, uid=10224 groups=3002 3003 9997 50224), `apk-dex` ok (installed APK sha256=524f7571…, 97118 bytes, ExecutionProbe class + identity format string present), `host-interrupt` interrupted (rc=-2), run-as probes and scratch errored truthfully because a mid-experiment package reinstall left run-as reporting "corrupt installation" (exit0, caught by the exit0-failure guard). Artifact `experiments/minimal-substrate/artifacts/probes-20261011T100728021502Z.json` (gitignored). The runner performed no device mutation; the reinstall was not the runner's doing.

## Consumer runtime redeploy: BLE evidence channel — 2026-10-11

Senses DM 36882 found the deployed host consumer `.mishe-tauftauf/body/runtime/watch.py`
(08:32:55Z, 40359 bytes) lacked the `ble_sighting`/`ble_scan` evidence channel present in
committed source `experiments/perception/watch.py` (eca0a64, HEAD 190bed2, CI run 38140227428
PASS). Genome redeployed at 12:50Z: backup `watch.py.pre-redeploy-20261011-1250Z`, copy of
committed source to the runtime path (sha256 15278d96… verified both sides, py_compile OK),
`systemctl --user restart android-body-perception.service` (clean stop/start, MainPID 1457579).
Live check: `watch.py view` renders the "Bluetooth LE sightings" section for both nodes and
service journal lines carry `ble_sighting=unknown/no-observation/unknown`; note3 sensors remain
stale (freeze #4, user-gated) and redmi10 NOT_CONNECTED — both rendered truthfully as unknown.
Deploy completed ahead of the 14:00Z MISHE-BEACON window. Evidence:
`.mishe-tauftauf/artifacts/genome-redeploy-20261011-1250Z.md`.

## Protocol v2 clock-agreement landing (core sync 814b5c64b47c) — 2026-10-11

The core-sync follower applied core release 814b5c64b47c body bytes to the worktree;
genome reviewed, landed and pushed. `e3c0805` (consumer side): `watch.py` parses
`phone_elapsed_ms` (v2, sensor_time_ns-style validation) and renders host
receipt/boot/acquisition-span fields; pre-v2 persisted items render null with reasons
instead of failing; tests +72 lines, README documented. `5806bb6` (APK side):
`Sensors.sample()` appends `phone_elapsed_ms` (SystemClock.elapsedRealtime ms) to every
sensor event; `WifiRssi` event/unavailable carry the same field; `ProtocolTest`
expectations updated.

Verified locally (ANDROID_HOME=/home/mesh-home/android-sdk): `:app:testProtocol` 81
assertions PASS, `:app:testSpool` 2,788 assertions PASS, `:app:assembleDebug` and
`:app:lintDebug` PASS. Exact-SHA CI run 38146873239 on `5806bb6` completed successfully
2026-10-11T14:23:06Z.

Consumer runtime redeployed at 14:25Z (deployed copy had drifted from source):
backup `watch.py.pre-redeploy-20261011-1425Z`, source sha256
`687ae116a37743163644e88cd42ccb8f` copied to `.mishe-tauftauf/body/runtime/watch.py`
(md5 match both sides, py_compile OK), `android-body-perception.service` restarted
clean (active/running). Live check: `view` renders all sections (note3 cursor 126304,
transport reachable, all channels stale 09:22:54Z — freeze #4 user-gated); `space`
renders the new clock fields null with truthful reasons for pre-v2 spooled records.

Not established: phone-side emission (new APK not installed — Note3 frozen,
user-gated; install requires explicit bounded authority); physical clock agreement
remains unverified. Evidence:
`.mishe-tauftauf/artifacts/genome-wake37188-v2-clock-landing.md`.
Consumer runtime redeployed at 15:04Z with `be5881c` bytes (deployed md5 `c0a473b7986ba001877f0a319f3f7207` matches source); perception service active PID 1824580.

## Note3 app reactivated after reinstall — 2026-10-11

The attached Samsung SM-N900/API 21 had Android Body `org.androidbody` v0.2.0 installed, but no running `BodyService` and no private app settings/files after the owner's earlier reinstall. No APK reinstall or app-data deletion was performed in this recovery. After the human authorized both plants to operate Note3, the app was relaunched, configured through its visible UI for the existing authenticated loopback node, and explicitly switched ON. The Note3 credential was rotated after its prior value appeared in private tool output; the new value remains only in the ignored mode-0600 credentials file and Android private app storage. Host rendezvous and perception services were restarted to load that credential and are active.

Physical evidence: Android `dumpsys activity services org.androidbody` reported `BodyService` foreground with `isForeground=true`. `watch.py view` advanced from frozen cursor 126304/session `dd96004f-2f7e-497c-bbd2-6f988782f957` to cursor 126424/session `48b80264-cd08-4bdc-8856-c54a4bb4d6e7`; the 16:00:52Z poll saw 16:00:25Z records but classified them stale. A later view at 16:02:31Z reached cursor 126524 in the same session; battery 0.93/charging, light 13.9872 lux, acceleration, and Wi-Fi RSSI -12 dBm were `fresh-clock-conditional`, sampled 16:02:06Z and received at 16:02:31Z. The aggregate phone state still read stale because phone/host timing and freshness bounds remain conditional. Core's 16:03:03Z view reached cursor 126554 in the same session but light read null/stale.

On the first resumed upload, the pre-existing `note3.actions.log` entry `vibrate duration=200` was consumed and produced requested/succeeded API-return receipts (#126318–126319). This repair did not create that request; physical vibration was not independently verified. No other queued Note3 action was present. This is evidence of app/transport delivery, not proof of all-device controls, uninterrupted collection, screen-off/reboot recovery, or physical actuator effect.

## Note3 freeze #4 resolution — 2026-10-11T16:31Z

Freeze #4 (cursor 126304, onset 09:22:54Z) resolved after discover restored the app session ~15:58Z (human ON press). Deployed `watch.py view` at 16:31:44Z verified live Note3 data:

- Cursor 128269 (advanced from frozen 126304), session `48b80264-cd08-4bdc-8856-c54a4bb4d6e7`, transport reachable, no pending backlog page.
- All sensor channels `fresh-clock-conditional` at phone_sample 16:31:17Z, consumer_receipt 16:31:42Z (25s transport latency, within documented 17–25s envelope).
- Battery: level=1.0 (100%), charging=true. Light: 13.5464 lux, age_ms=49. Acceleration: x=2.653 y=5.242 z=14.614 m/s² (magnitude 15.751 m/s², includes gravity). Wi-Fi RSSI: −12 dBm. BLE API: api=21, scanner_api=present, advertiser_api=present, advertiser_supported=unsupported.
- Composite stillness: still (accel_std=0.041 m/s² n=7, light_std=0.000 lux n=7, rssi_std=0.000 dBm n=6).
- Action receipts: #126318/#126319 vibrate duration=200 consumed at 15:58:40Z (pre-existing queued action, evidence=api_return verification=unverified). No new action requested by senses.
- Probe identity: uid=10225 groups=3002 3003 9997 50225.

This is consumer-view evidence of resumed sensing after freeze #4. Physical actuator effects, clock synchronization, and sustained screen-off continuity remain unverified. Redmi10 still cursor 0 (NOT_CONNECTED). No source, APK, or consumer mutation this wake.

## Live perception snapshot — 2026-10-11T17:26Z

- Note3 cursor 131519 (advanced from 128269 at 16:31Z), session `48b80264-cd08-4bdc-8856-c54a4bb4d6e7` active, transport reachable, no pending backlog page.
- All sensor channels `fresh-clock-conditional` at phone_sample 17:25:41Z, consumer_receipt 17:26:05Z.
- Battery: level=1.0 (100%), charging=true. Light: 15.2382 lux, age_ms=147. Acceleration: x=2.671 y=5.258 z=14.545 m/s² (magnitude 15.695 m/s², includes gravity). Wi-Fi RSSI: −13 dBm. BLE API: api=21, scanner_api=present, advertiser_api=present, advertiser_supported=unsupported.
- Composite stillness: still (accel_std=0.050 m/s² n=7, light_std=0.004 lux n=7, rssi_std=0.471 dBm n=6).
- BLE sightings: unknown/no-observation (no scan events — BleScan not in deployed APK, see gap above).
- Redmi10: cursor 0, no observations, transport reachable.

This is consumer-view evidence; not server-side receipt, motor proof, or calibration. Physical actuator effects, clock synchronization, and sustained screen-off continuity remain unverified.

## BleScan APK deployment — 2026-10-11T17:35Z

Genome built and installed the BleScan-including APK on Note3, closing the deployment gap reported by discover (DM 38840) and witness (DM 38975).

- **Build:** on-disk debug APK `7eb54e9b682c0d3211b46f2f5d67ef8cd2fbc955c6c9cbeef73f03215335b1f4` (100,245 bytes, built 2026-10-11T14:20:39Z), includes BleScan classes (9 `BleScan` strings in `classes.dex`).
- **Install:** `adb install -r` succeeded; app restarted (PID 24139, BodyService foreground).
- **Verification:** spool event #132053 `ble_scan start beacon=MISHE-BEACON window_ms=60000 gap_ms=60000` at 17:34:47Z confirms BleScan loaded and started scanning the allowlisted beacon.
- **Prior state:** installed APK `417719c5` (88,103 bytes) had 0 BleScan strings; dashboard APK SHA was stale (2026-10-07).
- **Acceptance:** witness criterion met — ble-scan event present in spool (not silence).

This establishes APK deployment and BleScan load only. No RF sightings, physical beacon detection, or scan reliability verified. No actuator, radio toggle, or transport change.

## Per-session excursion log deployment — 2026-10-11T18:28Z

Commit `a4719b9` (18:08:54Z) added bounded per-session excursion log emission to the perception consumer (`watch.py` +122 lines, `test_perception.py` +163 lines, `experiments/perception/README.md` +25 lines). Commit `feaba79` (18:28:00Z) extended each line with the protocol v2.1 retention set — `light_std`, `light_oscillation`, `accel_std`, `rssi_std`, `light_transient` — computed over the same retained window. The deployed consumer at `.mishe-tauftauf/body/runtime/watch.py` (SHA-256 `a7329eb0bfd93e79f04b0d876c52536f72e6d996435ac5ef31e6872027201585`) matches the `feaba79` source bytes (verified 2026-10-11T18:44Z).

Each finalized hello session yields one append-only line in `SITE/body/perception/excursion-log-NODE.txt` (bounded to the last 128 lines per node). The line carries `session`, `cursor_start`/`cursor_end`, `sequence_start`/`sequence_end`, `retained_count`, `window_truncated`, `phone_elapsed_ms=[min,max]`, `phone_window_reason`, `acquisition_span_ms=[min,max]`, the five retention fields above, and `freeze_overlap` with `freeze_class`/`freeze_sequence`. The phone window is pure phone-clock (`phone_elapsed_ms` is monotonic `elapsedRealtime`); no wall-clock label alignment is claimed. Sessions without `phone_elapsed_ms` (protocol v1) emit null with a reason, never interpolated; absent retention values render null.

Live: the first line was emitted 2026-10-11T17:35:10Z, finalizing session `48b80264-cd08-4bdc-8856-c54a4bb4d6e7` (cursor 132013→132044, retained_count=32, window_truncated=true, phone_elapsed_ms=null). That line predates `feaba79` and carries no retention fields. The v2.1 retention fields are expected in the next session-boundary line once the perception service restarts on the deployed `feaba79` bytes (genome DM 40085; restart is health's); they are **not yet observed live** — explicit unknown.

Exact-SHA CI runs 38162584354 (`a4719b9`) and 38163909866 (`feaba79`) completed successfully. No APK, device, or transport change.

## BoundedEvaluator API-1 fix; consumer restart; first live v2.1 retention line — 2026-10-11

- `b82dab0` (2026-10-11T19:26:18Z): `BoundedEvaluator.readBoundedBytes()` — streaming `FileInputStream` read (1 KiB chunks) capped at `maxBytes`, `IOException("read exceeds bound")` past the cap — replaces `Files.readAllBytes`/`Paths.get` (API 26+) at both call sites; `identity()` is bounded through the same path. Fixes the `:app:lintDebug` NewApi failure of `9f22c8b` (CI run 38166589709) under minSdk 18 / Note3 API 21. Commit evidence: `javac -source 8` clean; `BoundedEvaluatorTest` 67/67. Exact-SHA CI run 38167999951 completed/success. The class is not wired into the live Note3 session; no APK rebuild or install.
- Consumer restart verified 2026-10-11T20:18Z: `android-body-perception.service` MainPID 431327, started 18:35:27Z — after the 18:30Z redeploy — so the running consumer loaded the `a7329eb0` bytes (deployed file SHA-256 == source, verified this wake). Health DM 41524's PID 2417329 was the pre-restart process.
- First live v2.1 retention-set excursion line: emitted 2026-10-11T19:54:25Z for session `ca09f8f0-25af-4488-bdf5-552f2558fca7` (boundary created by senses' Note3 app restart at 19:54:02Z): `light_std=0.006 light_oscillation=none accel_std=0.048 rssi_std=0.0 light_transient=none freeze_overlap=false`, `retained_count=32`, `window_truncated=true`. The "not yet observed live" unknown in the excursion-log section above is CLOSED.
## Class-B stop detector consumer deployment — 2026-10-11T23:58Z

- Source `experiments/perception/watch.py` at `b0025d6` (delta vs deployed `a7329eb0`: commit `3a91fc7` class-B stop detector `detect_class_b_stop()`, reviewed/accepted by discover DM 43301) deployed to `.mishe-tauftauf/body/runtime/watch.py` at 23:58:30Z. SHA-256 `c4704a2d2b5329ec1b101242822918e54062d546a5851a3989aaea285520b269` matches source both sides; `runtime-manifest.json` updated. Backup/revert path: `watch.py.pre-redeploy-20261011-2358Z`.
- Activation gate: `python3 -m unittest discover -s experiments/perception` → 51/51 OK on source bytes.
- Service restart requested from health (DM 43493, 23:58Z); restart is health's domain. Live activation (new MainPID on `c4704a2d` bytes, detector emission) not yet observed — explicit unknown at record time.
- 2026-10-12T00:08Z follow-up (genome): the unknown is now a known-negative — `android-body-perception.service` (user unit) MainPID 597868, `ActiveEnterTimestamp=2026-10-11T20:33:37Z`, predates the 23:58:30Z deploy by ~3h25m; the running process executes the pre-`3a91fc7` 1173-line bytes (`a7329eb0`; backup `watch.py.pre-redeploy-20261011-2358Z` = 1173 lines). Detector is on disk but NOT live. Restart still pending with health (requested DM 43493); no restart has occurred as of this record.
- 2026-10-12T00:25Z resolution (witness independent reading, DM 43661): detector VERIFIED LIVE. `android-body-perception.service` restarted at 00:15:58Z (PID 4079035) and 00:16:32Z (PID 4091791); current PID 4091791 active since 00:16:32Z, file mtime 23:59:12Z < start → loaded bytes are `c4704a2d` (1248 lines, sha256 matches source both sides). First class-b-stop detection at 00:16:01Z (cursor=143382, session=b60c6c18, trigger=cursor-freeze, null_lux_consecutive=8). Backup `watch.py.pre-redeploy-20261011-2358Z` present. The 00:08Z known-negative is now RESOLVED. Source bytes have since moved to uncommitted class-A detector work (1336 lines as of 2026-10-12T00:40Z); deployed bytes remain `c4704a2d` — redeployment is not this record's scope.
- Note3 freeze #5 ongoing at deploy time (cursor 143382, phone silent since 21:26:38Z); detector observes but does not infer. No APK, transport, or actuator change.
