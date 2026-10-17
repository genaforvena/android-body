#!/usr/bin/env python3
# SPDX-License-Identifier: CC0-1.0
"""Measure each mind pane's top-pane lease against the bound the core sync applies.

The pinned core release (``coordination/site_sync.py``) reads the last
``-- pane live <ISO>`` footer of every mind pane before it records a linked site,
and holds the replant when either predicate fails:

* ``_leases`` raises "top-pane lease is stale" once a footer's age leaves
  ``0 <= age <= 20``. ``_verify`` gives that read one retry after
  ``RENDERER_FRAME`` (20 + 2 + 5 = 27 s) -- the cycle a respawned pane needs
  before its own footer replaces the replaced process's -- but applies the same
  20 s threshold, so a pane that is *already* stale and stays silent is held.
  This check therefore judges silence against the 20 s stale bound: a respawned
  pane clears within one frame, and reading it RED in that window is the safe
  direction.
* the advance check that follows has no retry: every pane's lease must advance
  within ``3 x 6 s``. A pane whose frame cycle exceeds that bound fails it on
  most attempts, which is the churn ``tools/health-check.sh`` §1c counts.

A renderer whose frame cycle exceeds the bound therefore holds the site and then
restarts every channel service on the next advance. Measured 2026-10-16T20:05-
20:28Z: ``witness`` ~21-22 s steady, ``discover``/``permissions`` ~13 s, the
other minds ~6 s, plus one host-load episode (20:15-20:23Z, load1 ~22) in which
every pane stalled 22-53 s.

§1c's trailing-60-min restart count decays on its own between pin advances, so a
GREEN §1c is not evidence that the render cost went away (measured: 49/h at
19:53Z, 26/h at 20:04Z, 0/h at 20:28Z). This check reads the frame cycle itself.

The measurement is the pane footer -- the same artifact the core parses -- and
the history tmux retains is the frame sequence, so consecutive ``-- pane live``
stamps give exact frame intervals with no wait. The verdict is the *newest*
interval (the pane's current cycle: the advance check has no retry, so one slow
cycle is what holds) plus the age against that 20 s stale bound; the worst
interval over the retained history is reported as severity evidence. A single
replant respawn gap can therefore read RED for one cycle, which is the same
condition the core holds on, and a repaired renderer clears immediately. The
reported ``load1`` separates a pane's own render cost from a host-load episode.
Measured intervals are printed at millisecond precision and every failure names
the excess it measured, because a pane whose cycle sits a few milliseconds over
the bound otherwise prints the measured value and the bound identically
(measured 2026-10-17T09:0xZ: ``witness`` cycles of 18.001-18.004 s printed as
``18.0s over the 18.0s advance window``) and the line reads as a tool fault
rather than the 0.001-0.004 s excursion it is. The retained median is reported
beside the newest cycle, so a pane whose steady cycle sits under the bound while
single frames cross it (``witness`` 2026-10-17: median 17.76 s, 15/73 over) is
distinguishable from one whose whole cycle is too slow.

Usage: ``pane_lease.py --site SITE [--session NAME] [--panes a,b,c]
         [--socket PATH] [--depth 800] [--bound 20]``

Exit: 0 every pane's current cycle and lease age are within the bound, 1 at
least one pane exceeded it (or publishes no lease footer at all), 2 the panes
could not be read (no tmux, no socket owning the session, no declared pane).
"""

from __future__ import annotations

import argparse
import datetime
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

#: Roles whose top-pane lease the core sync verifies before recording a linked
#: site (kernel ``coordination/site_sync.py`` ``ROLES``). The site's
#: ``health/windows.json`` lists every window; the intersection is what the core
#: actually holds the replant for. ``operator`` is deliberately outside it: the
#: core's own dash-stall detector watches that pane.
CORE_LEASED_ROLES = (
    "genome", "witness", "discover", "senses", "health", "docs",
    "research-methods", "permissions",
)

#: The session option recording which site owns a session
#: (``tmux.OWNED_OPTION`` in the pinned core release). A candidate socket whose
#: session records a *different* home is another plant's server, never ours.
OWNED_OPTION = "@mishe-tauftauf-home"

#: ``site_sync._verify``'s advance check: every pane's lease must advance within
#: ``3 x 6 s``, with no retry, so a frame cycle above this holds the site. This
#: is the predicate that binds a live-but-slow renderer.
ADVANCE_BOUND_SECONDS = 18.0

#: ``site_sync._leases``' accepted lease age (stale outside ``0 <= age <= 20``).
#: Its retry applies the same threshold, so a pane already this old and still
#: silent is held; a single read at that age is the safe direction, since a
#: respawned pane clears within one frame.
STALE_BOUND_SECONDS = 20.0

#: Lines of pane history read per pane (~74 frames retained here), which bounds
#: how far back the reported worst interval reaches.
LEASE_DEPTH_LINES = 800

