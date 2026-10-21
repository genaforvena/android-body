#!/usr/bin/env python3
# SPDX-License-Identifier: CC0-1.0
"""Deterministic tests for tools/transport_gap.py.

Every case uses a captured writes census and a captured journal in a temporary
directory, so no case touches the live census, the journal, the network or a
device. The fixtures are the shapes the real 2026-10-20 Redmi10 evening produced
(``TLS handshake error … EOF``, ``CreateEndpoint error … connection was refused``
/ ``operation timed out``, ``netstack: decrementing connsInFlightByClient[ip]``,
``Switching ipn state``), transcribed rather than copied so the assertions name
the behaviour instead of a byte-for-byte paste.
"""

import contextlib
import datetime as dt
import io
import json
import tempfile
import unittest
from pathlib import Path


import transport_gap

import unittest.mock

IP = "100.103.99.16"
OTHER = "100.99.99.99"
RUNNING = ("Switching ipn state Starting -> Running (WantRunning=true, nm=true)")


def write(path, rows):
    with Path(path).open("w", encoding="utf-8") as handle:
        for moment, kind in rows:
            handle.write(json.dumps({"ts": moment.isoformat(), "node": "redmi10",
                                     "kind": kind, "records": 4}) + "\n")


def journal(path, lines):
    """Write journal lines, each prefixed with a short-iso stamp."""
    with Path(path).open("w", encoding="utf-8") as handle:
        for moment, text in lines:
            handle.write(f"{moment.isoformat()} mesh-home tailscaled[1]: {text}\n")


def at(text):
    return dt.datetime.fromisoformat(text)


def stderr_run(argv):
    """``(exit code, stdout, stderr)`` for one CLI invocation."""
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = transport_gap.main(argv)
    return code, out.getvalue(), err.getvalue()


