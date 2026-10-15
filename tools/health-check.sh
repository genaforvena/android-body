#!/bin/sh
# SPDX-License-Identifier: CC0-1.0
# Bounded health check for android-body infrastructure, the Note3 session,
# and the Redmi tailnet transport.
# Section 6 classifies the device session (tools/device_state.py); a node that
# is not attached reads UNKNOWN and does not fail the host-infrastructure checks.
# Section 7 checks the published node-state file the perception consumer reads,
# and that the bytes which publish it are the committed ones.
# Section 8 checks this role's own plate (bin/wall-check): a settle whose staged
# notes still hold an earlier wake's text writes that text over walls/health.md
# with no error, so the plate can name a wake older than the last yield while
# every service check above stays GREEN.
# Section 3b supervises the Redmi tailnet HTTPS path (serve config, endpoint
# probe, write recency); a device that is not connected reads UNKNOWN.
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
# first 95 min of history was one 29-min outage). UNKNOWN when the device is
# simply not connected, matching section 6 above.
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
  REMI_ONLINE=$(tailscale status --json 2>/dev/null | python3 "$PWD/tools/tailnet_peer.py" "$REMI_NODE")
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
        elif [ "$REMI_ONLINE" = "yes" ]; then
          fail "redmi10 silent ${REMI_AGE}s over a live tailnet path"
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
NODE_STATE="$SITE/body/perception/node-state-note3.json"
if [ -f "$NODE_STATE" ]; then
  NS_AGE=$(( $(date +%s) - $(stat -c%Y "$NODE_STATE") ))
  if [ "$NS_AGE" -le 120 ]; then
    pass "node-state note3 fresh (${NS_AGE}s)"
  else
    fail "node-state note3 stale ${NS_AGE}s (>120s)"
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


echo "---"
if [ "$FAIL" -eq 0 ]; then
  echo "HEALTH: GREEN"
else
  echo "HEALTH: RED"
fi
exit "$FAIL"
