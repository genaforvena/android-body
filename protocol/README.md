# Android Body text protocol, version 1

A phone observes and requests effects through Android APIs. An arbitrary program reasons outside it. HTTP is the replaceable rendezvous boundary. There is no agent, remote shell, model, plugin loader, account or Mishe-specific field here.

## Node and authentication

Configure a node base URL, for example `https://body.example/node/note3`, and one per-node shared secret. Node IDs match `[a-z0-9][a-z0-9_-]{0,63}`. The Android app removes one trailing slash. No URL credentials, query or fragment are allowed. The server must provision the same node and secret.

All four routes require `Authorization: Bearer SECRET`. Secrets match `[A-Za-z0-9._~-]{32,256}`; generate with `python3 -c 'import secrets; print(secrets.token_urlsafe(32))'`. The MVP's same secret can read observations and enqueue actions. Anyone with it can vibrate the phone while ON. There are no separate observer/controller roles.

Use HTTPS with valid certificates. Redirects are never followed by the app. Cleartext HTTP requires explicit opt-in in the app and, when remotely bound, the example server. HTTP transmits both observations and the secret unencrypted. Never expose that mode to the public Internet.

## Routes

| Request | Actor | Body or result |
|---|---|---|
| `POST /node/ID/observations` | Phone | Original observation lines |
| `GET /node/ID/observations?after=N` | Consumer | `sequence original-observation` lines |
| `POST /node/ID/actions` | Consumer | Commands without sequence IDs |
| `GET /node/ID/actions?after=N` | Phone | `sequence command` lines |

Request and response bodies are UTF-8 `text/plain`. No JSON envelope. LF delimits lines; a final LF is allowed. The Android GET parser tolerates CRLF; producers should send LF. Empty GET response means no new records. An empty POST or blank interior line is invalid.

Successful POST: HTTP **201**, with one assigned positive sequence ID per line, in the same order as submitted. Example response `21\n22\n`. Successful GET: HTTP **200**. Read headers `X-Last-Sequence` (last record returned, or requested cursor) and `X-Has-More` (`0` or `1`) are conveniences; parsing the returned IDs is sufficient.

There are two independent append-only queues per node. IDs begin at 1, strictly increase and fit within `1..9007199254740991`. `after` is exclusive, beginning at 0. Store a cursor independently for each queue and node. Consumers must not interpret an observation ID as an action ID.

Limits: 65,536 bytes per request/response, 128 records per POST/read page, 1,007 UTF-8 bytes per submitted line, 1,024 bytes per returned line including its ID prefix. No control characters inside lines. Android validates the whole action response, IDs and limits before executing any command in it. Unsupported commands with valid IDs get a failed outcome and are consumed; malformed envelopes pause uploads/actions while local collection continues.

No long polling, inbound port, WebSocket or MQTT is required. The phone polls about every two seconds when idle. Network errors use exponential retry (2–60 seconds plus jitter). It refreshes observations about every five seconds independently of connectivity, while Android schedules the app.

## Example exchange

Phone POST body:

```text
1712345678 hello node=note3 protocol=1 session=82ab62fb-a644-419a-9065-0edab5c8fe6b
1712345678 android sdk=19
1712345678 cap battery
1712345678 cap light
1712345678 cap accelerometer
1712345678 cap vibration
1712345679 battery level=0.73 charging=true
1712345679 light lux=82.0 accuracy=3 age_ms=21
1712345679 acceleration x=0.12 y=-0.08 z=9.71 accuracy=3 age_ms=34
```

Consumer enqueues:

```text
vibrate duration=200
```

Server assigns `812`. Phone GET body:

```text
812 vibrate duration=200
```

Subsequent observations:

```text
1712345680 action 812 requested kind=vibrate duration=200
1712345680 action 812 succeeded kind=vibrate duration=200 evidence=api_return verification=unverified
```

`api_return` means the Android request returned without throwing. It does **not** prove the motor ran, that someone felt it, or that the device moved. DND, hardware, firmware and Android policy may suppress it. Physical verification requires independent evidence and belongs to the consumer or test operator.

## Unknown, absence and failure

```text
1712345678 sensor light absent
1712345678 actuator vibration absent
1712345679 light unavailable reason=no_sample
1712345680 acceleration unavailable reason=stale
1712345680 battery level=unknown charging=unknown
1712345681 action 812 failed reason=rate_limited
1712345682 action 813 unknown reason=interrupted verification=unverified
```