class GapDerivationTest(unittest.TestCase):
    """The gap is the consumer-side fact: seconds without an accepted POST."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.writes = self.root / "writes.jsonl"

    def tearDown(self):
        self.tmp.cleanup()

    def test_a_gap_is_bounded_by_the_posts_around_it(self):
        write(self.writes, [(at("2026-10-20T10:00:00+00:00"), "observations"),
                            (at("2026-10-20T10:02:00+00:00"), "observations"),
                            (at("2026-10-20T10:10:00+00:00"), "observations")])
        found = transport_gap.gaps(self.writes, "redmi10", 200.0)
        self.assertEqual([(g[0].isoformat(), g[1].isoformat(), g[2]) for g in found],
                         [("2026-10-20T10:02:00+00:00", "2026-10-20T10:10:00+00:00",
                           480.0)])

    def test_gaps_below_the_threshold_are_not_reported(self):
        write(self.writes, [(at("2026-10-20T10:00:00+00:00"), "observations"),
                            (at("2026-10-20T10:00:30+00:00"), "observations")])
        self.assertEqual(transport_gap.gaps(self.writes, "redmi10", 60.0), [])

    def test_a_threshold_at_the_boundary_counts(self):
        write(self.writes, [(at("2026-10-20T10:00:00+00:00"), "observations"),
                            (at("2026-10-20T10:02:00+00:00"), "observations")])
        self.assertEqual(len(transport_gap.gaps(self.writes, "redmi10", 120.0)), 1)
        self.assertEqual(transport_gap.gaps(self.writes, "redmi10", 120.1), [])

    def test_only_the_named_nodes_posts_count(self):
        with self.writes.open("w", encoding="utf-8") as handle:
            handle.write(json.dumps({"ts": "2026-10-20T10:00:00+00:00",
                                     "node": "note3", "kind": "observations"}) + "\n")
            handle.write(json.dumps({"ts": "2026-10-20T10:05:00+00:00",
                                     "node": "redmi10", "kind": "observations"}) + "\n")
        self.assertEqual(transport_gap.gaps(self.writes, "redmi10", 60.0), [])

    def test_limit_keeps_the_newest_gaps(self):
        write(self.writes, [(at("2026-10-20T10:00:00+00:00"), "observations"),
                            (at("2026-10-20T10:10:00+00:00"), "observations"),
                            (at("2026-10-20T10:20:00+00:00"), "observations"),
                            (at("2026-10-20T10:30:00+00:00"), "observations")])
        found = transport_gap.gaps(self.writes, "redmi10", 60.0, limit=2)
        self.assertEqual([g[0].isoformat() for g in found],
                         ["2026-10-20T10:10:00+00:00", "2026-10-20T10:20:00+00:00"])

    def test_limit_zero_returns_no_gap(self):
        write(self.writes, [(at("2026-10-20T10:00:00+00:00"), "observations"),
                            (at("2026-10-20T10:10:00+00:00"), "observations"),
                            (at("2026-10-20T10:20:00+00:00"), "observations")])
        self.assertEqual(transport_gap.gaps(self.writes, "redmi10", 60.0, limit=0), [])

    def test_since_until_bound_the_scan(self):
        write(self.writes, [(at("2026-10-20T10:00:00+00:00"), "observations"),
                            (at("2026-10-20T11:00:00+00:00"), "observations"),
                            (at("2026-10-20T12:00:00+00:00"), "observations")])
        found = transport_gap.gaps(self.writes, "redmi10", 60.0,
                                   since=at("2026-10-20T10:30:00+00:00"))
        self.assertEqual([(g[0].isoformat(), g[1].isoformat()) for g in found],
                         [("2026-10-20T11:00:00+00:00", "2026-10-20T12:00:00+00:00")])

    def test_a_row_without_a_readable_timestamp_is_skipped(self):
        with self.writes.open("w", encoding="utf-8") as handle:
            handle.write(json.dumps({"ts": "not-a-time", "node": "redmi10",
                                     "kind": "observations"}) + "\n")
            handle.write(json.dumps({"ts": "2026-10-20T10:00:00+00:00",
                                     "node": "redmi10", "kind": "observations"}) + "\n")
            handle.write("{not json}\n")
            handle.write(json.dumps({"ts": "2026-10-20T10:10:00+00:00",
                                     "node": "redmi10", "kind": "observations"}) + "\n")
        found = transport_gap.gaps(self.writes, "redmi10", 60.0)
        self.assertEqual([(g[0].isoformat(), g[1].isoformat()) for g in found],
                         [("2026-10-20T10:00:00+00:00", "2026-10-20T10:10:00+00:00")])


class ClassificationTest(unittest.TestCase):
    """A/B/C/D over one gap, each with the separating signal present."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.writes = self.root / "writes.jsonl"
        self.journal = self.root / "journal.txt"
        self.start = at("2026-10-20T18:53:00+00:00")
        self.end = at("2026-10-20T19:02:00+00:00")

    def tearDown(self):
        self.tmp.cleanup()

    def _run(self, journal_lines, *, cover=True, **kwargs):
        """Write a census holding one gap and a journal covering it end to end.

        ``cover=False`` leaves the window open on purpose, for the case where a
        partial read must read UNKNOWN rather than a class.
        """
        write(self.writes, [(self.start, "observations"), (self.end, "observations")])
        lines = list(journal_lines)
        if cover:
            lines.append((self.end + dt.timedelta(minutes=5), "health(warnable=x): ok"))
        journal(self.journal, lines)
        return list(transport_gap.report(
            self.writes, str(self.journal), "redmi10", IP,
            min_gap=60.0, **kwargs))[0]

    def test_a_gap_with_no_address_line_and_running_tailnet_is_a_device_pause(self):
        row = self._run([
            (at("2026-10-20T17:39:11+00:00"), RUNNING),
            (at("2026-10-20T18:50:00+00:00"), "health(warnable=no-derp-connection): ok"),
        ])
        self.assertEqual(row["class"], "A")
        self.assertEqual(row["address_lines"], 0)
        self.assertEqual(row["ipn"], "ipn Running across the gap")

    def test_a_tls_handshake_eof_from_the_node_address_is_a_path_failure(self):
        row = self._run([
            (at("2026-10-20T17:39:11+00:00"), RUNNING),
            (at("2026-10-20T18:53:40+00:00"),
             "http: TLS handshake error from 100.103.99.16:49984: EOF"),
            (at("2026-10-20T18:55:29+00:00"),
             "http: TLS handshake error from 100.103.99.16:49996: EOF"),
        ])
        self.assertEqual(row["class"], "B")
        self.assertEqual(row["tls_handshake_errors"], 2)

    def test_a_create_endpoint_refusal_from_the_node_address_is_a_path_failure(self):
        row = self._run([
            (at("2026-10-20T17:39:11+00:00"), RUNNING),
            (at("2026-10-20T18:54:24+00:00"),
             "CreateEndpoint error for 100.103.99.16:50014 -> 100.81.222.19:443: "
             "connection was refused"),
        ])
        self.assertEqual(row["class"], "B")
        self.assertEqual(row["create_endpoint_errors"], 1)
        self.assertEqual(row["tls_handshake_errors"], 0)


    def test_a_create_endpoint_timeout_from_the_node_address_is_counted_not_named_a_refusal(self):
        """The count is reason-agnostic: a timeout is B, and not a refusal census."""
        row = self._run([
            (at("2026-10-20T17:39:11+00:00"), RUNNING),
            (at("2026-10-20T18:54:24+00:00"),
             "CreateEndpoint error for 100.103.99.16:50014 -> 100.81.222.19:443: "
             "operation timed out"),
        ])
        self.assertEqual(row["class"], "B")
        self.assertEqual(row["create_endpoint_errors"], 1)
        self.assertEqual(row["tls_handshake_errors"], 0)

    def test_a_failure_line_from_another_address_does_not_classify_this_node(self):
        row = self._run([
            (at("2026-10-20T17:39:11+00:00"), RUNNING),
            (at("2026-10-20T18:54:24+00:00"),
             f"http: TLS handshake error from {OTHER}:50014: EOF"),
            (at("2026-10-20T18:55:00+00:00"),
             f"CreateEndpoint error for {OTHER}:50015 -> 100.81.222.19:443: "
             "connection was refused"),
        ])
        self.assertEqual(row["class"], "A")
        self.assertEqual(row["address_lines"], 0)
        self.assertEqual(row["tls_handshake_errors"], 0)
        self.assertEqual(row["create_endpoint_errors"], 0)

    def test_a_netstack_line_without_a_failure_is_connected_no_separating_failure(self):
        row = self._run([
            (at("2026-10-20T17:39:11+00:00"), RUNNING),
            (at("2026-10-20T19:01:30+00:00"),
             "netstack: decrementing connsInFlightByClient[100.103.99.16] because the "
             "packet was not handled; new value is 0"),
        ])
        self.assertEqual(row["class"], "D")
        self.assertEqual(row["address_lines"], 1)
        self.assertEqual(row["tls_handshake_errors"], 0)

    def test_a_tailnet_stop_over_the_gap_wins_over_a_path_failure(self):
        row = self._run([
            (at("2026-10-20T17:39:11+00:00"), RUNNING),
            (at("2026-10-20T18:55:00+00:00"),
             "Switching ipn state Running -> Stopped (WantRunning=false, nm=true)"),
            (at("2026-10-20T19:01:00+00:00"),
             "Switching ipn state NoState -> Starting (WantRunning=true, nm=true)"),
            (at("2026-10-20T19:01:30+00:00"), RUNNING),
            (at("2026-10-20T18:56:00+00:00"),
             "http: TLS handshake error from 100.103.99.16:49984: EOF"),
        ])
        self.assertEqual(row["class"], "C")
        self.assertIn("Stopped", row["ipn"])

    def test_a_tailnet_that_is_running_the_whole_gap_is_not_class_c(self):
        row = self._run([
            (at("2026-10-20T17:39:11+00:00"), RUNNING),
            (at("2026-10-20T18:56:00+00:00"),
             "http: TLS handshake error from 100.103.99.16:49984: EOF"),
            (at("2026-10-20T19:05:00+00:00"),
             "Switching ipn state Running -> Stopped (WantRunning=false, nm=true)"),
        ])
        self.assertEqual(row["class"], "B")
        self.assertNotIn("Stopped", row["ipn"])

    def test_a_gap_the_journal_does_not_cover_is_unknown_never_a_pass(self):
        # The journal starts inside the gap: no line before `start`, so an
        # address count of 0 would be an artefact of the read.
        row = self._run([
            (at("2026-10-20T18:56:00+00:00"),
             "http: TLS handshake error from 100.103.99.16:49984: EOF"),
            (at("2026-10-20T19:05:00+00:00"), "health(warnable=no-derp-connection): ok"),
        ], cover=False)
        self.assertEqual(row["class"], "unknown")
        self.assertEqual(row["reason"], transport_gap.CLASS_REASON["unknown"])
    def test_a_journal_that_ends_inside_the_gap_is_unknown_too(self):
        row = self._run([
            (at("2026-10-20T17:39:11+00:00"), RUNNING),
            (at("2026-10-20T18:56:00+00:00"), "health(warnable=no-derp-connection): ok"),
        ], cover=False)
        self.assertEqual(row["class"], "unknown")
    def test_no_ipn_transition_in_the_window_is_unknown_not_running(self):
        row = self._run([
            (at("2026-10-20T18:50:00+00:00"), "health(warnable=no-derp-connection): ok"),
        ])
        self.assertEqual(row["class"], "unknown")
        self.assertIn("no ipn transition", row["ipn"])

    def test_a_stop_before_a_gap_the_journal_never_reached_is_unknown_not_c(self):
        # The transition is 53 min before the gap and the journal's last line is
        # before the gap too: a span end fabricated as the gap end must not turn a
        # non-Running state into class C on evidence the journal never reached.
        row = self._run([
            (at("2026-10-20T17:39:11+00:00"), RUNNING),
            (at("2026-10-20T18:00:00+00:00"),
             "Switching ipn state Running -> Stopped (WantRunning=false, nm=true)"),
            (at("2026-10-20T18:50:00+00:00"), "health(warnable=x): ok"),
        ], cover=False)
        self.assertEqual(row["class"], "unknown")

    def test_a_transition_inside_the_gap_is_c_even_when_the_journal_does_not_cover(self):
        # The documented C exception: a transition inside the gap is positive
        # evidence, so a journal that neither reaches back to the gap's start nor
        # past its end still yields C rather than UNKNOWN.
        row = self._run([
            (at("2026-10-20T18:55:00+00:00"),
             "Switching ipn state Running -> Stopped (WantRunning=false, nm=true)"),
        ], cover=False)
        self.assertEqual(row["class"], "C")
        self.assertIn("Stopped", row["ipn"])

    def test_undecodable_journal_bytes_raise_so_the_caller_reports_unknown(self):
        write(self.writes, [(self.start, "observations"), (self.end, "observations")])
        with self.journal.open("wb") as handle:
            handle.write(b"2026-10-20T17:39:11+00:00 mesh-home tailscaled[1]: " +
                         RUNNING.encode("utf-8") + b"\n")
            handle.write(b"2026-10-20T18:56:00+00:00 mesh-home tailscaled[1]: "
                         b"netstack conns[100.103.99.\xff16] reached\n")
        with self.assertRaises(UnicodeDecodeError):
            list(transport_gap.report(self.writes, str(self.journal), "redmi10", IP,
                                      min_gap=60.0))

    def test_a_serve_proxy_error_is_context_and_never_the_class(self):
        row = self._run([
            (at("2026-10-20T17:39:11+00:00"), RUNNING),
            (at("2026-10-20T18:58:00+00:00"), "http: proxy error: context canceled"),
        ])
        self.assertEqual(row["serve_proxy_errors"], 1)
        self.assertEqual(row["class"], "A")

    def test_samples_are_bounded_and_name_the_evidence(self):
        lines = [(at("2026-10-20T17:39:11+00:00"), RUNNING)]
        lines += [(at(f"2026-10-20T18:5{minute}:00+00:00"),
                   "http: TLS handshake error from 100.103.99.16:49984: EOF")
                  for minute in range(3, 10)]
        lines += [(at("2026-10-20T18:50:00+00:00"),
                   "http: TLS handshake error from 100.103.99.16:49984: EOF"),
                  (at("2026-10-20T19:01:50+00:00"),
                   "http: TLS handshake error from 100.103.99.16:49984: EOF")]
        row = self._run(lines)
        # Seven lines are inside the gap (18:53-18:59); 18:50 and 19:01:50 are not.
        self.assertEqual(row["tls_handshake_errors"], 8)
        self.assertLessEqual(len(row["samples"]), 8)
        self.assertIn("TLS handshake error", row["samples"][0])

    def test_the_lookback_widens_only_the_live_fetch_not_a_file_read(self):
        # A captured file is read whole: the lookback governs the window the live
        # fetch asks for, so it cannot shrink a file read.
        row = self._run([
            (at("2026-10-20T17:39:11+00:00"), RUNNING),
            (at("2026-10-20T18:56:00+00:00"),
             "http: TLS handshake error from 100.103.99.16:49984: EOF"),
        ], state_lookback=1.0)
        self.assertEqual(row["class"], "B")


