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

Last updated 2026-10-21T07:10Z. Availability stamps below are from the read-only deployed view
and can go stale; each correction is stated in the card body with its evidence, and the history
lives in Git.

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
since the 2026-10-16 install an in-process `probe exec` row that executes the app-written 0700
`files/probe.txt` under the app UID (SELinux ALLOW on this firmware). Both run at session
start including collect-only, make no network request and request no actuator.

Local owner enablement (persisted phone-side, emitted at each session start):

- battery=on, light=on, acceleration=on, vibration=on (emitted at each session start; read
  2026-10-20T08:26Z).
- Checkboxes are local-owner state: remote text cannot grant access or turn a channel on.
  An unchecked capability produces no collection and no effect; OFF disarms sensor
  listeners, vibration, network work and the wake lock; restart honors the saved choices.

Android permissions actually requested (manifest): BLUETOOTH (maxSdk 30),
BLUETOOTH_ADMIN, BLUETOOTH_SCAN (`neverForLocation`), INTERNET, ACCESS_WIFI_STATE,
ACCESS_NETWORK_STATE, VIBRATE, WAKE_LOCK, RECEIVE_BOOT_COMPLETED, FOREGROUND_SERVICE,
FOREGROUND_SERVICE_SPECIAL_USE, POST_NOTIFICATIONS. Camera, microphone and location
permissions are NOT requested.

Present availability (2026-10-21T09:57Z, read-only deployed view):

- `mode=ON_COLLECT_ONLY` (`desired_on=true`; node-state observed 09:56:34Z, age 26.1 s,
  `status=ok`): the phone stores observations and issues no HTTP requests and no actions by
  design; the host pulls through the bridge. Transport reachable, no backlog page pending
  (delivered cursor 265,956 is the queue head), node-state fresh.
- Delivered samples are stale since 2026-10-14T06:13:24Z — by design under collect-only, not a
  delivery fault. Collection-side spool reads are live: spool 3,523,091 B, physical-file
  window 5.4 h, 25,372 rows, coverage ok, 726,755 records dropped cumulatively by the bound
  (714,673 at 07:07Z); scan_state windows=3406 phase=window last_error=none sightings=341.
  That window is the *physical file's*: the spool drops rows logically but keeps their bytes
  until compaction at `2*maxBytes`, so a raw-file read overstates the app's logical retention
  ([observations](observations.md)). The file cycles 3,191,852 B → 2,486,014 B → 3,494,097 B →
  3,523,091 B as eviction and compaction alternate, all inside `(maxBytes, 2*maxBytes]`.
- Phone clock measured -0.9 s at 09:57Z (n=3, bounds -1.4..-0.4 s,
  `host_ntp_synchronized=true`): the host clock is the synchronized reference, so the offset
  is attributable to the phone rather than shared with host error; the pane derives an implied
  transport latency of 27.3-30.4 s. Earlier readings are history: -0.5 s at 07:07Z; -1.2 s at
  00:04Z; +2.8 s at 08:26Z carried `host_ntp_synchronized=false` and could not separate phone
  error from host error; -1.1 s at 18:28Z; -0.9 s at 19:29Z. Receipt times are consumer-fetch
  times, not server receipts.

Supported bounded text requests (while ON; nothing executes in collect-only mode):

- `vibrate duration=<1..2000>` — canonical decimal milliseconds; at least 3 s between
  accepted vibrations; cancelled on OFF or in collect-only. `api_return` is not physical-
  effect proof.
- `eval identity | clock | read <allowlisted /proc path> | env` — fixed allowlist, output
  bounded to 1024 B/command and 64 KiB/session, 10 s timeout, 128 commands/session;
  non-allowlist paths return `failed reason=read_denied`. Eval is not advertised in the
  hello capabilities and is skipped in collect-only mode. Exercised on Note3 (2026-10-13,
  prior install `5e7fa255…`): identity/clock/read/env receipts retained, uid=10225. The
  current Note3 install (2026-10-16T16:16:48Z, APK `87b36024…`) carries the consumer
  `eval write`/`eval exec` verbs. The session-start in-process
  `probe exec` row exercises the same write-then-exec machinery on device: the
  post-install session `d4438183` (16:17:15Z) emitted
  `probe exec uid=10225 cmd=/data/data/org.androidbody/files/probe.txt output=hello
  exit=0`, identical to the prior install's session row — no exec-path regression
  (health wake 101276) — retained collection-side only (spool, not delivered).
  Consumer write/exec rows remain unexercised: no write/exec action posted;
  collect-only freezes delivery.

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
in every retained session start. That failure is structural, not a grantable gap: before
`e131909` (2026-10-15T20:16Z) the manifest declared only `BLUETOOTH`/`BLUETOOTH_ADMIN`
(`maxSdkVersion=30`), while API31+ `BluetoothLeScanner.startScan()` requires the runtime
`BLUETOOTH_SCAN` permission — no configuration change on this build can make it scan.

