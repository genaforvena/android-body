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

Last updated 2026-10-16 ~02:24Z by android-body discover; the `cap`/BLE attribution was
corrected 2026-10-16 ~09:28Z by docs. Availability stamps below are from the read-only
deployed view at 02:23:13Z and can go stale.

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

Local owner enablement (persisted phone-side, emitted at each session start):

- battery=on, light=on, acceleration=on, vibration=on (measured 02:23Z).
- Checkboxes are local-owner state: remote text cannot grant access or turn a channel on.
  An unchecked capability produces no collection and no effect; OFF disarms sensor
  listeners, vibration, network work and the wake lock; restart honors the saved choices.

Android permissions actually requested (manifest): BLUETOOTH (maxSdk 30),
BLUETOOTH_ADMIN, BLUETOOTH_SCAN (`neverForLocation`), INTERNET, ACCESS_WIFI_STATE,
ACCESS_NETWORK_STATE, VIBRATE, WAKE_LOCK, RECEIVE_BOOT_COMPLETED, FOREGROUND_SERVICE,
FOREGROUND_SERVICE_SPECIAL_USE, POST_NOTIFICATIONS. Camera, microphone and location
permissions are NOT requested.

Present availability (02:23:13Z):

- `mode=ON_COLLECT_ONLY` (`desired_on=true`): the phone stores observations and issues no
  HTTP requests and no actions by design; the host pulls through the bridge. Transport
  reachable, no backlog page pending, node-state fresh.
- Delivered samples are stale since 2026-10-14T06:13:24Z — by design under collect-only,
  not a delivery fault. Collection-side spool reads are live: scan loop at windows=84,
  phase=gap, last_error=none, sightings=0; spool 4,118,624 B, coverage ok.
- Phone clock runs ~24.6 s behind the host (measured offset +24.1..+25.1 s); receipt
  times are consumer-fetch times, not server receipts.

Supported bounded text requests (while ON; nothing executes in collect-only mode):

- `vibrate duration=<1..2000>` — canonical decimal milliseconds; at least 3 s between
  accepted vibrations; cancelled on OFF or in collect-only. `api_return` is not physical-
  effect proof.
- `eval identity | clock | read <allowlisted /proc path> | env` — fixed allowlist, output
  bounded to 1024 B/command and 64 KiB/session, 10 s timeout, 128 commands/session;
  non-allowlist paths return `failed reason=read_denied`. Eval is not advertised in the
  hello capabilities and is skipped in collect-only mode. Exercised on Note3 (2026-10-13):
  identity/clock/read/env receipts retained, uid=10225.

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
`ble_status` row, and its only BLE row is `ble_scan error reason=SecurityException` (API 33
scan-permission regime) — not a working scanner on this build.

Local owner enablement: UNKNOWN. The installed APK predates the `owner_checkboxes`
emission (added 2026-10-12T22:05Z): it emits no checkbox row, and the host-side
node-state file is absent (`mode=UNKNOWN`, reason `no-node-state-file`; unknown is never
OFF). No persisted owner choices exist yet to honor.

Present availability (02:23:13Z): phone `fresh-clock-conditional` over tailnet HTTPS,
cursor advancing at ~2 s channel cadence — the healthiest live channel of the two nodes.
`wifi_link_rssi_dbm` reports `unavailable reason=disconnected` — an API verdict
(`getNetworkId() < 0`), not proof the Wi-Fi link is down; the known false negative is
fixed in the pending candidate APK (health lane). No action receipts observed.

Supported bounded text requests: none exercised; none are being sent (no actuator
authority). The installed build's eval status is unknown (build date unrecorded; it
predates 2026-10-12T22:05Z). The vibration grammar is the app's own; whether this build
carries it is unverified.

Limits: Redmi10 is preparation, not a wired node: no USB window, no owner checkboxes,
BLE scan erroring, Wi-Fi RSSI verdict ambiguous. The APK update (candidate `a17829c7…`,
containing the ACCESS_NETWORK_STATE fix) needs an operator USB window before any card
claim about this phone can be re-declared truthfully.

## Emergent conventions (observed, not imposed)

- Cards are text; state is text; the pane reads consumer JSON, humans read this file.
- A capability in an app `cap` block is not a working sensor; action receipts and
  spool-side evidence decide.
- Availability stamps ride with their reading; a card entry without a stamp is stale.