class LiveJournalTest(unittest.TestCase):
    """``--journal live`` fetches once, for the window the gaps actually need."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.writes = self.root / "writes.jsonl"
        self.start = at("2026-10-20T18:53:00+00:00")
        self.end = at("2026-10-20T19:02:00+00:00")
        write(self.writes, [(self.start, "observations"), (self.end, "observations")])
        self.text = "\n".join([
            "2026-10-20T17:39:11+00:00 mesh-home tailscaled[1]: " + RUNNING,
            "2026-10-20T18:56:00+00:00 mesh-home tailscaled[1]: "
            "http: TLS handshake error from 100.103.99.16:49984: EOF",
            "2026-10-20T19:05:00+00:00 mesh-home tailscaled[1]: health(warnable=x): ok",
        ]) + "\n"

    def tearDown(self):
        self.tmp.cleanup()

    def test_live_fetches_once_for_the_lookback_window(self):
        calls = []

        class Done:
            returncode = 0
            stdout = self.text
            stderr = ""

        def fake_run(command, **kwargs):
            calls.append((list(command), dict(kwargs)))
            return Done()

        with unittest.mock.patch.object(transport_gap.subprocess, "run", fake_run):
            rows = list(transport_gap.report(self.writes, "live", "redmi10", IP,
                                             min_gap=60.0))
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["class"], "B")
        self.assertEqual(len(calls), 1)
        command, kwargs = calls[0]
        self.assertEqual(command[:6], ["journalctl", "-u", "tailscaled", "-o",
                                       "short-iso", "--since"])
        self.assertEqual(command[6],
                         (self.start - dt.timedelta(seconds=86400)).isoformat())
        self.assertEqual(command[7], "--until")
        self.assertEqual(command[8], (self.end + dt.timedelta(seconds=120)).isoformat())
        self.assertEqual(kwargs["timeout"], 120)

    def test_a_failed_fetch_raises_so_the_caller_reports_unknown(self):
        class Failed:
            returncode = 1
            stdout = ""
            stderr = "no journal access"

        with unittest.mock.patch.object(transport_gap.subprocess, "run",
                                        lambda *a, **k: Failed()):
            with self.assertRaises(OSError):
                list(transport_gap.report(self.writes, "live", "redmi10", IP,
                                          min_gap=60.0))


class StampTest(unittest.TestCase):
    def test_a_short_iso_line_splits_stamp_and_text(self):
        moment, text = transport_gap.parse_stamp(
            "2026-10-20T17:39:11+00:00 mesh-home tailscaled[1]: Switching ipn state "
            "Starting -> Running")
        self.assertEqual(moment.isoformat(), "2026-10-20T17:39:11+00:00")
        self.assertEqual(text, "Switching ipn state Starting -> Running")

    def test_a_line_without_a_stamp_is_not_a_journal_line(self):
        self.assertEqual(transport_gap.parse_stamp("Switching ipn state Running"),
                         (None, "Switching ipn state Running"))

    def test_a_naive_stamp_is_refused_rather_than_read_as_utc(self):
        line = "2026-10-20T17:39:11 mesh-home tailscaled[1]: hi"
        self.assertEqual(transport_gap.parse_stamp(line), (None, line))

    def test_lines_are_returned_oldest_first(self):
        parsed = transport_gap.journal_lines_from_text(
            "2026-10-20T10:00:00+00:00 h tailscaled[1]: second\n"
            "2026-10-20T09:00:00+00:00 h tailscaled[1]: first\n")
        self.assertEqual([text for _moment, text in parsed], ["first", "second"])

    def test_the_newest_span_without_an_end_is_the_state_now(self):
        spans = transport_gap.state_spans(transport_gap.journal_lines_from_text(
            "2026-10-20T17:39:11+00:00 mesh-home tailscaled[1]: " + RUNNING + "\n"))
        self.assertEqual(spans, [(at("2026-10-20T17:39:11+00:00"), None, "Running", "Starting")])


class MainTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.writes = self.root / "writes.jsonl"
        self.journal = self.root / "journal.txt"
        write(self.writes, [(at("2026-10-20T10:00:00+00:00"), "observations"),
                            (at("2026-10-20T10:10:00+00:00"), "observations")])
        journal(self.journal, [
            (at("2026-10-20T09:00:00+00:00"), RUNNING),
            (at("2026-10-20T10:04:00+00:00"),
             "http: TLS handshake error from 100.103.99.16:49984: EOF"),
            (at("2026-10-20T10:15:00+00:00"), "health(warnable=no-derp-connection): ok"),
        ])

    def tearDown(self):
        self.tmp.cleanup()

    def _run(self, *extra):
        return stderr_run([
            "--writes", str(self.writes), "--journal", str(self.journal),
            "--node", "redmi10", "--ip", IP, *extra])

    def test_json_lines_carry_the_class_and_the_counts(self):
        code, out, _err = self._run()
        self.assertEqual(code, 0)
        row = json.loads(out.strip())
        self.assertEqual(row["class"], "B")
        self.assertEqual(row["duration_s"], 600.0)
        self.assertEqual(row["tls_handshake_errors"], 1)
        self.assertEqual(row["start"], "2026-10-20T10:00:00+00:00")
        self.assertEqual(row["end"], "2026-10-20T10:10:00+00:00")

    def test_human_output_names_the_counts(self):
        code, out, _err = self._run("--human")
        self.assertEqual(code, 0)
        self.assertIn("addresses=1", out)
        self.assertIn("tls_eof=1", out)
        self.assertIn("ipn=ipn Running across the gap", out)

    def test_no_gap_prints_the_explanation_and_exits_zero(self):
        write(self.writes, [(at("2026-10-20T10:00:00+00:00"), "observations"),
                            (at("2026-10-20T10:00:10+00:00"), "observations")])
        code, out, _err = self._run("--min-gap", "60")
        self.assertEqual(code, 0)
        self.assertIn("no gap", out)

    def test_a_non_address_is_refused(self):
        code, _out, err = stderr_run(["--writes", str(self.writes),
                                      "--journal", str(self.journal),
                                      "--node", "redmi10", "--ip", "../etc"])
        self.assertEqual(code, 2)
        self.assertIn("not an IPv4 address", err)

    def test_a_non_positive_threshold_is_refused(self):
        code, _out, err = stderr_run(["--writes", str(self.writes),
                                      "--journal", str(self.journal),
                                      "--node", "redmi10", "--ip", IP,
                                      "--min-gap", "0"])
        self.assertEqual(code, 2)
        self.assertIn("refused", err)

    def test_limit_zero_is_refused(self):
        code, _out, err = stderr_run(["--writes", str(self.writes),
                                      "--journal", str(self.journal),
                                      "--node", "redmi10", "--ip", IP,
                                      "--limit", "0"])
        self.assertEqual(code, 2)
        self.assertIn("positive", err)

    def test_an_unreadable_journal_is_unknown_and_exits_two(self):
        code, _out, err = stderr_run(["--writes", str(self.writes),
                                      "--journal", str(self.root / "absent.txt"),
                                      "--node", "redmi10", "--ip", IP])
        self.assertEqual(code, 2)
        self.assertIn("UNKNOWN", err)

    def test_an_unwritable_census_is_unknown_and_exits_two(self):
        code, _out, err = stderr_run(["--writes", str(self.root / "absent.jsonl"),
                                      "--journal", str(self.journal),
                                      "--node", "redmi10", "--ip", IP])
        self.assertEqual(code, 2)
        self.assertIn("UNKNOWN", err)

    def test_undecodable_journal_is_unknown_and_exits_two(self):
        path = self.root / "bad.txt"
        path.write_bytes(b"2026-10-20T18:56:00+00:00 h t[1]: netstack[\xff]\n")
        code, _out, err = stderr_run(["--writes", str(self.writes),
                                      "--journal", str(path),
                                      "--node", "redmi10", "--ip", IP])
        self.assertEqual(code, 2)
        self.assertIn("UNKNOWN", err)

    def test_undecodable_census_is_unknown_and_exits_two(self):
        path = self.root / "bad.jsonl"
        path.write_bytes(b'{"ts":"2026-10-20T10:00:00+00:00","node":"redmi10","\xff}\n')
        code, _out, err = stderr_run(["--writes", str(path),
                                      "--journal", str(self.journal),
                                      "--node", "redmi10", "--ip", IP])
        self.assertEqual(code, 2)
        self.assertIn("UNKNOWN", err)


if __name__ == "__main__":
    unittest.main()
