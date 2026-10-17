"""Deterministic consumer-visible boundaries; no phone or physical requests."""
import json
import tempfile
import time
import unittest
from unittest.mock import MagicMock, patch
from pathlib import Path

import watch


class PerceptionTests(unittest.TestCase):
    def setUp(self):
        # This suite makes no phone or physical request. Unpatched
        # detect_class_c_delivery_gap() calls reach _host_stopped_state(), which
        # runs `adb shell dumpsys package org.androidbody` against the physically
        # connected phone: measured 2026-10-14 at 135 real device round-trips per
        # suite run (bounded-output 133, fires-on-halt 1, no-repeat 1). OSError is
        # the failure mode _host_stopped_state maps to an honest unknown, so the
        # offline verdict is what these tests observe; tests asserting a specific
        # host_stopped outcome patch subprocess.run themselves.
        patcher = patch("subprocess.run",
                        side_effect=OSError("subprocess disabled in unit tests"))
        patcher.start()
        self.addCleanup(patcher.stop)

    def state(self):
        return watch.initial("note3", "http://127.0.0.1:8765/node/note3")

    def page(self, state, lines, received=1000, more=False, log_dir=None):
        body = "".join(f"{state['cursor'] + offset} {line}\n"
                       for offset, line in enumerate(lines, 1)).encode()
        watch.apply_page(state, watch.parse_page(body, state["cursor"]), received,
                         more, log_dir=log_dir)

    def test_sensor_monotonic_time_is_scoped_and_invalid_inputs_are_incomparable(self):
        state = self.state()
        self.page(state, ["1000 hello node=note3 protocol=1 session=s1",
                          "1000 light lux=12.5 accuracy=3 age_ms=21 sensor_time_ns=123456789"])
        node = watch.space_snapshot([state], 1000, 30)["nodes"][0]
        self.assertEqual(node["light"]["sensor_time"],
                         {"sensor_time_ns": 123456789,
                          "scope": ["light", "s1"],
                          "status": "same-sensor-session-only"})
        self.assertEqual(node["light"]["phone_sample_epoch_s"], 1000)
        self.assertEqual(node["light"]["age_ms_at_phone_collection"], 21)

        for field, session in (("sensor_time_ns=01", "s1"),
                               ("sensor_time_ns=-1", "s1"),
                               ("sensor_time_ns=9223372036854775808", "s1"),
                               ("sensor_time_ns=4", None),
                               ("sensor_time_ns=4", "")):
            item = watch.record(3, f"1000 light lux=12.5 accuracy=3 age_ms=21 {field}",
                                1000, False)
            self.assertIsNone(watch.sensor_time_scope(item, session))
        missing = watch.record(3, "1000 light lux=12.5 accuracy=3 age_ms=21", 1000, False)
        self.assertIsNone(watch.sensor_time_scope(missing, "s1"))

        empty_session_state = self.state()
        self.page(empty_session_state, [
            "1000 hello node=note3 protocol=1 session=",
            "1000 light lux=12.5 accuracy=3 age_ms=21 sensor_time_ns=4"])
        light = watch.space_snapshot([empty_session_state], 1000, 30)["nodes"][0]["light"]
        self.assertIsNone(light["sensor_time"])
        self.assertEqual(light["sensor_time_reason"],
                         "missing/invalid timestamp or session; incomparable")


    def test_dead_follower_views_age_without_mutating_checkpoint(self):
        state = self.state()
        self.page(state, ["1000 battery level=0.6 charging=false",
                          "1000 acceleration x=0 y=0 z=9.8 age_ms=0"])
        with tempfile.TemporaryDirectory() as folder:
            directory = Path(folder)
            watch.save(directory / "note3.json", state)
            current = watch.read_views(directory, 1001, 30)
            stale = watch.read_views(directory, 1031, 30)
            compact = watch.read_views(directory, 1031, 30, compact=True)
            self.assertIn("acceleration magnitude=9.800 m/s²", current)
            self.assertIn("stale/phone-silent-or-delayed", stale)
            self.assertIn("unknown/consumer-not-refreshing", compact)
            self.assertNotIn("acceleration magnitude=9.800", stale)
            self.assertEqual(watch.load(directory / "note3.json")["cursor"], 2)

    def test_backlog_is_not_current_and_resume_uses_new_evidence(self):
        state = self.state()
        self.page(state, ["100 acceleration x=1 y=2 z=3 age_ms=1"], more=True)
        self.assertIn("backlog/draining", watch.render(state, 1000, 30))
        self.assertIn("delayed_at_receipt=true", watch.render(state, 1000, 30))
        self.page(state, [], more=False)
        # Node responded to the poll: receipt is recent, node label is fresh.
        # Freshness uses receipt time, so acceleration is fresh (received at 1000).
        # The old phone event time is captured by delayed_at_receipt=true above.
        self.assertIn("fresh-clock-conditional", watch.render(state, 1000, 30))
        self.assertIn("acceleration [fresh-clock-conditional]", watch.render(state, 1000, 30))
        self.page(state, ["1001 battery level=0.5 charging=true",
                          "1001 acceleration x=0 y=0 z=10 age_ms=0"], received=1001)
        self.assertIn("acceleration magnitude=10.000 m/s²", watch.render(state, 1001, 30))

    def test_view_clock_note_is_computed_not_hardcoded(self):
        # Regression: render() must not assert an unmeasured clock-alignment
        # pass. The view uses the same bounded acquisition-span reason as
        # space.json; it never hardcodes "UTC-aligned (<0.2s offset".
        state = self.state()
        self.page(state, ["1000 hello node=note3 protocol=1 session=s1",
                          "1000 light lux=12.5 accuracy=3 age_ms=21"])
        view = watch.render(state, 1000, 30)
        self.assertNotIn("UTC-aligned", view)
        self.assertNotIn("0.2s offset", view)
        self.assertIn("clock skew <=", view)

        empty = self.state()
        self.assertIn("clock agreement is unverified", watch.render(empty, 1000, 30))

    def test_events_receipt_line_carries_its_freshness(self):
        """Regression: the events pane printed the last action receipt as a bare
        raw line, so a receipt days old (collect-only, no fresh delivery) sat
        after fresh event lines with no date and read as current. The receipt
        now carries the view's provenance: phone event time, consumer receipt
        time and the delayed flag.
        """
        state = self.state()
        self.page(state, ["900 action 25 succeeded kind=eval command=env "
                          "identity=2f94ed status=ok truncated=false output=uid=10225"],
                   received=1000)
        events = watch.render_events(state, 1000, 30)
        self.assertIn("receipt: #1 900 action 25 succeeded kind=eval", events)
        self.assertIn("phone_sample/event=1970-01-01T00:15:00+00:00", events)
        self.assertIn("consumer_receipt=1970-01-01T00:16:40+00:00", events)
        self.assertIn("delayed_at_receipt=true", events)

    def test_restart_preserves_cursor_raw_unknowns_and_no_timestamp_wakes(self):
        state = self.state()
        self.page(state, ["1000 battery level=0.5 charging=true future=kept",
                          "1000 light lux=80 accuracy=3 age_ms=0",
                          "1000 alien extra=never-discard opaque-text"])
        self.assertTrue(watch.update_events(state, 1000, 30))
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "note3.json"
            watch.save(path, state)
            restored = watch.load(path, "note3", state["source"])
            self.assertEqual(restored["cursor"], 3)
            self.assertEqual(restored["latest"]["alien"]["raw"],
                             "1000 alien extra=never-discard opaque-text")
            before = watch.render_events(restored, 1000, 30)
            self.page(restored, ["1005 battery level=0.5 charging=true future=kept",
                                 "1005 light lux=80 accuracy=3 age_ms=0"], received=1005)
            self.assertFalse(watch.update_events(restored, 1005, 30))
            self.assertEqual(before, watch.render_events(restored, 1005, 30))
            self.assertIn("future=kept", watch.render(restored, 1005, 30))
            with self.assertRaises(ValueError):
                watch.load(path, "note3", "https://other.example/node/note3")

    def test_capability_absence_and_unknown_do_not_become_zero(self):
        state = self.state()
        self.page(state, ["1000 sensor light absent", "1000 battery level=unknown charging=unknown",
                          "1000 acceleration unavailable reason=no_sample"])
        view = watch.render(state, 1000, 30)
        self.assertIn("light=absent", view)
        self.assertIn("accelerometer=unknown", view)
        self.assertIn("battery [unknown/", view)
        self.assertIn("acceleration magnitude unknown", view)
        watch.update_events(state, 1000, 30)
        self.page(state, ["1001 cap accelerometer"], received=1001)
        self.assertTrue(watch.update_events(state, 1001, 30))


    def test_owner_checkboxes_parse_render_json_and_session_reset(self):
        state = self.state()
        self.page(state, ["1000 hello node=note3 protocol=1 session=s1",
                          "1000 owner_checkboxes battery=on light=off acceleration=on vibration=on"])
        view = watch.render(state, 1000, 30)
        self.assertIn("owner=battery:on,light:off,acceleration:on,vibration:on", view)
        self.assertIn("owner checkboxes: battery=on light=off acceleration=on vibration=on", view)
        node = watch.space_snapshot([state], 1000, 30)["nodes"][0]
        self.assertEqual(node["owner_checkboxes"],
                         {"battery": "on", "light": "off", "acceleration": "on", "vibration": "on"})
        self.page(state, ["1001 hello node=note3 protocol=1 session=s2",
                          "1001 owner_checkboxes battery=on light=on acceleration=on vibration=on"], received=1001)
        self.assertEqual(state["owner_checkboxes"],
                         {"battery": "on", "light": "on", "acceleration": "on", "vibration": "on"})
        view = watch.render(state, 1001, 30)
        self.assertIn("owner=battery:on,light:on,acceleration:on,vibration:on", view)

    def test_owner_checkboxes_change_surfaces_as_event(self):
        state = self.state()
        self.page(state, ["1000 hello node=note3 protocol=1 session=s1",
                          "1000 owner_checkboxes battery=on light=on acceleration=on vibration=on"])
        self.assertTrue(watch.update_events(state, 1000, 30))
        self.assertFalse(watch.update_events(state, 1000, 30))
        self.page(state, ["1001 hello node=note3 protocol=1 session=s2",
                          "1001 owner_checkboxes battery=off light=on acceleration=on vibration=on"], received=1001)
        self.assertTrue(watch.update_events(state, 1001, 30))

    def test_owner_checkboxes_ignore_malformed_values(self):
        state = self.state()
        self.page(state, ["1000 hello node=note3 protocol=1 session=s1",
                          "1000 owner_checkboxes battery=on light=maybe acceleration=off vibration=on extra=1"])
        self.assertEqual(state["owner_checkboxes"],
                         {"battery": "on", "acceleration": "off", "vibration": "on"})
        view = watch.render(state, 1000, 30)
        self.assertIn("owner=battery:on,light:unknown,acceleration:off,vibration:on", view)

    def test_load_migrates_legacy_state_without_owner_checkboxes(self):
        """Legacy persisted state lacks owner_checkboxes; load() must seed it.

        Regression: compact_key/render hard-access state["owner_checkboxes"],
        so a legacy state crashed the follower at startup (KeyError).
        """
        import json
        import tempfile
        from pathlib import Path
        legacy = watch.initial("note3", "http://127.0.0.1:8765/node/note3")
        del legacy["owner_checkboxes"]
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "note3.json"
            path.write_text(json.dumps(legacy), encoding="utf-8")
            state = watch.load(path, node="note3",
                              source="http://127.0.0.1:8765/node/note3")
        self.assertEqual(state["owner_checkboxes"], {})
        key = watch.compact_key(state, 1000, 30)
        self.assertEqual(len(key), 10)
        view = watch.render(state, 1000, 30)
        self.assertIn("owner=battery:unknown,light:unknown,"
                      "acceleration:unknown,vibration:unknown", view)


    def test_light_bucket_transition_keeps_both_fresh_raw_endpoints(self):
        state = self.state()
        self.page(state, ["1000 hello node=note3 protocol=1 session=s1",
                          "1000 light lux=0 accuracy=3 age_ms=0"], received=1000)
        self.assertTrue(watch.update_events(state, 1000, 30))
        self.page(state, ["1005 light lux=20 accuracy=3 age_ms=0"], received=1005)
        self.assertTrue(watch.update_events(state, 1005, 30))
        event = state["events"][-1]
        self.assertIn("measured-light-bucket-transition id=note3:s1:3 note3", event)
        self.assertIn("session=s1 bucket=0->4", event)
        self.assertIn("from=#2 lux=0.0", event)
        self.assertIn("to=#3 lux=20.0", event)
        self.assertIn("phone_sample=1970-01-01T00:16:40+00:00", event)
        self.assertIn("consumer_receipt=1970-01-01T00:16:45+00:00", event)
        self.assertIn("historical-measurement-only", event)
        self.assertEqual(state["last_light_transition"]["event_id"], "note3:s1:3")
        self.assertEqual(state["last_light_transition"]["validity_seconds"], 30)
        self.assertIn(event, watch.render_events(state, 1005, 30))

    def test_light_transition_rejects_backlog_and_does_not_replay_after_drain(self):
        state = self.state()
        self.page(state, ["1000 hello node=note3 protocol=1 session=s1",
                          "1000 light lux=0 accuracy=3 age_ms=0"], received=1000)
        watch.update_events(state, 1000, 30)
        self.page(state, ["1005 light lux=20 accuracy=3 age_ms=0"], received=1005, more=True)
        watch.update_events(state, 1005, 30)
        self.page(state, ["1006 light lux=0 accuracy=3 age_ms=0"], received=1006, more=False)
        watch.update_events(state, 1006, 30)
        self.assertFalse(any("measured-light-bucket-transition" in event
                             for event in state["events"]))
        self.page(state, ["1010 light lux=20 accuracy=3 age_ms=0"], received=1010)
        watch.update_events(state, 1010, 30)
        transitions = [event for event in state["events"]
                       if "measured-light-bucket-transition" in event]
        self.assertEqual(len(transitions), 1)
        self.assertIn("from=#4 lux=0.0", transitions[0])
        self.assertIn("to=#5 lux=20.0", transitions[0])

    def test_light_transition_requires_recent_adjacent_samples_and_seeds_new_session(self):
        state = self.state()
        self.page(state, ["1000 hello node=note3 protocol=1 session=s1",
                          "1000 light lux=0 accuracy=3 age_ms=0"], received=1000)
        watch.update_events(state, 1000, 30)
        self.page(state, ["1035 light lux=20 accuracy=3 age_ms=0"], received=1035)
        watch.update_events(state, 1035, 30)
        self.assertFalse(any("measured-light-bucket-transition" in event
                             for event in state["events"]))
        self.page(state, ["1040 hello node=note3 protocol=1 session=s2",
                          "1040 light lux=20 accuracy=3 age_ms=0"], received=1040)
        watch.update_events(state, 1040, 30)
        self.page(state, ["1045 light lux=0 accuracy=3 age_ms=0"], received=1045)
        self.assertTrue(watch.update_events(state, 1045, 30))
        self.assertIn("session=s2 bucket=4->0", state["events"][-1])
    def test_fresh_null_lux_stays_unknown_emits_no_transition_and_is_not_counted(self):
        # Core light-channel measurement: null-lux blocks (published lux: null,
        # transport reachable) recur on a minutes-scale cadence during live
        # operation. They are not measurements and must never become one.
        state = self.state()
        self.page(state, ["1000 hello node=note3 protocol=1 session=s1",
                          "1000 light lux=0 accuracy=3 age_ms=0",
                          "1001 light lux=0 accuracy=3 age_ms=0"], received=1001)
        watch.update_events(state, 1001, 30)
        self.page(state, ["1002 light lux=null accuracy=3 age_ms=0"], received=1002)
        watch.update_events(state, 1002, 30)
        self.assertFalse(any("measured-light-bucket-transition" in event
                             for event in state["events"]))
        self.assertEqual(watch.sensor_status(state["latest"]["light"], 1002, 30),
                         "unknown/fresh-clock-conditional")
        self.assertEqual(watch.compact_key(state, 1002, 30)[4][1],
                         ["light", "unknown/fresh-clock-conditional", None, None])
        node = watch.space_snapshot([state], 1002, 30)["nodes"][0]
        self.assertEqual(node["light"]["status"], "unknown/fresh-clock-conditional")
        self.assertIsNone(node["light"]["lux"])
        self.assertEqual(watch.stillness_snapshot(state, 1002, 30)["light"]["count"], 2)
        view = watch.render(state, 1002, 30)
        self.assertIn("light [unknown/fresh-clock-conditional]", view)
        self.assertIn("lux=null", view)

    def test_space_snapshot_exposes_fresh_values_and_unknown_unavailable_timestamps(self):
        state = self.state()
        self.page(state, ["1000 hello node=note3 protocol=1 session=s1",
                          "1000 light lux=12.5 accuracy=3 age_ms=21"], received=1000)
        snapshot = watch.space_snapshot([state], 1000, 30)
        node = snapshot["nodes"][0]
        self.assertEqual(snapshot["schema_version"], 1)
        self.assertEqual(snapshot["producer"]["name"], "android-body-perception")
        self.assertEqual(snapshot["producer"]["mode"], "space")
        self.assertEqual((node["source"], node["session"], node["cursor"]),
                         (state["source"], "s1", 2))
        self.assertEqual(node["light"]["status"], "fresh-clock-conditional")
        self.assertEqual(node["light"]["freshness_basis"],
                         "host receipt time; phone event time and age_ms retained for provenance")
        self.assertEqual(node["light"]["lux"], 12.5)
        self.assertEqual(node["light"]["units"], "lux")
        self.assertEqual(node["light"]["sequence"], 2)
        self.assertEqual(node["light"]["phone_sample_utc"], "1970-01-01T00:16:40+00:00")
        self.assertEqual(node["light"]["consumer_receipt_utc"], "1970-01-01T00:16:40+00:00")
        self.assertIsNone(node["light"]["phone_elapsed_realtime_ms"])
        self.assertEqual(node["light"]["phone_elapsed_realtime_reason"],
                         "not provided by protocol v1")
        self.assertIsInstance(node["light"]["host_receipt_monotonic_ns"], int)
        self.assertGreaterEqual(node["light"]["host_receipt_monotonic_ns"], 0)
        boot_id = node["light"]["host_boot_id"]
        self.assertTrue(boot_id is None or
                        watch.re.fullmatch(r"[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}",
                                           boot_id))
        self.assertIsNone(node["light"]["server_receipt_utc"])
        self.assertEqual(node["light"]["server_receipt_utc_reason"],
                         "not provided by protocol v1")
        self.assertEqual(node["light"]["acquisition_span_ms"], 0.0)
        with tempfile.TemporaryDirectory() as folder:
            empty = watch.read_space(Path(folder), 1000, 30)
        self.assertEqual(empty["status"], "unknown/no-perception-state")
        self.assertEqual(empty["producer"]["name"], "android-body-perception")
        self.assertEqual(empty["nodes"], [])
        state["has_more"] = True
        backlog = watch.space_snapshot([state], 1001, 30)["nodes"][0]
        self.assertEqual(backlog["light"]["status"], "backlog/draining")
        self.assertIsNone(backlog["light"]["lux"])
        self.assertTrue(backlog["backlog_page_pending"])
        state["has_more"] = False
        stale = watch.space_snapshot([state], 1031, 30)["nodes"][0]
        self.assertEqual(stale["light"]["status"], "stale")
        self.assertIsNone(stale["light"]["lux"])

    def test_space_snapshot_publishes_the_host_side_node_state_verdict(self):
        """A designed collect-only silence must be nameable, not scored as a fault."""
        state = self.state()
        self.page(state, ["1000 hello node=note3 protocol=1 session=s1",
                          "1000 light lux=12.5 accuracy=3 age_ms=21"], received=1000)
        # No verdict read: unknown, never OFF.
        node = watch.space_snapshot([state], 1000, 30)["nodes"][0]
        self.assertEqual(node["node_state"],
                         {"status": "unknown", "mode": "UNKNOWN", "desired_on": None,
                          "collect_only": None, "observed_at_epoch_s": None,
                          "reason": "no-node-state", "reasons": []})
        verdict = {"status": "ok", "mode": "ON_COLLECT_ONLY", "desired_on": True,
                   "collect_only": True, "observed_at_epoch_s": 999.0, "age_s": 1.0,
                   "reason": None, "reasons": ["collect-only: no HTTP by design"]}
        node = watch.space_snapshot([state], 1000, 30, {"note3": verdict})["nodes"][0]
        # The reader's clock-derived age_s is not republished (see the churn test).
        self.assertEqual(node["node_state"],
                         {key: value for key, value in verdict.items() if key != "age_s"})
        # read_space wires the directory document in without a schema bump:
        # the core consumer rejects schema_version != 1.
        with tempfile.TemporaryDirectory() as folder:
            directory = Path(folder)
            watch.save(directory / "note3.json", state)
            (directory / "node-state-note3.json").write_text(json.dumps(
                {"node": "note3", "mode": "ON_COLLECT_ONLY", "desired_on": True,
                 "collect_only": True, "observed_at_epoch_s": 999.0,
                 "source": "tools/node_state.py", "reasons": []}), encoding="utf-8")
            snapshot = watch.read_space(directory, 1000, 30)
        self.assertEqual(snapshot["schema_version"], 1)
        published = snapshot["nodes"][0]["node_state"]
        self.assertEqual((published["status"], published["mode"],
                          published["collect_only"]), ("ok", "ON_COLLECT_ONLY", True))

    def test_space_snapshot_publishes_the_clock_domain_reading_additively(self):
        """The clock-domain reading is one additive node field; inconsistent values pass through uncoerced."""
        state = self.state()
        self.page(state, ["1000 hello node=note3 protocol=1 session=s1",
                          "1000 light lux=12.5 accuracy=3 age_ms=21"], received=1000)
        # No verdict read: absent, never a verified offset.
        node = watch.space_snapshot([state], 1000, 30)["nodes"][0]
        self.assertEqual(node["clock_domain"],
                         {"version": 1, "status": "absent", "offset_nominal_s": None,
                          "offset_min_s": None, "offset_max_s": None,
                          "observed_at_epoch_s": None, "validity_seconds": None,
                          "samples": 0, "source": None,
                          "reason": "no-clock-domain-reading", "jump": None})
        # A fresh measurement publishes its raw values; nominal outside the bounds
        # is preserved, not coerced. age_s is not republished (churn).
        clock = {"status": "ok", "offset_min_s": 24.202, "offset_max_s": 25.202,
                 "offset_nominal_s": 25.651, "observed_at_epoch_s": 999.0,
                 "age_s": 12.0, "validity_seconds": 3600.0, "samples": 3,
                 "source": "tools/clock_offset.py", "reason": None, "jump": None}
        node = watch.space_snapshot([state], 1000, 30,
                                    clocks={"note3": clock})["nodes"][0]
        self.assertEqual(node["clock_domain"],
                         {"version": 1, "status": "ok",
                          "offset_nominal_s": 25.651,
                          "offset_min_s": 24.202, "offset_max_s": 25.202,
                          "observed_at_epoch_s": 999.0,
                          "validity_seconds": 3600.0, "samples": 3,
                          "source": "tools/clock_offset.py",
                          "reason": None, "jump": None})
        # read_space wires the directory document in without a schema bump:
        with tempfile.TemporaryDirectory() as folder:
            directory = Path(folder) / "body" / "perception"
            directory.mkdir(parents=True)
            watch.save(directory / "note3.json", state)
            (Path(folder) / "body" / "clock-domain-note3.json").write_text(json.dumps(
                {"node": "note3", "status": "ok", "offset_min_s": 24.0,
                 "offset_max_s": 25.0, "offset_nominal_s": 24.5, "samples": 7,
                 "observed_at_epoch_s": 999.0, "validity_seconds": 3600.0,
                 "source": "tools/clock_offset.py", "jump": None}), encoding="utf-8")
            snapshot = watch.read_space(directory, 1000, 30)
        self.assertEqual(snapshot["schema_version"], 1)
        published = snapshot["nodes"][0]["clock_domain"]
        self.assertEqual((published["status"], published["offset_nominal_s"],
                          published["offset_min_s"], published["offset_max_s"],
                          published["samples"], published["source"]),
                         ("ok", 24.5, 24.0, 25.0, 7, "tools/clock_offset.py"))

    def test_space_render_is_stable_within_a_second_so_publish_can_skip_it(self):
        """publish_space rewrites only on change; a clock-derived field would defeat that."""
        state = self.state()
        self.page(state, ["1000 hello node=note3 protocol=1 session=s1",
                          "1000 light lux=12.5 accuracy=3 age_ms=21"], received=1000)
        with tempfile.TemporaryDirectory() as folder:
            directory = Path(folder)
            watch.save(directory / "note3.json", state)
            (directory / "node-state-note3.json").write_text(json.dumps(
                {"node": "note3", "mode": "ON_COLLECT_ONLY", "desired_on": True,
                 "collect_only": True, "observed_at_epoch_s": 999.0,
                 "source": "tools/node_state.py", "reasons": []}), encoding="utf-8")
            first = watch.render_space(directory, 1000.0, 30)
            later = watch.render_space(directory, 1000.3, 30)
        self.assertEqual(first, later)
        self.assertIn('"node_state"', first)
    def test_space_snapshot_light_reason_carries_measured_clock_bound(self):
        state = self.state()
        self.page(state, ["1000 hello node=note3 protocol=1 session=s1",
                          "1000 light lux=12.5 accuracy=3 age_ms=21"], received=1024)
        self.page(state, ["1001 light lux=12.5 accuracy=3 age_ms=21"], received=1026)
        node = watch.space_snapshot([state], 1026, 30)["nodes"][0]["light"]
        self.assertEqual(node["status"], "fresh-clock-conditional")
        self.assertEqual(node["status_reason"],
                         "phone/host clock skew <=24000ms behind host "
                         "(acquisition span 24000-25000ms, n=3 retained); "
                         "skew/latency split unknown")

    def test_space_snapshot_clock_bound_falls_back_to_unverified_without_history(self):
        state = self.state()
        self.page(state, ["1000 hello node=note3 protocol=1 session=s1",
                          "1000 light lux=12.5 accuracy=3 age_ms=21"], received=1000)
        state["history"] = []
        node = watch.space_snapshot([state], 1000, 30)["nodes"][0]["light"]
        self.assertEqual(node["status"], "fresh-clock-conditional")
        self.assertEqual(node["status_reason"],
                         "phone/host clock agreement is unverified")

    def test_space_snapshot_real_age_upper_bound_corrects_clock_skew(self):
        state = self.state()
        self.page(state, ["1000 hello node=note3 protocol=1 session=s1",
                          "1000 light lux=12.5 accuracy=3 age_ms=21"], received=1024)
        self.page(state, ["1001 light lux=12.5 accuracy=3 age_ms=21"], received=1026)
        node = watch.space_snapshot([state], 1026, 30)["nodes"][0]["light"]
        self.assertEqual(node["real_age_upper_bound_ms"], 1000.0)
        self.assertTrue(node["is_fresh_at_host"])

    def test_space_snapshot_real_age_upper_bound_false_when_exceeds_validity(self):
        state = self.state()
        self.page(state, ["1000 hello node=note3 protocol=1 session=s1",
                          "1000 light lux=12.5 accuracy=3 age_ms=21"], received=1024)
        self.page(state, ["1001 light lux=12.5 accuracy=3 age_ms=21"], received=1055)
        node = watch.space_snapshot([state], 1055, 30)["nodes"][0]["light"]
        self.assertEqual(node["real_age_upper_bound_ms"], 30000.0)
        self.assertFalse(node["is_fresh_at_host"])

    def test_space_snapshot_real_age_upper_bound_none_without_history(self):
        state = self.state()
        self.page(state, ["1000 hello node=note3 protocol=1 session=s1",
                          "1000 light lux=12.5 accuracy=3 age_ms=21"], received=1000)
        state["history"] = []
        node = watch.space_snapshot([state], 1000, 30)["nodes"][0]["light"]
        self.assertIsNone(node["real_age_upper_bound_ms"])
        self.assertIsNone(node["is_fresh_at_host"])


    def test_space_snapshot_parses_phone_elapsed_realtime_when_present(self):
        state = self.state()
        self.page(state, ["1000 hello node=note3 protocol=2 session=s1",
                          "1000 light lux=12.5 accuracy=3 age_ms=21 "
                          "phone_elapsed_ms=9223372036854775807"], received=1000)
        node = watch.space_snapshot([state], 1000, 30)["nodes"][0]["light"]
        self.assertEqual(node["phone_elapsed_realtime_ms"], 9223372036854775807)
        self.assertIsNone(node["phone_elapsed_realtime_reason"])
        self.assertEqual(node["acquisition_span_ms"], 0.0)
        for raw, reason in (
                ("1000 light lux=12.5 accuracy=3 age_ms=21 phone_elapsed_ms=abc",
                 "invalid phone_elapsed_ms value"),
                ("1000 light lux=12.5 accuracy=3 age_ms=21 phone_elapsed_ms=-1",
                 "invalid phone_elapsed_ms value"),
                ("1000 light lux=12.5 accuracy=3 age_ms=21 phone_elapsed_ms=01",
                 "invalid phone_elapsed_ms value"),
                ("1000 light lux=12.5 accuracy=3 age_ms=21 "
                 "phone_elapsed_ms=9223372036854775808",
                 "invalid phone_elapsed_ms value"),
                ("1000 light lux=12.5 accuracy=3 age_ms=21 phone_elapsed_ms=",
                 "invalid phone_elapsed_ms value")):
            item = watch.record(5, raw, 1002.5, False)
            self.assertIsNone(watch.phone_elapsed_realtime(item))
            node = watch.space_snapshot(
                [{"latest": {"light": item}, "has_more": False, "node": "note3",
                  "source": state["source"], "session": "s1", "cursor": 5,
                  "capabilities": {}, "poll_at": None, "error": None,
                  "history": [], "actions": [], "event_key": None,
                  "last_light_sequence": None, "last_light_transition": None,
                  "last_light_event_cursor": None, "poll_start_cursor": 0,
                  "ok_at": None}],
                1002.5, 30)["nodes"][0]["light"]
            self.assertIsNone(node["phone_elapsed_realtime_ms"])
            self.assertEqual(node["phone_elapsed_realtime_reason"], reason)
            self.assertEqual(node["acquisition_span_ms"], 2500.0)

    def test_space_snapshot_tolerates_pre_v2_items_without_receipt_metadata(self):
        state = self.state()
        self.page(state, ["1000 hello node=note3 protocol=1 session=s1",
                          "1000 light lux=12.5 accuracy=3 age_ms=21"], received=1000)
        legacy = watch.record(5, "1000 light lux=12.5 accuracy=3 age_ms=21", 1000, False)
        legacy.pop("host_receipt_monotonic_ns")
        legacy.pop("host_boot_id")
        node = watch.space_snapshot(
            [{"latest": {"light": legacy}, "has_more": False, "node": "note3",
              "source": state["source"], "session": "s1", "cursor": 5,
              "capabilities": {}, "poll_at": None, "error": None,
              "history": [], "actions": [], "event_key": None,
              "last_light_sequence": None, "last_light_transition": None,
              "last_light_event_cursor": None, "poll_start_cursor": 0,
              "ok_at": None}],
            1000, 30)["nodes"][0]["light"]
        self.assertIsNone(node["host_receipt_monotonic_ns"])
        self.assertIsNone(node["host_boot_id"])
        self.assertEqual(node["host_boot_id_reason"], "receipt metadata not recorded")
        self.assertEqual(node["phone_elapsed_realtime_reason"],
                         "not provided by protocol v1")
        self.assertEqual(node["acquisition_span_ms"], 0.0)

    def test_old_state_seeds_transition_marker_without_replaying_history(self):
        state = self.state()
        self.page(state, ["1000 hello node=note3 protocol=1 session=s1",
                          "1000 light lux=0 accuracy=3 age_ms=0"], received=1000)
        watch.update_events(state, 1000, 30)
        state.pop("last_light_sequence")
        state.pop("last_light_transition")
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "note3.json"
            watch.save(path, state)
            restored = watch.load(path, "note3", state["source"])
            self.page(restored, ["1005 light lux=20 accuracy=3 age_ms=0"], received=1005)
            watch.update_events(restored, 1005, 30)
            self.assertFalse(any("measured-light-bucket-transition" in event
                                 for event in restored["events"]))
            self.page(restored, ["1010 light lux=0 accuracy=3 age_ms=0"], received=1010)
            watch.update_events(restored, 1010, 30)
            self.assertIn("session=s1 bucket=4->0", restored["events"][-1])

    def test_rollback_cursor_advance_then_reapply_does_not_replay_transitions(self):
        state = self.state()
        self.page(state, ["1000 hello node=note3 protocol=1 session=s1",
                          "1000 light lux=0 accuracy=3 age_ms=0"], received=1000)
        watch.update_events(state, 1000, 30)
        self.page(state, ["1005 light lux=20 accuracy=3 age_ms=0"], received=1005)
        watch.update_events(state, 1005, 30)
        self.assertEqual(state["last_light_transition"]["to"]["sequence"], 3)
        # The old reader advances the shared cursor but does not maintain our event watermark.
        self.page(state, ["1010 light lux=0 accuracy=3 age_ms=0"], received=1010)
        state["event_key"] = watch.compact_key(state, 1010, 30)
        self.page(state, [], received=1011)
        watch.update_events(state, 1011, 30)
        transitions = [event for event in state["events"]
                       if "measured-light-bucket-transition" in event]
        self.assertEqual(len(transitions), 1)
        self.assertIn("to=#3 lux=20.0", transitions[0])
        self.assertEqual(state["last_light_transition"]["to"]["sequence"], 3)

    def test_consecutive_polls_do_not_repeat_transition_while_pair_stays_fresh(self):
        state = self.state()
        self.page(state, ["1000 hello node=note3 protocol=1 session=s1",
                          "1000 light lux=0 accuracy=3 age_ms=0"], received=1000)
        watch.update_events(state, 1000, 30)
        self.page(state, ["1005 light lux=20 accuracy=3 age_ms=0"], received=1005)
        watch.update_events(state, 1005, 30)
        # The 0->20 lux pair is still fresh at this poll; it must not be
        # emitted a second time.
        self.page(state, ["1010 light lux=21 accuracy=3 age_ms=0"], received=1010)
        watch.update_events(state, 1010, 30)
        transitions = [event for event in state["events"]
                       if "measured-light-bucket-transition" in event]
        self.assertEqual(len(transitions), 1)
        self.assertIn("to=#3 lux=20.0", transitions[0])

    def test_space_publication_replaces_fast_node_before_later_node_completes(self):
        fast = self.state()
        slow = watch.initial("redmi10", "http://127.0.0.1:8765/node/redmi10")
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            directory = root / "body" / "perception"
            directory.mkdir(parents=True)
            fast_path = directory / "note3.json"
            slow_path = directory / "redmi10.json"
            watch.save(fast_path, fast)
            watch.save(slow_path, slow)
            nodes = [(fast_path, fast, ""), (slow_path, slow, "")]
            watch.publish_space(directory, nodes, 1000, 30)

            self.page(fast, ["1000 hello node=note3 protocol=1 session=s1",
                             "1000 light lux=20 accuracy=3 age_ms=0"])
            fast.update(poll_at=1000, error="http-502")
            watch.save(fast_path, fast)
            watch.publish_space(directory, nodes, 1000, 30)

            snapshot = watch.read_space(directory, 1000, 30)
            by_node = {node["node"]: node for node in snapshot["nodes"]}
            self.assertEqual(by_node["note3"]["transport"], "offline-or-rejected/http-502")
            self.assertEqual(by_node["note3"]["light"]["status"], "fresh-clock-conditional")
            self.assertEqual(by_node["note3"]["light"]["lux"], 20)
            self.assertEqual(by_node["redmi10"]["phone_status"], "unknown/no-observations")
            self.assertIsNone(by_node["redmi10"]["light"]["lux"])
    def test_stalled_follower_preserves_last_transport_failure(self):
        state = self.state()
        self.page(state, ["1000 battery level=0.5 charging=false"])
        state.update(poll_at=1005, error="http-401")
        self.assertEqual(watch.transport(state, 1010, 30), "offline-or-rejected/http-401")
        self.assertEqual(watch.transport(state, 1040, 30),
                         "unknown/consumer-not-refreshing/last-error=http-401")

    def test_future_clock_and_sensor_age_do_not_license_derived_sense(self):
        state = self.state()
        # Phone event time 1100 (future), consumer receipt 1000.
        # Freshness uses receipt time, so a future phone clock does not
        # produce unknown-clock-future. The data is fresh (received at 1000).
        self.page(state, ["1100 acceleration x=0 y=0 z=10 age_ms=0"])
        self.assertIn("fresh-clock-conditional", watch.render(state, 1000, 30))
        self.assertIn("magnitude=10.000", watch.render(state, 1000, 30))
        # But a large age_ms (phone's own measurement) still prevents magnitude.
        self.page(state, ["1000 acceleration x=0 y=0 z=10 age_ms=60000"])
        self.assertNotIn("magnitude=10.000", watch.render(state, 1000, 30))

    def test_wifi_rssi_projection_separates_api_time_and_unknown_acquisition_age(self):
        state = self.state()
        self.page(state, ["1000 wifi_link_rssi_dbm=-57 source=androidbody_wifi_api "
                          "observed_at=1700000000"], received=1002)
        node = watch.space_snapshot([state], 1003, 30)["nodes"][0]
        rssi = node["wifi_link_rssi"]
        self.assertEqual(rssi["status"], "fresh-clock-conditional")
        self.assertEqual(rssi["rssi_dbm"], -57)
        self.assertEqual(rssi["units"], "dBm")
        self.assertEqual(rssi["protocol_event_time_epoch_s"], 1000)
        self.assertEqual(rssi["consumer_receipt_epoch_s"], 1002)
        self.assertEqual(rssi["observed_at_api_read_time"], "1700000000")
        self.assertIsNone(rssi["acquisition_age"])
        rendered = watch.render(state, 1003, 30)
        self.assertIn("acquisition age=unknown", rendered)

        self.page(state, ["1003 wifi_link_rssi_dbm unavailable "
                          "reason=disconnected source=androidbody_wifi_api "
                          "observed_at=1700000003"], received=1004)
        unavailable = watch.space_snapshot([state], 1005, 30)["nodes"][0]["wifi_link_rssi"]
        self.assertEqual(unavailable["status"], "unavailable/fresh-clock-conditional")
        self.assertIsNone(unavailable["rssi_dbm"])
        self.assertEqual(unavailable["unavailable_reason"], "disconnected")
        self.assertEqual(unavailable["sequence"], 2)

    def test_wifi_disconnection_verdict_carries_its_api_basis_only_when_unavailable(self):
        """A null link verdict is not link-state evidence; a measured RSSI needs no caveat."""
        state = self.state()
        self.page(state, ["1000 wifi_link_rssi_dbm=-57 source=androidbody_wifi_api "
                          "observed_at=1700000000"], received=1002)
        self.assertIn("wifi_link_rssi_dbm=-57", watch.render(state, 1003, 30))
        self.assertNotIn(watch.WIFI_LINK_BASIS, watch.render(state, 1003, 30))
        self.assertNotIn(watch.WIFI_LINK_BASIS, watch.render_events(state, 1003, 30))

        self.page(state, ["1003 wifi_link_rssi_dbm unavailable reason=disconnected "
                          "source=androidbody_wifi_api observed_at=1700000003"], received=1004)
        rendered = watch.render(state, 1005, 30)
        # The phone's own verdict stays verbatim; the basis names what it cannot establish.
        self.assertIn("reason=disconnected source=androidbody_wifi_api", rendered)
        self.assertIn(watch.WIFI_LINK_BASIS, rendered)
        self.assertIn(watch.WIFI_LINK_BASIS, watch.render_events(state, 1005, 30))

        # A stale measured sample is a freshness fact, not an API verdict: no basis line.
        self.page(state, ["1040 wifi_link_rssi_dbm=-57 source=androidbody_wifi_api "
                          "observed_at=1700000040"], received=1042)
        self.assertNotIn(watch.WIFI_LINK_BASIS, watch.render(state, 1100, 30))

    def test_wifi_rssi_capability_is_session_scoped_and_new_session_clears_sample(self):
        state = self.state()
        self.page(state, [
            "1000 hello node=note3 protocol=1 session=s1",
            "1000 cap wifi_link_rssi",
            "1000 wifi_link_rssi_dbm=-57 source=androidbody_wifi_api "
            "observed_at=1700000000",
        ], received=1000)
        node = watch.space_snapshot([state], 1001, 30)["nodes"][0]
        self.assertEqual(node["capabilities"]["wifi_link_rssi"], "present")
        self.assertEqual(node["wifi_link_rssi"]["rssi_dbm"], -57)

        self.page(state, ["1002 hello node=note3 protocol=1 session=s2"], received=1002)
        node = watch.space_snapshot([state], 1003, 30)["nodes"][0]
        self.assertEqual(node["capabilities"]["wifi_link_rssi"], "unknown")
        self.assertEqual(node["wifi_link_rssi"]["status"], "unknown/no-observation")
        self.assertIsNone(node["wifi_link_rssi"]["rssi_dbm"])

    def test_ble_status_projection_preserves_unknown_error_and_session_scope(self):
        state = self.state()
        initial = watch.space_snapshot([state], 1000, 30)["nodes"][0]
        self.assertEqual(initial["bluetooth_le"]["status"], "unknown/no-observation")
        self.page(state, [
            "1000 hello node=note3 protocol=1 session=s1",
            "1000 ble_status source=androidbody_bluetooth_api api=21 "
            "api_surface=platform_sdk feature_ble=present adapter=enabled scanner_api=present "
            "advertiser_api=present scanner_getter=returned advertiser_getter=null "
            "advertiser_supported=unsupported "
            "adapter_error=SecurityException",
        ], received=1001)
        view = watch.space_snapshot([state], 1002, 30)["nodes"][0]["bluetooth_le"]
        self.assertEqual(view["status"], "fresh-clock-conditional")
        self.assertEqual(view["api_surface"], "platform_sdk")
        self.assertEqual(view["adapter"], "enabled")
        self.assertEqual(view["advertiser_supported"], "unsupported")
        self.assertEqual(view["errors"], {"adapter": "SecurityException"})
        self.assertEqual(view["scanner_getter"], "returned")
        self.assertEqual(view["advertiser_getter"], "null")
        self.assertEqual(view["sequence"], 2)
        self.assertNotIn("bluetooth_le", state["capabilities"])

        self.page(state, [
            "1002 ble_status source=androidbody_bluetooth_api api=21 "
            "feature_ble=query_error adapter=error scanner_api=unavailable "
            "advertiser_api=error advertiser_supported=error "
            "feature_ble_error=SecurityException",
        ], received=1003)
        view = watch.space_snapshot([state], 1004, 30)["nodes"][0]["bluetooth_le"]
        self.assertEqual(view["feature_ble"], "query_error")
        self.assertEqual(view["adapter"], "error")
        self.assertEqual(view["errors"], {"feature_ble": "SecurityException"})
        self.assertNotIn("bluetooth_le", state["capabilities"])
        stale = watch.space_snapshot([state], 1034, 30)["nodes"][0]["bluetooth_le"]
        self.assertEqual(stale["status"], "stale")
        self.assertIsNone(stale["feature_ble"])
        self.assertIsNone(stale["adapter"])
        self.assertIsNone(stale["api_surface"])
        self.assertIsNone(stale["scanner_getter"])
        self.assertIsNone(stale["advertiser_getter"])
        self.assertEqual(stale["errors"], {})
        self.page(state, [
            "1004 ble_status source=androidbody_bluetooth_api api=21 "
            "feature_ble=present adapter=enabled scanner_api=present "
            "advertiser_api=present advertiser_supported=supported",
        ], received=1004)
        view = watch.space_snapshot([state], 1005, 30)["nodes"][0]["bluetooth_le"]
        self.assertIsNone(view["api_surface"])

        self.page(state, [
            "1005 ble_status source=androidbody_bluetooth_api api=21 "
            "api_surface=hardware_supported feature_ble=present adapter=enabled "
            "scanner_api=present advertiser_api=present advertiser_supported=supported",
        ], received=1005)
        view = watch.space_snapshot([state], 1006, 30)["nodes"][0]["bluetooth_le"]
        self.assertIsNone(view["api_surface"])

        self.page(state, ["1005 hello node=note3 protocol=1 session=s2"], received=1005)
        view = watch.space_snapshot([state], 1006, 30)["nodes"][0]["bluetooth_le"]
        self.assertEqual(view["status"], "unknown/no-observation")
        self.assertIsNone(view["feature_ble"])

    def test_ble_sighting_projection_carries_sample_and_receipt_epochs(self):
        state = self.state()
        initial = watch.space_snapshot([state], 1000, 30)["nodes"][0]["ble_sighting"]
        self.assertIsNone(initial["phone_sample_epoch_s"])
        self.assertIsNone(initial["consumer_receipt_epoch_s"])
        self.page(state, ["1000 ble_sighting name=MISHE-BEACON rssi=-23"],
                 received=1000)
        view = watch.space_snapshot([state], 1001, 30)["nodes"][0]["ble_sighting"]
        self.assertEqual(view["phone_sample_epoch_s"], 1000)
        self.assertEqual(view["consumer_receipt_epoch_s"], 1000)
        # Stale keeps the raw epochs: cessation age is computed against
        # clock_domain by the consumer, never hidden by the validity verdict.
        stale = watch.space_snapshot([state], 1040, 30)["nodes"][0]["ble_sighting"]
        self.assertEqual(stale["status"], "stale")
        self.assertIsNone(stale["rssi_dbm"])
        self.assertEqual(stale["phone_sample_epoch_s"], 1000)
        self.assertEqual(stale["consumer_receipt_epoch_s"], 1000)

    def test_ble_scan_state_projection_carries_sample_and_receipt_epochs(self):
        state = self.state()
        initial = watch.space_snapshot([state], 1000, 30)["nodes"][0]["ble_scan_state"]
        self.assertIsNone(initial["phone_sample_epoch_s"])
        self.assertIsNone(initial["consumer_receipt_epoch_s"])
        self.page(state, ["1000 ble_scan_state windows=3 phase=gap "
                          "last_error=none sightings=0 window_ms=60000 gap_ms=60000"],
                 received=1000)
        view = watch.space_snapshot([state], 1001, 30)["nodes"][0]["ble_scan_state"]
        self.assertEqual(view["sightings"], 0)
        self.assertEqual(view["phone_sample_epoch_s"], 1000)
        self.assertEqual(view["consumer_receipt_epoch_s"], 1000)
        stale = watch.space_snapshot([state], 1040, 30)["nodes"][0]["ble_scan_state"]
        self.assertEqual(stale["status"], "stale")
        self.assertEqual(stale["phone_sample_epoch_s"], 1000)

    def test_summary_line_shows_sighting_phone_sample_with_observation_only(self):
        state = self.state()
        self.page(state, ["1000 hello node=note3 protocol=1 session=s1",
                          "1000 ble_sighting name=MISHE-BEACON rssi=-23"],
                 received=1000)
        self.assertTrue(watch.update_events(state, 1000, 30))
        self.assertIn("sighting_phone_sample=1970-01-01T00:16:40",
                      state["events"][-1])
        quiet = self.state()
        self.page(quiet, ["1000 hello node=note3 protocol=1 session=s1",
                          "1000 battery level=0.5 charging=true"], received=1000)
        self.assertTrue(watch.update_events(quiet, 1000, 30))
        self.assertFalse(any("sighting_phone_sample=" in event
                             for event in quiet["events"]))

    def test_wifi_rssi_rejects_invalid_sentinels_and_out_of_range_values(self):

        for value in ("0", "1", "-127", "-128", "nan", "inf"):
            with self.subTest(value=value):
                state = self.state()
                self.page(state, [
                    "1000 wifi_link_rssi_dbm=" + value
                    + " source=androidbody_wifi_api observed_at=1700000000"
                ], received=1002)
                item = state["latest"]["wifi_link_rssi_dbm"]
                self.assertEqual(
                    watch.wifi_rssi_status(item, 1003, 30),
                    "unknown/invalid-or-missing-rssi")
                snapshot = watch.wifi_rssi_snapshot(item, 1003, 30)
                self.assertIsNone(snapshot["rssi_dbm"])

    def test_wifi_rssi_compact_events_track_value_freshness_and_unavailable(self):
        state = self.state()
        self.page(state, [
            "1000 wifi_link_rssi_dbm=-57 source=androidbody_wifi_api "
            "observed_at=1700000000",
        ], received=1000)
        self.assertTrue(watch.update_events(state, 1000, 30))
        self.assertIn("wifi_link_rssi=fresh-clock-conditional rssi_dbm=-57",
                      state["events"][-1])

        self.page(state, [
            "1001 wifi_link_rssi_dbm=-63 source=androidbody_wifi_api "
            "observed_at=1700000001",
        ], received=1001)
        self.assertTrue(watch.update_events(state, 1001, 30))
        self.assertIn("rssi_dbm=-63", state["events"][-1])
        count = len(state["events"])
        self.page(state, [
            "1002 wifi_link_rssi_dbm=-63 source=androidbody_wifi_api "
            "observed_at=1700000002",
        ], received=1002)
        self.assertFalse(watch.update_events(state, 1002, 30))
        self.assertEqual(len(state["events"]), count)

        self.assertTrue(watch.update_events(state, 1033, 30))
        self.assertIn("wifi_link_rssi=stale rssi_dbm=None", state["events"][-1])
        self.assertIn("rssi_dbm=None", watch.render_events(state, 1033, 30))

        self.page(state, [
            "1033 wifi_link_rssi_dbm unavailable reason=disconnected "
            "source=androidbody_wifi_api observed_at=1700000033",
        ], received=1033)
        self.assertTrue(watch.update_events(state, 1033, 30))
        self.assertIn("wifi_link_rssi=unavailable/fresh-clock-conditional "
                      "rssi_dbm=None reason=disconnected", state["events"][-1])
        count = len(state["events"])
        self.page(state, [
            "1034 wifi_link_rssi_dbm unavailable reason=permission_denied "
            "source=androidbody_wifi_api observed_at=1700000034",
        ], received=1034)
        self.assertTrue(watch.update_events(state, 1034, 30))
        self.assertEqual(len(state["events"]), count + 1)
        self.assertIn("wifi_link_rssi=unavailable/fresh-clock-conditional "
                      "rssi_dbm=None reason=permission_denied",
                      state["events"][-1])

    def test_stale_rows_carry_age_ms_that_localizes_the_sensor_silence(self):
        """A stale row's age_ms is the phone-side age of its last real event.

        Body-research wake 51003: the retained stale row carried only
        reason=stale, so now - received measured poll/receipt latency (~20 s),
        not the sensor silence (observed 2 h 47 m). age_ms makes the silence
        measurable consumer-side: last-event epoch = collected - age_ms/1000.
        """
        state = self.state()
        self.page(state, [
            "1000 hello node=note3 protocol=1 session=s1",
            "1000 acceleration unavailable reason=stale age_ms=101234",
            "1000 light unavailable reason=stale age_ms=55000",
        ], received=1000)
        accel = state["latest"]["acceleration"]
        light = state["latest"]["light"]
        self.assertEqual(accel["fields"].get("age_ms"), "101234")
        self.assertEqual(light["fields"].get("age_ms"), "55000")
        # The extra token must not change the unavailable status or its
        # receipt-based freshness: the feed keeps advancing while stale.
        self.assertEqual(
            watch.sensor_status(accel, 1030, 30),
            "unavailable/fresh-clock-conditional")
        self.assertEqual(
            watch.sensor_status(light, 1030, 30),
            "unavailable/fresh-clock-conditional")
        # The silence is now derivable: accel last event ~101 s before
        # collection, light ~55 s — two distinct per-channel gaps.
        self.assertEqual(accel["collected"] - 101234 // 1000, 899)
        self.assertEqual(light["collected"] - 55000 // 1000, 945)
        view = watch.space_snapshot([state], 1030, 30)["nodes"][0]
        self.assertEqual(view["light"]["age_ms_at_phone_collection"], 55000)

    def test_ble_compact_events_track_status_errors_freshness_not_timestamps(self):
        state = self.state()
        self.page(state, [
            "1000 ble_status source=androidbody_bluetooth_api api=21 "
            "api_surface=platform_sdk feature_ble=present adapter=enabled "
            "scanner_api=present advertiser_api=present advertiser_supported=supported",
        ], received=1000)
        self.assertTrue(watch.update_events(state, 1000, 30))
        self.assertIn("bluetooth_le=fresh-clock-conditional", state["events"][-1])
        self.assertIn("adapter=enabled", state["events"][-1])
        self.assertIn("bluetooth_le fresh-clock-conditional",
                      watch.render_events(state, 1000, 30))

        self.page(state, [
            "1001 ble_status source=androidbody_bluetooth_api api=21 "
            "api_surface=platform_sdk feature_ble=present adapter=enabled "
            "scanner_api=present advertiser_api=present advertiser_supported=supported",
        ], received=1001)
        count = len(state["events"])
        self.assertFalse(watch.update_events(state, 1001, 30))
        self.assertEqual(len(state["events"]), count)

        self.page(state, [
            "1002 ble_status source=androidbody_bluetooth_api api=21 "
            "api_surface=platform_sdk feature_ble=present adapter=disabled "
            "scanner_api=present advertiser_api=present advertiser_supported=supported",
        ], received=1002)
        self.assertTrue(watch.update_events(state, 1002, 30))
        self.assertIn("adapter=disabled", state["events"][-1])

        self.page(state, [
            "1003 ble_status source=androidbody_bluetooth_api api=21 "
            "api_surface=platform_sdk feature_ble=query_error adapter=error "
            "feature_ble_error=SecurityException",
        ], received=1003)
        self.assertTrue(watch.update_events(state, 1003, 30))
        self.assertIn("feature=query_error", state["events"][-1])
        self.assertIn("'feature_ble': 'SecurityException'", state["events"][-1])

        self.assertTrue(watch.update_events(state, 1034, 30))
        self.assertIn("bluetooth_le=stale", state["events"][-1])


    def test_ble_compact_key_tracks_provenance_support_and_stale_recovery(self):
        state = self.state()
        base = (
            "api=21 api_surface=platform_sdk feature_ble=present "
            "adapter=enabled scanner_api=present advertiser_api=present "
            "scanner_getter=returned advertiser_getter=unavailable "
            "advertiser_supported=supported")

        def add(sequence, details, received):
            self.page(state, [
                f"{sequence} ble_status source=androidbody_bluetooth_api "
                f"{details}",
            ], received=received)

        add(1000, base, 1000)
        self.assertTrue(watch.update_events(state, 1000, 30))
        for index, (old, new) in enumerate((
                ("api=21", "api=22"),
                ("scanner_api=present", "scanner_api=error"),
                ("advertiser_api=present", "advertiser_api=error"),
                ("advertiser_supported=supported", "advertiser_supported=unsupported"),
                ("scanner_getter=returned", "scanner_getter=null"))):
            details = base.replace(old, new)
            add(1001 + index, details, 1001 + index)
            self.assertTrue(watch.update_events(state, 1001 + index, 30))
        self.assertIn("scanner_getter=null", state["events"][-1])
        self.assertIn("api=22", state["events"][1])
        count = len(state["events"])
        errors = ("scanner_api_error=SecurityException "
                  "adapter_error=IllegalStateException")
        add(1005, base + " " + errors, 1005)
        self.assertTrue(watch.update_events(state, 1005, 30))
        add(1006, base + " adapter_error=IllegalStateException "
            "scanner_api_error=SecurityException", 1006)
        self.assertFalse(watch.update_events(state, 1006, 30))
        key = watch.compact_key(state, 1006, 30)[7]
        self.assertEqual(key[-1], [("adapter", "IllegalStateException"),
                                   ("scanner_api", "SecurityException")])
        self.assertEqual(len(state["events"]), count + 1)
        self.assertTrue(watch.update_events(state, 1037, 30))
        add(1037, base, 1037)
        self.assertTrue(watch.update_events(state, 1037, 30))
        self.assertIn("bluetooth_le=fresh-clock-conditional", state["events"][-1])





    def test_invalid_page_cannot_advance_checkpoint(self):
        state = self.state()
        with self.assertRaises(ValueError):
            self.page(state, ["1000 battery level=0.5", "bad\tcontrol"])
        self.assertEqual(state["cursor"], 0)
        self.assertEqual(state["history"], [])

    def test_node_status_hysteresis_requires_enter_and_exit_margins(self):
        stale = 30
        state = self.state()
        self.page(state, ["1000 battery level=0.5 charging=true"], received=1000)
        # No persisted label yet: raw status.
        self.assertEqual(watch.node_status(state, 1020, stale), "fresh-clock-conditional")
        state["node_status"] = "fresh-clock-conditional"
        # Age 40 crosses the 30s threshold but not the 45s enter margin: damped fresh.
        self.assertEqual(watch.node_status(state, 1040, stale), "fresh-clock-conditional")
        # Sensor-level freshness is undamped.
        self.assertEqual(watch.sensor_status(state["latest"]["battery"], 1040, stale), "stale")
        # Age 46 exceeds the enter margin: node label flips.
        self.assertEqual(watch.node_status(state, 1046, stale), "stale/phone-silent-or-delayed")
        state["node_status"] = "stale/phone-silent-or-delayed"
        # Age 30 recovery is not below the 20s exit margin: stays stale.
        self.assertEqual(watch.node_status(state, 1030, stale), "stale/phone-silent-or-delayed")
        # Age 19 is below the exit margin: returns fresh.
        self.assertEqual(watch.node_status(state, 1019, stale), "fresh-clock-conditional")

    def test_node_status_hysteresis_passes_through_anomalies_and_unknown_label(self):
        state = self.state()
        self.page(state, ["1000 battery level=0.5 charging=true"], received=1000)
        # Phone clock ahead of the consumer: anomaly stays visible.
        self.assertEqual(watch.node_status(state, 990, 30), "unknown-clock-future")
        state["node_status"] = "fresh-clock-conditional"
        self.assertEqual(watch.node_status(state, 990, 30), "unknown-clock-future")
        # A non-steady persisted label returns the threshold status without hysteresis.
        state["node_status"] = "unknown/no-observations"
        self.assertEqual(watch.node_status(state, 1040, 30), "stale/phone-silent-or-delayed")

    def test_node_status_hysteresis_survives_state_round_trip(self):
        stale = 30
        state = self.state()
        self.page(state, ["1000 battery level=0.5 charging=true"], received=1000)
        state["node_status"] = "stale/phone-silent-or-delayed"
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "note3.json"
            watch.save(path, state)
            loaded = watch.load(path, "note3", "http://127.0.0.1:8765/node/note3")
        self.assertEqual(loaded["node_status"], "stale/phone-silent-or-delayed")
        self.assertEqual(watch.node_status(loaded, 1030, stale), "stale/phone-silent-or-delayed")
        self.assertEqual(watch.node_status(loaded, 1019, stale), "fresh-clock-conditional")

    def test_node_status_hysteresis_keeps_flap_out_of_compact_key(self):
        state = self.state()
        self.page(state, ["1000 battery level=0.5 charging=true"], received=1000)
        state["node_status"] = "fresh-clock-conditional"
        # The damped node label stays fresh at age 40 while the battery
        # sensor evidence honestly reports stale.
        key = watch.compact_key(state, 1040, 30)
        self.assertEqual(key[0], "fresh-clock-conditional")
        self.assertEqual(key[4][0][1], "stale")

    def test_node_status_uses_receipt_time_not_phone_event_time(self):
        """Clock skew and transport lag must not pin the node label stale.

        The phone clock is ~24s behind the host. Freshness uses the consumer
        receipt time (not phone event time), so age is 0s regardless of skew.
        The node label uses the same receipt-time basis: liveness is the
        consumer's observation of when it last heard from the node.
        """
        stale = 30
        state = self.state()
        # Phone event time 976, consumer receipt 1000: 24s clock skew + lag.
        self.page(state, ["976 battery level=0.5 charging=true"], received=1000)
        # Freshness uses receipt time: 1000-1000=0 < 30, fresh.
        self.assertEqual(watch.sensor_status(state["latest"]["battery"], 1000, stale),
                         "fresh-clock-conditional")
        # Simulate the stuck stale label from prior skew-limited hysteresis.
        state["node_status"] = "stale/phone-silent-or-delayed"
        # One second after receipt: receipt-age is 1s, below the 20s exit margin.
        self.assertEqual(watch.node_status(state, 1001, stale), "fresh-clock-conditional")

    def test_freshness_uses_receipt_time_not_phone_collection_time(self):
        """Regression: phone clock ~27.5s behind host must not consume freshness budget.

        Discovered 2026-10-13 (DM 61787): phone clock is ~27.5s behind host
        (constant offset, stdev 0.7s). freshness() previously used
        now - collected (host-minus-phone), so 27.5s skew consumed 92% of
        the 30s budget, leaving ~2.5s for jitter. This froze composite
        stillness and blocked light transitions (milestone-5 blockers).

        Fix: freshness() uses now - received (host receipt time), so clock
        skew does not affect freshness. Age measures transport + processing
        only (~0.7s actual latency).
        """
        stale = 30
        state = self.state()
        # Phone event time 965, consumer receipt 1000: 35s clock skew.
        # With old code: age = 1000 - 965 = 35 > 30 → stale (BUG).
        # With fix: age = 1000 - 1000 = 0 < 30 → fresh-clock-conditional.
        self.page(state, ["965 battery level=0.5 charging=true"], received=1000)
        self.assertEqual(watch.sensor_status(state["latest"]["battery"], 1000, stale),
                         "fresh-clock-conditional")
        # Also verify wifi_rssi_status uses the same receipt-time basis.
        self.page(state, ["965 wifi_link_rssi_dbm=-57 source=androidbody_wifi_api"],
                 received=1000)
        self.assertEqual(watch.wifi_rssi_status(state["latest"]["wifi_link_rssi_dbm"], 1000, stale),
                         "fresh-clock-conditional")

    def test_render_uses_stored_node_status_not_render_time_recompute(self):
        """Render-time now can be 20-30s after poll due to slow multi-node polling.

        The follower computes node_status at poll time (age ~0 → fresh), but
        render recomputes with render-time now. When render-time age exceeds
        the enter margin, the recompute returns stale even though the poll was
        recent. The fix: render uses the stored node_status.
        """
        stale = 30
        state = self.state()
        self.page(state, ["1000 battery level=0.5 charging=true"], received=1000)
        # Follower computes node_status at poll time (age ~0 → fresh).
        state["node_status"] = "fresh-clock-conditional"
        # Render-time now is 50s after poll: age=50 exceeds enter margin
        # (stale + ENTER_MARGIN = 45), so recompute returns stale.
        self.assertEqual(watch.node_status(state, 1050, stale), "stale/phone-silent-or-delayed")
        # But render uses the stored value, not the recompute.
        rendered = watch.render(state, 1050, stale)
        self.assertIn("phone=fresh-clock-conditional", rendered)
        # space_snapshot likewise uses the stored value.
        node = watch.space_snapshot([state], 1050, stale)["nodes"][0]
        self.assertEqual(node["phone_status"], "fresh-clock-conditional")

    def test_render_falls_back_to_compute_when_no_stored_node_status(self):
        """When node_status is not yet stored (initial state), render computes it."""
        stale = 30
        state = self.state()
        self.page(state, ["1000 battery level=0.5 charging=true"], received=1000)
        # No stored node_status: render computes with render-time now.
        self.assertNotIn("node_status", state)
        rendered = watch.render(state, 1001, stale)
        self.assertIn("phone=fresh-clock-conditional", rendered)
        rendered_stale = watch.render(state, 1040, stale)
        self.assertIn("phone=stale/phone-silent-or-delayed", rendered_stale)

    def test_stillness_reports_frozen_when_sensors_stale(self):
        """During a freeze, pre-frozen samples roll through the history window.
        Computing std over them would report a misleading still/moving verdict.
        Instead, return unknown/frozen when the most recent sample for any
        required sensor type is stale."""
        state = self.state()
        # Fresh samples at t=1000: light varies, accel varies, wifi varies.
        self.page(state, [
            "1000 light lux=1.0 accuracy=3 age_ms=10",
            "1000 acceleration x=0 y=0 z=9.8 age_ms=10",
            "1000 wifi_link_rssi_dbm=-10 source=androidbody_wifi_api observed_at=1000",
            "1001 light lux=2.0 accuracy=3 age_ms=10",
            "1001 acceleration x=0 y=0 z=9.9 age_ms=10",
            "1001 wifi_link_rssi_dbm=-20 source=androidbody_wifi_api observed_at=1001",
            "1002 light lux=3.0 accuracy=3 age_ms=10",
            "1002 acceleration x=0 y=0 z=10.0 age_ms=10",
            "1002 wifi_link_rssi_dbm=-30 source=androidbody_wifi_api observed_at=1002",
        ], received=1002)
        # Fresh: should compute normally (moving, since light_std > 0.1).
        result = watch.stillness_snapshot(state, 1002, 30)
        self.assertEqual(result["status"], "moving")
        self.assertIsNotNone(result["accel"])
        self.assertIsNotNone(result["light"])
        self.assertIsNotNone(result["wifi_rssi"])

        # Simulate freeze: same samples, but now is 1002+60 (well past stale=30).
        frozen = watch.stillness_snapshot(state, 1062, 30)
        self.assertEqual(frozen["status"], "unknown/frozen")
        self.assertIsNone(frozen["accel"])
        self.assertIsNone(frozen["light"])
        self.assertIsNone(frozen["wifi_rssi"])
        self.assertIn("acceleration", frozen["stale_sensors"])
        self.assertIn("light", frozen["stale_sensors"])
        self.assertIn("wifi_link_rssi_dbm", frozen["stale_sensors"])

        # After freeze clears (new fresh samples), stillness computes again.
        self.page(state, [
            "1062 light lux=1.0 accuracy=3 age_ms=10",
            "1062 acceleration x=0 y=0 z=9.8 age_ms=10",
            "1062 wifi_link_rssi_dbm=-10 source=androidbody_wifi_api observed_at=1062",
            "1063 light lux=1.1 accuracy=3 age_ms=10",
            "1063 acceleration x=0 y=0 z=9.8 age_ms=10",
            "1063 wifi_link_rssi_dbm=-11 source=androidbody_wifi_api observed_at=1063",
        ], received=1063)
        recovered = watch.stillness_snapshot(state, 1063, 30)
        self.assertNotEqual(recovered["status"], "unknown/frozen")

    def test_stillness_names_an_unavailable_required_input(self):
        """An observed input with no usable value is not a sample-count shortfall.

        Redmi10's Wi-Fi link read is ``unavailable reason=disconnected`` on every
        row while the phone is on mobile data. Accel and light carry plenty of
        values, so ``unknown/insufficient-samples`` named the wrong cause and a
        consumer would wait for RSSI samples that cannot arrive.
        """
        state = self.state()
        self.page(state, [
            "1000 light lux=1.0 accuracy=3 age_ms=10",
            "1000 acceleration x=0 y=0 z=9.8 age_ms=10",
            "1000 wifi_link_rssi_dbm unavailable reason=disconnected source=androidbody_wifi_api observed_at=1000",
            "1001 light lux=1.1 accuracy=3 age_ms=10",
            "1001 acceleration x=0 y=0 z=9.8 age_ms=10",
            "1001 wifi_link_rssi_dbm unavailable reason=disconnected source=androidbody_wifi_api observed_at=1001",
        ], received=1001)
        result = watch.stillness_snapshot(state, 1001, 30)
        self.assertEqual(result["status"], "unknown/no-available-input")
        self.assertEqual(result["unavailable_inputs"], ["wifi_link_rssi_dbm"])
        self.assertEqual(result["missing_inputs"], [])
        self.assertEqual(result["accel"]["count"], 2)
        self.assertEqual(result["light"]["count"], 2)
        self.assertIsNone(result["wifi_rssi"])
        view = watch.render(state, 1001, 30)
        self.assertIn("status=unknown/no-available-input", view)
        self.assertIn("unavailable_inputs=wifi_link_rssi_dbm", view)

    def test_stillness_names_a_missing_required_input(self):
        """An input absent from the window is missing, not undersampled."""
        state = self.state()
        self.page(state, [
            "1000 light lux=1.0 accuracy=3 age_ms=10",
            "1000 acceleration x=0 y=0 z=9.8 age_ms=10",
            "1001 light lux=1.1 accuracy=3 age_ms=10",
            "1001 acceleration x=0 y=0 z=9.8 age_ms=10",
        ], received=1001)
        result = watch.stillness_snapshot(state, 1001, 30)
        self.assertEqual(result["status"], "unknown/no-available-input")
        self.assertEqual(result["missing_inputs"], ["wifi_link_rssi_dbm"])
        self.assertEqual(result["unavailable_inputs"], [])
        self.assertIn("missing_inputs=wifi_link_rssi_dbm",
                      watch.render(state, 1001, 30))

    def test_stillness_insufficient_samples_is_reserved_for_short_value_lists(self):
        """Every input carries a value; there are just too few of them."""
        state = self.state()
        self.page(state, [
            "1000 light lux=1.0 accuracy=3 age_ms=10",
            "1000 acceleration x=0 y=0 z=9.8 age_ms=10",
            "1000 wifi_link_rssi_dbm=-10 source=androidbody_wifi_api observed_at=1000",
        ], received=1000)
        result = watch.stillness_snapshot(state, 1000, 30)
        self.assertEqual(result["status"], "unknown/insufficient-samples")
        self.assertNotIn("missing_inputs", result)
        self.assertNotIn("unavailable_inputs", result)

    def test_stillness_gates_on_the_most_recent_observation_not_the_window(self):
        """A window value that predates a link loss cannot authorize a verdict about now.

        An older usable RSSI sample is still in the window when the link drops,
        so a window-scoped availability test would let the composite report a
        current verdict from a value taken before the disconnection.
        """
        state = self.state()
        self.page(state, [
            "1000 light lux=1.0 accuracy=3 age_ms=10",
            "1000 acceleration x=0 y=0 z=9.8 age_ms=10",
            "1000 wifi_link_rssi_dbm=-40 source=androidbody_wifi_api observed_at=1000",
            "1001 light lux=1.1 accuracy=3 age_ms=10",
            "1001 acceleration x=0 y=0 z=9.8 age_ms=10",
            "1001 wifi_link_rssi_dbm unavailable reason=disconnected source=androidbody_wifi_api observed_at=1001",
        ], received=1001)
        result = watch.stillness_snapshot(state, 1001, 30)
        self.assertEqual(result["status"], "unknown/no-available-input")
        self.assertEqual(result["unavailable_inputs"], ["wifi_link_rssi_dbm"])

    def test_stillness_frozen_still_names_a_missing_input(self):
        """The freeze verdict is the strongest statement, but it is not the only fact."""
        state = self.state()
        self.page(state, [
            "1000 light lux=1.0 accuracy=3 age_ms=10",
            "1000 acceleration x=0 y=0 z=9.8 age_ms=10",
        ], received=1000)
        result = watch.stillness_snapshot(state, 1060, 30)
        self.assertEqual(result["status"], "unknown/frozen")
        self.assertEqual(result["stale_sensors"], ["acceleration", "light"])
        self.assertEqual(result["missing_inputs"], ["wifi_link_rssi_dbm"])
        self.assertEqual(result["unavailable_inputs"], [])

    def test_stillness_names_a_light_row_without_lux_as_unavailable(self):
        state = self.state()
        self.page(state, [
            "1000 light lux=1.0 accuracy=3 age_ms=10",
            "1000 acceleration x=0 y=0 z=9.8 age_ms=10",
            "1000 wifi_link_rssi_dbm=-10 source=androidbody_wifi_api observed_at=1000",
            "1001 light lux=null accuracy=3 age_ms=10",
            "1001 acceleration x=0 y=0 z=9.8 age_ms=10",
            "1001 wifi_link_rssi_dbm=-11 source=androidbody_wifi_api observed_at=1001",
        ], received=1001)
        result = watch.stillness_snapshot(state, 1001, 30)
        self.assertEqual(result["status"], "unknown/no-available-input")
        self.assertEqual(result["unavailable_inputs"], ["light"])
        self.assertEqual(result["missing_inputs"], [])

    def test_ble_sighting_and_scan_lifecycle_are_readable_evidence_without_presence_claim(self):
        state = self.state()
        self.page(state, ["1000 hello node=note3 protocol=1 session=s1",
                          "1000 ble_scan start beacon=MISHE-BEACON window_ms=60000 gap_ms=60000",
                          "1000 ble_sighting name=MISHE-BEACON rssi=-62"], received=1000)
        view = watch.render(state, 1000, 30)
        self.assertIn("#2 1000 ble_scan start beacon=MISHE-BEACON window_ms=60000 gap_ms=60000", view)
        self.assertIn("#3 1000 ble_sighting name=MISHE-BEACON rssi=-62", view)
        self.assertIn("sightings_in_delivered_history=1", view)
        self.assertIn("scan_lifecycle status=fresh-clock-conditional latest=start", view)
        self.assertIn("NOT presence, occupancy or proximity proof", view)
        node = watch.space_snapshot([state], 1000, 30)["nodes"][0]
        self.assertEqual(node["ble_sighting"]["status"], "fresh-clock-conditional")
        self.assertEqual(node["ble_sighting"]["rssi_dbm"], -62.0)
        self.assertEqual(node["ble_sighting"]["name"], "MISHE-BEACON")
        self.assertEqual(node["ble_scan"]["subtype"], "start")
        self.assertEqual(node["ble_scan"]["beacon"], "MISHE-BEACON")
        self.assertEqual(node["ble_scan"]["window_ms"], 60000.0)
        self.assertEqual(node["ble_scan"]["gap_ms"], 60000.0)
        self.assertTrue(watch.update_events(state, 1000, 30))
        events = watch.render_events(state, 1000, 30)
        self.assertIn("ble_sighting fresh-clock-conditional name=MISHE-BEACON rssi_dbm=-62.0 "
                      "scan=fresh-clock-conditional/start reason=unspecified", events)

    def test_ble_scan_unavailable_lifecycle_is_reported_as_latest_event(self):
        state = self.state()
        self.page(state, ["1000 hello node=note3 protocol=1 session=s1",
                          "1000 ble_scan unavailable reason=adapter_off"], received=1000)
        view = watch.render(state, 1000, 30)
        self.assertIn("scan_lifecycle status=fresh-clock-conditional latest=unavailable "
                      "reason=adapter_off", view)
        node = watch.space_snapshot([state], 1000, 30)["nodes"][0]
        self.assertEqual(node["ble_scan"]["subtype"], "unavailable")
        self.assertEqual(node["ble_scan"]["reason"], "adapter_off")
        self.assertIsNone(node["ble_scan"]["beacon"])

    def test_ble_scan_consecutive_error_count_surfaces_in_snapshot(self):
        state = self.state()
        self.page(state, ["1000 hello node=note3 protocol=1 session=s1",
                          "1000 ble_scan error reason=scan_failed code=2",
                          "1001 ble_scan error reason=scan_failed code=2",
                          "1002 ble_scan error reason=scan_failed code=2"], received=1002)
        node = watch.space_snapshot([state], 1002, 30)["nodes"][0]
        self.assertEqual(node["ble_scan"]["consecutive_errors"], 3)
        view = watch.render(state, 1002, 30)
        self.assertIn("consecutive_errors=3", view)

    def test_ble_scan_consecutive_error_count_resets_on_non_error(self):
        state = self.state()
        self.page(state, ["1000 hello node=note3 protocol=1 session=s1",
                          "1000 ble_scan error reason=scan_failed code=2",
                          "1001 ble_scan error reason=scan_failed code=2",
                          "1002 ble_scan start beacon=MISHE-BEACON window_ms=60000 gap_ms=60000"],
             received=1002)
        node = watch.space_snapshot([state], 1002, 30)["nodes"][0]
        self.assertEqual(node["ble_scan"]["consecutive_errors"], 0)
        view = watch.render(state, 1002, 30)
        self.assertNotIn("consecutive_errors=", view)

    def test_ble_scan_consecutive_error_count_not_in_compact_key(self):
        state = self.state()
        self.page(state, ["1000 hello node=note3 protocol=1 session=s1",
                          "1000 ble_scan error reason=scan_failed code=2"], received=1000)
        watch.update_events(state, 1000, 30)
        key1 = watch.compact_key(state, 1000, 30)
        self.page(state, ["1001 ble_scan error reason=scan_failed code=2"], received=1001)
        key2 = watch.compact_key(state, 1001, 30)
        self.assertEqual(key1, key2)
        self.assertFalse(watch.update_events(state, 1001, 30))

    def test_ble_scan_consecutive_error_count_survives_history_eviction(self):
        state = self.state()
        self.page(state, ["1000 hello node=note3 protocol=1 session=s1",
                          "1000 ble_scan error reason=scan_failed code=2"], received=1000)
        # Sensor-dominated traffic evicts the sparse ble_scan item from the
        # 32-item history long before the next scan-cycle error arrives.
        epoch = 1000
        for _ in range(40):
            self.page(state, [f"{epoch} light lux=1.0 accuracy=3",
                              f"{epoch + 1} battery level=1.0 charging=true"],
                      received=4000)
            epoch += 2
        self.assertFalse(any(item["kind"] == "ble_scan" for item in state["history"]))
        node = watch.space_snapshot([state], 4100, 30)["nodes"][0]
        self.assertEqual(node["ble_scan"]["consecutive_errors"], 1)
        self.page(state, ["5000 ble_scan error reason=scan_failed code=2"], received=5000)
        node = watch.space_snapshot([state], 5000, 30)["nodes"][0]
        self.assertEqual(node["ble_scan"]["consecutive_errors"], 2)
        view = watch.render(state, 5000, 30)
        self.assertIn("consecutive_errors=2", view)

    def test_ble_scan_consecutive_error_count_resets_on_session_change(self):
        state = self.state()
        self.page(state, ["1000 hello node=note3 protocol=1 session=s1",
                          "1000 ble_scan error reason=scan_failed code=2",
                          "1001 ble_scan error reason=scan_failed code=2"], received=1001)
        node = watch.space_snapshot([state], 1001, 30)["nodes"][0]
        self.assertEqual(node["ble_scan"]["consecutive_errors"], 2)
        self.page(state, ["1002 hello node=note3 protocol=1 session=s2",
                          "1003 ble_scan error reason=scan_failed code=2"], received=1003)
        node = watch.space_snapshot([state], 1003, 30)["nodes"][0]
        self.assertEqual(node["ble_scan"]["consecutive_errors"], 1)
        view = watch.render(state, 1003, 30)
        self.assertIn("consecutive_errors=1", view)

    def test_ble_rf_channels_stay_honest_unknown_without_observations(self):
        state = self.state()
        self.page(state, ["1000 hello node=note3 protocol=1 session=s1"], received=1000)
        view = watch.render(state, 1000, 30)
        self.assertIn("status=unknown/no-observation", view)
        self.assertIn("sightings_in_delivered_history=0", view)
        self.assertIn("scan_lifecycle status=unknown/no-observation latest=unknown "
                      "reason=unspecified", view)
        node = watch.space_snapshot([state], 1000, 30)["nodes"][0]
        self.assertEqual(node["ble_sighting"]["status"], "unknown/no-observation")
        self.assertIsNone(node["ble_sighting"]["rssi_dbm"])
        self.assertEqual(node["ble_scan"]["status"], "unknown/no-observation")
        self.assertIsNone(node["ble_scan"]["subtype"])

    def test_sighting_window_caveat_follows_the_node_state_not_the_node(self):
        # The freeze cause is a node-state fact. A delivering node (redmi10 is
        # ON, not collect-only) must not be told its delivered envelope is
        # frozen by collect-only, nor be pointed at a spool-side count it may
        # not have; an unknown node state earns neither caveat.
        state = self.state()
        self.page(state, ["1000 hello node=note3 protocol=1 session=s1"], received=1000)

        def node_state(status, mode, collect):
            return {"status": status, "mode": mode, "desired_on": True,
                    "collect_only": collect, "observed_at_epoch_s": 1000,
                    "age_s": 0.0, "reason": None, "reasons": []}

        collecting = node_state("ok", "ON_COLLECT_ONLY", True)
        view = watch.render(state, 1000, 30, node_state=collecting)
        self.assertIn("sightings_in_delivered_history=0 (delivered-envelope window; "
                      "collect-only freezes this", view)

        unknown_state = node_state("stale", "UNKNOWN", None)
        for other in (node_state("ok", "ON", False), unknown_state, None):
            view = watch.render(state, 1000, 30, node_state=other)
            self.assertIn("sightings_in_delivered_history=0 (delivered-envelope window; "
                          "not a rate or duration)", view)
            self.assertNotIn("collect-only freezes this", view)

    def test_ble_scan_state_surfaces_quantitative_loop_state_everywhere(self):
        # Discover 83319: the per-session scan status must be quantitative and
        # co-retained with the five per-cycle kinds, not a coarse flag.
        state = self.state()
        self.page(state, ["1000 hello node=note3 protocol=1 session=s1",
                          "1000 ble_scan_state windows=3 phase=window last_error=none "
                          "sightings=12 window_ms=60000 gap_ms=60000"], received=1000)
        view = watch.render(state, 1000, 30)
        self.assertIn("scan_state windows=3 phase=window last_error=none sightings=12 "
                      "(window_ms=60000 gap_ms=60000)", view)
        self.assertTrue(watch.update_events(state, 1000, 30))
        events = watch.render_events(state, 1000, 30)
        self.assertIn("scan_state=fresh-clock-conditional windows=3 phase=window "
                      "last_error=none sightings=12", events)
        node = watch.space_snapshot([state], 1000, 30)["nodes"][0]
        self.assertEqual(node["ble_scan_state"]["windows"], 3)
        self.assertEqual(node["ble_scan_state"]["phase"], "window")
        self.assertEqual(node["ble_scan_state"]["last_error"], "none")
        self.assertEqual(node["ble_scan_state"]["sightings"], 12)
        self.assertEqual(node["ble_scan_state"]["window_ms"], 60000)
        self.assertEqual(node["ble_scan_state"]["gap_ms"], 60000)

    def test_ble_scan_state_persists_spaced_error_reason_across_cycles(self):
        # last_error may contain a space (scan_failed code=2); it must survive
        # parsing intact, not truncate at the whitespace split.
        state = self.state()
        self.page(state, ["1000 hello node=note3 protocol=1 session=s1",
                          "1000 ble_scan_state windows=27 phase=window "
                          "last_error=scan_failed code=2 sightings=5 "
                          "window_ms=60000 gap_ms=60000"], received=1000)
        node = watch.space_snapshot([state], 1000, 30)["nodes"][0]
        self.assertEqual(node["ble_scan_state"]["last_error"], "scan_failed code=2")
        self.assertEqual(node["ble_scan_state"]["windows"], 27)
        view = watch.render(state, 1000, 30)
        self.assertIn("last_error=scan_failed code=2 sightings=5", view)

    def test_ble_scan_state_absent_is_unknown_not_a_calm_zero(self):
        # The deployed publisher predates the field; absence must not read as
        # "loop healthy" or "loop dead" — it is simply not observed.
        state = self.state()
        self.page(state, ["1000 hello node=note3 protocol=1 session=s1"], received=1000)
        view = watch.render(state, 1000, 30)
        self.assertTrue(watch.update_events(state, 1000, 30))
        events = watch.render_events(state, 1000, 30)
        self.assertIn("scan_state=unknown/no-observation", events)
        node = watch.space_snapshot([state], 1000, 30)["nodes"][0]
        self.assertEqual(node["ble_scan_state"]["status"], "unknown/no-observation")
        self.assertIsNone(node["ble_scan_state"]["windows"])
        self.assertIsNone(node["ble_scan_state"]["phase"])
        self.assertIsNone(node["ble_scan_state"]["last_error"])
        self.assertIsNone(node["ble_scan_state"]["sightings"])

    def test_ble_scan_state_stale_drops_fields_and_emits_no_event(self):
        # A stale cycle row is historical evidence: fields drop to None. The
        # fresh->stale flip itself changes the view, so it emits once and is
        # then stable.
        state = self.state()
        self.page(state, ["1000 hello node=note3 protocol=1 session=s1",
                          "1000 ble_scan_state windows=3 phase=gap last_error=none "
                          "sightings=1 window_ms=60000 gap_ms=60000"], received=1000)
        self.assertTrue(watch.update_events(state, 1000, 30))
        self.assertFalse(watch.update_events(state, 1000, 30))
        node = watch.space_snapshot([state], 1031, 30)["nodes"][0]
        self.assertEqual(node["ble_scan_state"]["status"], "stale")
        self.assertIsNone(node["ble_scan_state"]["windows"])
        self.assertIsNone(node["ble_scan_state"]["sightings"])
        view = watch.render(state, 1031, 30)
        self.assertIn("scan_state stale", view)
        self.assertTrue(watch.update_events(state, 1031, 30))
        events = watch.render_events(state, 1031, 30)
        self.assertIn("scan_state=stale", events)
        self.assertFalse(watch.update_events(state, 1031, 30))

    def test_ble_scan_state_change_is_an_evidence_event(self):
        # windows/phase advancing is new evidence; identical rows are churn.
        state = self.state()
        self.page(state, ["1000 hello node=note3 protocol=1 session=s1",
                          "1000 ble_scan_state windows=3 phase=gap last_error=none "
                          "sightings=1 window_ms=60000 gap_ms=60000"], received=1000)
        self.assertTrue(watch.update_events(state, 1000, 30))
        self.page(state, ["1001 ble_scan_state windows=3 phase=gap last_error=none "
                          "sightings=1 window_ms=60000 gap_ms=60000"], received=1001)
        self.assertFalse(watch.update_events(state, 1001, 30))
        self.page(state, ["1002 ble_scan_state windows=4 phase=window last_error=none "
                          "sightings=1 window_ms=60000 gap_ms=60000"], received=1002)
        self.assertTrue(watch.update_events(state, 1002, 30))
        events = watch.render_events(state, 1002, 30)
        self.assertIn("scan_state windows=4 phase=window last_error=none sightings=1",
                      events)

    def test_stale_ble_sighting_drops_measured_values_and_new_sighting_is_evidence_change(self):
        state = self.state()
        self.page(state, ["1000 hello node=note3 protocol=1 session=s1",
                          "1000 ble_sighting name=MISHE-BEACON rssi=-62"], received=1000)
        node = watch.space_snapshot([state], 1031, 30)["nodes"][0]
        self.assertEqual(node["ble_sighting"]["status"], "stale")
        self.assertIsNone(node["ble_sighting"]["rssi_dbm"])
        self.page(state, ["1031 ble_sighting name=MISHE-BEACON rssi=-58"], received=1031)
        self.assertTrue(watch.update_events(state, 1031, 30))
        self.assertIn("rssi_dbm=-58.0", watch.render_events(state, 1031, 30))
    def excursion_log(self, folder):
        log_dir = Path(folder) / "body" / "perception"
        log_dir.mkdir(parents=True, exist_ok=True)
        return log_dir

    def test_excursion_log_emits_bounded_window_when_next_session_finalizes(self):
        state = self.state()
        with tempfile.TemporaryDirectory() as folder:
            log_dir = self.excursion_log(folder)
            self.page(state, ["1000 hello node=note3 protocol=1 session=s1",
                              "1000 light lux=12.5 accuracy=3 age_ms=21 phone_elapsed_ms=5000",
                              "1000 light lux=40 accuracy=3 age_ms=21 phone_elapsed_ms=8000",
                              "1000 light lux=20 accuracy=3 age_ms=21 phone_elapsed_ms=6000"],
                      received=1000, log_dir=log_dir)
            self.assertFalse((log_dir / "excursion-log-note3.txt").exists())
            self.page(state, ["1000 hello node=note3 protocol=1 session=s2"],
                      received=1001, log_dir=log_dir)
            lines = (log_dir / "excursion-log-note3.txt").read_text().splitlines()
            self.assertEqual(len(lines), 1)
            self.assertIn("session=s1", lines[0])
            self.assertIn("cursor_start=1 cursor_end=4", lines[0])
            self.assertIn("sequence_start=1 sequence_end=4", lines[0])
            self.assertIn("retained_count=4", lines[0])
            self.assertIn("window_truncated=false", lines[0])
            self.assertIn("phone_elapsed_ms=5000,8000", lines[0])
            self.assertIn("phone_window_reason=null", lines[0])
            self.assertIn("acquisition_span_ms=0.0,0.0", lines[0])
            self.assertIn("freeze_overlap=false", lines[0])
            self.assertIn("freeze_class=null freeze_sequence=null", lines[0])
            # The live session has no line until a later hello finalizes it.
            self.page(state, ["1000 light lux=30 accuracy=3 age_ms=21 phone_elapsed_ms=9000"],
                      received=1002, log_dir=log_dir)
            self.assertEqual(
                len((log_dir / "excursion-log-note3.txt").read_text().splitlines()), 1)
            self.page(state, ["1000 hello node=note3 protocol=1 session=s3"],
                      received=1003, log_dir=log_dir)
            lines = (log_dir / "excursion-log-note3.txt").read_text().splitlines()
            self.assertEqual(len(lines), 2)
            self.assertIn("session=s2", lines[1])
            self.assertIn("phone_elapsed_ms=9000,9000", lines[1])
            self.assertIn("acquisition_span_ms=1000.0,2000.0", lines[1])

    def test_excursion_log_marks_truncation_and_window_covers_retained_tail(self):
        state = self.state()
        with tempfile.TemporaryDirectory() as folder:
            log_dir = self.excursion_log(folder)
            lines = ["1000 hello node=note3 protocol=1 session=s1"]
            lines += [f"1000 light lux=10 accuracy=3 age_ms=0 phone_elapsed_ms={1000 + i * 100}"
                      for i in range(35)]
            self.page(state, lines, received=1000, log_dir=log_dir)
            self.page(state, ["1000 hello node=note3 protocol=1 session=s2"],
                      received=1001, log_dir=log_dir)
            line = (log_dir / "excursion-log-note3.txt").read_text().splitlines()[0]
            self.assertIn("retained_count=32", line)
            self.assertIn("window_truncated=true", line)
            self.assertIn("sequence_start=5 sequence_end=36", line)
            self.assertIn("phone_elapsed_ms=1300,4400", line)

    def test_excursion_log_v1_session_emits_null_window_with_reason(self):
        state = self.state()
        with tempfile.TemporaryDirectory() as folder:
            log_dir = self.excursion_log(folder)
            self.page(state, ["1000 hello node=note3 protocol=1 session=s1",
                              "1000 light lux=12.5 accuracy=3 age_ms=21"],
                      received=1000, log_dir=log_dir)
            self.page(state, ["1000 hello node=note3 protocol=1 session=s2"],
                      received=1001, log_dir=log_dir)
            line = (log_dir / "excursion-log-note3.txt").read_text().splitlines()[0]
            self.assertIn("phone_elapsed_ms=null", line)
            self.assertIn("phone_window_reason=no phone_elapsed_ms in retained window", line)
            self.assertIn("window_truncated=false", line)

    def test_excursion_log_empty_session_emits_null_reason(self):
        state = self.state()
        with tempfile.TemporaryDirectory() as folder:
            log_dir = self.excursion_log(folder)
            self.page(state, ["1000 hello node=note3 protocol=1 session=s1"],
                      received=1000, log_dir=log_dir)
            self.page(state, ["1000 hello node=note3 protocol=1 session=s2"],
                      received=1001, log_dir=log_dir)
            line = (log_dir / "excursion-log-note3.txt").read_text().splitlines()[0]
            self.assertIn("retained_count=1", line)
            self.assertIn("cursor_start=1 cursor_end=1", line)
            self.assertIn("phone_elapsed_ms=null", line)
            self.assertIn("phone_window_reason=no phone_elapsed_ms in retained window", line)

    def test_excursion_log_flags_documented_freeze_onset_inside_window(self):
        state = self.state()
        with tempfile.TemporaryDirectory() as folder:
            log_dir = self.excursion_log(folder)
            freeze_dir = Path(folder) / "discovery"
            freeze_dir.mkdir(parents=True, exist_ok=True)
            (freeze_dir / "space-light-freeze.json").write_text(json.dumps(
                {"class": "light-stream-freeze", "cursor": 3, "sequence": 3,
                 "session": "s1", "onset_epoch_s": 1000.5}), encoding="utf-8")
            self.page(state, ["1000 hello node=note3 protocol=1 session=s1",
                              "1000 light lux=12.5 accuracy=3 age_ms=0 phone_elapsed_ms=5000",
                              "1000 light lux=40 accuracy=3 age_ms=0 phone_elapsed_ms=8000"],
                      received=1000, log_dir=log_dir)
            self.page(state, ["1000 hello node=note3 protocol=1 session=s2"],
                      received=1001, log_dir=log_dir)
            line = (log_dir / "excursion-log-note3.txt").read_text().splitlines()[0]
            self.assertIn("freeze_overlap=true", line)
            self.assertIn("freeze_class=light-stream-freeze", line)
            self.assertIn("freeze_sequence=3", line)

    def test_excursion_log_ignores_freeze_onset_outside_window(self):
        state = self.state()
        with tempfile.TemporaryDirectory() as folder:
            log_dir = self.excursion_log(folder)
            freeze_dir = Path(folder) / "discovery"
            freeze_dir.mkdir(parents=True, exist_ok=True)
            (freeze_dir / "space-light-freeze.json").write_text(json.dumps([
                {"class": "light-stream-frozen", "sequence": 999, "session": "s1"},
                {"class": "light-stream-frozen", "sequence": 2, "session": "other"},
            ]), encoding="utf-8")
            self.page(state, ["1000 hello node=note3 protocol=1 session=s1",
                              "1000 light lux=12.5 accuracy=3 age_ms=0 phone_elapsed_ms=5000",
                              "1000 light lux=40 accuracy=3 age_ms=0 phone_elapsed_ms=8000"],
                      received=1000, log_dir=log_dir)
            self.page(state, ["1000 hello node=note3 protocol=1 session=s2"],
                      received=1001, log_dir=log_dir)
            line = (log_dir / "excursion-log-note3.txt").read_text().splitlines()[0]
            self.assertIn("freeze_overlap=false", line)
            self.assertIn("freeze_class=null freeze_sequence=null", line)

    def test_excursion_log_seeds_counter_for_states_without_session_records(self):
        state = self.state()
        with tempfile.TemporaryDirectory() as folder:
            log_dir = self.excursion_log(folder)
            self.page(state, ["1000 hello node=note3 protocol=1 session=s1"],
                      received=1000, log_dir=log_dir)
            del state["session_records"]  # simulate a pre-excursion persisted state
            lines = [f"1000 light lux=10 accuracy=3 age_ms=0 phone_elapsed_ms={2000 + i * 100}"
                     for i in range(33)]
            self.page(state, lines, received=1001, log_dir=log_dir)
            self.page(state, ["1000 hello node=note3 protocol=1 session=s2"],
                      received=1002, log_dir=log_dir)
            line = (log_dir / "excursion-log-note3.txt").read_text().splitlines()[0]
            # 1 hello + 33 lights = 34 records; the seeded counter (1) plus the
            # 33 new records exceeds HISTORY, so bounds cover the retained tail.
            self.assertIn("retained_count=32", line)
            self.assertIn("window_truncated=true", line)
            self.assertIn("phone_elapsed_ms=2100,5200", line)

    def test_excursion_log_is_bounded_to_the_last_lines(self):
        state = self.state()
        with tempfile.TemporaryDirectory() as folder:
            log_dir = self.excursion_log(folder)
            for index in range(1, 131):
                self.page(state, [f"1000 hello node=note3 protocol=1 session=s{index}"],
                          received=1000 + index, log_dir=log_dir)
            lines = (log_dir / "excursion-log-note3.txt").read_text().splitlines()
            self.assertEqual(len(lines), 128)
            self.assertTrue(any(" session=s2 " in line for line in lines))
            self.assertFalse(any(" session=s1 " in line for line in lines))



    def test_excursion_log_retains_windowed_std_oscillation_and_transient(self):
        state = self.state()
        with tempfile.TemporaryDirectory() as folder:
            log_dir = self.excursion_log(folder)
            self.page(state, ["1000 hello node=note3 protocol=1 session=s1",
                              "1000 light lux=0 accuracy=3 age_ms=0 phone_elapsed_ms=1000",
                              "1000 light lux=1 accuracy=3 age_ms=0 phone_elapsed_ms=2000",
                              "1000 light lux=0 accuracy=3 age_ms=0 phone_elapsed_ms=3000",
                              "1000 acceleration x=0 y=0 z=9.8 age_ms=0 phone_elapsed_ms=3100",
                              "1000 acceleration x=0 y=0 z=9.8 age_ms=0 phone_elapsed_ms=3200",
                              "1000 wifi_link_rssi_dbm=-50 age_ms=0 phone_elapsed_ms=3300",
                              "1000 wifi_link_rssi_dbm=-52 age_ms=0 phone_elapsed_ms=3400",
                              "1000 wifi_link_rssi_dbm=-54 age_ms=0 phone_elapsed_ms=3500"],
                      received=1000, log_dir=log_dir)
            self.page(state, ["1000 hello node=note3 protocol=1 session=s2"],
                      received=1001, log_dir=log_dir)
            line = (log_dir / "excursion-log-note3.txt").read_text().splitlines()[0]
            # Population std of [0, 1, 0]; [9.8, 9.8]; [-50, -52, -54].
            self.assertIn("light_std=0.471", line)
            self.assertIn("light_oscillation=0->1->0", line)
            self.assertIn("accel_std=0.0", line)
            self.assertIn("rssi_std=1.633", line)
            self.assertIn("light_transient=revert", line)

    def test_excursion_log_retention_nulls_and_none_without_evidence(self):
        state = self.state()
        with tempfile.TemporaryDirectory() as folder:
            log_dir = self.excursion_log(folder)
            self.page(state, ["1000 hello node=note3 protocol=1 session=s1",
                              "1000 light lux=12.5 accuracy=3 age_ms=0 phone_elapsed_ms=1000"],
                      received=1000, log_dir=log_dir)
            self.page(state, ["1000 hello node=note3 protocol=1 session=s2"],
                      received=1001, log_dir=log_dir)
            line = (log_dir / "excursion-log-note3.txt").read_text().splitlines()[0]
            self.assertIn("light_std=null", line)
            self.assertIn("light_oscillation=none", line)
            self.assertIn("accel_std=null", line)
            self.assertIn("rssi_std=null", line)
            self.assertIn("light_transient=none", line)

    def test_excursion_log_marks_open_transient_and_quantized_signature(self):
        state = self.state()
        with tempfile.TemporaryDirectory() as folder:
            log_dir = self.excursion_log(folder)
            self.page(state, ["1000 hello node=note3 protocol=1 session=s1",
                              "1000 light lux=0 accuracy=3 age_ms=0 phone_elapsed_ms=1000",
                              "1000 light lux=1 accuracy=3 age_ms=0 phone_elapsed_ms=2000",
                              "1000 light lux=2 accuracy=3 age_ms=0 phone_elapsed_ms=3000"],
                      received=1000, log_dir=log_dir)
            self.page(state, ["1000 hello node=note3 protocol=1 session=s2"],
                      received=1001, log_dir=log_dir)
            first = (log_dir / "excursion-log-note3.txt").read_text().splitlines()[0]
            self.assertIn("light_oscillation=0->1", first)
            self.assertIn("light_transient=open", first)
            self.page(state, ["1000 hello node=note3 protocol=1 session=s3",
                              "1000 light lux=0 accuracy=3 age_ms=0 phone_elapsed_ms=4000",
                              "1000 light lux=0 accuracy=3 age_ms=0 phone_elapsed_ms=5000",
                              "1000 light lux=0 accuracy=3 age_ms=0 phone_elapsed_ms=6000"],
                      received=1002, log_dir=log_dir)
            self.page(state, ["1000 hello node=note3 protocol=1 session=s4"],
                      received=1003, log_dir=log_dir)
            # lines[1] is s2's own hello-only line; s3's window is lines[2].
            second = (log_dir / "excursion-log-note3.txt").read_text().splitlines()[2]
            self.assertIn("light_oscillation=quantized", second)
            self.assertIn("light_transient=none", second)

    def test_excursion_log_retention_survives_a_stale_window_verdict(self):
        state = self.state()
        with tempfile.TemporaryDirectory() as folder:
            log_dir = self.excursion_log(folder)
            self.page(state, ["1000 hello node=note3 protocol=1 session=s1",
                              "1000 light lux=0 accuracy=3 age_ms=0 phone_elapsed_ms=1000",
                              "1000 light lux=1 accuracy=3 age_ms=0 phone_elapsed_ms=2000",
                              "1000 light lux=0 accuracy=3 age_ms=0 phone_elapsed_ms=3000"],
                      received=1000, log_dir=log_dir)
            # Far past the stale horizon: the live composite refuses a verdict,
            # but retention evidence is still emitted at the session boundary.
            self.assertEqual(
                watch.stillness_snapshot(state, 1000 + 60, 30)["status"],
                "unknown/frozen")
            self.page(state, ["1000 hello node=note3 protocol=1 session=s2"],
                      received=1061, log_dir=log_dir)
            line = (log_dir / "excursion-log-note3.txt").read_text().splitlines()[0]
            self.assertIn("light_std=0.471", line)
            self.assertIn("light_oscillation=0->1->0", line)
            self.assertIn("light_transient=revert", line)

    def test_accel_guard_ok_for_healthy_rest_with_varying_axes(self):
        state = self.state()
        lines = ["1000 hello node=note3 protocol=1 session=s1"]
        lines += [f"1000 acceleration x={0.01 * i:.3f} y={-0.02 * i:.3f} "
                  f"z={9.80 + 0.01 * i:.3f} age_ms=0 phone_elapsed_ms={1000 + i}"
                  for i in range(6)]
        self.page(state, lines)
        guard = watch.accel_guard(state["history"])
        self.assertEqual(guard["status"], "ok")
        self.assertEqual(guard["samples"], 6)
        self.assertEqual(guard["pinned_axes"], [])
        self.assertFalse(guard["indeterminate"])

    def test_accel_guard_flags_pinned_axis_as_indeterminate(self):
        state = self.state()
        lines = ["1000 hello node=note3 protocol=1 session=s1"]
        lines += [f"1000 acceleration x=-19.6133 y={0.01 * i:.3f} "
                  f"z={9.80 + 0.01 * i:.3f} age_ms=0 phone_elapsed_ms={1000 + i}"
                  for i in range(6)]
        self.page(state, lines)
        guard = watch.accel_guard(state["history"])
        self.assertEqual(guard["status"], "pinned-axis")
        self.assertEqual(guard["pinned_axes"], ["x"])
        self.assertTrue(guard["indeterminate"])

    def test_accel_guard_flags_stable_implausible_magnitude(self):
        state = self.state()
        lines = ["1000 hello node=note3 protocol=1 session=s1"]
        lines += [f"1000 acceleration x={0.001 * i:.4f} y={-0.001 * i:.4f} "
                  f"z={15.70 + 0.002 * i:.4f} age_ms=0 phone_elapsed_ms={1000 + i}"
                  for i in range(6)]
        self.page(state, lines)
        guard = watch.accel_guard(state["history"])
        self.assertEqual(guard["status"], "implausible-magnitude")
        self.assertLess(guard["magnitude_std"], watch.ACCEL_GUARD_MAGNITUDE_STABILITY)
        self.assertTrue(guard["indeterminate"])

    def test_accel_guard_reports_few_samples_below_minimum(self):
        state = self.state()
        self.page(state, ["1000 hello node=note3 protocol=1 session=s1",
                          "1000 acceleration x=0.1 y=0.2 z=9.8 age_ms=0 phone_elapsed_ms=1000"])
        guard = watch.accel_guard(state["history"])
        self.assertEqual(guard["status"], "few-samples")
        self.assertEqual(guard["samples"], 1)
        self.assertTrue(guard["indeterminate"])

    def test_excursion_log_carries_accel_guard_evidence(self):
        state = self.state()
        with tempfile.TemporaryDirectory() as folder:
            log_dir = self.excursion_log(folder)
            lines = ["1000 hello node=note3 protocol=1 session=s1"]
            lines += [f"1000 acceleration x={0.01 * i:.3f} y={-0.02 * i:.3f} "
                      f"z={9.80 + 0.01 * i:.3f} age_ms=0 phone_elapsed_ms={1000 + i}"
                      for i in range(6)]
            self.page(state, lines, received=1000, log_dir=log_dir)
            self.page(state, ["1000 hello node=note3 protocol=1 session=s2"],
                      received=1001, log_dir=log_dir)
            line = (log_dir / "excursion-log-note3.txt").read_text().splitlines()[0]
            self.assertIn("accel_guard=ok accel_samples=6 accel_pinned_axes=null", line)

    def test_excursion_log_flags_indeterminate_accel_guard(self):
        state = self.state()
        with tempfile.TemporaryDirectory() as folder:
            log_dir = self.excursion_log(folder)
            lines = ["1000 hello node=note3 protocol=1 session=s1"]
            lines += [f"1000 acceleration x=-19.6133 y={0.01 * i:.3f} "
                      f"z={9.80 + 0.01 * i:.3f} age_ms=0 phone_elapsed_ms={1000 + i}"
                      for i in range(6)]
            self.page(state, lines, received=1000, log_dir=log_dir)
            self.page(state, ["1000 hello node=note3 protocol=1 session=s2"],
                      received=1001, log_dir=log_dir)
            line = (log_dir / "excursion-log-note3.txt").read_text().splitlines()[0]
            self.assertIn("accel_guard=pinned-axis", line)
            self.assertIn("accel_pinned_axes=x", line)

    def test_view_names_accel_guard_and_flags_indeterminate_leg(self):
        state = self.state()
        lines = ["1000 hello node=note3 protocol=1 session=s1"]
        lines += [f"1000 acceleration x={0.01 * i:.3f} y={-0.02 * i:.3f} "
                  f"z={9.80 + 0.01 * i:.3f} age_ms=0 phone_elapsed_ms={1000 + i}"
                  for i in range(6)]
        self.page(state, lines, received=1000)
        text = watch.render(state, 1000, 30)
        self.assertIn("Accel guard (retained window; calibration-free, baseline-step-immune):", text)
        self.assertIn("status=ok samples=6 pinned_axes=null", text)
        self.assertNotIn("accel leg indeterminate", text)

        pinned = self.state()
        pinned_lines = ["1000 hello node=note3 protocol=1 session=s1"]
        pinned_lines += [f"1000 acceleration x=-19.6133 y={0.01 * i:.3f} "
                         f"z={9.80 + 0.01 * i:.3f} age_ms=0 phone_elapsed_ms={1000 + i}"
                         for i in range(6)]
        self.page(pinned, pinned_lines, received=1000)
        pinned_text = watch.render(pinned, 1000, 30)
        self.assertIn("status=pinned-axis samples=6 pinned_axes=x", pinned_text)
        self.assertIn("accel leg indeterminate", pinned_text)

    def test_class_b_delivery_gap_detector_fires_on_cursor_freeze_with_null_lux(self):
        state = self.state()
        with tempfile.TemporaryDirectory() as folder:
            log_dir = Path(folder)
            # Session s1: two null-lux reads
            self.page(state, ["1000 hello node=note3 protocol=1 session=s1",
                              "1000 light lux=0 accuracy=3 age_ms=0 phone_elapsed_ms=1000",
                              "1000 light lux=0 accuracy=3 age_ms=0 phone_elapsed_ms=2000"],
                      received=1000, log_dir=log_dir)
            # First call seeds prev state
            watch.detect_class_b_delivery_gap(state, log_dir)
            # Simulate cursor frozen for > CLASS_B_FREEZE_SECONDS
            state["_class_b_last_cursor_advance_at"] = time.time() - watch.CLASS_B_FREEZE_SECONDS - 1
            # Second poll: cursor frozen, still null-lux
            detection = watch.detect_class_b_delivery_gap(state, log_dir)
            self.assertIsNotNone(detection)
            self.assertEqual(detection["trigger"], "cursor-freeze")
            self.assertEqual(detection["null_lux_consecutive"], 2)
            self.assertEqual(detection["cursor"], state["cursor"])

    def test_class_b_delivery_gap_detector_fires_on_session_change_with_null_lux(self):
        state = self.state()
        with tempfile.TemporaryDirectory() as folder:
            log_dir = Path(folder)
            # Session s1 with null-lux
            self.page(state, ["1000 hello node=note3 protocol=1 session=s1",
                              "1000 light lux=0 accuracy=3 age_ms=0 phone_elapsed_ms=1000"],
                      received=1000, log_dir=log_dir)
            watch.detect_class_b_delivery_gap(state, log_dir)
            # Session s2 with null-lux (session change)
            # Session s2 with 2 null-lux reads (session change)
            self.page(state, ["1000 hello node=note3 protocol=1 session=s2",
                              "1000 light lux=0 accuracy=3 age_ms=0 phone_elapsed_ms=2000",
                              "1000 light lux=0 accuracy=3 age_ms=0 phone_elapsed_ms=3000"],
                      received=1001, log_dir=log_dir)
            detection = watch.detect_class_b_delivery_gap(state, log_dir)
            self.assertIsNotNone(detection)
            self.assertEqual(detection["trigger"], "session-change")
            self.assertEqual(detection["null_lux_consecutive"], 2)

    def test_class_b_delivery_gap_detector_silent_without_null_lux(self):
        state = self.state()
        with tempfile.TemporaryDirectory() as folder:
            log_dir = Path(folder)
            # Session s1: non-null-lux
            self.page(state, ["1000 hello node=note3 protocol=1 session=s1",
                              "1000 light lux=12.5 accuracy=3 age_ms=0 phone_elapsed_ms=1000"],
                      received=1000, log_dir=log_dir)
            watch.detect_class_b_delivery_gap(state, log_dir)
            # Cursor frozen but no null-lux
            detection = watch.detect_class_b_delivery_gap(state, log_dir)
            self.assertIsNone(detection)

    def test_class_b_delivery_gap_detector_no_repeat_for_same_session_and_light(self):
        state = self.state()
        with tempfile.TemporaryDirectory() as folder:
            log_dir = Path(folder)
            self.page(state, ["1000 hello node=note3 protocol=1 session=s1",
                              "1000 light lux=0 accuracy=3 age_ms=0 phone_elapsed_ms=1000",
                              "1000 light lux=0 accuracy=3 age_ms=0 phone_elapsed_ms=2000"],
                      received=1000, log_dir=log_dir)
            watch.detect_class_b_delivery_gap(state, log_dir)
            # Simulate cursor frozen for > CLASS_B_FREEZE_SECONDS
            state["_class_b_last_cursor_advance_at"] = time.time() - watch.CLASS_B_FREEZE_SECONDS - 1
            detection1 = watch.detect_class_b_delivery_gap(state, log_dir)
            self.assertIsNotNone(detection1)
            # Same session and same retained light evidence: no repeat
            detection2 = watch.detect_class_b_delivery_gap(state, log_dir)
            self.assertIsNone(detection2)

    def test_class_b_delivery_gap_detector_bounded_output(self):
        state = self.state()
        with tempfile.TemporaryDirectory() as folder:
            log_dir = Path(folder)
            # Generate CLASS_B_DETECTOR_LINES + 5 detections
            for i in range(watch.CLASS_B_DETECTOR_LINES + 5):
                state["cursor"] = 100 + i
                state["session"] = f"s{i}"
                state["history"] = [{"kind": "light", "fields": {"lux": 0.0}},
                                     {"kind": "light", "fields": {"lux": 0.0}}]
                state.pop("_class_b_detected_light_sequence", None)
                state.pop("_class_b_detected_session", None)
                watch.detect_class_b_delivery_gap(state, log_dir)
            path = log_dir / "class-b-delivery-gap-detectors.jsonl"
            lines = path.read_text(encoding="utf-8").strip().split("\n")
            self.assertEqual(len(lines), watch.CLASS_B_DETECTOR_LINES)

    def test_class_b_delivery_gap_detector_no_false_positive_on_advancing_cursor(self):
        """Cursor advancing slowly (+4 per poll) must NOT trigger cursor-freeze.

        Real-world scenario: 2s poll interval, cursor advances +4 per ~10s.
        Between consecutive polls cursor is often unchanged, but over time it
        advances. Detector must distinguish slow advance from true freeze.
        """
        state = self.state()
        with tempfile.TemporaryDirectory() as folder:
            log_dir = Path(folder)
            # Session s1: two null-lux reads
            self.page(state, ["1000 hello node=note3 protocol=1 session=s1",
                              "1000 light lux=0 accuracy=3 age_ms=0 phone_elapsed_ms=1000",
                              "1000 light lux=0 accuracy=3 age_ms=0 phone_elapsed_ms=2000"],
                      received=1000, log_dir=log_dir)
            # Seed prev state
            watch.detect_class_b_delivery_gap(state, log_dir)
            # Simulate cursor advancing +4 per poll (like real Note3 scenario)
            # Each poll is 2s apart, cursor advances every ~5 polls (~10s)
            # After 3 polls: cursor should have advanced at least once
            state["cursor"] = 1004  # advanced +4
            detection = watch.detect_class_b_delivery_gap(state, log_dir)
            self.assertIsNone(detection)
            # Continue advancing: cursor keeps moving, no freeze
            state["cursor"] = 1008  # advanced +4 again
            detection = watch.detect_class_b_delivery_gap(state, log_dir)
            self.assertIsNone(detection)
            # Even after many polls with null-lux, advancing cursor = no freeze
            for i in range(10):
                state["cursor"] = 1008 + (i + 1) * 4
                detection = watch.detect_class_b_delivery_gap(state, log_dir)
                self.assertIsNone(detection)

    def test_class_b_detector_ignores_non_producer_cursor_advance(self):
        """A malformed authenticated POST advances the queue cursor without
        adding light evidence: 30 s later the cursor is frozen again, but this
        must not re-arm a second onset for one continuous gap.

        Live case: queue lines 265955-265956 ("invalid line here") advanced
        Note3 cursor 265954 -> 265956 at 2026-10-14T08:58:04Z and produced a
        duplicate class-b row at 08:58:34Z for the same session (discover
        DM 75390).
        """
        state = self.state()
        with tempfile.TemporaryDirectory() as folder:
            log_dir = Path(folder)
            self.page(state, ["1000 hello node=note3 protocol=1 session=s1",
                              "1000 light lux=0 accuracy=3 age_ms=0 phone_elapsed_ms=1000",
                              "1000 light lux=0 accuracy=3 age_ms=0 phone_elapsed_ms=2000"],
                      received=1000, log_dir=log_dir)
            watch.detect_class_b_delivery_gap(state, log_dir)  # seed prev state
            state["_class_b_last_cursor_advance_at"] = time.time() - watch.CLASS_B_FREEZE_SECONDS - 1
            first = watch.detect_class_b_delivery_gap(state, log_dir)
            self.assertIsNotNone(first)
            self.assertEqual(first["trigger"], "cursor-freeze")
            self.assertEqual(first["cursor_state"], "frozen")
            # Non-producer write: the queue cursor advances, no light arrives.
            state["cursor"] += 2
            watch.detect_class_b_delivery_gap(state, log_dir)
            # 30 s later the cursor is frozen again; the gap is the same one.
            state["_class_b_last_cursor_advance_at"] = time.time() - watch.CLASS_B_FREEZE_SECONDS - 1
            self.assertIsNone(watch.detect_class_b_delivery_gap(state, log_dir))
            rows = (log_dir / "class-b-delivery-gap-detectors.jsonl").read_text().strip().split("\n")
            self.assertEqual(len(rows), 1)

    def test_class_b_detector_fires_again_after_new_light_evidence(self):
        """A genuine resumption (a new light observation) followed by a new halt
        is a distinct gap and must still be reported."""
        state = self.state()
        with tempfile.TemporaryDirectory() as folder:
            log_dir = Path(folder)
            self.page(state, ["1000 hello node=note3 protocol=1 session=s1",
                              "1000 light lux=0 accuracy=3 age_ms=0 phone_elapsed_ms=1000",
                              "1000 light lux=0 accuracy=3 age_ms=0 phone_elapsed_ms=2000"],
                      received=1000, log_dir=log_dir)
            watch.detect_class_b_delivery_gap(state, log_dir)
            state["_class_b_last_cursor_advance_at"] = time.time() - watch.CLASS_B_FREEZE_SECONDS - 1
            self.assertIsNotNone(watch.detect_class_b_delivery_gap(state, log_dir))
            # Delivery resumes: a fresh null-lux light observation arrives.
            self.page(state, ["1000 light lux=0 accuracy=3 age_ms=0 phone_elapsed_ms=3000"],
                      received=1001, log_dir=log_dir)
            watch.detect_class_b_delivery_gap(state, log_dir)
            state["_class_b_last_cursor_advance_at"] = time.time() - watch.CLASS_B_FREEZE_SECONDS - 1
            again = watch.detect_class_b_delivery_gap(state, log_dir)
            self.assertIsNotNone(again)
            self.assertEqual(again["trigger"], "cursor-freeze")
            rows = (log_dir / "class-b-delivery-gap-detectors.jsonl").read_text().strip().split("\n")
            self.assertEqual(len(rows), 2)

    def test_load_seeds_class_b_light_identity_for_legacy_state(self):
        """State persisted before the dedup change keys class-B on (cursor,
        session). Loading must seed the light-sequence identity so a restart
        does not re-fire the still-current gap."""
        state = self.state()
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "note3.json"
            self.page(state, ["1000 hello node=note3 protocol=1 session=s1",
                              "1000 light lux=0 accuracy=3 age_ms=0 phone_elapsed_ms=1000",
                              "1000 light lux=0 accuracy=3 age_ms=0 phone_elapsed_ms=2000"],
                      received=1000)
            state["_class_b_detected_session"] = "s1"
            state["_class_b_detected_cursor"] = state["cursor"]
            state.pop("_class_b_detected_light_sequence", None)
            watch.save(path, state)
            loaded = watch.load(path)
            self.assertEqual(loaded["_class_b_detected_light_sequence"], 3)
            with tempfile.TemporaryDirectory() as logfolder:
                log_dir = Path(logfolder)
                watch.detect_class_b_delivery_gap(loaded, log_dir)  # seed prev state
                loaded["_class_b_last_cursor_advance_at"] = (
                    time.time() - watch.CLASS_B_FREEZE_SECONDS - 1)
                self.assertIsNone(watch.detect_class_b_delivery_gap(loaded, log_dir))

    def test_class_a_detector_freeze_on_code2_cursor_halt(self):
        state = self.state()
        with tempfile.TemporaryDirectory() as folder:
            log_dir = Path(folder)
            self.page(state, ["1000 ble_scan error reason=scan_failed code=2"],
                      received=time.time() - 301, log_dir=log_dir)
            watch.detect_class_a_freeze(state, log_dir)
            detection = watch.detect_class_a_freeze(state, log_dir)
            self.assertIsNotNone(detection)
            self.assertEqual(detection["kind"], "class-a-freeze")
            self.assertEqual(detection["code2_cursor"], 1)

    def test_class_a_detector_freeze_when_delivery_continues_then_halts(self):
        state = self.state()
        with tempfile.TemporaryDirectory() as folder:
            log_dir = Path(folder)
            start = time.time()
            self.page(state, ["1000 ble_scan error reason=scan_failed code=2"],
                      received=start - 400, log_dir=log_dir)
            self.page(state, ["1001 light lux=12.5 accuracy=3 age_ms=0 phone_elapsed_ms=1000"],
                      received=start - 341, log_dir=log_dir)
            watch.detect_class_a_freeze(state, log_dir)
            detection = watch.detect_class_a_freeze(state, log_dir)
            self.assertIsNotNone(detection)
            self.assertEqual(detection["kind"], "class-a-freeze")
            self.assertEqual(detection["code2_cursor"], 1)

    def test_class_a_detector_rejected_when_delivery_past_window(self):
        state = self.state()
        with tempfile.TemporaryDirectory() as folder:
            log_dir = Path(folder)
            start = time.time()
            self.page(state, ["1000 ble_scan error reason=scan_failed code=2"],
                      received=start - 400, log_dir=log_dir)
            self.page(state, ["1001 light lux=12.5 accuracy=3 age_ms=0 phone_elapsed_ms=1000"],
                      received=start - 50, log_dir=log_dir)
            watch.detect_class_a_freeze(state, log_dir)
            detection = watch.detect_class_a_freeze(state, log_dir)
            self.assertIsNotNone(detection)
            self.assertEqual(detection["kind"], "class-a-rejected")

    def test_class_a_detector_arm_survives_code2_aging_out_of_history(self):
        state = self.state()
        with tempfile.TemporaryDirectory() as folder:
            log_dir = Path(folder)
            start = time.time()
            self.page(state, ["1000 ble_scan error reason=scan_failed code=2"],
                      received=start - 400, log_dir=log_dir)
            for index in range(watch.HISTORY):
                self.page(state, ["1001 light lux=12.5 accuracy=3 age_ms=0 phone_elapsed_ms=1000"],
                          received=start - 400 + index, log_dir=log_dir)
            state["history"] = [item for item in state["history"] if item["sequence"] > 1]
            watch.detect_class_a_freeze(state, log_dir)
            detection = watch.detect_class_a_freeze(state, log_dir)
            self.assertIsNotNone(detection)
            self.assertEqual(detection["kind"], "class-a-freeze")

    def test_class_a_detector_silent_without_code2(self):
        state = self.state()
        with tempfile.TemporaryDirectory() as folder:
            log_dir = Path(folder)
            self.page(state, ["1000 hello node=note3 protocol=1 session=s1",
                              "1000 light lux=12.5 accuracy=3 age_ms=0 phone_elapsed_ms=1000"],
                      received=time.time() - 200, log_dir=log_dir)
            detection = watch.detect_class_a_freeze(state, log_dir)
            self.assertIsNone(detection)

    def test_class_a_detector_no_repeat_for_same_code2(self):
        state = self.state()
        with tempfile.TemporaryDirectory() as folder:
            log_dir = Path(folder)
            self.page(state, ["1000 ble_scan error reason=scan_failed code=2"],
                      received=time.time() - 301, log_dir=log_dir)
            watch.detect_class_a_freeze(state, log_dir)
            detection1 = watch.detect_class_a_freeze(state, log_dir)
            self.assertIsNotNone(detection1)
            detection2 = watch.detect_class_a_freeze(state, log_dir)
            self.assertIsNone(detection2)

    def test_class_a_detector_bounded_output(self):
        state = self.state()
        with tempfile.TemporaryDirectory() as folder:
            log_dir = Path(folder)
            state["latest"]["ble_scan"] = {
                "kind": "ble_scan",
                "raw": "1000 ble_scan error reason=scan_failed code=2",
                "fields": {"reason": "scan_failed", "code": "2"},
                "sequence": 100,
                "collected": 1000,
                "received": time.time() - 400}
            for i in range(watch.CLASS_A_DETECTOR_LINES + 5):
                state["cursor"] = 100 + i + 1
                state["history"] = [{"kind": "light",
                                     "raw": "1001 light lux=12.5 accuracy=3 age_ms=0",
                                     "fields": {"lux": 12.5, "accuracy": "3", "age_ms": "0"},
                                     "sequence": 100 + i + 1,
                                     "collected": 1001,
                                     "received": time.time() - 10}]
                state.pop("_class_a_detection_emitted", None)
                watch.detect_class_a_freeze(state, log_dir)
            path = log_dir / "class-a-detectors.jsonl"
            lines = path.read_text(encoding="utf-8").strip().split("\n")
            self.assertEqual(len(lines), watch.CLASS_A_DETECTOR_LINES)
    def test_class_c_delivery_gap_detector_fires_on_delivery_halt_without_known_cause(self):
        state = self.state()
        with tempfile.TemporaryDirectory() as folder:
            log_dir = Path(folder)
            start = time.time()
            self.page(state, ["1000 hello node=note3 protocol=1 session=s1",
                              "1000 light lux=12.5 accuracy=3 age_ms=0"],
                      received=start - 200, log_dir=log_dir)
            state["ok_at"] = time.time()
            detection = watch.detect_class_c_delivery_gap(state, log_dir)
            self.assertIsNotNone(detection)
            self.assertEqual(detection["kind"], "class-c-delivery-gap")
            self.assertEqual(detection["reason"],
                             "delivery halted with polls succeeding; no code=2, no null-lux freeze")

    def test_class_c_delivery_gap_detector_silent_before_window(self):
        state = self.state()
        with tempfile.TemporaryDirectory() as folder:
            log_dir = Path(folder)
            start = time.time()
            self.page(state, ["1000 hello node=note3 protocol=1 session=s1",
                              "1000 light lux=12.5 accuracy=3 age_ms=0"],
                      received=start - 50, log_dir=log_dir)
            state["ok_at"] = time.time()
            detection = watch.detect_class_c_delivery_gap(state, log_dir)
            self.assertIsNone(detection)

    def test_class_c_delivery_gap_detector_silent_when_class_a_armed(self):
        state = self.state()
        with tempfile.TemporaryDirectory() as folder:
            log_dir = Path(folder)
            start = time.time()
            self.page(state, ["1000 hello node=note3 protocol=1 session=s1",
                              "1000 light lux=12.5 accuracy=3 age_ms=0",
                              "1000 ble_scan error code=2 node=note3"],
                      received=start - 200, log_dir=log_dir)
            state["ok_at"] = time.time()
            detection = watch.detect_class_c_delivery_gap(state, log_dir)
            self.assertIsNone(detection)

    def test_class_c_delivery_gap_detector_silent_when_null_lux_condition_met(self):
        state = self.state()
        with tempfile.TemporaryDirectory() as folder:
            log_dir = Path(folder)
            start = time.time()
            self.page(state, ["1000 hello node=note3 protocol=1 session=s1",
                              "1000 light lux=0 accuracy=3 age_ms=0",
                              "1000 light lux=0 accuracy=3 age_ms=0"],
                      received=start - 200, log_dir=log_dir)
            state["ok_at"] = time.time()
            detection = watch.detect_class_c_delivery_gap(state, log_dir)
            self.assertIsNone(detection)

    def test_class_c_delivery_gap_detector_silent_when_polls_not_succeeding(self):
        state = self.state()
        with tempfile.TemporaryDirectory() as folder:
            log_dir = Path(folder)
            start = time.time()
            self.page(state, ["1000 hello node=note3 protocol=1 session=s1",
                              "1000 light lux=12.5 accuracy=3 age_ms=0"],
                      received=start - 200, log_dir=log_dir)
            detection = watch.detect_class_c_delivery_gap(state, log_dir)
            self.assertIsNone(detection)

    def test_class_c_delivery_gap_detector_no_repeat_for_same_cursor_session(self):
        state = self.state()
        with tempfile.TemporaryDirectory() as folder:
            log_dir = Path(folder)
            start = time.time()
            self.page(state, ["1000 hello node=note3 protocol=1 session=s1",
                              "1000 light lux=12.5 accuracy=3 age_ms=0"],
                      received=start - 200, log_dir=log_dir)
            state["ok_at"] = time.time()
            detection1 = watch.detect_class_c_delivery_gap(state, log_dir)
            self.assertIsNotNone(detection1)
            detection2 = watch.detect_class_c_delivery_gap(state, log_dir)
            self.assertIsNone(detection2)

    def test_class_c_delivery_gap_detector_bounded_output(self):
        state = self.state()
        with tempfile.TemporaryDirectory() as folder:
            log_dir = Path(folder)
            start = time.time()
            self.page(state, ["1000 hello node=note3 protocol=1 session=s1",
                              "1000 light lux=12.5 accuracy=3 age_ms=0"],
                      received=start - 200, log_dir=log_dir)
            state["ok_at"] = time.time()
            for i in range(watch.CLASS_C_DETECTOR_LINES + 5):
                state["cursor"] = 100 + i
                state["session"] = f"s{i}"
                state["history"] = [{"kind": "light",
                                     "raw": "1001 light lux=12.5 accuracy=3 age_ms=0",
                                     "received": start - 200}]
                state.pop("_class_c_detected_cursor", None)
                state.pop("_class_c_detected_session", None)
                watch.detect_class_c_delivery_gap(state, log_dir)
            path = log_dir / "class-c-delivery-gap-detectors.jsonl"
            lines = path.read_text(encoding="utf-8").strip().split("\n")
            self.assertEqual(len(lines), watch.CLASS_C_DETECTOR_LINES)

    def test_channel_delivery_verdict_pass_when_cursor_advancing(self):
        state = self.state()
        now = time.time()
        state["latest"]["battery"] = {
            "kind": "battery", "raw": "battery level=0.9 charging=true",
            "fields": {"level": "0.9", "charging": "true"},
            "received": now - 1.0, "collected": now - 1.0, "sequence": 100}
        state["latest"]["light"] = {
            "kind": "light", "raw": "light lux=17.0 accuracy=3 age_ms=4",
            "fields": {"lux": "17.0", "accuracy": "3", "age_ms": "4"},
            "received": now - 1.0, "collected": now - 1.0, "sequence": 100}
        state["latest"]["acceleration"] = {
            "kind": "acceleration",
            "raw": "acceleration unavailable reason=stale",
            "fields": {"reason": "stale"},
            "received": now - 1.0, "collected": now - 1.0, "sequence": 100}
        state["cursor"] = 100
        state["poll_at"] = now
        state["error"] = None
        # First call seeds
        watch._channel_delivery_verdict(state, now, 30.0)
        # Second call: cursor advances
        state["cursor"] = 101
        verdict = watch._channel_delivery_verdict(state, now, 30.0)
        self.assertEqual(verdict["status"], "pass")
        self.assertEqual(verdict["cursor_state"], "advancing")
        self.assertEqual(verdict["transport"], "reachable")
        self.assertIsNone(verdict["reason"])

    def test_channel_delivery_detector_fires_on_cursor_freeze(self):
        state = self.state()
        now = time.time()
        state["latest"]["battery"] = {
            "kind": "battery", "raw": "battery level=0.9 charging=true",
            "fields": {"level": "0.9", "charging": "true"},
            "received": now - 1.0, "collected": now - 1.0, "sequence": 100}
        state["cursor"] = 100
        state["poll_at"] = now
        state["error"] = None
        with tempfile.TemporaryDirectory() as folder:
            log_dir = Path(folder)
            # Seed
            watch.detect_channel_delivery_gap(state, log_dir, 30.0)
            # Simulate cursor frozen for > 30s
            state["_channel_delivery_last_cursor_advance_at"] = (
                now - watch.CHANNEL_DELIVERY_CURSOR_FREEZE_SECONDS - 1)
            detection = watch.detect_channel_delivery_gap(state, log_dir, 30.0)
            self.assertIsNotNone(detection)
            self.assertEqual(detection["reason"], "cursor-freeze")
            self.assertEqual(detection["cursor_state"], "frozen")

    def test_channel_delivery_detector_fires_on_transport_unreachable(self):
        state = self.state()
        now = time.time()
        state["cursor"] = 100
        state["poll_at"] = now
        state["error"] = "network-error"
        with tempfile.TemporaryDirectory() as folder:
            log_dir = Path(folder)
            # Seed with reachable
            state["error"] = None
            watch.detect_channel_delivery_gap(state, log_dir, 30.0)
            # Now unreachable
            state["error"] = "network-error"
            detection = watch.detect_channel_delivery_gap(state, log_dir, 30.0)
            self.assertIsNotNone(detection)
            self.assertEqual(detection["reason"], "transport-unreachable")

    def test_channel_delivery_detector_silent_on_throttling(self):
        """Cursor advancing + accel stale = throttling, NOT delivery loss."""
        state = self.state()
        now = time.time()
        state["latest"]["battery"] = {
            "kind": "battery", "raw": "battery level=0.9 charging=true",
            "fields": {"level": "0.9", "charging": "true"},
            "received": now - 1.0, "collected": now - 1.0, "sequence": 100}
        state["latest"]["light"] = {
            "kind": "light", "raw": "light lux=17.0 accuracy=3 age_ms=4",
            "fields": {"lux": "17.0", "accuracy": "3", "age_ms": "4"},
            "received": now - 1.0, "collected": now - 1.0, "sequence": 100}
        state["latest"]["acceleration"] = {
            "kind": "acceleration",
            "raw": "acceleration unavailable reason=stale",
            "fields": {"reason": "stale"},
            "received": now - 1.0, "collected": now - 1.0, "sequence": 100}
        state["cursor"] = 100
        state["poll_at"] = now
        state["error"] = None
        with tempfile.TemporaryDirectory() as folder:
            log_dir = Path(folder)
            # Seed
            watch.detect_channel_delivery_gap(state, log_dir, 30.0)
            # Cursor advances (throttling scenario)
            state["cursor"] = 101
            detection = watch.detect_channel_delivery_gap(state, log_dir, 30.0)
            self.assertIsNone(detection)

    def test_channel_delivery_detector_no_repeat_for_same_session_and_reason(self):
        state = self.state()
        now = time.time()
        state["cursor"] = 100
        state["poll_at"] = now
        state["error"] = None
        with tempfile.TemporaryDirectory() as folder:
            log_dir = Path(folder)
            # Seed
            watch.detect_channel_delivery_gap(state, log_dir, 30.0)
            # Simulate cursor frozen
            state["_channel_delivery_last_cursor_advance_at"] = (
                now - watch.CHANNEL_DELIVERY_CURSOR_FREEZE_SECONDS - 1)
            detection1 = watch.detect_channel_delivery_gap(state, log_dir, 30.0)
            self.assertIsNotNone(detection1)
            # Same session, same reason: no repeat
            detection2 = watch.detect_channel_delivery_gap(state, log_dir, 30.0)
            self.assertIsNone(detection2)
            # New session: fires again
            state["session"] = "s2"
            detection3 = watch.detect_channel_delivery_gap(state, log_dir, 30.0)
            self.assertIsNotNone(detection3)

    def test_channel_delivery_detector_bounded_output(self):
        state = self.state()
        now = time.time()
        state["cursor"] = 100
        state["poll_at"] = now
        state["error"] = None
        with tempfile.TemporaryDirectory() as folder:
            log_dir = Path(folder)
            # Seed
            watch.detect_channel_delivery_gap(state, log_dir, 30.0)
            for i in range(watch.CHANNEL_DELIVERY_DETECTOR_LINES + 5):
                state["session"] = f"s{i}"
                state["_channel_delivery_last_cursor_advance_at"] = (
                    now - watch.CHANNEL_DELIVERY_CURSOR_FREEZE_SECONDS - 1)
                state.pop("_channel_delivery_detected_key", None)
                watch.detect_channel_delivery_gap(state, log_dir, 30.0)
            path = log_dir / "channel-delivery-gap-detectors.jsonl"
            lines = path.read_text(encoding="utf-8").strip().split("\n")
            self.assertEqual(len(lines), watch.CHANNEL_DELIVERY_DETECTOR_LINES)

    def test_channel_delivery_verdict_per_channel_ages(self):
        state = self.state()
        now = time.time()
        state["latest"]["battery"] = {
            "kind": "battery", "raw": "battery level=0.9 charging=true",
            "fields": {"level": "0.9", "charging": "true"},
            "received": now - 2.0, "collected": now - 2.0, "sequence": 100}
        state["latest"]["light"] = {
            "kind": "light", "raw": "light lux=17.0 accuracy=3 age_ms=4",
            "fields": {"lux": "17.0", "accuracy": "3", "age_ms": "4"},
            "received": now - 5.0, "collected": now - 5.0, "sequence": 100}
        state["latest"]["acceleration"] = {
            "kind": "acceleration",
            "raw": "acceleration unavailable reason=stale",
            "fields": {"reason": "stale"},
            "received": now - 10.0, "collected": now - 10.0, "sequence": 100}
        state["cursor"] = 100
        state["poll_at"] = now
        state["error"] = None
        watch._channel_delivery_verdict(state, now, 30.0)  # seed
        state["cursor"] = 101
        verdict = watch._channel_delivery_verdict(state, now, 30.0)
        self.assertEqual(verdict["channel_ages_seconds"]["battery"], 2.0)
        self.assertEqual(verdict["channel_ages_seconds"]["light"], 5.0)
        self.assertEqual(verdict["channel_ages_seconds"]["acceleration"], 10.0)
        self.assertEqual(verdict["status"], "pass")
        self.assertEqual(verdict["cursor_state"], "advancing")

    def test_channel_delivery_verdict_event_ages_localize_per_channel(self):
        # age_ms is the phone-side age of the channel's last event at phone
        # collection, so the event's age now is age_ms/1000 + receipt delay --
        # per channel, with no host/phone clock agreement needed. This is the
        # witness L2 fix: shared receipt ages cannot localize a channel gap.
        state = self.state()
        now = time.time()
        state["latest"]["battery"] = {
            "kind": "battery", "raw": "battery level=0.9 charging=true",
            "fields": {"level": "0.9", "charging": "true"},
            "received": now - 2.0, "collected": now - 2.0, "sequence": 100}
        state["latest"]["light"] = {
            "kind": "light",
            "raw": "light unavailable reason=stale age_ms=120000",
            "fields": {"reason": "stale", "age_ms": "120000"},
            "received": now - 5.0, "collected": now - 5.0, "sequence": 100}
        state["latest"]["acceleration"] = {
            "kind": "acceleration",
            "raw": "acceleration unavailable reason=stale age_ms=15000",
            "fields": {"reason": "stale", "age_ms": "15000"},
            "received": now - 10.0, "collected": now - 10.0, "sequence": 100}
        state["cursor"] = 100
        state["poll_at"] = now
        state["error"] = None
        watch._channel_delivery_verdict(state, now, 30.0)  # seed
        state["cursor"] = 101
        verdict = watch._channel_delivery_verdict(state, now, 30.0)
        # Battery row carries no age_ms (not a sampled sensor): None, never a
        # fabricated receipt-age stand-in.
        self.assertIsNone(verdict["channel_event_ages_seconds"]["battery"])
        # Stale light: 120 s of sensor silence + 5 s receipt delay.
        self.assertEqual(verdict["channel_event_ages_seconds"]["light"], 125.0)
        # Stale accel: 15 s + 10 s.
        self.assertEqual(verdict["channel_event_ages_seconds"]["acceleration"], 25.0)
        # The two stale channels differ -- the gap is now localized per channel.
        self.assertNotEqual(verdict["channel_event_ages_seconds"]["light"],
                            verdict["channel_event_ages_seconds"]["acceleration"])
        # Receipt ages are unchanged: same envelope, still shared (the L2 limit
        # on that older field stands; this field is the fix).
        self.assertEqual(verdict["channel_ages_seconds"]["light"], 5.0)
        self.assertEqual(verdict["channel_ages_seconds"]["acceleration"], 10.0)

    def test_channel_delivery_detection_carries_event_ages(self):
        # The JSONL emission exposes the per-channel event ages alongside the
        # receipt ages, so a consumer of the log localizes the same gap.
        state = self.state()
        now = time.time()
        state["latest"]["acceleration"] = {
            "kind": "acceleration",
            "raw": "acceleration unavailable reason=stale age_ms=45000",
            "fields": {"reason": "stale", "age_ms": "45000"},
            "received": now - 3.0, "collected": now - 3.0, "sequence": 100}
        state["cursor"] = 100
        state["poll_at"] = now
        state["error"] = None
        with tempfile.TemporaryDirectory() as tmp:
            log_dir = Path(tmp)
            watch.detect_channel_delivery_gap(state, log_dir, 30.0)  # seed
            state["_channel_delivery_last_cursor_advance_at"] = (
                now - watch.CHANNEL_DELIVERY_CURSOR_FREEZE_SECONDS - 1)
            detection = watch.detect_channel_delivery_gap(state, log_dir, 30.0)
            self.assertEqual(detection["channel_event_ages_seconds"]["acceleration"], 48.0)
            lines = (log_dir / "channel-delivery-gap-detectors.jsonl").read_text(
                encoding="utf-8").strip().split("\n")
            logged = json.loads(lines[-1])
            self.assertEqual(logged["channel_event_ages_seconds"]["acceleration"], 48.0)

    def test_host_stopped_state_true(self):
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "    User 0:  installed=true hidden=false stopped=true notLaunched=false enabled=0\n"
        with patch("subprocess.run", return_value=mock_result):
            self.assertTrue(watch._host_stopped_state())

    def test_host_stopped_state_false(self):
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "    User 0:  installed=true hidden=false stopped=false notLaunched=false enabled=0\n"
        with patch("subprocess.run", return_value=mock_result):
            self.assertFalse(watch._host_stopped_state())

    def test_host_stopped_state_unknown_on_error(self):
        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stdout = ""
        with patch("subprocess.run", return_value=mock_result):
            self.assertIsNone(watch._host_stopped_state())

    def test_host_stopped_state_unknown_on_timeout(self):
        import subprocess
        with patch("subprocess.run", side_effect=subprocess.TimeoutExpired("adb", 5)):
            self.assertIsNone(watch._host_stopped_state())

    def test_host_stopped_state_unknown_on_no_adb(self):
        with patch("subprocess.run", side_effect=FileNotFoundError()):
            self.assertIsNone(watch._host_stopped_state())

    def test_host_stopped_probe_stays_offline_in_this_suite(self):
        # Regression guard for the observed defect: without setUp's guard the
        # class-C tests spawned 135 real `adb shell dumpsys` calls per run
        # against the connected phone (2026-10-14). With the device present the
        # real probe returns stopped=false, so this fails loudly if the guard is
        # dropped; the contract under test is "unknown when spawning is
        # unavailable", never a device read.
        self.assertIsNone(watch._host_stopped_state())

    def test_class_c_delivery_gap_detection_includes_host_stopped(self):
        state = self.state()
        with tempfile.TemporaryDirectory() as folder:
            log_dir = Path(folder)
            start = time.time()
            self.page(state, ["1000 hello node=note3 protocol=1 session=s1",
                              "1000 light lux=12.5 accuracy=3 age_ms=0"],
                      received=start - 200, log_dir=log_dir)
            state["ok_at"] = time.time()
            with patch("subprocess.run") as mock_run:
                mock_result = MagicMock()
                mock_result.returncode = 0
                mock_result.stdout = "    User 0:  installed=true hidden=false stopped=true notLaunched=false enabled=0\n"
                mock_run.return_value = mock_result
                detection = watch.detect_class_c_delivery_gap(state, log_dir)
            self.assertIsNotNone(detection)
            self.assertTrue(detection["host_stopped"])

    def test_class_c_delivery_gap_detection_host_stopped_false(self):
        state = self.state()
        with tempfile.TemporaryDirectory() as folder:
            log_dir = Path(folder)
            start = time.time()
            self.page(state, ["1000 hello node=note3 protocol=1 session=s1",
                              "1000 light lux=12.5 accuracy=3 age_ms=0"],
                      received=start - 200, log_dir=log_dir)
            state["ok_at"] = time.time()
            with patch("subprocess.run") as mock_run:
                mock_result = MagicMock()
                mock_result.returncode = 0
                mock_result.stdout = "    User 0:  installed=true hidden=false stopped=false notLaunched=false enabled=0\n"
                mock_run.return_value = mock_result
                detection = watch.detect_class_c_delivery_gap(state, log_dir)
            self.assertIsNotNone(detection)
            self.assertFalse(detection["host_stopped"])

    def test_class_c_delivery_gap_detection_host_stopped_unknown(self):
        state = self.state()
        with tempfile.TemporaryDirectory() as folder:
            log_dir = Path(folder)
            start = time.time()
            self.page(state, ["1000 hello node=note3 protocol=1 session=s1",
                              "1000 light lux=12.5 accuracy=3 age_ms=0"],
                      received=start - 200, log_dir=log_dir)
            state["ok_at"] = time.time()
            with patch("subprocess.run") as mock_run:
                mock_result = MagicMock()
                mock_result.returncode = 1
                mock_result.stdout = ""
                mock_run.return_value = mock_result
                detection = watch.detect_class_c_delivery_gap(state, log_dir)
            self.assertIsNotNone(detection)
            self.assertIsNone(detection["host_stopped"])

    def test_light_resumption_view_reports_missing_heartbeat_as_unknown_not_calm(self):
        with tempfile.TemporaryDirectory() as folder:
            folder = Path(folder)
            with patch.object(watch, "MONITOR_STATE_FILE", folder / "absent-state.json"), \
                 patch.object(watch, "MONITOR_LOG_FILE", folder / "absent-log.jsonl"):
                view = watch.light_resumption_view(1000, 30)
        self.assertIn("status=unknown/no-monitor-heartbeat", view)
        self.assertIn("UNKNOWN, not calm", view)
        self.assertIn("last_row=none", view)

    def test_light_resumption_view_reports_fresh_armed_state_and_last_row(self):
        with tempfile.TemporaryDirectory() as folder:
            folder = Path(folder)
            state_file = folder / "light-cycle-monitor-state.json"
            log_file = folder / "light-cycle-resumed.jsonl"
            state_file.write_text(json.dumps({
                "poll": 7, "interval_seconds": 30.0, "max_polls": 3300,
                "threshold_lux": 7.0, "lux": 11.4, "prev_lux": 0.2, "armed": True,
                "pid": 4242, "started_unix": 900.0, "timestamp_unix": 990.0}))
            log_file.write_text(json.dumps({
                "event": "light-cycle-resumed", "lux": 11.4, "prev_lux": 0.2,
                "prev_observed_unix": 960.0, "baseline_first_unix": 960.0,
                "baseline_samples": [[12, 960.0, 0.2]], "threshold_lux": 7.0, "samples": 7,
                "timestamp_unix": 990.0}) + "\n")
            with patch.object(watch, "MONITOR_STATE_FILE", state_file), \
                 patch.object(watch, "MONITOR_LOG_FILE", log_file):
                view = watch.light_resumption_view(1000, 30)
        self.assertIn("status=fresh-clock-conditional", view)
        self.assertIn("heartbeat_age=10.0s (stale>30s)", view)
        self.assertIn("armed=True", view)
        self.assertIn("pid=4242", view)
        self.assertIn("last_row=lux=11.4 prev_lux=0.2 threshold_lux=7.0 samples=7 "
                      "baseline_span_s=-", view)
        self.assertNotIn("predates the 7.0-lux rule", view)

    def test_light_resumption_view_flags_silent_detector_and_retained_old_row(self):
        with tempfile.TemporaryDirectory() as folder:
            folder = Path(folder)
            state_file = folder / "light-cycle-monitor-state.json"
            log_file = folder / "light-cycle-resumed.jsonl"
            state_file.write_text(json.dumps({
                "poll": 3, "armed": False, "lux": None, "prev_lux": None,
                "threshold_lux": 7.0, "timestamp_unix": 900.0}))
            log_file.write_text(json.dumps({
                "event": "light-cycle-resumed", "lux": 2.505, "poll": 0,
                "prev_lux": None, "timestamp_unix": 899.0}) + "\n")
            with patch.object(watch, "MONITOR_STATE_FILE", state_file), \
                 patch.object(watch, "MONITOR_LOG_FILE", log_file):
                view = watch.light_resumption_view(1000, 30)
        self.assertIn("status=stale/detector-silent", view)
        self.assertIn("baseline=no-fresh-reading", view)
        self.assertIn("predates the current rule", view)

    def _detector_view(self, heartbeat, row=None):
        """Render the detector view against a written heartbeat (and optional last row)."""
        with tempfile.TemporaryDirectory() as folder:
            folder = Path(folder)
            state_file = folder / "light-cycle-monitor-state.json"
            log_file = folder / "light-cycle-resumed.jsonl"
            state_file.write_text(json.dumps(heartbeat))
            if row is not None:
                log_file.write_text(json.dumps(row) + "\n")
            with patch.object(watch, "MONITOR_STATE_FILE", state_file), \
                 patch.object(watch, "MONITOR_LOG_FILE", log_file):
                return (watch.light_resumption_view(1000, 30),
                        watch.light_resumption_view(1000, 30, compact=True))

    def test_light_resumption_view_names_a_frozen_source_as_no_fresh_reading(self):
        # The live case: the phone is ON but collect-only, so the light channel delivers
        # nothing fresh. armed=false is "a fresh baseline exists" being false, not "the
        # fresh readings are all bright"; the view must name the source, not the threshold.
        heartbeat = {"poll": 310, "interval_seconds": 30.0, "max_polls": 3300,
                     "threshold_lux": 7.0, "lux": None, "prev_lux": None, "armed": False,
                     "pid": 4242, "started_unix": 900.0, "timestamp_unix": 990.0}
        view, compact = self._detector_view(heartbeat)
        self.assertIn("baseline=no-fresh-reading", view)
        self.assertIn("no fresh light reading has been observed this run", view)
        self.assertNotIn("fresh baseline below the threshold", view)
        self.assertIn("armed=False baseline=no-fresh-reading", compact)

    def test_light_resumption_view_names_a_bright_baseline_as_not_resumable(self):
        # armed=true does not mean "a sub-threshold baseline": a fresh, already-lit reading
        # arms the detector with nothing dim to resume from.
        heartbeat = {"poll": 5, "threshold_lux": 7.0, "lux": 12.4, "prev_lux": 12.4,
                     "armed": True, "timestamp_unix": 990.0}
        view, compact = self._detector_view(heartbeat)
        self.assertIn("baseline=at-or-above-threshold", view)
        self.assertIn("nothing dim to resume from", view)
        self.assertNotIn("no fresh light reading", view)
        self.assertIn("armed=True baseline=at-or-above-threshold", compact)

    def test_light_resumption_view_names_a_stale_poll_with_a_retained_baseline(self):
        # A baseline survives the source going stale: only fresh readings update it, so the
        # current poll's silence must be reported separately from the baseline's existence.
        heartbeat = {"poll": 9, "threshold_lux": 7.0, "lux": None, "prev_lux": 0.2,
                     "armed": True, "timestamp_unix": 990.0}
        view, compact = self._detector_view(heartbeat)
        self.assertIn("baseline=baseline-without-current-reading", view)
        self.assertIn("no transition can be evaluated this poll", view)
        self.assertIn("armed=True baseline=baseline-without-current-reading", compact)

    def test_light_resumption_view_names_a_sub_threshold_baseline(self):
        heartbeat = {"poll": 4, "threshold_lux": 7.0, "lux": 0.4, "prev_lux": 0.2,
                     "armed": True, "timestamp_unix": 990.0}
        view, compact = self._detector_view(heartbeat)
        self.assertIn("baseline=sub-threshold", view)
        self.assertIn("armed=True baseline=sub-threshold", compact)

    def test_light_resumption_view_names_a_dwell_arming_state(self):
        # dark-dwell rule: fresh dark readings exist but the required consecutive dark
        # samples have not been seen, so the detector is arming rather than armed.
        heartbeat = {"poll": 2, "rule": "dark-dwell", "threshold_lux": 10.0,
                     "rule_constants": {"arm_lux_max": 6.0, "resume_lux_min": 10.0,
                                        "dark_dwell_samples": 3},
                     "lux": 2.0, "prev_lux": 1.0, "armed": False, "dark_run": 1,
                     "timestamp_unix": 990.0}
        view, compact = self._detector_view(heartbeat)
        self.assertIn("baseline=dwell-arming", view)
        self.assertIn("fewer consecutive dark samples", view)
        self.assertNotIn("no fresh light reading", view)
        self.assertIn("armed=False baseline=dwell-arming", compact)

    def test_light_resumption_view_names_an_armed_dark_dwell(self):
        heartbeat = {"poll": 4, "rule": "dark-dwell", "threshold_lux": 10.0,
                     "rule_constants": {"arm_lux_max": 6.0, "resume_lux_min": 10.0,
                                        "dark_dwell_samples": 3},
                     "lux": 1.0, "prev_lux": 0.5, "armed": True, "dark_run": 3,
                     "timestamp_unix": 990.0}
        view, compact = self._detector_view(heartbeat)
        self.assertIn("baseline=sub-threshold", view)
        self.assertIn("armed=True baseline=sub-threshold", compact)

    def test_light_resumption_view_names_a_lit_dark_dwell_baseline(self):
        # Not armed, but the reason is a lit reading, not an incomplete dwell.
        heartbeat = {"poll": 6, "rule": "dark-dwell", "threshold_lux": 10.0,
                     "rule_constants": {"arm_lux_max": 6.0, "resume_lux_min": 10.0,
                                        "dark_dwell_samples": 3},
                     "lux": 64.0, "prev_lux": 58.0, "armed": False, "dark_run": 0,
                     "timestamp_unix": 990.0}
        view, compact = self._detector_view(heartbeat)
        self.assertIn("baseline=at-or-above-threshold", view)
        self.assertIn("nothing dim to resume from", view)
        self.assertIn("armed=False baseline=at-or-above-threshold", compact)

    def test_light_resumption_view_names_a_stale_dark_dwell_source(self):
        heartbeat = {"poll": 8, "rule": "dark-dwell", "threshold_lux": 10.0,
                     "rule_constants": {"arm_lux_max": 6.0, "resume_lux_min": 10.0,
                                        "dark_dwell_samples": 3},
                     "lux": None, "prev_lux": 1.0, "armed": True, "dark_run": 3,
                     "timestamp_unix": 990.0}
        view, compact = self._detector_view(heartbeat)
        self.assertIn("baseline=baseline-without-current-reading", view)
        self.assertIn("armed=True baseline=baseline-without-current-reading", compact)

    def test_light_resumption_view_shows_the_monitored_node_and_rule(self):
        heartbeat = {"node": "redmi10", "poll": 2, "rule": "dark-dwell",
                     "rule_constants": {"arm_lux_max": 6.0, "resume_lux_min": 10.0,
                                        "dark_dwell_samples": 3},
                     "threshold_lux": 10.0, "lux": 2.0, "prev_lux": 1.0, "armed": False,
                     "dark_run": 2, "timestamp_unix": 990.0}
        view, _ = self._detector_view(heartbeat)
        self.assertIn("over the redmi10 light channel", view)
        self.assertIn("rule=dark-dwell", view)
        self.assertIn("dark_run=2", view)

    def test_monitor_baseline_rejects_a_dark_dwell_heartbeat_without_numbers(self):
        for heartbeat in ({"rule": "dark-dwell", "armed": True, "lux": 1.0,
                           "prev_lux": "dark", "threshold_lux": 10.0},
                          {"rule": "dark-dwell", "armed": True, "lux": 1.0,
                           "prev_lux": 0.5, "threshold_lux": None},
                          {"rule": "dark-dwell", "armed": "yes", "lux": 1.0,
                           "prev_lux": 0.5, "threshold_lux": 10.0}):
            self.assertEqual(watch.monitor_baseline(heartbeat), "unknown", heartbeat)

    def test_monitor_baseline_reports_unknown_for_an_inconsistent_heartbeat(self):
        # A heartbeat whose armed flag disagrees with its own fields is not calm.
        for heartbeat in ({"armed": True, "lux": 0.4, "prev_lux": None, "threshold_lux": 7.0},
                          {"armed": False, "lux": None, "prev_lux": 0.2, "threshold_lux": 7.0},
                          {"armed": "yes", "lux": 0.4, "prev_lux": 0.2, "threshold_lux": 7.0},
                          {"armed": True, "lux": 0.4, "prev_lux": 0.2},
                          None):
            self.assertEqual(watch.monitor_baseline(heartbeat), "unknown", heartbeat)
        view, compact = self._detector_view({"poll": 1, "threshold_lux": 7.0, "lux": 0.4,
                                             "prev_lux": None, "armed": True,
                                             "timestamp_unix": 990.0})
        self.assertIn("baseline=unknown", view)
        self.assertIn("UNKNOWN, not calm", view)
        self.assertIn("baseline=unknown", compact)

    def test_monitor_baselines_cover_every_rendered_sentence(self):
        for baseline in watch.MONITOR_BASELINES:
            self.assertIn(baseline, watch.MONITOR_BASELINE_TEXT)
        self.assertEqual(len(set(watch.MONITOR_BASELINES)), len(watch.MONITOR_BASELINES))

    def test_read_views_carries_the_detector_verdict_into_the_pane_text(self):
        with tempfile.TemporaryDirectory() as folder:
            folder = Path(folder)
            watch.save(folder / "note3.json", self.state())
            artifacts = folder / "runtime-artifacts"
            artifacts.mkdir()
            state_file = artifacts / "light-cycle-monitor-state.json"
            state_file.write_text(json.dumps({
                "poll": 1, "armed": False, "lux": None, "prev_lux": None,
                "threshold_lux": 7.0, "timestamp_unix": 1000.0}))
            with patch.object(watch, "MONITOR_STATE_FILE", state_file), \
                 patch.object(watch, "MONITOR_LOG_FILE", artifacts / "no-log.jsonl"):
                view = watch.read_views(folder, 1000, 30)
                compact = watch.read_views(folder, 1000, 30, compact=True)
        self.assertIn("NODE note3", view)
        self.assertIn("Light-cycle resumption detector", view)
        self.assertIn("status=fresh-clock-conditional", view)
        self.assertIn("light-resumption-detector status=fresh-clock-conditional", compact)
        # The compact view is cached to events.txt; a per-poll age would rewrite it every poll.
        self.assertNotIn("heartbeat_age", compact)


    def test_last_monitor_row_survives_a_truncated_final_line(self):
        # A crash mid-append must not turn earlier complete rows into "no row".
        with tempfile.TemporaryDirectory() as folder:
            log_file = Path(folder) / "light-cycle-resumed.jsonl"
            log_file.write_text(json.dumps({
                "event": "light-cycle-resumed", "lux": 11.4, "prev_lux": 0.2,
                "prev_observed_unix": 960.0, "threshold_lux": 7.0, "poll": 7,
                "timestamp_unix": 990.0}) + "\n" + '{"event": "light-cycle-resum')
            with patch.object(watch, "MONITOR_STATE_FILE", Path(folder) / "absent.json"), \
                 patch.object(watch, "MONITOR_LOG_FILE", log_file):
                view = watch.light_resumption_view(1000, 30)
        self.assertIn("last_row=lux=11.4 prev_lux=0.2 threshold_lux=7.0 samples=7 "
                      "baseline_span_s=-", view)
        self.assertNotIn("last_row=none", view)

    def test_last_monitor_row_reports_none_when_no_line_is_complete(self):
        with tempfile.TemporaryDirectory() as folder:
            log_file = Path(folder) / "light-cycle-resumed.jsonl"
            log_file.write_text('{"event": "light-cycle-resum')
            with patch.object(watch, "MONITOR_STATE_FILE", Path(folder) / "absent.json"), \
                 patch.object(watch, "MONITOR_LOG_FILE", log_file):
                view = watch.light_resumption_view(1000, 30)
        self.assertIn("last_row=none", view)

    def test_last_monitor_row_reads_past_the_bounded_tail_start(self):
        # The tail read starts mid-line on a large log; the last complete row must survive.
        with tempfile.TemporaryDirectory() as folder:
            log_file = Path(folder) / "light-cycle-resumed.jsonl"
            rows = [json.dumps({"event": "light-cycle-resumed", "lux": 8.0 + index,
                                "prev_lux": 0.2, "prev_observed_unix": 900.0 + index,
                                "threshold_lux": 7.0, "poll": index,
                                "timestamp_unix": 930.0 + index})
                    for index in range(60)]
            log_file.write_text("\n".join(rows) + "\n")
            self.assertGreater(log_file.stat().st_size, watch.MONITOR_LOG_TAIL_BYTES)
            with patch.object(watch, "MONITOR_STATE_FILE", Path(folder) / "absent.json"), \
                 patch.object(watch, "MONITOR_LOG_FILE", log_file):
                view = watch.light_resumption_view(1000, 30)
        self.assertIn("last_row=lux=67.0 prev_lux=0.2 threshold_lux=7.0 samples=59", view)


    def test_last_monitor_row_names_a_pre_rename_row_and_flags_it(self):
        # The count of consumed samples and the baseline start were written as ``poll`` and
        # ``prev_observed_unix`` until 2026-10-16. The view renders both under their current
        # names and says the row predates the rename, so a reader is not left comparing the
        # row's ``poll`` against the heartbeat's ``poll`` (the check index).
        with tempfile.TemporaryDirectory() as folder:
            log_file = Path(folder) / "light-cycle-resumed.jsonl"
            log_file.write_text(json.dumps({
                "event": "light-cycle-resumed", "lux": 14.0, "prev_lux": 4.0,
                "prev_observed_unix": 1005.0, "threshold_lux": 10.0, "poll": 3284,
                "baseline_samples": [[49923, 1005.0, 4.0], [49943, 1030.0, 4.0]],
                "timestamp_unix": 1073.0}) + "\n")
            with patch.object(watch, "MONITOR_STATE_FILE", Path(folder) / "absent.json"), \
                 patch.object(watch, "MONITOR_LOG_FILE", log_file):
                view = watch.light_resumption_view(1000, 30)
        self.assertIn("last_row=lux=14.0 prev_lux=4.0 threshold_lux=10.0 samples=3284 "
                      "baseline_span_s=25s", view)
        self.assertIn("predates the 2026-10-16 field rename", view)

    def test_last_monitor_row_names_a_current_row_without_the_rename_note(self):
        with tempfile.TemporaryDirectory() as folder:
            log_file = Path(folder) / "light-cycle-resumed.jsonl"
            log_file.write_text(json.dumps({
                "event": "light-cycle-resumed", "lux": 14.0, "prev_lux": 4.0,
                "prev_observed_unix": 1030.0, "baseline_first_unix": 1005.0,
                "baseline_samples": [[49923, 1005.0, 4.0], [49943, 1030.0, 4.0]],
                "threshold_lux": 10.0, "samples": 3341, "timestamp_unix": 1073.0}) + "\n")
            with patch.object(watch, "MONITOR_STATE_FILE", Path(folder) / "absent.json"), \
                 patch.object(watch, "MONITOR_LOG_FILE", log_file):
                view = watch.light_resumption_view(1000, 30)
        self.assertIn("last_row=lux=14.0 prev_lux=4.0 threshold_lux=10.0 samples=3341 "
                      "baseline_span_s=25s", view)
        self.assertNotIn("predates the 2026-10-16 field rename", view)

    def test_node_state_document_is_not_parsed_as_a_perception_state(self):
        # tools/node_state.py publishes node-state-<node>.json into the same
        # directory; loading it as a perception state raised KeyError 'version'
        # and crash-looped the follower on 2026-10-14.
        state = self.state()
        self.page(state, ["1000 light lux=12.5 accuracy=3 age_ms=21"])
        with tempfile.TemporaryDirectory() as folder:
            directory = Path(folder)
            watch.save(directory / "note3.json", state)
            (directory / "node-state-note3.json").write_text(json.dumps({
                "node": "note3", "mode": "ON_COLLECT_ONLY", "desired_on": True,
                "collect_only": True, "observed_at_epoch_s": 1000.0,
                "source": "tools/node_state.py", "reasons": []}))
            view = watch.read_views(directory, 1000, 30)
            space = watch.read_space(directory, 1000, 30)
        self.assertIn("NODE note3", view)
        self.assertIn("mode=ON_COLLECT_ONLY desired_on=true collect_only=true", view)
        self.assertEqual([node["node"] for node in space["nodes"]], ["note3"])

    def test_read_node_state_reports_published_mode_and_age(self):
        with tempfile.TemporaryDirectory() as folder:
            directory = Path(folder)
            (directory / "node-state-note3.json").write_text(json.dumps({
                "node": "note3", "mode": "OFF", "desired_on": False,
                "collect_only": False, "observed_at_epoch_s": 1000.0,
                "source": "tools/node_state.py", "reasons": ["marker absent"]}))
            verdict = watch.read_node_state(directory, "note3", 1030.0)
        self.assertEqual(verdict["status"], "ok")
        self.assertEqual(verdict["mode"], "OFF")
        self.assertFalse(verdict["desired_on"])
        self.assertEqual(verdict["age_s"], 30.0)

    def test_read_node_state_failures_and_staleness_are_unknown_never_off(self):
        with tempfile.TemporaryDirectory() as folder:
            directory = Path(folder)
            absent = watch.read_node_state(directory, "note3", 1000.0)
            self.assertEqual((absent["status"], absent["mode"]), ("absent", "UNKNOWN"))
            other = watch.read_node_state(directory, "redmi10", 1000.0)
            self.assertEqual((other["status"], other["mode"]), ("absent", "UNKNOWN"))
            path = directory / "node-state-note3.json"
            path.write_text("{not json")
            invalid = watch.read_node_state(directory, "note3", 1000.0)
            self.assertEqual((invalid["status"], invalid["mode"]), ("invalid", "UNKNOWN"))
            path.write_text(json.dumps({
                "node": "note3", "mode": "OFF", "desired_on": False,
                "collect_only": False, "observed_at_epoch_s": 1000.0,
                "source": "tools/node_state.py", "reasons": []}))
            stale = watch.read_node_state(directory, "note3", 1000.0 + 3600)
            self.assertEqual((stale["status"], stale["mode"]), ("stale", "UNKNOWN"))

    def test_view_renders_absent_node_state_as_unknown_never_off(self):
        state = self.state()
        self.page(state, ["1000 light lux=12.5 accuracy=3 age_ms=21"])
        with tempfile.TemporaryDirectory() as folder:
            directory = Path(folder)
            watch.save(directory / "note3.json", state)
            view = watch.read_views(directory, 1000, 30)
        self.assertIn("mode=UNKNOWN status=absent reason=no-node-state-file", view)
        self.assertNotIn("mode=OFF", view)
        self.assertNotIn("reasons=", view)

    def test_read_node_state_bounds_and_sanitizes_reasons(self):
        with tempfile.TemporaryDirectory() as folder:
            directory = Path(folder)
            (directory / "node-state-note3.json").write_text(json.dumps({
                "node": "note3", "mode": "ON_COLLECT_ONLY", "desired_on": True,
                "collect_only": True, "observed_at_epoch_s": 1000.0,
                "source": "tools/node_state.py",
                "reasons": ["ok reason", "", "   ", 7, "x" * 500,
                            "r1", "r2", "r3", "r4", "r5"]}))
            verdict = watch.read_node_state(directory, "note3", 1000.0)
            absent = watch.read_node_state(directory, "redmi10", 1000.0)
        self.assertEqual(verdict["reasons"][0], "ok reason")
        self.assertEqual(len(verdict["reasons"]), watch.NODE_STATE_MAX_REASONS)
        self.assertEqual(len(verdict["reasons"][1]), watch.NODE_STATE_MAX_REASON_CHARS)
        self.assertTrue(verdict["reasons"][1].endswith("..."))
        self.assertNotIn("x" * 500, verdict["reasons"])
        self.assertEqual(absent["reasons"], [])

    def test_view_renders_node_state_reasons(self):
        state = self.state()
        self.page(state, ["1000 light lux=12.5 accuracy=3 age_ms=21"])
        with tempfile.TemporaryDirectory() as folder:
            directory = Path(folder)
            watch.save(directory / "note3.json", state)
            (directory / "node-state-note3.json").write_text(json.dumps({
                "node": "note3", "mode": "ON_COLLECT_ONLY", "desired_on": True,
                "collect_only": True, "observed_at_epoch_s": 1000.0,
                "source": "tools/node_state.py",
                "reasons": ["marker matches the recorded endpoint cursor",
                            "collect-only: no HTTP by design"]}))
            view = watch.read_views(directory, 1000, 30)
        self.assertIn("status=ok reasons=marker matches the recorded endpoint cursor; "
                      "collect-only: no HTTP by design", view)

    def test_read_node_state_reasons_cannot_forge_lines_or_break_utf8(self):
        state = self.state()
        self.page(state, ["1000 light lux=12.5 accuracy=3 age_ms=21"])
        with tempfile.TemporaryDirectory() as folder:
            directory = Path(folder)
            watch.save(directory / "note3.json", state)
            (directory / "node-state-note3.json").write_text(json.dumps({
                "node": "note3", "mode": "ON_COLLECT_ONLY", "desired_on": True,
                "collect_only": True, "observed_at_epoch_s": 1000.0,
                "source": "tools/node_state.py",
                "reasons": ["line one\nline two", "esc\x1b[31mred",
                            "solo\ud800surrogate"]}))
            verdict = watch.read_node_state(directory, "note3", 1000.0)
            view = watch.read_views(directory, 1000, 30)
            watch.atomic(directory / "view.txt", view)
            written = (directory / "view.txt").read_text(encoding="utf-8")
        self.assertEqual(verdict["reasons"],
                         ["line one line two", "esc[31mred", "solosurrogate"])
        self.assertEqual(written, view)
        self.assertIn("reasons=line one line two; esc[31mred; solosurrogate", written)

    def test_class_b_record_carries_node_mode_provenance(self):
        state = self.state()
        with tempfile.TemporaryDirectory() as folder:
            log_dir = Path(folder)
            self.page(state, ["1000 hello node=note3 protocol=1 session=s1",
                              "1000 light lux=0 accuracy=3 age_ms=0 phone_elapsed_ms=1000",
                              "1000 light lux=0 accuracy=3 age_ms=0 phone_elapsed_ms=2000"],
                      received=1000, log_dir=log_dir)
            mode = {"status": "ok", "mode": "ON_COLLECT_ONLY"}
            watch.detect_class_b_delivery_gap(state, log_dir, mode)
            state["_class_b_last_cursor_advance_at"] = (
                time.time() - watch.CLASS_B_FREEZE_SECONDS - 1)
            detection = watch.detect_class_b_delivery_gap(state, log_dir, mode)
            row = json.loads(
                (log_dir / "class-b-delivery-gap-detectors.jsonl").read_text().strip().split("\n")[-1])
        self.assertEqual(detection["node_mode"], "ON_COLLECT_ONLY")
        self.assertEqual(detection["node_state_status"], "ok")
        self.assertEqual(row["node_mode"], "ON_COLLECT_ONLY")
        self.assertEqual(row["node_state_status"], "ok")

    def write_clock(self, directory, document):
        (Path(directory).parent / "clock-domain-note3.json").write_text(
            json.dumps(document))


    def test_read_clock_domain_reports_absent_invalid_and_stale_as_unknown(self):
        state = self.state()
        with tempfile.TemporaryDirectory() as folder:
            directory = Path(folder) / "perception"
            directory.mkdir()
            watch.save(directory / "note3.json", state)
            self.assertEqual(watch.read_clock_domain(directory, "note3", 1000.0)["status"],
                             "absent")
            self.assertIsNone(watch.read_clock_domain(directory, "note3", 1000.0)["offset_nominal_s"])
            self.write_clock(directory, {"node": "note3", "status": "unavailable"})
            self.assertEqual(watch.read_clock_domain(directory, "note3", 1000.0)["status"],
                             "invalid")
            self.write_clock(directory, {"node": "redmi10", "status": "ok",
                                         "offset_min_s": 1.0, "offset_max_s": 2.0,
                                         "offset_nominal_s": 1.5,
                                         "observed_at_epoch_s": 1000.0,
                                         "validity_seconds": 3600.0})
            self.assertEqual(watch.read_clock_domain(directory, "note3", 1000.0)["status"],
                             "invalid")
            self.write_clock(directory, {"node": "note3", "status": "ok",
                                         "offset_min_s": 24.0, "offset_max_s": 25.0,
                                         "offset_nominal_s": 25.4, "samples": 7,
                                         "observed_at_epoch_s": 1000.0,
                                         "validity_seconds": 3600.0})
            fresh = watch.read_clock_domain(directory, "note3", 1000.0)
            expired = watch.read_clock_domain(directory, "note3", 1000.0 + 3601)
        self.assertEqual(fresh["status"], "ok")
        self.assertEqual(fresh["offset_max_s"], 25.0)
        self.assertEqual(fresh["age_s"], 0.0)
        self.assertEqual(expired["status"], "stale")
        self.assertIsNone(expired["offset_min_s"])

    def test_read_clock_domain_carries_the_measured_device_identity(self):
        state = self.state()
        with tempfile.TemporaryDirectory() as folder:
            directory = Path(folder) / "perception"
            directory.mkdir()
            watch.save(directory / "note3.json", state)
            named_doc = {"node": "note3", "status": "ok", "offset_min_s": 24.0,
                         "offset_max_s": 25.0, "offset_nominal_s": 24.5, "samples": 7,
                         "observed_at_epoch_s": 1000.0, "validity_seconds": 3600.0,
                         "device_serial": "4d00553d61ab90b7", "device_model": "SM-N900"}
            self.write_clock(directory, named_doc)
            named = watch.read_clock_domain(directory, "note3", 1000.0)
            self.write_clock(directory, {key: value for key, value in named_doc.items()
                                         if not key.startswith("device_")})
            unnamed = watch.read_clock_domain(directory, "note3", 1000.0)
            self.write_clock(directory, {"node": "redmi10", "status": "ok",
                                         "device_serial": "4d00553d61ab90b7",
                                         "device_model": "SM-N900"})
            foreign = watch.read_clock_domain(directory, "note3", 1000.0)
        self.assertEqual((named["device_serial"], named["device_model"]),
                         ("4d00553d61ab90b7", "SM-N900"))
        self.assertEqual((unnamed["device_serial"], unnamed["device_model"]), (None, None))
        # An unusable document still reports which device it claims to come from, so
        # a mislabelled one is diagnosable instead of merely "invalid".
        self.assertEqual(foreign["status"], "invalid")
        self.assertEqual(foreign["device_serial"], "4d00553d61ab90b7")

    def test_read_clock_domain_carries_the_host_ntp_verdict(self):
        # tools/clock_offset.py publishes the host's own NTPSynchronized verdict as
        # provenance; the renderer needs it to name the host side of the offset. A
        # missing, non-boolean or unusable document stays None, never a verdict.
        state = self.state()
        with tempfile.TemporaryDirectory() as folder:
            directory = Path(folder) / "perception"
            directory.mkdir()
            watch.save(directory / "note3.json", state)
            base = {"node": "note3", "status": "ok", "offset_min_s": 24.0,
                    "offset_max_s": 25.0, "offset_nominal_s": 24.5, "samples": 3,
                    "observed_at_epoch_s": 1000.0, "validity_seconds": 3600.0}
            self.write_clock(directory, dict(base, host_ntp_synchronized=True))
            synchronized = watch.read_clock_domain(directory, "note3", 1000.0)
            self.write_clock(directory, dict(base, host_ntp_synchronized=False))
            unsynchronized = watch.read_clock_domain(directory, "note3", 1000.0)
            self.write_clock(directory, base)
            omitted = watch.read_clock_domain(directory, "note3", 1000.0)
            self.write_clock(directory, dict(base, host_ntp_synchronized="yes"))
            non_boolean = watch.read_clock_domain(directory, "note3", 1000.0)
            expired = watch.read_clock_domain(directory, "note3", 1000.0 + 3601)
            self.write_clock(directory, {"node": "note3", "status": "unavailable"})
            unavailable = watch.read_clock_domain(directory, "note3", 1000.0)
        self.assertIs(synchronized["host_ntp_synchronized"], True)
        self.assertIs(unsynchronized["host_ntp_synchronized"], False)
        self.assertIsNone(omitted["host_ntp_synchronized"])
        self.assertIsNone(non_boolean["host_ntp_synchronized"])
        self.assertEqual(expired["status"], "stale")
        self.assertIsNone(expired["host_ntp_synchronized"])
        self.assertEqual(unavailable["status"], "invalid")
        self.assertIsNone(unavailable["host_ntp_synchronized"])

    def test_an_identity_that_could_forge_a_pane_line_is_dropped(self):
        # The document can be written by hand as well as by the producer, and the pane
        # is a rendered surface: an identity carrying a newline or an escape sequence
        # must not become a line of its own.
        state = self.state()
        with tempfile.TemporaryDirectory() as folder:
            directory = Path(folder) / "perception"
            directory.mkdir()
            watch.save(directory / "note3.json", state)
            self.write_clock(directory, {
                "node": "note3", "status": "ok", "offset_min_s": 24.0,
                "offset_max_s": 25.0, "offset_nominal_s": 24.5, "samples": 7,
                "observed_at_epoch_s": 1000.0, "validity_seconds": 3600.0,
                "device_serial": "4d00553d61ab90b7\nclock-domain alarm: stepped -22.4s",
                "device_model": "\x1b[2J" + "M" * 65})
            clock = watch.read_clock_domain(directory, "note3", 1000.0)
        self.assertEqual((clock["device_serial"], clock["device_model"]), (None, None))
        view = watch.render(state, 1024, 30, None, clock)
        self.assertNotIn("clock-domain provenance", view)
        self.assertNotIn("\x1b", view)

    def test_render_shows_the_measured_device_of_a_clock_domain_reading(self):
        state = self.state()
        self.page(state, ["1000 hello node=note3 protocol=1 session=s1",
                          "1000 light lux=12.5 accuracy=3 age_ms=21"], received=1024)
        base = {"status": "ok", "offset_min_s": 24.0, "offset_max_s": 25.0,
                "offset_nominal_s": 24.5, "age_s": 12.0, "samples": 7, "jump": None}
        self.assertNotIn("clock-domain provenance", watch.render(state, 1024, 30, None, base))
        named = dict(base, device_serial="4d00553d61ab90b7", device_model="SM-N900")
        self.assertIn("clock-domain provenance: measured on SM-N900 "
                      "(device_serial=4d00553d61ab90b7)",
                      watch.render(state, 1024, 30, None, named))
        self.assertIn("clock-domain provenance",
                      watch.render_events(state, 1024, 30, None, named))
        # A document that names only one of the two still reports what it has.
        partial = dict(base, device_serial="4d00553d61ab90b7")
        self.assertIn("measured on unknown model",
                      watch.render(state, 1024, 30, None, partial))

    def test_clock_agreement_resolves_the_split_only_with_a_fresh_measurement(self):
        spans = {"min_ms": 26900.0, "max_ms": 28968.0, "median_ms": 27000.0, "n": 30}
        self.assertEqual(watch.clock_agreement_reason(spans),
                         "phone/host clock skew <=26900ms behind host (acquisition span "
                         "26900-28968ms, n=30 retained); skew/latency split unknown")
        clock = {"status": "ok", "offset_min_s": 24.0, "offset_max_s": 25.0,
                 "offset_nominal_s": 25.4, "age_s": 12.0, "samples": 7,
                 "host_ntp_synchronized": False}
        self.assertEqual(watch.clock_agreement_reason(spans, clock),
                         "phone/host clock skew <=26900ms behind host (acquisition span "
                         "26900-28968ms, n=30 retained); measured phone/host offset "
                         "+25.4s behind host (age 12s, n=7, bounds +24.0..+25.0s, "
                         "host_ntp_synchronized=false: the host clock is itself "
                         "unsynchronized, so part of this offset is host error, not a "
                         "measured phone error) resolves the split: implied transport "
                         "latency 1.9-5.0s")

    def test_clock_agreement_names_a_measurement_that_conflicts_with_the_span_bound(self):
        spans = {"min_ms": 26900.0, "max_ms": 28968.0, "median_ms": 27000.0, "n": 30}
        clock = {"status": "ok", "offset_min_s": 30.0, "offset_max_s": 31.0,
                 "offset_nominal_s": 30.5, "age_s": 1.0, "samples": 7}
        reason = watch.clock_agreement_reason(spans, clock)
        self.assertIn("conflicts with the span bound", reason)
        self.assertIn("split unresolved", reason)

    def test_clock_agreement_names_the_host_side_of_the_measured_offset(self):
        # The offset is host-minus-phone, so without the producer's own host-NTP
        # verdict a reader takes the whole number for a phone defect (health DM 105987).
        spans = {"min_ms": 26900.0, "max_ms": 28968.0, "median_ms": 27000.0, "n": 30}
        base = {"status": "ok", "offset_min_s": 24.0, "offset_max_s": 25.0,
                "offset_nominal_s": 24.8, "age_s": 44.0, "samples": 3}
        synchronized = watch.clock_agreement_reason(
            spans, dict(base, host_ntp_synchronized=True))
        self.assertIn("host_ntp_synchronized=true", synchronized)
        self.assertIn("attributable to the phone", synchronized)
        unsynchronized = watch.clock_agreement_reason(
            spans, dict(base, host_ntp_synchronized=False))
        self.assertIn("host_ntp_synchronized=false", unsynchronized)
        self.assertIn("part of this offset is host error, not a measured phone error",
                      unsynchronized)
        # Absent, unreadable or non-boolean stays unknown, never synchronized.
        for missing in (base, dict(base, host_ntp_synchronized=None),
                        dict(base, host_ntp_synchronized="yes"),
                        dict(base, host_ntp_synchronized=1)):
            reason = watch.clock_agreement_reason(spans, missing)
            self.assertIn("host_ntp_synchronized unknown", reason)
            self.assertNotIn("host_ntp_synchronized=true", reason)
        # No measurement at all: no offset is claimed, so no host clause is invented.
        self.assertNotIn("host_ntp_synchronized", watch.clock_agreement_reason(spans))

    def test_the_pane_and_space_publish_the_host_ntp_attribution(self):
        # Consumer-visible: the same clause reaches the raw-units pane line and the
        # space.json light status_reason, not only the in-process helper.
        state = self.state()
        self.page(state, ["1000 hello node=note3 protocol=1 session=s1",
                          "1000 light lux=12.5 accuracy=3 age_ms=21"], received=1024)
        self.page(state, ["1001 light lux=12.5 accuracy=3 age_ms=21"], received=1026)
        clock = {"status": "ok", "offset_min_s": 24.0, "offset_max_s": 25.0,
                 "offset_nominal_s": 24.8, "observed_at_epoch_s": 1020.0, "age_s": 12.0,
                 "samples": 3, "source": "tools/clock_offset.py",
                 "validity_seconds": 3600.0, "jump": None, "reason": None,
                 "host_ntp_synchronized": False}
        view = watch.render(state, 1024, 30, None, clock)
        self.assertIn("host_ntp_synchronized=false", view)
        self.assertIn("part of this offset is host error, not a measured phone error",
                      view)
        node = watch.space_snapshot([state], 1026, 30,
                                    clocks={"note3": clock})["nodes"][0]["light"]
        self.assertIn("host_ntp_synchronized=false", node["status_reason"])

    def test_space_snapshot_light_reason_carries_the_resolved_split(self):
        state = self.state()
        self.page(state, ["1000 hello node=note3 protocol=1 session=s1",
                          "1000 light lux=12.5 accuracy=3 age_ms=21"], received=1024)
        self.page(state, ["1001 light lux=12.5 accuracy=3 age_ms=21"], received=1026)
        clock = {"status": "ok", "offset_min_s": 19.0, "offset_max_s": 20.0,
                 "offset_nominal_s": 19.6, "observed_at_epoch_s": 1020.0,
                 "age_s": 12.0, "samples": 7, "source": "tools/clock_offset.py",
                 "validity_seconds": 3600.0, "jump": None, "reason": None}
        node = watch.space_snapshot([state], 1026, 30,
                                    clocks={"note3": clock})["nodes"][0]["light"]
        self.assertEqual(node["status"], "fresh-clock-conditional")
        self.assertIn("resolves the split", node["status_reason"])
        unmeasured = watch.space_snapshot([state], 1026, 30)["nodes"][0]["light"]
        self.assertIn("skew/latency split unknown", unmeasured["status_reason"])

    def test_render_shows_a_clock_domain_alarm_only_on_a_measured_step(self):
        state = self.state()
        self.page(state, ["1000 hello node=note3 protocol=1 session=s1",
                          "1000 light lux=12.5 accuracy=3 age_ms=21"], received=1024)
        base = {"status": "ok", "offset_min_s": 24.0, "offset_max_s": 25.0,
                "offset_nominal_s": 25.4, "age_s": 12.0, "samples": 7, "jump": None}
        self.assertNotIn("clock-domain alarm", watch.render(state, 1024, 30, None, base))
        stepped = dict(base, jump={"previous_offset_nominal_s": 25.4,
                                   "previous_observed_at_epoch_s": 1000.0,
                                   "delta_s": -22.4, "threshold_s": 2.0})
        view = watch.render(state, 1024, 30, None, stepped)
        self.assertIn("clock-domain alarm: measured phone/host offset stepped -22.4s", view)
        self.assertIn("not comparable across the step", view)
        # The compact view accepts the same argument (a jump must not crash the cached render).
        self.assertIn("clock-domain alarm", watch.render_events(state, 1024, 30, None, stepped))


class SpoolCoverageVerdictTests(unittest.TestCase):
    """The co-count verdict separates collector silence from per-channel failure.

    Discover 81112 measured the five per-cycle kinds exactly co-counted on
    Note3 (one row each per ~5 s cycle). The verdict is derived consumer-side
    from the spool summary's per-kind counts; no phone request is made.
    """

    def _counts(self, **overrides):
        counts = {kind: 100 for kind in watch.SPOOL_COVERAGE_KINDS}
        counts.update(overrides)
        return counts

    def test_co_counted_kinds_are_ok(self):
        self.assertEqual(watch.spool_coverage_verdict(self._counts()),
                         "coverage=ok")

    def test_skew_within_bound_is_ok(self):
        counts = self._counts()
        counts["light"] = 96
        counts["wifi_link_rssi"] = 101
        self.assertEqual(watch.spool_coverage_verdict(counts), "coverage=ok")

    def test_stopped_channel_is_divergent_with_each_count(self):
        verdict = watch.spool_coverage_verdict(self._counts(light=0))
        self.assertTrue(verdict.startswith("coverage=divergent "))
        self.assertIn("light=0", verdict)
        self.assertIn("ble_status=100", verdict)
        self.assertIn("wifi_link_rssi=100", verdict)

    def test_all_zero_window_is_no_rows_not_ok(self):
        counts = {kind: 0 for kind in watch.SPOOL_COVERAGE_KINDS}
        self.assertEqual(watch.spool_coverage_verdict(counts),
                         "coverage=no-rows")

    def test_missing_counts_are_no_rows(self):
        self.assertEqual(watch.spool_coverage_verdict({}), "coverage=no-rows")

    def test_sighting_kind_is_not_part_of_the_per_cycle_set(self):
        # ble_sighting is emitted only while ON; under collect-only it stays 0
        # while the collector is alive, so it must not trigger divergence.
        self.assertNotIn("ble_sighting", watch.SPOOL_COVERAGE_KINDS)

    def test_view_line_reports_faint_bucket_and_coverage(self):
        spool = {"status": "ok", "spool_bytes": 2634665,
                 "retention_window_s": 18180.0,
                 "counts": self._counts(),
                 "light_buckets": {"dark_exact": 87, "faint_0_1": 0,
                                   "dim_0_9": 3500, "moderate_10_99": 0,
                                   "bright_100_999": 0,
                                   "very_bright_1000_plus": 0},
                 "age_s": 12.3}
        line = watch.spool_view_line(spool)
        self.assertIn("coverage=ok", line)
        self.assertIn("faint=0", line)
        self.assertIn("dark=87", line)
        self.assertIn("NOT delivered", line)

    def test_view_line_without_spool_is_none(self):
        self.assertIsNone(watch.spool_view_line(None))

    def test_view_line_unavailable_stays_never_calm(self):
        spool = {"status": "unavailable", "reason": "spool-read-failed"}
        line = watch.spool_view_line(spool)
        self.assertIn("status=unavailable", line)
        self.assertIn("never calm", line)
        self.assertNotIn("coverage", line)

    def test_view_line_reports_cumulative_eviction_loss(self):
        """A live collector with a stale consumer is NOT lossless: bounded
        retention already discarded the undelivered backlog, so the loss term
        is rendered, not hidden by the coverage verdict (discover 81710)."""
        spool = {"status": "ok", "spool_bytes": 3227302,
                 "retention_window_s": 21292.0,
                 "counts": self._counts(),
                 "light_buckets": {"dark_exact": 3082, "faint_0_1": 0,
                                   "dim_0_9": 1121, "moderate_10_99": 0,
                                   "bright_100_999": 0,
                                   "very_bright_1000_plus": 0},
                 "overflow": {"dropped": 108040, "notice_epoch_s": 1792050926},
                 "age_s": 212.6}
        line = watch.spool_view_line(spool)
        self.assertIn("overflow=cumulative-dropped=108,040", line)
        self.assertIn("coverage=ok", line)

    def test_view_line_shows_a_never_evicted_spool_as_a_truthful_zero(self):
        spool = {"status": "ok", "spool_bytes": 2634665,
                 "retention_window_s": 18180.0,
                 "counts": self._counts(),
                 "light_buckets": {"dark_exact": 87, "faint_0_1": 0,
                                   "dim_0_9": 3500, "moderate_10_99": 0,
                                   "bright_100_999": 0,
                                   "very_bright_1000_plus": 0},
                 "overflow": {"dropped": 0, "notice_epoch_s": None},
                 "age_s": 12.3}
        self.assertIn("overflow=cumulative-dropped=0",
                      watch.spool_view_line(spool))

    def test_view_line_marks_an_absent_loss_field_unknown_not_zero(self):
        """Publisher and consumer are activated separately: a spool summary
        published before this field existed carries no overflow key, and that
        must not render as "nothing evicted"."""
        spool = {"status": "ok", "spool_bytes": 2634665,
                 "retention_window_s": 18180.0,
                 "counts": self._counts(),
                 "light_buckets": {"dark_exact": 87, "faint_0_1": 0,
                                   "dim_0_9": 3500, "moderate_10_99": 0,
                                   "bright_100_999": 0,
                                   "very_bright_1000_plus": 0},
                 "age_s": 12.3}
        line = watch.spool_view_line(spool)
        self.assertIn("overflow=unknown", line)
        self.assertNotIn("cumulative-dropped", line)

    def test_view_line_ignores_a_malformed_loss_field(self):
        for bad in ({"dropped": "106097"}, {"dropped": -1}, {"dropped": None},
                    {"dropped": 1.5}, "dropped", {}):
            spool = {"status": "ok", "spool_bytes": 2634665,
                     "retention_window_s": 18180.0,
                     "counts": self._counts(),
                     "light_buckets": {"dark_exact": 87, "faint_0_1": 0,
                                       "dim_0_9": 3500, "moderate_10_99": 0,
                                       "bright_100_999": 0,
                                       "very_bright_1000_plus": 0},
                     "overflow": bad, "age_s": 12.3}
            self.assertIn("overflow=unknown", watch.spool_view_line(spool), bad)


class SpoolScanStateTests(unittest.TestCase):
    """The collection-side scan-state segment is labelled, honest and bounded."""

    ROW = {"epoch_s": 1792061943, "windows": 23, "phase": "gap",
           "last_error": "none", "sightings": 0,
           "window_ms": 60000, "gap_ms": 60000}

    # Bounds deliberately distinct from the nominal: a regression that reads
    # offset_min_s/offset_max_s instead of offset_nominal_s must change the age.
    CLOCK = {"status": "ok", "offset_min_s": 24.0, "offset_max_s": 25.0,
             "offset_nominal_s": 25.6, "observed_at_epoch_s": 1792061900.0,
             "age_s": 7.5, "samples": 3, "jump": None, "reason": None}

    def test_row_age_is_host_domain_not_the_bare_phone_epoch_difference(self):
        # 1792061943 is a PHONE stamp and the host is 25.6 s ahead of the phone, so
        # a row written 4 s ago must read 4 s -- not the 29.6 s that a bare
        # ``now - epoch_s`` gives and that made live windows look stale.
        now = 1792061943 + 25.6 + 4.0
        self.assertIn("row_age=4s",
                      watch.spool_scan_state_segment(True, self.ROW, now, self.CLOCK))

    def test_row_age_is_unknown_without_a_resolved_clock_domain(self):
        self.assertIn("row_age=unknown(no-reference-time)",
                      watch.spool_scan_state_segment(True, self.ROW))
        self.assertIn("row_age=unknown(clock-domain-unresolved)",
                      watch.spool_scan_state_segment(True, self.ROW, 1792062000.0, None))
        for clock, reason in (
                ({"status": "stale"}, "clock-domain-unresolved"),
                ({"status": "absent"}, "clock-domain-unresolved"),
                ({"status": "invalid"}, "clock-domain-unresolved"),
                (dict(self.CLOCK, jump={"delta_s": 5.0}), "clock-domain-jump"),
                ({"status": "ok", "offset_nominal_s": None,
                  "offset_min_s": 24.0, "offset_max_s": 25.0}, "clock-domain-invalid"),
                ({"status": "ok", "offset_nominal_s": True,
                  "offset_min_s": 24.0, "offset_max_s": 25.0}, "clock-domain-invalid"),
                ({"status": "ok", "offset_nominal_s": 25.6,
                  "offset_min_s": 26.0, "offset_max_s": 25.0}, "clock-domain-invalid")):
            self.assertIn(f"row_age=unknown({reason})",
                          watch.spool_scan_state_segment(True, self.ROW, 1792062000.0, clock),
                          reason)

    def test_row_age_clamps_a_marginally_early_stamp_instead_of_accusing_it(self):
        # offset_nominal_s is the interval midpoint and can overstate the true
        # offset by up to offset_nominal_s - offset_min_s (1.6 s here), so a
        # row stamped inside that band is fresh, not future.
        now = 1792061943 + 25.6 - 0.5
        self.assertIn("row_age=0s",
                      watch.spool_scan_state_segment(True, self.ROW, now, self.CLOCK))

    def test_row_age_survives_an_unvalidated_epoch_from_the_summary(self):
        # epoch_s is passed through from the summary document unvalidated, and
        # math.isfinite raises OverflowError on an int too large for a float.
        for epoch in (10 ** 400, float("nan"), float("inf"), "1792061943", True):
            self.assertIn("row_age=unknown(no-row-epoch)",
                          watch.spool_scan_state_segment(
                              True, dict(self.ROW, epoch_s=epoch), 1792062000.0, self.CLOCK),
                          epoch)

    def test_row_age_is_unknown_without_a_row_epoch(self):
        row = {key: value for key, value in self.ROW.items() if key != "epoch_s"}
        self.assertIn("row_age=unknown(no-row-epoch)",
                      watch.spool_scan_state_segment(True, row, 1792062000.0, self.CLOCK))

    def test_row_age_flags_a_row_stamped_far_after_the_host(self):
        now = 1792061943 + 25.6 - 5.0
        self.assertIn("row_age=unknown(row-epoch-in-future)",
                      watch.spool_scan_state_segment(True, self.ROW, now, self.CLOCK))

    def test_row_lag_names_how_long_before_the_summary_the_row_was_written(self):
        # The sampler lane re-stamps the row every 5 s, so a live lane leaves the
        # row only seconds older than the summary; the lag is what separates the
        # reader cadence from a stopped sampler (2026-10-16 correction).
        live = watch.spool_scan_state_segment(
            True, self.ROW, 1792061943 + 25.6 + 300.0, self.CLOCK, 298.0)
        self.assertIn("row_age=300s (row written 2s before the summary)", live)
        stopped = watch.spool_scan_state_segment(
            True, self.ROW, 1792061943 + 25.6 + 1200.0, self.CLOCK, 298.0)
        self.assertIn("row_age=1200s (row written 902s before the summary)", stopped)

    def test_row_lag_degrades_to_the_bare_row_age_without_a_usable_summary_age(self):
        # A missing or malformed summary age must not invent a lag, and a huge
        # int must not raise OverflowError out of math.isfinite.
        for bad in (None, -1.0, True, "5", float("nan"), float("inf"), 10 ** 400):
            segment = watch.spool_scan_state_segment(
                True, self.ROW, 1792061943 + 25.6 + 4.0, self.CLOCK, bad)
            self.assertIn("row_age=4s", segment, bad)
            self.assertNotIn("before the summary", segment, bad)

    def test_view_line_carries_the_row_lag(self):
        spool = {"status": "ok", "spool_bytes": 3130966,
                 "retention_window_s": 20431.0,
                 "counts": {kind: 100 for kind in watch.SPOOL_COVERAGE_KINDS},
                 "light_buckets": {"dark_exact": 1, "faint_0_1": 0,
                                   "dim_0_9": 1, "moderate_10_99": 0,
                                   "bright_100_999": 0,
                                   "very_bright_1000_plus": 0},
                 "overflow": {"dropped": 0, "notice_epoch_s": None},
                 "scan_state": self.ROW, "scan_state_present": True, "age_s": 5.0}
        line = watch.spool_view_line(spool, 1792061943 + 25.6 + 4.0, self.CLOCK)
        self.assertIn("row_age=4s (row written 0s before the summary)", line)

    def test_view_line_keeps_the_summary_age_and_the_row_age_distinct(self):
        spool = {"status": "ok", "spool_bytes": 3130966,
                 "retention_window_s": 20431.0,
                 "counts": {kind: 100 for kind in watch.SPOOL_COVERAGE_KINDS},
                 "light_buckets": {"dark_exact": 1, "faint_0_1": 0,
                                   "dim_0_9": 1, "moderate_10_99": 0,
                                   "bright_100_999": 0,
                                   "very_bright_1000_plus": 0},
                 "overflow": {"dropped": 0, "notice_epoch_s": None},
                 "scan_state": self.ROW, "scan_state_present": True, "age_s": 5.0}
        line = watch.spool_view_line(spool, 1792061943 + 25.6 + 4.0, self.CLOCK)
        self.assertIn("age=5.0s", line)
        self.assertIn("row_age=4s", line)

    def test_segment_absent_row_is_none_retained(self):
        self.assertEqual(watch.spool_scan_state_segment(True, None),
                         " scan_state=none-retained")

    def test_segment_absent_field_is_field_absent(self):
        # A document that predates the field is not a none-retained row; the
        # two must not collapse into one reading.
        self.assertEqual(watch.spool_scan_state_segment(False, None),
                         " scan_state=unknown/field-absent")

    def test_segment_renders_the_bounded_fields(self):
        segment = watch.spool_scan_state_segment(True, self.ROW)
        self.assertIn("scan_state(windows=23", segment)
        self.assertIn("phase=gap", segment)
        self.assertIn("last_error=none", segment)
        self.assertIn("sightings=0", segment)
        self.assertIn("window_ms=60000", segment)
        self.assertIn("gap_ms=60000", segment)

    def test_segment_renders_a_spaced_failure_reason(self):
        row = dict(self.ROW, windows=28, phase="none",
                   last_error="scan_failed code=2")
        self.assertIn("last_error=scan_failed code=2",
                      watch.spool_scan_state_segment(True, row))

    def test_segment_marks_a_malformed_row_invalid(self):
        for bad in ({"phase": "scanning", "windows": 1, "sightings": 0,
                     "last_error": "none"},
                    {"phase": "gap", "windows": "23", "sightings": 0,
                     "last_error": "none"},
                    {"phase": "gap", "windows": True, "sightings": 0,
                     "last_error": "none"},
                    {"phase": "gap", "windows": 1, "sightings": 0},
                    {"phase": "gap", "windows": 1, "sightings": 0,
                     "last_error": "none", "window_ms": "60000",
                     "gap_ms": 60000},
                    {"phase": "gap", "windows": 1, "sightings": 0,
                     "last_error": "none", "window_ms": -1, "gap_ms": 60000},
                    {"phase": "gap", "windows": 1, "sightings": 0,
                     "last_error": "none", "window_ms": True,
                     "gap_ms": 60000},
                    {"phase": "gap", "windows": 1, "sightings": 0,
                     "last_error": "none", "window_ms": 60000},
                    "windows=1"):
            self.assertEqual(watch.spool_scan_state_segment(True, bad),
                             " scan_state=invalid", bad)

    def test_view_line_appends_the_scan_state_inside_the_collection_side_line(self):
        spool = {"status": "ok", "spool_bytes": 3130966,
                 "retention_window_s": 20431.0,
                 "counts": {kind: 100 for kind in watch.SPOOL_COVERAGE_KINDS},
                 "light_buckets": {"dark_exact": 1, "faint_0_1": 0,
                                   "dim_0_9": 1, "moderate_10_99": 0,
                                   "bright_100_999": 0,
                                   "very_bright_1000_plus": 0},
                 "overflow": {"dropped": 0, "notice_epoch_s": None},
                 "scan_state": self.ROW, "scan_state_present": True, "age_s": 5.0}
        line = watch.spool_view_line(spool)
        self.assertIn("NOT delivered", line)
        self.assertIn("scan_state(windows=23 phase=gap last_error=none sightings=0 "
                      "window_ms=60000 gap_ms=60000)", line)

    def test_view_line_with_a_present_null_row_says_none_retained(self):
        spool = {"status": "ok", "spool_bytes": 3130966,
                 "retention_window_s": 20431.0,
                 "counts": {kind: 100 for kind in watch.SPOOL_COVERAGE_KINDS},
                 "light_buckets": {"dark_exact": 1, "faint_0_1": 0,
                                   "dim_0_9": 1, "moderate_10_99": 0,
                                   "bright_100_999": 0,
                                   "very_bright_1000_plus": 0},
                 "overflow": {"dropped": 0, "notice_epoch_s": None},
                 "scan_state": None, "scan_state_present": True, "age_s": 5.0}
        self.assertIn("scan_state=none-retained", watch.spool_view_line(spool))

    def test_view_line_without_the_field_says_field_absent(self):
        spool = {"status": "ok", "spool_bytes": 3130966,
                 "retention_window_s": 20431.0,
                 "counts": {kind: 100 for kind in watch.SPOOL_COVERAGE_KINDS},
                 "light_buckets": {"dark_exact": 1, "faint_0_1": 0,
                                   "dim_0_9": 1, "moderate_10_99": 0,
                                   "bright_100_999": 0,
                                   "very_bright_1000_plus": 0},
                 "overflow": {"dropped": 0, "notice_epoch_s": None},
                 "scan_state_present": False, "age_s": 5.0}
        self.assertIn("scan_state=unknown/field-absent",
                      watch.spool_view_line(spool))

    def test_read_spool_summary_passes_the_scan_state_through(self):
        import json
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp) / "body" / "perception"
            directory.mkdir(parents=True)
            (Path(tmp) / "body" / "spool-summary-note3.json").write_text(json.dumps({
                "node": "note3", "source": "tools/spool_read.py",
                "status": "ok", "observed_at_epoch_s": 1792061907.5,
                "validity_seconds": 300.0, "spool_bytes": 3130966,
                "retention_window_s": 20431.0, "oldest_row_epoch_s": 1792041446,
                "newest_row_epoch_s": 1792061877, "counts": {"light": 4031},
                "light_buckets": {"dark_exact": 563}, "overflow": {
                    "dropped": 119348, "notice_epoch_s": 1792061882},
                "scan_state": self.ROW, "reason": None}), encoding="utf-8")
            spool = watch.read_spool_summary(directory, "note3", 1792061908.0)
        self.assertEqual(spool["status"], "ok")
        self.assertEqual(spool["scan_state"], self.ROW)
        self.assertTrue(spool["scan_state_present"])

    def test_read_spool_summary_unknown_states_carry_a_null_scan_state(self):
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp) / "body" / "perception"
            directory.mkdir(parents=True)
            spool = watch.read_spool_summary(directory, "note3", 1792061908.0)
        self.assertEqual(spool["status"], "absent")
        self.assertIsNone(spool["scan_state"])

    def test_read_spool_summary_without_the_field_is_field_absent(self):
        # The flag separating field-absent from none-retained is derived from the
        # document's own key set; pin it on the absent side too.
        import json
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp) / "body" / "perception"
            directory.mkdir(parents=True)
            (Path(tmp) / "body" / "spool-summary-note3.json").write_text(json.dumps({
                "node": "note3", "source": "tools/spool_read.py",
                "status": "ok", "observed_at_epoch_s": 1792061907.5,
                "validity_seconds": 300.0, "spool_bytes": 3130966,
                "retention_window_s": 20431.0, "oldest_row_epoch_s": 1792041446,
                "newest_row_epoch_s": 1792061877, "counts": {"light": 4031},
                "light_buckets": {"dark_exact": 563}, "overflow": {
                    "dropped": 119348, "notice_epoch_s": 1792061882},
                "reason": None}), encoding="utf-8")
            spool = watch.read_spool_summary(directory, "note3", 1792061908.0)
        self.assertEqual(spool["status"], "ok")
        self.assertIsNone(spool["scan_state"])
        self.assertFalse(spool["scan_state_present"])
        self.assertIn("scan_state=unknown/field-absent",
                      watch.spool_view_line(spool))

if __name__ == "__main__":
    unittest.main()
