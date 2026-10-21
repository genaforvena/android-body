#!/bin/sh
# SPDX-License-Identifier: CC0-1.0
# Bounded health check for android-body infrastructure, the Note3 session,
# and the Redmi tailnet transport.
# Section 6 classifies the device session (tools/device_state.py); a node that
# is not attached reads UNKNOWN and does not fail the host-infrastructure checks.
# Section 7 checks the published node-state, spool-summary and perception-view
# files the perception consumer reads and writes, and that the bytes which
# publish them are the committed ones.
# Section 8 checks this role's own plate (bin/wall-check): a settle whose staged
# notes still hold an earlier wake's text writes that text over walls/health.md
# with no error, so the plate can name a wake older than the last yield while
# every service check above stays GREEN.
# Section 3b supervises the Redmi tailnet HTTPS path (serve config, endpoint
# probe, write recency); a device that is not connected reads UNKNOWN.
# Section 9 checks the published candidate APK (downloads/) against the committed
# SHA256SUMS record; the install itself stays gated on device transport.
# Section 1b reads each unit's systemd LOAD state (tools/service_units.py): a
# fragment systemd refuses to load still reads `active (running)` from an
# earlier generation, so `is-active` alone passes while the core replant holds
# on the refused restart and restarts every channel with it. Section 1c bounds
# the whole-hour channel restart count, which is how that retry loop reads.
# Section 2f reads this site's binding-refusal audit log
# (tools/binding_refusal.py): a documented cross-plant command the guard rejects
# is a dead route, and the log is the only record of it.
# Section 10 reads the volume's free bytes (tools/disk_free.py) against the core
# scan's own 20 GiB near threshold; the drain rate stays core-owned, and an
# unreadable df reads UNKNOWN rather than passing.
# Exits 0 if all invariants hold, 1 otherwise.
set -u
cd "$(dirname "$0")/.."

SITE="$PWD/.mishe-tauftauf"
FAIL=0

pass() { echo "GREEN  $1"; }
fail() { echo "RED    $1"; FAIL=1; }

# 1. Services
for svc in android-body-rendezvous android-body-perception android-body-usb; do
  if env XDG_RUNTIME_DIR=/run/user/$(id -u) systemctl --user is-active --quiet "$svc.service"; then
    pass "service $svc active"
  else
    fail "service $svc NOT active"
  fi
done

# 1b. Unit load state (wake 95926): `is-active` in §1 cannot see a fragment
# systemd refuses to load. On 2026-10-16 `android-body-silence.service` loaded
# `bad-setting` (its core-generated fragment had lost `[Unit]` and `[Service]`)
# while still reading `active (running)` from an earlier valid generation, so
# every check here stayed GREEN while the core replant held on the refused
# restart (`plant.py` `reconcile_services` raises `CalledProcessError`) and
# restarted every channel service with it. The LOAD column is the fact that
# separates the two; an unreadable dump is UNKNOWN, never a pass.
if command -v python3 >/dev/null 2>&1 && [ -x "$PWD/tools/service_units.py" ]; then
  UNITS_OUT=$(env XDG_RUNTIME_DIR=/run/user/$(id -u) systemctl --user list-units \
    'android-body-*.service' --all --full --plain --no-legend 2>/dev/null \
    | python3 "$PWD/tools/service_units.py" 2>&1)
  UNITS_RC=$?
  printf '%s\n' "$UNITS_OUT"
  case "$UNITS_RC" in
    0) ;;
    1) FAIL=1 ;;
    *) ;;
  esac
else
  echo "UNKNOWN unit load state (python3 or tools/service_units.py unavailable)"
fi

# 1c. Channel restart churn (wake 95926): the hold above restarts every
# android-body channel service on each retry. Measured 2026-10-16 during the
# hold: 10 restarts per channel per hour, against one per channel for a normal
# pin-advance replant — so an hour's total above RESTART_BOUND separates a
# retry loop from replant churn, while two legitimate replants (~24) stay under
# it. A single service crash-looping is caught here too, with no bad fragment.
# This is a trailing-60-min count, so it decays on its own once a burst ages out
# and a GREEN here is not evidence that the render cost behind the bursts went
# away (the bursts follow pin advances, not the frame cycle); §2c measures the
# frame cycle directly. The decomposition line names which units the count is
# made of, so a mind-initiated activation of a managed unit is visible as such.
RESTART_BOUND=40
JOURNAL=$(env XDG_RUNTIME_DIR=/run/user/$(id -u) journalctl --user --since '60 min ago' \
  --no-pager 2>/dev/null)
JOURNAL_RC=$?
RESTARTS=$(printf '%s\n' "$JOURNAL" | grep -c 'Stopping android-body-.*\.service' || true)
if [ "$JOURNAL_RC" -ne 0 ]; then
  echo "UNKNOWN channel restart churn (user journal unreadable)"
elif [ "$RESTARTS" -le "$RESTART_BOUND" ]; then
  pass "channel restarts $RESTARTS/h (bound $RESTART_BOUND)"
else
  fail "channel restarts $RESTARTS/h over bound $RESTART_BOUND"
fi

if [ "$JOURNAL_RC" -eq 0 ] && [ -n "$RESTARTS" ] && [ "$RESTARTS" -gt 0 ]; then
  RESTART_UNITS=$(printf '%s\n' "$JOURNAL" | grep -o 'Stopping android-body-[a-z0-9-]*\.service' \
    | sed 's/Stopping //' | sort | uniq -c | sort -rn)
  echo "INFO   channel restart decomposition: $(printf '%s\n' "$RESTART_UNITS" | awk '{printf "%s=%s ", $2, $1}')"