#: Mirrors ``observations.FOOTER_LEASE_RE`` in the pinned core release: the one
#: footer line the core parses for a lease, and the only line whose stamp is a
#: frame time. ``\u00b7`` is the middle dot the renderer writes. A footer that a
#: narrow pane wraps is *not* matched, exactly as the core does not match it.
FOOTER_LEASE_RE = re.compile(
    r"^-- pane live \d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z"
    r" \u00b7 refresh [0-9.]+s \u00b7 ticks every frame --$"
)


def lease_stamps(text):
    """Frame timestamps in *text*, oldest first. Non-footer lines are ignored."""
    stamps = []
    for line in text.splitlines():
        if not FOOTER_LEASE_RE.fullmatch(line):
            continue
        stamp = line.removeprefix("-- pane live ").split(" \u00b7 ", 1)[0]
        try:
            stamps.append(datetime.datetime.fromisoformat(stamp.replace("Z", "+00:00")))
        except ValueError:
            continue
    return stamps


def frame_intervals(stamps):
    """Frame intervals (s) between consecutive *stamps*, oldest first."""
    return [(b - a).total_seconds() for a, b in zip(stamps, stamps[1:])]


def pane_report(text, *, now, advance_bound=ADVANCE_BOUND_SECONDS, stale_bound=STALE_BOUND_SECONDS):
    """``(status, detail)`` for one pane's captured text.

    RED when the newest frame interval exceeds *advance_bound* (the core's
    advance check has no retry, so the pane's current cycle is what holds the
    site) or when the lease is already older than *stale_bound* (the core's first
    read is stale, and its retry 27 s later still finds a pane that has not
    published in the meantime -- a respawned pane clears within one frame, so
    this is the safe direction). A pane that publishes no footer at all is RED:
    the core raises "top pane has no visible lease" for it. Too little retained
    history to measure a cycle is UNKNOWN, never a pass.
    """
    if text is None:
        return "UNKNOWN", "pane capture failed"
    stamps = lease_stamps(text)
    if not stamps:
        return "RED", "no visible lease footer (core sync would hold: no visible lease)"
    age = now - max(stamps).timestamp()
    intervals = frame_intervals(stamps)
    if not intervals:
        if age > stale_bound:
            return "RED", (f"age={age:.3f}s exceeds the {stale_bound:.3f}s stale bound "
                           f"by {age - stale_bound:.3f}s; no frame interval retained")
        return "UNKNOWN", f"age={age:.1f}s; fewer than two lease footers retained, interval unmeasurable"
    newest, worst = intervals[-1], max(intervals)
    median = sorted(intervals)[len(intervals) // 2]
    if newest > advance_bound:
        return "RED", (f"age={age:.1f}s newest_interval={newest:.3f}s exceeds the {advance_bound:.3f}s advance bound "
                       f"by {newest - advance_bound:.3f}s (n={len(intervals)}, median={median:.3f}s, worst={worst:.3f}s)")
    if age > stale_bound:
        return "RED", (f"age={age:.3f}s exceeds the {stale_bound:.3f}s stale bound by {age - stale_bound:.3f}s "
                       f"(newest_interval={newest:.3f}s, median={median:.3f}s, n={len(intervals)})")
    return "GREEN", (f"age={age:.1f}s newest_interval={newest:.3f}s median={median:.3f}s "
                     f"(n={len(intervals)}, advance {advance_bound:.3f}s)")


def expected_panes(site):
    """The core-leased panes this site declares, or None when it declares none.

    The site's own ``health/windows.json`` is the source of truth for which
    windows exist; the core only leases the roles it knows (``ROLES``), so the
    intersection is what a hold would name.
    """
    try:
        windows = json.loads((Path(site) / "health" / "windows.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(windows, list):
        return None
    declared = {name for name in windows if isinstance(name, str)}
    panes = [name for name in CORE_LEASED_ROLES if name in declared]
    return panes or None


def legacy_socket(uid=None):
    """The legacy default tmux socket, before per-site sockets existed."""
    return str(Path("/tmp") / f"tmux-{os.getuid() if uid is None else uid}" / "default")


def socket_candidates(site, *, environ=None, uid=None):
    """Every socket that may host the site's session, in the core's own order.

    Mirrors ``tmux._socket_candidates`` in the pinned core release: the caller's
    own socket (``_socket_for_home``, honoring an inherited ``TMUX_TMPDIR``),
    then the legacy default, then the socket derived from the home alone
    (``_site_socket``). The caller's own socket comes first so a caller carrying
    another site's ``TMUX_TMPDIR`` still reaches this site through the
    home-derived candidate; the ambient ``TMUX`` socket is deliberately absent,
    as in the core, because session names collide across sites and a read there
    would measure another plant.
    """
    env = os.environ if environ is None else environ
    uid = os.getuid() if uid is None else uid
    site = Path(site)
    caller = env.get("TMUX_TMPDIR") or str(Path("/tmp") / f"tmux-{uid}" / site.parent.name)
    return tuple(dict.fromkeys((
        str(Path(caller) / f"tmux-{uid}" / "default"),
        legacy_socket(uid),
        str(Path("/tmp") / f"tmux-{uid}" / site.parent.name / f"tmux-{uid}" / "default"),
    )))


def _tmux(args, socket, run=subprocess.run):
    """``tmux -S *socket* *args*``, or None when tmux is unavailable."""
    env = os.environ.copy()
    if env.get("TMUX_TMPDIR"):
        # An inherited pane socket otherwise overrides the explicit -S, the
        # same split as tmux._tmux in the core.
        env.pop("TMUX", None)
    try:
        return run(["tmux", "-S", socket, *args], capture_output=True, env=env)
    except OSError:
        return None


def _owner(socket, session, run):
    """The home the session records on *socket*, or None when it records none."""
    result = _tmux(["show-option", "-qv", "-t", session, OWNED_OPTION], socket, run=run)
    if result is None or result.returncode:
        return None
    return result.stdout.decode().strip() or None


def resolve_socket(site, session, *, environ=None, uid=None, run=subprocess.run):
    """The first candidate socket that hosts *session* for *site*, or None.

    A candidate is accepted only when it answers for the session *and* the
    session records this site's home on ``@mishe-tauftauf-home``, the same
    ownership rule ``tmux.owned_socket`` applies in the pinned core release.
    Session names collide across sites (each is the site's parent directory
    name), and the first candidate is the caller's own ``TMUX_TMPDIR``, so an
    unset or foreign owner must never be taken as this site's server: a record
    without the option reads UNKNOWN here, which never passes.
    """
    wanted = str(Path(site).resolve())
    for socket in socket_candidates(site, environ=environ, uid=uid):
        result = _tmux(["has-session", "-t", session], socket, run=run)
        if result is None or result.returncode:
            continue
        if _owner(socket, session, run) == wanted:
            return socket
    return None


def capture(socket, session, pane, depth, *, run=subprocess.run):
    """The pane's captured text (history included), or None on any failure."""
    result = _tmux(["capture-pane", "-p", "-t", f"{session}:{pane}.0", "-S", f"-{depth}"],
                   socket, run=run)
    if result is None or result.returncode:
        return None
    return result.stdout.decode("utf-8", "replace")


def load1():
    """The host 1-minute load average, or None when it cannot be read."""
    try:
        return os.getloadavg()[0]
    except OSError:
        return None


def main(argv=None, *, capture_fn=capture, now=None, load=None):
    parser = argparse.ArgumentParser(description="Measure pane lease age and frame cycle.")
    parser.add_argument("--site", required=True, help="site root (reads health/windows.json)")
    parser.add_argument("--session", default=None, help="tmux session (default: the site's parent directory name)")
    parser.add_argument("--panes", default=None, help="comma-separated pane names (default: the site's core-leased panes)")
    parser.add_argument("--socket", default=None, help="tmux socket path (default: discovered)")
    parser.add_argument("--depth", type=int, default=LEASE_DEPTH_LINES, help="lines of pane history to read")
    parser.add_argument("--bound", type=float, default=ADVANCE_BOUND_SECONDS,
                        help="frame-cycle bound, the core's 3 x 6 s advance window (s)")
    parser.add_argument("--stale-bound", type=float, default=STALE_BOUND_SECONDS,
                        help="lease age bound, the core's stale threshold (s)")
    args = parser.parse_args(argv)
    site = Path(args.site).resolve()
    session = args.session or site.parent.name
    if args.panes:
        panes = [name.strip() for name in args.panes.split(",") if name.strip()]
    else:
        panes = expected_panes(site)
    if not panes:
        print(f"UNKNOWN pane lease: no core-leased pane declared in {site / 'health' / 'windows.json'}")
        return 2

    socket = args.socket or resolve_socket(site, session)
    if socket is None:
        print(f"UNKNOWN pane lease: no tmux socket owning session {session} "
              f"(candidates: {', '.join(socket_candidates(site))})")
        return 2

    now = time.time() if now is None else now
    host_load = load1() if load is None else load
    context = "" if host_load is None else f" load1={host_load:.1f}"
    failed = False
    unknown = False
    for pane in panes:
        status, detail = pane_report(capture_fn(socket, session, pane, args.depth),
                                     now=now, advance_bound=args.bound, stale_bound=args.stale_bound)
        print(f"{status:<6} pane lease {pane} {detail}{context}")
        failed = failed or status == "RED"
        unknown = unknown or status == "UNKNOWN"
    return 1 if failed else (2 if unknown else 0)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
