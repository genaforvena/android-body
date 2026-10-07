# SPDX-License-Identifier: CC0-1.0
# POSIX awk, run by watch-light.sh. Input: sequence timestamp light lux=value.
# Unknown/unavailable, malformed, and stale samples never become lux=0.
# Emits at most one command from the latest light state in this batch.
function number(s) {
    return length(s) <= 32 && s ~ /^[+]?[0-9]+([.][0-9]+)?([eE][+-]?[0-9]+)?$/
}
BEGIN { last = cursor; emit = 0; invalid = 0; known = 0 }
{
    if ($1 !~ /^[1-9][0-9]*$/ || length($1) > 16 || $1 + 0 > 9007199254740991 || $1 + 0 != last + 1) {
        invalid = 1
        next
    }
    last = $1 + 0
    if ($3 != "light") next
    known = 0
    # Exact MVP shape and device timestamp; reject unknown, old, or future data.
    if (NF < 4 || NF > 6 || $2 !~ /^[0-9]+$/ || length($2) > 16 || $4 !~ /^lux=/) next
    metadata_ok = 1; have_age = 0; have_accuracy = 0
    for (i = 5; i <= NF; i++) {
        if ($i ~ /^accuracy=(-1|[0-3])$/ && !have_accuracy) { have_accuracy = 1 }
        else if ($i ~ /^age_ms=[0-9]+$/ && !have_age) {
            have_age = 1
            age = substr($i, 8)
            if (length(age) > 10 || age + 0 > max_age * 1000) metadata_ok = 0
        } else metadata_ok = 0
    }
    if (!metadata_ok) next
    if (now - $2 > max_age || $2 - now > 5) next
    value = substr($4, 5)
    if (!number(value) || value + 0 < 0 || value + 0 > 1000000000) next
    lux = value + 0
    known = 1
}
END {
    if (invalid) exit 2
    if (known && lux >= threshold) {
        armed = 1
    } else if (known && armed && now - last_action >= cooldown && attempts < max_actions) {
        emit = 1
        armed = 0
        last_action = now
        attempts++
    }
    # %.0f avoids scientific notation for long sequence IDs.
    printf "%.0f %d %.0f %d\n", last, armed, last_action, attempts > state_out
    close(state_out)
    if (emit) printf "vibrate duration=%d\n", duration
}