fi

# 2. Panes
EXPECTED_PANES="senses docs genome research-methods permissions operator witness discover health"
for name in $EXPECTED_PANES; do
  if tmux list-windows -t android-body -F '#{window_name}' 2>/dev/null | grep -qx "$name"; then
    pass "pane $name present"
  else
    fail "pane $name MISSING"
  fi
done
DEAD=$(tmux list-panes -t android-body -F '#{pane_dead}' 2>/dev/null | grep -c 1 || true)
if [ "$DEAD" -eq 0 ]; then
  pass "no dead panes"
else
  fail "$DEAD dead pane(s)"
fi

# 2b. Renderer crash tripwire (wake 80473): a healthy `pain watch` loop is
# stderr-silent; a stderr write in the last 2 min is a crash. Needed because
# operator-view restores a crashed pane within ~2 min, so the presence/dead
# checks above pass while a crash loop runs (the 2026-10-13 11:00 –
# 2026-10-14 18:43 wcwidth loop ran 31h under a GREEN check; observed crash
# cadence was every ~1-2 min, so a 2-min window catches active loops while
# aging out single self-healed crashes).
RECENT_CRASH=""
for err in "$SITE"/logs/pain-watch-*.stderr; do
  [ -e "$err" ] || continue
  if [ -n "$(find "$err" -mmin -2 -print -quit 2>/dev/null)" ]; then
    RECENT_CRASH="$RECENT_CRASH $(basename "$err")"
  fi
done
if [ -z "$RECENT_CRASH" ]; then
  pass "no renderer crash in last 2 min"
else
  fail "renderer stderr written in last 2 min:$RECENT_CRASH"
fi

# 2c. Pane lease advance (wake 103031): the core sync reads every mind pane's
# `-- pane live` footer before it records a linked site, and holds the replant
# when a footer is older than 20 s (one retry after RENDERER_FRAME = 27 s, so a
# pane already stale that stays silent is held) or when the leases do not
# advance within 3 x 6 s -- an advance check with no retry, which a frame cycle
# over 18 s fails (pinned core `coordination/site_sync.py` `_leases`/`_verify`);
# the retry then restarts every channel service (§1c). Measured 2026-10-17T09:1xZ
# (post-reboot, load1 3.8, core pin 14963f76fc38): witness median 17.76 s over 73
# retained frames with 15 of them over the 18 s bound (max 18.31 s) -- its steady
# cycle sits under that bound by only 0.24 s, so the advance check fails on
# roughly one frame in five; discover/permissions 11.2 s, the other minds 5.6 s.
# Earlier, 2026-10-16T20:28Z/21:05Z: witness 19.6-20.1 s, discover/permissions
# 12-13 s, while §1c had already decayed to 0/h. This check reads the frame cycle
# from the footer history tmux retains -- the same artifact the core parses -- so
# it costs no wait and does not decay; each line carries load1, which separates a
# pane's own render cost from a host-load episode (20:15-20:23Z: every pane 22-53 s
# at load1 ~22 with no channel restarts). Panes are the site's own
# health/windows.json intersected with the core's ROLES; `operator` is outside
# that set because the core's own dash-stall detector covers it. RED is the newest
# frame interval over the 18 s advance window or a lease age over the 20 s stale
# bound, each reported with the excess it measured; UNKNOWN never passes.
if command -v python3 >/dev/null 2>&1 && [ -x "$PWD/tools/pane_lease.py" ]; then
  PL_OUT=$(python3 "$PWD/tools/pane_lease.py" --site "$SITE" 2>&1)
  PL_RC=$?
  printf '%s\n' "$PL_OUT"
  case "$PL_RC" in
    0) ;;
    1) FAIL=1 ;;
    *) ;;
  esac
else
  echo "UNKNOWN pane lease advance (python3 or tools/pane_lease.py unavailable)"
fi

# 2d. Stranded channel clear (wake 105526): `wall.tick` creates no wake while a
# role's turn is settled but not cleared (`settled != cleared`), and `wall.clear`
# commits the clear in the same call that writes the journal -- so a journal left
# in `rotating`/`rotated` at the core's own 60 s stall threshold
# (`seed_culture_views.CLEAR_JOURNAL_STALL_S`) is a mind that will never be
# woken again. Measured 2026-10-17: genome and senses stranded from the
# 08:47:24Z boot by a clear whose journal named the pre-replant launcher
# (PYTHONPATH .../releases/db764959.../src) while the live panes ran the pin the
# kernel-sync replant installed; `wall._rotated_by_resurrection`'s exact-launcher
# guard could never match again, the supervisor printed 133/132 HOLD lines in 45
# minutes, and this check still printed HEALTH: GREEN over both dead minds. RED
# names the role, settled turn, phase and the age that measured it; UNKNOWN never
# passes, and an all-UNKNOWN run prints no GREEN line. It reads the journals only,
# so it cannot see a starved mind whose clear committed (that signal has a
# different resolver).
if command -v python3 >/dev/null 2>&1 && [ -x "$PWD/tools/channel_clear.py" ]; then
  CC_OUT=$(python3 "$PWD/tools/channel_clear.py" --site "$SITE" 2>&1)
  CC_RC=$?
  printf '%s\n' "$CC_OUT"
  case "$CC_RC" in
    0) ;;
    1) FAIL=1 ;;
    *) ;;
  esac
