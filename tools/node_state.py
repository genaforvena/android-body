#!/usr/bin/env python3
# SPDX-License-Identifier: CC0-1.0
"""Publish a bounded host-side node-state file for the read-only perception consumer.

From the rendezvous queue alone, three situations look identical: the app is OFF,
it is durably ON with *collect-only* selected (no HTTP by design), or delivery has
failed. ``tools/device_state.py`` separates them from already-read device text;
this publisher projects that one classification into the small JSON document the
perception consumer reads, so a class-b delivery-gap detection can name *why* the
producer is silent instead of only that it is (contract agreed with the perception
owner, chat 75665).

Document (exactly these keys, never the endpoint or the node secret):

    {"node": "note3",
     "mode": "ON_SENDING|ON_COLLECT_ONLY|ON_NOT_RUNNING|OFF|UNKNOWN",
     "desired_on": true, "collect_only": false,
     "observed_at_epoch_s": 1760439327.5,
     "source": "tools/node_state.py",
     "reasons": ["..."]}

- ``desired_on``/``collect_only`` are ``null`` when ``mode`` is UNKNOWN: the read
  failed, so the tool has no basis for a boolean and does not fabricate one.
- A failed read publishes mode=UNKNOWN with the error as the reason, never OFF.
- Written atomically (temp file + rename, 0600); a reader never sees a partial
  document and never sees a file left behind by a failed write.
- Published at ``<site>/body/perception/node-state-<node>.json``, the path the
  consumer reads (watch.py:1653-1666). The consumer discovers its *own* node
  state with a non-recursive ``*.json`` glob over that directory and skips the
  ``node-state-`` prefix (watch.py:1640-1650); the prefix is what keeps this
  document from being parsed as a perception state -- an unprefixed JSON
  document there crashed the consumer with ``KeyError('version')``
  (2026-10-14T10:58:27Z-11:01:45Z, repaired by publishing under this name).
- The consumer treats the file as valid for a bounded age and renders
  mode=unknown past it; an absent file is unknown, never OFF.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import device_state

SOURCE = "tools/node_state.py"
UNKNOWN = device_state.UNKNOWN
MODES = frozenset(
    {
        device_state.ON_SENDING,
        device_state.ON_COLLECT_ONLY,
        device_state.ON_NOT_RUNNING,
        device_state.OFF,
        device_state.UNKNOWN,
    }
)
ALLOWED_KEYS = frozenset(
    {"node", "mode", "desired_on", "collect_only", "observed_at_epoch_s", "source", "reasons"}
)
#: Longest reason string accepted. Bounds accidental leakage of a long value
#: (e.g. a URL) into the published document; real reasons are short phrases.
MAX_REASON_CHARS = 200


def document(label, state, error=None, now=None):
    """The bounded node-state document for ``state`` (a DeviceState) or an error."""
    observed = float(time.time() if now is None else now)
    if state is None:
        reason = str(error) if error else "device state unreadable"
        return {
            "node": label,
            "mode": UNKNOWN,
            "desired_on": None,
            "collect_only": None,
            "observed_at_epoch_s": observed,
            "source": SOURCE,
            "reasons": [reason],
        }
    return {
        "node": label,
        "mode": state.state,
        "desired_on": bool(state.desired_on),
        "collect_only": bool(state.collect_only),
        "observed_at_epoch_s": observed,
        "source": SOURCE,
        "reasons": list(state.reasons),
    }


def observe(adb, serial, package, timeout, label, now=None):
    """Read and classify the device, returning ``(document, state_or_None)``.

    Never raises for an unreadable device: an unreadable device is a state this
    tool reports, not a failure that hides the previous document's age.
    """
    try:
        state = device_state.read_device(adb, serial, package, timeout)
    except (OSError, subprocess.SubprocessError, RuntimeError) as error:
        return document(label, None, error=error, now=now), None
    return document(label, state, now=now), state


def assert_bounded(document_dict):
    """Reject a document that is not the agreed bounded shape."""
    keys = set(document_dict)
    if keys != set(ALLOWED_KEYS):
        raise ValueError(f"unexpected node-state keys: {sorted(keys ^ set(ALLOWED_KEYS))}")
    if document_dict["mode"] not in MODES:
        raise ValueError(f"unknown node-state mode: {document_dict['mode']!r}")
    for reason in document_dict["reasons"]:
        if not isinstance(reason, str) or len(reason) > MAX_REASON_CHARS:
            raise ValueError("node-state reason is not a bounded string")


def publish(output, document_dict):
    """Write ``document_dict`` to ``output`` atomically as 0600 JSON."""
    assert_bounded(document_dict)
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(document_dict, sort_keys=True) + "\n"
    tmp = output.with_name(f"{output.name}.tmp{os.getpid()}")
    try:
        descriptor = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, output)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


#: The consumer skips this prefix when globbing its own node state (watch.py:1640);
#: a document without it in the perception directory is parsed as a state and
#: crashes the consumer, so the prefix is part of the contract, not cosmetics.
NODE_STATE_PREFIX = "node-state-"


def default_output(site, label):
    return Path(site) / "body" / "perception" / f"{NODE_STATE_PREFIX}{label}.json"


def run_once(args):
    """Publish one document. Returns the exit status."""
    doc, state = observe(
        args.adb, args.serial, args.package, args.timeout, args.label
    )
    output = Path(args.output) if args.output else default_output(args.site, args.label)
    publish(output, doc)
    line = (
        state.line(args.label) if state is not None
        else f"device-state {args.label}: {UNKNOWN} ({doc['reasons'][0]})"
    )
    print(f"{line} -> {output}")
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--site", required=True, help="site root (writes body/perception/node-state-<node>.json)")
    parser.add_argument("--serial", required=True, help="adb serial of the node")
    parser.add_argument("--package", default="org.androidbody")
    parser.add_argument("--label", default="note3")
    parser.add_argument("--adb", default="adb", help="adb command; may be multi-word (default: adb)")
    parser.add_argument("--timeout", type=float, default=10.0, help="per-command seconds")
    parser.add_argument("--output", help="explicit document path (default: site/body/perception/)")
    args = parser.parse_args(argv)
    # One document per invocation: the 60s cadence is the systemd timer's job
    # (android-body-node-state.timer), not a loop in this tool.
    return run_once(args)


if __name__ == "__main__":
    sys.exit(main())
