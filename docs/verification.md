# Verification record

Checked 2026-10-07. Version 0.2 adds persistent ON and durable collect/upload-later behavior. Host/build evidence is separate from Android runtime and physical-device evidence.

## Built artifact

- Application: `org.androidbody`, version `0.2.0` (code 2)
- Build: debug APK, Java source 8, JDK 17, Gradle 8.11.1, Android Gradle Plugin 8.10.1
- Compile/target SDK 36, minimum SDK 18
- APK: `app/build/outputs/apk/debug/app-debug.apk`
- Size: 88,103 bytes
- SHA-256: `417719c5811ca0acf9546577b8ef54bd80e212d18a5acfa28fe139203d8a261b`
- `apksigner verify --verbose`: PASS, v1 and v2 signatures verified
- `aapt dump badging`: confirms version 2, minimum 18, target 36 and the intended permissions, including boot completion

The version 0.1 and 0.2 signer certificate SHA-256 digests were compared and match, preserving signing continuity for an in-place upgrade. Its private key is not in the repository. `apksigner` reports the usual v1 warning that Gradle's `META-INF/com/android/build/gradle/app-metadata.properties` is not covered by the v1 JAR signature; the complete APK's v2 signature verifies. This is not a production release-signing identity or device certification.

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
The latest published source checkpoint is commit `b596eaa9d6d360e2bacc39444686b717c14d9073`. [GitHub Actions run 37596299457](https://github.com/genaforvena/android-body/actions/runs/37596299457) **PASSED** for that exact SHA: protocol (68 assertions), spool (2,788), rendezvous (18 tests), light/vibration (8), perception (7), Android build/lint and both artifact uploads. Observed warnings included Java 8 bootstrap/deprecation, Node 20-to-24 action migration, setup-java v4 retirement, Ubuntu 26 migration and Node `punycode`/`url.parse` deprecations.

The downloaded APK member was 54,107 bytes, SHA-256 `ad8ae0e2baca6e76ea4553bbebe76a9912bc147cb1b8eae92d6c095e0e0c624b`. Retained Ubuntu `apksigner` 31.0.2-1ubuntu1 verified v1/v2 signatures, including explicit API18 v1 and API24 v2 checks. Its RSA-2048 debug signer certificate SHA-256 `a03eee7f5f810f8bb303fb033be36cc91626b99061eb0d7a037fa0d5a1e9bfbd` differs from both the prior CI signer and installed/published signer `039da4473796b1851e2546219e1ab0005387956ba85425cea30cad9558f00c071`; no signing continuity or update acceptance follows. An API18 v1 negative control with a changed `classes.dex` byte was rejected for manifest digest mismatch. The rebuilt negative-control ZIP lacked a v2 signing block; `META-INF/com/android/build/gradle/app-metadata.properties` remains outside the v1 JAR signature. The retained lint report lists two warnings (`UnusedAttribute`, `AndroidGradlePluginVersion`), no errors, and 39 disabled checks; this is not comprehensive platform acceptance. No artifact was installed and no physical validation is claimed.

The artifact ZIP's reported size/digest are upload metadata, not APK-member measurements. The APK member and lint report were separately inspected; these results apply only to this CI run.

The preceding published source checkpoint recorded here is commit `eb911611b23344394449426d97f931dc794fb66c`. [GitHub Actions run 37594711578](https://github.com/genaforvena/android-body/actions/runs/37594711578) **PASSED** for that exact SHA: protocol (68 assertions), spool (2,788), rendezvous (18 tests), light/vibration (8), perception (7), Android build/lint and both artifact uploads. Observed warnings included Java 8 bootstrap/deprecation, Node 20-to-24 action migration, setup-java v4 retirement, Ubuntu 26 migration and Node `punycode`/`url.parse` deprecations. Subsequent inspection measured the APK member at 54,110 bytes, SHA-256 `960f86c82057cee8f47a7611765a433328ff4ac1c81c81c6033f35f276069522`; its extracted public-certificate fingerprint `3c066a90c38979…

The preceding published checkpoint `a0aa8532d0b827c0785f46e9c9f4c8682ae976b8` passed [run 37593836353](https://github.com/genaforvena/android-body/actions/runs/37593836353) for that exact SHA, with the same listed test counts, Android build/lint and artifact uploads. Its lint report listed the same two warnings: API18 ignores manifest `usesCleartextTraffic`, and the pinned Gradle wrapper 8.11.1 is older than lint's 8.14.5 recommendation. Source independently gates HTTP on explicit user opt-in; no security test, upgrade or suppression is claimed. Its uploaded APK member was not independently measured or signature-checked.


The public [GitHub repository](https://github.com/genaforvena/android-body) contains the full source, CC0 license, third-party notices and the installable debug APK. The initial 54-file upload was verified against the staged Git tree, including executable modes and binary blob hashes.

[GitHub Actions run 37584419974](https://github.com/genaforvena/android-body/actions/runs/37584419974) **PASSED** for commit `d76f9badcd427ee102ad1d0ea923fe85525a76bc`: SDK setup, the boundary tests, Android build, lint and artifact uploads. The first run stopped before tests because the setup action tried to install the obsolete SDK package `tools`; the workflow now requests only `platform-tools` and avoids blanket acceptance of unrelated SDK add-on agreements.

The committed APK's download was exercised through GitHub and independently checked at 88,103 bytes with the SHA-256 above. The CI workflow builds another debug-signed APK; its bytes/signing identity are not claimed to match the committed download. A green build does not add physical-device evidence.

An independent comparison of the retained published APK and a retained APK member from run 37592181603 found different APK SHA-256 values and different public signer-certificate SHA-256 fingerprints: published APK `417719c5811ca0acf9546577b8ef54bd80e212d18a5acfa28fe139203d8a261b` / certificate `039da4473796b1851e2546219e1ab0005387956ba85425cea30cad9558f00c071`; CI APK `e7c1f9f8df6d1896fd6045b2f1c14f2e60045ebad6c7509ea738669263913c72` / certificate `f4b34bd34b10374d7ea574048da8b00f7b316273e74ded581b65d9e57a19eb79`. Both certificates have an Android Debug subject, which does not establish signer equality. This comparison concerns that earlier CI artifact only; no update attempt, signature-validation result for that CI APK, or device acceptance is claimed. The installed APK's v1/v2 verification and its version 0.1/0.2 signer continuity remain the separate evidence recorded above.

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

## Reproduce the host checks

```sh
tools/test-protocol.sh
tools/test-spool.sh
python3 -m unittest discover -s rendezvous/minimal-server
python3 -m unittest discover -s experiments/light-vibrate
python3 -m unittest discover -s experiments/perception
./gradlew --no-daemon :app:assembleDebug :app:lintDebug :app:testProtocol :app:testSpool
"$ANDROID_HOME/build-tools/35.0.0/apksigner" verify --verbose \
  app/build/outputs/apk/debug/app-debug.apk
```

Install dependencies from official vendors, accept the SDK agreement, and keep generated signing keys outside version control. The Gradle distribution checksum is pinned. Recheck APK size/hash after source/resource changes; independently signed/debug-built artifacts can have different bytes and upgrade identities.
