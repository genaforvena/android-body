# Observations

Every line begins with phone Unix seconds. See the [protocol](../protocol/README.md) for queue prefixes and delivery semantics.

## First milestone

- `battery level=0.73 charging=true`: fraction in [0,1] from `ACTION_BATTERY_CHANGED`. Unavailable fields are `unknown`; charging is true for charging/full, false for discharging/not-charging, otherwise unknown. The latest system battery state is repeated.
- `light lux=82.0 accuracy=3 age_ms=21`: latest actual TYPE_LIGHT event in lux. Some devices do not have an ambient-light sensor. If no event arrived, registration failed or the value is invalid, report unavailable. After 60 seconds without a sample, conservatively mark stale; on-change sensors may be stable rather than broken.
- `acceleration x=0.12 y=-0.08 z=9.71 accuracy=3 age_ms=34`: device-coordinate acceleration in m/s², including gravity. This is not inferred movement, velocity, orientation or linear acceleration. Values are actual TYPE_ACCELEROMETER samples. After 15 seconds without an event, mark stale.
- Note3 current device state: resting acceleration magnitude reads ~1.05×g since a discrete step at 2026-10-13T00:16:05Z phone time (15.93→10.24 m/s², coinciding with freeze #6 resolution and new session `f8bddad5`); a prior discrete step at 2026-10-11T03:14:41Z had raised it from 10.21→15.93 m/s² (~1.6×g). Both steps' causes UNKNOWN. The channel still responds to movement — prefer change detection over absolute-magnitude thresholds on this device.

Sensors register at Android's normal sampling rate. A dedicated sampler durably saves snapshots approximately five seconds apart, independently of network timeouts/backoff. This is not a raw high-rate stream. `accuracy` is the Android event's reported integer (commonly -1/0/1/2/3); it is not a calibrated error estimate. Nonfinite/negative lux and nonfinite accelerometer values are rejected. Old or future-inconsistent sample clocks become unavailable.

Missing hardware is announced at hello and appears as `unavailable reason=absent` in snapshots. Other reasons include `no_sample`, `stale`, `invalid_sample` and `registration_failed`. Null/failed APIs never create substitute physical readings.
- A `stale` row carries `age_ms=<elapsed ms between the last real event and collection>`: the phone-side silence measure, since `now - received` on a stale row is only poll/receipt latency. A consumer derives the last-event phone-wall epoch as `collected - age_ms/1000`; absolute silence length additionally needs phone/host clock agreement (see `sensor_time_ns`/`phone_elapsed_ms` provenance).

All sensor values are device-dependent. Mounting, gravity, calibration, occlusion, sensor privacy settings, screen suspension and OEM power management matter. Foreground service and the ON-only CPU wake lock are not a promise of continuous samples, especially in Doze or after an OEM process kill. Consumer logic should check freshness/capability and tolerate gaps and duplicate observations. Durable backlog preserves collection timestamps; age_ms is the sample age at collection and does not include time waiting to upload.

## Deployed beyond first milestone

- `wifi_link_rssi_dbm=-13 source=androidbody_wifi_api observed_at=1791685327`: RSSI of the currently connected Wi-Fi link in dBm, read through the platform Wi-Fi API. `observed_at` is when the app read the API, not the RSSI measurement time; measurement age is unknown. Not a scan, a network identity, a distance or an occupancy measure. Disconnected/invalid/read-failure outcomes use `wifi_link_rssi_dbm unavailable reason=...`.
- `ble_status source=androidbody_bluetooth_api api=21 api_surface=platform_sdk feature_ble=present adapter=enabled scanner_api=present advertiser_api=present scanner_getter=returned advertiser_getter=null advertiser_supported=unsupported`: read-only `BluetoothAdapter` capability snapshot at startup. `scanner_getter`/`advertiser_getter` record whether the API21 scanner/advertiser getters returned; they are not radio, scan or advertisement results and never toggle Bluetooth. API<21 and null-adapter outcomes report `unavailable`.
- `probe identity uid=10225 groups=3001 3002 3003 9997 50225`: read-only identity of the APK process (uid plus Linux supplementary groups from `/proc/self/status`, bounded to 4096 bytes), emitted within the hello `session`. It attributes session-scoped probes to the app UID; it executes nothing.
- `sensor_time_ns=23707107773680`: raw monotonic `SensorEvent.timestamp` on light/acceleration samples, preserved alongside the phone wall-clock time. Compare only within the same sensor and hello `session`; not Unix time or a receipt time.
- `phone_elapsed_ms=123456789`: monotonic `SystemClock.elapsedRealtime()` in milliseconds at observation time, on light, acceleration and Wi-Fi link RSSI records (protocol v2). Not Unix time, not a host-clock quantity; deltas are meaningful only within one hello `session`. Protocol v1 records omit it; consumers must tolerate its absence.
- `ble_scan start beacon=MISHE-BEACON window_ms=60000 gap_ms=60000`, `ble_scan stop reason=session_end`, `ble_scan error reason=<cause>`, `ble_scan unavailable reason=<cause>`: bounded BLE scan lifecycle while ON, emitted at session start, session end, or on scanner error/absence. `ble_sighting name=MISHE-BEACON rssi=<dBm>` records a scanner-visible allowlisted beacon only. Scanner-visible evidence, not presence, occupancy or proximity; no RF conclusion without a sighting.
- `owner_checkboxes battery=on light=on acceleration=on vibration=on`: the phone's local owner-enablement state for each sense, emitted in the hello `session`. It reports local choices; remote text cannot change it.

## Note3 hardware inventory (witnessed 2026-10-12)

A read-only `dumpsys sensorservice` survey of the installed Note3 lists physical sensors: acceleration and gyroscope (MPU6500), magnetic field (AK09911C), barometer (LPS25H), proximity and RGB light (MAX88922), humidity and temperature (SHTC1), step detector, step counter and significant motion (Samsung), and rotation vector (MPL), plus derived gravity, linear-acceleration and orientation sensors. The proximity channel is on-change and wake-up capable and was reading 0.0 (near) at survey time. This is witnessed hardware evidence about this one unit, not a protocol guarantee; other devices differ. See [compatibility](compatibility.md) for validation scope.

## Not implemented

Proximity and gyroscope hardware is present on the Note3 (inventory above); they are not emitted. Location, microphone amplitude, camera capture, orientation inference and raw audio/images are not implemented and no permissions for them are requested; the 2026-10-07 node-cards mandate makes their expansion a requested programme — capability by capability, local owner checkboxes, human-readable text; remote text cannot enable. Add a new boundary only with real-device tests, privacy review and explicit unavailable/error semantics.

## Saved observations and later upload

Collect-only mode keeps the foreground notification and sampler but makes no new HTTP requests or remote actions. Uncheck it while ON to send that endpoint's retained backlog. OFF stops collection without deleting saved observations. Every endpoint has a separate bounded queue; changing configuration never reroutes old data.

At the shipped five lines every five seconds, the 2 MiB byte bound holds roughly 14,500 of the deployed APK's ~130-byte records — about four hours — and the 24,576-line ceiling would allow ~6.8 hours. The Note3 measured 4.4 hours / 15,756 rows after compaction and 6.6 hours / 25,256 rows before it (2026-10-15); the journal keeps evicted frames until compaction, so a raw-file read can show more than the queue itself retains. Retention is bounded by bytes/lines, not a promised time window. Collect-only leaves the buffer saturated, so the cumulative `dropped` count grows at about the emission rate (~1 record/s on the Note3).

Overflow is explicit (`spool overflow dropped=N policy=oldest`). Interrupted journal writes may produce `spool recovery reason=incomplete_write loss=unknown`; complete corruption stops collection until resolved or explicitly deleted. Read the [delivery and retention contract](../protocol/README.md#delivery-collection-and-restart-semantics) before treating the stream as historical evidence.
