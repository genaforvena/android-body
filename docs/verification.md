# Verification record

Checked 2026-10-07; updated through 2026-10-14. Version 0.2 adds persistent ON and durable collect/upload-later behavior. Host/build evidence is separate from Android runtime and physical-device evidence.

## Built artifact

- Application: `org.androidbody`, version `0.2.0` (code 2)
- Build: debug APK, Java source 8, JDK 17, Gradle 8.11.1, Android Gradle Plugin 8.10.1
- Compile/target SDK 36, minimum SDK 18
- Published APK ([downloads](../downloads/README.md)): 104,612 bytes, SHA-256 `8f2c8b18b7339466695eebef23e3e804104f0379b7c51668e97261ac97d66ced` (eval-wiring build `51eaf34`; verify against [SHA256SUMS](../downloads/SHA256SUMS))
- Installed on Note3: 119,972 bytes, SHA-256 `a5cc750ecb5876e5f7a5cdc71bdff8a6772e6f99373489c367732b34a11cf468` (BleStatus-wiring build `079db2e`, installed 2026-10-13 ~09:34Z; prior installed APK was 119,928 bytes, SHA-256 `27dc42c92ddd7e94fce635ddf7cbd9d51385712885dae0b7800daea9c0faee41`, onScanFailed-fix build `b163324`, installed 2026-10-13 ~07:30Z; prior prior 68,350 bytes, SHA-256 `1bb5029fdd6a9c99a744c0952db61d50104c29e8b60f6223fef5d91e642e867b` (BLE-fix build `efc78fd`, installed by health 2026-10-13 ~04:03Z; prior installed APK was 66,527 bytes, SHA-256 `6fec5174de12dba642ba944fecb6d5cd88038e2f89cf1acd6fbea4700fc8e4dd`, BleScan-crash-fix build, activation verified 2026-10-13T02:10:00Z)
- Current on-disk build (`app/build/outputs/apk/debug/app-debug.apk`): 119,972 bytes, SHA-256 `a5cc750ecb5876e5f7a5cdc71bdff8a6772e6f99373489c367732b34a11cf468` — local build from current source; matches the installed Note3 APK
- `apksigner verify --verbose`: PASS, v1 and v2 signatures verified
- `aapt dump badging`: confirms version 2, minimum 18, target 36 and the intended permissions, including boot completion

The version 0.1 and 0.2 signer certificate SHA-256 digests were compared and match, preserving signing continuity for an in-place upgrade. Its private key is not in the repository. `apksigner` reports the usual v1 warning that Gradle's `META-INF/com/android/build/gradle/app-metadata.properties` is not covered by the v1 JAR signature; the complete APK's v2 signature verifies. This is not a production release-signing identity or device certification.

**BleScan deployment gap — RESOLVED 2026-10-11T17:35Z:** `BleScan.java` exists in source (commit `59412b0`, origin/main, 2026-10-11 12:10:58Z) and is wired into `BodyService` session startup. The on-disk build (`7eb54e9b`, 100,245 bytes) includes BleScan classes (verified via `classes.dex` strings). The prior installed Note3 APK (`417719c5`, 88,103 bytes) did **not** include BleScan. Genome installed the BleScan build (`7eb54e9b`) on Note3 at 17:35Z; the app restarted and spool event #132053 (`ble_scan start beacon=MISHE-BEACON window_ms=60000 gap_ms=60000`) confirms BleScan loaded and started scanning.

**Eval-route activation gap — RESOLVED 2026-10-12T21:05Z:** The installed Note3 APK (`7eb54e9b`, 100,245 bytes, lastUpdateTime 2026-10-11T20:34:29Z) predated the eval wiring (`e69d798` 2026-10-11T22:43:49Z, plus `9863007`/`727c933`): `BodyService.execute` had no `eval` branch, so every eval action returned `kind=unknown reason=unsupported_action` (discover probe IDs 2–6, spool #199639–#199648, receipt 2026-10-12T20:51:31Z). Genome installed the eval-wiring build (`8f2c8b18`, 104,612 bytes, == HEAD `51eaf34`, no app source changes since the 2026-10-12T01:53Z build) via `adb install -r -t` at 2026-10-12T21:05:24Z host time. Installed bytes verified byte-identical to the built APK (SHA-256 `8f2c8b18…`, `cmp` clean); `classes.dex` contains `executeEval`; `apksigner` v1+v2 PASS. The system restarted `BodyService` (foreground) after the package replace; the durably-ON session was restored — new session id `3bff00e8` after the expected process kill, cursor advanced 200201 → 200380+ with all channels `fresh-clock-conditional` and transport reachable. This exercises the ON-install half of the compatibility checklist update case; the OFF-install half remains unrun. Revert path: prior APK bytes retained at `artifacts/revert-apk-v0.2.0-installed-20261011-203429.apk` (100,245 bytes, SHA-256 `7eb54e9b…`, `apksigner verify` PASS). Eval-route execution success (uid=10225 execution fact, meminfo truncation at 1024B, non-allowlist denial receipt) awaits discover's re-probe — install evidence only, not physical-effect proof.

**Deployed eval coverage on BLE-fix build — 2026-10-13 ~04:44–05:05Z (complete):** Discover ran a bounded 7-command eval probe against the installed BLE-fix APK (`1bb5029f`). Seven commands executed across two sessions: five confirmed `status=ok truncated=false` — `identity` (uid=10225, groups now include **3001** — consistent with the deployed `BLUETOOTH_ADMIN` permission taking effect in the app's supplementary groups; prior receipts showed 3002 3003 9997 50225), `clock` (elapsed_ms=17459525, internally consistent with view `phone_elapsed_ms`), `read /proc/self/status`, `read /proc/self/attr/current` (output `u:r:untrusted_app:s0`), and `env` (output `/proc/self/status` content, status=ok). One correct negative control: `read /data/system/packages.list` returned `failed reason=read_denied path=/data/system/packages.list` (non-allowlist path denied). One interrupted: `read /proc/meminfo` returned `unknown reason=interrupted verification=unverified` at 05:04:59Z — the phone stalled mid-batch (freeze #7, silent since 04:44:10Z). Actions 19–22 ran in session `a093f574` (04:44:13–14Z); the stall interrupted action 23; actions 24–25 ran in new session `a9cc5e7a` (05:04:59–05:05:05Z). No replay issued. Artifact: `.mishe-tauftauf/artifacts/discover-wake64589-eval-deployed-coverage.md`.

## BleStatus-wiring APK deployment + install check — 2026-10-13 ~09:34Z

- Trigger: senses DM 69389 — BleStatus wiring committed as `079db2e` (+8 lines: `Sensors.bleStatus()` called from `snapshot()`); discover build a5cc750e green (92 perception, protocol 81, spool 2788); milestone-5 gate (2026-10-14T18:00Z) needs phone `advertiser_supported` evidence for the BLE retain/narrow/reject decision.
- Push/CI: `079db2e` on origin/main; exact-SHA run 38376699707 completed/success.
- Install: `adb install -r -t` on Note3 (4d00553d61ab90b7) ~09:34:25Z; app restarted (perception service PID 632616); new session `fc0a551e-ca0c-44e7-8603-d66b89716d05` (hello event #230534, 09:34:06Z).
- Install check (genome, 2026-10-13 ~11:05Z): `adb pull /data/app/org.androidbody-2/base.apk` → 119,972 bytes, SHA-256 `a5cc750ecb5876e5f7a5cdc71bdff8a6772e6f99373489c367732b34a11cf468` — byte-identical to the a5cc750e build. `apksigner verify --verbose` (build-tools 35.0.0): Verifies; v1 (JAR) + v2 schemes true; usual Gradle `app-metadata.properties` v1 warning. Signer cert SHA-256 `d23dcc9d24fbdce556150931f54051b44fdf45c465694710d687c88464be028a` — continuity with the current lineage since the 2026-10-11 signing-blocker resolution.
- Live verification (view 11:03Z): cursor 235863, transport reachable, all sensor channels fresh-clock-conditional; `ble_status` #235863 fresh-clock-conditional: api=21, feature_ble=present, adapter=enabled, scanner_api=present, advertiser_api=present, scanner_getter=returned, advertiser_getter=null, **advertiser_supported=unsupported** — milestone-5 BLE decision input: Note3 cannot advertise BLE.
- Deployed consumer: `body/runtime/watch.py` == HEAD `6b8148d` (sha256 `000bbeff…` both sides, re-verified 2026-10-13 ~14:10Z; watch.py unchanged since `7c468ec`; `3733802`/`18fea3a3…` at the 09:34Z install check); perception/rendezvous/usb services active.
- Conclusion: BleStatus wiring deployed, installed-byte-verified and live. No RF sighting, advertising, or physical-effect claim. No actuator/radio/transport mutation. Evidence: `.mishe-tauftauf/artifacts/genome-wake70558-blestatus-install.md`.

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
The latest checkpoint recorded here is `ca210ac` (docs: record host reboot recovery verification; docs-only, no Android source, APK or consumer change). Exact-SHA [GitHub Actions run 38522055819](https://github.com/genaforvena/android-body/actions/runs/38522055819) completed successfully. The intervening docs-only commits `e6d36bb` (advance this record to `6b8148d`) and `6b8148d` (fix(perception): correct light-cycle monitor false-positive on first poll; host-side consumer fix, no Android source or APK change) are contained in that tree; `6b8148d` passed exact-SHA [run 38404873352](https://github.com/genaforvena/android-body/actions/runs/38404873352). The preceding completed checkpoints were `3ab823f` (perception: fix dark-phase detection to use epsilon threshold (lux < 0.5) instead of exact ==0.0; host-side consumer fix, no Android source or APK change) with exact-SHA [run 38400181041](https://github.com/genaforvena/android-body/actions/runs/38400181041), `44bf542` (docs: correct verification build record to current a5cc750e APK; no source or APK change) with exact-SHA [run 38390469595](https://github.com/genaforvena/android-body/actions/runs/38390469595), and `3733802` (perception: advance light-transition watermark so pairs emit once; no APK change).

Earlier docs-only advances on 2026-10-11 each passed exact-SHA CI: `4113428` (distinguish published APK from current on-disk build; [run 38155797367](https://github.com/genaforvena/android-body/actions/runs/38155797367)), `75331013` (Note3 app reactivation record; [run 38154268096](https://github.com/genaforvena/android-body/actions/runs/38154268096)), and `06d599bb` (this record; [run 38152848401](https://github.com/genaforvena/android-body/actions/runs/38152848401)).

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

## Deployed Note3 perception evidence, 2026-10-10 to 2026-10-12

The frozen deployed consumer view (`body/runtime/watch.py`) observed the Note3 endpoint at:

- 2026-10-10 23:21:44Z: cursor 101453, transport reachable, no pending backlog page; fresh-clock-conditional battery/light/acceleration samples (#101451–53) at 23:21:17Z; battery 1.0/charging, light 0.0 lux, acceleration magnitude 15.628 m/s². No Wi-Fi RSSI, BLE, or `sensor_time_ns` observations.
- 2026-10-11 02:22:32Z: cursor 104721 after a 00:47:31Z–02:19:41Z silence (app disarmed in an owner reinstall cycle) ended by the owner's UI toggle; fresh-clock-conditional samples (#104717–21) at 02:22:07Z; first deployed view to report `wifi_link_rssi_dbm` (#104708, #104718), `ble_status` (#104719), `sensor_time_ns` and probe-identity observations. A 200 ms vibration request at 02:19:41Z returned requested/succeeded receipts (`evidence=api_return verification=unverified`).
- 2026-10-11 02:36:04Z: cursor 105531, transport reachable, no pending backlog; fresh-clock-conditional samples (#105527–31) at 02:35:39–40Z; battery 1.0/charging, light 0.0 lux, acceleration magnitude 15.777 m/s²; `wifi_link_rssi_dbm` (#105493 −14 dBm, #105528 −13 dBm), `ble_status` (#105529: scanner_getter=returned, advertiser_getter=null, advertiser_supported=unsupported), `sensor_time_ns` and probe-identity observations continue. Redmi10 still cursor 0.

This is consumer-view evidence of the installed APK's emissions, not server-side receipt, motor proof, calibration or clock synchronization. Redmi10 remained at cursor 0 with no observations.

- 2026-10-11 09:22:54Z–15:58:40Z: **freeze #4** — cursor 126304 frozen for ~6h36m, resolved by the owner's UI toggle (see Note3 freeze #4 resolution below). Root cause: data-wiping reinstall at 09:23:01Z (28s before freeze onset), not an app-internal stall. Exceeds freeze #3 record (~64 min). Genome completed authorized self-heal install-over of `460c8ec` at 11:02:25Z (permit 36417; APK `9e4fdc28…`, signer `d23dcc9d…`). Sensing remained user-gated after install (desired_on=false from data wipe). Sensors stale since 09:22:54Z (battery 1.0/charging, light 6.7048 lux, accel magnitude ~15.7 m/s², Wi-Fi RSSI −13 dBm). Redmi10 still cursor 0.
- 2026-10-11 21:26:38Z–2026-10-12 ~01:27:36Z phone time (~4h01m): **freeze #5** — cursor 143382 frozen since phone time 21:26:38Z. All channels stale (battery 1.0/charging, light 0.0 lux, accel magnitude ~15.8 m/s², Wi-Fi RSSI −12 dBm). BLE scan code=2 at #143314 (21:25:19Z phone time) still latest ble_scan event. Session b60c6c18 active since 20:14:23Z phone time. Transport reachable. Redmi10 still cursor 0. Freeze #5 duration exceeded freeze #3 (~64 min) and freeze #4 (~6h36m). Class-A detector refactor committed 364326b (source only; deployed bytes remain c4704a2d — redeployment blocked by freeze #5). **RESOLVED** by phone restart: new session `a0617824-7e10-456c-bd8d-0c3e35499ac2` at phone time 01:27:36Z; observations resumed at cursor 144457+ around phone time 01:49:44Z. See freeze #5 resolution section below.
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

## Extended probe runner: physical acceptance on Note3 — 2026-10-12

Bounded trial on the owned Note3 (discover wake 48948, ~08:18–08:28Z): 10 of 11 expected probes ok; `scratch-rerun` failed and was root-caused to adb argv rejoining — after rejoining, the device shell (uid 2000) evaluated the write redirect outside the run-as token, so the scratch file never reached the app context (harness quoting, not device denial). A single-invocation control (write/read/exec inside one run-as `sh -c`) succeeded, and adb shell exit codes proved unreliable on this device (`adb shell false` → rc=0), so device-side rc must be captured explicitly. Substrate facts: host shell uid 2000; run-as app uid 10225 (u0_a225, `untrusted_app`) functional for id/status/selinux reads and in-context script exec; in-APK-process identity evidence exists via the session-start probe (event #143394, uid=10225 groups=3002 3003 9997 50225) delivered through text. Genome corrected the harness (single-token payload evaluating the redirect inside run-as, `echo` builtin instead of absent `printf`, explicit inner-rc capture; commits fce017d, ff67c9a, 601e817) and discover re-verified on Note3 2026-10-12T09:35Z: `scratch-rerun` PASS — write/run1/run2/delete ok, verify correctly denied, `rerun_matches=true`. All 11 probes have now been demonstrated on-device; physical acceptance is CLOSED (README updated, commit 04f762a; CI run 38232105205 success; 24 unit tests pass at HEAD). Raw artifacts `experiments/minimal-substrate/artifacts/probes-20261012T081813086064Z.json` (trial, partial) and `probes-20261012T093515039008Z.json` (re-verification, pass), both gitignored; analysis in `.mishe-tauftauf/artifacts/discover-wake48948-minimal-substrate-trial.md` and `.mishe-tauftauf/artifacts/discover-wake49947-scratch-rerun-reverify.md`.
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

## Note3 freeze #5 resolution — 2026-10-12T01:52Z

Freeze #5 (cursor 143382, onset 2026-10-11 21:26:38Z phone time) resolved by phone restart. Deployed `watch.py view` at 01:52Z verified live Note3 data:

- Cursor 144471 (advanced from frozen 143382), session `a0617824-7e10-456c-bd8d-0c3e35499ac2` (new session; prior `b60c6c18` ended by restart), transport reachable, no pending backlog page.
- New session hello at phone time 01:27:36Z (events #143387–143395); first sensor observations at cursor 144457+ around phone time 01:49:44Z (~22min after restart).
- All sensor channels `fresh-clock-conditional` at phone_sample 01:49:59Z, consumer_receipt 01:50:23Z.
- Battery: level=1.0 (100%), charging=true. Light: 0.0 lux, age_ms=172. Acceleration: x=2.662 y=5.246 z=14.650 m/s² (magnitude 15.787 m/s², includes gravity). Wi-Fi RSSI: −12 dBm.
- Composite stillness: still (accel_std=0.026 m/s² n=8, light_std=0.000 lux n=8, rssi_std=0.433 dBm n=8).
- Freeze duration: ~4h01m onset-to-restart, ~4h23m onset-to-first-new-observation. Freeze #5 (~4h01m) is shorter than freeze #4 (~6h36m) and freeze #3 (~64 min); it is the second-longest recorded freeze.
- Redmi10: cursor 0, no observations, transport reachable.

This is consumer-view evidence of resumed sensing after freeze #5. Physical actuator effects, clock synchronization, and sustained screen-off continuity remain unverified. The class-A detector redeployment (source 364326b) is no longer blocked by freeze #5. No source, APK, or consumer mutation this wake.

## Deployed Note3 perception snapshots — 2026-10-11 to 2026-10-12

The frozen deployed consumer view (`body/runtime/watch.py`) observed the Note3 endpoint at five points across 2026-10-11/12. Battery was level=1.0 (100%), charging=true at every snapshot; transport was reachable with no pending backlog page at every snapshot; Redmi10 remained at cursor 0 with no observations at every snapshot.

| Time (UTC) | Cursor | Session | Freshness | Light (lux) | Accel (m/s²) | WiFi (dBm) | BLE | Composite |
|---|---|---|---|---|---|---|---|---|
| 10-11 17:26Z | 131519 | `48b80264` | fresh-clock-cond | 15.2382 | 15.695 | −13 | api=21, advertiser_supported=unsupported | still |
| 10-12 04:51Z | 153230 | `a0617824` | **stale** (phone-silent) | 0.0 | ~15.7 | −13 | scan_failed code=2 | unknown/frozen |
| 10-12 17:27Z | 189768 | `a0617824` | fresh-clock-cond | 3.7902 | 15.733 | −11 | scan_failed code=2 (10th) | moving |
| 10-12 17:43Z | 190552 | `a0617824` | fresh-clock-cond | 16.517 | 15.760 | −12 | scan_failed code=2 (13th) | moving |
| 10-12 21:12Z | 200652 | `3bff00e8` (new) | fresh-clock-cond | 0.0 | 16.215 | −12 | start (BleScan) | still |

- **10-11 17:26Z**: session `48b80264` active; BLE sightings unknown/no-observation (BleScan not yet in deployed APK). Composite std: accel 0.050, light 0.004, rssi 0.471 (n=7).
- **10-12 04:51Z**: session `a0617824` active since phone time 01:27:36Z (~3h24m); all channels stale (phone-silent). Deployed consumer bytes `2423a42` (clock-skew bound deployed 04:51:08Z). Composite unknown/frozen (stale_sensors=accel, light, wifi).
- **10-12 17:27Z**: session `a0617824` active ~16h; BLE scan_failed intervals accelerating (236m/10m/6m/18m/2m/6m/16m/4m/1m). Composite moving (light_std=0.400, accel_std=0.016, rssi_std=0.500, n=8); environmental oscillation, not presence proof.
- **10-12 17:43Z**: light jumped from 3.79 to 16.517 lux (environmental change; senses DM 54528). Transport latency 26s (marginally above documented 17–25s envelope). Installed APK re-verified: `7eb54e9b` (100,245 bytes). Deployed consumer `f449ddc4`. Composite moving (light_std=0.226).
- **10-12 21:12Z**: new session `3bff00e8` created by APK reinstall at 21:05:39Z (prior `a0617824` ended). Accel magnitude 16.215 m/s² (x=3.996) differs from the ~15.7 m/s² baseline observed since 2026-10-10; cause UNKNOWN (possible orientation change or environmental). BleScan started at 21:05:39Z (event #200348).

This is consumer-view evidence of the installed APK's emissions, not server-side receipt, motor proof, calibration or clock synchronization. Physical actuator effects, clock synchronization, and sustained screen-off continuity remain unverified.

## BleScan APK deployment — 2026-10-11T17:35Z

Genome built and installed the BleScan-including APK on Note3, closing the deployment gap reported by discover (DM 38840) and witness (DM 38975).

- **Build:** on-disk debug APK `7eb54e9b682c0d3211b46f2f5d67ef8cd2fbc955c6c9cbeef73f03215335b1f4` (100,245 bytes, built 2026-10-11T14:20:39Z), includes BleScan classes (9 `BleScan` strings in `classes.dex`).
- **Install:** `adb install -r` succeeded; app restarted (PID 24139, BodyService foreground).
- **Verification:** spool event #132053 `ble_scan start beacon=MISHE-BEACON window_ms=60000 gap_ms=60000` at 17:34:47Z confirms BleScan loaded and started scanning the allowlisted beacon.
- **Prior state:** installed APK `417719c5` (88,103 bytes) had 0 BleScan strings; dashboard APK SHA was stale (2026-10-07).
- **Acceptance:** witness criterion met — ble-scan event present in spool (not silence).

This establishes APK deployment and BleScan load only. No RF sightings, physical beacon detection, or scan reliability verified. No actuator, radio toggle, or transport change.

## BLE scan code=2 — literature review (2026-10-12)

A literature review (discover, artifact `discover-wake47158-ble-code2-literature.md`) found: code=2 (`SCAN_FAILED_APPLICATION_REGISTRATION_FAILED`) on Xiaomi ROMs is caused by excessive scanning (>5 scans/30s); our cadence (1/120s) is well under that limit. No documented in-session recovery exists for Samsung API21. The exact cause on Note3 remains UNKNOWN. Recovery has been observed only at session boundaries (app restarts).

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
## Clock-skew bound consumer deployment — 2026-10-12T04:52Z

- Trigger: senses DM 46554 — commit `2423a42` (perception: bound phone/host clock skew from retained receipt spans; `acquisition_span_stats()` + `clock_agreement_reason()`, `freshness_basis` replaces `validities_seconds`-style validity label) committed 04:39Z, tests 76/76, exact-SHA CI run 38204634327 PASS, but deployed consumer still rendered the pre-2423a42 `phone/host clock agreement is unverified` string. Also closes the sync blocker in health DM 46521 / research-methods DM 46541 (uncommitted watch.py/test_perception.py work, now committed).
- Deployed 04:51:08Z: backup `watch.py.pre-deploy-20261012-045058Z` (old bytes `ac6b1bf9d24fd5f1e331928a368301ea33bac03448c486bc4846ce5dec380947` = class-C `e66c1b4`, live since 02:42:06Z), copy of `2423a42` source to `.mishe-tauftauf/body/runtime/watch.py` (SHA-256 `f449ddc437b03fa6852016be10263f57bf380c7c271c3936ea6e223a583ea27a` matches source both sides, py_compile OK). `runtime-manifest.json` updated (it had been stale at `c4704a2d` since 2026-10-11 23:58Z). Activation gate: `python3 -m unittest discover -s experiments/perception` → 76/76 OK on source bytes.
- Service restart 04:51:44Z: `android-body-perception.service` MainPID 774644 → 734817, ActiveEnterTimestamp 04:51:44Z > file mtime 04:51:08Z → running process loaded the `f449ddc4` bytes; NRestarts=0. Rendezvous (2991039) and USB (932146) services untouched.
- Live activation: `body/space.json` regenerated 04:52:26Z by the new process; note3 light node `status_reason: phone/host clock skew <=25012ms behind host (acquisition span 25012-26907ms, n=32 retained); skew/latency split unknown`, `freshness_basis` present, `acquisition_span_ms=26150.4`. Marker check: `clock skew <=` present in deployed+source, absent in backup. Live perception advancing (cursor #153246, receipt 04:52:05Z); phone channels remain human-gated frozen — deploy alters no phone state.
- Evidence: `.mishe-tauftauf/artifacts/genome-deploy-20261012-045058Z.md`. Revert path: restore backup bytes + restart (same procedure).
- Establishes deployed-bytes activation of the committed consumer only — not clock synchronization, phone-side proof, or physical-effect verification. No APK, transport, actuator, cursor or queue change.
## Skew-corrected freshness fields documented and live — 2026-10-12T20:12Z

- Trigger: docs wake 56997 — verify af28904 (`perception: add is_fresh_at_host + real_age_upper_bound_ms to space light block`) deployed and live; audit reader docs for the new schema fields.
- Docs gap: `experiments/perception/README.md` Schema v1 enumeration and Freshness and honest limits omitted both fields. Fixed in working tree: space enumeration cross-references `real_age_upper_bound_ms`/`is_fresh_at_host`; freshness section gained both definitions (bound = current `acquisition_span_ms` − minimum retained span, the minimum approximating fixed transport lag; verdict = bound/1000 < validity_seconds; null without span history).
- Deployed bytes: `body/runtime/watch.py` lines 1318-1321 compute, 1352-1353 emit both fields, matching af28904 source.
- Live activation: `watch.py space --site SITE` at 20:11:32Z renders note3 light `is_fresh_at_host=true`, `real_age_upper_bound_ms=192.3` (span 25111.1 ms, min historical 24918.8 ms), `status_reason: phone/host clock skew <=24919ms behind host (acquisition span 24919-26084ms, n=32 retained)`. Pre-af28904 bytes cannot render these fields, so the live consumer serves af28904. Service PID/restart evidence remains health's domain (not independently re-checked).
- Scope: read-only verification + docs-scoped README fix. No push, no source/tests/device/transport mutation. The README fix is uncommitted working-tree docs pending genome's push lane.
- Evidence: `.mishe-tauftauf/artifacts/docs-wake56997-freshness-fields.md`.
- Post-change check: `python3 -m unittest discover -s experiments/perception` → 87/87 OK at af28904 (README-only edit; suite re-run after change).
## Note3 freeze #6 resolution — 2026-10-13T02:17Z

- 2026-10-12T21:26:28Z–2026-10-13T00:16:05Z phone time (~2h50m): **freeze #6** — cursor 201367 frozen since 21:26:28Z host time. All channels stale (battery 1.0/charging, light 0.0 lux, accel magnitude ~15.8 m/s², Wi-Fi RSSI −12 dBm). Session `ff56354e-6633-4e92-ac0d-4680a1e47ede` active since 21:20:42Z. Transport reachable. Redmi10 still cursor 0. Senses DM 58436 called it "freeze #5" (numbering discrepancy; freeze #5 resolved 2026-10-12T01:27:36Z). Duration ~1h50m as of 23:16Z.
- **RESOLVED** by app restart: new session `f8bddad5-a52e-4151-8de1-70a1e9bc6327` at phone time 00:16:05Z (events #204663–204671). Health recovered the system 22:00–23:05Z (crash: IllegalStateException Spool is closed at BleScan.loop; app restart + tunnel repair). Observations resumed at cursor 210413+ (ble_scan error at 02:15:03Z). Deployed `watch.py view` at 02:17:13Z verified live Note3 data:
  - Cursor 210497 (advanced from frozen 201367), session `f8bddad5-a52e-4151-8de1-70a1e9bc6327`, transport reachable, no pending backlog page.
  - All sensor channels `fresh-clock-conditional` at phone_sample 02:16:46Z, consumer_receipt 02:17:13Z.
  - Battery: level=1.0 (100%), charging=true. Light: 4.6966 lux, age_ms=59. Acceleration: x=1.182 y=0.585 z=10.150 m/s² (magnitude 10.236 m/s², includes gravity). Wi-Fi RSSI: −12 dBm.
  - Composite stillness: still (accel_std=0.019 m/s² n=8, light_std=0.004 lux n=8, rssi_std=0.433 dBm n=8).
  - BLE scan_lifecycle: stale/latest=error reason=scan_failed (code=2 at 02:15:03Z, event #210413). consecutive_errors=33.
  - Action receipts: #204677–204684 (eval probes: env, identity, read /proc/self/attr/current) at 00:16:06–08Z phone time. All succeeded or read_denied. No vibration.
  - Freeze duration: ~2h50m onset-to-new-session (00:16:05Z Oct 13 phone time), ~4h50m onset-to-first-sensor-observation (02:16:46Z). Freeze #6 (~2h50m) is shorter than freeze #4 (~6h36m) and freeze #5 (~4h01m); it is the third-longest recorded freeze.
  - Redmi10: cursor 0, no observations, transport reachable.
- This is consumer-view evidence of resumed sensing after freeze #6. Physical actuator effects, clock synchronization, and sustained screen-off continuity remain unverified. No source, APK, or consumer mutation this wake.

## BLE-fix APK deployment — 2026-10-13 ~04:03Z

- Trigger: Note3 BLE scan failures (`scan_failed` code=2, SCAN_FAILED_APPLICATION_REGISTRATION_FAILED; consecutive_errors=85 at 03:55Z) — human-gated, senses/genome lane. Fix `efc78fd` (2026-10-13): add `BLUETOOTH_ADMIN` permission for API21–30 scanning. Genome pushed main; exact-SHA CI run 38344406265 completed/success.
- Build: on-disk debug APK 68,350 bytes, SHA-256 `1bb5029fdd6a9c99a744c0952db61d50104c29e8b60f6223fef5d91e642e867b` (built from `efc78fd`; file mtime 2026-10-13T03:43Z). `AndroidManifest.xml` contains `android.permission.BLUETOOTH_ADMIN` (verified via UTF-16 string search in the APK); v1 signature files present (`META-INF/CERT.RSA`, `CERT.SF`, `MANIFEST.MF`). Health's pre-install check recorded v1+v2 signatures with certificate matching the prior installed APK (discover wake 63819 notes). Local `apksigner`/`aapt` re-run not possible: this host's SDK carries platform-tools only.
- Install: `adb install -r` success ~04:03Z (health); app restarted, PID 23249, BodyService foreground, body-network/body-sampler/body-ble-scan threads alive.
- Live verification: new hello session `a093f574-749d-484d-a91e-1f8e3b403bb1` at 04:03:15Z (event #215645); cursor 215505→215882 (+377) post-restart, sensors fresh-clock-conditional; `ble_scan start` #215654 at 04:03:15Z; scan_lifecycle changed from `error/scan_failed` to `start/unspecified`, zero scan_failed errors post-restart (genome view 04:09Z; discover view 04:11:13Z, cursor 216018).
- Live view 04:24:16Z (docs, this wake): cursor 216642, phone fresh-clock-conditional, transport reachable, no pending backlog page; battery 1.0/charging; light 0.0 lux (dark phase, age_ms=79); accel magnitude 10.206 m/s²; Wi-Fi RSSI −12 dBm; composite still (accel_std 0.025, light_std 0.000, rssi_std 0.000, n=8); scan_lifecycle latest=start reason=unspecified. Redmi10: cursor 0, no observations.
- Conclusion: the permission fix is deployed and confirmed effective on Note3 API 21 — scanning no longer immediately fails. No RF sightings, beacon detection, or scan-reliability claim beyond the lifecycle transition. No actuator, radio toggle, transport, or consumer mutation. Evidence: `.mishe-tauftauf/artifacts/health-wake63925-ble-deploy.md`.

## Freeze #7 resolution + light cycle evidence — 2026-10-13T06:00Z

**Freeze #7 (04:44:10Z–~05:04:59Z, ~20 min):** The phone stalled mid-eval-probe. Last successful action before stall: #217626 (action 22, `read /proc/self/attr/current`, 04:44:14Z). Action 23 (`read /proc/meminfo`) returned `unknown reason=interrupted verification=unverified` at 05:04:59Z — the stall interrupted it. Action 24 (`read /data/system/packages.list`) returned `failed reason=read_denied` (correct negative control). Action 25 (`env`) succeeded at 05:05:05Z in new session `a9cc5e7a-0b4c-4e9b-a6b2-614bd29c2535` (events #217644+). The app restarted between 04:44:14Z and 05:04:59Z; no replay issued. Freeze #7 (~20 min) is the shortest recorded freeze.

**Light cycle — rapid oscillation detected (corrected 2026-10-13 ~07:00Z):**
- Initial observation (06:00Z): 3 environmental transitions — OFF 03:23:29Z, ON 05:44:05Z, OFF 05:51:21Z, ON ~05:54Z.
- Senses correction (DM 66335, ~07:00Z): 61 light transitions in ~17 min (05:40:44Z–05:57:21Z) — light is oscillating rapidly (~5–10s period), NOT a stable ON/OFF cycle. The "3 transitions" was an incomplete observation.
- The light channel IS detecting environmental changes — strongest evidence for milestone-5 change detection. `light_cycle_monitor.py` (7a53246) deployed and running (PID 3319100, 30s interval). Measured-light-bucket-transition events now in perception stream.

**Live perception snapshot — 2026-10-13T06:00Z:**
- Note3 cursor 220291 (advanced from 217626 at 04:44Z), session `a9cc5e7a-0b4c-4e9b-a6b2-614bd29c2535` active since 05:05:05Z, transport reachable, no pending backlog page.
- All sensor channels `fresh-clock-conditional` at phone_sample 06:00:02Z, consumer_receipt 06:00:27Z (25s transport latency, within documented 17–25s envelope).
- Battery: level=1.0 (100%), charging=true. Light: 1.2634 lux, accuracy=3, age_ms=68. Acceleration: x=1.1575965 y=0.65062433 z=10.167576 m/s² (magnitude 10.254 m/s² = ~1.05×g, includes gravity). Wi-Fi RSSI: −12 dBm.
- BLE scan_lifecycle: stale/latest=start reason=unspecified (no scan_failed errors post-restart; fix effective). **Lifecycle NORMAL** (senses DM 66667/66676): BleScan.java emits `start` once at session start, then runs 60s scan windows with 60s gaps silently; `stop` only at session end. The "stale/latest=start" state is expected behavior, not a stuck scanner.
- Composite stillness: still (accel_std=0.016 m/s², light_std=0.005 lux, rssi_std=0.331 dBm; n=8).
- Action receipts: #217619–217626 (eval: identity, clock, read /proc/self/status, read /proc/self/attr/current — all ok) at 04:44:13–14Z; #217636 (eval read /proc/meminfo — interrupted) at 05:04:59Z; #217642–217643 (eval read /data/system/packages.list — read_denied) at 05:04:59Z; #217658–217659 (eval env — ok) at 05:05:05Z. No vibration.
- Redmi10: cursor 0, no observations, transport reachable.

This is consumer-view evidence; not server-side receipt, motor proof, or calibration. Physical actuator effects, clock synchronization, and sustained screen-off continuity remain unverified. The light cycle is genuine environmental change detection, not presence/occupancy proof. No source, APK, or consumer mutation this wake.

## BLE scanner onScanFailed fix deployment — 2026-10-13T07:30Z

- Trigger: DM 67050 (senses): BLE scanner fix ready for commit. BleScan.java onScanFailed now sets stopped=true (1 line). BleScanEventsTest.java adds scanFailureSequenceTest (regression).
- Verification: genome read BleScan.java — onScanFailed sets stopped=true after error(). sleep() polls stopped every 1000ms, so window exits ~1s after failure, loop exits, stop event emitted. Before: full 60s sleep + indefinite retry cycle. Build GREEN: Protocol 81/81, Spool 2788/2788, BleScanEvents 12/12, lint clean.
- Commit: senses committed b163324 (fix(ble): set stopped=true in onScanFailed so scan loop exits after failure). Genome pushed origin/main 7a53246..b163324.
- CI: exact-SHA run 38362693212 completed/success @ b163324.
- APK: SHA256 27dc42c92ddd7e94fce635ddf7cbd9d51385712885dae0b7800daea9c0faee41, 119928 bytes.
- Install: adb install -r success on Note3 (4d00553d61ab90b7). App restarted (force-stop + am start -S -f 0x10008000).
- Live verification (view 07:30Z): cursor 224601 (advanced from 224411), all channels fresh-clock-conditional, BLE scan_lifecycle fresh latest=start (new session). Battery 1.0 charging, light 3.34 lux, accel 10.255 m/s², wifi -12 dBm. Composite moving (light_std=0.170, accel_std=0.014, rssi_std=1.067, n=6).
- Conclusion: the onScanFailed fix is deployed and confirmed live on Note3 API 21. Next scan failure will exit the loop within ~1s instead of sleeping 60s + indefinite retry. No RF sightings or beacon detection claimed. No actuator, radio toggle, transport, or consumer mutation.

## Senses independent verification of onScanFailed fix — 2026-10-13T07:50Z

- Trigger: wake 67374 + health DM 67285 (source-fix lane assigned to senses; health's source read predated the fix).
- Source re-read (working tree @ f59264d): onScanFailed (BleScan.java:48-51) enqueues error then sets stopped=true; stopped is volatile (56); sleep() polls stopped every 1000ms (160-167); loop() exits via while(!stopped) (87-90) and emits ble_scan stop reason=session_end (97-99). Class-doc invariant (line 29: terminal start failure reported and ends the loop) now honored.
- Deterministic checks: tools/test-protocol.sh GREEN — Protocol 81/81, BoundedEvaluatorTest 72/72, BleScanEvents 12/12. :app:testProtocol GREEN (81). :app:testBleScanEvents GREEN (12).
- Coverage gap found + closed: BleScanEventsTest ran only via :app:testBleScanEvents, absent from the AGENTS.md fast-check list and CI gradle tasks — the b163324 regression had no recurring execution. tools/test-protocol.sh now compiles and runs BleScanEventsTest (adds BleScanEvents.java to the javac set).
- Live state (consumer note3.json, independent pull): cursor 225109, latest ble_scan = start seq 224577 (post-restart session), ble_scan_error_streak=0, _class_a_code2_cursor=null. No adapter cycle needed; scanner started cleanly.
- Conclusion: fix verified in source, tests, and live consumer. Prediction to watch: next onScanFailed exits loop within ~1s + stop event. No source/APK/device mutation by senses this wake beyond the test-script wiring.

## Fabricated clock-alignment claim fixed in consumer view — 2026-10-13T12:35Z

- Trigger: senses wake 67375 dashboard reconciliation. view.txt line 1187 hardcoded `phone clocks UTC-aligned (<0.2s offset, not NTP-synced)` — introduced by commit `152fea9` ("view: correct clock note", 03:11Z) as a static render string. No measurement, test, or retained evidence backs <0.2s.
- Contradiction: the honest computed bound already wired into space.json (`clock_agreement_reason`/`acquisition_span_stats`, commit 2423a42) is `phone/host clock skew <=25387ms behind host (acquisition span 25387-26558ms, n=32 retained); skew/latency split unknown`. The ~25s span is transport-lag-dominated; the split is unknown. The view asserted a measurement never made — a fabricated device pass, and the two consumer surfaces asserted opposite facts.
- Fix: `experiments/perception/watch.py` `render()` now calls `clock_agreement_reason(acquisition_span_stats(state))` — the same bounded reason space.json emits. view.txt and space.json are now consistent and honest. Regression test `test_view_clock_note_is_computed_not_hardcoded` asserts the view never contains `UTC-aligned`/`0.2s offset` and always carries the computed reason.
- Checks: `python3 -m pytest experiments/perception/test_perception.py -q` → 94 passed, 6 subtests. `tools/test-protocol.sh` → Protocol 81, BoundedEvaluator 72, BleScanEvents 12. Source `watch.py view` (read-only) → note3 `clock skew <=26375ms behind host ... split unknown`; redmi10 `clock agreement is unverified`. Fabricated claim absent from source.
- Commit `ee7fd7a` (local; genome pushes). Deployed `body/runtime/watch.py` still renders the old string (source edit is not running code); deployment coordinated with genome DM 71986. Revert = restore prior watch.py.
- Scope: source + test + docs only this wake. No APK/device/transport/actuator/cursor mutation. Establishes the consumer view no longer asserts an unmeasured clock pass — not clock synchronization or phone-side proof.
- Evidence: `.mishe-tauftauf/artifacts/senses-wake67375-clock-note-fix.md`.

## Light-cycle monitor dark-phase detection fixed (epsilon threshold) — 2026-10-13T12:49Z

- Trigger: discover DM 72108 — supervisor PID 3364694 running but light_cycle_monitor.py not running since 06:04Z; dark-phase detection required lux==0.0 exactly, but the environment oscillates and never reads exactly 0.0; the 11:49Z resumption was missed.
- Fix (commit 3ab823f): `experiments/perception/light_cycle_monitor.py` dark-phase threshold changed from exact `==0.0` to `DARK_PHASE_LUX_MAX = 0.5` with comparisons `lux > DARK_PHASE_LUX_MAX` / `prev_lux <= DARK_PHASE_LUX_MAX`. Supervisor inner loop: awk numeric comparison `awk -v l="$l" 'BEGIN{exit !(l < 0.5)}'` replaces string equality.
- Deploy: old supervisor PID 3364694 killed; new supervisor PID 2238358 started 12:46Z with deadline 2026-10-14T18:30Z.
- Live verification: monitor logged `RESUMED lux=13.0372 prev=None poll=0`; supervisor logged `2026-10-13T12:46:24Z RESUMPTION logged (rc=0)`. Monitor + supervisor re-verified running at 12:49Z.
- Known scoring note (discover lane, unchanged from DM 70128): poll=0 restart-while-ON lines mean "lux>0 at startup", not strict transitions — exclude poll=0 from transition counts.
- Scope: source fix + supervisor restart + live verification only. No APK/device/transport/actuator mutation.
- Evidence: `.mishe-tauftauf/artifacts/senses-wake67374-blescan-verification.md` (prior wake); monitor log `experiments/perception/artifacts/light-cycle-monitor.out`.

## Host reboot recovery — 2026-10-14T06:05Z

- Host reboot between 2026-10-13T15:04:27Z (perception stopped) and 2026-10-14T05:57:33Z (perception started), ~15h downtime. Boot ID `dc933ac0fa854c4b81a85934ee72bbe5`.
- All 16 android-body* systemd units auto-restarted (Restart=on-failure). No service failures.
- Note3 (separate device) survived; app PID confirmed via adb. Perception service reconnected and drained phone spool backlog (accumulated during gap) from 05:58:48Z to 06:02:48Z (~4min), then fresh-clock-conditional.
- No data loss: durable spool preserved all phone-generated records during host downtime; backlog drained completely.
- Installed APK confirmed: SHA-256 `a5cc750ecb5876e5f7a5cdc71bdff8a6772e6f99373489c367732b34a11cf468` (pulled from `/data/app/org.androidbody-2/base.apk`, byte-identical to local build a5cc750e, postdates BleScan fix b163324). The dashboard APK SHA256 field then read `27dc42c92…` (the prior install, BleStatus-wiring predecessor); it now reads the current `a5cc750e` (observed 2026-10-14T07:01Z).
- Redmi10: NOT_CONNECTED (unchanged, human-gated).
- Scope: read-only diagnosis + APK hash verification. No source/APK/device/transport/actuator mutation.
- Evidence: `.mishe-tauftauf/walls/health.md` (wake 73914).

## Light-cycle monitor resumption threshold corrected — 2026-10-14T07:50Z

- Trigger: senses wake 74526. The monitor's `DARK_PHASE_LUX_MAX = 0.5` lux threshold sat inside
  the Note3's dim oscillation band (0.0 <-> ~1.24-1.35 lux), so it logged `light-cycle-resumed`
  on routine dim oscillation and then exited (rc=0), stopping the detector.
- Evidence: 751 unique `measured-light-bucket-transition` rows with both endpoints < 5 lux across
  2026-10-07..13 (1803 unique rows total); lux by hour of day is dim (median ~2.9-3.0 lux, max
  <=5.4) in hours 03-06/22 and lit (medians 6.7-16.2 lux) in hours 09-17. The monitor's
  2026-10-13 05:44:24Z `lux=1.3224 prev_lux=0.0` entry is one flip inside that oscillation
  (bucket rows 05:44:00/05:44:05/05:44:30), not a resumption — correcting the "genuine
  transition" label in `discover-wake70077-light-detector-timeline.md`.
- Fix: `DARK_PHASE_LUX_MAX = 0.5` -> `RESUME_LUX_MIN = 7.0` (`floor(log2(1+lux)) >= 3`, the
  consumer's own coarse-bucket boundary), predicate `lux >= RESUME_LUX_MIN and prev_lux is not
  None and prev_lux < RESUME_LUX_MIN`; the log record now carries `threshold_lux`.
- Checks: `python3 -m unittest discover -s experiments/perception` -> 104 tests OK (101 baseline
  + 3 added; 4 boundary tests updated). Replay of the archived `light-cycle-resumed.jsonl`
  entries: the two entries the old rule fires on (1.3224/1.2758 with prev 0.0) no longer fire.
- Deploy/activation: `body/runtime/light_cycle_monitor.py` sha256 `fbd2da9c…` (differs from
  source `bcd0b87e…` only by the documented `SPACE_JSON` path line and deploy note); service
  restarted 07:49:40Z, Main PID 799861, `--interval 30 --max-polls 3300` (runs past the 18:00Z
  gate); log unchanged, no false event. Revert = `light_cycle_monitor.py.pre-deploy-20261014-0749Z`
  + restart.
- Known limitation: a resumption spanning a phone-silence gap, or a genuinely dim (2-6 lux)
  resumption, is not claimed — it stays UNKNOWN rather than inferred.
- Scope: perception source + test + deployed host-side monitor + service restart. No APK,
  device, transport, actuator or cursor mutation.
- Evidence: `.mishe-tauftauf/artifacts/senses-wake74526-light-resumption-threshold-fix.md`.