else
  echo "UNKNOWN channel clear (python3 or tools/channel_clear.py unavailable)"
fi

# 2e. Runtime pin (wake 106233): every `seed run` channel resolves the bytes it
# will import through <site>/health/runtime-release.json and refuses to start
# unless that document names a clean exact-SHA git worktree
# (`runtime_source.checked_source`: the toplevel is the pinned path, HEAD is the
# pinned sha, `status --porcelain` is empty, the package is present). The refusal
# is a startup failure, not a warning. Measured 2026-10-17: a hand edit inside
# the pinned release itself (releases/1543b3a0.../src/mishe_tauftauf/
# session_watch.py, mtime 01:00:32Z) left it dirty, and all ten of the
# co-resident core plant's channel units exited 2 with `runtime pin invalid:
# runtime source changed or is not a clean exact-SHA worktree` on every 15 s
# restart (NRestarts=478 by 10:48Z) while no line in this check read the pin at
# all. This plant's own pin stayed clean, so the check is what makes the class
# legible before a restart storm and what names the cause when one starts.
# tools/runtime_pin.py REDs on each failing predicate; UNKNOWN (a site that
# declares no pin, a git that cannot be executed) never passes.
if command -v python3 >/dev/null 2>&1 && [ -x "$PWD/tools/runtime_pin.py" ]; then
  PIN_OUT=$(python3 "$PWD/tools/runtime_pin.py" --site "$SITE" 2>&1)
  PIN_RC=$?
  printf '%s\n' "$PIN_OUT"
  case "$PIN_RC" in
    0) ;;
    1) FAIL=1 ;;
    *) ;;
  esac
else
  echo "UNKNOWN runtime pin (python3 or tools/runtime_pin.py unavailable)"
fi

# 2f. Binding refusals (wake 106507): the pinned core's validate_home_binding
# writes one JSON line per refused cross-plant command to
# <bound-site>/logs/binding-refusal-audit.jsonl (observations.py
# _audit_binding_refusal). A refusal means a mind followed a documented command
# the guard rejects -- a dead route. Measured 2026-10-17: this plant's own
# panes produced 12 refusals in 09:00-11:09Z (newest 3 min before this
# section was written), because the charter fix (witness wake 106367) is on
# disk but the running panes still carry the pre-edit delivery. Nothing read
# the audit log, so the class surfaced only when a mind happened to open the
# file. RED when the 24h window holds a refusal; UNKNOWN when the log is
# missing or unreadable, never a pass.
if command -v python3 >/dev/null 2>&1 && [ -x "$PWD/tools/binding_refusal.py" ]; then
  REFUSAL_OUT=$(python3 "$PWD/tools/binding_refusal.py" --site "$SITE" 2>&1)
  REFUSAL_RC=$?
  printf '%s\n' "$REFUSAL_OUT"
  case "$REFUSAL_RC" in
    0) ;;
    1) FAIL=1 ;;
    *) ;;
  esac
else
  echo "UNKNOWN binding refusals (python3 or tools/binding_refusal.py unavailable)"
fi

