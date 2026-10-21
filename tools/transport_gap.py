#!/usr/bin/env python3
# SPDX-License-Identifier: CC0-1.0
"""Attribute a node's delivery gap to one side of the host path.

``tools/health-check.sh`` §3b decides RED vs UNKNOWN for a silent node from two
facts only: whether the peer is reachable and whether ``tailscaled`` is running.
A silent node with a running daemon is therefore reported as a fault without
saying *which side* of the path failed — the device, the host's DERP egress, or
the ``tailscale serve`` front that proxies to the rendezvous. Measured on
2026-10-20: the three evening Redmi10 halts had ``TLS handshake error … EOF`` and
``CreateEndpoint … connection was refused`` from the phone's own tailnet address
inside two of the three silences, while ``tailscaled`` stayed ``Running``
throughout (health wake 118178, ``artifacts/health-wake118178-…`` §5). That read
could not be re-derived, because the existing gap detectors
(``body/perception/class-b|class-c|channel-delivery-gap-detectors.jsonl``) read
only the consumer cursor: they name a gap, never its cause.

This tool closes that. The **gap** is the consumer-side fact — a run of
``--min-gap`` seconds with no accepted POST from the node, taken from the host's
own halt census ``SITE/body/queues/writes.jsonl``. The **cause** is read from
the ``tailscaled`` journal over that same window, which already carries the
three separating signals:

- **A** device-pause — no journal line for the node's tailnet address inside the
  window, with ``tailscaled`` ``Running``: nothing reached the host, so the
  device did not deliver.
- **B** path-or-serve-failure — a failure line *from that address* inside the
  window: ``http: TLS handshake error from <ip>:<port>:`` or ``CreateEndpoint
  error for <ip>:<port>``. B with no A rules the device out and names the
  transport path or the serve front.
- **C** tailnet-down — the journal shows the ipn state leaving ``Running`` over
  the gap (``Switching ipn state Running -> Stopped``). C wins over B and A.
- **D** connected-no-separating-failure — the node's address appears in the
  window but no failure line does. The device reached the tailnet and the host
  recorded no failure, so the loss sits between that connection and the
  rendezvous: the serve front's accept or the device's own POST. This is the
  class the two-sided split was asking for; it is stated, not inferred away.

A gap the journal does not cover end to end is ``class=unknown``, and so is a gap
whose ipn state the journal cannot establish: a partial read is UNKNOWN, never a
pass. The one exception is C, which is asserted from a transition *inside* the
gap — positive evidence that does not depend on the window being fully read.
``serve_proxy_errors`` counts ``http: proxy error:`` lines in-window as context for
the serve front; it is reported, not used to classify, because §5 names only the
two device-address failure lines. It is host-global, not node-scoped, so it is a
hint about the serve front and never a reason for this node's class.
``address_lines`` counts every journal line naming the node's address — a netstack
in-flight line, a TLS handshake or a CreateEndpoint error — matched on token
boundaries so a neighbouring address cannot be counted, so class A means nothing
at all reached the host for the whole gap, not merely that no failure was
recorded.

Every class is reported with the counts and the in-window evidence lines that
produced it, so a reader can disagree with the verdict without re-reading the
journal. Nothing here writes, installs, connects or actuates.

Usage: ``transport_gap.py --writes FILE --journal PATH|live --node NAME --ip ADDR
[--min-gap SECONDS] [--margin SECONDS] [--state-lookback SECONDS] [--limit N]
[--since T] [--until T] [--human]``

Gaps are printed as one JSON object per line, oldest first. Exit status: ``0`` a
verdict was printed (rows, or the census held no gap at the threshold); ``2`` the
evidence was incomplete (unreadable census or journal, journalctl failure or
timeout, undecodable bytes) or the invocation was refused.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import subprocess
import sys
from pathlib import Path

RUNNING = "Running"

#: The daemon's state transitions, as the journal writes them: ``Switching ipn
#: state Running -> Stopped (WantRunning=false, nm=true)``.
IPN_RE = re.compile(r"Switching ipn state (\S+) -> (\S+)")

#: ``http: TLS handshake error from 100.103.99.16:50056: EOF``
TLS_RE = re.compile(r"http: TLS handshake error from ([\d.]+):(\d+): (.*)")

#: ``CreateEndpoint error for 100.103.99.16:50014 -> 100.81.222.19:443: connection was refused``
CREATE_ENDPOINT_RE = re.compile(
    r"CreateEndpoint error for ([\d.]+):(\d+) -> ([\d.]+):(\d+): (.*)"
)

#: ``http: proxy error: context canceled`` — the serve front, not the device.
PROXY_ERROR_RE = re.compile(r"http: proxy error: (.*)")

#: ``2026-10-20T17:39:11+00:00 mesh-home tailscaled[440947]: Switching …``
STAMP_RE = re.compile(
    r"^(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?"
    r"(?:Z|[+-]\d{2}:?\d{2})) (.*)$"
)
#: The syslog prefix ``-o short-iso`` puts between the stamp and the message:
#: ``mesh-home tailscaled[440947]: ``. Dropping it keeps the classified text to the
#: daemon's own message, so a host name can never be mistaken for evidence.
SYSLOG_RE = re.compile(r"^\S+ tailscaled\[\d+\]: ")


#: A gap at or above this many seconds is a halt worth attributing. The
#: 2026-10-20 evening page cycles ran 75.4-83.6 s and the real halts 161.4-522.0 s,
#: so 120 s separates them; the caller can widen or narrow it.
DEFAULT_MIN_GAP = 120.0

#: How far past a gap's ends to read the journal, so the state *entering* the gap
#: and the resume are both inside the window.
DEFAULT_MARGIN = 120.0
#: How far back from the scan's start to read the journal, so the ipn state the
#: first gap *entered* is inside the window. The last transition before a gap can
#: be many hours old — the daemon restarted 2026-10-20T17:39:11Z and the first
#: evening gap began 18:53:14Z, 4444 s later — so a 1 h lookback silently reads
#: every later gap as uncovered. The caller can narrow it, and ``--since`` moves
#: the window's start as well, so a bounded scan stays bounded.
DEFAULT_STATE_LOOKBACK = 86400.0


CLASS_A = "A"
CLASS_B = "B"
CLASS_C = "C"
CLASS_D = "D"
CLASS_UNKNOWN = "unknown"

CLASS_REASON = {
    CLASS_A: "device-pause: no journal line for the node address in-window",
    CLASS_B: "path-or-serve-failure: a failure line from the node address in-window",
    CLASS_C: "tailnet-down: a non-Running ipn state covered the gap",
    CLASS_D: "connected-no-separating-failure: the node address appears, no failure line",
    CLASS_UNKNOWN: "journal does not cover the gap or the ipn state cannot be established",
}

#: An IPv4 address, and nothing else: ``\A``/``\Z`` rather than ``^``/``$`` so a
#: trailing newline cannot sneak through, and each octet range-checked so a typo
#: like ``999.999.999.999`` is refused instead of matching no journal line and
#: reporting class A for an address the node never used.
_OCTET = r"(?:25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)"
ADDRESS_RE = re.compile(r"\A" + _OCTET + r"(?:\." + _OCTET + r"){3}\Z")

#: The node's address, on token boundaries. A bare substring test lets a *different*
#: address that merely extends this one (``100.103.99.1`` inside ``100.103.99.160``)
#: count as this node's own line, which is the A/D discriminator.
ADDRESS_MATCH = r"(?<![\d.]){}(?![\d.])"


def parse_stamp(text):
    """``(aware datetime, rest-of-line)`` for a journal line, or ``(None, line)``."""
    match = STAMP_RE.match(text)
    if match is None:
        return None, text
    try:
        moment = dt.datetime.fromisoformat(match.group(1).replace("Z", "+00:00"))
    except ValueError:
        return None, text
    if moment.tzinfo is None:
        return None, text
    return moment, SYSLOG_RE.sub("", match.group(2), count=1)


def parse_ts(text):
    """An aware datetime from a JSON ``ts`` field, or None."""
    if not isinstance(text, str) or not text:
        return None
    try:
        moment = dt.datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    return moment if moment.tzinfo is not None else None


def write_times(path, node, *, since=None, until=None):
    """Yield ``(moment, kind, records)`` for *node*'s accepted POSTs, oldest first.

    The halt census is the host's accepted writes; a row it cannot parse is
    skipped, and a file it cannot read raises, because an unreadable census is
    not a clean one.
    """
    with Path(path).open(encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except ValueError:
                continue
            if not isinstance(row, dict) or row.get("node") != node:
                continue
            moment = parse_ts(row.get("ts"))
            if moment is None:
                continue
            if since is not None and moment < since:
                continue
            if until is not None and moment > until:
                continue
            yield moment, row.get("kind"), row.get("records")


def gaps(writes, node, min_gap, *, since=None, until=None, limit=None):
    """``(start, end, duration)`` for every accepted-POST gap of at least *min_gap*.

    A gap is bounded by the POST that preceded it and the POST that ended it, so
    its window is exactly the period in which the host accepted nothing from the
    node. Rows are sorted before the walk, because the census is append-only
    today but the tool reads any file the caller names and a clock jump or a
    replayed file would otherwise yield a window that contains a POST.

    ``limit`` keeps the newest N gaps; the result is still oldest-first. ``0``
    means no gap, which the CLI reports as a usage refusal rather than as the
    message it prints when the census holds no gap at all.
    """
    rows = sorted(write_times(writes, node, since=since, until=until),
                  key=lambda row: row[0])
    previous = None
    found = []
    for moment, _kind, _records in rows:
        if previous is not None:
            duration = (moment - previous).total_seconds()
            if duration >= min_gap:
                found.append((previous, moment, duration))
        previous = moment
    found.sort(key=lambda gap: gap[0])
    if limit is not None:
        found = found[-limit:] if limit else []
    return found


def journal_lines_from_text(text):
    """Journal lines as ``(moment, text)``, oldest first."""
    parsed = []
    for line in text.splitlines():
        moment, rest = parse_stamp(line)
        if moment is not None:
            parsed.append((moment, rest))
    parsed.sort(key=lambda item: item[0])
    return parsed


def read_journal_lines(path):
    """A captured journal file; a read error raises so the caller reports UNKNOWN."""
    return journal_lines_from_text(Path(path).read_text(encoding="utf-8"))


def live_journal_lines(since, until):
    """Fetch the journal once for ``[since, until]``."""
    command = [
        "journalctl", "-u", "tailscaled", "-o", "short-iso",
        "--since", since.isoformat(), "--until", until.isoformat(),
    ]
    completed = subprocess.run(
        command, capture_output=True, text=True, timeout=120, check=False
    )
    if completed.returncode != 0:
        raise OSError(f"journalctl rc={completed.returncode}: {completed.stderr.strip()}")
    return journal_lines_from_text(completed.stdout)


def state_spans(lines):
    """``[(start, end_or_None, state, source)]`` from the ipn transitions, in order.

    A transition's destination state holds until the next one; before the first
    transition the state is unknown and is not a span. ``end`` is None for the
    newest span, which is the state now. The transition's *source* state is kept
    because a class-C reason that says the state "left Running" is only supported
    when the journal actually shows it leaving Running.
    """
    transitions = []
    for moment, text in lines:
        match = IPN_RE.search(text)
        if match is not None:
            transitions.append((moment, match.group(1), match.group(2)))
    spans = []
    for index, (moment, source, state) in enumerate(transitions):
        end = transitions[index + 1][0] if index + 1 < len(transitions) else None
        spans.append((moment, end, state, source))
    return spans


def tailnet_down(spans, start, end, last_line=None):
    """``(down, covered, detail)`` for the gap window.

    ``down`` is True when a non-Running span covers part of the gap, False when a
    Running span covers all of it, and None when the journal does not cover the
    whole gap. ``covered`` is False in that last case, so a partial journal read
    never yields a class: an unreadable window is UNKNOWN, not a pass.

    ``last_line`` is the newest journal line's moment, or None when the journal is
    empty. The newest span has no ``end``; clamping it to ``last_line`` rather than
    to the gap's ``end`` keeps a non-Running span from being counted as covering a
    gap the journal never reached.

    Spans are half-open — ``[span_start, span_end)``, because ``span_end`` is the
    instant the state changed — and the gap is ``[start, end)``, so a span that
    ends exactly at ``start`` and one that begins exactly at ``end`` do not overlap
    it. Treating those boundaries as overlapping turns a gap that was Running
    throughout into class C.
    """
    covered_running = False
    for span_start, span_end, state, source in spans:
        span_finish = span_end if span_end is not None else (
            end if last_line is None else min(end, last_line))
        if span_start >= end:
            break
        if span_finish <= start:
            continue
        if state != RUNNING:
            return True, True, f"ipn {source} -> {state} from {span_start.isoformat()}"
        if span_start <= start and span_finish >= end:
            covered_running = True
    if not covered_running:
        detail = ("no ipn transition in the journal window" if not spans
                  else "the journal does not cover the whole gap")
        return None, False, detail
    return False, True, "ipn Running across the gap"



def classify(lines, start, end, ip, spans, covers_window):
    """``(class, counts, evidence)`` for one gap window.

    ``covers_window`` says the journal's own lines reach from before ``start`` to
    after ``end``; without it an ``address_lines`` of 0 means only that nothing
    was read, which is UNKNOWN rather than class A.
    """
    address_re = re.compile(ADDRESS_MATCH.format(re.escape(ip)))
    attempt = 0
    tls = 0
    refused = 0
    proxy = 0
    samples = []
    for moment, text in lines:
        if moment < start or moment >= end:
            continue
        if address_re.search(text):
            attempt += 1
            if len(samples) < 8:
                samples.append(text.strip()[:200])
        match = TLS_RE.search(text)
        if match is not None and match.group(1) == ip:
            tls += 1
        match = CREATE_ENDPOINT_RE.search(text)
        if match is not None and match.group(1) == ip:
            refused += 1
        if PROXY_ERROR_RE.search(text) is not None:
            proxy += 1
    down, covered, down_detail = tailnet_down(
        spans, start, end, lines[-1][0] if lines else None)
    counts = {
        "address_lines": attempt,
        "tls_handshake_errors": tls,
        "create_endpoint_refused": refused,
        "serve_proxy_errors": proxy,
        "ipn": down_detail,
    }
    # C is asserted from a transition *inside* the gap, which is positive evidence
    # even when the journal's own lines do not reach back to `start`; every other
    # class is a count over the window, so each needs the window fully read.
    if not covered:
        klass = CLASS_UNKNOWN
    elif down:
        klass = CLASS_C
    elif not covers_window:
        klass = CLASS_UNKNOWN
    elif tls or refused:
        klass = CLASS_B
    elif attempt == 0:
        klass = CLASS_A
    else:
        klass = CLASS_D
    return klass, counts, samples


def report(writes, journal, node, ip, *, min_gap=DEFAULT_MIN_GAP, margin=DEFAULT_MARGIN,
           state_lookback=DEFAULT_STATE_LOOKBACK, since=None, until=None, limit=None):
    """Yield one result object per attributed gap, oldest first."""
    found = gaps(writes, node, min_gap, since=since, until=until, limit=limit)
    if not found:
        return
    anchor = since if since is not None else found[0][0]
    window_start = anchor - dt.timedelta(seconds=max(margin, state_lookback))
    window_end = found[-1][1] + dt.timedelta(seconds=margin)
    lines = live_journal_lines(window_start, window_end) if journal == "live" \
        else read_journal_lines(journal)
    spans = state_spans(lines)
    for start, end, duration in found:
        covers_window = bool(lines) and lines[0][0] <= start and lines[-1][0] >= end
        klass, counts, samples = classify(lines, start, end, ip, spans, covers_window)
        yield {
            "node": node,
            "ip": ip,
            "start": start.isoformat(),
            "end": end.isoformat(),
            "duration_s": round(duration, 1),
            "class": klass,
            "reason": CLASS_REASON[klass],
            **counts,
            "samples": samples,
        }


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Attribute a node's delivery gap to one side of the host path."
    )
    parser.add_argument("--writes", required=True, help="halt census (body/queues/writes.jsonl)")
    parser.add_argument("--journal", required=True, help="captured journal file, or 'live'")
    parser.add_argument("--node", required=True, help="node slug in the census")
    parser.add_argument("--ip", required=True, help="node's tailnet address, e.g. 100.103.99.16")
    parser.add_argument("--min-gap", type=float, default=DEFAULT_MIN_GAP,
                        help=f"seconds without an accepted POST that count as a halt "
                             f"(default {DEFAULT_MIN_GAP:g})")
    parser.add_argument("--margin", type=float, default=DEFAULT_MARGIN,
                        help=f"seconds of journal to read past each gap (default {DEFAULT_MARGIN:g})")
    parser.add_argument("--state-lookback", type=float, default=DEFAULT_STATE_LOOKBACK,
                        help=f"seconds before the first gap to read, so the ipn state it "
                             f"entered is covered (default {DEFAULT_STATE_LOOKBACK:g})")
    parser.add_argument("--limit", type=int, default=None,
                        help="report only the newest N gaps")
    parser.add_argument("--since", default=None, help="ISO bound for the census scan")
    parser.add_argument("--until", default=None, help="ISO bound for the census scan")
    parser.add_argument("--human", action="store_true", help="one text line per gap")
    args = parser.parse_args(argv)

    if not ADDRESS_RE.match(args.ip):
        print(f"refused: --ip {args.ip!r} is not an IPv4 address", file=sys.stderr)
        return 2
    if args.limit is not None and args.limit <= 0:
        print("refused: --limit must be positive", file=sys.stderr)
        return 2
    if args.min_gap <= 0 or args.margin < 0 or args.state_lookback < 0:
        print("refused: --min-gap must be positive; --margin/--state-lookback non-negative",
              file=sys.stderr)
        return 2
    since = parse_ts(args.since) if args.since else None
    until = parse_ts(args.until) if args.until else None
    if (args.since and since is None) or (args.until and until is None):
        print("refused: --since/--until must be ISO timestamps", file=sys.stderr)
        return 2

    try:
        rows = list(report(args.writes, args.journal, args.node, args.ip,
                           min_gap=args.min_gap, margin=args.margin,
                           state_lookback=args.state_lookback,
                           since=since, until=until, limit=args.limit))
    except (OSError, subprocess.SubprocessError, UnicodeError) as exc:
        # Incomplete evidence is UNKNOWN, matching this repository's other host
        # tools (runtime_pin.py, binding_refusal.py): 0 a verdict, 2 UNKNOWN.
        # A journalctl timeout and a non-UTF-8 census or journal belong here too,
        # not in a traceback.
        print(f"UNKNOWN {exc}", file=sys.stderr)
        return 2
    if not rows:
        print("no gap at or above the threshold")
        return 0
    for row in rows:
        if args.human:
            print(f"{row['class']:<7} {row['node']} {row['start']} -> {row['end']} "
                  f"{row['duration_s']}s addresses={row['address_lines']} "
                  f"tls_eof={row['tls_handshake_errors']} "
                  f"create_endpoint_refused={row['create_endpoint_refused']} "
                  f"serve_proxy_errors={row['serve_proxy_errors']} "
                  f"ipn={row['ipn']}")
        else:
            print(json.dumps(row, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
