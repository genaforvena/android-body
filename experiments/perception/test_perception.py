"""Deterministic consumer-visible boundaries; no phone or physical requests."""
import json
import tempfile
import time
import unittest
from pathlib import Path

import watch


class PerceptionTests(unittest.TestCase):
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
        self.assertIn("stale/phone-silent-or-delayed", watch.render(state, 1000, 30))
        self.assertNotIn("magnitude=3.742", watch.render(state, 1000, 30))
        self.page(state, ["1001 battery level=0.5 charging=true",
                          "1001 acceleration x=0 y=0 z=10 age_ms=0"], received=1001)
        self.assertIn("acceleration magnitude=10.000 m/s²", watch.render(state, 1001, 30))

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
        self.assertEqual(node["light"]["validity_seconds"], 30)
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
        self.page(state, ["1100 acceleration x=0 y=0 z=10 age_ms=0"])
        self.assertIn("unknown-clock-future", watch.render(state, 1000, 30))
        self.assertNotIn("magnitude=10.000", watch.render(state, 1000, 30))
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

    def test_ble_sighting_and_scan_lifecycle_are_readable_evidence_without_presence_claim(self):
        state = self.state()
        self.page(state, ["1000 hello node=note3 protocol=1 session=s1",
                          "1000 ble_scan start beacon=MISHE-BEACON window_ms=60000 gap_ms=60000",
                          "1000 ble_sighting name=MISHE-BEACON rssi=-62"], received=1000)
        view = watch.render(state, 1000, 30)
        self.assertIn("#2 1000 ble_scan start beacon=MISHE-BEACON window_ms=60000 gap_ms=60000", view)
        self.assertIn("#3 1000 ble_sighting name=MISHE-BEACON rssi=-62", view)
        self.assertIn("sightings_in_history_window=1", view)
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

    def test_ble_rf_channels_stay_honest_unknown_without_observations(self):
        state = self.state()
        self.page(state, ["1000 hello node=note3 protocol=1 session=s1"], received=1000)
        view = watch.render(state, 1000, 30)
        self.assertIn("status=unknown/no-observation", view)
        self.assertIn("sightings_in_history_window=0", view)
        self.assertIn("scan_lifecycle status=unknown/no-observation latest=unknown "
                      "reason=unspecified", view)
        node = watch.space_snapshot([state], 1000, 30)["nodes"][0]
        self.assertEqual(node["ble_sighting"]["status"], "unknown/no-observation")
        self.assertIsNone(node["ble_sighting"]["rssi_dbm"])
        self.assertEqual(node["ble_scan"]["status"], "unknown/no-observation")
        self.assertIsNone(node["ble_scan"]["subtype"])

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

    def test_class_b_detector_fires_on_cursor_freeze_with_null_lux(self):
        state = self.state()
        with tempfile.TemporaryDirectory() as folder:
            log_dir = Path(folder)
            # Session s1: two null-lux reads
            self.page(state, ["1000 hello node=note3 protocol=1 session=s1",
                              "1000 light lux=0 accuracy=3 age_ms=0 phone_elapsed_ms=1000",
                              "1000 light lux=0 accuracy=3 age_ms=0 phone_elapsed_ms=2000"],
                      received=1000, log_dir=log_dir)
            # First call seeds prev state
            watch.detect_class_b_stop(state, log_dir)
            # Simulate cursor frozen for > CLASS_B_FREEZE_SECONDS
            state["_class_b_last_cursor_advance_at"] = time.time() - watch.CLASS_B_FREEZE_SECONDS - 1
            # Second poll: cursor frozen, still null-lux
            detection = watch.detect_class_b_stop(state, log_dir)
            self.assertIsNotNone(detection)
            self.assertEqual(detection["trigger"], "cursor-freeze")
            self.assertEqual(detection["null_lux_consecutive"], 2)
            self.assertEqual(detection["cursor"], state["cursor"])

    def test_class_b_detector_fires_on_session_change_with_null_lux(self):
        state = self.state()
        with tempfile.TemporaryDirectory() as folder:
            log_dir = Path(folder)
            # Session s1 with null-lux
            self.page(state, ["1000 hello node=note3 protocol=1 session=s1",
                              "1000 light lux=0 accuracy=3 age_ms=0 phone_elapsed_ms=1000"],
                      received=1000, log_dir=log_dir)
            watch.detect_class_b_stop(state, log_dir)
            # Session s2 with null-lux (session change)
            # Session s2 with 2 null-lux reads (session change)
            self.page(state, ["1000 hello node=note3 protocol=1 session=s2",
                              "1000 light lux=0 accuracy=3 age_ms=0 phone_elapsed_ms=2000",
                              "1000 light lux=0 accuracy=3 age_ms=0 phone_elapsed_ms=3000"],
                      received=1001, log_dir=log_dir)
            detection = watch.detect_class_b_stop(state, log_dir)
            self.assertIsNotNone(detection)
            self.assertEqual(detection["trigger"], "session-change")
            self.assertEqual(detection["null_lux_consecutive"], 2)

    def test_class_b_detector_silent_without_null_lux(self):
        state = self.state()
        with tempfile.TemporaryDirectory() as folder:
            log_dir = Path(folder)
            # Session s1: non-null-lux
            self.page(state, ["1000 hello node=note3 protocol=1 session=s1",
                              "1000 light lux=12.5 accuracy=3 age_ms=0 phone_elapsed_ms=1000"],
                      received=1000, log_dir=log_dir)
            watch.detect_class_b_stop(state, log_dir)
            # Cursor frozen but no null-lux
            detection = watch.detect_class_b_stop(state, log_dir)
            self.assertIsNone(detection)

    def test_class_b_detector_no_repeat_for_same_cursor_session(self):
        state = self.state()
        with tempfile.TemporaryDirectory() as folder:
            log_dir = Path(folder)
            self.page(state, ["1000 hello node=note3 protocol=1 session=s1",
                              "1000 light lux=0 accuracy=3 age_ms=0 phone_elapsed_ms=1000",
                              "1000 light lux=0 accuracy=3 age_ms=0 phone_elapsed_ms=2000"],
                      received=1000, log_dir=log_dir)
            watch.detect_class_b_stop(state, log_dir)
            # Simulate cursor frozen for > CLASS_B_FREEZE_SECONDS
            state["_class_b_last_cursor_advance_at"] = time.time() - watch.CLASS_B_FREEZE_SECONDS - 1
            detection1 = watch.detect_class_b_stop(state, log_dir)
            self.assertIsNotNone(detection1)
            # Same cursor/session: no repeat
            detection2 = watch.detect_class_b_stop(state, log_dir)
            self.assertIsNone(detection2)

    def test_class_b_detector_bounded_output(self):
        state = self.state()
        with tempfile.TemporaryDirectory() as folder:
            log_dir = Path(folder)
            # Generate CLASS_B_DETECTOR_LINES + 5 detections
            for i in range(watch.CLASS_B_DETECTOR_LINES + 5):
                state["cursor"] = 100 + i
                state["session"] = f"s{i}"
                state["history"] = [{"kind": "light", "fields": {"lux": 0.0}},
                                     {"kind": "light", "fields": {"lux": 0.0}}]
                state.pop("_class_b_detected_cursor", None)
                state.pop("_class_b_detected_session", None)
                watch.detect_class_b_stop(state, log_dir)
            path = log_dir / "class-b-detectors.jsonl"
            lines = path.read_text(encoding="utf-8").strip().split("\n")
            self.assertEqual(len(lines), watch.CLASS_B_DETECTOR_LINES)

    def test_class_b_detector_no_false_positive_on_advancing_cursor(self):
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
            watch.detect_class_b_stop(state, log_dir)
            # Simulate cursor advancing +4 per poll (like real Note3 scenario)
            # Each poll is 2s apart, cursor advances every ~5 polls (~10s)
            # After 3 polls: cursor should have advanced at least once
            state["cursor"] = 1004  # advanced +4
            detection = watch.detect_class_b_stop(state, log_dir)
            self.assertIsNone(detection)
            # Continue advancing: cursor keeps moving, no freeze
            state["cursor"] = 1008  # advanced +4 again
            detection = watch.detect_class_b_stop(state, log_dir)
            self.assertIsNone(detection)
            # Even after many polls with null-lux, advancing cursor = no freeze
            for i in range(10):
                state["cursor"] = 1008 + (i + 1) * 4
                detection = watch.detect_class_b_stop(state, log_dir)
                self.assertIsNone(detection)

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

if __name__ == "__main__":
    unittest.main()
