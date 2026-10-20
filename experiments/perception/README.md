# Read-only body perception

A Python 3.10+ standard-library consumer of the [text protocol](../../protocol/README.md),
running on the rendezvous host, not the phone. It only GETs observations. It never
queues actions, requests physical effects, imports Mishe, or uses a JSON endpoint.
The same node secret nevertheless grants write access: keep it private.

## Run

From the repository root, with a provisioned rendezvous and phones configured ON:

```sh
SITE=/home/mesh-home/android-body/.mishe-tauftauf
# Trusted private local file, not a downloaded script; values never appear in argv.
set -a
. "$SITE/body/credentials.env"
set +a
python3 experiments/perception/watch.py follow --site "$SITE" \
  --url http://127.0.0.1:8765 \
  --node note3:NOTE3_SECRET --node redmi10:REDMI10_SECRET
```

Provision each variable with that node's existing rendezvous secret. An unconnected
Redmi remains unknown; the consumer does not invent its capabilities or readings.
For a Note3-only experiment omit the Redmi `--node` argument. These are **environment
variable names**, never literal secrets. The root URL has no `/node/` suffix.

The foreground `follow` process is suitable for a systemd `Type=simple` service:
use an absolute Python/script path in `ExecStart`, the above arguments, a private
`EnvironmentFile=SITE/body/credentials.env`, and `UMask=0077`. SIGTERM or Ctrl-C
stops it. Only one follower can lock a perception directory. The parent operator
owns service installation; this script does not modify services or phone settings.

Default polling is one page per node every two seconds, five-second request
timeout, 30-second freshness window; optional flags are `--poll-seconds`,
`--timeout`, and `--stale-seconds`. Each cycle is bounded to one 128-record page per
node so a deep backlog does not monopolize the consumer. Catch-up is deliberately
bounded rather than instantaneous. State and view updates continue through network
errors; authentication/reset errors remain visible, and the cursor never resets
automatically. Fix the actual endpoint/credentials/storage rather than deleting
state or claiming a device is live.

HTTP is accepted only for loopback. For remote consumers use normal validated
HTTPS. Redirects are rejected; this consumer does not pass credentials to a redirect
or ambient HTTP proxy. In the USB arrangement `adb reverse tcp:8765 tcp:8765` lets
the app reach the host's loopback listener at its configured loopback endpoint.
This is not public/LAN cleartext deployment.

## Read without polling or credentials

```sh
python3 experiments/perception/watch.py view --site "$SITE"
python3 experiments/perception/watch.py events --site "$SITE"
python3 experiments/perception/watch.py space --site "$SITE"
```

`view` is the detailed upper-pane/sensor-check surface: source endpoint, observation
cursor, capability presence/absence/unknown, original battery fraction/charging,
light lux, acceleration axes (m/s²), connected-link Wi-Fi RSSI (dBm), and Bluetooth LE
API/feature status, accuracy/age fields, original phone event/sample time, and
consumer receipt time. RSSI is only the phone API's current-link reading, not room
proximity; `observed_at` is API read time, not acquisition age. The consumer keeps
protocol event time, API-read time, and consumer receipt distinct, reports
acquisition age as unknown, and preserves unavailable reasons. The `ble_status`
projection preserves feature declaration, adapter, scanner and advertiser SDK API
surface, scanner and advertiser getter outcomes, and multi-advertisement support as
separate values, including unavailable/error states. Getter `returned` means only
that the accessor returned an object; it does not prove scanner/advertiser operation,
an over-air event, or RF reception. These are declarations/status, not proof of an
operational scanner, advertiser, or over-air event. The installed phone emits this
read-only snapshot live (latest retained `ble_status` #265954, 2026-10-14T06:13Z on
the BleStatus-wiring APK `a5cc750e`), reporting Note3 `api=21 adapter=enabled
scanner_getter=returned advertiser_getter=null advertiser_supported=unsupported`.
The `ble_sighting` and `ble_scan` projections render bounded BLE scan evidence:
sighting name and RSSI (only when fresh-clock-conditional) and scan lifecycle
subtype (`start`/`stop`/`error`/`unavailable`) with reason, beacon, window and gap.
The sightings channel is explicitly not presence, occupancy or proximity proof;
`sightings_in_delivered_history` is a bounded count of the *delivered envelope*,
not a rate or duration. The pane names the freeze cause only for a node whose
host-side state is currently collect-only; a delivering node, or one whose
node-state read is stale or unknown, gets the bare bounded-window caveat instead
of a cause the renderer cannot support. The
installed phone emits scan lifecycle events live (retained evidence: `ble_scan
start beacon=MISHE-BEACON`, 2026-10-13T09:34Z; other subtypes not yet
retained-observed). One allowlisted-beacon window has now been retained, in the
app-private spool rather than the delivered stream: 20 `ble_sighting
name=MISHE-BEACON` rows at rssi −16 to −28 dBm, host 17:17:20Z–17:25:55Z on
2026-10-15, inside the host advertiser window 17:16:25Z–17:28:25Z (direct
read-only `adb run-as` count). That is scanner-visible reception only: no
presence, occupancy or proximity conclusion, and RSSI is not calibrated. Under
collect-only the delivered stream is frozen, so `sightings_in_delivered_history`
reads 0 until the backlog is uploaded; the spool-side count appears in the
`scan_state` line as `sightings=N`.
The bounded state retains the latest 32 event kinds, last 32 observations and last
16 action receipts. An unknown event is not treated as evidence of a known sensor.

