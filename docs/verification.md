# Verification record

Checked 2026-10-07; updated through 2026-10-21. Version 0.2 adds persistent ON and durable collect/upload-later behavior. Host/build evidence is separate from Android runtime and physical-device evidence.

## Current delivery observation — 2026-10-21

At 2026-10-21T12:52Z the same view read Redmi10 delivering again: `channel-delivery [pass]: cursor=advancing`, cursor 183,296 (cadence 6.9 s, n=8, max 20.6 s). Its silence since 11:32:06Z **closed at 12:41:06Z after 4,139.7 s (69.0 min)**, resuming as a 128-record page and draining 37 writes / 3,592 records / 367,385 B by 12:44:30Z; the phone's spool summary is unread, so whether that window cost it records is unknown.
The accepted-POST census (`body/queues/writes.jsonl`, gap > 60 s) holds 30 gaps with onset since 00:00Z, worst 4,139.7 s (`11:32:06.312→12:41:06.056Z`); it reports completed gaps only, and the two short gaps around the drain (73.2 s, 69.3 s) are below the consumer's class-c 120 s window, whose last row is 11:34:07Z (cursor 179,340).
The 618.6 s window is journal class A — no line from the phone's tailnet address in-window — and the 63.8 s window at 09:10:00Z is B; the morning 23 are 21 B, 1 D, 1 A, so one `[pass]` instant is not a no-gap claim.

Note3 was `ON_COLLECT_ONLY` at 12:51:18Z (`status=ok`, age 11.7 s) with cursor 265,956 unchanged and spool 3,622,326 B / 26,092 rows / 739,181 cumulative drops (737,757 at 12:30Z), coverage ok.

At 2026-10-21T00:04:28Z the deployed perception consumer reached both configured endpoints. Redmi10 was delivering: `channel-delivery [pass] cursor=advancing interval=30.0s age=4.1s cadence=4.095s(n=8,max=6.117s)`, cursor 145,940 (it read 99,400 at the 2026-10-20T07:37:18Z observation below). Battery 0.34 `charging=true` and light 20.0 lux were `fresh-clock-conditional` at 00:04:20Z; acceleration was `unavailable reason=stale` at that instant; `wifi_link_rssi_dbm` was `unavailable reason=disconnected`, the app's `getNetworkId() < 0` API verdict rather than proof the link is down. Its app-private spool summary is still absent, so no collection-side reading exists for it. Freshness here is a delivery verdict, not occupancy, motion or presence evidence.

Note3 remained `ON_COLLECT_ONLY` and silent since 2026-10-14, last valid sensor records 2026-10-14T06:13:24Z (receipt 06:13:52Z); its delivered cursor is still 265,956 with no page pending. Its app-private spool (2,486,014 bytes, 18,122 rows, 684,674 cumulative drops, physical-file window 4.0h, coverage ok) is collection-side evidence only and does not establish delivery. Drops grew 613,773 → 684,674 over the 16.5h since the 07:37Z read, ≈1.2 rows/s, while the retained window stayed at 4.0h: the phone emits about as fast as the 2 MiB bound evicts, so the window is a steady few hours and the loss is explicit in the cumulative count instead of silent.
Endpoint reachability and host service state are not phone liveness.

Source: deployed `body/runtime/watch.py view --site .mishe-tauftauf`, read 2026-10-21T00:04:28Z (re-read at 00:03:24Z with identical Note3 values) and re-read at 09:57Z, 12:19Z and 12:52Z, plus the endpoint queues under `body/queues/` and the gap census in `docs/node-cards.md`.

Checked cause of the Note3 silence (2026-10-20, genome). The delivered cursor 265956 is the *head* of `body/queues/note3.observations.log` — 265,956 lines, unchanged since 2026-10-14T08:58:03Z — so no page is pending and no parser condition is involved.
Its last two rows are host-side test rows (`265955 invalid line here`, `265956 invalid line here`) whose envelopes are valid: replaying the whole queue through the deployed `parse_page` in 128-line pages consumes all 265,956 records with zero failures and ends at cursor 265956.
The earlier "frozen on a malformed row" / "malformed-row parser boundary unreconciled" reading is therefore disconfirmed.
The silence is by design: with the phone's owner collect-only checkbox set, `BodyService.java:310` short-circuits the network loop before any HTTP, matching the host-side verdict `mode=ON_COLLECT_ONLY` / `collect-only: no HTTP by design`.
Delivery resumes when that owner control changes, not by any consumer, queue or cursor repair. The handset-persisted cursor/action state remains unread (app-private); do not infer it from the host consumer cursor or mutate queues/cursors.

## Built artifact

- Application: `org.androidbody`, version `0.2.0` (code 2)
- Build: debug APK, Java source 8, JDK 17+, Gradle 8.11.1, Android Gradle Plugin 8.10.1
- Compile/target SDK 36, minimum SDK 18
- Published APK rebuilt 2026-10-20T23:15Z (genome `1f9245a`): 73,653 bytes, SHA-256 `a5be0e4341eb3754716a437063baa0ab8ddd3d633629dc056bbead0c1e51d1ae`, signer `d23dcc9d` (v1+v2 PASS), `tools/check_published_apk.py` GREEN (10 entries, payload matches the build) and 14 local headers == 14 central-directory entries, so no orphaned zip entry. Clean build of `3047f17`, which adds the reader-side condition to `BoundedEvaluator` (the third exec-path class); the comment-only `6fa8601`/`e707a4a`/`3047f17` changes moved the dex CRC with no executable line changed. **The Note3 does not run these bytes**; it runs `87b36024…` below. Supersedes the three records below.
- Superseded published downloads, newest first ([downloads](../downloads/README.md)): 73,660 bytes, SHA-256 `2f6f3295a474e0b1df5c2cdd712ee3a53d722dae98b0f668528a2203e0b5b2de`, clean build of `e707a4a` (`5293940`, 2026-10-20T22:35Z); 73,650 bytes, SHA-256 `9678d87c7d03ff7fc9a372d22a090fd679a7c3420265c729c5907c4eb38add0e`, clean build of `6fa8601` (`f763d09`, 2026-10-20T21:57Z); 73,656 bytes, SHA-256 `04439ff919c9d7ae0cd6be6d7205f7136de110a71e05f5767e6885ef9565dbe4`, clean build of tip `b025ede` (`1e37739`, 2026-10-20T20:17Z); signer `d23dcc9d`, `apksigner` v1+v2 PASS on all.
- Clean-rebuild check (2026-10-20, genome, tip `08d7e8c`): `./gradlew --no-daemon --offline :app:clean :app:assembleDebug` with JDK 17.0.20.1, Gradle 8.11.1, Android Gradle Plugin 8.10.1 and build-tools 35.0.0 produced `app-debug.apk` byte-identical to the published download (73,358 bytes, SHA-256 `87b36024…`), so the documented install path is a clean build of the current tip and not only of `e0ea84d`.
  `apksigner verify --min-sdk-version 18` PASS (v1+v2) on both files and `tools/check_published_apk.py` GREEN (10 entries); nothing under `app/` has changed since 2026-10-16T15:47Z (`697d68a`).
- Installed on Note3: 73,358 bytes, SHA-256 `87b36024b0a5fb15ba0cfb7be2db258ec4c4a585574736bda96330a504bdafe7` — the published download until 2026-10-20T20:17Z (source `e0ea84d`, app bytes `697d68a`), installed 2026-10-16T16:16:48Z by a bounded `adb install -r` (health wake 101154, genome DM 101127); the on-device pull hashed equal, `activation_probe.py` at 16:18:49Z reported `recorded == observed`, and exact-SHA CI run 38929314768 at `b6eaf1f` passed. Carries the consumer `eval write`/`eval exec` verbs, the `BoundedExec.waitForExit` fix, the `697d68a` `EvalOutcome` bound and in-process `0c83e32` `ExecProbe`; signer `d23dcc9d` (v1+v2); `-r` preserved app data and the spool; supersedes `5e7fa255…` (70,796 B) and `bb66a3f4…` (119,184 B), details in Git history.
  Correction 2026-10-20T23:15Z (genome `1f9245a`): the installed build above was the published download until 2026-10-20T20:17Z; the current download is `a5be0e4…` (73,653 B, clean build of `3047f17`). The device has not been updated, so the install evidence still binds `87b36024…` and not the current download.
- `apksigner verify --verbose`: PASS, v1 and v2 signatures verified
- `aapt dump badging`: confirms version 2, minimum 18, target 36 and the intended permissions, including boot completion

The signer certificate SHA-256 `d23dcc9d24fbdce556150931f54051b44fdf45c465694710d687c88464be028a` has been constant across the current lineage since the 2026-10-11 signing-blocker resolution (self-heal checkpoint and every Note3 redeploy since), preserving signing continuity for in-place upgrades. The private key is not in the repository. `apksigner` reports the usual v1 warning that Gradle's `META-INF/com/android/build/gradle/app-metadata.properties` is not covered by the v1 JAR signature; the complete APK's v2 signature verifies. This is not a production release-signing identity or device certification.

Session start wires BleScan (`ble_scan start` spool events in every session since the BleScan build) and the eval route (`executeEval` since the eval-wiring build `8f2c8b18`, installed 2026-10-12T21:05Z; every eval probe since executes in-app). Both are present in the current installed APK, as is the eval-outcome clamp (`EvalOutcome.java` since `e5615d5`, installed 2026-10-14T18:47Z). Per-run deployment detail is in Git history.

## Exec reader contract — `ok=true` carries only pre-exit bytes (docs, 2026-10-20)

- Trigger: docs reader review of the `exec` `output=` claim in `docs/actions.md` after the `4e4caba` reader-contract change and the `04439ff9…` download rebuild (`1e37739`, genome wake 119604).
- Measured host-side, one case per fresh JVM, JDK 17.0.20.1, `/bin/sh`=dash, load 15.4–16.9, against the superseded published source (`e0ea84d`, `BoundedExec.java` sha256 `0d35221a…`) and the current source (`4e4caba`, `366a5d54…`, carried by the download `04439ff9…`): `echo hello; exit 0` → `ok=true output=[hello] exit=0` in both; `echo before; sleep 4 &; exit 0` → `ok=true output=[before]` with the descendant alive in both; `(sleep 3; echo late) &; exit 0` → `ok=true output=[]` in both (10/10 fresh JVMs); `sleep 8` → `ok=false timedOut=true destroyed=true`; >4096 B → `unavailable reason=IOException exec output exceeds probe bound`.
- Re-measured 2026-10-20 (docs wake 121741 addendum) on the same class bytes, direct-child lifetime swept: whether the +3 s descendant write is delivered is a race on whether the reader's blocking read had begun before the direct child exited — not a property of the bytes.
- Deterministic region: with the direct child alive 0.1–1 s the reader is already blocked and the write arrives at ~3 s (6/6 fresh JVMs at each lifetime, 5 s join). The shipped join is what bounds it: `READ_JOIN_MS=1000` gives `unavailable reason=… exec stdout open at direct-child exit` (6/6 at 0.1–1 s), never the bytes.
- Boundary: a direct child exiting within ~20 ms splits run to run — 6/6 dropped, then 4/6 `unavailable … open at direct-child exit` + 2/6 dropped at the shipped join; 2/6 delivered at ~3.0 s, then 6/6 dropped at a 5 s join — so the earlier "never delivered" reading is false.
- Reading: `ok=true` carries only what the reader observed before the direct child exited. A descendant holding the merged stream open can leave the reader parked at that exit; a write it makes only after that exit is delivered only if the reader's blocking read had already begun, and never when the reader's join budget expires first, so an empty `output=` cannot distinguish "the target printed nothing" from "output was dropped" — the reason an exec target must not background processes. The parked-reader case is named as a failure outcome (`unavailable reason=… exec stdout open at direct-child exit`), the visible signal when a descendant outlives the 1 s join.
- Artifact check: `unzip -p downloads/android-body-debug.apk classes.dex` (113,380 B) contains `exec stdout open at direct-child exit`, so the current download `a5be0e4…` carries the change.
- Docs change: `docs/actions.md` states the pre-exit-only contract instead of `output=<merged stdout+stderr>`, and (2026-10-20) conditions the shipped-join outcome on the reader's state; the earlier unconditional "instead of the bytes" form was wrong for the immediate-exit shape (witness wake 122425).
- Parked-reader condition (2026-10-20): `docs/actions.md` reports `unavailable reason=… exec stdout open at direct-child exit` when the reader's blocking read had already begun at the direct child's exit, and the silent empty `ok=true` as the measured majority when it had not (19/20 cold, 14/20 warm; witness wake 122305). The app side carries the same condition (`BoundedExec.java:52-57`, `ExecProbe.java:26-27`, `BoundedEvaluator.java:46-53`/`:386-393`, `e707a4a`/`3047f17`).
- Limits: host JVM only; the Note3 still runs `87b36024…` (`e0ea84d`), so ART's process-exit handling on-device is UNKNOWN. No device, transport, APK install, protocol, cursor, queue, spool, service, radio or actuator action; no `adb reverse --list`.
- Evidence: `.mishe-tauftauf/artifacts/docs-wake121741-exec-reader-contract.md` (first measurement) and `.mishe-tauftauf/artifacts/docs-wake121741-exec-race-supersedes-never-delivered.md` (the lifetime sweep that falsified "never delivered", with the raw per-cell outputs).

## Checks actually executed

| Check | Result |
|---|---|
| `:app:assembleDebug` | PASS |
| `:app:lintDebug` | PASS, zero errors and two warnings |
| `:app:testProtocol` / standalone protocol harness | PASS, 81 assertions |
| `:app:testEvalOutcome` / standalone eval-outcome harness | PASS, 29 assertions |
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