Installed build vintage: bracketed to [2026-10-11T22:43Z, 2026-10-12T22:05Z) by row-shape
differential over its retained session-start bundles and action receipts — it emits `ble_scan
start` (`59412b0`) and answers `eval` actions (`e69d798`, 2026-10-11T22:43Z), but emits no
`owner_checkboxes` (`ff865cd`, 2026-10-12T22:05Z) and no `command=` field in eval receipts
(`4066dd0`, 2026-10-12T22:08Z), which rules out every later emission. The interval is inferred
from row and receipt shapes, not an APK hash: the phone has no ADB/USB channel, so its
installed bytes are not readable from here.
Session `af9d723f…` (start bundle received 17:41:39Z) emits the same shape — no
`owner_checkboxes`, no in-process `probe exec`, no `command=` receipt — so the bracket rests on two
session-start bundles, not one.

Local owner enablement: UNKNOWN. The installed APK predates the `owner_checkboxes`
emission (added 2026-10-12T22:05Z): it emits no checkbox row, and the host-side node-state
file is stale (`mode=UNKNOWN`, `status=stale`, reason `node-state-stale`; unknown is never
OFF). No persisted owner choices exist yet to honor.

Present availability (2026-10-21T09:57Z, read-only deployed view plus the rendezvous write log).
This claim names its own detector and horizon, so a reader can re-derive it and a later halt
falsifies it: the accepted-POST gap census over `body/queues/writes.jsonl` (consecutive
`redmi10` rows, gap > 60 s), with halt onsets also in the consumer's
`body/perception/class-c-delivery-gap-detectors.jsonl`; a `channel-delivery [pass]` verdict is
not a no-gap verdict.

- Clean for the last 47 minutes as of 09:57Z: no gap onset after 2026-10-21T09:10:00Z (63.8 s,
  resumed 09:11:04Z). Live at the read: `channel-delivery [pass]: cursor=advancing`, cursor
  174,776, cadence 4.134 s median over the last 8 advances (max 6.151 s), current at the read.
- Behind that horizon, same census: **25** ≥60 s gaps with onset since 00:00Z today, worst
  **618.6 s** (`08:02:50.226 → 08:13:08.822`, resuming as a 128-record page) — larger than the
  386.6 s the previous stamp cited. 23 ran from the first onset 2026-10-21T00:27:26Z through
  06:08:21Z (worst 386.6 s, `04:08:50→04:15:16`; also 377.5 s, 311.3 s, 275.9 s, 249.2 s,
  247.2 s, 228.2 s), then 08:02:50Z and 09:10:00Z. The evening drain's clean window ran
  2026-10-20T19:54:32Z → 00:27:26Z.
- Attribution of those 25, by health's journal census (`tools/transport_gap.py` over the host
  `tailscaled` journal; A = no line for the phone's tailnet address in-window, B = a failure
  line from that address, C = the `ipn` state left `Running`, D = address present with no
  failure line), re-derived here from a frozen capture of the retained journal: the morning 23
  are **21 B, 1 D, 1 A** with `ipn` `Running` throughout; the 618.6 s window is **A** — no
  attempt from the phone at all — and 09:10:00Z is B. The host's rendezvous listener was up
  continuously (same PID since 2026-10-20T10:44:04Z), so the 21 B windows are host-side on the
  tailnet path, not the queue, while the two A windows are phone-side pauses: those 689.5 s
  were lost on the phone, not the host. The same command recorded 22 B / 1 D / 0 A at 07:1xZ,
  and journald rotates on this host (`Time jumped backwards, rotating`; the retained head moved
  forward ~74 min during this session), so a past window's class is not stable evidence and
  that one-window difference stays unattributed.
- The consumer's own class-c record (halted while polls succeed, no `code=2`, no light-channel
  fault) agrees on the phone side of the 08:02:50Z window: 24 rows, 13 new today (first
  04:10:51Z at cursor 157,668, last 08:04:52Z at 169,304), none for the 00:27:26Z or 09:10:00Z
  windows — it fires on a poll that observes a ≥120 s freeze, so it does not cover every ≥60 s
  gap.

The earlier pattern is history: 4-record POSTs every ~5 s until 18:53Z, then three silences —
18:53:14→19:01:56Z (522.0 s), 19:01:56→19:04:38Z (161.4 s), 19:04:38→19:11:02Z (384.4 s) — each
ending in a 128-record page, 128-record backlog pages every ~80 s to 19:28:46Z, a further burst
19:47:48→19:54:29Z, then the clean window 19:54:24Z→00:27:26Z described above. Current session `af9d723f…`, whose session-start
bundle was received 17:41:39Z inside the post-outage drain; it supersedes `45bdac2e…` (started
07:18:02Z).

Four halts matched a host tailnet outage: 09:30:41→09:49:35Z, 09:51:54→10:08:29Z,
10:08:43→13:20:30Z and 14:02:57→17:40:24Z (18.9 min, 16.6 min, 191.8 min, 13,047.4 s). Each
contains a `Running -> Stopped (WantRunning=false)` / `Stopped -> Starting` pair in the host
`tailscaled` journal and ends in a burst of 128-record pages (9,168 records in 8.7 s at
13:20:30Z; 132 writes / 7,914 records over 435.6 s at 17:40:24Z): the phone buffered rather than
losing data (health wake 118178, DM 119702). The 14:03:03Z stop and 17:39:11Z restart are the
operator's; this plant does not override a deliberate operator state.

