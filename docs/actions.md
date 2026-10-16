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
- `exec <path>` — run the app-written file itself as the direct child of the app process (`ProcessBuilder`, no shell command line); owner-exec is set first

Non-allowlist paths return `failed reason=read_denied|write_denied|exec_denied path=<path>`. Output is bounded to 1024 bytes per command and 65536 bytes per session, with a 10-second timeout and 128 commands per session; each outcome is emitted as two spool lines, each within the 1,007-byte observation-line budget, and a clamped outcome reports `truncated=true`. Eval is skipped in collect-only mode and is not advertised in hello capabilities. See the [minimal-substrate investigation](../experiments/minimal-substrate/README.md) for the full programme context.

`write` and `exec` are in the published download (`87b36024…`, source `e0ea84d`) but not in the Note3 install (`5e7fa255…`, source `0c83e32`), which answers them `failed reason=invalid_arguments`; write/exec remain unexercised on a device. A `write` receipt echoes the command, and the outcome clamp bounds that echoed value first, so a write whose receipt would exceed the 1,007-byte line budget is accepted with `truncated=true` instead of disarming the session; the pre-clamp overflow is recorded in [verification](verification.md).

`exec` classification arrives inside a `succeeded` eval row's `output=`: `uid=<app uid> exec cmd=<path> output=<merged stdout+stderr, ≤4096 B> exit=<n>`, `exec cmd=<path> unavailable reason=<exception class + message|dac-setup>`, or `exec cmd=<path> timeout reason=no-exit destroyed=<true|false>` (≤5 s, then the child is destroyed and reaped for up to 1 s). **An exec target must not background processes:** `destroyed=` reports whether the direct child was reaped, and `Process#destroy()` signals only that child, so a descendant it spawned is reparented and survives an ON-session stop. Parse the `unavailable`/`timeout`/`destroyed=` tokens rather than the message text; the wording of the over-bound classification (a target emitting more than 4096 B is currently reported `unavailable reason=IOException exec output exceeds probe bound`) is not settled.

Collect-only makes no action requests and executes no remote commands. Returning to sending mode also resumes queued, previously unconsumed vibration commands after the observation backlog drains. There is no command expiry in this small protocol; consumers should not enqueue time-sensitive physical effects for an offline body. Persisted cursors prevent replay of consumed commands, not execution of new commands queued during an outage.
