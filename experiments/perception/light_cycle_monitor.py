#!/usr/bin/env python3
"""Monitor a node's retained light observations for cycle resumption (dim/dark -> clearly lit).

Bounded: tails ``<site>/body/queues/<node>.observations.log``, applies the node's frozen
resumption rule to every newly appended ``light lux=`` row, appends a resumption event to
``light-cycle-resumed.jsonl`` and publishes a heartbeat to ``light-cycle-monitor-state.json``.
No physical actions, no phone mutation; the run ends after ``--max-polls`` tail checks.

The rule is defined over *consecutive samples of the retained observation stream*, so the
monitor consumes that stream directly. Polling a lossy projection of it (``space.json``, a
30 s view of a ~5 s stream) would decimate the samples and silently turn a 3-sample dwell
into a ~15-sample one, so the monitor would stop applying the frozen rule it names.

Each node carries its own frozen rule, because the rule is sensor-derived and a threshold is
not transferable between sensors (research-methods DM 92189):

* ``note3``   -- single-sample predicate at ``RESUME_LUX_MIN = 7.0`` (Note3's dim band is
  <= 5.4 lux, its lit medians 10-16 lux).
* ``redmi10`` -- ``ARM_LUX_MAX = 6.0``, ``RESUME_LUX_MIN = 10.0``, ``DARK_DWELL_SAMPLES = 3``,
  frozen by research-methods on a training window (see
  ``artifacts/research-methods-wake92289-redmi10-resumption-rule.md``).

``--node`` selects the node; the default is ``redmi10``, the node whose light channel is
live. ``note3`` is collect-only, so its rule stays dormant until delivery is re-enabled --
the named trigger for the alternative deferral (research-methods DM 92250).

The monitor starts at the end of the retained log: it observes from now on, so a resumption
whose dim readings were never observed this run is not claimed (a restart clears the
baseline). History is scored separately by research-methods' frozen-rule reproducer; the
monitor does not re-derive it.

The heartbeat is the detector's own liveness and armed state, published atomically so a
consumer can distinguish "armed, nothing yet" from "detector silent"; a stale heartbeat is
the only honest signal that the detector stopped. ``lux`` is null when the newest sample is
older than ``--stale-seconds``: then the *source* is stale, not the detector.

A resumption row names each quantity it carries (the renderer in ``watch.py`` reports them
verbatim):

* ``samples`` -- light samples consumed this run at the fire instant, the same quantity the
  heartbeat publishes under ``samples``. It was written as ``poll`` before 2026-10-16, which
  collided with the heartbeat's ``poll`` (the tail-check index, a different quantity) in one
  rendered block: a reader saw ``poll=557`` (heartbeat) beside ``poll=3284`` (row) and could
  infer a restart that never happened.
* ``prev_lux``/``prev_observed_unix`` -- the sample immediately before the fire: its lux and
  its phone epoch, so the pair describes one observation. For the dark-dwell rule this was
  previously the *first* dark sample's epoch paired with the *last* dark sample's lux, and
  the view rendered the resulting span as ``prev_observed_gap``, which read as the gap to
  the previous observation (43.6 s) when it was the baseline span (68.6 s).
* ``baseline_first_unix`` -- the first baseline sample's phone epoch, i.e. where the
  ``baseline_samples`` window starts; the view derives ``baseline_span_s`` from it. It was
  written as ``prev_observed_unix`` (a name the corrected ``prev_observed_unix`` now owns).
"""
import argparse
import json
import os
import re
import time
from pathlib import Path

#: Per-node frozen resumption rules (see the module docstring for provenance).
RULES = {
    "note3": {
        "rule": "single-sample",
        "resume_lux_min": 7.0,
    },
    "redmi10": {
        "rule": "dark-dwell",
        "arm_lux_max": 6.0,
        "resume_lux_min": 10.0,
        "dark_dwell_samples": 3,
    },
}
DEFAULT_NODE = "redmi10"

#: A retained ``light`` row: ``<seq> <epoch> light lux=<float> ...``. Rows without a lux
#: (``light unavailable reason=stale``) are not samples and are skipped.
LIGHT_ROW = re.compile(r"^(\d+) (\d+) light lux=([0-9.E+-]+)")

LOG_FILE = Path(__file__).resolve().parent / "artifacts" / "light-cycle-resumed.jsonl"
HEARTBEAT_FILE = LOG_FILE.parent / "light-cycle-monitor-state.json"


def default_site():
    """The ``.mishe-tauftauf`` site that owns this checkout (source-copy layout)."""
    return Path(__file__).resolve().parents[2] / ".mishe-tauftauf"


def initial_offset(path):
    """Offset the live run starts reading at: the end of the retained log (see docstring)."""
    try:
        return path.stat().st_size
    except OSError:
        return 0


def read_new_rows(path, offset):
    """Return ``(rows, offset)`` for complete ``light lux=`` rows appended after ``offset``.

    Only bytes up to the last newline are consumed, so a row the writer is still appending
    is left for the next check instead of being parsed half-written. A truncated or rotated
    file is re-read from its start.
    """
    rows = []
    try:
        size = path.stat().st_size
    except OSError:
        return rows, offset
    if size < offset:
        offset = 0
    with open(path, "rb") as stream:
        stream.seek(offset)
        data = stream.read()
    cut = data.rfind(b"\n")
    if cut < 0:
        return rows, offset
    for line in data[:cut].split(b"\n"):
        match = LIGHT_ROW.match(line.decode("utf-8", "replace"))
        if match:
            rows.append((int(match.group(1)), int(match.group(2)), float(match.group(3))))
    return rows, offset + cut + 1


