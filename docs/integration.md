# Reasoning lives outside the phone

Android Body owns physical I/O and truthful reports. The rendezvous holds text queues. A consumer owns interpretation, memory and policy. That consumer may be awk, a deterministic state machine, [Mishe](https://github.com/genaforvena/mishe-tauftauf), a model-backed program or a human using curl; all use the same boundary.

1. Poll `GET /node/ID/observations?after=N` with the node secret.
2. Parse each queue ID, keep its observation text, and advance the consumer's observation cursor.
3. Inspect capabilities, unknowns, freshness and multiple observations. Offline/collect-only backlog can arrive hours later; arrival is not a fresh physical event. Run reasoning outside Android. A low light reading alone does not prove a room is empty or a person arrived.
4. If a bounded vibration is appropriate, POST `vibrate duration=200` to the action queue. Save its assigned ID. This is an intention, not a result.
5. Continue reading observations for that action ID's requested/outcome events. `api_return` is still physically unverified. An interrupted/absent/missing outcome must remain unknown.
6. Seek additional independent evidence when physical verification matters. Do not turn an uncertain result into blind retries.

See [the deterministic light/vibration example](../experiments/light-vibrate/) for a shell/awk feedback loop. It works without an LLM and provides the same text observations Mishe can use. This repository does not assume where Mishe runs, implement its internal API, or store model credentials in the phone. The rendezvous URL remains stable while consumer addresses change.

For multiple phones, use a distinct node and secret for each. Correlate their streams outside Android, preserving each source and clock/freshness uncertainty. There is no built-in “someone moved through the room” event; that is a hypothesis for an external program to justify.

## Development discipline

Keep feedback loops short: change a bounded behavior, run protocol/spool/server tests, build/lint, then validate it on real hardware. Record observed facts separately from guesses. An emulator validates installation/lifecycle and synthetic inputs, not a real light sensor, motor, screen-off behavior or Xiaomi process survival. [The compatibility checklist](compatibility.md) defines the remaining hardware evidence. Avoid adding abstractions before an observed failure requires them.
