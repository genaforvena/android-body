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
```

`view` is the detailed upper-pane/sensor-check surface: source endpoint, observation
cursor, capability presence/absence/unknown, original battery fraction/charging,
light lux, acceleration axes (m/s²), accuracy/age fields, original phone event/sample
time, and consumer receipt time. Unknown names and extra fields remain raw rather
than being rejected or silently stripped. The bounded state retains the latest 32
event kinds, last 32 observations and last 16 action receipts. An unknown event
is not treated as evidence of a known sensor.

`events` is a compact wake-friendly surface with source, current freshness/errors,
capabilities and coarse measured buckets plus the last four meaningful transitions
and latest action receipt. Ordinary sequence, sample timestamp, receipt timestamp,
accuracy and `age_ms` churn do not produce a new event. Coarse buckets are battery
fraction in 0.05 steps (with charging state), `floor(log2(1 + lux))`, and acceleration
magnitude in 1 m/s² steps. They are **change filters**, not substitute measurements:
read `view` for exact raw evidence. Capability/freshness/error/session transitions
and action receipts also change this surface. No occupancy claim is made.

Both commands recompute freshness against the current host clock, including when
the follower has died. Use the CLI rather than blindly trusting an old cached
`view.txt`/`events.txt`. While running, the follower publishes these files beneath
`SITE/body/perception/`. `events.txt` is rewritten only if its text changes; stdout
also contains only meaningful transition lines, not every polled snapshot. Exit
zero from a view means it rendered evidence, **not** that any phone is healthy.

## Freshness and honest limits

- `fresh-clock-conditional` means the phone timestamp is within the configured
  window and no known sample-age constraint disqualifies it. Phone/host clocks are
  not synchronized by this consumer. More than five seconds future-dated is unknown,
  not fresh. Ordinary clock skew can make good samples unusable.
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