class ResumptionDetector:
    """State machine for one node's frozen resumption rule over its light samples."""

    def __init__(self, node):
        if node not in RULES:
            raise ValueError("unknown node %r; known: %s" % (node, sorted(RULES)))
        self.node = node
        self.rule = RULES[node]
        self.prev_lux = None
        self.prev_epoch = None
        self.last_seq = None
        self.prev_seq = None
        self.samples = 0
        self.dark_run = 0
        self.dark_samples = []  # (seq, epoch, lux) of the current consecutive dark run

    @property
    def armed(self):
        """True when this run has seen enough consecutive dark samples for a fire."""
        if self.rule["rule"] == "dark-dwell":
            return self.dark_run >= self.rule["dark_dwell_samples"]
        return self.prev_lux is not None

    def step(self, seq, epoch, lux):
        """Consume one sample; return a resumption event dict, or None."""
        self.samples += 1
        self.last_seq = seq
        event = None
        if self.rule["rule"] == "dark-dwell":
            arm = self.rule["arm_lux_max"]
            fire = self.rule["resume_lux_min"]
            dwell = self.rule["dark_dwell_samples"]
            if self.dark_run >= dwell and lux >= fire:
                event = self._event(seq, epoch, lux, self.dark_samples)
                self.dark_run = 0
                self.dark_samples = []
            elif lux < arm:
                self.dark_run += 1
                self.dark_samples.append((seq, epoch, lux))
            else:
                self.dark_run = 0
                self.dark_samples = []
        else:
            threshold = self.rule["resume_lux_min"]
            if (self.prev_lux is not None and lux >= threshold and
                    self.prev_lux < threshold):
                event = self._event(seq, epoch, lux,
                                    [(self.prev_seq, self.prev_epoch, self.prev_lux)])
        self.prev_lux = lux
        self.prev_epoch = epoch
        self.prev_seq = seq
        return event

    def _event(self, seq, epoch, lux, baseline_samples):
        """One resumption row. Field meanings are documented in the module docstring."""
        first = baseline_samples[0] if baseline_samples else None
        return {
            "event": "light-cycle-resumed",
            "node": self.node,
            "rule": self.rule["rule"],
            "rule_constants": {key: self.rule[key] for key in self.rule if key != "rule"},
            "lux": lux,
            "prev_lux": self.prev_lux,
            "prev_observed_unix": self.prev_epoch,
            "baseline_samples": [list(sample) for sample in baseline_samples],
            "baseline_first_unix": first[1] if first else None,
            "threshold_lux": self.rule["resume_lux_min"],
            "seq": seq,
            "epoch": epoch,
            "samples": self.samples,
            "timestamp_unix": time.time(),
        }


def write_heartbeat(fields):
    """Atomically publish this run's liveness/armed state for the consumer."""
    content = json.dumps(dict(fields, pid=os.getpid()), sort_keys=True) + "\n"
    pending = HEARTBEAT_FILE.with_name("." + HEARTBEAT_FILE.name + ".pending")
    try:
        with open(pending, "w") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(pending, HEARTBEAT_FILE)
    except OSError:
        pass


def run(args):
    """Tail the node's retained log and apply its frozen rule. Returns the exit status."""
    site = args.site or default_site()
    queues = site / "body" / "queues"
    if not queues.is_dir():
        raise SystemExit("no body/queues directory under %s" % site)
    log_path = queues / ("%s.observations.log" % args.node)

    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    detector = ResumptionDetector(args.node)
    offset = initial_offset(log_path)
    started_unix = time.time()

    for poll in range(args.max_polls):
        rows, offset = read_new_rows(log_path, offset)
        for seq, epoch, lux in rows:
            event = detector.step(seq, epoch, lux)
            if event is not None:
                with open(LOG_FILE, "a") as stream:
                    stream.write(json.dumps(event, sort_keys=True) + "\n")
                print("RESUMED node=%s lux=%s seq=%s baseline=%s samples=%s" %
                      (args.node, lux, seq, event["prev_lux"], event["samples"]))
        now = time.time()
        age = None if detector.prev_epoch is None else now - detector.prev_epoch
        fresh = age is not None and age <= args.stale_seconds
        write_heartbeat({
            "node": args.node,
            "rule": detector.rule["rule"],
            "rule_constants": {key: detector.rule[key]
                              for key in detector.rule if key != "rule"},
            "threshold_lux": detector.rule["resume_lux_min"],
            "poll": poll,
            "samples": detector.samples,
            "interval_seconds": args.interval,
            "max_polls": args.max_polls,
            "source": str(log_path),
            "cursor_seq": detector.last_seq,
            "source_age_seconds": age,
            "lux": detector.prev_lux if fresh else None,
            "prev_lux": detector.prev_lux,
            "armed": detector.armed,
            "arm_lux_max": detector.rule.get("arm_lux_max"),
            "dark_run": detector.dark_run,
            "dark_dwell_samples": detector.rule.get("dark_dwell_samples"),
            "started_unix": started_unix,
            "timestamp_unix": now,
        })
        time.sleep(args.interval)

    print("NO_RESUMPTION after %d checks" % args.max_polls)
    return 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--node", default=DEFAULT_NODE, choices=sorted(RULES),
                        help="node whose light channel to monitor (default: %(default)s)")
    parser.add_argument("--site", type=Path, default=None,
                        help="site root holding body/queues (default: this checkout's site)")
    parser.add_argument("--interval", type=float, default=10.0,
                        help="seconds between tail checks (default: %(default)s)")
    parser.add_argument("--max-polls", type=int, default=3300,
                        help="max tail checks (default: %(default)s)")
    parser.add_argument("--stale-seconds", type=float, default=30.0,
                        help="freshness window for the newest sample (default: %(default)s)")
    return run(parser.parse_args())


if __name__ == "__main__":
    raise SystemExit(main())
