# minimal-substrate

Retained bounded read-only probe runner for the minimal-substrate
investigation: harmless identity/environment/clock probes against the owned
Note3, executed under the host shell with strict bounds.

`probe.py` runs a fixed allowlist of read-only `adb shell` probes — no
arbitrary command execution, no device mutation, no radio/camera/mic/location,
no persistent state. Running the script is the only ON; not running is OFF;
nothing survives the process except bounded artifact files.

Bounds (env-overridable): per-command timeout with child kill (default 10s),
per-probe output cap (default 64 KiB), artifact retention (newest 20; N<=0 keeps none).
Interrupted outcomes (timeout, non-zero exit, missing adb) are recorded
truthfully in the artifact; nothing is retried or hidden.

Usage: `python3 probe.py [identity|environment|clock|all]`
Exit: `0` all ok · `1` any probe timed out or errored · `2` usage error.

Tests: `python3 -m unittest discover -s experiments/minimal-substrate`
