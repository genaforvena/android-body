# Installable first milestone

[Download Android Body APK](android-body-debug.apk?raw=true).

Version 0.2.0 (code 2), Android 4.3/API18 or newer. This debug-signed APK is 73,656 bytes; verify its SHA-256 against [SHA256SUMS](SHA256SUMS). It is a clean build of the pushed tip (`b025ede`), carrying the `4e4caba` bounded-exec reader-contract change, so it carries no orphaned zip entries. The Note3 still runs the previous build (73,358 bytes, `87b36024…`, installed 2026-10-16T16:16:48Z); the signer is unchanged, so an in-place upgrade stays possible.

This is a testing build, not a production release-signing identity. It uses the same signer as the earlier 0.1.0 APK, so that build can be upgraded in place without clearing data. Future independently built debug APKs can have different signing keys; Android will then refuse an in-place upgrade. Uninstalling clears local settings and the action cursor, so reconcile or use a fresh node before reinstalling to avoid replaying old actions. No signing key is published.

See [verification](../docs/verification.md) for actual checks and remaining physical-device tests. Android accepting a vibration API call is not proof that a motor physically moved.
