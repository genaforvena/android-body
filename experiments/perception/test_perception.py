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

    def test_invalid_page_cannot_advance_checkpoint(self):
        state = self.state()
        with self.assertRaises(ValueError):
            self.page(state, ["1000 battery level=0.5", "bad\tcontrol"])
        self.assertEqual(state["cursor"], 0)
        self.assertEqual(state["history"], [])


if __name__ == "__main__":
    unittest.main()