# 3. Transport. Two independent facts: the rendezvous server answers the
# loopback URL the phone uses, and the `adb reverse` mapping that carries the
# phone's requests to it is in place. The loopback probe alone cannot see the
# second: on 2026-10-15T11:16Z a replaced adb server dropped the mapping and the
# probe stayed GREEN. A mapping lives in the adb server process, and its
# transport_id restarts at 1, so a generation check cannot see the loss either.
# The mapping is observed on the device's socket table because `adb reverse
# --list` is forbidden on this Note3 (it correlated with repeated transport loss).
SERIAL=${NOTE3_SERIAL:-4d00553d61ab90b7}
PORT_HEX=$(printf '%04X' 8765)
TUNNEL=$(python3 -c "
import urllib.request, urllib.error
try:
    urllib.request.urlopen('http://127.0.0.1:8765/node/note3', timeout=5)
    print('unexpected-200')
except urllib.error.HTTPError as e:
    print('alive' if 'unknown_route' in e.read().decode() else 'unexpected-404')
except Exception:
    print('dead')
" 2>/dev/null)
if [ "$TUNNEL" = "alive" ]; then
  pass "rendezvous answers the phone's loopback URL (404 unknown_route)"
else
  fail "rendezvous loopback probe $TUNNEL"
fi

ATTACHED=""  # §3 attachment verdict; §7d reuses it for its unavailable-status branch
if command -v adb >/dev/null 2>&1; then
  ATTACHED=$(adb devices 2>/dev/null | awk -v s="$SERIAL" '$1==s && $2=="device"{print "yes"}')
  MAPPING=$(adb -s "$SERIAL" shell cat /proc/net/tcp 2>/dev/null \
    | awk -v p=":$PORT_HEX" '$4=="0A" && $2 ~ (p "$"){print "present"}')
  if [ "$MAPPING" != "present" ] && [ "$ATTACHED" = "yes" ]; then
    sleep 6  # android-body-usb.service re-establishes a lost mapping within ~5s
    MAPPING=$(adb -s "$SERIAL" shell cat /proc/net/tcp 2>/dev/null \
      | awk -v p=":$PORT_HEX" '$4=="0A" && $2 ~ (p "$"){print "present"}')
  fi
  if [ "$MAPPING" = "present" ]; then
    pass "adb reverse in place (device listens on 8765)"
  elif [ "$ATTACHED" = "yes" ]; then
    fail "adb reverse mapping absent while note3 is attached (tunnel dead)"
  else
    echo "UNKNOWN adb reverse mapping: note3 not attached"
  fi
else
  echo "UNKNOWN adb reverse mapping (adb unavailable)"
fi

# 3b. Redmi transport (tailnet HTTPS; no USB path, so adb reverse does not
# apply). The phone app writes to https://mesh-home.tail3e4555.ts.net, which
# `tailscale serve` proxies to 127.0.0.1:8765. Three host-side facts: the
# serve mapping is configured, the phone's exact URL answers (404
# unknown_route = serve+TLS+rendezvous alive), and the device actually
# writes (writes.jsonl recency). RED when the host path is dead, or when the
# device is on the tailnet but silent past REDMI_SILENT_BOUND (900s: the
# observed write cadence is a 4-7s interval, and the only >60s gap in the
# first 95 min of history was one 29-min outage). The "live tailnet path"
# verdict requires the daemon to be Running: `tailscale status --json` is a
# stale cached map while the daemon is stopped (wake 118178), so a stopped
# daemon prints its own RED reason instead of asserting a path that is down.
# UNKNOWN when the daemon state is unreadable or the device is simply not
# connected, matching section 6 above.
REMI_URL=${REMI_URL:-https://mesh-home.tail3e4555.ts.net/node/redmi10}
REMI_NODE=${REMI_NODE:-redmi-10}
REMI_SILENT_BOUND=${REMI_SILENT_BOUND:-900}
if command -v tailscale >/dev/null 2>&1; then
  if SERVE_OUT=$(tailscale serve status 2>/dev/null) && echo "$SERVE_OUT" | grep -q 'proxy http://127.0.0.1:8765'; then
    pass "tailscale serve maps the redmi URL to the rendezvous loopback"
  else
    fail "tailscale serve mapping for the redmi URL absent (or daemon down)"
  fi
  REMI_PROBE=$(python3 - "$REMI_URL" <<'PY'
import urllib.request, ssl, sys
# host-local liveness probe of this host's own serve; the serve config itself
# is checked via 'tailscale serve status' above, so full CA validation adds
# no signal here and would depend on tailscale CA placement.
ctx = ssl.create_default_context()
ctx.check_hostname = False
ctx.verify_mode = ssl.CERT_NONE
try:
    urllib.request.urlopen(sys.argv[1], timeout=8, context=ctx)
    print('unexpected-200')
except urllib.error.HTTPError as e:
    print('alive' if 'unknown_route' in e.read().decode() else 'unexpected-404')
except Exception:
    print('dead')
PY
)
  if [ "$REMI_PROBE" = "alive" ]; then
    pass "redmi tailnet endpoint answers (serve+TLS+rendezvous alive)"
  else
    fail "redmi tailnet endpoint probe $REMI_PROBE"
  fi
  # Peer reachability for the RED/UNKNOWN split below: `Online` (coordination
  # server's view) OR `Active` (traffic now). The earlier text test treated the
  # literal word "offline" as not-connected, but a phone on mobile data keeps a
  # working direct path while Online lags, so its line reads
  # "active; direct ...; offline, last seen 12m ago" while it writes every ~4s;
  # that made the RED branch unreachable for exactly the silent-but-connected
  # case it exists to catch (measured 2026-10-15: Online=False, Active=True,
  # writes every ~4s). Empty output = peer absent or view unreadable = UNKNOWN.
  # Wake 118178: that document is also a stale cached map while the daemon is
  # stopped (measured 2026-10-20T15:45Z: BackendState "Stopped" since 14:03:03Z,
  # peer still listed Online), so the peer predicate alone read `yes` and the
  # silence branch asserted "a live tailnet path" that did not exist — a silent
  # phone during a stopped daemon is expected (it buffers and dumps on resume),
  # not a device fault. The daemon's own state is read beside the peer view.
  REMI_STATUS=$(tailscale status --json 2>/dev/null)
  REMI_ONLINE=$(printf '%s' "$REMI_STATUS" | python3 "$PWD/tools/tailnet_peer.py" "$REMI_NODE")
  REMI_DAEMON=$(printf '%s' "$REMI_STATUS" | python3 "$PWD/tools/tailnet_daemon.py")
  REMI_AGE=$(python3 - "$SITE/body/queues/writes.jsonl" <<'PY'
import json, sys, datetime
last = None
try:
    for line in open(sys.argv[1]):
        try:
            r = json.loads(line)
        except ValueError:
            continue
        if r.get('node') == 'redmi10' and r.get('ts'):
            last = r['ts']
except FileNotFoundError:
    pass
if last is None:
    print('never')
else:
    try:
        age = (datetime.datetime.now(datetime.timezone.utc)
               - datetime.datetime.fromisoformat(last)).total_seconds()
        print(int(age))
    except ValueError:
        print('badts')
PY
)
  if [ -z "$REMI_AGE" ]; then
    fail "redmi10 write recency unreadable (no output)"
  else
    case "$REMI_AGE" in
      never) echo "UNKNOWN redmi10 transport: no writes yet (device not connected)" ;;
      badts) fail "redmi10 last write timestamp unreadable" ;;
      *)
        if [ "$REMI_AGE" -le "$REMI_SILENT_BOUND" ]; then
          pass "redmi10 writing over tailnet HTTPS (last ${REMI_AGE}s ago)"
        elif [ "$REMI_DAEMON" = "running" ] && [ "$REMI_ONLINE" = "yes" ]; then
          fail "redmi10 silent ${REMI_AGE}s over a live tailnet path"
        elif [ "$REMI_DAEMON" = "stopped" ]; then
          fail "redmi10 silent ${REMI_AGE}s with the host tailnet daemon not running (path down; the phone buffers)"
        elif [ "$REMI_DAEMON" = "unknown" ]; then
          echo "UNKNOWN redmi10 transport: silent ${REMI_AGE}s and the tailnet daemon state is unreadable"
        else
          echo "UNKNOWN redmi10 transport: silent ${REMI_AGE}s and not on tailnet (device off)"
        fi
        ;;
    esac
  fi
