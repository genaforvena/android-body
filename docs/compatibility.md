# Android compatibility and physical validation

Research checked: 2026-10-07. This is a compatibility plan and a list of known limits, not a hardware certification. A bounded physical smoke ran on Samsung SM-N900 / Android5 / API21; Xiaomi and current-device checks remain unrun. See [verification](verification.md) for the exact observed scope.

## Scope and build baseline

The phone runs an ordinary, platform-only Java Android APK. No Python, Termux, Node.js, root, Google Play services, or separately installed runtime is required on the phone. The configured HTTP(S) bridge must be reachable for upload; collect-only can operate offline. the Android APK does not supply the remote agent or server. JDK and Gradle are development-machine requirements only.

| Component | Pinned baseline | Status |
| --- | --- | --- |
| Minimum Android | `minSdk 18` (Android 4.3) | Intended API floor; physical validation pending |
| Compile / target SDK | `36` / `36` | Android 16 API contract |
| Android Gradle Plugin | `8.10.1` | Listed patch release in the official AGP 8.10 notes |
| Gradle | `8.11.1` | Official minimum/default for AGP 8.10 |
| Build JDK | `17` | Official minimum/default for AGP 8.10 |

Android's AGP 8.10 compatibility table explicitly supports API level 36. It lists SDK Build Tools 35.0.0 as its default, so compile SDK 36 does not by itself require pinning Build Tools 36. These are documented compatible versions; they do not establish that a build or installation was executed here. See [official AGP 8.10 release notes, including 8.10.1](https://developer.android.com/build/releases/agp-8-10-0-release-notes).

## Device and API boundaries

