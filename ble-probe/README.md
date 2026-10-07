# BLE capability diagnostic

Separate application ID `org.androidbody.bleprobe`; never upgrades or shares the Android Body package/data. Min API 18. It reports SDK, adapter state, and (API 21+) scanner/advertiser accessor availability and multiple-advertisement support. It does not start discovery, scan, advertise, toggle Bluetooth, inspect device identities, persist data, or use the network.

`OFF` and null scanner/advertiser accessors are conditional-unavailable, not unsupported. Object availability is not proof of over-air capability. Errors and API<21 queries are explicitly reported. `sampled_at_utc` is the device wall clock, not host-correlated freshness. Keep these manual diagnostic readings out of `watch.py` sensor history.

Build and run the formatter regression test with JDK 11+ and Android SDK platform 34: `./gradlew --no-daemon :ble-probe:testProbeReport :ble-probe:assembleDebug :ble-probe:lintDebug`. The app targets API 28 intentionally for local diagnostics on legacy API18–21 hardware; it is not for Play distribution. Lint disables only the expired target and newer-compile-SDK policy checks for that bounded use.

Do not install unless signer/data preservation and a bounded cleanup route have been independently reviewed. No Note3 runtime result is implied by building the APK.
