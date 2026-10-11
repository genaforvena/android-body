"""Deterministic consumer-visible boundaries; no phone or physical requests."""
import tempfile
import unittest
from pathlib import Path

import watch


class PerceptionTests(unittest.TestCase):
    def state(self):
        return watch.initial("note3", "http://127.0.0.1:8765/node/note3")

    def page(self, state, lines, received=1000, more=False):
        body = "".join(f"{state['cursor'] + offset} {line}\n"
                       for offset, line in enumerate(lines, 1)).encode()
        watch.apply_page(state, watch.parse_page(body, state["cursor"]), received, more)

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
        self.assertIsNone(node["light"]["host_receipt_monotonic_ns"])
        self.assertIsNone(node["light"]["server_receipt_utc"])
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


if __name__ == "__main__":
    unittest.main()
