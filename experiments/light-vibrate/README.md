# Light → vibrate

A deterministic consumer experiment. The Android APK observes; this machine runs
`curl` and POSIX `awk`; the rendezvous transports text. None of these tools need to
be installed on the phone.

Start the [minimal rendezvous](../../rendezvous/minimal-server/README.md), install
the APK, enter its node endpoint and secret, and switch it ON. Use a phone that
actually reports a light sensor and vibration capability. An absent sensor is an
observation, not a measured zero.

## Two curl requests

On the consumer machine, put the same node secret in `BODY_SECRET`. Set `BODY`
to your real endpoint. HTTPS is recommended; the LAN address below is only for an
explicitly enabled, trusted-LAN HTTP test.

```sh
BODY='http://192.168.1.20:8080/node/note3'
# BODY_SECRET must already be set to this node's secret. Do not paste it in a repo.
```

Read observations. Feeding the header through stdin avoids including the secret
itself in curl's process arguments:

```sh
printf 'header = "Authorization: Bearer %s"\n' "$BODY_SECRET" |
  curl --config - --fail --show-error --max-time 15 \
    "$BODY/observations?after=0"
```

The first number is the observation queue ID, followed by the phone's timestamp
and observation. Real light observations may include accuracy and sample age:

```text
1 1712345678 hello node=note3
2 1712345678 cap light
3 1712345679 light lux=82.0 accuracy=3 age_ms=20
```

Request one 200 ms vibration:

```sh
printf 'header = "Authorization: Bearer %s"\n' "$BODY_SECRET" |
  curl --config - --fail --show-error --max-time 15 \
    -H 'Content-Type: text/plain; charset=utf-8' \
    --data-binary 'vibrate duration=200' "$BODY/actions"
```

A successful response such as `1` means **action ID 1 was queued**. It does not
mean the phone received it or vibrated. Read observations again with `after=3`
(or your actual last observation ID), and look for that action's requested and
result records. Android reports physical verification as unverified. A timeout
leaves the append outcome uncertain: inspect the action queue before retrying, or
you may request another vibration under a different ID.

## Bounded awk detector

```sh
export BODY_SECRET  # already configured; never commit it
STATE_FILE="$HOME/.body-note3-light-state" \
  ./experiments/light-vibrate/watch-light.sh 'https://your-real-host/node/note3'
```

For the explicitly insecure LAN setup only:

```sh
ALLOW_INSECURE_HTTP=1 STATE_FILE="$HOME/.body-note3-light-state" \
  ./experiments/light-vibrate/watch-light.sh "$BODY"
```

Default behavior:

- Poll observations every 2 seconds, for at most 300 polls (about 10 minutes plus
  request time), or stop sooner after 10 action attempts
- Consider the latest usable light state in each received batch
- Queue `vibrate duration=200` when lux is below 10 and the detector is armed
- Rearm only after a real light sample at or above the threshold
- Allow no more than one request every 30 seconds and one request per batch
- Ignore unknown, malformed, stale, implausible, and future-dated readings
- Require sample timestamps no older than 30 seconds; when supplied, age_ms must
  also be within 30 seconds. Keep phone and consumer clocks reasonably aligned
- Validate optional accuracy/age_ms fields; missing fields remain unspecified
- Persist the observation cursor, arming state, last request time, and total
  attempts, bound to the exact endpoint
- Stop on malformed/gapped sequences, server errors, or ambiguous action outcomes
- Never automatically retry an action append

All limits are consumer-side environment variables:
`THRESHOLD_LUX` (default 10), `DURATION_MS` (200; range 1–2000),
`COOLDOWN_SECONDS` (30), `POLL_SECONDS` (2), `MAX_AGE_SECONDS` (30),
`MAX_ACTIONS` (10; maximum 100), `MAX_POLLS` (300), and `STATE_FILE`.
Ctrl-C stops. A successful HTTP append is printed as queued, with physical
vibration explicitly unverified.

The state is checkpointed **before** POST with an atomic file rename. The shell
runner does not fsync it; loss of storage or power can lose this checkpoint. This chooses possible missed effects
over blind retries: a crash after checkpointing and before the POST may skip a
vibration. An ambiguous response also counts as an attempt. Deleting the state
resets the limits and cursor and may replay still-fresh observations; do so only
intentionally with the phone OFF. A lock directory protects each state file. A
hard crash can leave a stale lock; stop any other runner and inspect before
removing it. Treat the state directory as private and trusted.

The first run reads from observation ID zero. Old records are advanced past but
do not trigger actions; large histories may take time to catch up. An on-change
light sensor may stop producing samples while illumination is stable; stale data
is ignored rather than treated as a fresh measurement. That can legitimately
produce no action.

## Synthetic verification

```sh
python3 -m unittest discover -s experiments/light-vibrate -v
```

Tests cover the actual Android light text, unknown/stale samples, bounds,
cooldown, reset/rearm, latest-sample behavior, cursor rejection, and a real
curl→local-server→awk→action roundtrip with fake observations. No phone is
contacted and no physical effect is requested by the tests.

## Why awk

Any body that speaks this text protocol can supply observations. A deterministic
state machine, shell script, awk program, or model-backed consumer can read the
same boundary. Mishe could eventually discover useful correlations, test a rule,
and help turn it into a deterministic detector. That learning/compilation loop
is an architectural possibility, not implemented behavior in this MVP. The
Android application remains only a sensory/actuator bridge.
