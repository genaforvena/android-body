# Minimal rendezvous

Two append-only text files per configured node. Python 3.10+ on Linux/macOS,
standard library only. Python runs on the **rendezvous host**, never on the phone.
This is a small experimental reference server, not a hardened public hosting
service. There is no database, broker, account system, remote shell, or LLM.

## Start locally

From the repository root:

```sh
export BODY_SECRET="$(python3 -c 'import secrets; print(secrets.token_hex(32))')"
python3 rendezvous/minimal-server/server.py \
  --node note3:BODY_SECRET \
  --data-dir ./body-data
```

The default listener is `127.0.0.1:8080`. It is reachable only on that host.
Keep the data directory private, backed up, and on a local filesystem that
supports `flock` and `fsync`. Do not commit the directory or a secret.
Only one process may open a data directory. Restart with the same data directory
and secrets to continue the same IDs.

For another node, generate a different secret in a different environment variable:

```sh
export HALL_SECRET="$(python3 -c 'import secrets; print(secrets.token_hex(32))')"
python3 rendezvous/minimal-server/server.py \
  --node note3:BODY_SECRET --node hall:HALL_SECRET \
  --data-dir ./body-data
```

Stop the first server before starting the second command. Secret values are not
passed in command-line arguments. Both the phone and its consumer use the same
per-node secret, granting read/write access to both queues for that node. There
are no read-only credentials or roles. Use distinct secrets between nodes.

## Connect a phone

Recommended: terminate HTTPS at a reverse proxy on a host you control, forwarding
only `/node/` to `http://127.0.0.1:8080`. Preserve the Authorization header, disable
caching, set request/body/time limits, and use a valid certificate. Keep this
Python listener loopback-bound. Configure the phone with
`https://your-real-host/node/note3` and the same node secret. Never disable
certificate validation to make an old phone connect; update the trust path or use
a supported certificate instead. No proxy or internet deployment is performed by
this repository.

For an explicitly insecure **trusted LAN experiment only**:

```sh
python3 rendezvous/minimal-server/server.py \
  --host 0.0.0.0 --port 8080 --allow-insecure-http \
  --node note3:BODY_SECRET --data-dir ./body-data
```

Use the host's actual LAN IP in the phone, such as
`http://192.168.1.20:8080/node/note3`, and separately enable the app's insecure-HTTP
option. `localhost` on the phone means the phone, not this host. Restrict the
host firewall to the test LAN. HTTP exposes the secret, observations, and action
commands to network observers; never publish this listener directly to the
internet. Stop the experiment when done.

## HTTP contract

All routes require exactly one `Authorization: Bearer <secret>` header. Node IDs
match `[a-z0-9][a-z0-9_-]{0,63}`. Secrets match `[A-Za-z0-9._~-]{32,256}`.
Unknown nodes and incorrect secrets both return `401`.

- Phone: `POST /node/note3/observations`; `GET /node/note3/actions?after=N`
- Consumer: `GET /node/note3/observations?after=N`; `POST /node/note3/actions`
- POST content type: `text/plain` or `text/plain; charset=utf-8`
- POST body: nonempty UTF-8 lines separated by LF; final LF optional
- POST success: `201`, assigned queue sequence IDs only, one decimal ID per line
- GET success: `200`, `ID original-line\n` for each record; empty body if none
- GET `after` is required; `0` means the beginning; IDs start at `1`
- IDs increase contiguously **within each node and each queue**, up to
  `9007199254740991`; action and observation IDs are independent
- `X-Last-Sequence`: last returned ID, or the requested cursor for an empty batch
- `X-Has-More`: `1` if another batch is currently available, otherwise `0`
- Poll again with the last received ID. A read does not consume/delete data
- No redirects, CORS API, long polling, chunked uploads, compression, or JSON

The rendezvous treats command and observation content as opaque text. It does not
claim a command is supported or physically carried out. The phone reports action
outcomes in the observations queue. An action queue ID is not a success receipt.

## Bounds and errors

- At most 64 provisioned nodes; the API cannot create nodes
- POST: 65,536 bytes, 128 lines, 1,007 UTF-8 bytes per input line
- GET: 65,536 bytes, 128 records, 1,024 bytes per prefixed line (excluding LF)
- Empty/whitespace-only lines, CR, tabs, control characters, Unicode line
  separators, and BOM are rejected; a malformed batch appends nothing
- Each queue: 16 MiB by default, configurable with `--max-queue-bytes`
- At most 32 concurrent request workers, 10-second socket inactivity timeout
- No automatic log retention/deletion, dynamic node creation, or disk cleanup

Errors are plain text: `error reason\n`. Relevant status codes:

- `400`: invalid text/body/cursor; `404`: unsupported route
- `401`: missing/wrong/duplicate authorization
- `409 cursor_ahead_of_queue`: requested cursor exceeds this queue's head
- `411`: missing Content-Length; `413`: oversized request; `415`: media/encoding
- `417`: Expect unsupported; `503`: unavailable/uncertain storage
- `507 queue_full`: append would exceed the queue's configured bound

When a queue fills, reads still work and appends fail explicitly. Increase the cap
with enough disk available or stop and deliberately rotate to a **new node ID and
endpoint**. Never silently delete or replace an active log to reclaim space.
A cursor ahead of the current head detects some resets, not every rollback: a
replacement log that has already grown past a saved cursor cannot be distinguished
without an epoch protocol, which this MVP deliberately does not have.

## Persistence and delivery: explicit limits

A successful POST is acknowledged only after the append and `fsync`. Startup
checks every record and rebuilds a compact offset index from the files. Process
concurrency is serialized per queue; a filesystem lock prevents a second server
from writing the same directory.

This is **not exactly-once delivery**:

- If a response is lost after persistence, retrying POST creates new IDs with
  duplicate content. Do not blindly retry physical-action requests.
- A crash during a multi-line write can leave some or all records on disk before
  a response. A well-formed complete prefix may be present after restart.
- A partial final line, invalid record, or sequence gap makes startup fail closed.
  Nothing is silently truncated or repaired. Preserve the files for inspection.
- A write or fsync error quarantines that queue until restart and inspection;
  the server never continues by reusing an uncertain ID.
- `fsync` depends on the underlying storage honoring durability. Sudden hardware
  failure or storage rollback cannot be repaired by this protocol.
- Android checkpoints an action before attempting the effect to avoid replay on
  process restart. A crash can therefore skip an effect or lose its outcome.
  See the app/protocol docs for pending-action recovery observations.

Use bounded, safe effects and inspect observations. An Android API returning
success does not independently verify that the physical motor moved.

## Test

```sh
python3 -m unittest discover -s rendezvous/minimal-server -v
python3 -m unittest discover -s experiments/light-vibrate -v
```

The tests create temporary local listeners and synthetic data. They test restart,
authentication, malformed input, concurrent IDs, bounds, ambiguous writes, duplicate
POST behavior, and the real curl/awk path. They do not test any phone hardware,
Android background restrictions, production TLS, or an internet deployment.
