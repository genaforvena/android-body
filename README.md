# Android Body

A tiny native Android application that turns an old phone into a sensory and actuator node. Install an APK, enter a rendezvous endpoint and secret, press **ON**.

The phone observes. Your program reasons. HTTP carries text between them.

**[Download and install the checked APK](downloads/README.md)** · [Verification evidence](docs/verification.md) · [Text protocol](protocol/README.md)

## First milestone

- Battery, ambient light and accelerometer observations, with explicit absent/unknown/stale states
- One bounded actuator: vibration, 1–2,000 ms with a three-second cooldown
- One primary ON/OFF control; saved ON can restore visibly after process loss/reboot where Android allows
- Truthful foreground notification: sending, offline collection or collect-only, with OFF action
- Durable bounded per-endpoint storage and a simple collect-only/upload-later checkbox
- Outbound HTTP(S) only: no inbound device port, account or Google services
- Platform Java APIs; no runtime dependencies, Compose, Termux, Python or Node on the phone
- Android 4.3/API18 minimum, compile/target API36; API18 includes the original Note 3 software baseline
- Minimal Python-standard-library rendezvous and a shell/awk light-to-vibration experiment

Original code and documentation are dedicated to the public domain under [CC0-1.0](LICENSE). See [third-party notices](NOTICE).

## Build and install

Use JDK17 (or a compatible newer JDK), Android SDK platform36 and build-tools35.0.0. The checked-in Gradle wrapper pins 8.11.1; Android Gradle Plugin is 8.10.1.

```sh
export ANDROID_HOME=/path/to/android-sdk
sdkmanager 'platforms;android-36' 'build-tools;35.0.0'
./gradlew :app:assembleDebug :app:lintDebug :app:testProtocol :app:testSpool
adb install -r app/build/outputs/apk/debug/app-debug.apk
```

Alternatively, open this directory in Android Studio and build the app module. The debug APK is signed for testing, includes legacy v1 plus modern v2 signatures, and is not a release-signing identity. CI uploads the APK as `android-body-debug`. Keep a consistent signing key for upgrades; do not commit private signing keys.

On a phone without adb, copy the APK, open it and approve Android's per-app installation permission as appropriate to that OS. Never disable security checks or install an APK from an untrusted source. A real-device test is still required; a successful build does not certify Note3/Xiaomi hardware behavior.

## Start the rendezvous

Python3 is needed on a computer/server, not on the phone. In a terminal:

```sh
export BODY_SECRET="$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')"
python3 rendezvous/minimal-server/server.py --node note3:BODY_SECRET
```

This binds loopback by default. See the [server README](rendezvous/minimal-server/README.md) for durable data paths, caps, HTTPS reverse proxy and explicit insecure LAN development mode. Do not expose the plain HTTP example server directly to the Internet.

Configure the phone with a reachable node base, such as `https://body.example/node/note3`, and the same secret. A phone cannot reach your server computer via that computer's `127.0.0.1`. For a deliberate isolated LAN experiment, bind the server to a LAN interface, enable its insecure mode, and check the app's HTTP opt-in. The UI clearly warns that HTTP exposes the secret and sensor data.

Press ON. On API33+, allow notification permission; denied/blocked notifications prevent startup. The ongoing notification shows current sending/collection status and has an OFF action. ON is remembered; sticky/boot-after-unlock restoration is attempted where Android permits it. OFF disarms restoration, releases the CPU wake lock, cancels vibration/network work and retains saved observations.

For offline recording, check **Collect only / upload later**. It makes no new HTTP requests or remote actions, and needs no deliberately broken endpoint. Keep the real node configuration; uncheck while ON to upload its backlog and resume queued vibration requests. Collection continues independently of network retry delays. Queues are bounded: the default 2 MiB / 24,576-line buffer is roughly 10 hours of sensor snapshots at representative record sizes. Actual retention depends on line lengths and action/startup traffic. Old records are then evicted with an explicit overflow report. [Full storage and delivery semantics](protocol/README.md#delivery-collection-and-restart-semantics).

ON uses more battery and can produce heat. Android Doze, Force stop and Xiaomi restrictions still apply. The app cannot promise immunity from OEM process kills; [model-scoped Xiaomi settings and limitations](docs/compatibility.md#xiaomi-miui-and-hyperos) explain user-selectable mitigations. If Android pauses a saved-ON session, switch OFF then ON to resume. Never leave a damaged/swollen old phone charging unattended.

## Observe and request an effect

```sh
export BODY_ENDPOINT=https://body.example/node/note3
curl --fail-with-body -H "Authorization: Bearer $BODY_SECRET" \
  "$BODY_ENDPOINT/observations?after=0"

curl --fail-with-body -H "Authorization: Bearer $BODY_SECRET" \
  -H 'Content-Type: text/plain; charset=utf-8' \
  --data-binary 'vibrate duration=200' "$BODY_ENDPOINT/actions"
```

The POST returns the assigned action ID. Poll observations for its result. `succeeded ... evidence=api_return verification=unverified` means Android accepted the request, **not** that the motor physically ran. An interrupted result is explicitly unknown. Do not blindly retry a physical action.

Try the [light/vibration experiment](experiments/light-vibrate/README.md). Its consumer logic works with shell and awk; Mishe can use exactly the same text boundary. No Mishe code or model credential is embedded in the phone.

## Checks and truthful scope

```sh
tools/test-protocol.sh
tools/test-spool.sh
python3 -m unittest discover -s rendezvous/minimal-server
python3 -m unittest discover -s experiments/light-vibrate
./gradlew :app:assembleDebug :app:lintDebug :app:testProtocol :app:testSpool
```

See the [verification record](docs/verification.md), [compatibility and physical validation](docs/compatibility.md), [observations](docs/observations.md), [actions](docs/actions.md), [integration](docs/integration.md), and the [wire protocol](protocol/README.md). Physical Note3, Xiaomi and contemporary-device checks remain explicit rather than inferred from emulator/host tests.

This is a first milestone, not unattended-production device management. No perfect delivery, no remote shell, no camera/microphone/location, no dashboard, no plugin system. Five-second snapshots are retained across network outages/process death within explicit storage bounds; raw sensor events between snapshots and OS scheduling gaps are not retained. Action cursors favor avoiding duplicate physical effects over guaranteed execution after a crash. The queues can be replaced without changing what the phone is for.
