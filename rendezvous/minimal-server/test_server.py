# SPDX-License-Identifier: CC0-1.0
"""Run with: python3 -m unittest discover -s rendezvous/minimal-server -v"""
import concurrent.futures
import http.client
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

import server

SECRET = "a" * 64
OTHER_SECRET = "b" * 64


class HttpTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.directory = Path(self.temp.name)
        self.start()

    def start(self):
        self.store = server.Store(self.directory, {"note3": SECRET, "hall": OTHER_SECRET})
        self.http = server.Server(("127.0.0.1", 0), self.store)
        self.thread = threading.Thread(target=self.http.serve_forever, daemon=True)
        self.thread.start()

    def stop(self):
        self.http.shutdown()
        self.thread.join()
        self.http.server_close()
        self.store.close()

    def tearDown(self):
        self.stop()
        self.temp.cleanup()

    def request(self, method, path, body=None, secret=SECRET, headers=None):
        connection = http.client.HTTPConnection("127.0.0.1", self.http.server_port, timeout=5)
        all_headers = {"Content-Type": "text/plain; charset=utf-8"}
        if secret is not None:
            all_headers["Authorization"] = "Bearer " + secret
        all_headers.update(headers or {})
        try:
            connection.request(method, path, body, all_headers)
            response = connection.getresponse()
            return response.status, response.read(), dict(response.getheaders())
        finally:
            connection.close()

    def test_phone_consumer_roundtrip(self):
        self.assertEqual(self.request("POST", "/node/note3/observations", b"1712345679 light lux=82\n1712345680 battery level=0.73 charging=true\n")[:2], (201, b"1\n2\n"))
        status, body, headers = self.request("GET", "/node/note3/observations?after=0")
        self.assertEqual(status, 200)
        self.assertEqual(body, b"1 1712345679 light lux=82\n2 1712345680 battery level=0.73 charging=true\n")
        self.assertEqual(headers["X-Last-Sequence"], "2")
        self.assertEqual(headers["X-Has-More"], "0")
        self.assertEqual(self.request("POST", "/node/note3/actions", b"vibrate duration=200")[:2], (201, b"1\n"))
        self.assertEqual(self.request("GET", "/node/note3/actions?after=0")[:2], (200, b"1 vibrate duration=200\n"))
        self.assertEqual(self.request("GET", "/node/note3/actions?after=1")[:2], (200, b""))

    def test_auth_and_node_isolation(self):
        for secret in (None, "wrong", OTHER_SECRET):
            self.assertEqual(self.request("POST", "/node/note3/actions", b"invalid\x00", secret)[0], 401)
        self.assertEqual(self.request("GET", "/node/unknown/actions?after=0")[0], 401)
        self.assertEqual(self.request("GET", "/node/hall/actions?after=0")[0], 401)
        self.assertEqual(self.request("GET", "/node/hall/actions?after=0", secret=OTHER_SECRET)[0], 200)
        self.assertEqual(self.request("GET", "/node/note3/actions?after=0", headers={"Authorization": "Basic " + SECRET})[0], 401)

    def test_restart_preserves_ids_and_observations(self):
        self.request("POST", "/node/note3/actions", b"vibrate duration=200\n")
        self.request("POST", "/node/note3/observations", b"123 light unavailable reason=absent\n")
        self.stop()
        self.start()
        self.assertEqual(self.request("POST", "/node/note3/actions", b"vibrate duration=10\n")[:2], (201, b"2\n"))
        self.assertEqual(self.request("GET", "/node/note3/actions?after=1")[:2], (200, b"2 vibrate duration=10\n"))
        self.assertEqual(self.request("GET", "/node/note3/observations?after=0")[:2], (200, b"1 123 light unavailable reason=absent\n"))

    def test_concurrent_posts_get_contiguous_unique_ids(self):
        def post(_):
            return self.request("POST", "/node/note3/actions", b"vibrate duration=10\n")
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
            replies = list(executor.map(post, range(64)))
        self.assertTrue(all(status == 201 for status, _, _ in replies))
        self.assertEqual(sorted(int(body) for _, body, _ in replies), list(range(1, 65)))
        lines = self.request("GET", "/node/note3/actions?after=0")[1].splitlines()
        self.assertEqual([int(line.split(b" ", 1)[0]) for line in lines], list(range(1, 65)))

    def test_duplicate_posts_are_not_deduplicated(self):
        first = self.request("POST", "/node/note3/actions", b"vibrate duration=200\n")
        retry = self.request("POST", "/node/note3/actions", b"vibrate duration=200\n")
        self.assertEqual((first[1], retry[1]), (b"1\n", b"2\n"))
        self.assertEqual(self.request("GET", "/node/note3/actions?after=0")[1].count(b"vibrate"), 2)

    def test_invalid_body_is_atomic_no_id_assigned(self):
        bad = (b"", b"\n", b"   ", b"ok\n\n", b"ok\r\n", b"ok\x00", b"ok\tbad", b"\xff", "x\u0085".encode(), "x\u2028".encode(), b"x" * 1008, b"x\n" * 129, b"ok\nbad\x7f")
        for body in bad:
            with self.subTest(body=body[:30]):
                self.assertEqual(self.request("POST", "/node/note3/actions", body)[0], 400)
        self.assertEqual(self.request("GET", "/node/note3/actions?after=0")[1], b"")
        self.assertEqual(self.request("POST", "/node/note3/actions", b"fine")[1], b"1\n")

    def test_body_media_type_and_size(self):
        self.assertEqual(self.request("POST", "/node/note3/actions", b"x" * 65537)[0], 413)
        self.assertEqual(self.request("POST", "/node/note3/actions", b"x", headers={"Content-Type": "application/json"})[0], 415)
        self.assertEqual(self.request("POST", "/node/note3/actions", b"x", headers={"Content-Encoding": "gzip"})[0], 415)
        self.assertEqual(self.request("POST", "/node/note3/actions", b"x", headers={"Transfer-Encoding": "chunked"})[0], 400)
        self.assertEqual(self.request("POST", "/node/note3/actions", b"x", headers={"Expect": "100-continue"})[0], 417)

    def test_strict_routes_and_cursor_reset_signal(self):
        paths = ("/node/../actions?after=0", "/node/%2e%2e/actions?after=0", "/node/NOTE3/actions?after=0", "/node/note3/actions?after=-1", "/node/note3/actions?after=01", "/node/note3/actions?after=0&extra=1", "/node/note3/actions/", "/node/note3/actions?after=0#fragment")
        for path in paths:
            self.assertEqual(self.request("GET", path)[0], 404, path)
        self.assertEqual(self.request("GET", "/node/note3/actions")[0], 400)
        self.assertEqual(self.request("GET", "/node/note3/actions?after=1")[0], 409)
        self.assertEqual(self.request("GET", f"/node/note3/actions?after={server.MAX_ID + 1}")[0], 400)
        self.assertEqual(self.request("POST", "/node/note3/actions?after=0", b"x")[0], 400)

    def test_read_batch_and_byte_bounds(self):
        for _ in range(2):
            self.assertEqual(self.request("POST", "/node/note3/actions", b"x\n" * 128)[0], 201)
        status, body, headers = self.request("GET", "/node/note3/actions?after=0")
        self.assertEqual(status, 200)
        self.assertEqual(len(body.splitlines()), 128)
        self.assertEqual(headers["X-Last-Sequence"], "128")
        self.assertEqual(headers["X-Has-More"], "1")
        long_line = ("é" * 503 + "x").encode()  # 1007 UTF-8 bytes.
        for _ in range(2):
            self.assertEqual(self.request("POST", "/node/note3/observations", (long_line + b"\n") * 65)[0], 201)
        _, body, headers = self.request("GET", "/node/note3/observations?after=0")
        self.assertLessEqual(len(body), server.MAX_BODY_BYTES)
        self.assertTrue(all(len(line) <= 1024 for line in body.splitlines()))
        self.assertEqual(headers["X-Has-More"], "1")
        next_body = self.request("GET", "/node/note3/observations?after=" + headers["X-Last-Sequence"])[1]
        self.assertTrue(next_body.startswith(str(int(headers["X-Last-Sequence"]) + 1).encode() + b" "))

    def test_queue_cap_is_explicit_no_pruning(self):
        queue = self.store.queues[("note3", "actions")]
        queue.max_bytes = 20
        self.assertEqual(self.request("POST", "/node/note3/actions", b"a\nb\nc\n")[0], 201)
        self.assertEqual(self.request("POST", "/node/note3/actions", b"long_command_here")[0], 507)
        self.assertEqual(self.request("GET", "/node/note3/actions?after=0")[1], b"1 a\n2 b\n3 c\n")
        self.assertEqual(queue.head, 3)

    def test_duplicate_headers_rejected(self):
        for name, values in (("Authorization", ["Bearer " + SECRET] * 2), ("Content-Length", ["1", "1"])):
            extra = "" if name == "Authorization" else f"Authorization: Bearer {SECRET}\r\n"
            extra += "" if name == "Content-Length" else "Content-Length: 1\r\n"
            duplicate = "".join(f"{name}: {value}\r\n" for value in values)
            request = f"POST /node/note3/actions HTTP/1.0\r\n{extra}{duplicate}Content-Type: text/plain\r\n\r\nx".encode()
            with socket.create_connection(("127.0.0.1", self.http.server_port), timeout=5) as sock:
                sock.sendall(request)
                response = sock.recv(4096)
            expected = b"401" if name == "Authorization" else b"400"
            self.assertIn(expected, response.split(b"\r\n", 1)[0])

    def test_unsupported_method_errors_are_text(self):
        status, body, headers = self.request("DELETE", "/node/note3/actions")
        self.assertEqual(status, 501)
        self.assertEqual(body, b"error http_501\n")
        self.assertEqual(headers["Content-Type"], "text/plain; charset=utf-8")