The three evening halts match no such stop: the `tailscaled` journal has no ipn-state transition
after 17:39:11Z, and session `af9d723f…` spans both sides of each one. Rows whose phone epochs fall
inside a silence arrived after it, so the phone stayed alive and buffered while the host accepted
nothing. Health's causal read of the same windows (wake 118178, DM 121882) narrows them to
transport-path stalls on the host's tailnet serve path: the serve front logged `TLS handshake error
… EOF` and `CreateEndpoint error … refused`/`… operation timed out` from the phone's own tailnet
address inside the silences, the phone was retrying throughout, and tailnet stop,
rendezvous-listener outage, serve reload and phone death are each ruled out. Health's host-side
A/B/C/D gap attribution (`tools/transport_gap.py`, landed `ff3829c`, DM 123099) reproduces five
≥120 s windows by code over 18:00–20:00Z and classes each from the same journal: 522.0 s, 384.4 s,
143.4 s and 324.8 s are **B** (a failure line from the phone's own tailnet address inside the
silence), 161.4 s is **D** (the address present, no failure line, so its loss sits between that
connection and the rendezvous), and `tailscaled` stays `Running` across every window, excluding C.
The split inside B — host DERP egress vs the serve front's accept — stays UNKNOWN (senses DM 121552
on the detector's per-session dedup). The tailnet stops' resolver remains the operator; the evening
halts have none. The consumer's class-c stays a no-known-cause class, not a cause: the nine older
rows since 2026-10-15 (cursors 1252–106658, including the ~3.5-day 98466 halt) have no matched
tailnet window either.

The rows' `host_stopped` field was the only adb-attached device's (Note3's) app state, not
Redmi10's, and must not be read as evidence about this phone; senses fixed the probe (commits
`7cdc70b`+`0951986`, DM 120528) so new rows carry `node`, and a node with no recorded serial reads
`host_stopped=null` with `host_stopped_reason=no-recorded-serial-for-node`, while the nine
pre-existing rows keep the old Note3 value as historical evidence. Scan lifecycle stays stale at
`error reason=SecurityException` (consecutive_errors=1). `wifi_link_rssi_dbm`'s `disconnected`
verdict is an API verdict (`getNetworkId() < 0`), not proof the Wi-Fi link is down; the known false
negative is fixed in the candidate APK. A delivered row's phone epoch lags its consumer receipt by
the backlog-dependent delivery lag (≈2 s to ≈186 s today; 13,053 s at the drain peak); the pane's
phone/host "skew" figure is that lag, and its clock/latency split is not established.

Supported bounded text requests: `eval` is exercised on this phone. Five receipts at
2026-10-20T08:30-08:33Z: `eval identity` and `eval read /proc/self/attr/current` succeeded (the
latter `u:r:untrusted_app:s0:c10,c257,c512,c768`, SELinux categories included), `eval read
/data/system/packages.list` returned `failed reason=read_denied`, and two further eval commands
returned `failed reason=invalid_arguments` — unknown-verb rejections by this build's parser, not
malformed arguments: the payloads were `eval write
p.sh #!/system/bin/sh\necho hello-from-app\n` and `eval exec p.sh` (posted 08:33:36Z), and the
`write`/`exec` verbs landed in `d54b382` (2026-10-16T14:55Z), four days after this bracket's
upper bound. The bracket's parser (`BoundedEvaluator.parse`, byte-identical through
`d54b382^`) throws `unknown eval command: write`; `BodyService.executeEval` maps that
`IllegalArgumentException` to exactly `failed reason=invalid_arguments`. The same payloads
parse on the current source. The receipts carry no `command=` field, so the canonical command
text is absent from these rows (pre-`4066dd0` vintage). No vibration request has been sent and
none is authorized; whether this build carries the vibration grammar is unverified.

Limits: Redmi10 is preparation, not a wired node: no USB window, no owner checkboxes,
BLE scan structurally dead on the installed build, Wi-Fi RSSI verdict ambiguous, spool
contents unread, delivery halting in every host tailnet-outage window and in phone-side pauses,
while the older class-c rows' cause stays unestablished from here. The remedy is an APK
update to the current candidate
`downloads/android-body-debug.apk` = `a5be0e4…` (73,653 B, clean build of `3047f17`), which carries `e131909` (BLUETOOTH_SCAN plus runtime request), `556049c` (ACCESS_NETWORK_STATE / `network_id_unavailable`), `0c83e32` (in-process ExecProbe), `697d68a` (`EvalOutcome` write-receipt bound) and `4e4caba` (the bounded-exec reader-contract change); it supersedes `2f6f3295…` (73,660 B, source `e707a4a`), `9678d87c…` (73,650 B, source `6fa8601`), `04439ff9…` (73,656 B, source `b025ede`), `87b36024…` (73,358 B, source `e0ea84d`), `3b6dcf7a…` (72,914 B, source `8dbb324`) and `a17829c7…` (70,631 B, source `a201891`).
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
