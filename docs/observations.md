# Observations

Every line begins with phone Unix seconds. See the [protocol](../protocol/README.md) for queue prefixes and delivery semantics.

## First milestone

- `battery level=0.73 charging=true`: fraction in [0,1] from `ACTION_BATTERY_CHANGED`. Unavailable fields are `unknown`; charging is true for charging/full, false for discharging/not-charging, otherwise unknown. The latest system battery state is repeated.
- `light lux=82.0 accuracy=3 age_ms=21`: latest actual TYPE_LIGHT event in lux. Some devices do not have an ambient-light sensor. If no event arrived, registration failed or the value is invalid, report unavailable. After 60 seconds without a sample, conservatively mark stale; on-change sensors may be stable rather than broken.
- `acceleration x=0.12 y=-0.08 z=9.71 accuracy=3 age_ms=34`: device-coordinate acceleration in m/s², including gravity. This is not inferred movement, velocity, orientation or linear acceleration. Values are actual TYPE_ACCELEROMETER samples. After 15 seconds without an event, mark stale.

Sensors register at Android's normal sampling rate. A dedicated sampler durably saves snapshots approximately five seconds apart, independently of network timeouts/backoff. This is not a raw high-rate stream. `accuracy` is the Android event's reported integer (commonly -1/0/1/2/3); it is not a calibrated error estimate. Nonfinite/negative lux and nonfinite accelerometer values are rejected. Old or future-inconsistent sample clocks become unavailable.

Missing hardware is announced at hello and appears as `unavailable reason=absent` in snapshots. Other reasons include `no_sample`, `stale`, `invalid_sample` and `registration_failed`. Null/failed APIs never create substitute physical readings.

All sensor values are device-dependent. Mounting, gravity, calibration, occlusion, sensor privacy settings, screen suspension and OEM power management matter. Foreground service and the ON-only CPU wake lock are not a promise of continuous samples, especially in Doze or after an OEM process kill. Consumer logic should check freshness/capability and tolerate gaps and duplicate observations. Durable backlog preserves collection timestamps; age_ms is the sample age at collection and does not include time waiting to upload.

## Deployed beyond first milestone

- `wifi_link_rssi_dbm=-13 source=androidbody_wifi_api observed_at=1791685327`: RSSI of the currently connected Wi-Fi link in dBm, read through the platform Wi-Fi API. `observed_at` is when the app read the API, not the RSSI measurement time; measurement age is unknown. Not a scan, a network identity, a distance or an occupancy measure. Disconnected/invalid/read-failure outcomes use `wifi_link_rssi_dbm unavailable reason=...`.
- `ble_status source=androidbody_bluetooth_api api=21 api_surface=platform_sdk feature_ble=present adapter=enabled scanner_api=present advertiser_api=present scanner_getter=returned advertiser_getter=null advertiser_supported=unsupported`: read-only `BluetoothAdapter` capability snapshot at startup. `scanner_getter`/`advertiser_getter` record whether the API21 scanner/advertiser getters returned; they are not radio, scan or advertisement results and never toggle Bluetooth. API<21 and null-adapter outcomes report `unavailable`.
- `probe identity uid=10224 groups=3002 3003 9997 50224`: read-only identity of the APK process (uid plus Linux supplementary groups from `/proc/self/status`, bounded to 4096 bytes), emitted within the hello `session`. It attributes session-scoped probes to the app UID; it executes nothing.
- `sensor_time_ns=23707107773680`: raw monotonic `SensorEvent.timestamp` on light/acceleration samples, preserved alongside the phone wall-clock time. Compare only within the same sensor and hello `session`; not Unix time or a receipt time.

## Not implemented

Location, proximity, gyroscope, microphone amplitude, camera capture, orientation inference and raw audio/images remain future work. No permissions for those sources are requested. Add a new boundary only with real-device tests, privacy review and explicit unavailable/error semantics.

## Saved observations and later upload

Collect-only mode keeps the foreground notification and sampler but makes no new HTTP requests or remote actions. Uncheck it while ON to send that endpoint's retained backlog. OFF stops collection without deleting saved observations. Every endpoint has a separate bounded queue; changing configuration never reroutes old data.

At three sensor lines every five seconds, the default 2 MiB / 24,576-line bound retains roughly 10 hours at representative 80-byte records. Shorter records can approach 11.4 hours; wider records and action/startup traffic reduce that. Retention is bounded by bytes/lines, not a promised time window.

Overflow is explicit (`spool overflow dropped=N policy=oldest`). Interrupted journal writes may produce `spool recovery reason=incomplete_write loss=unknown`; complete corruption stops collection until resolved or explicitly deleted. Read the [delivery and retention contract](../protocol/README.md#delivery-collection-and-restart-semantics) before treating the stream as historical evidence.