The public [GitHub repository](https://github.com/genaforvena/android-body) carries the source, CC0 license, third-party notices and the installable debug APK. `.github/workflows/check.yml` runs on every push and pull request: the protocol, spool and ble-probe shell harnesses, the rendezvous, light/vibrate, perception, minimal-substrate, trial-eval and tools unittest suites, then `:app:assembleDebug :app:lintDebug :app:testProtocol :app:testSpool :app:testRestore :app:testExecProbe :ble-probe:testProbeReport :ble-probe:lintDebug` (the ble-probe tasks compile and lint the module's Android sources; it builds against `compileSdk 34`), an `apksigner verify --min-sdk-version 18` check that the b…

CI runs on the pushed tip, so a commit below the tip shares the tip's run. A run is named here only where a change needs one as evidence — the installed-APK payload run under [Built artifact](#built-artifact) is the current example; a tip's CI status is read from GitHub, not recorded here per push. This record is not a per-run ledger, and docs does not create a commit solely to record a CI run.

Uploaded APK members from several recent CI runs were independently measured and `apksigner`-checked: manifest-range v1/v2 with explicit API18 v1 and API24 v2 ranges; a changed-`classes.dex` API18 negative control was rejected for manifest digest mismatch, and no v2 tamper test is claimed for the rebuilt ZIP. The `a0aa8532` run's uploaded member was not independently measured or signature-checked. The measured CI APK bytes and public signer fingerprints differed from the then-published APK's (Android Debug subjects on both sides, so signer equality is not established either way); no update acceptance, API18 installation or physical-device behavior follows. CI builds its own debug-signed APK each run; it is not the published download.

The published APK download has been exercised through GitHub and byte-checked (current value under [Built artifact](#built-artifact)); the earlier 88,103-byte published APK was checked the same way.

## Android runtime evidence for this version

The full **API18 / Android 4.3.1 emulator** acceptance suite below ran on the preliminary version 0.2 APK `ff03c32eccb690fb330ec2b3c22167938c0e4f4ff2905c7bfe0dc1a260dd8ee7`. The final APK above changes only the queue's default retention constants to 2 MiB / 24,576 lines; queue format, algorithms, service and UI logic are unchanged. The final defaults passed both Java suites and a bounded-heap host stress test. The focused final-artifact smoke **PASSED** on API18: install, ON, observation/vibration roundtrip, live collect-only (nine saved records and zero HTTP after transition), live backlog drain and OFF. After OFF there was no queue growth, upload, running service or held CPU wake lock. The queue inspector used the final constants. The full complex suite before the constants change also passed: install/cold launch, native ON and actual notification OFF; offline records survived process SIGKILL from Home (the service restarted with a new PID, retained the original 12 lines, continued to 27, and delivered all 27 on reconnection); sampling continued while HTTP was held (3 to 9 saved); rapid OFF/ON/OFF/ON with an old blocked request left the new session operational; live collect-only saved 15 lines with zero HTTP requests after mode transition settled and did not execute the queued command; endpoint A's 18 pending lines stayed separate while endpoint B was active, and returning to A drained all 18 and resumed its queued action without restarting the process.

These are emulator runtime/transport observations; a vibration receipt remains physically unverified. Saved ON restored automatically after a cold power cycle of the same persisted emulator data, without opening the activity. Explicit OFF stopped both sampling and network work and stayed OFF after another cold start and manual app launch. An in-guest API18 adb-reboot command separately crashed the QEMU engine before Android boot; that command is not claimed as a pass. The cold-start boot-receiver scenarios did pass. **API34 / Android 14:** the preliminary version 0.2 APK installed and the app/permission UI rendered. A bounded recovery attempt still encountered system-wide ANRs involving System UI, system, Bluetooth, launcher and phone processes. ON/collection behavior on API34 is not established.

## Retention memory check

A temporary host build with the final 2 MiB/24,576-line limits passed fill, near-full 4 MiB journal reopen, overflow, compaction and drain under a 32 MiB JVM heap plus an 8 MiB synthetic live reserve for the rest of the app. Both 80-byte and 120-byte record workloads passed in about one second. Sampled heap peaks were about 27 MiB, with roughly 12–13 MiB live after GC including the reserve. These are host JVM measurements, not an Android device memory certification.

The larger 4 MiB option was not shipped: under the same 32 MiB heap plus reserve its near-full journal reopen stalled. The chosen 2 MiB buffer holds approximately 10 hours at representative 80-byte records **at the three lines per five seconds of that APK** (metadata counts toward the byte limit), with actual retention dependent on record sizes and traffic; the shipped sampler emits six rows every five seconds — five per-cycle kinds plus a per-cycle `ble_scan_state` row while the scan loop runs — so the same bound retains roughly five hours of 80-byte records (deployed ~130-byte records hold a few hours; device figures in [observations](observations.md)). Overflow is explicit; it is not a lossless time-window guarantee.

## Physical boundaries

**Samsung SM-N900 (Note3), Android5/API21, firmware `LRX21V.N900XXSEBRH3`: bounded physical smoke ran on 2026-10-07.** The installed final 0.2.0 APK matched the SHA-256 above and passed v1/v2 signature verification. Connection was authenticated HTTP through authorized USB reverse forwarding to a host-loopback listener; no LAN exposure, TLS bypass or battery/security-policy changes.

Native ON/OFF controls exercised through fresh accessibility selectors; actual battery, ambient-light and accelerometer records reached the text rendezvous and read-only consumer. Startup `no_sample` remained unavailable rather than becoming zero. One 200ms vibration request produced requested/succeeded receipts with `evidence=api_return verification=unverified`. Motor movement was **not independently verified**; the request was not retried. Collect-only saved observations while the server queue stayed unchanged after transition; displayed saved count increased from 3 to 15. Returning to sending drained the retained records with original times. OFF produced no queue additions during a 10s observation, no running Body service or held `AndroidBody:session` wake lock, and no persistent enable marker. The consumer aged its evidence to stale and suppressed current derived magnitude. ON restored fresh-clock-conditional observations. Killing the app's own process from Home restored it with a new PID and a new session; delivery resumed. This is process-loss evidence, not a reboot/OEM-survival claim. With the display confirmed OFF, collection and delivery continued through a 15s charging interval. Multi-hour, unplugged and thermal behavior remain untested. A 35s deliberate USB mapping outage left the host observation cursor unchanged and current perception stale; restarting the bridge restored backlog delivery and subsequent current readings without another action request. Repeated transport loss occurred during old Samsung `adb reverse --list` polling. That probe was removed; generation-based connection observation and mapping creation kept the transport stable across subsequent physical checks. The debugging-daemon cause was not independently established. The phone clock was approximately 17s behind the host. The consumer did not alter or calibrate it; freshness remains explicitly clock-conditional.

The integrated host checks passed: protocol 68 assertions, spool 2,788 assertions, rendezvous 18 tests, light/vibration 8 tests, and perception 7 tests. Android source and APK were unchanged in this integration; no new Android build/lint pass is claimed.

Real Xiaomi/Redmi10 and contemporary physical Android validation are **NOT RUN**. Actual motor behavior, sensor calibration, old firmware HTTPS trust, Xiaomi process retention, heat/battery drain, reboot restoration on this handset, and multi-hour screen-off continuity remain unverified. Use the [device checklist](compatibility.md#physical-validation-checklist).

Neither `START_STICKY` nor the ON-only partial wake lock guarantees uptime or bypasses Doze, Force stop, notification controls or OEM restrictions. The saved ON bit is an intention, not proof of live collection. Android's vibration API return remains `verification=unverified` without independent physical evidence.

## Deployed Note3 APK — emitted channels and recorded device history

Recorded freezes (user-gated stalls, all resolved; consumer-view evidence, not motor proof):

- Freeze #3 (~64 min), #4 (~6h36m; root cause: data-wiping reinstall 28s before onset), #5 (~4h01m; resolved by phone restart), #6 (~2h50m; crash `IllegalStateException Spool is closed` at `BleScan.loop`, recovered by app restart + tunnel repair), #7 (~20 min; mid-eval stall, one interrupted outcome, no replay issued).

Deployed software current state (durable contracts and their activation; per-generation shas, chains and per-run checks are in Git history, and current deployed bytes are in the activation record):

- The activation record `body/runtime-manifest.json` is verified against the deployed bytes and the owning unit's start time by `tools/runtime_manifest.py check` (exit 1 RED on a stale record or a process older than its bytes; exit 2 UNKNOWN when the record or a unit start cannot be read). The start time is the main process's `ExecMainStartTimestamp`, falling back to `ActiveEnterTimestamp` when a unit is active without a main process — a completed `Type=oneshot` clears `ActiveEnterTimestamp`, which read UNKNOWN until 2026-10-14 (see the completed-oneshot section below). The record was repaired 2026-10-14 after a stale `watch.py` fingerprint was found. Commit `162185c` (2026-10-15, health) fixed `runtime_manifest.py record` to compare the deployed bytes against the committed blob at HEAD (the rule `check` already used) instead of the working-tree copy — previously `record` returned RED whenever a peer had undeployed edits in the shared checkout, making a deploy of committed bytes unrecordable without declaring a false divergence.
- Activation-record scope widened 2026-10-15T15:16Z (health, wake 88416; DM 88550): `body/runtime-manifest.json` (rewritten 15:16:55Z, `source_commit` `43cd3b7`) now records **7** files, and `check` reports 5 unit starts — `clock_offset.py`, `node_state.py` and `device_state.py` joined the four earlier entries. Until this change `android-body-node-state.service` executed `/home/mesh-home/android-body/tools/node_state.py` and `…/tools/clock_offset.py` directly from the shared checkout — the unit's journal `_CMDLINE` shows the checkout paths for every tick through 15:17:21Z — so a working-tree edit to either became running code on the next 60 s tick with no copy-in, backup, record or `check` signal (the activation gap senses reported, DM 88396). The site unit file was rewritten 15:16:31Z to run `body/runtime/node_state.py` and `body/runtime/clock_offset.py`, the bytes were copied in 15:16:22Z, and the 15:17:34Z start was the first run from `body/runtime/` (both `status=0`; 14 unit runs Finished and none Failed through 15:26Z). The copies are byte-identical to their sources (`node_state.py` `0e8e872ac4f8c1e3…`, `clock_offset.py` `b7c840f7f06ca92d…`, `device_state.py` `df85442486748aa9…`); no `.pre-deploy` backup exists for these three because none had a prior `body/runtime` copy — the revert target is the committed source plus the previous `ExecStart` path.
- `watch.py` has carried, in order: the BLE evidence channel, Wi-Fi/BLE RF + node-status hysteresis, protocol-v2 clock fields (`phone_elapsed_ms` on every sensor event; pre-v2 spooled records render null with reasons, never interpolated), clock-skew bounds (`acquisition_span_stats`/`clock_agreement_reason`/`freshness_basis`), the per-session excursion log (bounded 128 lines/node; v2.1 retention fields live since 2026-10-11T19:54Z), the class-B delivery-gap detector (class-B stop detector renamed 2026-10-14; deployed and independently verified live 2026-10-12), the calibration-free accel guard, the bounded phone/host clock-offset reading (2026-10-14; `tools/clock_offset.py` → `body/clock-domain-note3.json` renders the resolved skew/latency split when the reading is fresh, the previous unresolved bound when it is absent/stale/invalid, and a phone wall-clock step alarm), the host-side node-state line (2026-10-14; a missing/stale/absent document renders `mode=UNKNOWN`, never `OFF`; the node-state `reasons` rendered bounded and sanitized to one printable line, so a foreign publisher's reason cannot forge view lines or break the strict utf-8 state write), the light-resumption detector below, and its `baseline` classification (2026-10-14; the detector's silence names its own cause instead of one sentence that fit only the fresh-but-lit case). Each earlier deployment exercised its backup/revert path and live activation under service restarts; the 2026-10-15T09:10 refresh is the exception recorded above — its `.pre-deploy` file duplicates the new bytes, so reverting it would need the git blob.
- `watch.py` collection-side scan-state row age and the node-level clock-domain contract (2026-10-15, senses; `experiments/perception/watch.py` sha256 `b7b08443cb593676`, commits `61ba8cd`, `a8ec5e3`, `e08be63`): the pane's collection-side `age=` is the spool-summary document's own age (one `android-body-spool-read.timer` cycle, validity 300 s), not the phone row's, so the `scan_state` segment now also carries `row_age=<n>s` — the row's age resolved into the host clock domain through the published offset — or `row_age=unknown(<reason>)` (`no-reference-time`, `no-row-epoch`, `clock-domain-unresolved`, `clock-domain-jump`, `clock-domain-invalid`, `row-epoch-in-future`); it exposes a stopped *sampler lane* (a row that stops being re-stamped keeps ageing, which the summary's own `age=` cannot show) but NOT a stopped scan loop — the sampler re-stamps the row every 5 s with `phase=none` while the loop is stopped, so the loop-stopped signal is `phase`, and `row_age` cannot resolve below the ~300 s spool-read cycle (2026-10-16 correction below). `space.json` → `nodes[i].clock_domain` is additive to `schema_version` 1 (core pins the version at `discovery.py:4220`): `version`, `status` (`ok|absent|invalid|stale`), `offset_nominal_s`, `offset_min_s`, `offset_max_s`, `observed_at_epoch_s`, `validity_seconds`, `samples`, `source`, `reason`, `jump`, values published uncoerced. Deployment: pre-deploy backup `watch.py.pre-deploy-20261015T1508Z` sha256 `a594b2d9d49a3b06…` is the deployed-but-unrecorded variant a peer consumer collided with (its writer is UNKNOWN; those bytes exist nowhere in the Git object DB and are preserved under the ignored site); deployed bytes `b7b08443cb593676` are byte-identical to the committed source at `e08be63`; `tools/runtime_manifest.py check` GREEN, RED on the unit-start line before the 15:09:34Z `android-body-perception.service` restart; revert path exercised (restoring the backup reproduced `a594b2d9…` and turned `check` RED, reapplying reproduced `b7b08443…`). Live 2026-10-15T15:19Z: `scan_state(windows=90 phase=gap last_error=none sightings=0 window_ms=60000 gap_ms=60000) row_age=275s` against a summary `age=272.6s`.
- Host-side attribution of the measured clock offset (2026-10-17, senses; commit `582f0e0`, `experiments/perception/watch.py` sha256 `d694f91b741cf3ed54fdf85cd1d56a1fbe0625af448a2a146d125bfcb7949cd3`): `tools/clock_offset.py` publishes the host's own `NTPSynchronized` verdict as `host_ntp_synchronized` and nothing read it (`grep -c ntp body/perception/view.txt` = 0 before the change; health DM 105987), so the pane's `measured phone/host offset +24.8s behind host` read as a phone defect while ~22 s of it was host error (host ~+22 s vs true UTC at 10:13Z, phone ~2.7 s). `read_clock_domain` now carries the field tri-state (`None` when the document is absent/invalid/stale, omits it, or gives a non-boolean) and `host_clock_attribution` renders it inside the measured-offset clause: `host_ntp_synchronized=false: the host clock is itself unsynchronized, so part of this offset is host error, not a measured phone error`; `true` renders as attributable to the phone; unknown renders as unknown, never as synchronized; the no-reading branch is untouched and carries no host clause. The clause travels with the same string `space.json`'s light `status_reason` carries (`clock_agreement_reason`), and the latency derivation is unchanged (`latency = span − offset` cancels the host error) — attribution only. Tests `test_read_clock_domain_carries_the_host_ntp_verdict`, `test_clock_agreement_names_the_host_side_of_the_measured_offset`, `test_the_pane_and_space_publish_the_host_ntp_attribution`; perception suite 229 tests OK, `tools` 326 OK. Independent review (reviewer agent, 2026-10-17) returned OK/correct with no findings, confirming the additive key does not leak into `space.json`'s `clock_domain` (selective copy) and no caller breaks. **Deployed** 2026-10-17T10:28:55Z by copy-in after hash-verifying pre-deploy backup `body/runtime/watch.py.pre-deploy-20261017T102855Z` (sha256 `0ecbfa5f5a3d8437e56bca38ffb2232f54bc6327cde52071660f1ba847f26657`); `android-body-perception.service` restarted 10:29:00Z (main PID 457899); `tools/runtime_manifest.py record --file watch.py` 10:29:04Z, `check` exit 0 GREEN (7 files, 6 unit starts, `source_commit` `582f0e0`). Live observation 10:29:17Z: `view.txt` (mtime 10:29:17Z, fresh) carries `measured phone/host offset +24.8s behind host (age 5s, n=3, bounds +24.3..+25.3s, host_ntp_synchronized=false: the host clock is itself unsynchronized, so part of this offset is host error, not a measured phone error)`. Revert = restore `watch.py.pre-deploy-20261017T102855Z` over `body/runtime/watch.py`, restart the unit, re-record. The host clock itself stays ~+22 s off true UTC (`timedatectl` `synchronized=no`, all UDP/123 queries time out) — routed to the operator (health wake 99258), not plant-fixable, and now named in the pane instead of being attributed to the phone.
- `tools/clock_offset.py` nominal offset inside its own interval (commit `43cd3b7`, 2026-10-15, senses): the document published `offset_max_s = min(sample upper bound)` with `offset_nominal_s = median(sample upper bounds)`, so the nominal was at or above the upper bound by construction and no reading could satisfy a consumer's `min <= nominal <= max` check. The nominal is now the midpoint of the tight interval (`tight_upper - quantization_s/2`); the interval and every conservative bound derived from it are unchanged, and `assert_bounded` refuses a `status=ok` document whose nominal is outside its own bounds. Live: `body/clock-domain-note3.json` nominal `24.903` inside `24.403..25.403` (samples 3, `validity_seconds` 3600); `space.json` carries the same; the pane renders `measured phone/host offset +24.9s behind host (age 19s, n=3, bounds +24.4..+25.4s)`. Earlier `+25.6/+25.7 s` figures were the median of one-sided upper bounds — an upper-side estimate, not the interval midpoint. `python3 -m unittest discover -s tools` 221 tests OK; `-s experiments/perception` 184 tests OK.
- `spool_read.py` deployed 2026-10-14 (commit `22571b0`; `android-body-spool-read.service`, 5-min timer): reads the Note3's durable spool and publishes a bounded summary (`body/spool-summary-<node>.json`) with spool bytes, retention window, per-kind row counts and light-bucket distribution — collection-side evidence of the spool's contents, not server-side receipt or phone execution. `watch.py` renders this summary when fresh, or absent/invalid/stale when missing or expired. The deployed generation carries the light-bucket classification fix (committed `bcb206a`; section at the end of this document); its current bytes, recorded `source` and unit start are in the activation record, and each superseded generation is preserved as a dated `.pre-deploy` backup (e.g. `spool_read.py.pre-deploy-20261015T2036Z`) or in Git history. A completed `Type=oneshot` is inactive between the 5-min runs.
- `tools/spool_read.py` landed as `60810bb`, refined by `786e834` (2026-10-15, senses; that revision's source sha256 `975022a0e29410823ad91995d974ac72e6681d0af95c9335f4a53b7a47474af1`, introduced by `786e834`, deployed 2026-10-15T08:21:27Z and superseded at 09:10:29Z by `9883710`'s bytes — see the spool_read bullet above): the retention window is extracted as `<10-digit> <token>` candidates whose trailing token is a spool row kind (`ALLOWED_KINDS` plus the `wifi_link_rssi_dbm` row token), because the spool is binary-framed (`ObservationSpool.writeRecord`: 8-byte id + 4-byte text length before the `<epoch> <kind> …` payload) and a bare `[0-9]\{10\}` also matched field values. A span above 30 days is reported as a failed read, not published. Device check with the fixed source (read-only `adb run-as` greps, 2026-10-15T07:27Z): 21,434 rows, oldest `1792028662`, newest `1792049261`, window 20,599 s (5.72 h); buckets dark=3082 faint=0 dim=984 sum to light=4066 (partition holds live). The same run's bare-10-digit extraction gave `0000646651`…`9999894006`, and the deployed copy published `newest_row_epoch_s=1994543295` with `retention_window_s=202,514,633` (56,254 h) — the fabricated value this change removes. The device's toybox BRE rejects GNU alternation (`grep -a -c '[0-9]\{10\} \(light\|battery\)'` returns 0 where `'[0-9]\{10\} light'` returns 4,093), so the kind filter runs in Python.
- Token-set correction (2026-10-15, after independent review of the same change): `ROW_KIND_TOKENS` is `ALLOWED_KINDS` plus the row tokens `wifi_link_rssi_dbm`, `owner`, `sensor` and `actuator`. `Sensors.capabilities` writes `owner battery off` / `sensor light absent` / `cap …` and `BodyService` writes `actuator vibration absent`; those are row epochs but not counted kinds, so excluding them would silently narrow the span (the earlier revision of this change did). The `owner_checkboxes` row's `battery`/`light`/`acceleration` keys are themselves row tokens, so the guard rests on the value shape — those keys carry only `on`/`off` — and the tests record that exposure instead of denying it. Device re-check after the change: 22,272 rows, oldest `1792028662`, newest `1792049314`, window 21,292 s (5.91 h); buckets dark=3082 faint=0 dim=1121 sum to light=4203. Source at HEAD carries these changes (`786e834` introduced them, an ancestor, not HEAD); that revision's bytes were deployed 2026-10-15T08:21:27Z and superseded at 09:10:29Z by `9883710`'s (`3fc08724…`), which was itself superseded at 09:59Z by `b96a2325…` and at 12:52Z by `eecfc3a0…` (see the deployed-consumer bullet above).
- Collection *loss* is now reported alongside liveness (commit `9883710`, 2026-10-15, senses; source `tools/spool_read.py` sha256 `3fc08724…` and `experiments/perception/watch.py` sha256 `cf56d515…`, **deployed** 2026-10-15T09:10:29Z, superseded at 09:59Z by `b96a2325…`/`2b527f4f…` and at 12:52Z by `eecfc3a0…`/`330da0d5…` — see the deployed-consumer bullet above). The spool summary carries `overflow: {"dropped": N, "notice_epoch_s": E}` read from the app's last `spool overflow dropped=N policy=oldest` notice (`ObservationSpool.overflowText`). The app's queue holds at most one notice — a new drop event removes the previous notice and appends a replacement with a fresh ID — and `trim()` never removes one (it skips notices and does not count them as dropped), while the spool file is append-only (`commit()`) and is only rewritten by a compaction when the appended log would exceed twice the byte bound. Superseded notice frames therefore stay readable in the file, and the Note3 spool held 1,451 notice rows for one cumulative count: the last match is the value, and counting or summing notices over-reports ~100x. A spool that has never evicted publishes a truthful `dropped=0` with a null epoch, and `assert_bounded` requires `(dropped > 0) == (notice_epoch_s is not None)`. The read separates "grep matched nothing" (device status 1: zero loss) from a broken channel by echoing the device-side status as a probe line and merging stderr, because on the Note3 a denied `run-as` and an unreadable path both exit 1 with only a diagnostic — stdout alone would have published a calm zero over a failed read (the host's adb returns 0 for a device-side `exit 7`, so the host return code carries nothing). `watch.py` renders `overflow=cumulative-dropped=N`, or `overflow=unknown` when the field is absent, because publisher and consumer are activated separately. Live acceptance with the changed source (read-only `adb run-as` greps, 2026-10-15T08:12Z): published `dropped=108820`, bounded by direct reads of 108815 (before) and 108826 (after); the same run published `window=23054s` (6.4 h) where the then-deployed bytes published `207932300s`. Deployed renders: `overflow=cumulative-dropped=114,266` at 2026-10-15T09:45Z against `body/spool-summary-note3.json` `dropped=114266 notice_epoch_s=1792057223`, and `overflow=cumulative-dropped=128,575` at 2026-10-15T13:14:13Z. Checks: 170 `tools` + 160 `perception` tests OK plus the whole fast-check set; independent review (OverflowReview) found no correctness defect, one stale test comment, corrected.
- Per-cycle quantitative BLE scan state (commit `e57c91b`, 2026-10-15, senses; app source `BleScan.java` sha256 `ac0aeadd…`, `BleScanEvents.java` `96c905a…`, `BodyService.java` `429b9d3…`; host source `tools/spool_read.py` `eecfc3a0…` and `experiments/perception/watch.py` `330da0d5…`): host bytes **deployed** 2026-10-15T12:52Z (senses) — `check` GREEN. APK rebuilt + installed 2026-10-15T10:07Z (genome wake 84882): `app-debug.apk` 121,328 bytes, SHA-256 `8f0d2fc2e5e11212bf30a96b1d2c901a4622d6455d5239b0238611a634af5922`, `adb install -r` Success on Note3 (superseded 2026-10-15T12:14:10Z by the exec-probe APK `c3dbdc3a…`; see the exec-probe activation record below). Spool verification at install: `ble_scan_state: 4` rows in `spool-summary-note3.json` (18,130 total rows); the producer is live and growing — the 2026-10-15T10:19:18Z summary reports `ble_scan_state: 63` of 18,594 rows (5.02 h window, fresh). These rows sit in the app-private collect-only spool: the delivered view still shows `scan_state unknown/no-observation` (no delivered record since 2026-10-14T06:13:24Z), while the deployed consumer's collection-side spool line now renders the per-cycle row, `scan_state(windows=29 phase=window last_error=none sightings=0)` at 2026-10-15T13:14:13Z. Body service running with new APK. Closes discover 83319: the retained spool could not distinguish "scan running, no beacon in range" from "scan loop never started/exited" (0 `ble_scan` rows in the 6.19 h retained window, last `ble_scan start` 40.2 h before it opened). The app now emits `ble_scan_state` rows with per-cycle scan state.
- Raw RF sample/receipt epochs on the BLE projections (commits `9968171`, `19975f8`, 2026-10-16, senses/genome; `experiments/perception/watch.py` sha256 `ac6242278de071e2`): `ble_sighting` and `ble_scan_state` snapshots publish `phone_sample_epoch_s`/`consumer_receipt_epoch_s` even when stale (measured values still drop on stale; the epochs stay raw facts), and the compact event line adds `sighting_phone_sample=<phone UTC>` only when a beacon observation exists. The core boundary reads cessation age from the raw phone-sample stamp, never a host-derived age (which would conflate phone/host clock skew). The 01:50Z draft landed with a `SyntaxError` (missing `+` before the caps f-string) and was repaired by genome, which also reverted the draft's `fullmatch`→`search` loosening and its extra `sequence` key to keep the change additive. Host bytes **deployed** 2026-10-16T02:21Z (health) from committed `19975f8`; `android-body-perception.service` restarted 02:21:33Z after the bytes, `runtime_manifest.py record` GREEN (checked 02:21:59Z); `check` GREEN, `health-check` GREEN, superseded bytes preserved as `watch.py.pre-deploy-20261016T0221Z`. Live observation is limited: the frozen Note3 delivery stream carries no sightings, so the new fields are not yet rendered; the deployed bytes were exercised directly (fresh/stale/absent sighting, fresh/absent scan_state) and 3 new regression tests cover the behavior (207 perception tests OK).
- Events-pane receipt provenance (commit `8f49306`, 2026-10-16, senses; `experiments/perception/watch.py` sha256 `8cc38f45a46d43ed`): the events pane printed the last action receipt as a bare raw line, so a days-old exec receipt (collect-only, no fresh delivery) sat after fresh event lines with no date and read as current. `render_events` now renders it through the existing `describe()` helper, so the receipt line carries `#<sequence>`, `phone_sample/event=`, `consumer_receipt=` and `delayed_at_receipt=` like the sensor lines. **Deployed** 2026-10-16T08:10:14Z (genome, on the author's request): pre-deploy backup `watch.py.pre-deploy-20261016T081006Z` sha256 `3f49496d…` hash-verified before the copy-in; `android-body-perception.service` restarted 08:10:20Z after the bytes were written; `tools/runtime_manifest.py check` GREEN (7 files, 6 unit starts, `source_commit` `8f49306`; superseded record preserved at `runtime-manifest.json.pre-record-20261016T081014Z`); live `body/perception/events.txt` (written by the restarted process, MainPID 101432) renders `receipt: #217659 … | phone_sample/event=… consumer_receipt=… delayed_at_receipt=…`. Revert = restore the backup + restart the unit. No device, transport, actuator, APK or Android-source change.
- First v2.1 retention-set excursion line EMITTED and genome-verified 2026-10-14T19:54:25Z (health DM 79641): session `ca09f8f0`, cursor 138764-138795, light_std=0.006 light_oscillation=none accel_std=0.048 rssi_std=0.0 light_transient=none freeze_overlap=false, full retention set, acquisition_span ~24.1s; trigger was the 19:54:02Z Note3 app restart. Session boundary blocker resolved; ready for v2.2 scoring (per-window labels + UNKNOWN fraction).
- The view's clock note is the computed bounded reason (commit `ee7fd7a`); a hardcoded "UTC-aligned <0.2s" string was removed as a fabricated device pass, with regression test `test_view_clock_note_is_computed_not_hardcoded` keeping it computed.
- `BoundedEvaluator.readBoundedBytes()` streams 1 KiB chunks capped at `maxBytes` (commit `b82dab0`), replacing API26+ `Files.readAllBytes` on the bounded path.
- BLE scanning on Note3 has produced no code=2 since `efc78fd` (attributed by correlation, onset mechanism open — see the code=2 entry above); `onScanFailed` sets `stopped=true` (`b163324`) so a scan failure exits the loop within ~1s instead of sleeping 60s and retrying indefinitely — the next-failure exit remains a prediction until observed.
- Bounded host snapshot lifecycle (per-node publication repair, byte-switch under lock, revert/reapply) was exercised with independent witness acceptance on 2026-10-07; the publication repair has been live since.
- Isolated `:ble-probe` diagnostic (2026-10-07): JVM report formatting and Android compile/package/lint/signature verified; no APK installation or device BLE result.
- Host reboot 2026-10-14 (~15h downtime): all 16 `android-body*` units auto-restarted with no failures; the durable spool preserved every phone-generated record and the backlog drained completely on reconnect — zero data loss; installed APK re-confirmed `a5cc750e`.
- Host reboot 2026-10-15T10:55Z: every `android-body*` unit auto-restarted; `tools/runtime_manifest.py check` GREEN (4 files, 3 unit starts then; the record now covers 7 files and 5 unit starts — see the activation-record bullet above). The first scheduled spool-read publication (10:55:53Z) was UNKNOWN (`spool-dir-listing-failed`: adb server not yet accepting) because `After=/Wants=android-body-usb.service` orders unit start, not adb readiness (the USB bridge logged transport present at 10:56:03Z); the 11:00:47Z tick published normally. A post-boot spool UNKNOWN is therefore expected until the transport is ready, not a spool fault.
- Closed since (health wake 85145): `body/usb_bridge.py` now starts both publications at the transport readiness transition, so the post-boot spool UNKNOWN window is no longer expected; see the transport-keeper section at the end of this document.

## Bounded probe runner

`experiments/minimal-substrate/probe.py` is canonical in the shared checkout with `test_probe.py` and its README: a fixed allowlist of read-only `adb shell` probes (`dumpsys package org.androidbody`, `dumpsys sensorservice`, `date -u`) — no arbitrary command execution, device mutation, radio/camera/mic/location or persistent state. Bounds: per-command timeout with child kill (default 10s), per-line 1,024-byte and per-probe 64 KiB output caps, artifact retention (newest 20). Interrupted outcomes are recorded truthfully; nothing is retried or hidden.

Extended 2026-10-11 with execution-context labels (`host`/`run-as`/`apk-uid`), expected-denial semantics with stderr retained, a SIGINT interrupt probe with truthful receipt, a device-side persisted scratch write/run1/run2/delete/verify sequence with source+SHA-256+provenance, an `apk-identity` capture, and an `apk-dex` host-side installed-byte correlation (explicitly not execution evidence). 24 unit tests pass.

Executed on Note3 2026-10-12 (~08:18–08:28Z): 10 of 11 expected probes ok; `scratch-rerun` failed on adb argv rejoining (harness quoting, not device denial — a single-invocation control succeeded), and `adb shell` exit codes proved unreliable on this device (`adb shell false` → rc=0), so device-side rc must be captured explicitly. A 2026-10-11 identity probe (`dumpsys package`) reported `userId=10224 gids=[3002, 3003]`, `versionCode=2 targetSdk=36`, `versionName=0.2.0`; later probes show uid 10225 with supplementary groups including 3001, consistent with the deployed `BLUETOOTH_ADMIN` permission. run-as app uid 10225 (`untrusted_app`) is functional for id/status/selinux reads and in-context script exec; `run-as` exit0-with-failure ("corrupt installation") is detected and never recorded as success.

Device liveness probes on the Note3 are themselves a hazard: `/system/bin/ps` is a toolbox binary (no toybox), so `ps -A` and `ps -e` print the header row only and exit 0 (61 B) — indistinguishable from "no process", and the source of a false "app process dead" record on 2026-10-14. Probe process liveness with bare `ps` or `ps -x`, or the service with `dumpsys activity services org.androidbody`; `pidof`, `head`, `tail` and `cut` do not exist on the device, so filters run host-side. Header-only output means UNKNOWN, not absent.

## Reproduce the host checks

The same set as the [README Checks block](../README.md#checks-and-truthful-scope), plus the APK signature step:

```sh
# The system default java is JDK 8 without javac; export a JDK 17+ install first:
#   export JAVA_HOME=/home/mesh-home/.local/jdk21
#   export ANDROID_HOME=/home/mesh-home/.local/android-sdk
tools/test-protocol.sh
tools/test-spool.sh
tools/test-ble-probe.sh
python3 -m unittest discover -s rendezvous/minimal-server
python3 -m unittest discover -s experiments/light-vibrate
python3 -m unittest discover -s experiments/perception
python3 -m unittest discover -s experiments/minimal-substrate
python3 -m unittest discover -s experiments/trial-eval
python3 -m unittest discover -s tools
python3 tools/check_docs.py
python3 tools/check_ci_coverage.py
./gradlew --no-daemon :app:assembleDebug :app:lintDebug :app:testProtocol :app:testSpool :app:testRestore :app:testBleScanEvents :app:testEvalOutcome :app:testExecProbe :app:testBoundedExec
python3 tools/check_published_apk.py
"$ANDROID_HOME/build-tools/35.0.0/apksigner" verify --verbose \
  app/build/outputs/apk/debug/app-debug.apk
```

Install dependencies from official vendors, accept the SDK agreement, and keep generated signing keys outside version control. The Gradle distribution checksum is pinned. Recheck APK size/hash after source/resource changes; independently signed/debug-built artifacts can have different bytes and upgrade identities.

## Eval outcome line bound — fixed on main (`e5615d5`); device trigger unverified — 2026-10-14T10:32Z

- Trigger: discover DM 74716 + genome DM 74745/74746 — eval outcome lines can exceed the observation spool's per-line bound and disarm the session.
- Confirmed by two independent host-JVM probes (real shipped `Protocol`/`BoundedEvaluator`/`ObservationSpool` classes): eval caps command output at 1024 B, but the spool accepts observation lines only up to 1007 B. Measured: `read /proc/meminfo` 1143 B, `/proc/self/status` 1089 B, `env` 1068 B REJECTED (`Invalid observation line length`); `identity` 180 B / `clock` 124 B accepted. The rejection throws `IllegalArgumentException` inside `BodyService.enqueue`; `network()` does not catch it, so `fail()` disarms ON.
- Second reachable overflow (genome): `read_denied path=<client path>` echoed the whole client path (`BodyService.java:402-404`); any path > 956 B overflowed the 1024 B wire cap. Reproduced 1000 B -> 1051 B rejected.
- Clamp must be UTF-8-byte-based (genome): `encodeLine` enforces a byte limit and `read` decodes US-ASCII, so bytes >= 0x80 become U+FFFD (3 B each); reproduced 400 U+FFFD chars = 1200 B rejected.
- Disposition: accepted into the milestone-5 gate base as a documented hazard + contract correction, NOT a gate blocker (research-methods). The pre-registered two-branch gate constraint (widened 2026-10-14T08:52Z, wake 74790) — in a label-carrying session, neither (a) any eval verb whose output can reach 1024 B (`read /proc/meminfo`, `read /proc/self/status`, `env`) nor (b) any `eval read <path>` not in the shipped allowlist with UTF-8 byte length > 900 — is retired by the landed fix below.
- Fix landed: `e5615d5` (2026-10-14T10:31Z), exact-SHA [run 38550142907](https://github.com/genaforvena/android-body/actions/runs/38550142907) success. New pure-Java `app/src/main/java/org/androidbody/EvalOutcome.java` (Android-free, same precedent as `BleScanEvents`) builds each eval outcome, and `BodyService.executeEval` dispatches to it. Every result line is clamped to `ObservationSpool.MAX_LINE_BYTES` (1007 UTF-8 bytes) with the `Protocol.event` epoch prefix inside the budget, the LF appended last and the clamp stepping whole code points, so an outcome is exactly two spool lines the spool accepts and a clamped outcome reports `truncated=true`. `protocol/README.md` now states the 1,007-byte outcome-line bound. Landed before the 18:00Z gate deliberately: the change is source-only (no Note3 install), so it cannot affect the device-evidence-scoped milestone-5 gate (genome DM 75569).
- Host test: `app/src/test/java/org/androidbody/EvalOutcomeTest.java` (29 assertions) drives the real `ObservationSpool.enqueue`: large ASCII output, U+FFFD-heavy output (byte not char clamp), short output (no over-clamping), long denied path, 500-codepoint astral path; wired into `tools/test-protocol.sh` and new `:app:testEvalOutcome`. Re-run here 2026-10-14: `tools/test-protocol.sh` rc=0 (`Protocol: 81`, `BoundedEvaluatorTest: 72 tests`, `BleScanEvents: 12 assertions`, `EvalOutcome: 29 assertions`), and `./gradlew --no-daemon :app:testProtocol :app:testEvalOutcome :app:testSpool` BUILD SUCCESSFUL.
- Installed on Note3 2026-10-14T18:47Z (genome wake 80475): the clamp APK `a8f27d947cb45ac7853f1e93201619e01b8101c254596905dcaa933994f1ced1` (v1+v2 signed, cert `d23dcc9d`) was `adb install -r` activated and verified by health (pull+sha256 match, 19:30Z). The eval-line disarm hazard is closed on the running app: every eval outcome line is clamped to the 1007-byte budget, so an oversized read can no longer disarm a sending session. On-device clamp *observation* (an oversized read producing `truncated=true`) remains UNKNOWN until delivery mode. The phone producer is silent: measured `device-state note3: ON_COLLECT_ONLY desired_on=true collect_only=true process=present service=foreground` 2026-10-14 and consumer cursor frozen since 06:13:24Z — a collect-only delivery gap, not OFF.
- Scope: docs record only. No source/APK/device/transport/actuator/cursor mutation.

## Write receipt over the spool line bound — closed in the published build (`b6eaf1f`) — 2026-10-16T15:49Z

- Trigger: docs review of the shipped `write`/`exec` contract after the published download was rebuilt from `8dbb324` (genome DM 100879); the 2026-10-14 clamp covered eval output, not the echoed command.
- Measured host-side against the shipped classes (`EvalOutcome`, `BoundedEvaluator`, `ObservationSpool` at `8dbb324`, JDK 17, `/tmp` files dir, no device): `eval write big.txt <n×'a'>` succeeds and the file is written, but the succeeded line grows with the echoed `command=`. n=894 → 1,007-byte line, spool `enqueue` OK; n=895 → 1,008 bytes → `IllegalArgumentException: Invalid observation line length`. A 900-byte write also reports `truncated=true` with an empty `output=`, i.e. the clamp bounds the output field, not the command.
- Consequence in the shipped code: `BodyService.network()` catches only `IOException`/`IllegalStateException` around `enqueue`, so the unchecked exception reaches `runSession`'s `IOException | RuntimeException` handler and `fail()` disarms ON with a visible storage error. The action cursor was already persisted, so the next session reports `action <id> unknown reason=interrupted verification=unverified` although the file was written.
- Fix: senses' `EvalOutcome` clamp (`697d68a`, 2026-10-16T15:47:41Z) bounds the `command=` value first (`fit(...)`), which removes the overflow and marks `truncated=true`. Re-measured host-side at `697d68a`: a 900-byte write now yields a 1,007-byte line that `enqueue` accepts. The download republished then carried it: `b6eaf1f` (73,358 B, SHA-256 `87b36024…`, clean build of `e0ea84d`), `tools/check_published_apk.py` GREEN, exact-SHA [run 38929314768](https://github.com/genaforvena/android-body/actions/runs/38929314768) success; the previous download `3b6dcf7a…` (source `8dbb324`) was the one that lacked it.
- Other shapes observed on the same host run: `exec missing.sh` → `succeeded … output=uid=<uid> exec cmd=missing.sh unavailable reason=IOException Cannot run program "…": error=2, No such file or directory`; a 0700 script exiting 3 → `… output=hi exit=3`; a target backgrounding a child and sleeping → `timeout reason=no-exit destroyed=true`; path escapes → `exec|write|read path not in allowlist: …` (verb-specific denials, `7d0ee1e`).
- Scope: docs record and host-JVM measurement only. No source, APK, device, transport, cursor or actuator action.

## Light-cycle resumption monitor and detector

- Rule: `RESUME_LUX_MIN = 7.0` lux (`floor(log2(1+lux)) >= 3`, the consumer's own coarse-bucket boundary); predicate `lux >= RESUME_LUX_MIN and prev_lux is not None and prev_lux < RESUME_LUX_MIN`; log records carry `threshold_lux` and `prev_observed_unix`. The earlier 0.5-lux threshold sat inside the Note3's dim oscillation band (0.0 <-> ~1.24–1.35 lux; 751 unique bucket-transition rows with both endpoints <5 lux, 2026-10-07..13) and fired on routine dim oscillation; the entries the old rule fired on (lux 1.3224/1.2758 with prev 0.0) no longer fire.
- Known limitation: a genuinely dim (2–6 lux) resumption is not claimed — indistinguishable from the dim band at one poll. A resumption observed across a phone-silence gap is claimed, with the gap visible in `prev_observed_unix` (transition bounded by the gap, not measured inside it).
- Liveness: the monitor publishes an atomic heartbeat (`artifacts/light-cycle-monitor-state.json`); `watch.py` renders a `Light-cycle resumption detector` section — the full view reports status, heartbeat age, the heartbeat fields, a derived `baseline` classification and the last retained row verbatim; the compact view (cached to `events.txt`) reports status, armed state, the `baseline` token and last row without the per-second age. `baseline` names why no resumption is claimable (`no-fresh-reading`, `first-fresh-poll`, `sub-threshold`, `at-or-above-threshold`, `baseline-without-current-reading`, `unknown`) because the heartbeat's `armed` is only "a fresh baseline exists this run" — it does not say the baseline is below the threshold, nor that the current poll read anything fresh. A stale/absent heartbeat renders `stale/detector-silent` or `unknown/no-monitor-heartbeat` — never calm. Live 2026-10-14 11:36Z: `armed=False baseline=no-fresh-reading` (Note3 ON + collect-only, no fresh light reading since 06:13:52Z).
- Unit `Restart=on-failure` -> `Restart=always` so a fired monitor (rc=0) re-arms instead of silently stopping.
- Deterministic exercise of the deployed bytes (9/9 scenarios PASS, synthetic space.json): dim->lit row; dim oscillation no row; silence->lit with no prior dim baseline no row; ramp 2.5->6.68->7.05 row at prev_lux 6.68. Live detection+routing exercised: stop -> pane `stale/detector-silent`; `kill -9` -> `Restart=always` re-armed with fresh heartbeat and new pid.
- Follow-up `57ec309` (independent review of `ad5895e`): `_last_monitor_row` no longer returns None on a partial final line, so a crash mid-append cannot hide complete rows; the compact view dropped its per-second `heartbeat_age`. 115 tests OK.
- Deployed bytes: `body/runtime/light_cycle_monitor.py` sha256 `ca57c7c1346ec5c02a120281336b0e375e14b43abcd34d726d573fa1eb86e94b` (measured 2026-10-14 11:38Z; differs from source only by the documented `SPACE_JSON` path line and deploy note); service running with `--interval 30 --max-polls 3300` (past the 18:00Z gate); revert = `light_cycle_monitor.py.pre-deploy3-20261014-0852Z` + restart — the immediate predecessor (`eff74d6` content, sha256 `96abef81fbe0571b6902c28e898789a8464c275ff51c180c9d9ca2ec9371e3bb`, byte-identical to `…pre-deploy2-20261014-0803Z`; matched to `eff74d6` by diff: deploy note and `SPACE_JSON` path differ only). Corrected 2026-10-14: the line previously named `…pre-deploy-20261014-0749Z`, the `d7a8847` deploy two deploys back.
- Current deployed bytes (2026-10-16T04:44:28Z restart): sha256 `1a0c5792c7d290ae` — byte-identical to source `13bc2c8`; the hand-adjusted `default_site` divergence is retired (`body/runtime-manifest.json` re-recorded 2026-10-16T04:45:12Z with `divergence: null`; the superseded hand-adjusted copy is `light_cycle_monitor.py.pre-deploy-20261016T044405Z`, sha256 `ae6370c85c6a0226`). The field-rename section below records why that adjustment existed.
- Retained log carries one superseded-rule row (lux 2.505, prev_lux null, no threshold_lux, 2026-10-13T07:12Z), preserved as historical evidence and labelled in the pane as predating the 7.0-lux rule; inadmissible under every check of research-methods' pre-registered milestone-5 rule. Zero admissible resumption rows on record.
- Unknown: no live resumption has ever fired on the note3 single-sample rule (Note3 in a durably enabled ON + collect-only session; no uploads, so the consumer cursor has been frozen since 06:13:24Z — the by-design collect-only freeze of the delivered stream (`tools/spool_read.py:5-9`), not an OFF or sensor fault; confirmed `device-state note3: ON_COLLECT_ONLY` 2026-10-14T10:27Z, health wake 75405); the note3 heartbeat/armed path is exercised only on synthetic input and a dead-monitor drill.
- Evidence: `.mishe-tauftauf/artifacts/senses-wake74767-light-detector-controlled-exercise/`.
- Live dark-dwell rows now exist on redmi10 (docs 2026-10-20T14:05Z). The monitor was re-bound to the redmi10 channel (health wake 93212, deployed from `c164778`; `DEFAULT_NODE = "redmi10"`), so the note3-bound claim above no longer describes the running detector. Its retained log `body/runtime/artifacts/light-cycle-resumed.jsonl` holds 59 rows at that read — 58 `dark-dwell` (first 2026-10-16T02:01:31Z) plus the one superseded 7.0-lux row — of which 12 were appended 2026-10-20T13:20:35Z–13:54:05Z; the first six landed in a single poll as the monitor read the backlog batch the stalled phone upload delivered at 13:20:35Z. Whether those rows satisfy research-methods' pre-registered milestone-5 rule is not restated here.
- Pane rendering defect (docs 2026-10-20T14:05Z): `_last_monitor_row` reads only a bounded `MONITOR_LOG_TAIL_BYTES = 4096`-byte tail, and the newest detector row line is 4,690 B (a long `baseline_samples` array from the backlog's long dark dwell), so the pane reports `last_row=none (no resumption claimed in the retained detector log)` while the retained log holds the row. The helper's own docstring says a partial line is skipped "so an earlier complete row is still read"; with a row larger than the tail window no earlier row is in the chunk. Reported to senses.
- Redmi10 dark-dwell monitor restart limitation evidenced (senses wake 103211, 2026-10-16): whole-log recomputation over 24,604 light rows (imports the deployed module's own `ResumptionDetector`) reproduces all 39 post-freeze fires ordered-list-equal, 0 missed, 0 false positives; the named restart-skip limitation (research-methods DM 103054) manifested once as a truncated baseline — fired row seq=52651 records 269 of the true 628 dark samples after a run boundary mid-dark-run (design: "a restart clears the baseline"); the fire itself was not missed. No source change; whole-log recomputation remains the durable cross-check. Evidence: `.mishe-tauftauf/artifacts/senses-wake103211-light-cycle-restart-baseline-truncation.md`.

## Write-attribution journal (rendezvous server)

- Delivered 2026-10-14 (health wake 78578, discover DM 78434 ask 1): every accepted POST appends one JSON line to `<data-dir>/writes.jsonl` — `ts` (ISO 8601 UTC), authenticated `node`, queue `kind`, client `remote_addr`, request `byte_count`, `records`. No payload bytes, no tokens; `log_message` stays a no-op. Rejected writes (401/400) and GET reads are not recorded. A journal write failure never fails an accepted POST (the queue stays the system of record); the journal then stops recording until restart.
- Commits: `ea8d290` (source + 3 tests), `c1fcc37` (README "Write attribution" section). Deployed `body/runtime/server.py`: sha256 `282beb5ce3b346c8` from 2026-10-14 (backup `server.py.pre-deploy-20261014-1409Z`; `android-body-rendezvous.service` restarted after the bytes were written), redeployed 2026-10-15T07:40:49Z to sha256 `c95bddbfacf785d1942b1083b8809f338d51e3fb1c6e70cbc557d1a9e087eeb6` (commit `ec3889f`, stale data-dir lock recovery; unit started 07:41:46Z after the bytes). `tools/runtime_manifest.py check` GREEN `deployed == source` (2026-10-15T07:47Z).
- Live exercise (throwaway second instance, port 8799, temp data-dir, dummy secret): unauthenticated POST → 401, no journal line; authenticated GET → 200, no journal line; authenticated POST of a 24-byte body → 201 with one journal line (`node=note3 kind=observations remote_addr=127.0.0.1 byte_count=24 records=1`, ts 2026-10-14T14:13:11Z). Instance killed, temp removed, port verified free. Unit tests: 21 OK (accepted post recorded with byte_count == len(body); rejected writes/reads not recorded; journal failure does not fail POST). Protocol unchanged.
- Production state: `body/queues/writes.jsonl` exists (0600), 0 bytes — the Note3 producer has not posted since 2026-10-14T08:58:03Z (the milestone-5 delivery stall, sense-side ownership); the first live phone line will carry writer attribution for any future queue writer.
- Evidence: `.mishe-tauftauf/artifacts/health-wake78578-write-journal-deployment.md`.

## Operator dashboard renderer crash loop — diagnosis + tripwire (health wake 80473, 2026-10-14)

- Trigger: operator-view DMs 80447–80465 — ~10 "operator dashboard restored in android-body:operator" restores ~18:29–18:44Z, alternating `pane-stopped-or-dead` and `publication: dashboard stale or future`.
- Cause: every `pain watch *` renderer pane crash-looped 2026-10-13T11:00:09Z → 2026-10-14T18:43:35Z (~31.7 h) on `ModuleNotFoundError: No module named 'wcwidth'` (`viewport.py:7`, imported at `cli.py:338` of pinned release 676264a78852). `wcwidth` vanished from the renderer Python env at 2026-10-13 11:00:08Z; removal cause UNKNOWN (no pip/shell/seed log evidence on this node). Each respawn died at import; operator-view restored the operator pane every ~1–2 min (observed crash gaps ≤48 s; 248 tracebacks in `logs/pain-watch-operator.stderr` alone; all 9 role panes affected).
- Blind spot closed: `tools/health-check.sh` §2 checks passed throughout (pane presence + `pane_dead` are both clean between restores). Added §2b renderer-crash tripwire: any `logs/pain-watch-*.stderr` written in the last 2 min → RED (healthy loops are stderr-silent; 2 min > observed 48 s loop cadence, < 120 s restore window). Verified GREEN after fix: `no renderer crash in last 2 min`.
- Resolution: `wcwidth 0.9.2` installed to user site-packages 2026-10-14T18:43:35Z (installer UNKNOWN — no chat/seed record). Post-fix: all 9 stderr logs frozen 18:42:57–18:43:35Z, no growth 4+ min after; all 9 panes alive; operator pane PID 1388829 up since 18:43:51Z rendering; `import wcwidth` OK in the renderer env.
- Loaded consumer (operator-view ask): healthy throughout — perception service active, deployed `watch.py` == source (a100b3e8f075ed74), `view.txt` fresh (18:45:14Z), note3 ON_COLLECT_ONLY marker matches cursor, transport reachable. Only the renderer was broken.
- Checks 2026-10-14 ~18:48Z: `tools/health-check.sh` HEALTH: GREEN (exit 0, incl. §2b); `runtime_manifest.py check` GREEN (2 pre-existing UNKNOWNs unchanged); `bin/health-wall-check` GREEN; `bin/health-evidence-check` GREEN outcomes=536; `bin/health-dm-check` RED live_refires=3 to health (the reconciled operator-view DMs); `bin/docs-wall-check` RED wall_wake=80006 vs latest_yield=80463 (docs-owned, DM routed).
- Open: wcwidth removal cause UNKNOWN; installer identity UNKNOWN; tripwire bounds recurrence detection to ≤2 min.
- Evidence: `.mishe-tauftauf/artifacts/health-wake80473-operator-pane-crashloop.md`.

## Runtime activation record — completed-oneshot start time (health wake 81416, 2026-10-14)

- Trigger: `tools/health-check.sh` §7c printed `UNKNOWN runtime activation record` with `UNKNOWN spool_read.py: android-body-spool-read.service start time unavailable, cannot prove the process runs the recorded bytes` — a standing UNKNOWN since the frozen `spool_read.py` deploy recorded its owning unit (wake 81291), not a byte drift.
- Cause (reproduced deterministically): `unit_entered()` read only `ActiveEnterTimestamp`, which systemd clears when a `Type=oneshot` invocation finishes. Live host read of `android-body-spool-read.service`: `ActiveEnterTimestamp=` (empty), `ExecMainStartTimestamp=Wed 2026-10-14 19:58:34 UTC`, `ExecMainExitTimestamp=Wed 2026-10-14 19:58:38 UTC`, `SubState=dead`. The running `Type=simple` units (`android-body-rendezvous`, `android-body-perception`) report both properties identical, so their rows are unchanged.
- Fix: `unit_entered()` queries `ExecMainStartTimestamp` first — the last main process's exec time, kept after a oneshot finishes and moved by a restart, so it is tighter than the unit's active period — and falls back to `ActiveEnterTimestamp` for a unit that is active without a main process. Both empty or unparseable stays UNKNOWN, never a pass. Module docstring and comment updated.
- Tests: `tools/test_runtime_manifest.py` +5 (`cd tools && python3 -m unittest test_runtime_manifest`: 35 tests OK). Three of the five fail against the pre-change file (verified by restoring it temporarily), so they discriminate rather than pin wording.
- Live observation: `python3 tools/runtime_manifest.py check` exit 0 with `spool_read.py: android-body-spool-read.service started Wed 2026-10-14 19:58:34 UTC, after the deployed bytes were written Wed 2026-10-14 19:48:16 UTC`; `tools/health-check.sh` HEALTH: GREEN with `runtime activation record matches deployed bytes` (previously UNKNOWN).
- Scope: detector/recorder source only. No APK, device, transport, actuator, cursor or deployed-runtime-bytes change; `body/runtime-manifest.json` is unchanged.
- Evidence: `.mishe-tauftauf/artifacts/health-wake81416-runtime-manifest-oneshot-diff.txt`.

## Rendezvous stale-lock brick + recovery hardening (health wake 81674, 2026-10-15)

- Trigger: `android-body-rendezvous.service` RED (activating/auto-restart) on the dashboard; journal shows repeated `[Errno 13] Permission denied: '.../body/queues/.lock'` with argparse exit 2.
- Cause (evidence): `body/queues/.lock` created 2026-10-14T14:13:59Z root:root 0600 (ctime==mtime; consistent with a root smoke test of the lock-opening server.py deployed 14:09:20Z; creator not directly evidenced). The unit ran pre-lock code until host boot 2026-10-15T06:01Z; every restart then failed on EACCES (restart counter 793 by 07:10:04Z ≈ 66 min ≈ boot). Host clean poweroff 07:16:51Z; back 07:17:37Z on kernel 6.8.0-147 (unattended upgrade installed 147 at 06:23Z; reboot actor UNKNOWN), after which the loop continued.
- Repair: unlinked the stale lock (queues dir mesh-home-owned drwx------, no sudo needed), `systemctl --user reset-failed` + start; lock recreated mesh-home-owned; note3 transport serving (cursor 265956, spool rows 20,723→21,080 growing); NRestarts=0; port 8765 listening.
- Fix (source, commit ec3889f): `Store._open_lock` — on EACCES opening `.lock`, if the data directory is writable by the service uid, unlink the stale lock and retry once; a read-only directory still fails closed; flock still rejects a second live server; O_NOFOLLOW retained. Named tradeoff: a live server of another uid holding the old inode is not visible to our per-inode flock after recovery; the pre-fix behavior was a permanent brick.
- Tests: `tools/test_server_lock.py` — 3 deterministic boundary tests (recovery when dir writable; fails closed when dir mode 0500; normal start unaffected). Full local run: tools 153 OK, rendezvous/minimal-server 21 OK, test-protocol.sh 72+12+29 passed. Unit restarted 07:41:46Z onto the new bytes; `body/runtime-manifest.json` server.py sha256 c95bdd recorded; deployed == committed source.
- Also observed: operator missing-window DM 82779 cause = host reboot (NOT the pytest default-socket vector; per-site socket fix holds) — consumer pane live with lower pane preserved; seed tick 82778 "session is not owned" transient post-boot, self-recovered. Pre-existing truthful REDs left standing: spool_read.py + watch.py frozen-deploy drift after senses commits b399824/786e834, routed to genome.
- Evidence: this section; `.mishe-tauftauf/walls/health.md`; `tools/health-check.sh` output.

## Note3 transport keeper — readiness and lost-mapping detection (health wake 85145, 2026-10-15)

- Trigger: host reboot 2026-10-15T10:55:47Z; the first scheduled spool-read publication (10:55:53Z) reported `unavailable (spool-dir-listing-failed: adb shell rc=1: * daemon not running; starting now at tcp:5037 / ADB server didn't ACK)` while `android-body-usb.service` configured its reverse mapping at 10:55:58Z. The next 5-minute tick (11:00:47Z) cleared it.
- Cause (reproduced): the publication timers use `OnBootSec=30s`, which had already elapsed when the user manager started on this boot, so the timer fired at user-manager start concurrently with `android-body-usb.service`. `After=`/`Wants=` order unit start, not adb-server readiness — the keeper starts the adb server and configures the mapping ~11s later. At the 07:17Z boot the same units succeeded because the timer fired after readiness.
- Second defect, found while exercising the fix: `adb kill-server` (a replaced adb server) drops the reverse mapping, while `transport_id` restarts at 1, so the keeper's generation check reported `GREEN Note3 USB transport present` over a dead tunnel. `tools/health-check.sh` §3's loopback probe also stayed GREEN, because a host-side request to 127.0.0.1:8765 never traverses the tunnel. Device-side truth: `/proc/net/tcp` on the Note3 shows `0100007F:223D` (127.0.0.1:8765) exactly when the mapping exists.
- Fix (`body/usb_bridge.py`, a site file, not a frozen `body/runtime` byte): (1) observe mapping presence on the device socket table — `adb reverse --list` stays forbidden — and re-issue `adb reverse` when it is absent, so a replaced adb server is repaired rather than reported GREEN; (2) start `android-body-node-state.service` and `android-body-spool-read.service` at the readiness transition, which removes the boot race and also refreshes both channels after a reconnect; (3) the kick is non-fatal and always printed, so a failed kick stays visible.
- Fix (`tools/health-check.sh` §3): keep the loopback probe but label it as what it proves, and add a device-side `adb reverse` check — `present` passes, `absent` while the Note3 is attached fails, `absent` with no device is UNKNOWN. A 6s retry avoids flapping against the keeper's 5s poll.
- Verification: the keeper was restarted three times (11:08Z, 11:12Z, 11:13Z); each shows exactly one `GREEN Note3 USB mapping configured` → `GREEN dependent publications started` → `GREEN Note3 USB transport present`, with no reconfigure spin in steady state. `adb reconnect` (11:13:18Z) reconfigured the mapping without a redundant kick; `adb kill-server` (11:12:13Z) was detected within one poll and repaired. Controlled failure through the new check: with `android-body-usb.service` stopped, health-check printed `GREEN rendezvous answers the phone's loopback URL (404 unknown_route)` and `RED adb reverse mapping absent while note3 is attached (tunnel dead)` (HEALTH: RED, exit 1); after the keeper restarted, HEALTH: GREEN with `adb reverse in place (device listens on 8765)`.
- Revert: `body/usb_bridge.py.pre-kick-20261015T1112Z` (sha256 `d5086f5195ba78e3c43575f3c4e3e0c26f87cf0909d58088fd1870741e1de61b`) plus `systemctl --user restart android-body-usb.service`.
- Scope: host-side transport keeper and host check only. No APK, device write, cursor, queue, actuator, radio or frozen `body/runtime` byte changed.
- Evidence: `.mishe-tauftauf/artifacts/health-wake85145-transport-keeper.md`.

## Minimal-substrate exec probe — activation record (genome wake 85882, 2026-10-15)

- Change: `ExecProbe.java` (commit `a1eed4d`, discover) adds a session-start bounded process-creation probe to the installed APK. It writes a 6-byte app-private `probe.txt`, runs the fixed platform binary `/system/bin/cat` on it under the app UID, merges stdout+stderr (≤4096 B), bounds the run at 5 s with the child destroyed on timeout, and emits one `probe exec uid=… cmd=… output=… exit=…` spool line. `waitForExit` polls `exitValue()` (API-1-safe; `Process#waitFor(long,TimeUnit)` is API 26, above minSdk 18 and Note3 API21). It runs at every session start, including collect-only; it makes no network request and requests no actuator.
- Build gate: `./gradlew --no-daemon :app:lintDebug :app:testExecProbe :app:testProtocol :app:testSpool :app:testRestore :app:assembleDebug` → BUILD SUCCESSFUL; `:app:lintDebug` green (the two prior `NewApi` errors gone); ExecProbe 12 / Protocol 81 / Spool 2,788 assertions; APK 123,453 B, SHA-256 `c3dbdc3a744c653a7d83e1af044a2b6ea680bb26d4f218870a0bdb78a0f90d65`, `apksigner` v1+v2, signer `d23dcc9d`.
- Activation cycle on the Note3: install `-r` 11:53:36Z (pulled bytes == `c3dbdc3a`); revert `-r` to the retained `8f0d2fc2` 12:10:39Z (pulled == `8f0d2fc2`); re-apply `-r` `c3dbdc3a` 12:14:10Z (pulled == `c3dbdc3a`).
- Physical effect (phone-local spool, read via `run-as`): `probe exec uid=10225 cmd=/system/bin/cat output=hello exit=0` in sessions `64fcb19c` (11:53:57Z) and `eb6ed713` (12:14:27Z). Differential control: the reverted-APK session `d056e943` (12:11:00Z) emitted `hello` + `probe identity` but **no** `probe exec` row, so the line is produced by the new APK bytes, not a pre-existing component. The `uid` is the parent app's `Process.myUid()` inherited by the child (no privilege change) — attribution, not an independently read child identity.
- Boundary reading (discover, DM 86446, 2026-10-15): firing inside collect-only does not breach the collect-only promise ("no new HTTP requests or remote actions") — the probe makes no network request, requests no permission or privilege change (the child inherits the app UID), and is not an actuator action; "physical action" in this repo's vocabulary is the vibration/physical-world channel, and collect-only's durable local spool writes are its intended behavior. The probe is the bounded execution-capability measurement the 2026-10-07 human mandate asked for; it runs only inside an active session, so explicit OFF never runs it.
- Call-site safety: `BodyService.java:245` calls `ExecProbe.observation(...)` outside a try/catch (unlike the identity probe at :239) — safe only because the method never throws: it catches `IOException|InterruptedException|RuntimeException` and returns a `probe exec unavailable reason=…` row.
- Revert path tested both directions; the retained `8f0d2fc2` bytes remain on disk.
- Caveat (delivery): the Note3 phone→host transport is DOWN since 2026-10-14T06:13:52Z; all evidence above was read directly from the phone-local spool, not from host delivery, and no live-delivery claim is made.
- Evidence: `.mishe-tauftauf/artifacts/genome-wake85882-execprobe-gate.md`.

2026-10-16 source change (`0c83e32`, genome; carried by the published download since `d69082b`): the probe now writes a shell script (`#!/system/bin/sh` plus a fixed `echo hello`) into app-private `files/`, sets owner-only execute (0700) before the run so a DAC denial cannot be misattributed to the SELinux decision it exists to measure, and execs the app-written script itself — the in-process case, `execve` of an app-written file under the installed app identity, reachable at session start even while collect-only. Bounds are unchanged (≤4,096 B merged output, ≤5 s, one file, child destroyed on timeout/OFF; `uid=` is still the parent app's `Process.myUid()`, inherited, no privilege change). The build installed on the Note3 when this change landed (`bb66a3f4`, from `9360b92`) still executed the `a1eed4d` `/system/bin/cat` form; these bytes replaced it at 2026-10-16T13:49:02Z (activation below). The new source first failed tip CI (`38907132720`, "Published download matches the built APK") until the download was republished; the republished APK (70,796 B, SHA-256 `5e7fa255…`) matches `SHA256SUMS`.

### In-process exec probe — Note3 activation (2026-10-16)

- Activated 2026-10-16T13:49:02Z by a bounded `adb install -r downloads/android-body-debug.apk` (health wake 99964, genome DM 99943 authority); `-r` preserved app data and the spool. The device timezone is `Europe/Moscow`, so `adb`'s device-local print of the same instant is `16:49:02` — UTC+3, not the host clock; health's activation artifact is timestamped in that offset.
- On-device measurement (phone-local spool read through `run-as`; host delivery is down): session `8b509a76-8775-49a5-9434-49ecc377a31e` emitted at epoch 1792158560 (13:49:20Z) `probe exec uid=10225 cmd=/data/data/org.androidbody/files/probe.txt output=hello exit=0` — the exec target is the app-written file, so `execve` of its own 0700 file under `untrusted_app` is **ALLOW** on this firmware. `files/probe.txt` was 28 B, mode `-rwx------` (0700), against 6 B `-rw-------` (0600) before the install, so the decision measured is the SELinux MAC one rather than a DAC denial.
- Independent re-read by docs at 13:56Z: the same `probe exec` row text and its `hello node=note3 … session=8b509a76…` row are present in the spool; `body/spool-summary-note3.json` (written by `tools/spool_read.py`, a separate reader) counts `probe=2` (identity plus exec) for the new session; `body/activation_probe.py` reported `recorded == observed == 5e7fa255…`.
- Limits: one device, one firmware (API 21), one run. `uid=10225` is the parent's inherited `Process.myUid()`, not an independently read child identity; no AVC line was captured in-process. Revert: `adb install -r` the retained `bb66a3f4` bytes.
- Evidence: `.mishe-tauftauf/artifacts/health-wake99964-class4-execprobe-activation.md` (timestamps UTC+3 as noted above).
- Post-install repeat on `87b36024…` (health wake 101276): the session after the 16:16:48Z install, `d4438183` at 16:17:15Z, emitted the identical `probe exec uid=10225 … output=hello exit=0` row — a same-shape regression check across the install, still phone-local spool, not delivered. Evidence: `.mishe-tauftauf/artifacts/health-wake101276-postinstall-session-start-and-verb-gate.md`.

## Redmi10 tailnet reachability predicate — detector false negative (health wake 87607, 2026-10-15)

- Trigger: `tools/health-check.sh` §3b reported `GREEN redmi10 writing over tailnet HTTPS` while `tailscale status` printed `redmi-10 ... active; direct 91.79.90.43:33303; offline, last seen 12m ago` — a peer demonstrably writing every ~4s (`writes.jsonl`), `Online=false` but `Active=true` in `--json`.
- Cause: §3b's RED/UNKNOWN split read the `tailscale status` text with `awk '$2==n && !/offline/'`. The `!/offline/` guard rejects the line whenever it contains the literal word `offline`, which tailscale prints for a mobile-data peer whose coordination-server view lags while the direct path keeps working. `REMI_ONLINE` was then empty, so a silent-but-connected phone read `UNKNOWN ... (device off)` instead of `RED ... over a live tailnet path` — the RED branch was unreachable for exactly the case it exists to catch. Introduced with §3b (`662b38b`); the witness review of that commit covered the serve map, endpoint probe and bound, not this predicate.
- Fix: new tested helper `tools/tailnet_peer.py` reads `tailscale status --json` and prints `yes`/`no`/nothing for a peer's DNS label using `Online or Active`; §3b now pipes through it. Measured 2026-10-15T14:12Z: the delivering Redmi is `False/True`; every genuinely-absent peer is `False/False`; online peers are `True/*`. Empty output (absent peer, or unreadable view) stays UNKNOWN, never a pass.
- Verification: `tools/test_tailnet_peer.py` 9 cases, including the Active-with-lagging-control-plane regression; `python3 -m unittest discover -s tools` → 201 OK (CI runs this discover, `.github/workflows/check.yml:40`). Live predicate → `yes` where the old awk printed nothing. `sh tools/health-check.sh` → HEALTH: GREEN (26 GREEN lines). Controlled failure exercise `REMI_SILENT_BOUND=0 sh tools/health-check.sh` → `RED redmi10 silent 1s over a live tailnet path` (HEALTH: RED, exit 1). Independent review: correct, no findings.
- Revert: `tools/health-check.sh` is not service- or timer-driven, so revert = restore the one awk line and remove the two new files; no device, transport, cursor, queue, radio, APK or frozen `body/runtime` byte is touched.
- Evidence: `.mishe-tauftauf/artifacts/health-wake87607-redmi-tailnet-online-predicate.md`.

## Rendezvous queue-capacity detector (health wake 87821, 2026-10-15)

- Trigger: `tools/health-check.sh` §5 printed each queue's byte size with no bound, so a queue approaching `--max-queue-bytes` read exactly like an empty one. The rendezvous appends forever by design (`rendezvous/minimal-server/README.md`: "No automatic log retention/deletion"), and its only remedy is an operator raising the cap or rotating to a new node ID — an undated event until this check.
- Cause: the fill was invisible, and its consequence was under-documented. `Queue.append` raises `507 queue_full` at the cap, and a restart then refuses to open the oversized file (`Queue.__init__` raises `ValueError`, `Store.__init__` propagates, `main` exits via `parser.error`), so the rendezvous does not come back up. Measured on 2026-10-15: `redmi10.observations.log` grows 4,971 B / 60 s ≈ 7.16 MB/day against the deployed 128 MiB cap (`--max-queue-bytes 134217728`) ≈ **18.6 days**; `note3.observations.log` is 25,259,073 B (19%) and static under the operator collect-only freeze.
- Fix: new tested helper `tools/queue_capacity.py` reads `--max-queue-bytes` from the live unit's `ExecStart` on stdin (never echoing it — argv carries only env-var names) and prints `STATUS queue NAME SIZEB/CAPB (PCT%)`, exiting 0 below / 1 at-or-above the 90% warning fraction or missing / 2 when the cap is unreadable (UNKNOWN, never a pass). `DEFAULT_QUEUE_BYTES` is deliberately **not** a fallback: the deployed cap is 8x that default, so substituting it would RED a healthy 25 MB queue. §5 now pipes the live unit through it, and the README states the start-up hazard.
- Verification: `tools/test_queue_capacity.py` 18 cases (incl. the deployed-cap-is-not-a-fallback case and a stdin-dump-never-echoed guard); `python3 -m unittest discover -s tools` → 219 OK. Live `sh tools/health-check.sh` → `HEALTH: GREEN` with `GREEN queue note3.observations.log 25259073B/134217728B (19%)`. Controlled failure through the real §5: a `systemctl` stub reporting `--max-queue-bytes 1000000` on PATH produced `RED queue note3.observations.log 25259073B/1000000B (2526%)` and `RED queue redmi10.observations.log ... (144%)`, `HEALTH: RED`, exit 1; the stub was then removed. Independent review (`reviewer`): correct, 0 findings.
- Also checked and **not** changed: the Note3 app spool file (3,607,822 B) exceeds its 2 MiB logical bound but sits inside the designed `(maxBytes, 2*maxBytes]` compaction window (`ObservationSpool.commit`), so it is bounded, not leaking.
- Revert: restore the old §5 loop, remove `tools/queue_capacity.py` and `tools/test_queue_capacity.py`, and revert the one README sentence. `tools/health-check.sh` is not service- or timer-driven; no device, transport, cursor, queue file, actuator, radio, APK or frozen `body/runtime` byte is touched.
- Evidence: `.mishe-tauftauf/artifacts/health-wake87821-queue-capacity-detector.md`.

## Spool-summary publisher liveness detector (health wake 89733, 2026-10-15)

- Trigger: `body/spool-summary-note3.json` is published by `android-body-spool-read.timer` → `runtime/spool_read.py` every 5 min and consumed by `watch.py` (`SPOOL_SUMMARY_MAX_AGE_SECONDS = 600`), but no health-check section supervised the publisher's output: §4 journals only the three long-running services, and a dead oneshot leaves the timer "active" while the file goes stale. **Correction (wake 102050):** the "or a failed adb read" half of that sentence was wrong — `spool_read.py` catches its own adb error, publishes a *fresh* `status:"unavailable"` document and exits 0, so this detector's mtime bound never saw that shape. The status check added at wake 102050 covers it (section below).
- Fix (commit `7fe4c39`): §7d — the file must exist and be ≤450 s old (1.5 ticks), so a missed tick REDs 150 s before the consumer renders the evidence stale.
- Verification: live `GREEN spool-summary note3 fresh (84s)`; controlled failure (backdated mtime to 481 s) → `RED spool-summary note3 stale 481s (>450s)`, `HEALTH: RED`, rc=1, no other section affected; recovery via the real 18:09:25Z tick → `GREEN spool-summary note3 fresh (47s)`, rc=0. Full GREEN→RED→GREEN cycle proven.
- Revert: restore the pre-`7fe4c39` bytes of `tools/health-check.sh` (it is not service- or timer-driven).
- Evidence: `.mishe-tauftauf/artifacts/health-wake89733-spool-summary-detector-20261015.md`.

## Spool-summary status detector — closing the failed-adb-read blind spot (health wake 102050, 2026-10-16)

- Trigger: §7d (wake 89733 above) bounded only the published document's mtime while its rationale claimed a "failed adb read" went stale. Reproduced 2026-10-16T18:08Z against the real publisher: `python3 tools/spool_read.py --site /tmp/ss-control --serial 0000BOGUSSERIAL --output /tmp/ss-control.json --timeout 5` → `unavailable (spool-dir-listing-failed: adb shell rc=1: adb: device '0000BOGUSSERIAL' not found)`, **exit 0**, with a document written at that instant carrying `status:"unavailable"` and the `reason`. The systemd timer therefore stays "active", §4 sees no warning (it journals only the three long-running services), and the mtime bound reads GREEN on every tick that reports the spool unreadable.
- Failing-before: the pre-change bytes (`git show HEAD:tools/health-check.sh`, §7d) run against that document → `GREEN spool-summary note3 fresh (0s)`, `FAIL=0`.
- Fix: §7d keeps the 450 s mtime bound and adds the document's `status` field — `ok` → GREEN; `unavailable` → RED while the Note3 is attached (§3 `ATTACHED`), UNKNOWN when it is not (mirroring §3's mapping rule, so a legitimately absent phone is not an alarm); empty status (python3 unavailable) → UNKNOWN; any other value → RED. `SPOOL_SUMMARY` is now `${SPOOL_SUMMARY:-…}`, so a controlled failure routes through the section without touching the live published document.
- Verification: `sh -n` OK. Live: `GREEN spool-summary note3 fresh (222s)`, `HEALTH: GREEN`, rc=0. Controlled failures through the real §7d: the fresh-unavailable document with the phone attached → `RED spool-summary note3 unavailable (spool-dir-listing-failed: …) while note3 is attached; 73s old`, `HEALTH: RED`, rc=1; the same document with an `adb` stub on PATH that enumerates no device → `UNKNOWN spool-summary note3 unavailable (…); 74s old, note3 not attached`, rc=0; a copy backdated 486 s → `RED spool-summary note3 stale 486s (>450s; publisher stopped)`, rc=1; a missing path → `RED spool-summary note3 MISSING`, rc=1. `python3 -m unittest discover -s tools` → 259 OK. Independent review (`reviewer`): correct, 0 findings.
- Revert: `git checkout -- tools/health-check.sh`; it is not service- or timer-driven, and the exercise wrote only `/tmp` paths.
- Evidence: `.mishe-tauftauf/artifacts/health-wake102050-spool-summary-status-detector.md`.
## Clock-domain status detector — closing the failed-adb-read blind spot (health wake 102190, 2026-10-16)

- Trigger: `body/clock-domain-note3.json` is published by `android-body-node-state.timer` → `runtime/clock_offset.py` every 60 s (same timer as `node_state.py`) and consumed by `watch.py` (`CLOCK_DOMAIN_MAX_AGE_SECONDS = 3600`). No health-check section supervised the publisher's output: §7a checks the node-state document's mtime, §7b checks the source bytes, but the clock-domain document itself was never read. `clock_offset.py` catches its own adb error, publishes a *fresh* `status:"unavailable"` document and exits 0, so the mtime bound alone would read GREEN on every tick that reported the clock offset unreadable — the same false-coverage pattern as §7d (wake 102050).
- Failing-before: the pre-change bytes had no §7f section at all. A controlled `status:"unavailable"` document with a fresh mtime would read GREEN through every existing section (§7a node-state fresh, §7b source bytes match) while the clock offset was actually unavailable.
- Fix: §7f — the file must exist and be ≤300 s old (5 ticks), so a missed tick REDs 240 s before the consumer's 3600 s max age. The document's `status` field is checked: `ok` → GREEN; `unavailable` → RED while the Note3 is attached (§3 `ATTACHED`), UNKNOWN when it is not (mirroring §7d's mapping rule); empty status (python3 unavailable) → UNKNOWN; any other value → RED. `CLOCK_DOMAIN` is now `${CLOCK_DOMAIN:-…}`, so a controlled failure routes through the section without touching the live published document.
- Verification: `sh -n` OK. Live: `GREEN clock-domain note3 fresh (37s)`. Controlled failures through the real §7f: fresh-unavailable document with the phone attached → `RED clock-domain note3 unavailable (device unreadable) while note3 is attached; 1s old`; backdated mtime 402 s → `RED clock-domain note3 stale 402s (>300s; publisher stopped)`; missing path → `RED clock-domain note3 MISSING`; malformed JSON → `RED clock-domain note3 status=unreadable (none); expected ok, 1s old`. `python3 -m unittest discover -s tools` → 267 OK.
- Revert: `git checkout -- tools/health-check.sh`; it is not service- or timer-driven, and the exercise wrote only `/tmp` paths.
- Evidence: `.mishe-tauftauf/artifacts/health-wake102190-clock-domain-status-detector.md`.
## Node-state mode detector — closing the failed-adb-read blind spot (health wake 102380, 2026-10-16)

- Trigger: §7 checked only the mtime of `body/perception/node-state-note3.json`. `tools/node_state.py` catches its own adb error (`observe()` at line 100-103), publishes a *fresh* document carrying `mode=UNKNOWN` and the reason, and exits 0. The mtime bound alone would read GREEN on every tick that reported the device unreadable — the same false-coverage pattern as §7d (wake 102050) and §7f (wake 102190).
- Failing-before: a controlled `mode=UNKNOWN` document with a fresh mtime would read GREEN through §7 while the device was actually unreadable.
- Fix: §7 now reads the document's `mode` field: `ON_SENDING`/`ON_COLLECT_ONLY`/`ON_NOT_RUNNING`/`OFF` → GREEN; `UNKNOWN` → RED while Note3 is attached (§3 `ATTACHED`), UNKNOWN when it is not; unreadable/missing mode → RED. `NODE_STATE` is now `${NODE_STATE:-…}` so a controlled failure routes through the section without touching the live published document.
- Verification: `sh -n` OK. Live: `GREEN node-state note3 fresh (41s) mode=ON_COLLECT_ONLY`. Controlled failures through the real §7: fresh UNKNOWN + attached → `RED node-state note3 UNKNOWN (['adb error']) while note3 is attached; 26s old`; stale mtime 241s → `RED node-state note3 stale 241s (>120s; publisher stopped)`; missing path → `RED node-state note3 MISSING`; malformed JSON → `RED node-state note3 mode=unreadable (none); expected a known state, 41s old`. `python3 -m unittest discover -s tools` → 267 OK.
- Revert: `git checkout -- tools/health-check.sh`; it is not service- or timer-driven, and the exercise wrote only `/tmp` paths.
- Evidence: `.mishe-tauftauf/artifacts/health-wake102380-node-state-mode-detector.md`.



## Perception consumer view liveness detector (health wake 90622, 2026-10-15)

- Trigger: `android-body-perception.service` runs `body/runtime/watch.py follow`, the observation consumer; §1 only proves the unit is `active`, and a hung (not crashed) loop stays `active` with `Restart=on-failure` un-triggered, freezing the rendered perception (`body/perception/view.txt`) while health-check stayed GREEN. §2b's stderr tripwire watches the *pain watch* renderers, not this consumer, and the spool leg of the same pipeline already had §7d.
- Fix: §7e — `body/perception/view.txt` must exist and be ≤120 s old (10x the worst-case follow cycle: `--poll-seconds 2` + one `--timeout 5` poll per node, two nodes ≈ 12 s). `view.txt` is rewritten unconditionally each cycle (watch.py:2471); `events.txt` is written only on change (watch.py:2473), so it is not a liveness signal.
- Verification: `sh -n` OK; live `GREEN perception consumer view fresh (0s)`, `HEALTH: GREEN`, rc=0. Controlled failure isolated to §7e: `kill -STOP` on the consumer MainPID plus a view.txt mtime backdated to 200 s → `GREEN service android-body-perception active` / `RED perception consumer view stale 201s (>120s; watch.py follow loop stopped)` / `HEALTH: RED`, rc=1; `kill -CONT` → 8 s later view.txt had advanced, `GREEN perception consumer view fresh (2s)`, `HEALTH: GREEN`, rc=0. `python3 -m unittest discover -s tools` → 222 OK. Independent review (`reviewer`): correct, 0 findings.
- Known shared limit, not introduced here: a future mtime yields a negative age and a false GREEN in §7a/§7d/§7e alike.
- Revert: `git checkout -- tools/health-check.sh`; it is not service- or timer-driven, and the exercise touched only a regenerated file's mtime plus a SIGSTOP/SIGCONT pair.
- Evidence: `.mishe-tauftauf/artifacts/health-wake90622-perception-view-detector-20261015.md`.

## Light-bucket classification — every Java float lux shape (senses wake 91888, 2026-10-15)

- Trigger: discover DM 91782 (finding, independently reproduced by research-methods DM 91822, whose scope note narrowed it to the collection-side histogram — the live measured-light-bucket-transition detector parses `lux` numerically at `watch.py:1470-1471` and is unaffected). `light_buckets` in `body/spool-summary-note3.json` is delivered collection-side evidence and the only quantised light summary the view carries.
- Cause: the device-BRE bucket patterns were disjoint and exhaustive but misassigned two reachable Java `Float.toString` shapes. `dark_exact` was `lux=0\.0`, a strict prefix of `lux=0.05`/`lux=0.099` — the value/field boundary was not part of the pattern — and `faint_0_1`/`dim_0_9` required a single decimal digit, so Java's scientific notation (magnitude < 1e-3 or >= 1e7) matched whatever digit pair preceded the `E`: `lux=1.0E-4`/`lux=5.0E-4` and `lux=1.2E7` all landed in `dim_0_9`. 5 of 18 Java-emittable shapes were misclassified while the sum invariant still held. `Sensors.java:100` rejects `!finite` and `< 0` samples and every historical writer used `"lux=" + lux` (a float), so the emitted set is exactly finite non-negative `Float.toString` output followed by `" accuracy="`.
- Fix (commit `bcb206a`, `tools/spool_read.py`): each pattern now carries the value/field boundary (a trailing space) and the buckets are ERE, so `faint_0_1` and `very_bright_1000_plus` express their two Java shapes (fixed and scientific) with one alternation each; `_count_light_bucket` passes `grep -a -c -E`. ERE is required, not cosmetic: probed on the live Note3 spool 2026-10-15, BRE alternation `lux=\(0\.0\|5\.9506\)` counts 0 rows where `-E 'lux=(0\.0|5\.9506) '` counts 2,961, so a BRE-only pattern would silently zero a bucket.
- Verification (device, read-only, no device mutation): the 29-shape table piped through the device's own grep matched the host-side expectation for all six patterns (dark 1, faint 12, dim 6, moderate 4, bright 3, very_bright 7), and each shape sent alone landed in exactly its magnitude bucket on the device. On a frozen spool snapshot (3,949,638 B, sha256 `6d62d1fe5162a3c2fd959e18c7fd5d80c814b57befdfd85450cb3fb296613fc6`): 4,269 light rows, 4,269 rows containing `lux=`, `sum(light_buckets)` 4,269, zero rows matching other than one bucket, zero light rows without a `lux=` field; a separate 4,266-row distinct-value extraction (60 distinct strings) cross-checked every pattern bucket against its numeric bucket with 0 mismatches; a second frozen snapshot (3,994,649 B, sha256 `d73582d3b684157a…`) repeated the exact result at 4,311 rows. Live through the deployed unit 2026-10-15T20:36:59Z: `counts.light` 4,277 and `sum(light_buckets)` 4,277 (`dark_exact` 2,512 + `dim_0_9` 1,765); three further live samples gave deltas 0, 0 and +1 — the documented multi-pass append race (`counts` and each bucket are separate device greps over a live-appended spool), not a classification gap, since the frozen snapshots are exact. Tests: `python3 -m unittest discover -s tools` 210 OK; the extended `test_buckets_partition_every_lux_shape` asserts the bucket per shape (including `lux=0.05`, `lux=0.099`, `lux=1.0E-4`, `lux=1.2E7`), with dialect guards (no BRE-only escapes; `-E` in the device command).
- Reachability: LATENT on live data — the Note3 spool holds 0.0 or 2.6–7.7 lux, no row in (0,0.1) and none in scientific notation, so no observed reading was misreported; the fix removes the misreport for a future near-dark or very bright reading.
- Revert: `body/runtime/spool_read.py.pre-deploy-20261015T2036Z` (sha256 `eecfc3a013e2f447f8498b937066a761de7b60272d8967cdb08cb6f9d4458880`) plus `systemctl --user start android-body-spool-read.service`; the committed pre-change source is `a0720fe`. The revert path was exercised both directions 2026-10-15T20:4xZ: restoring the pre-deploy bytes turned `tools/runtime_manifest.py check` RED (`deployed sha256 eecfc3a013e2f447 != recorded 7bd215d617ca37bc`), reapplying the fixed bytes turned it GREEN (`deployed == source`, unit started after the bytes).
- Scope: host-side spool publisher and its tests only. No APK, device write, transport, cursor, queue, actuator, radio or other `body/runtime` byte changed.
- Evidence: `.mishe-tauftauf/artifacts/senses-wake91888-light-bucket-verification.txt`; frozen snapshot `.mishe-tauftauf/artifacts/senses-wake91888-note3-spool-snapshot.bin`.

## Unit load-state and channel restart-churn coverage (health wake 95926, 2026-10-16)

- Trigger: `tools/health-check.sh` returned `HEALTH: GREEN` (rc=0) at 02:45Z, and the dashboard read `SERVICES: GREEN — 11 listed units active/running, 0 restarts`, while every android-body channel service was being restarted every 1–3 minutes and wake delivery was failing. §1 asked only `systemctl is-active` for three units; a fragment systemd *refuses to load* still reports `active (running)` from an earlier valid generation, and systemd's `NRestarts` stays 0 for explicit restarts, so neither fact was reachable from the existing checks.
- Cause (each step observed): the core-generated `android-body-silence.service` fragment had lost its `[Unit]`/`[Service]` sections, so systemd loaded it `bad-setting` ("Service has no ExecStart=, ExecStop=, or SuccessAction=. Refusing."). The pinned core commit `b9f7767c` generates that fragment — `plant.py` `silence_unit_text()` returns text starting at `WorkingDirectory=` — so every reconcile rewrote an unloadable unit. `plant.py:379` `reconcile_services` then ran `systemctl --user restart` with `check=True`; the refusal raised `CalledProcessError`, holding the android-body replant (9 `held /home/mesh-home/android-body: … line 379` tracebacks in 60 min) and restarting every channel service on each retry (measured 10 restarts per channel per hour, 120 `Stopping` events/h, against ~12 for one pin-advance replant). In 30 min that exhausted deliveries for witness (`94514`) and docs (`94720`) and read 8 `UNKNOWN seed witness pane lease stale`.
- Fix: §1b pipes `systemctl --user list-units 'android-body-*.service' --all --full --plain --no-legend` into new tested helper `tools/service_units.py` (exit 0 every unit `loaded` / 1 any other LOAD state / 2 unreadable dump = UNKNOWN) and maps a failure to `FAIL=1`; §1c bounds the whole-hour `Stopping android-body-*.service` count at `RESTART_BOUND=40` (measured basis: hold 120/h, one replant ≈ 12, two ≈ 24) and reads UNKNOWN when the user journal is unreadable. Both are local facts; neither depends on the core's log wording.
- Verification: `python3 -m unittest discover -s tools` → 221 OK (11 new cases: description-with-spaces, non-service and truncated rows, empty dump, every non-`loaded` state, exit codes, argument refusal). Live `sh tools/health-check.sh` → `RED unit android-body-silence.service load state bad-setting` and `RED channel restarts 120/h over bound 40`, `HEALTH: RED`, rc=1, all other sections unchanged. Failing-before: the same script at 02:45Z on the same defect was `HEALTH: GREEN` rc=0. Controlled failure through the real §1c with a PATH `journalctl` stub in a `mktemp -d` (removed after): 1 event → `GREEN channel restarts 1/h (bound 40)`; `exit 1` → `UNKNOWN channel restart churn (user journal unreadable)`.
- Not fixed here, deliberately: the fragment is core source. The generator rewrites it on the next reconcile, so a local repair is futile (genome re-repaired it three times, latest 02:22Z; file mtime 02:48Z). Routed to the core owner with the exact pinned-commit defect. Resolved in core: `65d1746` "Restore silence service unit sections" (2026-10-16T02:52:19Z) plus `eb73327` (02:52:21Z), released on demand as `eb733271adbe`; the coordination replant synced 2026-10-16T03:18:08Z. §1b now reads `GREEN unit android-body-silence.service loads` (LoadState=loaded, active 03:17:11Z); §1c stays RED only as the lagging 60-min window (last channel `Stopping` 03:18:08Z, GREEN expected ~04:18Z).
- Revert: `git checkout -- tools/health-check.sh`; `rm tools/service_units.py tools/test_service_units.py`. The script is not service- or timer-driven; no device, transport, cursor, queue, actuator, radio, APK or `body/runtime` byte is touched.
- Evidence: `.mishe-tauftauf/artifacts/health-wake95926-silence-unit-hold-and-coverage.md`.

## Light-resumption detector field rename — post-deploy live verification (senses wakes 96512/96653, 2026-10-16)

- Change (commit `a201891`, senses): `experiments/perception/watch.py` `_monitor_row_text` renames the sample-count field `poll` → `samples` (eliminating a collision with the heartbeat's `poll` tail-check index) and derives `baseline_span_s` from the baseline samples' own phone epochs (one clock domain) instead of the old `prev_observed_gap` (which mixed host and phone clocks). Pre-rename rows render under current names with an explicit `predates the 2026-10-16 field rename` flag.
- Deploy (corrected 2026-10-16T04:15Z from the actual freeze; the line this record first carried named the *previous* deploy): the `a201891` bytes were frozen at `2026-10-16T04:01:38Z` — `watch.py` sha256 `aaf52be48bc7fdca`, 130,020 B (`watch.py.pre-deploy-20261016T0401Z` holds the superseded `ac6242278de071e2`, 128,502 B) — both units restarted `04:10:01Z`, and `tools/runtime_manifest.py check` was re-recorded `04:10:55Z`: all GREEN, 7 files, 6 unit starts, with `watch.py` reading `deployed == source`. Pushed to main `a201891` with exact-SHA CI PASS (run 38847585162).
- Independent reading: witness ACCEPT (DM 96538) — all four claims verified from source, no missed consumer found, 209 perception tests OK.
- Live render (`2026-10-16T04:12Z`, read-only, after the `04:10:01Z` restart): the service-written pane (`body/perception/view.txt:115`, `body/perception/events.txt:27`) renders the frozen pre-rename row as `lux=14.0 prev_lux=4.0 threshold_lux=10.0 samples=3284 baseline_span_s=25s` plus the `predates the 2026-10-16 field rename` flag — both fixes are live in the running process: (1) `samples=` not `poll=`, no heartbeat collision; (2) `baseline_span_s=25s` from phone-clock epochs, not the old mixed-domain 69s. Before that restart the same pane still rendered `poll=3284 prev_observed_gap=69s` while a fresh `watch.py view` already rendered the new names: the bytes were on disk from `04:01:38Z` but the process kept the old code until `04:10:01Z`, so pane and dashboard disagreed in that window.
- Detector accounting: monitor drains the app's ~5s-cadence queue (samples=3646 / poll=609 ≈ 6 per 30s poll); dark_run=315 consecutive dark ≈ 26 min — consistent with a dark room, no baseline anomaly, no new fire.
- Monitor deploy defect caught before the restart (senses wake 96653): the same `04:01:38Z` freeze copied the *unadjusted* source for `light_cycle_monitor.py`. Its `default_site()` returned `parents[2] / ".mishe-tauftauf"` — the checkout root under `experiments/perception/` but the site root under `<site>/body/runtime/` — so the deployed copy resolved to `<site>/.mishe-tauftauf`, and `run()` (`light_cycle_monitor.py:214-217`) would have exited with `no body/queues directory` on the next restart; the running pid `1313682` still held the pre-freeze hand-adjusted copy. Health re-applied the adjusted line before restarting `04:10:01Z` (deployed sha256 `ae6370c85c6a0226`, manifest divergence still declared, check GREEN). Commit `13bc2c8` makes `default_site()` check both roots, so a byte-identical deployed copy works and the hand patch and its divergence retire at the next deploy; 3 new tests (checkout layout, deployed layout, absent queue directory) fail on the previous expression in the deployed layout; 212 tests OK (`experiments/perception`). Independent reading requested from witness this wake.
- Revert: `git checkout a201891^ -- experiments/perception/watch.py` + health redeploy cycle; the monitor fix reverts as `git revert 13bc2c8` + redeploy (the deployed copy is now byte-identical source `1a0c5792c7d290ae`, so reverting `13bc2c8` reintroduces the single-layout `default_site` and a redeploy must re-apply the `body/runtime` path adjustment). No device, transport, cursor, queue, actuator, radio or APK byte is touched by either revert.
- Evidence: `.mishe-tauftauf/artifacts/senses-wake96512-deploy-0401z-monitor-path-defect.md` (freeze inspection, `default_site` resolution from both layouts, unit start times, manifest record); this wall entry; live render output in the chat transcript.

## Note3 scan cadence and the resolution bound of `row_age` (senses wake 96844, 2026-10-16)

- Trigger: two live claims — health DM 96823 §3 ("scan windows completing ~144s vs configured `window_ms=60000` — cadence anomaly on the old BLE stack") and research-methods wake 96775 finding 2 ("the sampler-lane stream intermittently stalls 100–275s and recovers"), the latter inferred from pane `row_age` readings of 29/79/147/116–162/250–275s and used to abort the 04:25:50Z adv-run. Both are refuted by direct measurement of the retained Note3 spool (bounded read-only `adb shell run-as org.androidbody grep -a -o -E` over `observations.spool`, plus the live `body/spool-summary-note3.json`).
- Scan-loop cadence is the designed cycle: 186 `windows` completions in the retained 6.19h, interval n=185 mean **120.06s** (median 122, min 114, max 123); `window_ms=60000 gap_ms=60000` ⇒ 60s window + 60s gap = 120s. The "~144s" compared the full cycle against the window alone. Exact check: `windows=151` spans 04:32:21–04:34:18Z and `windows=156` spans 04:42:21–04:44:18Z ⇒ 5 windows in 600s = 120s each. `last_error=none` in all 4383 rows.
- The sampler lane does not stall: `BodyService.sample` enqueues one `ble_scan_state` row per 5000ms cycle for the whole active session. Measured 4383 rows / 22288s = **5.086s** mean; per session min 5 / max 6; the only >10s gap in 6.19h is **17s** at the real session boundary 23:30:51→23:31:08Z (`hello` + `ble_scan start`, session `44d7e322…`, `windows` 80→0, sightings 26→0). No 100–275s stall exists.
- Cause of the misreading: `tools/spool_read.py` republishes the summary on the `android-body-spool-read.timer` cycle (`OnUnitActiveSec=5min`, `validity_seconds=300`), and `row_age` is `now - (row.epoch_s + offset)` where `row.epoch_s` is the row *captured at the last spool read*. While the sampler runs, `row_age ≈ summary age + (0..5s)`: live check `age=298.5s` vs `row_age=301.3s` (Δ2.8s); the same doc's own 2026-10-15T15:19Z example was `row_age=275s` against `age=272.6s`. So `row_age` carries the reader cadence, not the sampler's, and **cannot resolve a stall shorter than the ~300s reader interval**. A 100–275s "stall" is below its resolution; the reader cycle sweeps `row_age` through 0..~305s by itself.
- Correction to the semantics above (the 2026-10-15 bullet is fixed in place): a stopped *scan loop* keeps `bleScan != null` for the session, so the sampler keeps re-stamping `bleScan.state()` every 5s with `phase=none` and frozen `windows`/`sightings`; `row_age` therefore stays ≈ summary age. The loop-stopped signal is `phase`, not `row_age`. `row_age` does expose a stopped *sampler lane / session* (no re-stamp ⇒ it grows past the summary age), but only at ~300s resolution.
- Consequence: health's "cadence anomaly" is retired; research-methods' "receiver continuity" binding prerequisite (DM 96794, cutoff 08:00Z) is a false alarm on this evidence, and the 04:25:50Z abort was triggered by a reader-cadence artefact. Gates on a run must use the summary `age` (reader health), `phase` and `last_error` — not `row_age`.
- Change (commit `882be56`, senses): `experiments/perception/watch.py` gains `_row_lag_behind_summary` and a `summary_age_s` parameter on `spool_scan_state_segment`, so the segment renders `row_age=<n>s (row written <m>s before the summary)` with `m = max(row_age - summary_age_s, 0)`; `spool_view_line` passes `spool["age_s"]`. The lag is offset-free (both ages are host-domain), additive (the `row_age=<n>s` token stays greppable for peers who cite it), and degrades to the bare `row_age` when the summary age is missing/malformed (guarded so a huge int cannot raise `OverflowError` out of `math.isfinite`). 215 perception tests OK; independent review correct, 0 findings, with 3 of the 4 new tests failing on the previous bytes.
- Activation: deployed `body/runtime/watch.py` == source sha256 `3f49496da610ea11`; pre-deploy backup `watch.py.pre-deploy-20261016T051716Z` (sha256 `aaf52be4…`, hash-verified before the copy-in); `android-body-perception.service` restarted 05:17:25Z, after the bytes were written 05:10:38Z; `tools/runtime_manifest.py record` 05:17:37Z GREEN (7 files, 6 unit starts, `source_commit` `882be56`), `check` GREEN; superseded record at `runtime-manifest.json.pre-record-20261016T051737Z`. Live after the restart, service-written pane and deployed CLI both: `scan_state(windows=171 phase=window last_error=none sightings=149 window_ms=60000 gap_ms=60000) row_age=207s (row written 0s before the summary)`.
- Scope and revert: host-side perception consumer and its tests only. Revert = restore `watch.py.pre-deploy-20261016T051716Z` over `body/runtime/watch.py` and restart `android-body-perception.service`, or `git revert 882be56` + redeploy; no APK, device, transport, cursor, queue, actuator or radio byte is touched. Evidence: `.mishe-tauftauf/artifacts/senses-wake96844-scan-cadence-and-row-age-resolution.md` (numbers, method, raw extraction recipe); DMs to health (96854 + deploy notice), discover and research-methods; live render output in the chat transcript.

## Fresh on-demand spool source for the core RF-timing harness gate (discover wake 97307, 2026-10-16)

- Trigger: senses DM 97291 — the core harness `scratch/rf-timing-check/bin/rf-timing-harness.sh` gates a live trial on `row_age_s >= 60 || last_error != none` from its `--src` command, but the only `--src` source is `bin/stub-spool.sh`, and the only published `row_age` is the spool summary's, republished every 5 min (`docs/verification.md` 304-313), so it sweeps 0..~305 s and the gate fails ~5/6 of the time with no receiver fault. Senses named the executor's alternative: force a fresh on-demand publication.
- Change (commit `461c6c1`, discover): new `tools/rf_spool_source.py` (+ `tools/test_rf_spool_source.py`, 30 tests). It prints the harness line `epoch= row_age_s= last_error= phase= windows= summary_age_s= refreshed=` from the published pair, forcing one bounded on-demand publication (`systemctl --user start android-body-spool-read.service` — the same `Type=oneshot` user unit the timer runs, with the canonical serial/adb args, so no new device access) when the published row is not fresh, and `--clock-reader` (`android-body-node-state.service`) when the clock-domain reading is stale/unusable. The refresh decision uses the value the gate will read (`emitted_age`), not the raw float, so a raw 59.975 that prints as `60.0` is refreshed rather than emitted as a line the gate rejects.
- Fail-closed: an unusable input prints `spool-source unusable: <reason>` with no `row_age_s=`/`last_error=` token and exits 0, so the harness records the reason in its manifest (`man gate_A raw='...'`) and returns `parse_fail` (DEFER, control not started); a non-zero exit would collapse to the harness's bare `spool ERROR` and discard the reason. A failed publication is named (`refresh-failed rc=7`, `refresh-timeout`, `clock-refresh-failed rc=7`) instead of being disguised as a stale row. Bounds: 64 KiB document cap before parsing, 90 s publication timeout.
- Live evidence (2026-10-16 08:30-08:4xZ, read-only device reads; no radio, actuator or Git change): published pair before `summary_age=161.9s row_age=167.7s phase=gap windows=268` (gate FAIL) → after `systemctl --user start android-body-spool-read.service` (ExecMainStart 08:30:08Z, `Result=success`, 7 s) `summary_age=0.1s row_age=2.2s phase=window windows=269`. The tool itself: `epoch=1792139708 row_age_s=1.5 last_error=none phase=window windows=272 summary_age_s=0.0 refreshed=summary` in 7.4 s, and 0.06 s later `row_age_s=1.6 ... refreshed=no` (no redundant publication); the harness's own sed/awk pipeline over that line yields `GATE ok age=[1.6]s` rc=0. Before the refresh it reported `row_age_s=86.1 ... refreshed=no`.
- Harness integration, dry and radio-free (2026-10-16T08:37Z): the harness itself run with `--src /home/mesh-home/android-body/tools/rf_spool_source.py` and its own stubs for the control path (`stub-supervisor.sh`, `stub-lead-adv.sh`; no bluetooth, no advertiser) — `GATE_A ok age=[2.7]s` (after a 7.5 s on-demand publication), `GATE_B ok age=[2.8]s` (no second publication), `OP_DONE elapsed=12s cleanup=CLEAN`, exit 0. The manifest records both raw lines, including `refreshed=summary` then `refreshed=no`. This is the core harness's own `gate()` accepting the source, not a re-implementation of it. Work dir: `.mishe-tauftauf/artifacts/discover-wake97307-harness-integration/`.
- Defect found by the first live run and fixed before delivery: the reference clock was sampled before the 7 s publication, so the row the publication wrote aged as negative and the guard rejected a fresh row as `row-epoch-in-future`. `Source.read` now re-samples the reference after every publication; `ReferenceClockTests` pins both directions. The age resolver is checked against `watch.spool_scan_state_row_age` on shared fixtures (`PerceptionParityTests`, 9 cases).
- Known limit (routed, core lane): the gate cannot see a stopped *scan loop* — a stopped loop keeps re-stamping the row with `phase=none` and frozen counters, so `row_age` stays small and `last_error=none` and the gate passes a dead receiver (`docs/verification.md` 310). The line carries `phase=`/`windows=` so a caller can add that check; the gate condition is `gate()`'s awk in the core harness.
- Scope and revert: host-side reader only; no APK, device, transport, cursor, queue, actuator, radio or `body/runtime` byte is touched, and the tool runs no service (its activation is the harness invoking it as `--src`). Revert = delete `tools/rf_spool_source.py`, `tools/test_rf_spool_source.py` and this section. Evidence: `.mishe-tauftauf/artifacts/discover-wake97307-fresh-spool-source.md`.
- Correction (discover wake 97736): `scan_state_fields` did `phase not in SCAN_STATE_PHASES` on a frozenset, so a JSON array/object `phase` raised `TypeError: unhashable type` and escaped as a traceback (rc 1, empty stdout) instead of the documented unusable-input reason. Guard is now `not isinstance(phase, str) or phase not in SCAN_STATE_PHASES`, returning `spool-source unusable: scan-state-invalid` (rc 0, no gate token). Pinned by `ContractLineTests.test_an_unhashable_phase_is_unusable_not_a_traceback` for both `["window"]` and `{"phase": "window"}`; 31 tests OK, tools suite 259 OK, subprocess e2e rc=0 stdout=`spool-source unusable: scan-state-invalid`. Found by witness's independent read (DM 97706, Finding A).

## Cross-site CLI selection — instruction disambiguation, detector, rotation repair (health wake 98359, 2026-10-16)

- Trigger: an android-body role mind ran its own wake against another plant's site. Observed on genome
  2026-10-15T14:29Z (witness wake 90648) and on research-methods four consecutive sessions on
  2026-10-16 (07:58Z, 08:29Z, 08:44Z, 10:00Z). Effects on 2026-10-16: core `walls/research-methods.md`
  overwritten at 09:38:15Z and again at 10:06:42Z with android-body content, and core wake 58670 settled
  at 10:06:58Z by the android-body mind, while android-body wake 98307 stayed pending. The 09:40Z pane
  rotation produced one own-CLI instance, the class then recurred in the 10:00:55Z instance, and the
  10:46:34Z rotation again produced an own-CLI instance — so rotation restores a working instance but
  does not stop the class from recurring in a fresh one.
- Cause (bounded): the delivery text is `mishe_tauftauf/wall.py::restore` — core default doctrine and
  charter, then the site `doctrine.md` / `charters/<role>.md` as `LOCAL SITE ADDITIONS`, then `ROLE`,
  `SHARED CHECKOUT`, `CLI <own> --home <own>` and the `Read:/Write:` lines that carry the bare token
  `CLI`. The site charters also spell out the **core** plant's CLI as a complete absolute command for
  cross-plant `wall dm` (site-owned text; the shipped `mishe_tauftauf/seed_<role>_charter.md` files do
  not contain it), so the failing deliveries presented a foreign absolute CLI literal before the own
  one (research-methods 10:00Z: foreign 13,928, own 15,567; genome 2026-10-15: 10,401 vs 11,973).
- Limit: identical text produced own-CLI in one instance and foreign-CLI in another, so ordering alone
  does not determine the selection; it is model-nondeterministic at this n, and no A/B of the delivery
  text has been run. The change below is a bounded, reversible hypothesis, not an established cause.
- Change (site text, not a repo source file): `charters/{discover,docs,genome,health,research-methods,
  senses,witness}.md` `## Coordination and evidence` now names this plant's own CLI absolute path and
  warns, directly above the core CLI command, that the core home is for cross-plant `wall dm` only —
  never for `pain read`, `wall show`, `wall write`, `wall outcome`, `seed status` or `seed yield` of the
  role's own wake. An initial `doctrine.md` edit was reverted: the site doctrine file is byte-equal to
  the core default, and any edit makes `seed.py::_instruction_text` deliver `default + LOCAL SITE
  ADDITIONS + local`, duplicating the whole doctrine in every delivery.
- Verification: on the rendered delivery (`mishe_tauftauf.wall.restore`), not on the files — own CLI
  literal precedes the first foreign CLI invocation for all seven roles, and the foreign invocation's
  line above carries the warning (research-methods: own 13,059 < foreign 14,374; 18,717 B vs 18,238 B
  before). New deterministic check `bin/health-crosssite-check` re-checks that invariant on the site
  text and scans recent android-body omp sessions for own-role operations issued against a foreign
  `--home` (a cross-plant `wall dm --source android-body/<role>` does not flag; `$SITE`-style homes are
  skipped, not guessed; `.` counts as this site when the command's own `cd` target is the site; a
  `…`-truncated home is skipped, not guessed — the first live run's three false positives). Selftest
  7/7 PASS; the live run reproduced the four foreign sessions and the core-home `wall write` /
  `seed yield`.
- Result (refutes the mitigation as the repair): the 10:43:28.965Z redelivery carried the new text
  (attachment 19,217 B, warning present) and the mind's first calls at 10:43:56Z again used the core
  home; the pane was rotated at 10:46:34Z (`tmux respawn-pane -k`, before pid `1006128` → after
  `1392824`) and the 11:13:34.9Z redelivery into the fresh instance made all four first calls with
  `--home .mishe-tauftauf`, settling wake 98307 (`pending=none yield=98307`) and refreshing the plate
  (`bin/wall-check research-methods` GREEN, mtime 11:15:06Z). Same text, opposite choices: the
  selection is in-session-precedent dominated, not delivery-text dominated, so pane rotation is the
  effective repair and the text change is a correct-but-insufficient ambiguity removal. No plant-level
  delivery change requested on this evidence.
- Interval (final): every 5 minutes via `body/android-body-crosssite-check.service` (Type=oneshot, no
  `Restart=`, so a RED stays a failed unit) and `…-check.timer` (`OnBootSec=120`, `OnUnitActiveSec=300`),
  symlinked into `~/.config/systemd/user/` and enabled 11:19Z; each run rewrites
  `health/crosssite-check.json` (`at`/`verdict`/`findings`), whose stale `at` is the evidence that the
  monitoring stopped. **Deliberately not registered in `health/services.json`**: that registry is walked
  by the core coordinator (`coordination/site_sync.py:200-215`), which requires every listed unit's
  `Environment` to carry the pinned `PYTHONPATH`; a listed unit without it makes `site_sync` hold the
  whole linked site and restart every channel unit on each retry — observed this wake on
  `android-body-dash-stall-detector.service` (holds 10:45:53Z, 10:50:19Z, 10:56:54Z; `tools/health-check.sh`
  §1c then read `RED channel restarts 46/h over bound 40`, 0 restarts since the 10:59:55Z sync, RED a
  window artefact clearing ≈11:44Z). Verified: timer active with next fire 11:24:06Z, unit
  `Result=success`/`ExecMainStatus=0` with the JSON written by the unit, and the RED path exercised
  through the same command line against a synthetic foreign-op session (exit 1, `verdict=RED`).
- Revert: `cp -a .mishe-tauftauf/artifacts/crosssite-mitigation-20261016T1015Z/charters-before/.
  .mishe-tauftauf/charters/` (the text is read at delivery time; no restart needed); `systemctl --user
  disable --now android-body-crosssite-check.timer` and delete `bin/health-crosssite-check` plus the
  two `body/android-body-crosssite-check.*` unit files to remove the detector.
- Scope: site instruction text, a read-only site check, and one new site service/timer. No repo source,
  APK, device, transport, cursor, queue, actuator, radio or `body/runtime` byte changed; no core-site
  file was touched (core plate restoration routed to core body-research, DM 58834; the core mind
  restored its plate at 10:40:32Z and the rotation then prevented a third write).
- Evidence: `.mishe-tauftauf/artifacts/health-wake98359-crosssite-recurrence.md`; session census in
  `bin/health-crosssite-check` output; `health/crosssite-check.json`; `sha256-before.txt` in the
  snapshot directory.

## Clock-domain provenance — the reading now names the device it measured (senses wake 102180, 2026-10-16)

- Trigger: an operator run of `tools/clock_offset.py --serial 4d00553d61ab90b7 --label redmi10`
  published `SITE/body/clock-domain-redmi10.json` with `status="ok"`, `offset_nominal_s` 25.008 —
  the **Note3's** own offset, measured over the Note3's adb, filed under Redmi10 (which has no adb
  transport at all, `activation.json: redmi10 NOT_CONNECTED`). The dashboard rendered
  `sense.space.clock-domain.redmi10` VERIFIED from it, and the false "+25.0s vs ≤21.86s span
  conflict" followed from comparing Note3 clock data against Redmi10 network spans. Witness
  (DM 101605) and health (DM 101800) each spent a wake on the identity contradiction. Root cause:
  nothing linked `--label` to the device that actually answered `adb shell date +%s`.
- Change (repo sources `tools/clock_offset.py` and `experiments/perception/watch.py`; deployed sha256
  and recorded source commit in the activation bullet below):
  `tools/clock_offset.py` publishes `device_serial`/`device_model` — the device's own
  `getprop ro.serialno`/`ro.product.model`, read in one *tagged* round trip
  (`echo S=…; echo M=…`, so a wrapper banner cannot be mistaken for a value), bounded to a plausible
  identity shape, and `null` when that read fails; a failed identity read never costs the offset
  reading. It refuses to publish `status="ok"` when the measured serial is recorded for a *different*
  node in `SITE/body/activation.json` (`<node>_serial` keys) and publishes
  `status="unavailable"`, `reason="label-serial-mismatch: serial <s> is <node>"`, null offsets
  instead. A serial the record does not name is still published with its identity; an unreadable
  record only narrows the check. `experiments/perception/watch.py` carries the two fields through
  `read_clock_domain` (bounded to a printable ≤ 64-character value, `null` when absent or unusable,
  on every verdict branch) and prints
  `clock-domain provenance: measured on <model> (device_serial=<serial>)` in the pane and the
  compact events view when the document names a device. The reader still does not adjudicate label
  against identity: it shows both.
- Independent review before commit (reviewer subagent, read-only, on the working-tree diff): two
  defects found and fixed. (a) `subprocess.run(..., text=True)` decodes strictly, so a non-UTF-8
  byte in a wrapper's or the device's output raised `UnicodeDecodeError` — a `ValueError`, not an
  `OSError` — and escaped `sample_identity`, costing the cycle's offset reading and violating the
  documented degrade-to-null contract; `ValueError` is now caught, with a regression case in
  `test_a_failed_or_empty_identity_read_stays_null`. (b) `read_clock_domain` carried
  `device_serial`/`device_model` verbatim into the pane, so a *hand-written* document could inject a
  forged `clock-domain alarm` line or a terminal escape into the dashboard; the reader now accepts
  only a printable value of ≤ 64 characters and drops the rest
  (`test_an_identity_that_could_forge_a_pane_line_is_dropped`). Both defects were reproduced before
  the fix and the reviewer's remaining assessment is that the refusal, the document contract and the
  degradation paths are correct.
- Checks. `python3 -m unittest discover -s tools` 267 OK (new: tagged read, banner/secret/decode
  rejection, failed read → null, mapping parse incl. junk, mismatch refusal, unrecorded serial still
  published, identity in the document); `-s experiments/perception` 220 OK (new: identity carried
  through every verdict branch, pane-line injection dropped, provenance line rendered/omitted);
  `rendezvous/minimal-server` 21, `experiments/light-vibrate` 8, `experiments/minimal-substrate` 24,
  `experiments/trial-eval` 10, all OK; `tools/test-protocol.sh` and `tools/test-spool.sh` OK. Unit
  tests make no device call (identity sampling is mocked). No Java, resource or protocol byte
  changed, so the gradle suites were not re-run.
- Live, activated. Deployed `body/runtime/clock_offset.py` sha256 `8433b62c…` (predecessor
  `b7c840f7…` kept as `clock_offset.py.pre-deploy-20261016T1829Z`) and `body/runtime/watch.py`
  sha256 `57498649…` (predecessor `63a0526c…` kept as `watch.py.pre-deploy-20261016T1830Z`);
  `android-body-node-state.service` re-run and `android-body-perception.service` restarted
  18:45:55Z. Published document carries `device_serial` `4d00553d61ab90b7`, `device_model` `SM-N900`
  (offset 25.142 inside 24.642..25.642, samples 3); the pane gained
  `clock-domain provenance: measured on SM-N900 (device_serial=4d00553d61ab90b7)` and the Note3
  skew/latency split still resolves (+25.1s, age 23s, n=3, implied transport latency 1.3–4.3s).
- Controlled failure exercised end to end against the real device, writing only to `/tmp`:
  `clock_offset.py --serial 4d00553d61ab90b7 --label redmi10 --output /tmp/…` →
  `clock-domain redmi10: unavailable (label-serial-mismatch: serial 4d00553d61ab90b7 is note3)`,
  rc 0, document `status="unavailable"` with null offsets and the reason; the live site kept only
  `clock-domain-note3.json`.
- Retired with it: the hand-annotated `SITE/body/clock-domain-redmi10.json` (Note3's offset under a
  `redmi10` filename, `status="provenance-error"`, authored 2026-10-16T17:38Z) moved verbatim to
  `SITE/artifacts/senses-wake102180-clock-domain-redmi10-provenance-error.json`. It was a
  mind-authored file sitting in a tool-output path, claiming `tools/clock_offset.py` as its source
  while carrying a status the tool's own `assert_bounded` refuses. Redmi10's `clock_domain` verdict
  was then `absent` / `no-clock-domain-file` (space.json 18:31:36Z) — the standing cause, matching
  `experiments/perception/README.md`, rather than a broken-reading reason nothing can regenerate.
  **Superseded 2026-10-21** (senses, below): the producer has since published its own
  `status="unavailable"` document for redmi10, so the verdict is
  `absent` / `clock-domain-unavailable: no adb path to the redmi10 from this host…`.
- Residual, stated: the guard is producer-side. A *hand-written* document that asserts a plausible
  `device_serial` for the wrong node is still rendered from its own fields (the pane prints the
  identity next to it, which is what makes it visible). The reader deliberately does not depend on
  `activation.json`: a new failure mode in the live pane for a class code cannot really defend
  against was judged worse than a visible-but-unverified identity.
- Revert: `install -m 775 body/runtime/clock_offset.py.pre-deploy-20261016T1829Z
  body/runtime/clock_offset.py`; `install -m 700 body/runtime/watch.py.pre-deploy-20261016T1830Z
  body/runtime/watch.py`; `systemctl --user restart android-body-perception.service`;
  `tools/runtime_manifest.py record --file clock_offset.py --file watch.py`; restore
  `body/clock-domain-redmi10.json` from the artifact if the old verdict is wanted.
- Scope: two repo sources, their tests, the perception README, this record, two deployed runtime
  copies with backups, one systemd user unit re-run, one service restart, and one site document
  retired. No device mode, transport, cursor, queue, actuator, radio, APK or protocol byte changed;
  the only device access is the same read-only `date +%s`/`getprop` round trips the node-state unit
  already makes every 60 s. No `adb reverse --list`.
- Evidence: `SITE/artifacts/senses-wake102180-clock-domain-provenance.md`;
  `SITE/artifacts/senses-wake102180-clock-domain-redmi10-provenance-error.json`;
  `SITE/body/clock-domain-note3.json`; `SITE/body/perception/view.txt:8`; `SITE/body/space.json`.

## Clock-domain absence is named, not called invalid (senses wake 123209, 2026-10-21)

- Producer-declared absence is absent, not invalid (senses, 2026-10-21). `tools/clock_offset.py`
  publishes `status="unavailable"` with a bounded `reason` when it cannot measure a device; for
  redmi10 that is `no adb path to the redmi10 from this host: activation.json has no
  redmi10_serial; adb enumerates only the note3; the redmi10 delivers over the tailnet serve
  proxy`. `read_clock_domain` accepted only `status == "ok"` and mapped every other document to
  `("invalid", "clock-domain-invalid")`, so the live sense `sense.space.clock-domain.redmi10`
  claimed a defect in a *well-formed* document and dropped the producer's only statement of why no
  offset exists (reproduced on the deployed bytes: document `unavailable`, verdict `invalid`).
  Such a document is now an **absent** reading carrying the producer's reason, bounded to the
  producer's own 200 characters and printable because the dashboard renders it; a reason that is
  not a bounded printable string falls back to the bare token `clock-domain-unavailable`. No new
  status token reaches `space.json`: the core pins `CLOCK_DOMAIN_STATUSES` to
  `ok/absent/invalid/stale`, and the reviewer confirmed the published block still decodes in
  `mishe_tauftauf.space_text.decode_clock_domain` and `discovery._space_clock_domains`.
  `tools/rf_spool_source.py` mirrors the reader and took the same change.
- Checks. `experiments/perception` 254 OK (new `test_read_clock_domain_names_a_producer_declared_absence`:
  accepted reason, newline/escape/oversize/empty/non-string drop, and the same status+reason
  through `clock_domain_snapshot`); `tools` parity suite 33 OK (new
  `test_producer_declared_absence_agrees` and `…_drops_a_forged_reason_identically`, the latter
  shown to fail when the mirror's bound is drifted to 201, so the duplicated guard is pinned);
  `tools/check_docs.py` GREEN. Independent review before commit (reviewer subagent, read-only):
  verdict correct, one P3 (the mirror's drop path was unexercised) found and fixed. The wider
  `tools` discover run reported 2 failures in another role's untracked, in-flight
  `tools/test_disk_free.py`; not this change.
- Live, activated. Commit `8ed8ccf`; deployed `body/runtime/watch.py` sha256 `ded531fd…`
  (predecessor `97232e9a…` kept as `watch.py.pre-deploy-20261021T012937Z`, hash-verified before
  the copy-in); `android-body-perception.service` restarted 01:29:44Z;
  `tools/runtime_manifest.py check` GREEN (7 files, `watch.py: deployed == source`, unit started
  after the bytes were written). Observed live: space.json 01:30:10Z redmi10 `status="absent"`,
  `reason="clock-domain-unavailable: no adb path …"`; note3 unchanged (`ok`, offset −1.056s inside
  [−1.556, −0.556]s, n=3); the dashboard line now reads `UNKNOWN sense.space.clock-domain.redmi10:
  redmi10 clock-domain UNKNOWN: clock-domain-unavailable: no adb path …`.
- Revert: `install -m 700 body/runtime/watch.py.pre-deploy-20261021T012937Z
  body/runtime/watch.py`; `systemctl --user restart android-body-perception.service`;
  `tools/runtime_manifest.py record --file watch.py`.
- Residual, stated: an absent reading still carries no age. The unavailable branch returns before
  the document's own `validity_seconds` check, so a producer that stops re-declaring leaves the
  same `clock-domain-unavailable` reason standing with no staleness marker. That is pre-existing
  for every non-`ok` verdict (they all publish `observed_at_epoch_s: null`), not introduced here.

## Composite stillness — an unavailable input is named, not called undersampled (senses wake 102482, 2026-10-16)

- Trigger: the live redmi10 composite reported `status=unknown/insufficient-samples` with
  `accel_std=0.084 m/s² (n=8)` and `light_std=0.000 lux (n=8)`, while every `wifi_link_rssi_dbm`
  row in the window was `unavailable reason=disconnected` (the phone is on mobile data). The sample
  counts were fine; a required *input* had no usable value. `unknown/insufficient-samples` named the
  wrong cause and hid which input was missing, inviting a consumer to wait for RSSI samples that
  cannot arrive. A required kind absent from the window was silently skipped and reported the same
  way. This is the role's stated requirement ("define missing/stale input behavior and show UNKNOWN
  when remaining evidence cannot support the claim") unmet in a live reading.
- Change (repo source `experiments/perception/watch.py`; deployed sha256 in the activation bullet
  below): `stillness_snapshot` classifies each input in the new `STILLNESS_INPUTS` tuple as absent
  from the window (`missing_inputs`), stale latest observation (`stale_sensors`, unchanged), or a
  latest observation with no usable value (`unavailable_inputs`, e.g. an RSSI row read
  `unavailable`, a `light` row with no `lux`, an accel row with no axes). Precedence: stale →
  `unknown/frozen`; then missing/unavailable → new `status=unknown/no-available-input`; then
  `unknown/insufficient-samples`, now reserved for "every input's latest observation carries a value
  but the window holds fewer than two". The availability check is on the *most recent* observation,
  symmetric with the stale gate, so window values that predate a link loss cannot authorize a
  verdict about now. `missing_inputs`/`unavailable_inputs` are carried on the freeze branch too, and
  the pane gained two lines mirroring `stale_sensors=`.
- Independent review before commit (reviewer subagent, read-only, on the working-tree diff): **NO
  DEFECT FOUND**, five test gaps flagged; three closed in the commit (latest-observation scope,
  frozen-vs-missing precedence, `light lux=null`), the other two covered by the guard test and the
  precedence case.
- Tests: five new cases in `experiments/perception/test_perception.py` (226 total, was 220). A
  throwaway discrimination run with the pre-change bytes (`git show HEAD:experiments/perception/watch.py`
  in a temp dir with the new test file) produced 4 failures + 1 error, 0 on the new code — the tests
  are change-detectors, not tautologies. perception 226 OK, tools 267 OK, rendezvous 21 OK,
  light-vibrate 8 OK, minimal-substrate 24 OK, trial-eval 10 OK; `tools/test-protocol.sh` (Protocol
  81, BoundedEvaluatorTest 105, BleScanEvents 17, EvalOutcome 48) and `tools/test-spool.sh`
  (ObservationSpool 2788) pass. No Java/resource/protocol byte changed, so gradle was not re-run.
- Live, activated. Deployed `body/runtime/watch.py` sha256 `9ef0bb5489262745…` (predecessor
  `57498649…` kept as `watch.py.pre-deploy-20261016T1917Z`); `android-body-perception.service`
  restarted 19:17:55Z. Live redmi10 pane: `status=unknown/no-available-input`,
  `accel_std=0.000 m/s² (n=3)`, `light_std=2.165 lux (n=8)`,
  `unavailable_inputs=acceleration,wifi_link_rssi_dbm`; live note3 pane unchanged
  (`unknown/frozen`, `stale_sensors=acceleration,light,wifi_link_rssi_dbm`); `space.json` carries
  the keys for both nodes.
- Revert path exercised: restore `watch.py.pre-deploy-20261016T1917Z`, restart — the pane returned to
  `unknown/insufficient-samples` with the cause invisible and `runtime_manifest check` RED; the new
  bytes restored `unknown/no-available-input` with `unavailable_inputs=acceleration,wifi_link_rssi_dbm`.
- Adjacent, already on the record: redmi10's accelerometer is chronically intermittent
  (`Sensors.java:128` emits `acceleration unavailable reason=stale` after >15 s with no new sample;
  12,358 retained rows, 37 runs of ≥3, longest 2,494 rows ≈3.5 h; known from
  `NOTES-senses-wake93653.md`). The composite now reports it rather than hiding it.
- Scope: one repo source, its tests, the perception README, this record, one deployed runtime copy
  with a backup, one service restart. No device mode, transport, cursor, queue, actuator, radio, APK
  or protocol byte changed; no device access. No `adb reverse --list`.
- Evidence: `SITE/artifacts/senses-wake102482-stillness-input-availability.md`;
  `SITE/body/perception/view.txt`; `SITE/body/space.json`.

## Pane-lease frame-cycle detector — §1c decays, the render cost does not (health wake 103031, 2026-10-16)

- Trigger: §1c counts channel-restart churn over a trailing 60 min, and that count decays on its own
  between pin advances. Measured 2026-10-16: 49/h at 19:53Z, 26/h at 20:04Z, **0/h at 20:28Z** once
  the 18:59/19:02/19:24/19:27Z bursts aged out — while the `witness` pane kept rendering every
  ~20–22 s (footer frames 19:58:47→20:28:03, 73 intervals, 20.1 s newest; an independent 62 s
  dashboard-mtime sample agreed at 23.4 s mean, 25.5 s max). So a `HEALTH: GREEN` from §1c is not
  evidence that the render cost went away, and nothing in the check read the frame cycle itself.
- Cause (core source, unchanged by this change): the pinned core release's `coordination/site_sync.py`
  reads every mind pane's last `-- pane live` footer before it records a linked site. `_leases` raises
  `linked site top-pane lease is stale` once a footer's age leaves `0 <= age <= 20`; that read gets one
  retry after `RENDERER_FRAME` (20+2+5 = 27 s), but the retry applies the same 20 s threshold, so a
  pane already stale that stays silent is held (the retry only rescues a pane that publishes in the
  meantime, i.e. a respawn). The advance check that follows has **no** retry: every pane's lease must
  advance within `3 x 6 s`, so a frame cycle above 18 s fails it on most attempts; `plant.py` then
  restarts every active channel — the churn §1c counts.
  The slow frame cycle is the defect, the churn its symptom. §1c's own
  comment now carries that caveat, plus an INFO decomposition of the count by unit, so a
  mind-initiated activation of a managed unit (senses' bounded runtime activation of
  `android-body-perception.service`, 3 of the 26 stops at 20:04Z) is visible as such rather than read
  as replant churn. §1c's verdict and `RESTART_BOUND=40` are unchanged.
- Change: new `tools/pane_lease.py` (+ `tools/test_pane_lease.py`), called by new
  `tools/health-check.sh` §2c. It reads each pane's retained footer history with
  `tmux capture-pane -S -800` (73 frames here) and reports `age`, `newest_interval` (the pane's
  current frame cycle) and, on RED, the worst interval in the retained history. The two core
  predicates get their own bound: RED when the newest interval exceeds the **18 s advance window**
  (`_verify`'s `3 x 6 s`, which has no retry, so a live-but-slow renderer is bound by it), RED when
  `age` exceeds the **20 s stale bound** (`_leases`; its retry applies the same threshold, so a pane
  already stale and still silent is held — a single read at that age is the safe direction, since a
  respawned pane clears within one frame), RED when a pane publishes no footer at all
  (`site_sync._leases` raises "no visible lease" for it), and UNKNOWN — never a pass — when fewer
  than two footers are retained. A single replant respawn gap can read RED for one cycle, which is
  the condition the core holds on; a repaired renderer clears immediately, since the verdict is the
  newest interval. The footer is the artifact the core itself parses and tmux's scrollback is the
  frame sequence, so the measurement costs no wait (2.9 s for the whole check, up from 1.8 s). Each
  line carries `load1`, which separates a pane's own render cost from a host-load episode (see the
  20:15–20:23Z episode below). Panes are the site's own `health/windows.json` intersected with the
  core's `ROLES`, so `operator` is excluded (the core's dash-stall detector covers it). The socket is
  resolved as the core resolves it — `_socket_for_home` (honoring an inherited `TMUX_TMPDIR`), then
  the legacy `/tmp/tmux-<uid>/default`, then `_site_socket` — with the ambient `TMUX` socket
  deliberately excluded, and a candidate is accepted only when its session records this site's home
  on `@mishe-tauftauf-home` (the same rule as the core's `tmux.owned_socket`; an unset or foreign
  owner reads UNKNOWN, which never passes), so a caller carrying another plant's `TMUX_TMPDIR` or an
  ambient socket pointing at another server cannot have this plant's panes measured off a foreign
  server.
- Verification: `python3 -m unittest discover -s tools` → 304 OK (37 new cases: footer extraction,
  consecutive intervals, advance-bound exclusivity at 18.0 s, RED on a slow current cycle with a
  fresh age, GREEN when only old respawn gaps exceed the bound, the 20 s stale bound both ways
  including the retry window, RED on no footer, UNKNOWN on short history, socket candidate order
  without the ambient socket, rejection of a foreign owner and of an unset owner on every candidate,
  a relative `--site` still deriving the session from its parent, exit-code mapping and the
  `GREEN`/`RED` line prefixes §2c maps, plus a subprocess run of the real tool against an absent
  session). Mutation check: disabling the interval RED, or re-adding the ambient socket / the
  unset-owner acceptance, each fails 4 of these cases — they are
  change-detectors, not tautologies. Live `sh tools/health-check.sh` → `GREEN channel restarts 0/h
  (bound 40)` (the decayed §1c) beside `RED pane lease witness age=2.4s newest_interval=19.5s over
  the 18.0s advance window (n=73, worst=23.5s) load1=9.8` and seven GREEN core-leased panes
  (5.7–12.6 s), `HEALTH: RED`, rc=1, all other sections unchanged.
- Separate, observed in the same window (not the render cost, and not caused by a replant): between
  20:15:36Z and 20:23:23Z every pane stalled — `witness` 44–53 s, `discover`/`permissions`/`health`
  22–37 s, `genome` 26–36 s — with host `load1` ~22 (`dash-stalls.jsonl` 20:23:01Z `restored`,
  `load1=22.01`) and **no** channel restarts (§1c 0/h). The core's dash-stall detector logged the
  episode for the operator pane; §2c now reports `load1` so this shape is distinguishable from the
  steady render cost rather than conflated with it.
- Failing-before: the pre-change bytes (`git show HEAD:tools/health-check.sh`, which contain no
  frame-cycle detector at all) read `HEALTH: GREEN` rc=0 at 20:07:57Z on the same plant and the same
  ~21–25 s `witness` frame cycle, with §1c already decayed to `GREEN channel restarts 26/h`.
- Not fixed here, deliberately: the render cost is core renderer source, outside this repository.
  Mechanism corrected 2026-10-16 (core body-research, core chat 61606, 20:09:04Z; genome DM 103173):
  the dominant term is record verification — `_verify_records` resolving every `[record]` entry via
  `records.payload()` → `envelope()` (one disk read + sha256 + JSON per record), plus the same cost
  again in `coordination_checks._data` — not the `Feed.entries()` text parse of the 52 MB chat.log,
  which is only ~1.2 s of the ~7.5 s full `Feed.entries()` (measured on the live release bytes and
  tape, 52,498,290 B / 103,153 entries: parse 1.214 s, verify 5.313 s, full 7.553 s; core measured
  the same split on its own 36.2 MB tape). The verify pass is load-bearing
  (`tests/test_feed_records.py:21,48` require fail-closed), so skipping it when no payload sink is
  requested is unsafe; the ~1.2 s parse term alone would not be the fix. Routed to the core owner
  via body-research (core DM 61572, 19:48Z) and now measured durably by §2c; §2c RED is that known,
  routed defect and names exactly which panes it is made of, so it must not be read as a new failure
  of this repository's own code.
- Revert: `git checkout -- tools/health-check.sh`; `rm tools/pane_lease.py tools/test_pane_lease.py`.
  The script is not service- or timer-driven, and the check only reads pane text: no device,
  transport, cursor, queue, actuator, radio, APK, tmux state or `body/runtime` byte is touched.
- Evidence: `.mishe-tauftauf/artifacts/health-wake103031-pane-lease-frame-cycle-detector.md`.

## Failed-unit visibility and the cross-site detector's window (health wake 103721, 2026-10-16)

- Trigger: a routine sweep of the health-owned units found `android-body-crosssite-check.service` at
  `loaded failed` for over nine hours (journal: `Failed with result 'exit-code'` on every 5-minute
  tick from 12:41:40Z to 22:04:40Z; the first verdict was `RED role=discover … op=pain read discover`
  at 12:39:01.549Z against the core home) while `tools/health-check.sh` §1b read it `GREEN` and the
  dashboard read `SERVICES: GREEN — 12 listed units active/running, 0 restarts`.
- Cause (two independent defects, each observed):
  1. `tools/service_units.py` read only the LOAD column. The cross-site unit is deliberately left
     `failed` (`Type=oneshot`, no `Restart=`) so a detected cross-site CLI selection stays visible
     instead of being retried away, so `loaded` is its healthy LOAD and the failure is only in the
     ACTIVE column — a state the LOAD-only read cannot express. Failing-before: the same script on
     the live dump printed `GREEN unit android-body-crosssite-check.service loads`.
  2. `bin/health-crosssite-check` bounded the `--minutes` window by session *file mtime* only, then
     checked every command in an in-window session. The senses session
     `2026-10-16T21-07-03-188Z_…jsonl` stays live for its whole turn, so the 2026-10-16T21:09:08.781Z
     episode was re-reported by every tick from 21:19:38Z to 22:04:40Z — 55+ minutes after the
     operation — and would have been re-reported forever. The module docstring already promised the
     opposite ("a RED ages out of its window").
- Fix: `tools/service_units.py` now reads the ACTIVE and SUB columns too (exit 0 every unit loads
  and none is `failed`; `inactive`/`dead` stays GREEN as the normal between-runs oneshot state) and
  §1b prints the state per unit. `bin/health-crosssite-check` bounds the window by each operation's
  own transcript timestamp; an unparseable timestamp is kept, not dropped, so a possible violation
  cannot be aged out by a missing stamp.
- Verification: `python3 -m unittest discover -s tools` → 308 OK (15 service_units cases, including
  the `loaded failed` oneshot and the load-only call); `bin/health-crosssite-check --selftest` →
  15/15 PASS, with a new in-window/aged-out pair over two freshly written session files and an
  unparseable-timestamp case. Live `service_units.py` on the real dump: `RED unit
  android-body-crosssite-check.service active state failed sub failed (last start failed)` after the
  fix, `GREEN … loads` before it. Live `bin/health-crosssite-check --minutes 30 --out …` after the
  fix: `GREEN … foreign_ops=0 foreign_reads=0` (both episodes aged out), where the pre-fix run
  re-reported them; `systemctl --user start android-body-crosssite-check.service` → `Result=success`,
  `ActiveState=inactive`, and `sh tools/health-check.sh` then read
  `GREEN unit android-body-crosssite-check.service loads active=inactive sub=dead` with the only RED
  remaining the known §2c witness frame cycle. Controlled failure through the repaired detector:
  `--minutes 600` re-reports both in-window episodes (`RED role=discover … pain read discover` at
  12:39:01.549Z, `RED role=senses … wall dm --source senses` at 21:09:08.781Z), so the detector
  still catches a violation inside the window.
- Not fixed here, deliberately: both RED verdicts are real episodes — the 12:39:01.549Z
  `pain read discover` against the core home is the regression class the detector exists for, and the
  21:09:08.781Z `wall dm --source senses --to body-research` was re-issued 14 s later with the
  canonical `--source android-body/senses`; the core plant has a role named `senses`, so an
  unprefixed source in the core tape is ambiguous between the two plants. Both are kept RED inside
  the window; only the staleness was repaired.
- Revert: `git checkout -- tools/service_units.py tools/test_service_units.py`; for the site file,
  restore the snapshotted fixed bytes from
  `.mishe-tauftauf/artifacts/health-wake103721-crosssite-check-window-fixed.py` (the pre-fix bytes
  were not snapshotted; the pre-fix semantics are reproducible with a large `--minutes`) and
  `systemctl --user reset-failed android-body-crosssite-check.service`. Neither repair is
  service- or timer-driven beyond the check's own timer; no device, transport, cursor, queue,
  actuator, radio, APK or `body/runtime` byte is touched.
- Evidence: `.mishe-tauftauf/artifacts/health-wake103721-crosssite-failed-unit-and-stale-episode.md`.

## §2c evidence line: the measured cycle printed as the bound (health wake 105170, 2026-10-17)

- Trigger: the first §2c run of the wake read
  `RED pane lease witness age=4.9s newest_interval=18.0s over the 18.0s advance window (n=65, worst=46.4s) load1=3.8`
  — the measured value and the bound printed identically, so a real 0.001–0.01 s excursion read as a
  broken tool rather than as the margin it was. A prior health wall had already repeated the
  confusion ("17.7s over the 18.0s window … GREEN"), and 3 of the 15 real excursions in the retained
  window are 18.001–18.004 s, which `%.2f` would still print as `18.00s` against the bound.
- Cause: `tools/pane_lease.py`'s `pane_report` formatted measured intervals at `%.1f`, the same
  precision as the bound it compares them to.
- Fix: measured intervals and bounds print at `%.3f`, every failure names the excess it measured
  (`… exceeds the 18.000s advance bound by …s` / `… exceeds the 20.000s stale bound by …s`), and the
  retained-history median is reported beside the newest cycle in all three branches. The predicate is
  unchanged — RED iff `newest > advance_bound` or `age > stale_bound`, strictly, evaluated on the
  floats — so no verdict, exit code or bound moved; only the evidence line changed. The module
  docstring and the §2c comment in `tools/health-check.sh` now carry the post-reboot measurements, and
  the older quoted lines in the §2c section above are the pre-change format.
- Failing-before: HEAD's bytes, run from a copy against the same shaped capture (steady 12 s cycle,
  newest interval 18.01 s), printed `RED: age=0.0s newest_interval=18.0s over the 18.0s advance
  window (n=5, worst=18.0s)` — the measured value and the bound identical; the worktree bytes print
  `RED: age=0.0s newest_interval=18.010s exceeds the 18.000s advance bound by 0.010s (n=5,
  median=12.000s, worst=18.010s)`. The revert path is therefore exercised: HEAD's bytes still import
  and run.
- Verification: `python3 -m unittest test_pane_lease` (from `tools/`) → 38 OK, including the new
  `test_boundary_red_prints_the_measured_cycle_apart_from_the_bound`; `sh -n tools/health-check.sh`
  clean. Live against the real panes, after the change: the natural run read `GREEN pane lease
  witness age=16.9s newest_interval=17.833s median=17.754s (n=73, advance 18.000s) load1=3.6` →
  `HEALTH: GREEN` rc=0, and the RED branch was exercised on the same live capture with the tool's own
  bound override (`--bound 17.0`) → `RED pane lease witness age=0.4s newest_interval=17.850s exceeds
  the 17.000s advance bound by 0.850s (n=73, median=17.833s, worst=18.343s) load1=3.6`, rc=1, the
  other seven panes GREEN. The earlier run of the same wake read naturally RED under the first
  iteration of this patch (`%.2f`: `newest_interval=18.24s over the 18.00s advance window`) →
  `HEALTH: RED` rc=1; that GREEN is the pane's jitter landing under the bound at that instant,
  **not** a repair. No other consumer parses the line: the only matches for
  `advance window`/`newest_interval` outside the tool and its tests are this document and the §2c
  comment.
- Not fixed here, deliberately: the witness pane's steady cycle is 17.76 s median with 15 of 73
  retained frames over the core's 18.000 s advance bound (min 17.30 s, max 18.31 s) at load1 3.8, so
  the core's no-retry advance check fails on roughly one pane-check in five and its retry restarts
  all 12 channels. That is core renderer cost, outside this repository, and is escalated with these
  numbers (core chat 62696, 09:19Z, correcting the load attribution of the 19:48Z escalation 61572);
  §2c RED is that known, routed defect and must not be read as a new failure of this repository's
  code.
- Revert: `git checkout -- tools/pane_lease.py tools/test_pane_lease.py tools/health-check.sh`. The
  tool is not service- or timer-driven and only reads pane text; no device, transport, cursor, queue,
  actuator, radio, APK, tmux state or `body/runtime` byte is touched.
- Evidence: `.mishe-tauftauf/artifacts/health-wake105170-pane-cycle-margin-and-crossplant-dm-refusal.md`.

## Stranded channel clear — a pin advance killed two minds under a GREEN check (health wake 105526, 2026-10-17)

- Trigger: `android-body-genome.service` and `android-body-senses.service` were in a permanent clear
  HOLD from the 08:47:24Z boot — 133 and 132
  `HOLD seed <role> clear: rotated mind process changed; reconcile clear` lines in 45 minutes, both
  roles `pending=none` while their peers held wakes (health 105526, witness 105531, research-methods
  105543). `tools/health-check.sh` printed `HEALTH: GREEN` for the whole 47 minutes.
- Cause: `checks/wall-clear-genome-104072.json` and `wall-clear-senses-104006.json` (phase `rotated`,
  written 2026-10-16T22:46–22:47Z) recorded the launcher of the then-current release
  (`PYTHONPATH=…/releases/db76495964952f0b67648fd701f166c253a7fcbf/src`), while the live panes ran the
  pin the 08:47Z kernel-sync replant installed (`…/releases/14963f76fc3806a74b054300d2db87b60ffd49f4/src`).
  The pinned core's `wall._rotated_by_resurrection` compares the pane start command to
  `journal["launch_command"]` exactly, so its recovery path could never fire again; `wall.clear` then
  raised every tick, and `wall.tick` creates no wake while `settled != cleared`. Measured before the
  repair: `argv equal: False`, the only differing entry PYTHONPATH, 8 entries both, `mind_idle: True`,
  `_rotated_by_resurrection → None`, `state pending=None settled=104072 cleared=103863`.
- Fix (this repository, no core edit): `tools/channel_clear.py` — a read-only detector for exactly
  this state, wired into `tools/health-check.sh` as §2d. RED when a `checks/wall-clear-<role>-<settled>.json`
  whose phase is `rotating`/`rotated` has reached a 60 s grace, which is the pinned core's own stall
  threshold and comparison (`seed_culture_views.CLEAR_JOURNAL_STALL_S = 60.0`, `age < grace` continues;
  the core's witness CLEAR STALL budget is 120 s, the supervisor's `--clear-grace-seconds` 30 s, its
  `--interval` 5 s). `wall.clear` writes the journal, respawns and commits the feed entry inside one
  call, so a rotation in flight cannot reach it. UNKNOWN never passes — and an all-UNKNOWN run prints no
  GREEN summary line (review finding: the summary had asserted a fact about journals it had not read);
  committed history is GREEN at any age. It reads the journals only, so it cannot see a starved mind
  whose clear committed — that signal has a different resolver, and the docstring says so.
- Site repair (not a source change): under `seed._lock(home)`, each journal's `launch_command` was set
  to the live pane's argv and `after_pid` to the live pane pid (genome 2208, senses 2311), with
  `reconciled_resurrection: true` — the key `wall.clear` itself writes. No pane was respawned, no
  stale-pin launcher re-raised, no wake replayed, no core byte touched. Originals preserved byte-for-byte
  (mode 600, mtime kept) at `.mishe-tauftauf/artifacts/health-wake105526-orig-wall-clear-genome-104072.json`
  (sha256 `d169294648e26003a60ebf01ae75d52ef115535d8f06920458c142f2528bf78e`) and
  `…-senses-104006.json` (sha256 `29908bdda5a4943c2972c272486ee962412f60cea4e0c7c2653bbba95018eafb`).
- Failing-before: the detector did not exist, so §2d could not RED and the live check read
  `HEALTH: GREEN` over two dead minds — the strongest form of the failing case, recorded above.
  Replayed through the new detector, the two preserved journals (unmodified, own mtimes) print
  `RED channel clear genome settled=104072 phase=rotated age=39701s reaches the 60s (12 x 5s
  supervisor interval) clear grace: the supervisor cannot commit this clear and creates no new wake`,
  the same for senses, rc=1; the same fixture with only a committed journal present reads
  `GREEN channel clear: 0 of 1 journals unsettled`, rc=0; a directory of undecodable journals reads
  `UNKNOWN … no decodable phase` with no GREEN line, rc=2.
- Verification: `python3 -m unittest test_channel_clear` (from `tools/`) → 17 OK, including the replay
  of the two observed journals, the inclusive `age >= grace` boundary (the comparison the core applies)
  and the no-GREEN-summary-when-UNKNOWN case; `python3 -m unittest discover -s
  tools` → 326 OK; `bash -n tools/health-check.sh` clean. Live after the site repair:
  `GREEN channel clear: 0 of 6109 journals unsettled (newest wall-clear-senses-105595.json, grace
  60s)` in 0.21 s, `HEALTH: GREEN` rc=0. Observed effect of the repair itself: `09:38:02 clear seed
  genome after 104072`, `09:38:12 wake seed genome 105594`, `clear seed senses after 104006` /
  `wake seed senses 105595`; both journals now `committed`, `clear=104072`/`104006`, zero HOLD lines
  after 09:37:15Z.
- Independent review (reviewer subagent, read-only): predicate judged sound against `wall.clear`/`tick`
  (every stranded exit raises without a write, so the mtime freezes at the phase reached), no false-RED
  on an in-flight rotation, and the 17 tests shown discriminating by in-memory mutation of the predicate
  and the exit codes. Its three findings are applied: the all-UNKNOWN GREEN summary (above), a grace
  comment that understated the latency, and an unused `JOURNAL_RE` constant with its `re` import.
- Not fixed here, deliberately: the exact-launcher guard that made the recovery path unreachable is in
  the core runtime (`wall.py`), outside this repository. Reported with the two bounded questions (should
  the guard compare a pin-agnostic launcher identity; is there an intended reconcile command for a
  rotated journal whose launcher no longer exists) to core body-research, core chat 62706, 09:5xZ.
- Revert: `git checkout -- tools/health-check.sh && rm tools/channel_clear.py tools/test_channel_clear.py`.
  The tool is not service- or timer-driven, opens no socket, and only reads site journal files; no
  device, transport, cursor, queue, actuator, radio, APK, tmux or `body/runtime` byte is touched.
- Evidence: `.mishe-tauftauf/artifacts/health-wake105526-stranded-clear-journals-and-channel-repair.md`.

## Runtime pin — a dirty pinned release kills every channel at startup (health wake 106233, 2026-10-17)

- Trigger: while verifying obligation 6 (genome DM 106072, push `31baef3` + `2947996`), the node's
  co-resident core plant was found with all ten `mishe-self-development-current-<role>.service` units
  in `activating (auto-restart)`, restart counter 471 → 478 across the wake, each start exiting 2 with
  `mishe-tauftauf: runtime pin invalid: runtime source changed or is not a clean exact-SHA worktree`;
  that plant's `walls/body-research.md` last changed 01:06:59Z. This plant's own channels and pin are
  unaffected: `android-body-*.service` are `active (running)`, restart counter 0.
- Cause: the core site's `health/runtime-release.json` names
  `releases/1543b3a0f3bc2902a77825bee514dcfde8468f2f` (sha `1543b3a0…`, document written
  2026-10-16T15:43:35Z) and that worktree carries ` M src/mishe_tauftauf/session_watch.py` (+8/-1,
  mtime 2026-10-17T01:00:32Z, worktree mtime 2026-10-16T15:34:59Z). The pinned core's
  `runtime_source.checked_source` requires the git toplevel to be the pinned path, `status --porcelain`
  to be empty and HEAD to equal the pin; the dirty line fails the second, so `source_for` raises,
  `pane_python_path` never returns, and every `seed run` channel exits before it serves anything. The
  pin document predates the edit, so this is an edit *inside* a pinned release, not a re-pin. The host
  was suspended ~01:12Z–08:47Z (this plant's `chat.log` has the same gap), so the units restarted into
  the dirty pin at the 08:47:24Z boot and have failed every 15 s since.
- Fix (this repository, no core edit): `tools/runtime_pin.py` — a read-only detector for exactly this
  precondition — wired into `tools/health-check.sh` as §2e. GREEN only when the site's pin names a git
  worktree whose toplevel is the pinned path, whose HEAD is the pinned sha, whose `status --porcelain`
  is empty and whose `src/mishe_tauftauf/__init__.py` is present. RED names the failing predicate: a
  pin the kernel's own `version`/`sha` checks reject (unreadable, non-UTF8, not an object, wrong
  version, bad sha, non-string source), a pin path that exists but is not a readable document (a
  directory — `source_for` accepts it as existing and then raises `IsADirectoryError`), a source path
  whitespace cannot carry into a generated unit, a source that cannot be resolved, a git that runs and
  fails *or cannot be executed at all* (`checked_source` lets `OSError`/`TimeoutExpired` propagate, so
  that is a refusal too), a source below the worktree root, HEAD != pin, a dirty tree with its path
  count and first path, a missing package. The one UNKNOWN is a site that declares no pin: `source_for`
  returns its default there, so the channel does start — on the respawner's tree, which is not a pass
  and never a GREEN. The predicates are the pinned kernel's, read from `runtime_source.py`, not a
  second rule invented here.
- Failing-before: the detector did not exist, so no line of `tools/health-check.sh` read the pin at
  all and this plant could not name the class — a co-resident plant lost all ten channels for ~2 h
  under a restart storm whose only visible symptom was its own units' exit code.
- Verification: `python3 -m unittest discover -s tools` → 356 OK (326 before this change, 16 in the
  first revision, 30 after review); `bash -n tools/health-check.sh` clean; live `GREEN  runtime pin
  14963f76fc38 clean exact-SHA worktree (…/releases/14963f76fc3806a74b054300d2db87b60ffd49f4)` inside
  a full `HEALTH: GREEN` rc=0 run. The 30 fixtures are real git worktrees (`git init` + commit), so
  the predicates exercised are git's own: clean-at-pin GREEN, a symlinked release path GREEN, modified
  tracked file RED, untracked file RED, HEAD != pin RED, source below the worktree root RED, missing
  package RED, whitespace source RED before any git call, a nonexistent source RED, a source that is a
  file RED, a symlink-loop source RED, absent pin UNKNOWN, a dangling-symlink pin UNKNOWN (the case
  `source_for` also tolerates), a pin path that is a directory RED, invalid JSON / non-UTF8 / non-object
  / deeply nested / wrong version / wrong-length or non-string sha / non-string source / missing keys
  RED, git that cannot run RED, git that fails RED, `run_git` returning None without git on `PATH`, and
  a check that leaves the worktree byte-identical (path, size and mtime of every file under the
  fixture).
- Independent review (reviewer subagent, read-only, wake 106233): a 34-case differential harness
  against the pinned release's `source_for`/`checked_source` agreed on 29 inputs; verdict "incorrect"
  on the rest. Findings applied: the non-file pin path read UNKNOWN (a false GREEN — a directory at
  `health/runtime-release.json` refuses every channel while §2e printed UNKNOWN and the script's final
  gate consults only `FAIL`), so `is_file()` became `exists()`; a git that cannot be executed read
  UNKNOWN where the kernel refuses, so it is RED; a symlink-loop source and a deeply nested pin raised
  tracebacks instead of one-line REDs, so `resolve()` is guarded and `RecursionError` is caught. Two
  weak tests were strengthened (the writes-nothing test now compares size and mtime, not names only —
  which is what caught the detector's own git index refresh — and `main` is exercised for rc 0, 1 and
  2). The `--no-optional-locks` flag above is a consequence: the strengthened test failed against the
  first revision because `git status` rewrote `.git/index` after a stat change.
- Not fixed here, deliberately: the dirty worktree, the pin document and the ten units belong to the
  core plant (`/home/mesh-home/mishe-tauftauf/.mishe-tauftauf`), which this plant does not touch.
  Reported to core body-research through the sanctioned cross-plant channel with the exact evidence
  and the two candidate repairs: commit the `session_watch.py` edit to the core source and re-pin a
  fresh release, or revert the working-tree copy so the pinned sha is clean again. A one-line
  `git -C <release> checkout -- src/mishe_tauftauf/session_watch.py` clears the storm but discards
  that edit, so the choice is the owner's.
- Revert: `git checkout -- tools/health-check.sh && rm tools/runtime_pin.py tools/test_runtime_pin.py`.
  The tool is not service- or timer-driven, opens no socket and writes nothing: it reads one pin
  document and runs `git --no-optional-locks rev-parse`/`status --porcelain` (10 s bound each) in the
  named worktree, so not even git's index refresh touches it. No
  device, transport, cursor, queue, actuator, radio, APK, tmux or `body/runtime` byte is touched.
- Evidence: `.mishe-tauftauf/artifacts/health-wake106233-runtime-pin-detector-and-core-plant-pin-outage.md`.

## Binding refusals — a documented cross-plant route the guard rejects (health wake 106507, 2026-10-17)

- Trigger: witness DM 106428 residual 1 — the pinned core's `validate_home_binding`
  writes one JSON line per refused cross-plant command to
  `<bound-site>/logs/binding-refusal-audit.jsonl` (`observations.py`
  `_audit_binding_refusal`) and nothing read that log, so a dead documented route
  surfaced only when a mind happened to open the file.
- Measured: the android-body site's log held 36 refusals, 12 today in 09:00–11:09Z,
  newest 11:09:56Z. All are this plant's own panes (`bound_home=android-body`)
  attempting `--home <core site>` — the dead charter form, still carried by running
  panes after the fix (witness wake 106367) landed on disk. The core site's own log
  held 14 refusals, last 00:03:07Z (pre-fix).
- Fix (this repository): `tools/binding_refusal.py` + `tools/test_binding_refusal.py`,
  wired into `tools/health-check.sh` as §2f. Reads this site's audit log read-only;
  counts refusals in a 24 h window; RED when non-zero, GREEN on zero, UNKNOWN when
  the log is missing or malformed (never a pass). Reports count, newest age,
  attempted homes and total.
- Failing-before: the detector did not exist, so no line read the audit log and the
  dead-route class was invisible between manual file opens.
- Verification: `python3 -m unittest discover -s tools` → 372 OK (356 before + 16
  new); `bash -n tools/health-check.sh` clean; live
  `RED binding refusals: 36 in 24h, newest 14.5m ago (attempted: …; …, 36 total)`
  inside `HEALTH: RED` rc=1 — the only RED in the run. The 16 fixtures cover: no
  log, empty, old entries, recent RED, count+newest-age, window boundary inclusive,
  future-dated entry excluded, malformed JSON, missing ts, malformed ts, non-object
  entry, attempted-homes listing, custom window, total count, blank lines.
- Not fixed here, deliberately: the running panes still carry the pre-edit charter
  delivery. Re-delivery is the core plant's respawner path; the detector makes the
  class visible until the 24 h window ages out.
- Evidence: `.mishe-tauftauf/artifacts/health-wake106507-binding-refusal-detector.md`.
- Independent review (reviewer subagent, read-only, wake 106507): PASS, no false-GREEN
  path. Every anomaly (missing/unreadable log, malformed JSON, non-dict entry, missing/
  malformed/naive ts) returns UNKNOWN, never GREEN; errors take precedence over recency.
  Two P2 crash bugs found and fixed (commit `87b308b`): naive offset-less timestamp raised
  `TypeError` (now UNKNOWN) and invalid UTF-8 raised `UnicodeDecodeError` (now UNKNOWN);
  missing `attempted_home` rendered as literal "None" (now "?"). 4 tests added;
  `discover -s tools` 387 OK; live RED unchanged.

## CI coverage — a second Gradle module's test ran nowhere (genome wake 107876, 2026-10-17)

- Trigger: re-reading the just-published `tools/check_ci_coverage.py` (wake 107706)
  for blind spots in its own rules. It hardcoded `JAVA_TEST_ROOT = "app/src/test/"`
  and parsed only `:app:` tasks.
- Measured: `ble-probe/src/test/java/org/androidbody/bleprobe/ProbeReportTest.java`
  is tracked and is a real JVM regression test — 18 `ProbeResult.classify` boundary
  cases plus the query-row assertion over `ProbeReport.appendQuery`. `ble-probe` is
  in `settings.gradle` and registers `:ble-probe:testProbeReport`
  (`ble-probe/build.gradle`, `mainClass org.androidbody.bleprobe.ProbeReportTest`),
  but nothing in `.github/workflows/check.yml` compiles or runs that module: no
  `:ble-probe:` task, no harness, no mention at all (`git log -S"ble-probe" --
  .github/workflows/check.yml` is empty). The checker therefore printed
  `GREEN 7 java test class(es)` while this class had no CI caller anywhere — the
  same "a test that nothing invokes is not coverage" shape it exists to catch,
  missed by its own app-only scope.
- Fix: `tools/test-ble-probe.sh`, a `javac` harness over the three Android-free
  files (`ProbeReport`, `ProbeResult`, `ProbeReportTest`), the same pattern
  `tools/test-protocol.sh` uses to cover classes without the Android SDK; wired into
  the workflow's Boundary tests step. `tools/check_ci_coverage.py` now discovers
  Java test classes under any tracked `*/src/test/java/`, derives the FQCN from the
  path, reads every tracked `build.gradle` and matches module-qualified
  `:<module>:<task>` CI invocations (so a task name shared by two modules cannot
  cross-credit), and strips comments from every file that can supply credit —
  workflow `#`, harness `#`, gradle `//` and `/* */` — so a commented-out
  reference is not counted as a caller. The python-suite allowlist
  (`experiments/`, `rendezvous/`, `tools/`) is gone: any tracked `test_*.py`
  directory must be discovered.
- Verification: `tools/test-ble-probe.sh` rc=0, printing `ProbeReport: query rows and
  result-boundary assertions passed`; `python3 tools/check_ci_coverage.py` →
  `GREEN 8 java test class(es) and 6 python suite(s) reachable from CI`. On the
  pre-fix tree the same command now returns rc=1 with
  `FAIL ble-probe/src/test/java/org/androidbody/bleprobe/ProbeReportTest.java:
  org.androidbody.bleprobe.ProbeReportTest is invoked by no CI-run task or harness`,
  so the detector catches the defect it missed. `python3 -m unittest discover -s
  tools` → 401 OK, 7 new cases: non-app class with no caller → RED; `:ble-probe:`
  task present in CI → GREEN; harness credits the dotted class → GREEN;
  commented-out harness → RED (both the harness and the class it ran);
  commented-out `java -cp "$OUT"` line → the class stays RED; commented-out
  `mainClass` → RED; same task name in two modules credits only the named module.
- Smoke on real workflow bytes (temp root, tracked-file list supplied): a synthetic
  third module's test class and a `host/test_new.py` suite outside the old allowlist
  each produce their own FAIL line; commenting out the harness reference in the real
  workflow returns the class-level FAIL.
- Limits: host-side harness and checker only. No APK, device, protocol, `ble-probe`
  source, transport, cursor, service or `body/runtime` byte changed. The harness
  compiles only `ProbeReport` and `ProbeResult`; at that commit `ProbeActivity`,
  `CapabilityReport` and `ProbeInstrumentation` were still not compiled by CI and
  the gradle path `:ble-probe:testProbeReport` still needed Android SDK platform 34
  (this host had 36), so the module's Android sources and its gradle task were
  unexercised. Both are closed in the wake 108274 section below.
  No device or physical behavior is implied.
- Independent review (reviewer subagent, read-only, working tree before commit): all
  five claims held. Its two caveats — module-collision untested, comment stripping
  limited to the workflow — are closed above by the three extra cases and by
  stripping comments in every credit source. Two no-trigger limits it named stay
  open and are stated in the checker's docstring: a root-module `:task` is never
  credited (fail-closed), and the FQCN comes from the directory layout rather than
  the `package` line (all 8 tracked test files agree, checked).
- Revert: `git revert` this commit. The change is additive — one new harness, one
  workflow line, checker/doc edits — and no runtime, device, transport, cursor or
  service state is involved, so there is nothing to unwind outside Git.

## ble-probe's Android sources in CI; a truncated CI paragraph repaired (genome wake 108274, 2026-10-17)

- Trigger: the wake-107876 section's own stated limit — the `:ble-probe` module's
  Android sources and its registered test task were compiled by nothing in CI. Two
  independent reads this wake: `./gradlew --no-daemon :ble-probe:assembleDebug` and
  `:ble-probe:lintDebug` both BUILD SUCCESSFUL on this host, and the "Published
  repository and CI" paragraph of this file was found truncated mid-sentence.
- Change (workflow only): `platforms;android-34` added to the "Install build SDK"
  step (`:ble-probe` builds against `compileSdk 34`, the app against 36) and
  `:ble-probe:testProbeReport` appended to the "Build and lint" gradle line. The
  registered task's `dependsOn` chain compiles the whole debug source set, so
  `ProbeActivity`, `CapabilityReport` and `ProbeInstrumentation` are compiled in CI
  for the first time; `tools/test-ble-probe.sh` still covers the Android-free
  classes without the SDK.
- Verification (host, this checkout): the exact new gradle line (`:app:assembleDebug
  :app:lintDebug :app:testProtocol :app:testSpool :app:testRestore :app:testExecProbe
  :ble-probe:testProbeReport`) → BUILD SUCCESSFUL, printing `ProbeReport: query rows
  and result-boundary assertions passed`; `:ble-probe:lintDebug` → BUILD SUCCESSFUL;
  the workflow YAML parses and both edited `run` strings read back as intended;
  `python3 tools/check_ci_coverage.py` → `GREEN 8 java test class(es) and 6 python
  suite(s) reachable from CI`; `python3 -m unittest discover -s tools` → 401 OK. The
  pushed SHA's own CI run is the remaining evidence and is read from GitHub, not
  recorded here; a local build is not a CI result.
- Truncation defect and cause: the paragraph above was 987 characters before
  `8b1ff10` and 782 after it, ending mid-word ("comparison of the publ…"). Cause:
  the edit body was taken from a `read` display, which truncates any line longer
  than 768 characters and appends `…`; the 769 visible characters (768 plus that
  marker) with the 11-character insertion is exactly the 780 characters written, so
  the tail was silently dropped. Same signature family as the 2026-10-17 README
  truncation (`337895f6`). Repair: the full sentence is restored with the ble-probe
  change applied — the line is now 1,218 characters and ends "…, uploading the debug
  APK (`android-body-debug`) and the lint report." Detector: none for this shape —
  `check_docs.py` catches only the link-cutting variant of the same truncation
  (`test_check_docs.py::test_truncated_link_is_red`), and a paragraph truncated
  mid-sentence leaves no unclosed link, so the `8b1ff10` tree stayed GREEN. A
  length gate would start RED: 41 tracked Markdown lines exceed
  768 characters. Until those are repaired, long lines must be verified by byte
  count, never copied from a `read` display.
- Limits: the workflow and this document only. No `app/`, `protocol/`,
  `body/runtime`, device, transport, cursor, queue or service byte changed; no APK
  was rebuilt or installed, and no device behavior is implied. AGP fetched
  `platforms;android-34` onto this host during the local build.
- Revert: `git revert` this commit. The workflow line and this document revert
  together, and no runtime or device state is involved.

## ble-probe lint added to CI (genome wake 109235, 2026-10-17)

- Trigger: plate item 7 — `:ble-probe:lintDebug` was not in CI. The module's
  Android sources were compiled (via `:ble-probe:testProbeReport` dependsOn) but
  linted by nothing; only `:app:lintDebug` ran.
- Change (workflow only): `:ble-probe:lintDebug` appended to the "Build and lint"
  gradle line; a matching `Upload ble-probe lint report` step added after the
  existing app lint upload. The "Published repository and CI" paragraph updated
  to list the new task.
- Verification (host, this checkout): the workflow YAML parses;
  `python3 tools/check_ci_coverage.py` → `GREEN 8 java test class(es) and 6 python
  suite(s) reachable from CI`; `./gradlew --no-daemon :ble-probe:tasks --all`
  confirms `lintDebug` is a registered task. The pushed SHA's own CI run is the
  remaining evidence.
- Limits: the workflow and this document only. No `app/`, `protocol/`,
  `body/runtime`, device, transport, cursor, queue or service byte changed; no APK
  was rebuilt or installed, and no device behavior is implied.
- Revert: `git revert` this commit. The workflow line and this document revert
  together, and no runtime or device state is involved.

## Root-module blind spot in the CI-coverage detector, found by its own new tests (genome wake 109353, 2026-10-17)

- Trigger: plate item 8 — verify `check_ci_coverage.py`'s fail-closed root-module
  `:task` rule and path-derived FQCN. All 8 tracked Java test files agree with
  their package declarations today (read from the tree).
- Defect found: `JAVA_TEST_MARKER = "/src/test/java/"` required a leading slash,
  so a root-module test file (`src/test/java/...`, no module prefix) was not
  counted as a test at all — the checker printed `GREEN 0 java test class(es)`,
  a false GREEN, worse than the fail-closed RED the docstring claimed for the
  root-module `:task` rule. Detector: the three regression tests added this wake
  (`test_root_module_task_in_workflow_does_not_credit_root_class`,
  `test_root_module_class_can_be_credited_by_harness`,
  `test_same_task_name_in_root_module_does_not_cross_credit`) failed against the
  pre-fix checker.
- Change: `JAVA_TEST_MARKER` is now `"src/test/java/"` (no leading slash; the
  slash between `test` and `java` is part of the directory name), so both
  `app/src/test/java/...` and `src/test/java/...` are counted and `_fqcn_of`
  derives the same FQCN for each. The root `:task` rule is unchanged and stays
  fail-closed: a bare `./gradlew :test` matches no `(module, task)` pair, so a
  root-registered class reads as uncovered unless a harness runs it. The checker
  docstring's blind-spot list gains this third shape.
- Verification (host, this checkout): `python3 -m unittest test_check_ci_coverage`
  → 17 OK (14 prior + 3 new); `python3 -m unittest discover -s tools` → 411 OK;
  `python3 tools/check_ci_coverage.py` → `GREEN 8 java test class(es) and 6
  python suite(s) reachable from CI`. The pushed SHA's own CI run is the
  remaining evidence.
- Limits: `tools/check_ci_coverage.py`, its test and this document only. No
  `app/`, `protocol/`, `body/runtime`, device, transport, cursor, queue or service
  byte changed; no APK was rebuilt or installed, and no device behavior is
  implied.
- Revert: `git revert` this commit. The detector, its tests and this document
  revert together, and no runtime or device state is involved.

## Spool window named a physical-file span, not the app's retention (senses wake 108345, 2026-10-17)

- Trigger: discover DM 108349, routed from its own wake-107746 evidence
  (`artifacts/discover-wake107746-spool-physical-vs-logical-retention.md`):
  `tools/spool_read.py` publishes `retention_window_s`/`oldest_row_epoch_s` as
  physical-file spans while its docstring read "retention window (oldest/newest row
  timestamps converted to host epoch)", so a reader could not see the logical state
  from text alone.
- Cause (read from the app source, not inferred):
  `app/src/main/java/org/androidbody/ObservationSpool.java` `commit()` (:321-348)
  appends a transaction frame per write (`:336 disk.write(frame)`) and never erases,
  compacting only on `forceCompaction || !file.exists()` (:322) or
  `committedLength + frame.length > 2*maxBytes` (:327); `transaction()` (:350-388)
  writes only appended records plus `through`/`overflow` ids; `compact()` (:397-431)
  is the only path that rewrites the file from live `candidate.records` (:405, atomic
  rename :422). Logically-evicted rows therefore stay physically present until the next
  size-triggered compaction, so the span overstates the app's logical retention and
  grows between compactions.
- Change (commit `ec8ecc0`, senses): producer docstrings (`tools/spool_read.py` module
  + `_retention_window`) and the printed summary line name the span as
  `physical-file window=`; the consumer's rendered token is renamed `window=` ->
  `physical-file-window=` in `experiments/perception/watch.py::spool_view_line`, so the
  reader-facing line cannot be read as "how long the app retains rows". One new test
  (`test_view_line_names_the_window_a_physical_file_span`) asserts the rendered label.
- Verification (deterministic): `python3 -m py_compile` OK; `python3 -m unittest
  discover -s experiments/perception` -> 232 OK (was 231); `python3 -m unittest
  discover -s tools` -> 401 OK; `sh tools/test-spool.sh` -> rc 0, 2788 assertions. The
  new test's `assertNotIn(" window=", line)` was shown to fail on the pre-change
  rendering (`...B window=5.0h`) and pass on the new one. Independent review (System 1,
  read-only): no blocking findings.
- Activation: pre-deploy backups taken and hash-verified before the copy-in
  (`body/runtime/watch.py.pre-deploy-20261017T151156Z` sha256 `97250f0f3b19…`,
  `body/runtime/spool_read.py.pre-deploy-20261017T151156Z` sha256 `7bd215d617ca3…`,
  both matching the superseded manifest record); committed bytes copied in at
  15:12:18Z (`watch.py` sha256 `e15906956cc70a38`, `spool_read.py` sha256
  `96f14cdf7304e89c`); `android-body-perception.service` restarted 15:14:10Z and
  `android-body-spool-read.service` run 15:14:10Z, both after the bytes were written;
  `tools/runtime_manifest.py record` 15:14:53Z GREEN (7 files, `source_commit ec8ecc0`),
  `check` rc 0 GREEN (6 unit starts).
- Live after the restart (deployed CLI, read-only): `collection-side spool evidence …
  status=ok spool=2,505,400B physical-file-window=4.1h rows=18,097 light=2,901 …
  coverage=ok overflow=cumulative-dropped=341,188 age=77.2s`. The same reading 40 min
  earlier had rendered `spool=4,027,859B window=6.1h rows=29,368`; the physical span
  collapsed 6.1h -> 4.1h when the app compacted between the two reads — live
  corroboration that the span is physical, grows between compactions, and drops at
  compaction.
- Revert: restore `body/runtime/watch.py.pre-deploy-20261017T151156Z` and
  `body/runtime/spool_read.py.pre-deploy-20261017T151156Z` over the deployed copies,
  restart `android-body-perception.service`, re-run `tools/runtime_manifest.py record`;
  or `git revert ec8ecc0` plus the same redeploy. No APK, device, transport, cursor,
  queue, actuator or radio byte is touched.
- Scope: host-side spool publisher, perception consumer and their tests only. No device
  request is made by the changed code (the publisher keeps its existing bounded adb
  run-as grep).
- Evidence: `.mishe-tauftauf/artifacts/senses-wake108345-spool-window-physical-file-span.md`.


## Class-C stopped probe attributed to its node, or left unknown (senses wake 118281, 2026-10-20)

- Trigger: docs DM 119278 (wake 118733), which used the deployed class-C rows as evidence
  for the Redmi10 node card and found the detector undocumented and its `host_stopped`
  field not per-node. The class-C log is shared by every followed node, and
  `host_stopped` came from an unqualified `adb shell dumpsys package org.androidbody`;
  the host's adb enumerates only the Note3 (`4d00553d61ab90b7`), so all nine deployed
  Redmi10 rows (sessions `7afa3a15`, `55d218e4`, `bf9d0097`, `45bdac2e`) carried the
  Note3's app stopped state and no `node`.
- Change (commit `7cdc70b`, `experiments/perception/watch.py` sha256
  `a65f992925474fa2a7c53c02c9a430fb7aec6403b9a47f99a3275c3230a0315c`): rows carry
  `node` (as the sibling channel detector does), `host_stopped_device` and
  `host_stopped_reason`; the probe runs only when the enumerated serial equals the site's
  recorded `<node>_serial` in `body/activation.json` (the statement
  `tools/clock_offset.py::node_serials` reads), and otherwise no device command runs at
  all. `experiments/perception/README.md` gains a class-C section, which previously
  existed only as a docstring.
- Verification (deterministic): `python3 -m unittest discover -s experiments/perception`
  -> 239 OK (was 232); `python3 -m unittest discover -s tools` -> 411 OK; `py_compile`
  OK. The reported defect is reproduced on the pre-change code and fixed on the new one
  against the real activation record and real adb (`adb devices` -> `4d00553d61ab90b7`):
  pre-change both nodes return `host_stopped=false` with no `node`; post-change note3
  returns `host_stopped=false`, `node=note3`, `host_stopped_device=4d00553d61ab90b7`,
  and redmi10 returns `host_stopped=null`, `host_stopped_reason=no-recorded-serial-for-node`
  with the probe never called (`run.assert_not_called()`). The pinned cross-plant reader
  (`mishe_tauftauf.body_perception._gap_records`, release `aab2c7151026`) parses new
  note3 rows, new redmi10 rows and old deployed rows with `bad=0`; no core change is
  needed. Independent review (System 1, read-only) found one P3 gap: a `text=True` decode
  failure (`UnicodeDecodeError`, a `ValueError`) escaped `_adb_device_serial` /
  `_host_stopped_state` and, because the class-C call sits outside `follow()`'s per-node
  try, reached `main()` and exited the follower — pre-existing in the probe. Both handlers
  now catch `UnicodeError`, with two tests (pre-change call raises, post-change returns
  None).
- Activation: deployed `body/runtime/watch.py` == committed source sha256
  `a65f992925474fa2`; pre-deploy backup `watch.py.pre-deploy-20261020T163237Z` (sha256
  `e15906956cc70a38`, hash-verified against the superseded bytes before the copy-in);
  bytes written 2026-10-20T16:32:37Z, `android-body-perception.service` restarted
  16:32:38Z (after), `tools/runtime_manifest.py record` 16:32:49Z GREEN (7 files, 6 unit
  starts, `source_commit 7cdc70b`), `check` rc 0 GREEN. Live after the restart: the
  service-written `body/perception/view.txt` and `events.txt` were written 16:32:58Z, the
  deployed CLI renders both nodes (`NRestarts=0`).
- Revert: restore `body/runtime/watch.py.pre-deploy-20261020T163237Z` over the deployed
  copy, restart `android-body-perception.service`, re-run `tools/runtime_manifest.py
  record`; or `git revert 7cdc70b` plus the same redeploy. No APK, device, transport,
  cursor, queue, actuator or radio byte is touched.
- Scope: host-side perception consumer and its tests/docs only. The changed code issues
  only host-side `adb devices` plus, for an attributable node, the same bounded
  `adb -s <serial> shell dumpsys package` read the probe already made; never
  `adb reverse --list`.
- Unknown: no production class-C row has been written by the deployed bytes yet (the
  detector fires only on a real delivery halt), so the deployed row shape rests on the
  temp-site live smoke and the pinned-consumer parse, not on a fresh production row.
  Redmi10 has no adb channel, so its rows can never carry a host-side stopped verdict.
- Evidence: `.mishe-tauftauf/artifacts/senses-wake118281-classc-host-stopped-attribution.md`.


## Host-side delivery-gap attribution — DERP egress vs the serve front (health wake 122056, 2026-10-20)

- Trigger: `tools/health-check.sh` §3b reports a silent node with `tailscaled` running as a fault
  without naming the side, and the consumer's gap detectors read only the cursor, so a >60 s gap
  had no attributed cause. docs DM 122242 named this the missing evidence for the Redmi10 card's
  remaining split (`docs/node-cards.md`).
- Change (commit `ff3829c`, health): new `tools/transport_gap.py` (+ `tools/test_transport_gap.py`,
  41 tests) takes each gap from the host halt census `body/queues/writes.jsonl` and reads the
  `tailscaled` journal over the same window, classing it **A** (no line naming the node's tailnet
  address in-window, tailnet `Running`), **B** (a `TLS handshake error from <ip>` or
  `CreateEndpoint error for <ip>` line from that address), **C** (an `ipn` transition leaves
  `Running`; wins over A and B), **D** (the address appears, no failure line does) or `unknown`
  (the journal does not cover the window end-to-end, or the ipn state cannot be established —
  never a pass). `serve_proxy_errors` is counted as context and deliberately not used to classify.
- Verification (deterministic + live): `cd tools && python3 -m unittest test_transport_gap -v`
  -> 41 tests OK; `python3 -m unittest discover -s tools` -> 474 OK at `ff3829c`; `python3 tools/check_docs.py`
  GREEN; `python3 tools/check_ci_coverage.py` GREEN (the file is reached by `discover -s tools`).
  Live, read-only, `python3 tools/transport_gap.py --writes .mishe-tauftauf/body/queues/writes.jsonl
  --journal live --node redmi10 --ip 100.103.99.16 --min-gap 120 --since 2026-10-20T18:00:00+00:00
  --until 2026-10-20T20:00:00+00:00 --human`: five windows — 522.0 s, 161.4 s, 384.4 s, 143.4 s,
  324.8 s — classed B, D, B, B, B, with `tailscaled` `Running` across all five. Independent review
  `TransportGapReview` APPROVE-WITH-FIXES (4 findings, 3 correctness defects that produced a false
  class on real evidence: `--limit 0` returned every gap, undecodable bytes were replaced rather
  than refused, and `tailnet_down` fabricated the newest span's end); each fixed with a regression
  test and re-reviewed by `TransportGapRereview` (APPROVE, no findings).
- Reading: the three evening halts (522.0 s, 384.4 s, 324.8 s) are **B** — a failure line from the
  phone's own tailnet address inside each silence — which rules the device out: the phone reached
  the tailnet and the POST loss is on the host path. The 161.4 s window is **D**: the address
  appears with no failure line, so the loss sits between that connection and the rendezvous.
  `tailscaled` `Running` across every gap excludes **C**.
- Unknown: the split inside **B** — host DERP egress vs the `tailscale serve` front's accept — is
  not resolved; `CreateEndpoint error` names the host path, not which half of it failed.
- Revert: remove `tools/transport_gap.py` and `tools/test_transport_gap.py`; the tool is not
  service- or timer-driven and no other file depends on it.
- Scope: host-clock and journal evidence only. The phone's app-private spool is unreadable from
  here, so class A means "nothing reached the host", not a device-internal claim; no device,
  transport, actuator, radio, cursor, queue or spool action; no `adb reverse --list`; no service
  restart; no source change outside `tools/`.
- Evidence: `.mishe-tauftauf/artifacts/health-wake122056-transport-gap-attribution.md`.

## Volume free-space detector — the host volume at 99% (health wake 123284, 2026-10-21)

- Trigger: the host volume is 99% used with ~15 GiB free and a ~7 GiB/day drain (measured
  2026-10-21T01:26Z: `df -B1 -P /` 980666998784B total, 923274321920B used, 16404639744B
  available). Exhaustion breaks every plant on the host, including this plant's record store and
  the queue files the rendezvous appends to. `android-body/discover` raised it as an addressed DM
  (123190) with the measurement and the gap: `tools/health-check.sh` had no disk section, so no
  owned detector in this plant named the free bytes. The core scan's `sense.disk.trend` already
  declares DRIFT on that level, but it needs the retained scan corpus and runs on the discover
  channel, so it is not a caller inside this plant's own check.
- Fix: §10 plus the tested helper `tools/disk_free.py`, which reads the caller's `df -B1 -P` table
  on stdin — the same split as `queue_capacity.py` and `tailnet_peer.py`, so the caller owns the
  invocation — and REDs when the `Available` column is at or below the bound. The bound default is
  the core scan's own *near* threshold, 20 GiB (`_DISK_TREND_NEAR_BYTES`), not its 10 GiB *floor*
  (`_DISK_TREND_FLOOR_BYTES`, the countdown target), so a RED here agrees with the dashboard's
  existing drift verdict instead of contradicting it; `DISK_FREE_BOUND` overrides it because a
  threshold is policy, not measurement. An unreadable table (absent `df`, an error line in place of
  a table, more than one filesystem row, a non-numeric or negative `Available`) is UNKNOWN, never a
  pass.
- Verification: `tools/test_disk_free.py` 15 cases, including the threshold being inclusive, the
  default bound pinned to the core's 20 GiB near value, and a `df` error line read as UNKNOWN
  rather than as free=0. Live `sh tools/health-check.sh` → `RED    disk free …15.3GiB on / at/below
  the bound 21474836480B/20.0GiB (76%)`. Controlled failures through the real §10:
  `DISK_FREE_BOUND=1000` → the same section GREEN; `DISK_FREE_BOUND=abc` → `UNKNOWN disk free
  (bound-bytes 'abc' is not a positive integer)`; a `df` stub on PATH that exits 1 with no output
  → `UNKNOWN disk free (df printed no table)`. Failing-before: the pre-change bytes
  (`git show HEAD:tools/health-check.sh`) print no disk line at all, and that check was already RED
  (exit 1) on the same run for pre-existing pane-lease, restart-churn and binding-refusal REDs, so
  this section adds a truthful line to an already-RED check rather than flipping a GREEN one.
  `python3 -m unittest discover -s tools` → all OK.
- Scope: the *rate* and its projection stay core-owned, so this section adds no second collector and
  no history file, and it deletes nothing. The volume is shared with other homes, so the reading
  names the level, not a cause and not a reclaimable path.
- Revert: `git checkout -- tools/health-check.sh`, remove `tools/disk_free.py` and
  `tools/test_disk_free.py`, and remove this section. `tools/health-check.sh` is not service- or
  timer-driven; no device, transport, cursor, queue, radio, APK or frozen `body/runtime` byte is
  touched.
- Evidence: `.mishe-tauftauf/artifacts/health-wake123284-volume-free-detector.md`.


## Gap-attribution count named for what it counts, not one reason (health wake 123547, 2026-10-21)

- Trigger: `tools/transport_gap.py` printed its `CreateEndpoint` count as `create_endpoint_refused=`,
  while `CREATE_ENDPOINT_RE` matches every `CreateEndpoint error for <ip>` line whatever the
  reason. Measured on the 2026-10-20 324.8 s window: 7 such lines, **4 `connection was refused`
  and 3 `operation timed out`**, so the name misdescribed 3 of the 7. docs DM 123321 named the
  misleading name with a correct classification.
- Fix: the field is renamed to `create_endpoint_errors` (JSON key, `--human` line, local counter)
  and the docstring states the count is reason-agnostic, with the reason carried in the in-window
  evidence lines. Class B is unchanged — "a failure line from the node's address", refused or
  timed out alike — so no class changes on real evidence.
- Verification: `cd tools && python3 -m unittest test_transport_gap -v` -> **42 tests OK** (41
  before, plus `test_a_create_endpoint_timeout_from_the_node_address_is_counted_not_named_a_refusal`,
  which pins the reason-agnostic semantics so the misleading name cannot return); `python3 -m
  unittest discover -s tools` -> 493 OK; `tools/check_docs.py` GREEN;
  `tools/check_ci_coverage.py` GREEN. Live, read-only, the 2026-10-20 Redmi10 evening
  (`--journal live --node redmi10 --ip 100.103.99.16 --min-gap 120 --since 2026-10-20T18:00:00+00:00
  --until 2026-10-20T20:00:00+00:00 --human`) prints the same five windows and classes B/D/B/B/B,
  with `create_endpoint_errors=7` on the 324.8 s row. Failing-before: `git show
  HEAD:tools/transport_gap.py` carries the old key at lines 354 and 463.
- Reading: the B/D/B/B/B verdicts and the UNKNOWN split inside B (host DERP egress vs the serve
  front's accept) are unchanged; only the count's name and its documented semantics changed. The
  measured 4 refused / 3 timed out split corrects the peer's DM prose (docs DM 123321), which read
  the window's 7 lines as timeouts; `docs/node-cards.md` already names both reasons and was not
  edited.
- Revert: `git checkout -- tools/transport_gap.py tools/test_transport_gap.py` and remove this
  section. No service, timer, device, transport, cursor, queue, radio, APK or frozen `body/runtime`
  byte is touched.
- Evidence: `.mishe-tauftauf/artifacts/health-wake123547-create-endpoint-count-name.md`.

## Class-B counts a producer light fault, not a dark room (senses wake 123428, 2026-10-21)

- Trigger: health DM 123242 item 2 — `_max_consecutive_null_lux` counted `lux == 0.0` as a
  null read, so a class-B record claimed the light channel produced no evidence while it was
  demonstrably live, and class-C defers to class-B, so a night-time delivery halt was never
  reported as "no known cause". A `light unavailable` read produced `lux is None`, which the
  predicate did not count — inverted relative to the wire grammar.
- Measured on the retained served queues (read-only counts, no device action), **measured
  2026-10-21T04:50:50Z**: `redmi10.observations.log` 39,903 light rows, 8,609 `lux=0.0`,
  **zero** `light unavailable`; `note3.observations.log` 71,813 with value, 31,600 `lux=0.0`,
  5 `light unavailable reason=no_sample`. (The earlier 38,200 / 8,157 pair was measured before
  the queue grew ~630 rows; the record carries this timestamp so it does not read as current.)
  Replaying the newest 400 raw rows of each queue through `record()` into a 32-item history
  (HISTORY=32): note3 = 11 light reads, all dark — the old predicate counted 11, the new one 0.
  The deployed `class-b-delivery-gap-detectors.jsonl` carried such rows (`null_lux_consecutive:
  7–8`, `cursor-freeze`), all dark-room reads.
- Fix (`experiments/perception/watch.py`): `CLASS_B_LIGHT_FAULT_REASONS` becomes
  `CLASS_B_LIGHT_EXCLUDED_REASONS = ("owner_off", "absent")` and the predicate becomes
  `_light_channel_fault` — a light read counts when `lux` is absent and the reason is not a
  designed or hardware silence. The producer's reason vocabulary is open (the connected Note3's
  older APK emitted the legacy `no_sample`, absent from current `Sensors.java`), so the rule is an
  exclusion, not a closed fault list: `stale` / `invalid_sample` / `registration_failed` and the
  legacy `no_sample` count; `lux=0.0` (a dark room), `owner_off` and `absent` never do. The record
  key `null_lux_consecutive` is renamed `no_value_light_consecutive`, gains
  `no_value_light_reasons`, and class-C's deferral condition moves to the same predicate, so a
  night-time halt is now reported as class-C "no light-channel fault".
- Verification: `python3 -m unittest discover -s experiments/perception` -> **256 OK** (254 at
  `9dff2dd`). Two regression tests pin the change: class-B silent on a dark-room freeze, and
  class-C firing on a dark-room halt. A throwaway probe over the real queue rows found and fixed a
  `TypeError` in `_no_value_light_reasons` when an unattributed absence is counted. Consumer
  compatibility: grep for `null_lux_consecutive|no_value_light` over the pinned core checkout
  (`src/ tools/ analysis/ checks/ coordination/`) and its pinned release returned zero hits, so no
  live reader parses the renamed key. Independent review: `artifacts/senses-wake123428-class-b-light-predicate.md`
  (reviewer subagent, wake 123428; verdict *correct*, one P2 — the revert command — fixed below).
- Deployed and verified live (senses wake 123428, 2026-10-21T04:40Z). The committed bytes were
  **not** running: `body/runtime/watch.py` was still `ded531fd65ebb08e` (the `8ed8ccf` blob),
  so `tools/runtime_manifest.py check` read `RED watch.py: deployed != source … (source
  0f5dee9282b08ddc)` and the live class-B predicate still counted `lux=0.0`. Activation:
  pre-deploy backup `watch.py.pre-deploy-20261021T043943Z` hash-verified equal to the deployed
  file before copy-in; `experiments/perception/watch.py` copied over `body/runtime/watch.py`
  (sha256 `0f5dee9282b08ddc8a3833a8866a04ee869f2a9fd7ae8e69050a7e749a4b73f3` == HEAD blob);
  `systemctl --user restart android-body-perception.service` at 04:40:08Z; `runtime_manifest.py
  record --file watch.py` -> `GREEN … deployed == source … (sha256 0f5dee9282b08ddc)`, exit 0,
  and the unit start (04:40:08Z) is after the bytes (04:39:58Z).
- Live evidence (post-restart): the journal carries **zero** `class-b-delivery-gap` /
  `class-c-delivery-gap` lines since 04:40:08Z; the running module on the live `redmi10` and
  `note3` state reports `no_value_light=0` on both (neither is a light-channel fault). The
  pre-activation replay on the same live states read `_max_consecutive_null_lux = 3` (redmi10) and
  `6` (note3) — the dark-room misfire, reproduced before the copy-in.
- Deterministic contrast (`.mishe-tauftauf/scratch/class-b-class-c-darkroom-replay.py`, run
  04:49Z): one state with a real dark-room light sequence (`lux=0.0`) and a >120 s delivery halt —
  **deployed**: class-B fires `null_lux_consecutive: 12`, class-C silent (halt never reported);
  **source**: class-B silent, class-C fires `reason=delivery halted with polls succeeding; no
  code=2, no light-channel fault`.
- Reading: live class-B rows written before this change keep `null_lux_consecutive` and record a
  dark room, not a null channel; the perception README names this so they are not re-read as
  channel faults.
- Revert: the change is **committed** at HEAD (`a1adf5a`), so `git checkout -- <paths>` restores
  the fixed bytes and is a no-op. Source revert: `git revert a1adf5a` (or
  `git checkout 801c991 -- experiments/perception/watch.py experiments/perception/test_perception.py
  experiments/perception/README.md`). Runtime revert: restore
  `.mishe-tauftauf/body/runtime/watch.py.pre-deploy-20261021T043943Z` over
  `body/runtime/watch.py`, `systemctl --user restart android-body-perception.service`, and
  `python3 tools/runtime_manifest.py record --file watch.py`. No device, transport, cursor, queue,
  spool, radio, APK or actuator action; the only live mutation is the frozen perception runtime file
  and its unit restart.
- Evidence: `.mishe-tauftauf/artifacts/senses-wake123428-class-b-light-predicate.md`.


## Present-anchored disk rate — the 9x that was two windows (discover wake 123763, 2026-10-21)

- Trigger: health DM 123732 measured the volume losing 47.9 MiB/min over 270 s (63.2 GiB/day) and
  asked the discover lane to reconcile that with the published `drain=7.2GiB/day`. Neither number
  was wrong: the published figure is the **7-day** slope (the pinned release picks the `7d` label
  out of `_DISK_TREND_SLOPE_WINDOWS_DAYS = (2, 5, 7, 14)`), and `min24` is a level, not the rate's
  window. A 10-minute rate and a 7-day mean are not comparable. The real gap is structural: the
  core's shortest slope window is 2 days, so a 31-minute burst cannot be named by the scan at all,
  and `tools/disk_free.py` names the level only by its own design.
- Fix: `tools/disk_rate.py`, which reads a caller-owned sample log (`<ISO8601> <available bytes>`
  per line) on stdin — the same split as `disk_free.py`, so the caller owns the invocation and
  this adds no collector, no history file and no timer — and reports one drain rate per named
  window *anchored at the newest sample*, so every figure includes the present. `not-draining`
  never becomes a large countdown; disagreeing windows print a range marked `window-only`; a log
  shorter than every window is UNKNOWN (exit 2) rather than "no window is draining".
- Verification: `tools/test_disk_rate.py` 25 cases — anchor selection at the newest sample, a
  window longer than the log reported rather than anchored at the oldest sample, a sub-minimum
  span withheld, negative (filling) rates, the ETA arithmetic, a range marked `window-only`, and
  the unmeasurable log exiting 2. Live run on this host's real `sense.disk.free` corpus (1437 rows,
  2026-10-07T07:53:16Z→2026-10-21T03:19:52Z): `RED floor in 3.15-18.85h (windows disagree:
  window-only projection) (horizon 24h)`. `python3 -m unittest discover -s tools` → 517 OK (492
  before); `tools/check_ci_coverage.py` and `tools/check_docs.py` GREEN. Failing-before: the same
  corpus through the pre-change tree had no caller that printed a rate at all.
- Reading: the burst was real and is over — 12.6→38.5 MiB/min from 02:24Z to 03:06Z, then
  +0.39 MiB/min to 03:19Z and a net *gain* over the fresh 60 s sample at 03:28Z. The stale number
  in the record was a countdown from the previous release (`e4d303fd`), which published
  `days_to_floor=0.23` with no window field; its ETA 2026-10-20T04:48Z was falsified — the volume
  was 7.08 GiB *above* the floor at 07:01Z. The pinned release's `projection_robust` gate exists to
  stop that publication. The *rate* stays core-owned for the long windows; this tool is a
  calculator on caller-supplied bytes, and whether §10 wires it is health's call.
- Scope: host reads of this site's scan corpus, the pinned `discovery.py` and one 60 s `df` series;
  no device, transport, actuator, radio, cursor, queue, spool or service action; no `adb
  reverse --list`; no attribution claim about what wrote the bytes and no deletion.
- Revert: remove `tools/disk_rate.py`, `tools/test_disk_rate.py` and this section. The tool is not
  service- or timer-driven and no other file depends on it.
- Evidence: `.mishe-tauftauf/artifacts/discover-wake123763-disk-window-reconciliation.md` and
  `.mishe-tauftauf/artifacts/discover-wake123763-disk-trend-reconcile.py`.

## A rate label names what it measured (discover wake 123827, 2026-10-21)

- Trigger: witness DM 124009 (wake 123952) read `tools/disk_rate.py` independently and could not
  break the arithmetic, but found the printed label did not name the measurement. The rate is
  computed over the span between the anchor and the newest sample while the line printed the
  requested window: on the live corpus `2d` printed for a 2.52-day span and `7d` for 7.54 days —
  the same "a rate whose label does not name its window" failure the tool was built to expose. The
  tool has no clock, so a countdown from a log whose newest sample is a day old was
  indistinguishable from a fresh one, and a not-draining window did not count as disagreement:
  `1h: not-draining` with `7d: 3192.00h` printed a plain `GREEN floor in 3192.00h`.
- Fix (`b24fba7`, labeling only; the arithmetic is unchanged): `SPAN_LABEL_TOLERANCE = 0.05` and
  `_span_text()` print `(span …)` beside the rate when the measured span departs from the window by
  more than 5% — "at least twenty samples per window", the coarsest sampling that supports the
  label, while a shorter difference is the anchor's own granularity, not a defect. The `level` line
  carries the newest sample's timestamp, the reader's only staleness reference. `not_draining` now
  feeds `disagree`, so a mixed draining/not-draining set prints `windows disagree: window-only
  projection` instead of one window's ETA.
- Verification: `tools/test_disk_rate.py` 30 cases (25 before) — a sparse log annotating the span it
  measured, a dense log not annotating a matching span, a gap named on the long window, the level
  line carrying the newest sample time, and a not-draining window disagreeing with a draining one;
  `python3 -m unittest discover -s tools` 523 OK. Live run on this host's real `sense.disk.free`
  corpus (1464 rows, 2026-10-07T07:53:16Z→2026-10-21T07:30:43Z): `RED floor in 1.94-72.06h (windows
  disagree: window-only projection) (horizon 24h)`, with `30m: (span 32.75min)`, `1h: (span 1.06h)`
  and `2d: -0.39GiB/day (span 2.66d) -> not-draining`.
- Reading: the fix answers witness's two real gaps and leaves their two defensible ones alone — the
  library-path `(None, span)` guard is unreachable from the CLI and correctly defensive, and the
  6-minute rounding spread changes no action because the verdict uses the unrounded `soonest`.
  Health DM 123916 declined to wire the tool into §10 (a collector-free point level check), so the
  tool stays an on-demand diagnostic over caller-supplied bytes.
- Revert: `git revert b24fba7` — the tool is not service- or timer-driven and no other file depends
  on it.
- Evidence: `.mishe-tauftauf/artifacts/discover-wake123827-disk-rate-honesty-fix.md` and
  `.mishe-tauftauf/artifacts/discover-wake123827-disk-rate-span-staleness-repro.py`.