The app advertises only implemented hardware capabilities, not every Android API. `cap` reports hardware/API availability, not permission, freshness, reliability or proof of future success. Consumers must tolerate unknown event names and added key/value fields; an action command is deliberately parsed strictly. Never substitute zero for absent data.

The current-link Wi-Fi RSSI observation uses `wifi_link_rssi_dbm=<signed dBm> source=androidbody_wifi_api observed_at=<phone Unix seconds>`. `observed_at` is when the app read the Android Wi-Fi API, not a timestamp supplied for the underlying RSSI measurement; its measurement age is unknown. Consumer receipt time is separate. Disconnected, invalid, and read-failure outcomes retain the same field name as `unavailable`, with a reason and the API-read observation time. No network identity or scan result is included.

Times are integer Unix seconds according to the phone's wall clock. They are not server receipt times, synchronized clocks or ordering authorities. `age_ms` uses Android's elapsed real-time clock; sensor sample timestamps are mapped to approximate wall time when collected. Queue IDs, not timestamps, order records within one queue. `session` changes each ON session and contains no hardware identifier.
For light and acceleration sample records, `sensor_time_ns` preserves the raw decimal `SensorEvent.timestamp` in nanoseconds (a nonnegative signed 64-bit value). It is an Android monotonic event timestamp, not Unix time or a receipt time. Consumers may compare only records for the same sensor and the same hello `session`; missing/out-of-range timestamps or missing sessions are incomparable. A session partitions ON sessions but does not prove boot identity. This field does not change existing wall-time or `age_ms` freshness behavior.

The read-only BLE capability snapshot uses `ble_status source=androidbody_bluetooth_api api=<SDK_INT> api_surface=platform_sdk feature_ble=<present|absent|query_error> adapter=<enabled|disabled|unavailable|error> scanner_api=<present|unavailable|error> advertiser_api=<present|unavailable|error> scanner_getter=<returned|null|error|unavailable> advertiser_getter=<returned|null|error|unavailable> advertiser_supported=<supported|unsupported|error|unavailable>`. It records `BluetoothAdapter` state and whether the API21 scanner/advertiser getters returned; it never scans, advertises, toggles Bluetooth or produces an RF result. API<21 and null-adapter outcomes report `unavailable`.

The read-only process identity probe uses `probe identity uid=<uid> groups=<space-separated gid list|none>`, read from `/proc/self/status` (bounded to 4096 bytes) within the hello `session`. It attributes session-scoped probes to the app UID; it executes nothing.

## Delivery, collection and restart semantics

The wire protocol remains version 1. App version 0.2 adds durable local collection and persistent ON without changing the HTTP endpoints.

