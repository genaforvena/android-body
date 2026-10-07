#!/bin/sh
# SPDX-License-Identifier: CC0-1.0
# Consumer-side POSIX shell + awk + curl. Never runs on the Android phone.
set -eu
umask 077

fail() { printf '%s\n' "$*" >&2; exit 1; }
[ "$#" -eq 1 ] || fail "Usage: BODY_SECRET=... $0 https://host/node/note3"
BASE_URL=${1%/}
printf '%s\n' "$BASE_URL" | grep -Eq '^https?://[^/?#@[:space:]]+/node/[a-z0-9][a-z0-9_-]{0,63}$' || fail "Use an exact https://host/node/id endpoint without credentials, query, or fragment"
case "$BASE_URL" in
    https://*) ;;
    http://*) [ "${ALLOW_INSECURE_HTTP:-0}" = 1 ] || fail "HTTP exposes the secret and data. For a trusted test LAN only, set ALLOW_INSECURE_HTTP=1" ;;
esac
: "${BODY_SECRET:?Set the node secret in BODY_SECRET}"
case "$BODY_SECRET" in *[!A-Za-z0-9._~-]*) fail "Secret contains unsupported characters" ;; esac
[ "${#BODY_SECRET}" -ge 32 ] && [ "${#BODY_SECRET}" -le 256 ] || fail "Secret must be 32–256 characters"
THRESHOLD_LUX=${THRESHOLD_LUX:-10}
DURATION_MS=${DURATION_MS:-200}
COOLDOWN_SECONDS=${COOLDOWN_SECONDS:-30}
POLL_SECONDS=${POLL_SECONDS:-2}
MAX_AGE_SECONDS=${MAX_AGE_SECONDS:-30}
MAX_ACTIONS=${MAX_ACTIONS:-10}
MAX_POLLS=${MAX_POLLS:-300}
STATE_FILE=${STATE_FILE:-.light-vibrate-state}
case "$STATE_FILE" in /*) ;; *) STATE_FILE="$(pwd)/$STATE_FILE" ;; esac
SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)

check_int() {
    case "$2" in ''|*[!0-9]*) fail "$1 must be an integer" ;; esac
    [ "${#2}" -le 8 ] && [ "$2" -ge "$3" ] && [ "$2" -le "$4" ] || fail "$1 must be between $3 and $4"
}
check_int THRESHOLD_LUX "$THRESHOLD_LUX" 1 1000000
check_int DURATION_MS "$DURATION_MS" 1 2000
check_int COOLDOWN_SECONDS "$COOLDOWN_SECONDS" 1 86400
check_int POLL_SECONDS "$POLL_SECONDS" 1 3600
check_int MAX_ACTIONS "$MAX_ACTIONS" 1 100
check_int MAX_POLLS "$MAX_POLLS" 1 100000
check_int MAX_AGE_SECONDS "$MAX_AGE_SECONDS" 1 3600
command -v curl >/dev/null 2>&1 || fail "curl is required on the consumer"
command -v awk >/dev/null 2>&1 || fail "awk is required on the consumer"

# One local consumer per state file. No automatic stale-lock deletion.
mkdir "$STATE_FILE.lock" 2>/dev/null || fail "State lock exists: stop the other runner, or inspect and remove the stale lock directory"
TEMP_DIR=
cleanup() {
    [ -z "$TEMP_DIR" ] || rm -rf "$TEMP_DIR"
    rmdir "$STATE_FILE.lock" 2>/dev/null || :
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
TEMP_DIR=$(mktemp -d "${TMPDIR:-/tmp}/body-light.XXXXXXXX")
# Read the secret from a private config file instead of exposing it in curl argv.
printf 'header = "Authorization: Bearer %s"\n' "$BODY_SECRET" > "$TEMP_DIR/auth.conf"
unset BODY_SECRET

# State is tied to this exact node URL. It is data, never sourced as shell code.
if [ -f "$STATE_FILE" ]; then
    saved_url=$(sed -n '1p' "$STATE_FILE")
    [ "$saved_url" = "$BASE_URL" ] || fail "State belongs to another node endpoint; choose a different STATE_FILE"
    state=$(sed -n '2p' "$STATE_FILE")
    [ "$(wc -l < "$STATE_FILE" | tr -d ' ')" = 2 ] || fail "Malformed state file"
else
    state="0 1 0 0"
fi
printf '%s\n' "$state" | awk 'NF == 4 && $1 ~ /^[0-9]+$/ && length($1) <= 16 && $1+0 <= 9007199254740991 && $2 ~ /^[01]$/ && $3 ~ /^[0-9]+$/ && $4 ~ /^[0-9]+$/ { ok=1 } END { exit !ok }' || fail "Malformed state file"
# The validation above allows only four numeric fields, so word splitting is safe.
set -- $state
cursor=$1; armed=$2; last_action=$3; attempts=$4
polls=0
printf 'Watching %s: lux < %s, cooldown %ss, at most %s attempts / %s polls. Ctrl-C stops.\n' "$BASE_URL" "$THRESHOLD_LUX" "$COOLDOWN_SECONDS" "$MAX_ACTIONS" "$MAX_POLLS"
while [ "$polls" -lt "$MAX_POLLS" ] && [ "$attempts" -lt "$MAX_ACTIONS" ]; do
    polls=$((polls + 1))
    code=$(curl --silent --show-error --config "$TEMP_DIR/auth.conf" --connect-timeout 5 --max-time 15 --proto '=http,https' --max-filesize 65536 --output "$TEMP_DIR/observations" --write-out '%{http_code}' "$BASE_URL/observations?after=$cursor") || fail "Observation read failed; state retained. Rerun when reachable"
    [ "$code" = 200 ] || fail "Observation read returned HTTP $code; inspect the server before resetting any cursor"
    [ "$(wc -c < "$TEMP_DIR/observations" | tr -d ' ')" -le 65536 ] || fail "Observation batch too large"
    now=$(date +%s)
    LC_ALL=C awk -v cursor="$cursor" -v armed="$armed" -v last_action="$last_action" -v attempts="$attempts" -v now="$now" -v threshold="$THRESHOLD_LUX" -v duration="$DURATION_MS" -v cooldown="$COOLDOWN_SECONDS" -v max_age="$MAX_AGE_SECONDS" -v max_actions="$MAX_ACTIONS" -v state_out="$TEMP_DIR/next-state" -f "$SCRIPT_DIR/light-threshold.awk" "$TEMP_DIR/observations" > "$TEMP_DIR/action" || fail "Invalid observation sequences; cursor unchanged"
    state=$(cat "$TEMP_DIR/next-state")
    # Commit before POST. An interrupted/ambiguous action is never auto-retried.
    # The temp state sits beside its destination for an atomic same-filesystem mv.
    { printf '%s\n' "$BASE_URL"; printf '%s\n' "$state"; } > "$STATE_FILE.lock/next"
    mv "$STATE_FILE.lock/next" "$STATE_FILE"
    set -- $state
    cursor=$1; armed=$2; last_action=$3; attempts=$4
    if [ -s "$TEMP_DIR/action" ]; then
        code=$(curl --silent --show-error --config "$TEMP_DIR/auth.conf" --connect-timeout 5 --max-time 15 --proto '=http,https' --max-filesize 4096 --header 'Content-Type: text/plain; charset=utf-8' --data-binary @"$TEMP_DIR/action" --output "$TEMP_DIR/assigned" --write-out '%{http_code}' "$BASE_URL/actions") || fail "Action append outcome uncertain; not retried. Inspect the action log before doing anything else"
        [ "$code" = 201 ] || fail "Action append returned HTTP $code; attempt counted and not retried"
        id=$(cat "$TEMP_DIR/assigned")
        printf '%s\n' "$id" | grep -Eq '^[1-9][0-9]{0,15}$' || fail "Unexpected action acknowledgement; inspect the queue, do not retry blindly"
        printf 'Queued action %s (attempt %s/%s). Physical vibration is unverified.\n' "$id" "$attempts" "$MAX_ACTIONS"
    fi
    [ "$polls" -ge "$MAX_POLLS" ] || [ "$attempts" -ge "$MAX_ACTIONS" ] || sleep "$POLL_SECONDS"
done
printf 'Stopped after %s polls and %s total recorded attempts. Cursor %s.\n' "$polls" "$attempts" "$cursor"
