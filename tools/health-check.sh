#!/bin/sh
# SPDX-License-Identifier: CC0-1.0
# Bounded health check for android-body infrastructure.
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

echo "---"
if [ "$FAIL" -eq 0 ]; then
  echo "HEALTH: GREEN"
else
  echo "HEALTH: RED"
fi
exit "$FAIL"