The RSSI consumer accepts only the Android candidate's supported numeric range
(-126 through -1 dBm). Zero, the -127 unavailable sentinel, and values outside the
range remain UNKNOWN and are never surfaced as measurements.

`events` is a compact wake-friendly surface with source, current freshness/errors,
capabilities and coarse measured buckets plus the last four meaningful transitions
and latest action receipt. Ordinary sequence, sample timestamp, receipt timestamp,
accuracy and `age_ms` churn do not produce a new event. Coarse buckets are battery
fraction in 0.05 steps (with charging state), `floor(log2(1 + lux))`, and acceleration
in 1 m/s² steps. They are **change filters**, not substitute measurements:
read `view` for exact raw evidence. Capability/freshness/error/session transitions,
connected-link RSSI status/value/reason changes, Bluetooth LE status/value/error/
freshness and sighting/scan lifecycle changes, and action receipts also change
this surface.
only while fresh; stale and unavailable statuses remain visible without a value.
Sequence and timestamp churn with unchanged RSSI or BLE evidence does not repeat an
event. No occupancy claim is made.
An allowlisted-beacon observation adds `sighting_phone_sample=<phone UTC>` to the
compact event line; it is omitted without an observation. A frozen stamp beside an
advancing `scan_state` (windows/phase advancing, `sightings` flat) is the readable
cessation signal during and after an advertiser window.

When two adjacent retained light observations in the same phone session are both
fresh, not delayed at receipt, within the configured freshness interval, neither
was received on a page marked as having more records, and no backlog is pending, a
bucket crossing adds a `measured-light-bucket-transition` row to `events`. It
includes both protocol sequence IDs, lux values, phone sample times and consumer
receipt times, plus source/session. This is a historical measured light change, not
a room, person, motion, or occupancy event. A missing, stale, delayed,
session-reset, or backlog boundary seeds a new baseline rather than inventing a
transition. The protocol provides no phone monotonic timestamp, host monotonic/boot
receipt, or server-receipt time; the consumer does not synthesize them.

