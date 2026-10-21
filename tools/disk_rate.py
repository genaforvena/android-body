#!/usr/bin/env python3
# SPDX-License-Identifier: CC0-1.0
"""Rate and floor-ETA on the caller's own free-space sample log.

``tools/disk_free.py`` (§10) deliberately names the *level* only, and the core
scan's ``sense.disk.trend`` measures its drain over ``_DISK_TREND_SLOPE_WINDOWS_DAYS
= (2, 5, 7, 14)`` -- days. Neither can express a burst of tens of MiB/min lasting
half an hour, which is the drain that actually reaches a floor on a volume this
full: on 2026-10-21 the volume lost 12.6-38.5 MiB/min from 02:35Z to 03:06Z and
then went flat, while the published figure was ``drain=7.2GiB/day(7d)``. The two
numbers were never comparable: a rate belongs to a named window.

This tool takes a sample log -- one ``<ISO8601 timestamp> <available bytes>`` per
line, oldest or newest first -- and reports the drain over each window *anchored
at the newest sample*, so every figure it prints includes the present. A caller
that appends one line per tick (the same split as ``disk_free.py``: the caller
owns the invocation and its failure handling) gets a countdown that moves with the
disk instead of a 7-day average that does not.

The projection is a statement about the named window only, and a rate is computed
over the span between the anchor and the newest sample. When that span differs from
the named window by more than :data:`SPAN_LABEL_TOLERANCE`, the span is printed beside
the rate: the label would otherwise name a window the rate did not measure (``2d``
printed for a 2.52-day span). When the windows disagree -- whether in their ETAs or
about whether the volume is draining at all -- the tool prints every rate and marks
the ETA ``window-only`` rather than picking one, because a countdown taken from the
wrong window sends a reader to prune the wrong thing. A volume that is not draining
has no ETA: ``not-draining`` is printed as such, never as a large number of hours.

The tool has no clock, so the newest sample's timestamp is printed on the ``level``
line: that is the reader's only staleness reference. Without it, a countdown from a
log whose newest sample is a day old is indistinguishable from a fresh one.

Usage: ``disk_rate.py [--floor-bytes N] [--windows 10m,1h,6h,24h,7d] < samples``

Exit: 0 no floor crossing implied within the horizon, 1 crossing implied (or
already below the floor), 2 the reading is unavailable.
"""

import argparse
import re
import sys
from datetime import datetime, timedelta, timezone

#: ``_DISK_TREND_FLOOR_BYTES`` in the pinned core's ``discovery.py``: the
#: countdown target. The *near* threshold (20 GiB) is a level policy and lives in
#: ``disk_free.py``; this tool only needs the target it counts down to.
DEFAULT_FLOOR_BYTES = 10 * 1024 * 1024 * 1024

#: Present-anchored windows, shortest first. The shortest is what makes a burst
#: visible; the longest is the core's own shortest slope window (2d) and beyond,
#: kept so the disagreement between them is visible instead of inherited.
DEFAULT_WINDOWS = "10m,30m,1h,2h,6h,12h,24h,2d,5d,7d"

#: A window narrower than this is timing noise on a shared volume, not a rate.
MIN_WINDOW_SECONDS = 60

#: The horizon a point check decides over: RED when the floor is projected inside
#: it. Policy, not measurement, so it is overridable.
DEFAULT_HORIZON_HOURS = 24.0

_UNIT_SECONDS = {"s": 1, "m": 60, "h": 3600, "d": 86400}


def parse_window(text):
    """``'90m'``/``'7d'``/``'45s'`` as seconds, or None when it is not one."""
    match = re.fullmatch(r"(\d+)([smhd])", text.strip())
    if not match:
        return None
    return int(match.group(1)) * _UNIT_SECONDS[match.group(2)]