- **Samsung Note 3:** check the exact model and installed Android version. The name alone does not establish compatibility. Android below 4.3/API 18 cannot install this APK; the original Note 3 API18 baseline is included. Samsung documented a 4.4.2 update for specified Korean carrier models, but that does not establish the firmware on a particular handset. Check Settings → About device before attempting installation. [Samsung's model-scoped update announcement](https://news.samsung.com/kr/%EC%82%BC%EC%84%B1%EC%A0%84%EC%9E%90-%EA%B0%A4%EB%9F%AD%EC%8B%9C-%EB%85%B8%ED%8A%B8-3%EC%97%90-%EB%B3%B4%EB%8B%A4-%EC%99%84%EB%B2%BD%ED%95%9C-%EC%95%88%EB%93%9C%EB%A1%9C%EC%9D%B4%EB%93%9C-%ED%82%B7)
- **Xiaomi:** model, Android version, MIUI/HyperOS release, background restrictions, and lock-screen behavior remain unknown until tested. Do not promise a particular settings path, a vendor exemption, or uninterrupted operation. Record any user-selected battery settings with the results; do not silently change them.
- **API 18–25:** use the older service start path and notification APIs; newer classes must remain behind SDK checks. Battery telemetry uses the battery broadcast rather than assuming newer battery-property APIs exist. [BatteryManager reference](https://developer.android.com/reference/android/os/BatteryManager)
- **API 26+:** create a notification channel, use `startForegroundService()`, and promote immediately with `startForeground()` before network or sensor setup can block. Android requires promotion within five seconds. [Service lifecycle](https://developer.android.com/develop/background-work/services)
- **API 28+:** declare `FOREGROUND_SERVICE`. Background-only sensor collection is restricted; ongoing collection belongs in the visible activity or the active foreground service. [Foreground-service changes](https://developer.android.com/develop/background-work/services/fgs/changes), [sensor restrictions](https://developer.android.com/develop/sensors-and-location/sensors/sensors_overview)
- **API 31+:** an initial ON action starts from the visible activity. Background starts require an OS exemption; boot and package replacement are covered below. Handle a rejected launch rather than claiming the session is running. [Background-start restrictions](https://developer.android.com/develop/background-work/services/fgs/restrictions-bg-start)

## User-visible operation and service type

ON is an explicit, persistent user choice. Persist the desired state separately from whether the process is actually running. A displayed saved ON state is not proof of live observations, a working connection, or a delivered upload. OFF and the app's notification Stop clear the desired state before cleanup; every teardown cancels network work, unregisters sensor listeners and battery receivers, cancels vibration, and releases the wake lock. Do not clear the user's ON choice merely because an ordinary system teardown occurred. The restoration rules below remain subject to OS and manufacturer limits.

On API 33+, request `POST_NOTIFICATIONS` in context. **The app requires notification permission for an active session**, including restoration. This is an application policy: Android permits an FGS without that permission, but hides its notice from the notification drawer while retaining a Task Manager entry. Check app-level notification blocking on API24+, channel blocking on API26+, and runtime permission on API33+ before starting or restoring, and during operation. If a check fails, stop active work and expose the reason on the next app visit; never silently fall back to hidden collection. API18–23 lacks the platform `areNotificationsEnabled()` check, so notification visibility there remains a manual test. Permission changes may kill the process, making rechecks on recreated service entries necessary. [Notification permission behavior](https://developer.android.com/develop/ui/compose/notifications/notification-permission), [permission-change exit reason](https://developer.android.com/reference/android/app/ApplicationExitInfo#REASON_PERMISSION_CHANGE)

The notification must distinguish collecting locally, sending/uploading, waiting/retrying, and failure rather than reporting every ON state as a successful upload. Request `FOREGROUND_SERVICE_IMMEDIATE` on API31+ to avoid the platform's initial notification deferral. Android14+ lets users dismiss ordinary ongoing notifications while the phone is unlocked; `setOngoing(true)` does not make this app's notice impossible to hide. The app wires user dismissal to the same OFF/disarm action as the notification button. Permission/channel checks test permission to display, not that the user currently sees the notification. Updates coalesce to at most once every two seconds. Test notification dismissal separately from its Stop action, and do not claim an unhideable notification. [Immediate foreground notification](https://developer.android.com/reference/android/app/Notification.Builder#setForegroundServiceBehavior(int)), [Android14 notification dismissal](https://developer.android.com/about/versions/14/behavior-changes-all#non-dismissable-notifications)

On API 34+, the manifest needs `foregroundServiceType="specialUse"`, `FOREGROUND_SERVICE_SPECIAL_USE`, and a service-level `android.app.PROPERTY_SPECIAL_USE_FGS_SUBTYPE`. The subtype should explain the actual work, for example:

> User-started, user-stoppable remote device bridge that continuously observes battery, ambient light and accelerometer state and receives bounded vibration commands during an explicitly enabled session, with an ongoing notification.

This is an engineering justification for an immediate, ongoing device-interaction session that does not cleanly fit the standard service types. It is not a Google Play approval or an exemption from system power management. Android documents `specialUse` for valid FGS work outside the other types and requires an informative subtype; Play reviews the declaration. Do not relabel the session as location, health, media playback, or data sync merely to obtain background execution. [Official service-type requirements](https://developer.android.com/develop/background-work/services/fgs/service-types#special-use)

## Restoring an enabled session

`START_STICKY` asks Android to recreate a started service after ordinary process loss; it does not promise immediate recreation or uninterrupted sampling. A recreated service may receive a null intent. Read the saved desired state and settings again, validate them, and require notification visibility before collecting or uploading. Android's API31 background-start restriction does not apply to the system's recreation of a sticky foreground service; it still applies when the app itself requests a new background start. OFF must use the normal stop path and return `START_NOT_STICKY`, rather than leaving a sticky session eligible for restoration. [Service restart semantics](https://developer.android.com/reference/android/app/Service#START_STICKY)

In this implementation, restoration requires both the desired-ON preference and a matching endpoint enable marker. OFF deletes the marker independently of its preference write; either successful operation prevents restoration. If both writes fail, the current session still stops and the UI explicitly requires Android Force stop before reboot. A local storage error also disarms and stops collection.

An explicit ON records the latest process-exit timestamp as a baseline. A newer API30+ `REASON_USER_REQUESTED` disarms restoration; old records do not override a later explicit ON. Ambiguous update/Recents reasons can therefore conservatively suppress restoration. The activity does not automatically start a paused session merely because it was opened; the user can switch OFF then ON to resume.

The supported boot/update restoration contract is:

1. Declare `RECEIVE_BOOT_COMPLETED` and a manifest receiver for `BOOT_COMPLETED` and `MY_PACKAGE_REPLACED`. Restore only a previously enabled session, never a fresh install or a saved OFF state. `MY_PACKAGE_REPLACED` is delivered to the app whose existing installation was updated. [Boot broadcast](https://developer.android.com/reference/android/content/Intent#ACTION_BOOT_COMPLETED), [package-replacement broadcast](https://developer.android.com/reference/android/content/Intent#ACTION_MY_PACKAGE_REPLACED)
2. Use normal credential-protected preferences and storage. Do not register for `LOCKED_BOOT_COMPLETED` or move the endpoint secret into device-protected storage. On encrypted devices, restoration waits for the first unlock after reboot. [Direct Boot storage guidance](https://developer.android.com/privacy-and-security/direct-boot)
3. Check the desired state, settings, and notification eligibility before requesting a service start. On API26+ use `startForegroundService()` and promote immediately before network or sensor work; on API18–25 use `startService()` and the foreground notification. Recheck inside the service to handle races.
4. On API31+, receipt of `BOOT_COMPLETED` or `MY_PACKAGE_REPLACED` is a documented background-start exemption. On API34+, the special-use declaration and permission still apply; this light/accelerometer/battery bridge does not request the while-in-use camera, microphone, location, or health permissions. [Background-start exemptions](https://developer.android.com/develop/background-work/services/fgs/restrictions-bg-start)
5. On API35+, boot receivers cannot launch `dataSync`, `camera`, `mediaPlayback`, `phoneCall`, `mediaProjection`, or `microphone` FGS types. `specialUse` is not on that documented prohibition list; this is not an exemption from the other prerequisites. Android16/API36's documented FGS change subjects jobs launched from an FGS to their usual job quotas; it does not add a special-use boot prohibition. [Android15 boot limits](https://developer.android.com/about/versions/15/behavior-changes-15#boot-completed), [FGS changes through Android16](https://developer.android.com/develop/background-work/services/fgs/changes)
6. Catch rejected starts, including `ForegroundServiceStartNotAllowedException`/`IllegalStateException` and permission/type `SecurityException`. Leave a truthful paused/error state for the activity. Do not install an alarm, job, or tight retry loop to evade the rejection.

**Deliberate system stops are a boundary.** Force-stop keeps an app stopped until the user interacts with it again; sticky services and a boot receiver are not a bypass. Android15+ also delivers `BOOT_COMPLETED` when user interaction removes an app from the stopped state, so that intent is not proof of a fresh device reboot. Android13+ Active apps → Stop removes the whole app and notification without a callback, meaning it cannot synchronously clear a saved ON bit. Android recommends checking `ApplicationExitInfo.REASON_USER_REQUESTED` on the next process start; on API30–33 that reason can also describe updates or component changes, and it can describe a Recents removal. Treat it as evidence with those limits, not a universal force-stop detector. Use the app's OFF control to reliably clear future restoration. Test these distinct paths and document the actual resume behavior. [Stopped-state boundary](https://developer.android.com/about/versions/15/behavior-changes-all#stopped-state), [Active apps Stop](https://developer.android.com/develop/background-work/services/fgs/handle-user-stopping), [exit-reason limitations](https://developer.android.com/reference/android/app/ApplicationExitInfo#REASON_USER_REQUESTED)

On API33+ with this target, a user-selected Restricted battery state can defer delivery of boot broadcasts until the app starts for another reason. Manufacturers determine additional restrictions; on AOSP, Restricted can also prevent foreground starts and remove an existing service from the foreground. A persisted ON choice is therefore an intention to restore when allowed, not a claim of guaranteed uptime. [Android background optimization](https://developer.android.com/topic/performance/background-optimization)

## Sensors, vibration, and missing hardware

- Discover light and accelerometer availability at runtime. Missing hardware must produce an explicit unavailable state, never a fabricated zero reading. Light is measured in lux; accelerometer values include gravity and use m/s². Sensor rate requests are hints, not timing guarantees. [Sensor overview](https://developer.android.com/develop/sensors-and-location/sensors/sensors_overview)
- Use modest sampling. The MVP does not need high-rate motion permission. Android caps applicable listener delivery at 200 Hz unless the high-rate permission is declared. Non-wakeup sensor events can be lost while the application processor sleeps. [SensorManager](https://developer.android.com/reference/android/hardware/SensorManager)
- Distinguish current reading, no reading yet, unavailable sensor, and old observation. Reusing a cached value after sleep must not make it appear freshly measured. Unchanging light readings can also be normal for an on-change sensor; sample age alone does not prove hardware failure.
- Vibration requires the manifest `VIBRATE` permission. Use the legacy `Vibrator` path on API 18–25 and `VibrationEffect` on API 26+. Check hardware availability; device settings and hardware may prevent a perceptible effect. A successful API call is not proof that the user felt vibration. Bound duration and provide cancellation. [Vibrator](https://developer.android.com/reference/android/os/Vibrator), [VibrationEffect](https://developer.android.com/reference/android/os/VibrationEffect)

## Power and screen-off limits

**The MVP holds a partial CPU wake lock only while explicitly ON.** It releases the lock on OFF, start failure and service teardown; the OS releases it on process death. The UI discloses increased battery use. This helps old phones keep non-wakeup sensor and network loops alive with the screen off; it does not keep the display on. No battery-optimization exemption is requested. Screen-off operation remains best effort: a foreground service/wake lock cannot guarantee network access or OEM process survival.

On Android 6/API 23 and newer, Doze can suspend networking and ignore wake locks. An FGS is relevant to App Standby but does not make Doze disappear. Test unplugged and stationary as well as charging; a desk test while plugged in can hide this failure mode. The current design accepts these limits rather than silently requesting an exemption. [Doze and App Standby](https://developer.android.com/training/monitoring-device-state/doze-standby)

An active CPU lock increases battery use and heat. Turn OFF when finished. Test release after repeated ON/OFF and rejected startup. Do not leave a damaged or swollen old phone charging unattended. [Wake-lock guidance](https://developer.android.com/develop/background-work/background-tasks/awake/wakelock)

### Xiaomi, MIUI and HyperOS

Foreground execution and sticky restoration improve resilience but cannot guarantee survival on an untested Xiaomi. Identify the exact model and firmware before giving settings instructions. Xiaomi's own documentation gives these **model-scoped examples**, not one universal path:

- For **Xiaomi 14T Pro**, Xiaomi documents Settings → Apps → Permissions → Background autostart. The user may enable it for Android Body if they want boot restoration. [Xiaomi 14T Pro autostart guidance](https://www.mi.com/global/support/faq/details/KA-507611/)
- For **Xiaomi 15**, Xiaomi attributes some locked-screen/background network interruptions to battery protection, and documents Settings → Battery → the specific app → No restrictions. This is a user-selected battery/availability tradeoff, not a promise that every firmware keeps a service alive. [Xiaomi 15 background network guidance](https://www.mi.com/my/support/faq/details/KA-538010/)
- Xiaomi also documents background locking in Recents and autostart for its Mi Fitness app. That is evidence that these vendor controls exist on supported phones, not evidence that Android Body has an automatic exemption. Do not claim a private vendor API, use Accessibility or overlays to bypass controls, or change global MIUI optimization settings. [Xiaomi's model-dependent background-running guidance](https://www.mi.com/global/support/faq/details/KA-700534/)

Keep app notifications allowed. If an optional battery-settings shortcut is offered, it should open a supported system settings screen and let the user choose; do not silently request a battery-optimization exemption. Test both the default mode and any user-selected changes, including screen-off on battery, overnight gaps, reboot after unlock, and app update. Record the setting labels actually present on that phone.

## Transport and old Android security

HTTPS is preferred. The shared secret is restricted to 32–256 URL-safe ASCII characters. Endpoint validation rejects userinfo, query strings, and fragments. Do not put secrets in URLs or logs.

On legacy SDKs below 22, the client enables supported TLS 1.2 protocols using a socket-factory wrapper while retaining the platform's default certificate trust and hostname verification. TLS 1.2 is supported from API 16, but generic client sockets enable it by default only from API 20. That correction does not modernize an old cipher suite or trust store. [SSLSocket protocol table](https://developer.android.com/reference/javax/net/ssl/SSLSocket)

An old Note 3 may reject a valid modern service because its trust store lacks a CA or the server omits an intermediate. Test the actual endpoint and complete chain on the actual firmware. Never introduce a trust-all `TrustManager`, permissive hostname verifier, or automatic HTTP downgrade to repair a TLS failure. [Android TLS troubleshooting](https://developer.android.com/privacy-and-security/security-ssl)

HTTP requires the explicit insecure-transport checkbox, off by default. Manifest/network policy must allow the intended opt-in path, while application validation enforces the user's choice on every supported API, including old Android versions without modern network-security configuration. Cleartext exposes telemetry, commands, and the shared secret to observation and tampering; an isolated trusted test network reduces exposure but does not encrypt it. [Cleartext policy](https://developer.android.com/privacy-and-security/security-config), [HTTP risks](https://developer.android.com/privacy-and-security/risks/cleartext-communications)

For the target-36 baseline, Android documents LAN access under `INTERNET`; Android 16 also offers opt-in local-network restriction testing. Revisit permissions before raising target SDK to 37, where Android documents a dedicated LAN permission. Do not add an unneeded runtime LAN permission to the target-36 build. [Local-network permission](https://developer.android.com/privacy-and-security/local-network-permission)

## Physical validation checklist

Run the same signed APK against the same controlled bridge, and record APK hash, exact device model, OS/API, firmware, endpoint scheme, test time, battery mode, and result. The checklist remains open where a row combines tested and untested cases; the bounded Note3 observations below do not certify it.

| Device | Required baseline | Status |
| --- | --- | --- |
| Old Samsung Note 3 | SM-N900, Android5/API21, firmware `LRX21V.N900XXSEBRH3`; charging, private USB-loopback HTTP; final 0.2.0 APK | BOUNDED SMOKE PASS: installation, native ON/OFF, actual sensor delivery, collect-only/backlog, process-loss restoration, 15s screen-off; full checklist incomplete |
| Xiaomi | Exact model; MIUI/HyperOS and Android version | NOT RUN |
| Current Android device | API 34+; preferably API 36; notification/type checks | NOT RUN |

- [ ] Install and cold-launch; inspect API compatibility and crashes.
- [ ] ON produces an ongoing visible notification; Stop/OFF ends all work.
- [ ] API 33+: grant, deny, dismiss the permission prompt, revoke notification permission, and block the channel while ON and before a restore attempt. No collection/upload with notifications disabled.
- [ ] API 31+: verify immediate notification appearance. API34+: dismiss the ongoing notification while unlocked and verify the documented dismissal behavior separately from notification Stop.
- [ ] Compare battery level/charging state with system UI. Test a light change and device rotation; verify units, timestamps, and unavailable-sensor behavior.
- [ ] Send one permitted vibration; test bounded duration, cancellation, invalid commands, and absent/disabled vibration hardware.
- [ ] Repeat ON/OFF and rotate/recreate the activity; confirm no duplicate loops or listeners.
- [ ] Test screen off while charging, then unplugged and stationary. Log observation ages and command delays; do not count stale values as new sensor samples.
- [ ] On API 23+, force Doze in a development session and verify graceful pause/recovery: `adb shell dumpsys deviceidle force-idle`, then `adb shell dumpsys deviceidle unforce` and `adb shell dumpsys battery reset`. Record commands and observed effects.
- [ ] Test Wi-Fi loss/reconnect, unreachable bridge, slow replies, server errors, and airplane mode. Confirm bounded retries and responsive OFF.
- [ ] Verify trusted HTTPS success on the actual old device. Invalid certificate/hostname must fail; no downgrade or verifier bypass.
- [ ] HTTP is rejected with the checkbox off and allowed only after explicit opt-in. Check malformed URL and secret validation.
- [ ] Kill an enabled process without force-stop; verify one sticky restored loop, truthful new-session timestamps, notification, and no repeated physical effect. Repeat with saved OFF and confirm no restoration.
- [ ] Reboot while ON, then first-unlock; verify a single visible restoration in the saved mode. Repeat while OFF, with notifications blocked, and with battery mode Restricted. Check API26/31/34/35/36 boundaries where devices are available.
- [ ] Update the APK over an ON installation and then an OFF installation; verify desired state and local data survive, and only an eligible ON session restores. Test API30–33 exit-reason ambiguity separately.
- [ ] Swipe the task away, use Android's Active apps Stop, and force-stop as separate tests. Force-stop must not be bypassed. Verify the next manual launch, Android15+ post-force-stop boot broadcast, and next reboot against the documented desired-state behavior.
- [ ] Xiaomi: record model/firmware and exact autostart/battery settings; compare default and user-enabled settings without claiming either guarantees retention.
- [ ] Collect-only mode: verify zero outbound HTTP while sampling locally. Recreate the process/reboot and inspect retained observations. When the user enables upload later, verify original observation times, truthful queue/drop status, bounded storage, and no replay of consumed actuator commands. Previously unconsumed queued commands have no expiry and may execute when sending resumes.
- [ ] Measure a multi-hour session's gaps, heat, and battery use. Do not label the product reliable for unattended continuous observation until this evidence exists.

Emulator, local unit, and static tests can validate logic but cannot establish OEM retention, physical sensor delivery, actual vibration, old-device TLS trust, or battery behavior.
