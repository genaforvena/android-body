# minimal-substrate

Retained bounded read-only probe runner for the minimal-substrate
investigation: harmless identity/environment/clock probes against the owned
Note3, each record labeled with its execution context, plus a device-side
persisted trivial-script rerun and a capture of the in-process identity
observation delivered through existing text delivery.

`probe.py` runs a fixed allowlist of read-only `adb shell` probes — no
arbitrary command execution, no device mutation except one bounded
app-private scratch file that is deleted again, no radio/camera/mic/
location, no downloaded code. Running the script is the only ON; not
running is OFF; nothing survives the process except bounded artifact files.

Contexts (discriminator bar 4): `host` = adb shell (uid 2000), never
APK-identity evidence; `run-as` = org.androidbody app uid via debuggable
run-as, never APK-uid evidence; `apk-uid` = observation produced inside the
org.androidbody APK process (session-start in-process identity probe,
delivered through existing text delivery, retained in the durable consumer
spool). `apk-dex` records host-side installed-byte correlation —
explicitly not execution evidence. run-as exit0-with-failure ("corrupt
installation") is detected and never recorded as success.

Probes: `host-identity` (`id`), `host-environment` (`dumpsys sensorservice`),
`host-clock` (`date -u`), `runas-identity` (`run-as … id`),
`runas-status` (`/proc/self/status`), `runas-selinux` (`/proc/self/attr/current`),
`runas-denied` (another app's private file; denial expected, stderr retained),
`host-interrupt` (`sleep 30` + runner SIGINT, truthful receipt),
`apk-identity` (retained in-process observation from the spool copy),
`apk-dex` (installed APK dex correlation), `scratch-rerun` (fixed trivial
text script written to app-private scratch via run-as, run twice, deleted,
source+SHA-256+provenance retained).

Bounds (env-overridable): per-command timeout with child kill (default 10s),
per-line output cap (default 1024 bytes, matching the text-delivery per-line
limit), total output cap (default 64 KiB), artifact retention (newest 20;
N<=0 keeps none). Interrupted outcomes (timeout, non-zero exit, missing adb,
undecodable output, exit0-with-failed-operation) are recorded truthfully in
a dated artifact; nothing is retried or hidden.

Usage: `python3 probe.py [host-identity|host-environment|host-clock|runas-identity|runas-status|runas-selinux|runas-denied|host-interrupt|apk-identity|apk-dex|scratch-rerun|all]`
Exit: `0` every probe reached its expected outcome · `1` any did not · `2` usage error.

Tests: `python3 -m unittest discover -s experiments/minimal-substrate`