def parse_samples(text):
    """``([(datetime, bytes)], reason)`` from a sample log.

    A line is ``<ISO8601> <available bytes>``; blank lines are skipped. Anything
    else yields ``(None, reason)`` -- a malformed log is an unavailable reading,
    never a rate computed from the lines that happened to parse, because a
    silently dropped sample is a silently changed window.
    """
    samples = []
    for number, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            continue
        fields = line.split()
        if len(fields) != 2:
            return None, f"line {number} is not '<timestamp> <bytes>'"
        try:
            stamp = datetime.fromisoformat(fields[0].replace("Z", "+00:00"))
        except ValueError:
            return None, f"line {number} has an unreadable timestamp"
        if stamp.tzinfo is None:
            return None, f"line {number} has a timestamp without a zone"
        try:
            available = int(fields[1])
        except ValueError:
            return None, f"line {number} has a non-numeric byte count"
        if available < 0:
            return None, f"line {number} has a negative byte count"
        samples.append((stamp.astimezone(timezone.utc), available))
    if not samples:
        return None, "no samples"
    samples.sort(key=lambda row: row[0])
    return samples, None


def anchor_for(samples, window_seconds):
    """The newest sample at or before ``newest - window``; None when the log is
    shorter than the window (the window cannot be named, so it is not reported)."""
    newest = samples[-1][0]
    cutoff = newest - timedelta(seconds=window_seconds)
    older = [row for row in samples if row[0] <= cutoff]
    return older[-1] if older else None


def drain_per_day(samples, window_seconds):
    """``(rate_bytes_per_day, span_seconds)`` anchored at the newest sample.

    Positive means draining. ``(None, span)`` when the window has no anchor or its
    span is below :data:`MIN_WINDOW_SECONDS`.
    """
    anchor = anchor_for(samples, window_seconds)
    if anchor is None:
        return None, None
    span = (samples[-1][0] - anchor[0]).total_seconds()
    if span < MIN_WINDOW_SECONDS:
        return None, span
    return (anchor[1] - samples[-1][1]) / span * 86400.0, span


def eta_hours(headroom_bytes, rate_per_day):
    """Hours to the floor at ``rate_per_day``; None when not draining or already
    at or below it (the caller reports that state, never a negative countdown)."""
    if rate_per_day is None or rate_per_day <= 0 or headroom_bytes <= 0:
        return None
    return headroom_bytes / rate_per_day * 24.0


def _label(window_seconds):
    for unit, size in (("d", 86400), ("h", 3600), ("m", 60), ("s", 1)):
        if window_seconds % size == 0:
            return f"{window_seconds // size}{unit}"
    return f"{window_seconds}s"


#: A rate is labelled with its requested window, but it is measured over the span
#: between the anchor and the newest sample. The anchor is the newest sample at or
#: before ``newest - window``, so a uniformly sampled log measures the window to
#: within one sample interval; a sparse or gapped log does not. When the measured
#: span differs from the window by more than this fraction the span is printed with
#: the rate, because the label would otherwise overstate what was measured. 5% is
#: "at least twenty samples per window", the coarsest sampling that supports the
#: label; a shorter difference is the anchor's own granularity, not a defect.
SPAN_LABEL_TOLERANCE = 0.05


def _span_text(span_seconds):
    """``'2.52d'``/``'19.15min'``/``'30s'``: the span a rate was measured over."""
    if span_seconds >= 86400:
        return f"{span_seconds / 86400:.2f}d"
    if span_seconds >= 3600:
        return f"{span_seconds / 3600:.2f}h"
    if span_seconds >= 60:
        return f"{span_seconds / 60:.2f}min"
    return f"{span_seconds:.0f}s"


