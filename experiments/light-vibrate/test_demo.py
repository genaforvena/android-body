# SPDX-License-Identifier: CC0-1.0
"""Consumer-only tests: synthetic text + a local temporary server, no phone."""
import importlib.util
import os
from pathlib import Path
import subprocess
import tempfile
import threading
import time
import unittest

HERE = Path(__file__).resolve().parent
SERVER_PATH = HERE.parents[1] / "rendezvous/minimal-server/server.py"
spec = importlib.util.spec_from_file_location("body_demo_server", SERVER_PATH)
server = importlib.util.module_from_spec(spec)
spec.loader.exec_module(server)
SECRET = "a" * 64


class DetectorTests(unittest.TestCase):
    def detect(self, lines, **overrides):
        values = dict(cursor=0, armed=1, last_action=0, attempts=0, now=1000, threshold=10, duration=200, cooldown=30, max_age=30, max_actions=10)
        values.update(overrides)
        with tempfile.TemporaryDirectory() as directory:
            state_path = Path(directory, "state")
            command = ["awk"]
            for key, value in values.items():
                command.extend(["-v", f"{key}={value}"])
            command += ["-v", f"state_out={state_path}", "-f", str(HERE / "light-threshold.awk")]
            result = subprocess.run(command, input=lines.encode(), capture_output=True)
            state = state_path.read_text() if state_path.exists() else None
            return result.returncode, result.stdout.decode(), state

    def test_dark_sample_emits_and_checkpoints(self):
        self.assertEqual(self.detect("1 1000 light lux=5\n"), (0, "vibrate duration=200\n", "1 0 1000 1\n"))

    def test_actual_android_metadata_and_stale_age(self):
        self.assertEqual(self.detect("1 1000 light lux=5.0 accuracy=3 age_ms=50\n")[1], "vibrate duration=200\n")
        self.assertEqual(self.detect("1 1000 light lux=5.0 accuracy=3 age_ms=31000\n")[1], "")
        self.assertEqual(self.detect("1 1000 light lux=5.0 accuracy=3 accuracy=2\n")[1], "")
        self.assertEqual(self.detect("1 1000 light lux=5.0 surprise=1\n")[1], "")

    def test_unknown_missing_malformed_and_stale_never_become_zero(self):
        inputs = ["1 1000 light unavailable reason=absent\n", "1 1000 light lux=NaN\n", "1 1000 light lux=\n", "1 1000 light lux=-1\n", "1 1000 light lux=1e999\n", "1 500 light lux=1\n", "1 1010 light lux=1\n", "1 1000 battery level=0.01 charging=false\n"]
        for lines in inputs:
            self.assertEqual(self.detect(lines)[1], "", lines)

    def test_latest_light_in_batch_decides(self):
        self.assertEqual(self.detect("1 1000 light lux=1\n2 1000 light lux=50\n")[1], "")
        self.assertEqual(self.detect("1 1000 light lux=1\n2 1000 light unavailable reason=absent\n")[1], "")
        self.assertEqual(self.detect("1 1000 light lux=50\n2 1000 light lux=1\n")[1], "vibrate duration=200\n")

    def test_cooldown_and_cap(self):
        self.assertEqual(self.detect("1 1000 light lux=1\n", last_action=990)[1], "")
        self.assertEqual(self.detect("1 1000 light lux=1\n", attempts=10)[1], "")
        self.assertEqual(self.detect("1 1000 light lux=1\n", armed=0)[1], "")
        self.assertEqual(self.detect("1 1000 light lux=50\n", armed=0)[2], "1 1 0 0\n")

    def test_invalid_sequence_discards_whole_batch(self):
        for lines in ("1 1000 light lux=1\n3 1000 light lux=1\n", "0 1000 light lux=1\n", "9007199254740992 1000 light lux=1\n"):
            self.assertEqual(self.detect(lines), (2, "", None))


class RunnerTests(unittest.TestCase):
    def test_real_curl_awk_roundtrip_and_resume(self):
        with tempfile.TemporaryDirectory() as directory:
            store = server.Store(Path(directory, "data"), {"note3": SECRET})
            http = server.Server(("127.0.0.1", 0), store)
            thread = threading.Thread(target=http.serve_forever, daemon=True)
            thread.start()
            base = f"http://127.0.0.1:{http.server_port}/node/note3"
            environment = dict(os.environ, BODY_SECRET=SECRET, ALLOW_INSECURE_HTTP="1", STATE_FILE=str(Path(directory, "state")), MAX_POLLS="1")
            try:
                store.queues[("note3", "observations")].append([f"{int(time.time())} light lux=1.0 accuracy=3 age_ms=0".encode()])
                command = ["sh", str(HERE / "watch-light.sh"), base]
                first = subprocess.run(command, env=environment, capture_output=True, timeout=15)
                self.assertEqual(first.returncode, 0, first.stderr)
                self.assertIn(b"Queued action 1", first.stdout)
                self.assertIn(b"Physical vibration is unverified", first.stdout)
                self.assertEqual(store.queues[("note3", "actions")].read(0)[0], b"1 vibrate duration=200\n")
                second = subprocess.run(command, env=environment, capture_output=True, timeout=15)
                self.assertEqual(second.returncode, 0, second.stderr)
                self.assertNotIn(b"Queued action", second.stdout)
                self.assertEqual(store.queues[("note3", "actions")].head, 1)
                self.assertFalse(Path(directory, "state.lock").exists())
            finally:
                http.shutdown()
                thread.join()
                http.server_close()
                store.close()

    def test_plain_http_is_explicit_opt_in(self):
        env = dict(os.environ, BODY_SECRET=SECRET)
        env.pop("ALLOW_INSECURE_HTTP", None)
        result = subprocess.run(["sh", str(HERE / "watch-light.sh"), "http://127.0.0.1:8080/node/note3"], env=env, capture_output=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn(b"ALLOW_INSECURE_HTTP", result.stderr)


if __name__ == "__main__":
    unittest.main()
