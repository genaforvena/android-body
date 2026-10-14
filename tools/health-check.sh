#!/bin/sh
# SPDX-License-Identifier: CC0-1.0
# Bounded health check for android-body infrastructure and the Note3 session.
# Section 6 classifies the device session (tools/device_state.py); a node that
# is not attached reads UNKNOWN and does not fail the host-infrastructure checks.
# Section 7 checks the published node-state file the perception consumer reads,
# and that the bytes which publish it are the committed ones.
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

# 3. Transport tunnel (404 unknown_route probe)
TUNNEL=$(python3 -c "
import urllib.request
try:
    urllib.request.urlopen('http://127.0.0.1:8765/node/note3', timeout=5)
    print('unexpected-200')
except urllib.error.HTTPError as e:
    if 'unknown_route' in e.read().decode():
        print('alive')
    else:
        print('unexpected-404')
except Exception:
    print('dead')
" 2>/dev/null)
if [ "$TUNNEL" = "alive" ]; then
  pass "transport tunnel alive (404 unknown_route)"
else
  fail "transport tunnel $TUNNEL"
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

# 5. Queue sizes
for q in note3.observations.log note3.actions.log redmi10.observations.log redmi10.actions.log; do
  f="$SITE/body/queues/$q"
  if [ -f "$f" ]; then
    sz=$(stat -c%s "$f")
    pass "queue $q ${sz}B"
  else
    fail "queue $q MISSING"
  fi
done

# 6. Device session state (read-only). Classifies ON-sending / ON-collect-only /
# OFF / app-absent so a silent producer is not misread as "OFF" or "app dead".
# Collect-only issues no HTTP by design, so silence there is expected, not a fault.
SERIAL=${NOTE3_SERIAL:-4d00553d61ab90b7}
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

# 7b. android-body-node-state.timer executes tools/node_state.py (and its
# device_state.py import) straight from this checkout, so the working tree --
# not a frozen release -- is what publishes within 60s. Compare the live bytes
# with HEAD: an uncommitted or half-applied edit is otherwise invisible until
# the consumer misreads the document it produces. `git status` rather than
# `git diff HEAD` because diff reports an untracked file as unchanged; a
# skip-worktree/assume-unchanged bit hides even from status, so the index
# flags are checked too.
if command -v git >/dev/null 2>&1 && git rev-parse --git-dir >/dev/null 2>&1; then
  if NS_DIRTY=$(git status --porcelain --untracked-files=all -- tools/node_state.py tools/device_state.py 2>/dev/null); then
    if [ -z "$NS_DIRTY" ]; then
      pass "node-state publisher bytes match HEAD"
    else
      fail "node-state publisher bytes differ from HEAD (uncommitted edits go live within 60s)"
    fi
  else
    echo "UNKNOWN node-state publisher bytes (git status failed)"
  fi
  NS_BITS=$(git ls-files -v -- tools/node_state.py tools/device_state.py 2>/dev/null | awk '$1 != "H"')
  if [ -n "$NS_BITS" ]; then
    fail "node-state publisher bytes carry an assume-unchanged/skip-worktree bit (invisible to git status)"
  fi
else
  echo "UNKNOWN node-state publisher bytes (git unavailable)"
fi


echo "---"
if [ "$FAIL" -eq 0 ]; then
  echo "HEALTH: GREEN"
else
  echo "HEALTH: RED"
fi
exit "$FAIL"