else
  echo "UNKNOWN redmi transport (tailscale unavailable)"
fi

# 4. Journal warnings (last hour)
WARNS=$(env XDG_RUNTIME_DIR=/run/user/$(id -u) journalctl --user \
  -u android-body-rendezvous.service \
  -u android-body-perception.service \
  -u android-body-usb.service \
  --since '1 hour ago' -p warning --no-pager 2>/dev/null | grep -v '^-- No entries --$' | wc -l)
if [ "$WARNS" -eq 0 ]; then
  pass "no journal warnings (1h)"
else
  fail "$WARNS journal warning(s) (1h)"
fi

# 5. Queue sizes against the live rendezvous cap. The rendezvous appends forever
# (README "Bounds and errors": no automatic log retention/deletion), so a queue
# approaching --max-queue-bytes reads like an empty one until it fills -- then
# appends fail 507 queue_full and the next start cannot open the oversized file.
# Report the fill fraction and RED at the tool's warning threshold so the
# documented remedy (raise the cap, or rotate to a new node ID) is dated, not
# discovered at the outage. The cap comes from the live unit's ExecStart; an
# unreadable cap is UNKNOWN, never a DEFAULT_QUEUE_BYTES guess (8x too small
# here, which would RED a healthy queue).
if command -v python3 >/dev/null 2>&1 && [ -x "$PWD/tools/queue_capacity.py" ]; then
  QC_OUT=$(env XDG_RUNTIME_DIR=/run/user/$(id -u) \
    systemctl --user show android-body-rendezvous.service -p ExecStart 2>/dev/null \
    | python3 "$PWD/tools/queue_capacity.py" "$SITE/body/queues" \
      note3.observations.log note3.actions.log redmi10.observations.log redmi10.actions.log 2>&1)
  QC_RC=$?
  printf '%s\n' "$QC_OUT"
  case "$QC_RC" in
    0) ;;
    1) FAIL=1 ;;
    *) ;;
  esac
else
  echo "UNKNOWN queue capacity (python3 or tools/queue_capacity.py unavailable)"
fi

# 6. Device session state (read-only). Classifies ON-sending / ON-collect-only /
# OFF / app-absent so a silent producer is not misread as "OFF" or "app dead".
# Collect-only issues no HTTP by design, so silence there is expected, not a fault.

if command -v adb >/dev/null 2>&1 && [ -x "$PWD/tools/device_state.py" ]; then
  DEV=$(python3 "$PWD/tools/device_state.py" --serial "$SERIAL" 2>/dev/null || true)
  case "$DEV" in
    "device-state note3: ON_SENDING"*)
      MTIME=$(stat -c%Y "$SITE/body/queues/note3.observations.log" 2>/dev/null || echo "")
      if [ -z "$MTIME" ]; then
        fail "device note3 ON_SENDING but queue file unreadable"
      else
        AGE=$(( $(date +%s) - MTIME ))
        if [ "$AGE" -gt 120 ]; then
          fail "device note3 ON_SENDING but queue unchanged ${AGE}s (>120s)"
        else
          pass "device note3 ON_SENDING; queue written ${AGE}s ago"
        fi
      fi
      ;;
    "device-state note3: ON_COLLECT_ONLY"*)
      echo "INFO   device note3 ON+collect-only — no HTTP by design; producer silence expected"
      ;;
    "device-state note3: OFF"*)
      echo "INFO   device note3 OFF — no collection; producer silence expected"
      ;;
    "device-state note3: ON_NOT_RUNNING"*)
      fail "device note3 durably enabled but app process absent (restore expected)"
      ;;
    *)
      echo "UNKNOWN device note3 session state${DEV:+: $DEV}"
      ;;
  esac
else
  echo "UNKNOWN device note3 session state (adb or tools/device_state.py unavailable)"
fi