`space` is the stable, credential-free JSON read-only adapter for core consumers.
It prints a recomputed snapshot; the follower also atomically publishes the latest
snapshot at `SITE/body/space.json`, outside the node-state directory. Schema v1
last poll, capabilities, current light status/reason and validity window, usable lux
with sequence/units/accuracy/age plus `real_age_upper_bound_ms` and
`is_fresh_at_host` (skew-corrected freshness; see Freshness and honest limits),
and connected-link `wifi_link_rssi` status,
sequence, dBm, source, protocol event time, API `observed_at`, and consumer receipt.
RSSI acquisition age and its unavailable reason are explicit; no room-proximity
claim is made. `last_light_transition` includes stable event ID and both endpoint
`readings as historical evidence. Additive `ble_sighting` and `ble_scan` snapshots
mirror the `ble_status` convention: measured values only when fresh-clock-conditional,
honest unknown when absent, values dropped when stale. Both RF projections also publish
raw `phone_sample_epoch_s` and `consumer_receipt_epoch_s` even when stale, so a core
consumer can state "beacon last seen at phone-time T" and measure cessation age against
the node's `clock_domain` reading; the consumer computes no host-derived age, which would
conflate phone/host clock skew.
Additive `node_state` carries the host-side verdict for the node
(`tools/node_state.py`): status, mode, desired_on, collect_only,
`observed_at_epoch_s`, reason and bounded reasons. It is what lets a consumer name
a designed ON + collect-only silence, which sends no HTTP by design, instead of
scoring it as a modality fault; a missing, stale or invalid verdict is mode
UNKNOWN, never OFF. The reader's clock-derived `age_s` is deliberately not
republished, so the snapshot stays byte-stable between two polls inside one second
and the follower can skip the unchanged atomic write. Missing protocol v1 phone
monotonic time, host
monotonic/boot receipt, server receipt, and acquisition span are explicit nulls;
consumers must not infer them. Use the CLI for current freshness; the published file
is a cache whose `generated_at_utc` can age if the follower stops.
During follow, each node checkpoint is durably saved and the complete multi-node
snapshot is atomically refreshed before the next node is polled. A slow or stalled
later endpoint therefore cannot hide an earlier node's newly observed transport
error. On first start, empty per-node checkpoints are created before publishing the
initial complete map, so later nodes are not temporarily omitted. Snapshot freshness
still ages independently; a timed-out request is not treated as a completed result
until its configured timeout returns.

With no saved node state, the same schema reports `status=unknown/no-perception-state`
and an empty node list; absence of data is not an empty-space claim.

The `view`, `events`, and `space` CLI modes recompute freshness against the current
host clock, including when the follower has died. Use the CLI rather than blindly
trusting old cached files. While running, the follower publishes view/events beneath
`SITE/body/perception/` and the structured snapshot at `SITE/body/space.json`.
`events.txt` is rewritten only if its text changes; stdout contains meaningful
transition lines, not every polled snapshot. Exit zero means rendered evidence,
**not** that any phone is healthy.

## Composite stillness

`view` and `space` include a derived stillness composite: the joint standard
deviation of acceleration magnitude, light lux and connected-link Wi-Fi RSSI
over a bounded history window. `status=still` requires all three standard
deviations within thresholds (accel ≤ 0.5 m/s², light ≤ 0.1 lux, RSSI ≤ 2.0 dBm);
any single term exceeding its threshold yields `status=moving`. The composite is a
space-perception programme output, not a human-presence or occupancy claim.
If any required sensor's latest sample is stale, the composite reports `status=unknown/frozen` regardless of historical window contents; stale evidence cannot authorize a current stillness or moving claim.
When a required input is absent from the window (`missing_inputs`) or its most
recent observation carries no usable value (`unavailable_inputs`, e.g.
redmi10's `wifi_link_rssi_dbm unavailable reason=disconnected` while the phone
is on mobile data), the composite reports `status=unknown/no-available-input`
and names the input: it cannot support a current verdict, and calling it a
sample-count shortfall would name the wrong cause. The check is on the most
recent observation, symmetric with the stale gate, so window values that
predate a link loss cannot authorize a verdict about now.
`status=unknown/insufficient-samples` is reserved for the case where every
input's latest observation carries a value but the window holds fewer than two
usable values for some input.

The light term is quantized: at a near-constant baseline its readings can swing
enough to exceed the light threshold while acceleration and RSSI stay flat,
yielding `status=moving` on a stationary phone (observed repeatedly, e.g.
light_std ≈ 0.6 lux with accel_std ≤ 0.13 m/s² and rssi_std = 0 dBm). Treat
isolated light-term excursions as a known false-positive mode, not motion.

**Accel baseline anomaly and calibration-free guard (Note3):** On
2026-10-11T03:14:41Z the Note3 accelerometer resting magnitude stepped from
~10.21 m/s² (near Earth gravity) to ~15.93 m/s² (1.6×g) in one 5-second
interval. Two further regimes were measured over the retained queue
(research-methods wake 75303/75378): a stable ~15.7–16.2 m/s² magnitude held
for ~48 h (2026-10-10T23:14Z → 2026-10-12T23:30Z), and a pinned-axis run
(x = −19.6133, y = 19.612701 across 25,066 consecutive samples, |a| ≈ 29.57
m/s²) held for 57.17 h (2026-10-07T16:29:49Z → 2026-10-10T01:40:11Z). Cause
UNKNOWN (sensor fault vs fixture force). The std-based composite is
baseline-shift-immune: std of a constant stream is zero regardless of
baseline. Absolute-magnitude thresholds (e.g. "still if |a| < 11") would be
unsound on this device in its current state and are not deployed.

`view` therefore renders a calibration-free **accel guard** over the retained
window, and the excursion log carries the same verdict. Statuses: `few-samples`
(fewer than 5 accel samples), `pinned-axis` (any axis is bit-identical across
the window — std ≈ 0, which a stillness/change scorer would misread as "still"),
`implausible-magnitude` (a stable magnitude more than 20% from g with
pstdev(|a|) < 0.5 m/s² is not real acceleration), else `ok`. `ok` is the only
status under which the accel leg supports a stillness or movement claim; an
indeterminate verdict never substitutes a value and never authorizes a current
sense. The pinned-axis test is offset-invariant (per-axis range); the magnitude
test compares |a| to the nominal g and needs no per-device calibration. Both
survive the baseline steps above.

## Class-B delivery-gap detection

The consumer detects a class-B delivery gap: a cursor freeze or session change
with two or more consecutive null-lux (`0.0` lux) reads. A detection fires at
most once per `(session, newest retained light sequence)` pair — the null-lux
light evidence is the quantity that must be unmoving for two onsets to be the
same gap — and appends a bounded record to
`SITE/body/perception/class-b-delivery-gap-detectors.jsonl` (last 128 lines,
atomically replaced). The record includes the trigger type (`cursor-freeze` or
`session-change`), the consecutive null-lux count, the frozen cursor, the
`light_sequence` join key, and the session. The cursor's observed state is
recorded as provenance (`cursor_state`: `frozen`, `advanced`, `unknown`), never
as identity: a non-producer write (an authenticated POST of a malformed queue
line) advances the cursor without adding light evidence and therefore cannot
re-arm a spurious second onset for one continuous gap. A genuine resumption
followed by a new halt adds a new light observation and is reported as a
distinct gap. A freeze without null-lux reads is not class-B; the detector is
armed for the next qualifying occurrence. Historical rows written before this
dedup change keep `kind=class-b-stop` and carry no `light_sequence`.

Each record also carries `node_mode` and `node_state_status` read from the
host-side node-state file (below), so a gap names *why* the producer is silent
(OFF, collect-only, not-running) rather than only that it is. These fields are
provenance and never take part in the dedup identity.

## Class-C delivery-gap detection

The consumer detects a class-C delivery gap: no new record received for 120 s
(`CLASS_C_WINDOW_SECONDS`) while polls keep succeeding, with no class-A arming
(`ble_scan error code=2`) and no class-B null-lux freeze. The cause is explicitly
non-deterministic — phone asleep, force-stopped app, or another halt — so a row
reports the halt, not a cause. A detection fires at most once per `(cursor,
session)` pair and appends a bounded record to
`SITE/body/perception/class-c-delivery-gap-detectors.jsonl` (last 128 lines,
atomically replaced).

The log is shared by every followed node, so each record carries `node`. It also
carries `host_stopped`, the host-side adb complement (`dumpsys package
org.androidbody`, 5-second bound) that separates "phone asleep" from "app
force-stopped". That probe can only read a device the host's `adb devices`
enumerates exactly once, so its verdict is attributed to the row's node only when
the enumerated serial equals the site's recorded `<node>_serial` in
`SITE/body/activation.json`. Otherwise the row carries `host_stopped: null`,
`host_stopped_device` (the serial that *was* enumerated, or null) and
`host_stopped_reason` naming why:

| `host_stopped_reason` | meaning |
|---|---|
| `no-adb-device-enumerated` | adb is absent or failed, or did not name exactly one attached device |
| `no-recorded-serial-for-node` | the activation record names no serial for this node (no adb channel) |
| `enumerated-serial-is-another-node` | the enumerated device belongs to a different node |
| `probe-unknown` | the device matched; the bounded probe returned no verdict |

`host_stopped_reason` is null only alongside a boolean `host_stopped`. Rows
written before the `node`/attribution fields existed keep the old shape, and
their `host_stopped` was measured on whichever device adb enumerated without
being attributed to the row's node — on this site, the Note3's stopped state on
Redmi10 rows.

## Channel-delivery detection

The consumer evaluates a per-node delivery verdict on every poll and renders it as
`channel-delivery [status]`. `fail` means delivery loss by the detector's two rules: the
transport is not reachable, or the node's cursor has not advanced within
`CHANNEL_DELIVERY_CURSOR_FREEZE_SECONDS` (30 s). A cursor that advances while a channel stays
stale is sensor throttling, not delivery loss.

The interval is deliberately not widened for a draining node. Redmi10 on
2026-10-20T19:11-19:26Z drained a backlog by delivering one 128-record page every ~78 s, each
advancing the cursor, so those cycles report `cursor=frozen` while delivery is progressing
(docs DM 121552). Host-side evidence does not separate that page cadence from a halt: the same
evening held accepted-POST gaps of 36.9-112.6 s with no declared cause beside real halts of
161.4 s, 324.8 s, 384.4 s and 522.0 s, so an interval wide enough to ignore the page cadence
would stop reporting the 161.4 s halt. The verdict reports the node's own cadence as context
instead of filtering the wait:

| field | meaning |
|---|---|
| `cursor_age_seconds` | seconds since the cursor last advanced |
| `advance_interval_median_seconds` | median of the last `CHANNEL_DELIVERY_ADVANCE_SAMPLES` (8) completed advance intervals, null before the first |
| `advance_interval_max_seconds` | slowest of those retained intervals |
| `advance_interval_samples` | how many intervals the two fields cover |

The pane prints them as `interval=30.0s age=Ns cadence=Ms(n=k,max=Js)`, so a reader can see
that a frozen cursor is advancing in ~78 s pages rather than stopped. The intervals describe
the most recent uninterrupted observation window: the advance clock is persisted with the
node state, so a verdict gap wider than the module's refresh bound clears the retained samples
and drops the interval spanning it. Two residual cases are stated rather than hidden — a
restart shorter than that bound still folds its downtime into one sample, and one stalled poll
clears the samples for a cycle — so the field is context, never a filter. The halt census
remains `body/queues/writes.jsonl` (the host's accepted POSTs), not this verdict.

Detections append a bounded record to
`SITE/body/perception/channel-delivery-gap-detectors.jsonl` (last 128 lines, atomically
replaced). One row per `(session, reason)` onset, kept while the condition holds, across a
return to `pass` and across a follower restart (the key is persisted with the node state, as a
list so a JSON round trip preserves it — until 2026-10-20 it was a tuple, which never matched
the reloaded key and re-logged one onset per restart): this log is an onset record, not a halt
census. A per-episode key would log
every page cycle of a drain instead — measured on the 2026-10-20 evening, 18 rows in 75 min
of drain, 11 of them 75.4-83.6 s page cycles — and those rows would evict real halts from the
bounded file. A row carries the frozen cursor, its age, the node's cadence context, the
transport verdict, the per-channel ages and the session.

## Light-cycle resumption detector

`light_cycle_monitor.py` is a separate bounded host-side process that polls the live node's
light channel (per-node frozen rules; the Note3 rule stays dormant while it is collect-only),
publishes a heartbeat to `SITE/body/runtime/artifacts/light-cycle-monitor-state.json`, and
appends a row to `light-cycle-resumed.jsonl` only when a resumption is claimed. Both views
render a `Light-cycle resumption detector` section: liveness (`status`, heartbeat age against
the 30 s stale bound), the heartbeat fields verbatim, and the last retained row. A missing or
stale heartbeat is UNKNOWN/stale, never calm.

The view reads the last retained row from a bounded tail of the log and widens that window
until it holds a parseable row (cap `MONITOR_LOG_MAX_BYTES`), because one row can exceed the
4096 B window: a long dark dwell grows its `baseline_samples` array. A window that starts
inside a line never parses that line, so the scan falls back to the newest *complete* row
rather than rendering "no row".

A resumption row names each quantity it carries, and the view renders those names:

| row field | quantity |
|---|---|
| `samples` | light samples consumed this run at the fire instant — the heartbeat's own `samples`, not its `poll` (the tail-check index) |
| `prev_lux` / `prev_observed_unix` | the sample immediately before the fire: its lux and its phone epoch |
| `baseline_first_unix` | the first baseline sample's phone epoch; the view derives `baseline_span_s` from `baseline_samples`, whose epochs are all phone-clock, so the span is one clock domain |
| `timestamp_unix` | the row's own fire time on the host clock, rendered as `event_host_utc` so the row's `lux`/`prev_lux` cannot be read as this run's fresh reading |

Until 2026-10-16 the row wrote the sample count as `poll` and the baseline start as
`prev_observed_unix`, and the view subtracted the host `timestamp_unix` from the baseline
start as `prev_observed_gap`. That collided with the heartbeat's `poll` in one rendered
block (a reader saw `poll=557` beside `poll=3284`) and mixed clock domains (68.6 s rendered
for a 25 s dark window). A row that predates the rename still renders its count as
`samples` and its span from the baseline epochs, and the view says so.

The compact view carries no heartbeat line, so without that name the row's `lux`/`prev_lux`
could be taken for this run's fresh reading. A row written before the field renders
`event_host_utc=unknown`, never silently given a time.

The heartbeat's `armed` is only "a fresh baseline exists this run": it does not say the
baseline is below the threshold, nor that the current poll read anything fresh. The view
derives a `baseline` classification from the same fields and names it, so the detector's
silence carries its own cause instead of one sentence that fits only the fresh-but-lit case:

| `baseline` | meaning |
|---|---|
| `no-fresh-reading` | no fresh light reading this run (source stale/unreadable): no baseline |
| `first-fresh-poll` | the first fresh reading arrived this poll; the baseline is set next poll |
| `sub-threshold` | a fresh baseline below the threshold: a resumption fires on the next lit reading |
| `at-or-above-threshold` | a fresh baseline already lit: nothing dim to resume from |
| `baseline-without-current-reading` | a baseline survives from an earlier poll; this poll read nothing fresh |
| `unknown` | fields missing or disagreeing with `armed`: the armed state is UNKNOWN, not calm |

Rows are reported verbatim and never rescored here. A row without `threshold_lux` predates
the per-node rule and is labelled inadmissible; a row whose count and span fields predate
the 2026-10-16 rename is labelled with their current names and flagged as pre-rename.
Scoring stays research-methods' pre-registered milestone-5 rule.

## Host-side node state

`tools/node_state.py` (health) classifies the device from already-read adb text
and publishes `SITE/body/perception/node-state-<node>.json` atomically:

    {"node": "note3",
     "mode": "ON_SENDING|ON_COLLECT_ONLY|ON_NOT_RUNNING|OFF|UNKNOWN",
     "desired_on": true, "collect_only": false, "observed_at_epoch_s": 0.0,
     "source": "tools/node_state.py", "reasons": ["..."]}

`read_node_state` reads it with a bounded age (300 s) and the view renders one
`node state (host-side, ...)` line per node. The line appends the document's
`reasons` (the publisher's *why*), bounded and sanitized by the reader, so a
silent node names the reason (`collect-only: no HTTP by design`) instead of only
its mode. A missing, unreadable, malformed or stale document yields
`mode=UNKNOWN`, never `OFF`: only an explicit `OFF` the publisher wrote is
reported as OFF. The documents sit in the same directory as the perception state
files but are a distinct family; `state_paths` excludes the `node-state-` prefix
from the perception-state glob so they are never parsed as a node state (a
`KeyError: 'version'` crash-loop on 2026-10-14 showed why).

## Freshness and honest limits

- `fresh-clock-conditional` means the record's **host receipt time** is within the
  configured window: age = `now - received`, not `now - collected`. Phone/host
  clocks are not synchronized by this consumer, but clock skew does not consume
  this budget — the age measures transport and processing latency, not the phone
  offset. More than five seconds future-dated is unknown, not fresh. Phone event
  time and `age_ms` are retained for provenance, not used for this verdict.
- `real_age_upper_bound_ms` — conservative upper bound on the sample's real age
  at the host: current `acquisition_span_ms` minus the minimum span in the
  retained window (the minimum approximates fixed transport lag). Null without
  span history.
- `is_fresh_at_host` — `real_age_upper_bound_ms / 1000 < validity_seconds`. A
  skew-corrected upper bound on the sample's real age, distinct from the
  receipt-time base: even a freshly received record may hold an older sample, and
  this verdict bounds that. Null when the bound is unknown.
- The light/acceleration wire timestamp is the approximate **sensor sample time**,
  not necessarily the five-second snapshot collection time. `age_ms` is sample age
  at collection; it excludes queue residence. Do not add it to `now - phone_time`
  a second time. Battery snapshots normally provide a collection heartbeat.
- `consumer_receipt` is when this reader received the HTTP page. The protocol has
  **no server receipt timestamp**. `delayed_at_receipt=true` marks a phone timestamp
  older than the freshness window at fetch; queue residence and clock skew cannot
  be separated with this boundary.
- `backlog/draining` is an explicit pending server page. Delayed samples may still
  arrive in the final page or from the phone's private spool, which the consumer
  cannot inspect. After draining, an old sample remains stale: fetching it now does
  not make it a current perception or authorize a derived current sense.
- `stale/phone-silent-or-delayed` means no recent phone evidence, not proof that the
  phone is physically OFF. OFF, disconnected/collect-only operation, OS suspension,
  lost upload, and clock skew need independent investigation. `reachable` refers
  to rendezvous access, never a phone heartbeat. `offline-or-rejected` records a
  consumer transport/HTTP failure; `unknown/consumer-not-refreshing` means its
  last poll attempt is old (a previous error remains visible as `last-error`).
- Capability `present` is an advertisement, not proof of a fresh measurement.
  `absent`, `unavailable`, `unknown`, and numeric zero are distinct. A new ON session
  clears old capability/current-sensor evidence; historical action receipts remain.
- The bounded derived sense is `sqrt(x²+y²+z²)` in m/s², with its exact observation
  sequence as evidence. It includes gravity and is shown only for usable current
  axes. It is not proof of motion, occupancy, or physical action success.
- Requested/succeeded/failed/unknown action receipts are read as phone observations.
  `evidence=api_return verification=unverified` is preserved: an Android API return
  does not independently prove a motor ran. This consumer never retries an effect.


## Protocol v2 clock-agreement fields

The space snapshot carries five clock-agreement fields for trial scoring
(transport jitter, clock offset, host-restart detection). Four are computed by
this consumer (three per receipt, one cached per process); one is emitted by
the phone under protocol v2.

- `host_receipt_monotonic_ns` — `time.monotonic_ns()` captured per record at
  receipt. Always present on items written by this consumer; null only for items
  persisted by a pre-v2 consumer (`receipt metadata not recorded` is not a reason
  field for it; null means not recorded).
- `server_receipt_utc` — always null today: the rendezvous server emits no
  receipt timestamp in protocol v1, so `server_receipt_utc_reason` reads
  `not provided by protocol v1` (or `no-light-observation`). The consumer's own
  receipt time stays available under `consumer_receipt_epoch_s` /
  `consumer_receipt_utc`; it is never aliased as a server time.
- `host_boot_id` — `/proc/sys/kernel/random/boot_id`, read once per process and
  cached. Null with `host_boot_id_reason=host boot id unreadable` when the file
  is missing/unreadable; never fabricated. Deltas of `host_receipt_monotonic_ns`
  detect host restarts via boot_id change.
- `phone_elapsed_realtime_ms` — phone monotonic `SystemClock.elapsedRealtime()`
  in milliseconds, parsed from the record field `phone_elapsed_ms` when the phone
  emits it (protocol v2). Validation mirrors `sensor_time_ns`: unsigned decimal,
  at most 2^63−1; anything else is null with
  `phone_elapsed_realtime_reason=invalid phone_elapsed_ms value`. Protocol v1
  records leave it null with reason `not provided by protocol v1`. Deltas are
  comparable only within one hello `session` (same phone boot); the value is not
  Unix time and not a host-clock quantity.
- `acquisition_span_ms` — `(host receipt − phone collection epoch) × 1000`,
  rounded to 0.1 ms. Cross-clock and coarse: a sanity signal for receipt lag,
  not a transport-latency proof.

Scoring prerequisite (trial protocol v2.1): a labeled session is ineligible for
TP/FP/FN scoring unless phone-side elapsedRealtime is present and non-null on
scored samples; host receipt time is unusable for label correlation (observed
17–25 s transport lag). The APK emission side is discover's lane; this consumer
parses the field on arrival without further change.

## Node clock-domain reading, and why Redmi10 stays unknown

Each node's `clock_domain` in the `space` snapshot resolves
`SITE/body/clock-domain-<node>.json`, published by `tools/clock_offset.py`. That
reading is what separates the two terms of an acquisition span (`transport latency
+ host wall − phone wall`), which this consumer can only bound from above on its
own. A missing document is `unknown/no-clock-domain-file` — never a zero-offset
assumption — and the node's readings stay labelled `fresh-clock-conditional`
until it exists.

The document also names the device it measured: `device_serial`/`device_model` are
the device's own `getprop ro.serialno`/`ro.product.model`, read in the same run and
`null` when that read fails. They are the device's answer, not the `--label` the
operator passed, and the pane prints them (`clock-domain provenance: measured on …`),
so a document filed under the wrong node is visible where it is read instead of only
in the file. The producer additionally refuses to publish an `ok` reading whose
measured serial the site's activation record (`SITE/body/activation.json`,
`<node>_serial` keys) attributes to a *different* node: it publishes
`status="unavailable"`, `reason="label-serial-mismatch: serial <s> is <node>"` and
null offsets instead. A serial the record does not name is published with its
identity rather than refused, and an unreadable record only narrows the check.

The document also carries the host's own NTP verdict (`host_ntp_synchronized`,
from `timedatectl show --property=NTPSynchronized`; `null` when unreadable), and the
pane renders it beside the offset: `measured phone/host offset +24.8s behind host
(… host_ntp_synchronized=false: the host clock is itself unsynchronized, so part of
this offset is host error, not a measured phone error)`. The offset is a difference
(`host wall − phone wall`), not a verdict on which clock is wrong — on 2026-10-17
this host ran ~22 s ahead of true UTC while the phone was ~2.7 s behind it (health
DM 105987) — and the producer refuses to assume either clock is closer to true UTC,
so the field is published as provenance and the consumer repeats it instead of
adjudicating. The functional derivation is unaffected (`latency = span − offset`
cancels the host error); only attribution changes. An absent, unreadable or
non-boolean field renders as `host_ntp_synchronized unknown`, never as
synchronized, and a pane with no measured offset at all carries no host clause.

- **Note3**: the producer measures a paired round trip over adb
  (`adb shell date +%s` against the host wall clock; 1 s quantization,
  `rtt_max_s/2` extra uncertainty). Live 2026-10-16T18:30:10Z:
  `offset_nominal_s` 25.085 inside `24.585..25.585`, `samples` 3,
  `validity_seconds` 3600, `device_serial` `4d00553d61ab90b7`, `device_model`
  `SM-N900`.
- **Redmi10**: no document, so `unknown/no-clock-domain-file`. Cause: the
  producer's only method is an adb round trip, and Redmi10 is not on USB (tailnet
  HTTPS only); the protocol exposes no phone wall-clock request surface — the
  action grammar's `clock` is `elapsedRealtime`, and an observation row carries
  the phone wall clock only at collection time, so a receipt time bounds the
  offset from above alone (backlog residence is unbounded, protocol README:108).
  No two-sided reading is derivable from the current surfaces. A hand-annotated
  `clock-domain-redmi10.json` carrying Note3's own offset (measured 2026-10-16 and
  mislabelled) sat in the site until it was retired to `SITE/artifacts/`; the
  producer's label/serial refusal above is what keeps that mislabelling from
  recurring, and the identity fields are what make it visible if it does.
- **Retry condition**: an adb path to the node, or a validated transport-paired
  measurement. A candidate (not implemented, not validated) is to bracket a phone
  wall-clock reading between host send and receipt, or to pair a same-session row
  with a later `elapsedRealtime` reading; either must handle the wall-clock-step
  hazard (`jump`) before it may publish an interval.

## Per-session excursion log (phone-clock windows)

Each finalized hello session yields one append-only line in
`SITE/body/perception/excursion-log-NODE.txt` (bounded to the last 128 lines
per node, atomically replaced). The line is emitted when a later hello
finalizes the session; a silent or frozen phone produces no churn. Fields:
`session`, `cursor_start`/`cursor_end` and `sequence_start`/`sequence_end`
(join keys; the consumer event_id is `node:session:sequence`),
`retained_count`, `window_truncated`, `phone_elapsed_ms=[min,max]`,
`phone_window_reason`, `acquisition_span_ms=[min,max]`, `freeze_overlap` with
`freeze_class` and `freeze_sequence`, and the protocol v2.1 per-excursion
retention set: `light_std`, `accel_std`, `rssi_std` (windowed standard
deviations over the retained window, same population formula and minimum
sample count as the live stillness composite; null with fewer than two
samples), `light_oscillation` (adjacent 0↔1 lux flip path such as `0->1->0`,
`quantized` for a constant stream confined to the two-level grid, `none`),
`light_transient` (`revert` when the flip path returns to its starting level,
`open` when it does not, `none` without a flip).

The same line carries the calibration-free accel guard: `accel_guard` (`ok`,
`few-samples`, `pinned-axis`, `implausible-magnitude`), `accel_samples`,
`accel_pinned_axes` (`null` or the pinned axis names), `accel_magnitude_median`
and `accel_magnitude_std`. An excursion whose accel guard is not `ok` is
indeterminate for the accel leg and must not be scored as still or moving.

The retention set is required by the space-trial protocol v2.1: an excursion
missing any of these conditions scores `indeterminate`, never silently
excluded. The fields describe the retained window only; `freeze_affected` is
carried as `freeze_overlap`.

The phone window is pure phone-clock: `phone_elapsed_ms` is phone-monotonic
elapsedRealtime, not Unix, and phone/host clocks are unsynchronized, so no
wall-clock label alignment is claimed. Sessions of more than 32 records emit
`window_truncated=true`; the bounds then cover only the retained tail, not the
whole session. Sessions without any retained `phone_elapsed_ms` (protocol v1)
emit null with `phone_window_reason=no phone_elapsed_ms in retained window`,
never interpolated. `acquisition_span_ms` is a separate cross-clock transport
diagnostic and is never folded into the phone window. When a documented freeze
onset (`SITE/discovery/space-light-freeze.json`) falls inside the window's
sequence range, `freeze_overlap=true` marks the span indeterminate per the
trial-eval convention (wake 35388): frozen spans score indeterminate, never
still/moving.

Backward compatibility: state files written by a pre-v2 consumer lack the two
host receipt keys; the snapshot renders them null instead of failing, and the
first v2 poll replaces the item.
## Restart and local data

The node's source endpoint, cursor, raw bounded evidence and transition history are
committed together to `SITE/body/perception/NODE.json` by private atomic replacement,
file `fsync`, then directory `fsync`. Only one fixed temporary file per destination
is used under the follower lock, so repeated crashes do not accumulate anonymous
temporary files. Restart uses that exclusive cursor rather than reinterpreting
the entire server history. The local JSON is an implementation file,
**not** an HTTP API. State is endpoint-bound; changing its source fails closed.
A malformed complete page never advances the cursor. Unknown observation payloads
remain observations if their queue envelope is valid.

The first launch starts at cursor zero and may spend time draining historical pages.
At-least-once phone uploads can duplicate content under new queue IDs; this reader
advances the queue but does not mistake timestamps for ordering or new receipts for
fresh samples. It promises neither exactly-once events nor lossless history. A
rendezvous rollback that grows past the saved cursor is not detectable by protocol
v1. Local state corruption/storage failure is fatal rather than silently resetting.

Keep the whole site ignored and on a trusted local filesystem supporting `flock`,
atomic rename and `fsync`. Never commit credentials, perception files or real phone
observations. View files are disposable caches; the per-node state is authoritative.

Deterministic boundary checks (synthetic data only):

```sh
python3 -m unittest discover -s experiments/perception -v
```

They cover dynamic stale views after follower death, delayed backlog/resumption,
durable cursor/unknown-field restart, absence versus unknown, future/sample-age
constraints, no timestamp-only wakes, and malformed-page atomicity. A synthetic
check is not proof of Note3/Redmi hardware, Android scheduling, or a running plant;
those require observing the real reader/phone path.
