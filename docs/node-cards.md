# Node cards — owned Android bodies

Capability cards for the owned phones, per the 2026-10-07 node-cards mandate. They record
the shipped surface each installed build actually emits; the later 2026-10-07
minimal-substrate direction supersedes capability-card-first architecture as the plan. The
shared wire surface stays human-readable text; JSON is deliberately excluded. The
machine-readable observation layer is the perception consumer
(`body/perception/*.json` + the pane) owned by senses — humans read this file.

Each card states: implemented capability, local owner enablement, Android permission,
present availability, supported bounded text requests, limits. Declaration is not proof of
a working sensor. "Present availability" always carries its observation instant; staleness
is a property of the channel, never a silent default.

Last updated 2026-10-16 ~14:00Z by docs: Redmi10 installed-build bracket and
re-pointed update candidate, the BLE-grant requirement, and the Note3 class-4 install.
Availability stamps below are from the read-only deployed view at 13:53Z and can go stale.

## Note3 node card

Identity: note3 — stationary Samsung Galaxy Note 3, Android API 21 (`android sdk=21`),
plugged in over ADB to this host and reached through the loopback rendezvous bridge
(`http://127.0.0.1:8765/node/note3`). It is not a tailnet peer; it is a node over the ADB
transport, in the LTE Workstation junk-drawer-phone sense.

Implemented capabilities — five `cap` rows at session start (`cap battery`, `cap light`,
`cap accelerometer`, `cap wifi_link_rssi`, `cap vibration`), all `present`:

- battery — level fraction plus charging state.
- light — ambient lux; consumer buckets dark/faint/dim/moderate/bright for transitions.
- accelerometer — x/y/z in m/s² including gravity; magnitude is not motion proof.
- wifi_link_rssi — connected-link RSSI from the Android Wi-Fi API; not room proximity.
- vibration (actuator) — see bounded requests.

BLE is a per-cycle observation, not a `cap` row: the sampler emits `ble_status` (a
`BluetoothAdapter` snapshot) every five seconds, plus the bounded `ble_scan` lifecycle rows
and the per-cycle `ble_scan_state` row while scanning. Scan is bounded to the allowlisted
`MISHE-BEACON` only. The API-21 adapter reports `advertiser_supported=unsupported`: the
phone can scan but cannot advertise, which is why the space-perception advertiser trial runs
on the host dongle. No tracking of other people's devices.

Session-start probe rows are not `cap` rows either: `probe identity` on every session, and
since the 2026-10-16 install a class-4 `probe exec` row that executes the app-written 0700
`files/probe.txt` under the app UID (SELinux ALLOW on this firmware). Both run at session
start including collect-only, make no network request and request no actuator.

Local owner enablement (persisted phone-side, emitted at each session start):

- battery=on, light=on, acceleration=on, vibration=on (measured 13:52Z).
- Checkboxes are local-owner state: remote text cannot grant access or turn a channel on.
  An unchecked capability produces no collection and no effect; OFF disarms sensor
  listeners, vibration, network work and the wake lock; restart honors the saved choices.

Android permissions actually requested (manifest): BLUETOOTH (maxSdk 30),
BLUETOOTH_ADMIN, BLUETOOTH_SCAN (`neverForLocation`), INTERNET, ACCESS_WIFI_STATE,
ACCESS_NETWORK_STATE, VIBRATE, WAKE_LOCK, RECEIVE_BOOT_COMPLETED, FOREGROUND_SERVICE,
FOREGROUND_SERVICE_SPECIAL_USE, POST_NOTIFICATIONS. Camera, microphone and location
permissions are NOT requested.

Present availability (13:53Z):

- `mode=ON_COLLECT_ONLY` (`desired_on=true`; node-state observed 13:52:37Z): the phone
  stores observations and issues no HTTP requests and no actions by design; the host pulls
  through the bridge. Transport reachable, no backlog page pending, node-state fresh.
- Delivered samples are stale since 2026-10-14T06:13:24Z — by design under collect-only,
  not a delivery fault. Collection-side spool reads are live: spool 2,345,765 B, retention
  window 3.9 h, 16,851 rows, coverage ok, 233,393 records dropped cumulatively at the
  bound; scan_state windows=0 phase=window last_error=none sightings=0.
- Phone clock runs ~25.2 s behind the host (measured offset bounds +24.7..+25.7 s, n=3);
  receipt times are consumer-fetch times, not server receipts.

Supported bounded text requests (while ON; nothing executes in collect-only mode):

- `vibrate duration=<1..2000>` — canonical decimal milliseconds; at least 3 s between
  accepted vibrations; cancelled on OFF or in collect-only. `api_return` is not physical-
  effect proof.
- `eval identity | clock | read <allowlisted /proc path> | env` — fixed allowlist, output
  bounded to 1024 B/command and 64 KiB/session, 10 s timeout, 128 commands/session;
  non-allowlist paths return `failed reason=read_denied`. Eval is not advertised in the
  hello capabilities and is skipped in collect-only mode. Exercised on Note3 (2026-10-13):
  identity/clock/read/env receipts retained, uid=10225. This install predates the
  consumer `eval write`/`eval exec` verbs (published download `3b6dcf7a…`, source
  `8dbb324`) and answers them `failed reason=invalid_arguments`.