# 7. Published node state (perception consumer's "why is the producer silent").
# tools/node_state.py republishes every 60s from android-body-node-state.timer;
# the consumer accepts the file for 300s (watch.py NODE_STATE_MAX_AGE_SECONDS),
# so 120s is the tighter liveness bound for the publisher itself: past it the
# consumer would already be rendering mode=unknown, and the publisher is RED.
# node_state.py catches its own adb error and publishes a *fresh* document
# carrying mode=UNKNOWN and the reason, so the mtime bound alone would read
# GREEN on every tick that reported the device unreadable. A fresh UNKNOWN
# document is RED while the phone is attached (§3 ATTACHED) and UNKNOWN when
# it is not, mirroring §7f's mapping rule; the stale branch still wins, since
# a stopped publisher is the more specific fact.
# NODE_STATE is overridable so a controlled failure routes through this section
# without touching the live published document.
NODE_STATE=${NODE_STATE:-$SITE/body/perception/node-state-note3.json}
if [ -f "$NODE_STATE" ]; then
  NS_AGE=$(( $(date +%s) - $(stat -c%Y "$NODE_STATE") ))
  NS_LINE=$(python3 -c "
import json, sys
try:
    document = json.load(open(sys.argv[1]))
    print('%s\t%s' % (document.get('mode') or 'missing',
                      str(document.get('reasons') or 'none').replace('\n', ' ')))
except Exception:
    print('unreadable\tnone')" "$NODE_STATE" 2>/dev/null)
  NS_MODE=$(printf '%s\n' "$NS_LINE" | cut -f1)
  NS_REASONS=$(printf '%s\n' "$NS_LINE" | cut -f2)
  if [ "$NS_AGE" -gt 120 ]; then
    fail "node-state note3 stale ${NS_AGE}s (>120s; publisher stopped)"
  elif [ "$NS_MODE" = "ON_SENDING" ] || [ "$NS_MODE" = "ON_COLLECT_ONLY" ] || [ "$NS_MODE" = "ON_NOT_RUNNING" ] || [ "$NS_MODE" = "OFF" ]; then
    pass "node-state note3 fresh (${NS_AGE}s) mode=$NS_MODE"
  elif [ "$NS_MODE" = "UNKNOWN" ]; then
    if [ "${ATTACHED:-}" = "yes" ]; then
      fail "node-state note3 UNKNOWN (${NS_REASONS}) while note3 is attached; ${NS_AGE}s old"
    else
      echo "UNKNOWN node-state note3 UNKNOWN (${NS_REASONS}); ${NS_AGE}s old, note3 not attached"
    fi
  elif [ -z "$NS_MODE" ]; then
    echo "UNKNOWN node-state note3 mode (python3 unavailable)"
  else
    fail "node-state note3 mode=$NS_MODE (${NS_REASONS}); expected a known state, ${NS_AGE}s old"
  fi
else
  fail "node-state note3 MISSING"
fi

# 7b. android-body-node-state.timer runs node_state.py and clock_offset.py from
# body/runtime/ (frozen deployed copies, added to the manifest 2026-10-15).
# §7c verifies deployed == source; this check is the complement: the source of
# the publisher's entry points (node_state.py, clock_offset.py) and of the module
# they import (device_state.py) must match HEAD so the next deploy is from a
# known state. `git status` rather than `git diff HEAD` because diff reports an
# untracked file as unchanged; a skip-worktree/assume-unchanged bit hides even
# from status, so the index flags are checked too.
if command -v git >/dev/null 2>&1 && git rev-parse --git-dir >/dev/null 2>&1; then
  if NS_DIRTY=$(git status --porcelain --untracked-files=all -- tools/node_state.py tools/clock_offset.py tools/device_state.py 2>/dev/null); then
    if [ -z "$NS_DIRTY" ]; then
      pass "node-state publisher source matches HEAD"
    else
      fail "node-state publisher source differs from HEAD (deploy would be from a dirty tree)"
    fi
  else
    echo "UNKNOWN node-state publisher source (git status failed)"
  fi
  NS_BITS=$(git ls-files -v -- tools/node_state.py tools/clock_offset.py tools/device_state.py 2>/dev/null | awk '$1 != "H"')
  if [ -n "$NS_BITS" ]; then
    fail "node-state publisher source carries an assume-unchanged/skip-worktree bit (invisible to git status)"
  fi
else
  echo "UNKNOWN node-state publisher source (git unavailable)"
fi

# 7c. Runtime activation record (body/runtime-manifest.json). tools/runtime_manifest.py
# compares each recorded deployed module's sha256 with the bytes in body/runtime, with
# the declared repository source, and with the owning unit's start time (a unit started
# before its bytes were written is running older code). The record drifted silently on
# 2026-10-13/14 because it was the last step of a prose deploy, so supervise it here
# rather than only on genome wakes. A missing record or runtime directory is RED (like
# the node-state file above); the tool's own UNKNOWN (e.g. an unreadable unit start) is
# printed, never silently passed.
RUNTIME_MANIFEST="$SITE/body/runtime-manifest.json"
if [ ! -f "$RUNTIME_MANIFEST" ] || [ ! -d "$SITE/body/runtime" ]; then
  fail "runtime activation record or body/runtime MISSING"
elif command -v python3 >/dev/null 2>&1 && [ -x "$PWD/tools/runtime_manifest.py" ]; then
  RM_OUT=$(env XDG_RUNTIME_DIR=/run/user/$(id -u) python3 "$PWD/tools/runtime_manifest.py" check 2>&1)
  RM_RC=$?
  case "$RM_RC" in
    0) pass "runtime activation record matches deployed bytes" ;;
    1) fail "runtime activation record drifted (drift, unrecorded file, or process older than its bytes)"
       printf '%s\n' "$RM_OUT" ;;
    2) printf 'UNKNOWN runtime activation record: %s\n' "$RM_OUT" ;;
    *) printf 'UNKNOWN runtime activation record (exit %s): %s\n' "$RM_RC" "$RM_OUT" ;;
  esac
else
  echo "UNKNOWN runtime activation record (python3 or tools/runtime_manifest.py unavailable)"
fi

