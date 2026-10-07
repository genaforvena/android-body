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

## Persistent perception and a development plant

The [read-only perception consumer](../experiments/perception/) maintains a bounded
per-node cursor and evidence view on the host. It shows original battery, light and
acceleration observations, clock-conditional freshness, backlog, unknowns and action
receipts. Its derived acceleration magnitude includes gravity; it is not an occupancy
or movement verdict. The compact event view filters ordinary sample-time churn so a
resident can respond to meaningful evidence changes rather than every snapshot.

Plant Mishe in a separate local clone of this repository using the core's
[planting procedure](https://github.com/genaforvena/mishe-tauftauf#plant-your-first-instance).
Keep the shared Mishe runtime outside the APK; keep plant chat, charters, credentials,
queues and device evidence under the ignored site. Customize the existing senses,
health and research views for physical I/O instead of copying a hardware driver into
Mishe. Developing an organ, using its observations and researching a portable evaluator
are distinct responsibilities; a retained observation is not an executable program.

For a USB-connected API21+ phone, a private development connection can use:

```sh
adb -s PHONE_SERIAL reverse tcp:8765 tcp:8765
```

Bind the rendezvous to host `127.0.0.1:8765`, configure the phone with
`http://127.0.0.1:8765/node/NODE`, and explicitly enable the app's HTTP option.
The connection travels through the authorized USB debugging transport, not an exposed
LAN listener. Each phone needs its own node and secret. Mapping loss stops delivery;
local collection can continue, and a reconnect must not relabel delayed data as fresh.
Repeated transport loss occurred while polling `reverse --list` on the old Samsung
Android5 handset and stopped after replacing that probe. The daemon cause remains
unverified; avoid that inspection on this Note3 and observe ADB attachment generations
and the actual perception stream instead.

For a Redmi10, install the checked APK, provision its distinct node, and establish
its USB mapping before ON. Allow the app's notification permission when requested.
This does not establish Xiaomi screen-off survival: test the actual device without
silently changing its battery/security policy. An untethered phone instead needs a
reachable, normally validated HTTPS endpoint; the host's loopback URL alone is not
reachable over Wi-Fi.

## Development discipline

Keep feedback loops short: change a bounded behavior, run protocol/spool/server tests, build/lint, then validate it on real hardware. Record observed facts separately from guesses. An emulator validates installation/lifecycle and synthetic inputs, not a real light sensor, motor, screen-off behavior or Xiaomi process survival. [The compatibility checklist](compatibility.md) defines the remaining hardware evidence. Avoid adding abstractions before an observed failure requires them.
