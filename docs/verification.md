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
| `:app:lintDebug` | PASS, zero errors and one expected warning |
| `:app:testProtocol` / standalone protocol harness | PASS, 68 assertions |
| `:app:testSpool` / standalone spool harness | PASS, 2,788 assertions |
| Rendezvous unittest suite | PASS, 18 tests |
| Shell/awk demo unittest suite | PASS, 8 tests |
| Additional independent spool/reload checks | PASS, 1,711 checks |
| Additional independent journal truncation/CRC checks | PASS, 189 checks |
| Additional independent persistent-settings checks | PASS, 24 checks |

The lint warning is `UnusedAttribute`: Android below 23 ignores `usesCleartextTraffic`. Endpoint/transport validation enforces the explicit HTTP opt-in on every supported API. Legacy service/vibration paths are intentionally guarded by SDK checks; compilation reports deprecation notes.

The queue tests cover process exit/reopen, per-endpoint isolation, durable append/acknowledgment, immutable in-flight tokens, overflow bounds/loss notices, every incomplete transaction tail, complete corruption rejection, compaction, single-owner locks, explicit corrupted-queue discard, and randomized state replay. File-descriptor checks establish that ordinary enqueue/ACK extends the journal instead of rewriting the retained data. The full queue is compacted only at its bounded threshold.

Persistent-state checks cover endpoint-matching enable markers, failed preference OFF with independent marker deletion, newer user-stop records and explicit-ON overrides, API18 guards and the eight-destination limit. Source review also covered stopped-session ordering, OFF/clear races, mode-save failures, notification modes, local-storage errors versus network errors, and durable action receipts. No remaining known high/medium source blocker was found in this freeze. These checks do not certify OEM survival or physical effects.

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

Real Samsung Note3, real Xiaomi and contemporary physical Android validation are **NOT RUN**. Actual motor behavior, sensor calibration, old firmware HTTPS trust, Xiaomi process retention, heat/battery drain, and multi-hour screen-off continuity remain unverified. Use the [device checklist](compatibility.md#physical-validation-checklist--all-unrun).

Neither `START_STICKY` nor the ON-only partial wake lock guarantees uptime or bypasses Doze, Force stop, notification controls or OEM restrictions. The saved ON bit is an intention, not proof of live collection. Android's vibration API return remains `verification=unverified` without independent physical evidence.

## Reproduce the host checks

```sh
tools/test-protocol.sh
tools/test-spool.sh
python3 -m unittest discover -s rendezvous/minimal-server
python3 -m unittest discover -s experiments/light-vibrate
./gradlew --no-daemon :app:assembleDebug :app:lintDebug :app:testProtocol :app:testSpool
"$ANDROID_HOME/build-tools/35.0.0/apksigner" verify --verbose \
  app/build/outputs/apk/debug/app-debug.apk
```

Install dependencies from official vendors, accept the SDK agreement, and keep generated signing keys outside version control. The Gradle distribution checksum is pinned. Recheck APK size/hash after source/resource changes; independently signed/debug-built artifacts can have different bytes and upgrade identities.