# 7d. Spool-summary publisher liveness and status. android-body-spool-read.timer
# runs runtime/spool_read.py every 5min (observed 300s cadence, ~9s runtime) and
# publishes body/spool-summary-note3.json; the consumer accepts the file for
# 600s (watch.py SPOOL_SUMMARY_MAX_AGE_SECONDS). Nothing else supervises the
# publisher's output: §4 journals only the three long-running services, so the
# timer reads "active" through both failure shapes:
# (a) stopped publisher — the file goes stale. 450s is one-and-a-half ticks, so a
#     missed tick reads RED 150s before the consumer renders the evidence stale.
# (b) failing publisher — spool_read.py catches its own adb error, publishes a
#     *fresh* document carrying status="unavailable" and the reason, and exits 0
#     (reproduced wake 102050 against a bogus serial), so the mtime bound alone
#     read GREEN on every tick that reported the spool unreadable. A fresh
#     unavailable document is RED while the phone is attached (§3 ATTACHED) and
#     UNKNOWN when it is not, mirroring §3's mapping rule; the stale branch above
#     still wins, since a stopped publisher is the more specific fact.
# SPOOL_SUMMARY is overridable so a controlled failure routes through this
# section without touching the live published document.
SPOOL_SUMMARY=${SPOOL_SUMMARY:-$SITE/body/spool-summary-note3.json}
if [ -f "$SPOOL_SUMMARY" ]; then
  SS_AGE=$(( $(date +%s) - $(stat -c%Y "$SPOOL_SUMMARY") ))
  SS_LINE=$(python3 -c "
import json, sys
try:
    document = json.load(open(sys.argv[1]))
    print('%s\t%s' % (document.get('status') or 'missing',
                      str(document.get('reason') or 'none').replace('\n', ' ')))
except Exception:
    print('unreadable\tnone')" "$SPOOL_SUMMARY" 2>/dev/null)
  SS_STATUS=$(printf '%s\n' "$SS_LINE" | cut -f1)
  SS_REASON=$(printf '%s\n' "$SS_LINE" | cut -f2)
  if [ "$SS_AGE" -gt 450 ]; then
    fail "spool-summary note3 stale ${SS_AGE}s (>450s; publisher stopped)"
  elif [ "$SS_STATUS" = "ok" ]; then
    pass "spool-summary note3 fresh (${SS_AGE}s)"
  elif [ "$SS_STATUS" = "unavailable" ]; then
    if [ "${ATTACHED:-}" = "yes" ]; then
      fail "spool-summary note3 unavailable (${SS_REASON}) while note3 is attached; ${SS_AGE}s old"
    else
      echo "UNKNOWN spool-summary note3 unavailable (${SS_REASON}); ${SS_AGE}s old, note3 not attached"
    fi
  elif [ -z "$SS_STATUS" ]; then
    echo "UNKNOWN spool-summary note3 status (python3 unavailable)"
  else
    fail "spool-summary note3 status=$SS_STATUS (${SS_REASON}); expected ok, ${SS_AGE}s old"
  fi
else
  fail "spool-summary note3 MISSING"
fi

# 7e. Perception consumer loop liveness. android-body-perception.service runs
# body/runtime/watch.py `follow`, whose loop rewrites body/perception/view.txt
# unconditionally every cycle (follow(): atomic(view.txt, ...) per loop);
# events.txt is written only when its content changes, so view.txt is the
# liveness signal. Section 1 only proves the unit is active, and a hung loop
# (no crash) leaves it active with Restart=on-failure un-triggered, so the
# rendered perception would freeze while every check above stayed GREEN. The
# cycle is bounded by --poll-seconds 2 plus one poll per node (--timeout 5,
# two nodes) ~= 12s worst case; 120s is 10x that, matching section 7a's bound.
VIEW="$SITE/body/perception/view.txt"
if [ -f "$VIEW" ]; then
  VIEW_AGE=$(( $(date +%s) - $(stat -c%Y "$VIEW") ))
  if [ "$VIEW_AGE" -le 120 ]; then
    pass "perception consumer view fresh (${VIEW_AGE}s)"
  else
    fail "perception consumer view stale ${VIEW_AGE}s (>120s; watch.py follow loop stopped)"
  fi
else
  fail "perception consumer view.txt MISSING"
fi
# 7f. Clock-domain publisher liveness and status. android-body-node-state.timer
# runs runtime/clock_offset.py every 60s (same timer as node_state.py) and
# publishes body/clock-domain-note3.json; the consumer accepts the file for
# 3600s (watch.py CLOCK_DOMAIN_MAX_AGE_SECONDS). clock_offset.py catches its
# own adb error and publishes a *fresh* document carrying status="unavailable"
# and the reason, so the mtime bound alone would read GREEN on every tick that
# reported the clock offset unreadable. A fresh unavailable document is RED
# while the phone is attached (§3 ATTACHED) and UNKNOWN when it is not,
# mirroring §7d's mapping rule; the stale branch still wins, since a stopped
# publisher is the more specific fact.
CLOCK_DOMAIN=${CLOCK_DOMAIN:-$SITE/body/clock-domain-note3.json}
if [ -f "$CLOCK_DOMAIN" ]; then
  CD_AGE=$(( $(date +%s) - $(stat -c%Y "$CLOCK_DOMAIN") ))
  CD_LINE=$(python3 -c "
import json, sys
try:
    document = json.load(open(sys.argv[1]))
    print('%s\t%s' % (document.get('status') or 'missing',
                      str(document.get('reason') or 'none').replace('\n', ' ')))
except Exception:
    print('unreadable\tnone')" "$CLOCK_DOMAIN" 2>/dev/null)
  CD_STATUS=$(printf '%s\n' "$CD_LINE" | cut -f1)
  CD_REASON=$(printf '%s\n' "$CD_LINE" | cut -f2)
  if [ "$CD_AGE" -gt 300 ]; then
    fail "clock-domain note3 stale ${CD_AGE}s (>300s; publisher stopped)"
  elif [ "$CD_STATUS" = "ok" ]; then
    pass "clock-domain note3 fresh (${CD_AGE}s)"
  elif [ "$CD_STATUS" = "unavailable" ]; then
    if [ "${ATTACHED:-}" = "yes" ]; then
      fail "clock-domain note3 unavailable (${CD_REASON}) while note3 is attached; ${CD_AGE}s old"
    else
      echo "UNKNOWN clock-domain note3 unavailable (${CD_REASON}); ${CD_AGE}s old, note3 not attached"
    fi
  elif [ -z "$CD_STATUS" ]; then
    echo "UNKNOWN clock-domain note3 status (python3 unavailable)"
  else
    fail "clock-domain note3 status=$CD_STATUS (${CD_REASON}); expected ok, ${CD_AGE}s old"
  fi
else
  fail "clock-domain note3 MISSING"
fi

# 8. Own wall plate (bin/wall-check health). A settle whose staged notes still
# hold an earlier wake's text writes that text over the current plate with no
# error, so walls/health.md and handoffs/health.md can name a wake older than the
# last `seed yield health` while every check above stays GREEN (class: health
# plate reverted to genome's wake-75020 text, written 2026-10-15T15:23Z, found by
# `wall-check health` RED at wake 88579). The detector is deterministic and
# site-local; when it is absent this reads UNKNOWN rather than passing.
WALL_CHECK="$SITE/bin/wall-check"
if [ -f "$WALL_CHECK" ]; then
  if command -v python3 >/dev/null 2>&1; then
    if WC_OUT=$(python3 "$WALL_CHECK" health 2>&1); then
      pass "own wall plate current"
    else
      fail "own wall plate stale ($WC_OUT)"
    fi
  else
    echo "UNKNOWN own wall plate (python3 unavailable)"
  fi
else
  echo "UNKNOWN own wall plate (no $WALL_CHECK)"
fi

# 9. Candidate APK readiness (deploy lane). The published sideload candidate
# (downloads/android-body-debug.apk) must match the committed SHA256SUMS record;
# installing anything else would put unpublished bytes on a device, the class of
# publication hazard closed at wake 92338. Read-only: verifies the file, never
# installs. The install itself stays gated on device transport (§3b), which this
# check does not decide; a missing candidate or record reads UNKNOWN, like an
# unattached device in §6.
CANDIDATE="$PWD/downloads/android-body-debug.apk"
SUMS="$PWD/downloads/SHA256SUMS"
if [ -f "$SUMS" ]; then
  if [ -f "$CANDIDATE" ]; then
    CAND_SHA=$(sha256sum "$CANDIDATE" | awk '{print $1}')
    if grep -q "$CAND_SHA" "$SUMS"; then
      pass "candidate APK $CAND_SHA matches SHA256SUMS (deploy lane; install gated on device transport)"
    else
      fail "candidate APK SHA $CAND_SHA absent from SHA256SUMS (unpublished bytes)"
    fi
  else
    echo "UNKNOWN candidate APK: $CANDIDATE missing (republish before install)"
  fi
else
  echo "UNKNOWN candidate APK: no SHA256SUMS record at $SUMS"
fi

# 10. Volume free space (wake 123284). The host volume is 99% used with ~15 GiB
# free and a ~7 GiB/day drain (measured 2026-10-21T01:26Z by android-body/discover,
# DM 123190; this host the same minute: `df -B1 -P /` 980666998784B total,
# 923274321920B used, 16404639744B available). The core scan already declares
# `sense.disk.trend` DRIFT on that level, but that verdict needs the retained scan
# corpus and runs on the discover channel, so this plant's own check named no free
# bytes at all: exhaustion would surface as failed record-store and queue writes,
# which is the outage, not the warning. This is the point check; the *rate* and its
# projection stay core-owned, so the section adds no second collector or history
# file. The bound default is the core's own 20 GiB near threshold
# (`_DISK_TREND_NEAR_BYTES`), so a RED here agrees with the dashboard's drift
# verdict instead of contradicting it; DISK_FREE_BOUND overrides it because a
# threshold is policy, not measurement. An unreadable df is UNKNOWN, never a pass.
DISK_FREE_BOUND=${DISK_FREE_BOUND:-21474836480}
if command -v df >/dev/null 2>&1 && command -v python3 >/dev/null 2>&1 \
    && [ -x "$PWD/tools/disk_free.py" ]; then
  DISK_OUT=$(df -B1 -P "$PWD" 2>/dev/null \
    | python3 "$PWD/tools/disk_free.py" --bound-bytes "$DISK_FREE_BOUND" 2>&1)
  DISK_RC=$?
  printf '%s\n' "$DISK_OUT"
  case "$DISK_RC" in
    0) ;;
    1) FAIL=1 ;;
    *) ;;
  esac
else
  echo "UNKNOWN disk free (df, python3 or tools/disk_free.py unavailable)"
fi

echo "---"
if [ "$FAIL" -eq 0 ]; then
  echo "HEALTH: GREEN"
else
  echo "HEALTH: RED"
fi
exit "$FAIL"
