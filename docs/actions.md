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

Torch, speech, notification, sound, screen wake and camera are deliberately unimplemented. A validly numbered unsupported command returns failure and advances the cursor; malformed batches pause uploads/actions without executing anything in that response; local collection continues.

Collect-only makes no action requests and executes no remote commands. Returning to sending mode also resumes queued, previously unconsumed vibration commands after the observation backlog drains. There is no command expiry in this small protocol; consumers should not enqueue time-sensitive physical effects for an offline body. Persisted cursors prevent replay of consumed commands, not execution of new commands queued during an outage.