Limits: no camera, microphone, location, contacts or audio; no arbitrary code, URLs,
intents or shell; spool bounded (2 MiB / 24,576 lines, oldest evicted with a persisted
overflow row); interrupted actions report `unknown reason=interrupted` and are never
replayed.

## Redmi10 node card

Identity: redmi10 — the human's travel phone, Android API 33 (`android sdk=33`), reached
over the tailnet HTTPS front (`https://mesh-home.tail3e4555.ts.net/node/redmi10`). Not on
ADB; no host USB channel yet (operator-gated, health lane).

Implemented capabilities (session-start `cap` block): battery, light, accelerometer,
wifi_link_rssi present; vibration (actuator) present. The installed build emits no
`ble_status` and no `ble_scan_state` row; its BLE rows are `ble_scan start
beacon=MISHE-BEACON …` immediately followed by `ble_scan error reason=SecurityException`
in 5/5 session starts. That failure is structural, not a grantable gap: before `e131909`
(2026-10-15T20:16Z) the manifest declared only `BLUETOOTH`/`BLUETOOTH_ADMIN`
(`maxSdkVersion=30`), while API31+ `BluetoothLeScanner.startScan()` requires the runtime
`BLUETOOTH_SCAN` permission — no configuration change on this build can make it scan.

Installed build vintage: bracketed to [2026-10-11T12:10Z, 2026-10-12T22:05Z) by row-shape
differential over its 5 retained session-start bundles — it emits `ble_scan start`
(`59412b0`) but no `owner_checkboxes` (`ff865cd`), `ble_status` (`079db2e`),
`ble_scan_state` (`e57c91b`) or `probe exec` (`a1eed4d`) row. The interval is inferred from
row shapes, not an APK hash: the phone has no ADB/USB channel, so its installed bytes are
not readable from here.

Local owner enablement: UNKNOWN. The installed APK predates the `owner_checkboxes`
emission (added 2026-10-12T22:05Z): it emits no checkbox row, and the host-side
node-state file is absent (`mode=UNKNOWN`, reason `no-node-state-file`; unknown is never
OFF). No persisted owner choices exist yet to honor.

Present availability (13:53Z): phone `fresh-clock-conditional` over tailnet HTTPS,
cursor advancing at ~2 s channel cadence — the healthiest live channel of the two nodes.
`wifi_link_rssi_dbm` reports `unavailable reason=disconnected` — an API verdict
(`getNetworkId() < 0`), not proof the Wi-Fi link is down; the known false negative is
fixed in the candidate APK. No action receipts observed. Collection-side spool evidence is
absent (`no-spool-summary-file`), so this phone's own spool contents are unread; scan
lifecycle is stale at `error reason=SecurityException` (consecutive_errors=1).

Supported bounded text requests: none exercised; none are being sent (no actuator
authority). The installed build's eval status is unknown; it emits no `probe exec` row,
consistent with the vintage bracket. The vibration grammar is the app's own; whether this
build carries it is unverified.

Limits: Redmi10 is preparation, not a wired node: no USB window, no owner checkboxes,
BLE scan structurally dead on the installed build, Wi-Fi RSSI verdict ambiguous, spool
contents unread. The remedy is an APK update to the current candidate
`downloads/android-body-debug.apk` = `87b36024…` (73,358 B, source `e0ea84d` (app bytes `697d68a`), published `e0ea84d`), which carries `e131909` (BLUETOOTH_SCAN plus runtime request), `556049c` (ACCESS_NETWORK_STATE / `network_id_unavailable`), `0c83e32` (class-4 ExecProbe) and `697d68a` (`EvalOutcome` write-receipt bound); it supersedes `3b6dcf7a…` (72,914 B, source `8dbb324`) and `a17829c7…` (70,631 B, source `a201891`).
The update needs the human on the
phone (no ADB channel): either `adb install -r` in a USB window or copying the APK across
and opening it. An install alone still leaves the scanner dead — `BLUETOOTH_SCAN` is
requested only in `MainActivity.startBody()` (`MainActivity.java:129-130`), while
`RestoreReceiver.onReceive` (`RestoreReceiver.java:13-26`) restores a durably-enabled
session without checking it — so one foreground ON, which also asks for the grant, is
required. Acceptance would be a session bundle carrying `owner_checkboxes` and
`ble_status` rows plus scan windows and `ble_scan_state` rows instead of the
one-per-session `SecurityException`.

## Emergent conventions (observed, not imposed)

- Cards are text; state is text; the pane reads consumer JSON, humans read this file.
- A capability in an app `cap` block is not a working sensor; action receipts and
  spool-side evidence decide.
- Availability stamps ride with their reading; a card entry without a stamp is stale.
