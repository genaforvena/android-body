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
