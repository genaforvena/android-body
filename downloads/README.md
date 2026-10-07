# Installable first milestone

[Download Android Body APK](android-body-debug.apk?raw=true).

Version 0.2.0 (code 2), Android 4.3/API18 or newer. This debug-signed APK is 88,103 bytes; verify its SHA-256 against [SHA256SUMS](SHA256SUMS). ON is persistent where Android allows restoration. A collect-only checkbox saves observations for later; the default 2 MiB / 24,576-line buffer is roughly 10 hours at representative sizes, with explicit overflow. It needs no Termux, Google services or external runtime on the phone. Set up the reference rendezvous described in the [main README](../README.md), then enter its node endpoint and shared secret.

This is a testing build, not a production release-signing identity. It uses the same signer as the earlier 0.1.0 APK, so that build can be upgraded in place without clearing data. Future independently built debug APKs can have different signing keys; Android will then refuse an in-place upgrade. Uninstalling clears local settings and the action cursor, so reconcile or use a fresh node before reinstalling to avoid replaying old actions. No signing key is published.

See [verification](../docs/verification.md) for actual checks and remaining physical-device tests. Android accepting a vibration API call is not proof that a motor physically moved.