def report(samples, floor_bytes, windows, horizon_hours):
    """The printed lines and the exit code. Separated from ``main`` so the
    verdict is testable without a stdin, a clock, or an exit."""
    newest_t, newest_b = samples[-1]
    headroom = newest_b - floor_bytes
    lines = [f"level {newest_b}B/{newest_b / 2**30:.2f}GiB headroom "
             f"{headroom}B/{headroom / 2**30:.2f}GiB to floor "
             f"{floor_bytes / 2**30:.1f}GiB "
             f"(newest sample {newest_t:%Y-%m-%dT%H:%M:%SZ})"]
    rates = []
    not_draining = False
    for window in windows:
        rate, span = drain_per_day(samples, window)
        name = _label(window)
        if rate is None:
            lines.append(f"  {name:>4}: log shorter than the window" if span is None
                         else f"  {name:>4}: no anchor (span {span:.0f}s)")
            continue
        # The label names the requested window; the rate is measured over the span
        # from the anchor to the newest sample. Print that span when it departs from
        # the label, so a sparse or gapped log cannot present a short window as the
        # measurement (witness wake 123952: ``2d`` printed for a 2.52-day span).
        annotated = ""
        if abs(span - window) > window * SPAN_LABEL_TOLERANCE:
            annotated = f" (span {_span_text(span)})"
        rates.append((name, rate))
        if rate <= 0:
            not_draining = True
            lines.append(f"  {name:>4}: {rate / 2**30:+6.2f}GiB/day{annotated} "
                         "-> not-draining")
            continue
        hours = eta_hours(headroom, rate)
        target = (f"{hours:5.2f}h to floor" if hours is not None else "at/below floor")
        lines.append(f"  {name:>4}: {rate / 2**30:+6.2f}GiB/day{annotated} -> {target}")
    if headroom <= 0:
        lines.append(f"RED    below the floor by {-headroom / 2**30:.2f}GiB")
        return lines, 1
    if not rates:
        # Every window is longer than the log: nothing was measured, so nothing
        # is claimed. An unmeasurable log is not a volume that is holding.
        lines.append("UNKNOWN no window anchored: the log is shorter than every window")
        return lines, 2
    drainings = sorted(eta for eta in (eta_hours(headroom, rate)
                                       for _name, rate in rates)
                       if eta is not None)
    if not drainings:
        lines.append("GREEN  no window is draining; no floor ETA")
        return lines, 0
    soonest = drainings[0]
    # Two ways the windows can disagree: their ETAs round apart, or one window says
    # the volume is not draining while another yields a countdown. The second used to
    # print as a unanimous ETA (witness wake 123952 case G: ``1h: not-draining`` with
    # ``7d: 3192.00h`` printed a plain ``GREEN floor in 3192.00h``).
    etas_differ = len({round(eta, 1) for eta in drainings}) > 1
    disagree = etas_differ or not_draining
    span_text = (f"{soonest:.2f}-{drainings[-1]:.2f}h" if etas_differ
                 else f"{soonest:.2f}h")
    note = " (windows disagree: window-only projection)" if disagree else ""
    verdict = "RED   " if soonest < horizon_hours else "GREEN "
    lines.append(f"{verdict} floor in {span_text}{note} "
                 f"(horizon {horizon_hours:.0f}h)")
    return lines, 1 if soonest < horizon_hours else 0


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Present-anchored drain rate and floor ETA on a sample log.")
    parser.add_argument("--floor-bytes", default=str(DEFAULT_FLOOR_BYTES),
                        metavar="N", help="countdown target "
                        f"(default: {DEFAULT_FLOOR_BYTES}, the core scan's floor)")
    parser.add_argument("--windows", default=DEFAULT_WINDOWS, metavar="LIST",
                        help=f"comma-separated windows (default: {DEFAULT_WINDOWS})")
    parser.add_argument("--horizon-hours", default=str(DEFAULT_HORIZON_HOURS),
                        metavar="H", help="RED when the floor is projected inside "
                        f"this many hours (default: {DEFAULT_HORIZON_HOURS:g})")
    args = parser.parse_args(argv)
    try:
        floor = int(args.floor_bytes)
        horizon = float(args.horizon_hours)
    except ValueError:
        print("UNKNOWN disk rate (floor-bytes or horizon-hours is not a number)")
        return 2
    if floor <= 0 or horizon <= 0:
        print("UNKNOWN disk rate (floor-bytes and horizon-hours must be positive)")
        return 2
    windows = [parse_window(part) for part in args.windows.split(",") if part.strip()]
    if not windows or any(window is None or window < MIN_WINDOW_SECONDS for window in windows):
        print(f"UNKNOWN disk rate (windows must be like '30m' and at least "
              f"{MIN_WINDOW_SECONDS}s)")
        return 2
    samples, reason = parse_samples(sys.stdin.read())
    if samples is None:
        print(f"UNKNOWN disk rate ({reason})")
        return 2
    lines, code = report(samples, floor, windows, horizon)
    print("\n".join(lines))
    return code


if __name__ == "__main__":
    sys.exit(main())
