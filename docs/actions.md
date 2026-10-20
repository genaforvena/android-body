# Actions

The only implemented command is:

```text
vibrate duration=200
```

Duration must be a canonical decimal integer from 1 to 2,000 milliseconds. No leading zeroes, extra parameters, quotes, repeats or waveform commands. The app enforces at least three seconds between accepted vibration requests; requests inside that interval are consumed with `failed reason=rate_limited`. Rate limiting is per ON session, not a durable global hardware budget.

The app uses `Vibrator` before API26 and `VibrationEffect.createOneShot` on API26+. It cancels current vibration on OFF or when collect-only mode is selected. There is no audio/DND override and no claim that OS acceptance equals physical effect.

For every consumed action it produces a `requested` observation and either:

- `succeeded ... evidence=api_return verification=unverified`
- `failed reason=invalid_arguments|unsupported_action|absent|rate_limited|notifications_disabled|permission_denied|api_error`

The request event carries normalized recognized arguments, not arbitrary untrusted remote text. Unknown commands are not evaluated. `api_error` also carries `verification=unverified`, because a thrown platform call does not establish whether a partial physical effect occurred. If execution or durable outcome recording was interrupted, the next enabled session reports `unknown reason=interrupted verification=unverified` from the persisted marker.

Read [delivery semantics](../protocol/README.md#delivery-collection-and-restart-semantics) before building retries. Resubmitting an action POST creates a new action ID and may run it again. Never automatically retry a physical command merely because its HTTP response or result was lost.

Torch, speech, notification, sound, screen wake and camera are not implemented. A validly numbered unsupported command returns failure and advances the cursor; malformed batches pause uploads/actions without executing anything in that response; local collection continues.

## Bounded eval probes

Since commit `e69d798` (2026-10-11) a second action kind, `eval`, provides a bounded investigation surface. It is not arbitrary code execution — the grammar is a fixed allowlist:

```text
eval identity
eval clock
eval read /proc/self/status
eval read /proc/self/attr/current
eval read /proc/meminfo
eval env
eval write <path> <content>
eval exec <path>
```

- `identity` — UID/groups from `/proc/self/status` (bounded to 4096 bytes)
- `clock` — `elapsedRealtime` milliseconds
- `read <path>` — only the three allowlisted `/proc` paths above; each read bounded to 4096 bytes
- `env` — `/proc/self/status` (bounded)
- `write <path> <content>` — persist a bounded file inside the app's own `files/`; only `\n` and `\\` escapes, other escapes rejected; the receipt reports `wrote path=<path> bytes=<n>`
- `exec <path>` — run the app-written file itself as the direct child of the app process (`ProcessBuilder`, no shell command line); owner-exec is set first. Takes exactly one path and no arguments: a trailing token becomes part of the path and yields `unavailable reason=IOException … No such file or directory`, indistinguishable from a missing target. The child's cwd is the app process's cwd, not the app `files/` dir; targets must derive their own directory (e.g. `d=${0%/*}`).
Non-allowlist paths return `failed reason=read_denied|write_denied|exec_denied path=<path>`. Output is bounded to 1024 bytes per command and 65536 bytes per session, with a 10-second timeout and 128 commands per session; each outcome is emitted as two spool lines, each within the 1,007-byte observation-line budget, and a clamped outcome reports `truncated=true`. Eval is skipped in collect-only mode and is not advertised in hello capabilities. See the [minimal-substrate investigation](../experiments/minimal-substrate/README.md) for the full programme context.

`write` and `exec` are in the published download (`04439ff9…`, source `b025ede`) and in the Note3 install (`87b36024…`, source `e0ea84d`) since 2026-10-16T16:16:48Z; the prior install (`5e7fa255…`, source `0c83e32`) answered them `failed reason=invalid_arguments`. The shared write-then-exec machinery is device-exercised on the new install: the post-install session start (`d4438183`, 16:17:15Z) emitted `probe exec uid=10225 cmd=/data/data/org.androidbody/files/probe.txt output=hello exit=0`, identical to the prior install's session row — no exec-path regression (health wake 101276). Consumer `eval write`/`eval exec` rows remain unexercised on a device: no write/exec action has been posted to either node, and Note3 is collect-only (eval skipped; delivery frozen by design); producing one needs the mode change plus a posted consumer action, not a new session start.

`exec` classification arrives inside a `succeeded` eval row's `output=`: `uid=<app uid> exec cmd=<path> output=<merged stdout+stderr, ≤4096 B> exit=<n>`, `exec cmd=<path> unavailable reason=<exception class + message|dac-setup>`, or `exec cmd=<path> timeout reason=no-exit destroyed=<true|false>` (≤5 s, then the child is destroyed and reaped for up to 1 s). **An exec target must not background processes:** `destroyed=` reports whether the direct child was reaped, and `Process#destroy()` signals only that child, so a descendant it spawned is reparented and survives an ON-session stop. Parse the `unavailable`/`timeout`/`destroyed=` tokens rather than the message text; the wording of the over-bound classification (a target emitting more than 4096 B is currently reported `unavailable reason=IOException exec output exceeds probe bound`) is not settled.

`ok=true` carries only what the reader had observed before the direct child exited (≤4096 B). A descendant that keeps the merged stream open can leave the reader parked at that exit: a write it makes only after the exit reaches the reader only when that reader's blocking read had already begun, and with the shipped 1000 ms reader join a descendant writing later than the join yields `unavailable reason=… exec stdout open at direct-child exit` instead of the bytes. An empty `output=` therefore cannot distinguish "the target printed nothing" from "output was dropped".

Collect-only makes no action requests and executes no remote commands. Returning to sending mode also resumes queued, previously unconsumed vibration commands after the observation backlog drains. There is no command expiry in this small protocol; consumers should not enqueue time-sensitive physical effects for an offline body. Persisted cursors prevent replay of consumed commands, not execution of new commands queued during an outage.