class StoreTests(unittest.TestCase):
    def test_exclusive_writer_lock(self):
        with tempfile.TemporaryDirectory() as directory:
            first = server.Store(Path(directory), {"note3": SECRET})
            try:
                with self.assertRaisesRegex(ValueError, "already owns"):
                    server.Store(Path(directory), {"note3": SECRET})
            finally:
                first.close()
            second = server.Store(Path(directory), {"note3": SECRET})
            second.close()

    def test_torn_or_corrupt_log_fails_closed(self):
        for content in (b"1 a\n2 partial", b"2 a\n", b"1 a\n1 duplicate\n", b"1 ok\x00\n", b"1 " + b"x" * 1008 + b"\n"):
            with self.subTest(content=content[:20]), tempfile.TemporaryDirectory() as directory:
                Path(directory, "note3.actions.log").write_bytes(content)
                with self.assertRaises(ValueError):
                    server.Store(Path(directory), {"note3": SECRET})
                self.assertEqual(Path(directory, "note3.actions.log").read_bytes(), content)

    def test_symlink_queue_is_not_followed(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory, "target")
            target.write_text("do not touch")
            Path(directory, "note3.actions.log").symlink_to(target)
            with self.assertRaises(OSError):
                server.Store(Path(directory), {"note3": SECRET})
            self.assertEqual(target.read_text(), "do not touch")

    def test_uncertain_fsync_stops_queue_until_restart(self):
        with tempfile.TemporaryDirectory() as directory:
            store = server.Store(Path(directory), {"note3": SECRET})
            queue = store.queues[("note3", "actions")]
            with patch("server.os.fsync", side_effect=OSError("simulated disk failure")):
                with self.assertRaises(server.ProtocolError) as caught:
                    queue.append([b"vibrate duration=200"])
                self.assertEqual(caught.exception.status, 503)
            with self.assertRaises(server.ProtocolError):
                queue.append([b"vibrate duration=100"])
            with self.assertRaises(server.ProtocolError):
                queue.read(0)
            store.close()
            store = server.Store(Path(directory), {"note3": SECRET})
            self.assertEqual(store.queues[("note3", "actions")].append([b"next"]), [2])
            store.close()

    def test_cli_requires_explicit_non_loopback_opt_in(self):
        process = subprocess.run([sys.executable, str(Path(server.__file__)), "--host", "0.0.0.0", "--node", "note3:BODY_SECRET"], capture_output=True)
        self.assertNotEqual(process.returncode, 0)
        self.assertIn(b"--allow-insecure-http", process.stderr)

    def test_invalid_config(self):
        for secrets in ({}, {"../escape": SECRET}, {"n": "short"}, {"n": "x " * 32}):
            with tempfile.TemporaryDirectory() as directory, self.assertRaises(ValueError):
                server.Store(Path(directory), secrets)


if __name__ == "__main__":
    unittest.main()