- A dedicated sampler saves battery/light/acceleration snapshots roughly every five seconds while Android schedules the app. Network timeouts and retry sleeps do not pause that sampler. Raw sensor events are still coalesced into snapshots; this is not a high-rate recorder and OS/process gaps are not backfilled with invented data.
- Each normalized endpoint owns a private durable observation queue and its own action cursor. Changing endpoints never sends the previous node's backlog to the new destination. Secret rotation at the same endpoint retains that node's queue/cursor. Return to the old endpoint to drain its backlog, or explicitly delete that node's saved observations while OFF.
- Normal enqueue and acknowledgment append and fsync small checksummed journal transactions. Periodic atomic compaction bounds storage; it does not rewrite the retained buffer on every sample. The logical queue is bounded by 2 MiB and 24,576 lines; the committed journal is bounded by 4 MiB, with at most another 2 MiB temporary compaction file. The app permits eight saved endpoint directories, for at most 48 MiB of queue files including stale temporary copies, plus small configuration/lock files. At the default three sensor lines every five seconds, representative 80-byte records retain roughly 10 hours; shorter lines can approach the 24,576-line ceiling of 11.4 hours. Larger lines and action/startup records reduce retention. This is an approximate overnight-sized buffer, not a duration or lossless-history guarantee.
- Overflow keeps newest records, evicts oldest locally, and persists `TIME spool overflow dropped=N policy=oldest`. `N` is the cumulative local eviction count. A batch already in flight may still arrive, so an eviction is not proof that its upstream copy is missing. Ordinary samples and action results share these bounds; no unlimited retention is implied.
- A torn final journal transaction is recovered only to its validated prefix and produces `TIME spool recovery reason=incomplete_write loss=unknown`. Complete checksum/format corruption fails closed. Local storage failure stops and disarms the session; it is never disguised as a network outage. The user can explicitly delete a corrupt node queue while OFF without resetting its action cursor.
- **Collect only / upload later** keeps the same visible foreground session and durable sampler, but issues no new HTTP requests or remote actions. A real endpoint and secret are configured first to give the stored data an unambiguous destination. Unchecking while ON drains that node's backlog and resumes action polling. Previously unconsumed queued vibration commands may then run. A request already in flight when the mode changes cannot be recalled.
- Uploads have **at-least-once attempt semantics**. Only a validated 201 acknowledgment removes the batch's surviving prefix from local storage. Lost responses or a crash between server receipt and local acknowledgment can duplicate observations. Concurrent sampling/overflow cannot make an old acknowledgment remove newer records. Bounded overflow, storage failures and OS gaps mean this is not an exactly-once or lossless log.
- Observation timestamps and `age_ms` describe the snapshot at collection, not upload time. Backlog may arrive much later. In particular, `age_ms` does not include queue residence time. Consumers must reason about timestamps, clock skew and freshness before acting on delayed data.
- An action's cursor and pending-result marker are committed **before** the actuator call. Its outcome is then durably enqueued before that marker is cleared. On restoration, a remaining marker emits `unknown reason=interrupted`; the actuator is not repeated. A crash after durable outcome storage but before marker clearance can yield both the outcome and the conservative unknown. A crash between cursor commit and actuation can skip an effect. There is no retry of uncertain physical effects.
- The app drains pending observations/results before polling more actions. Unsupported, invalid-argument and rate-limited commands also advance the action cursor. On a server reset, a cursor ahead of the log head receives 409; uploading/action polling pauses while local collection continues. Reconcile the server before explicitly resetting the cursor. Resetting may replay historical effects.
- **ON is persistent intent.** Android is asked to recreate the foreground service with `START_STICKY`; eligible boot-after-unlock and package-update broadcasts restore a saved ON session. This is permission to restore, not a claim that Xiaomi/Android will keep the process alive. A fresh install and saved OFF never auto-enable. Restore requires matching endpoint state and allowed notifications. See [Android/OEM limits](../docs/compatibility.md#restoring-an-enabled-session).
- **OFF disarms before stopping.** It removes a separate enable marker and clears the desired-ON preference, then unregisters sensors, cancels vibration/network work and releases the CPU wake lock. Saved observations remain for later. An in-flight request may already have reached the server; final OFF or cancellation delivery is not guaranteed. If both durable disarm mechanisms fail, the app stops now and explicitly tells the user to use Android Force stop before reboot.
- The notification distinguishes sending/connected, offline collection, upload-paused and collect-only states; updates are coalesced to at most once every two seconds. Its OFF action disarms restoration. On Android versions that let users dismiss an ongoing notice, the delete action also requests OFF; no unhideable-notification claim is made. Notification visibility checks on API18–23 remain limited by the platform.
- Android Force stop and manufacturer restrictions are not bypassed. On API30+, a newer `USER_REQUESTED` process-exit record conservatively disarms restoration; on older releases this evidence is unavailable, and on API30–33 it can also describe updates. Opening a paused app does not itself start sensing; switch OFF then ON to resume. Clearing app data/uninstalling removes credentials, queues and cursors, potentially exposing old server commands on reconfiguration. Backups/device transfer are excluded.

The example rendezvous never prunes silently. Queue-full 507, non-retryable client errors (including 401/409), redirects and malformed responses pause uploads/actions while the phone keeps collecting locally. Resolve the problem, then switch OFF/ON or change collection mode to retry. Network/TLS errors and transient server errors (including 503 storage quarantine) use bounded exponential retries while sampling continues. A local storage failure instead stops the session and reports a visible error; there is no safe durable collection without writable storage.

## Boundaries

No request can evaluate code, open arbitrary URLs, start an intent, access files or issue shell commands. Version 1 implements only `vibrate duration=N`, where `1 <= N <= 2000` milliseconds and accepted vibrations are at least three seconds apart. The endpoint is authoritative, not safe: keep its secret private and turn OFF before moving a phone into a sensitive environment.
