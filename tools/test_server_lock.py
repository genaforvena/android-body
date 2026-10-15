"""Deterministic boundary tests for the rendezvous server's data-directory lock.

The server opens ``<data-dir>/.lock`` O_RDWR at startup. A lock left by a
process that is not the service uid (for example a deploy-time smoke test run
as root) bricks every start with EACCES. ``Store._open_lock`` recovers only
when the data directory is writable by the current uid; a read-only directory
must still fail closed. These tests exercise both paths without needing a
second uid: a mode-0000 lock owned by the test uid is unopenable exactly like
a foreign-owned one, and unlink permission is decided by the directory mode.
"""

import importlib.util
import tempfile
import unittest
from pathlib import Path

SERVER_PATH = (
    Path(__file__).resolve().parents[1]
    / "rendezvous"
    / "minimal-server"
    / "server.py"
)

_spec = importlib.util.spec_from_file_location("rendezvous_server", SERVER_PATH)
server = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(server)

SECRET = "a" * 32
MIN_QUEUE_BYTES = 1025


class LockAcquisitionTests(unittest.TestCase):
    def test_recovers_when_lock_unopenable_but_directory_writable(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp) / "queues"
            directory.mkdir(mode=0o700)
            (directory / ".lock").touch(mode=0o000)
            store = server.Store(directory, {"node": SECRET}, MIN_QUEUE_BYTES)
            try:
                self.assertIsNotNone(store.lockfile)
            finally:
                store.close()
            self.assertFalse((directory / ".lock").exists() and
                             (directory / ".lock").stat().st_mode & 0o777 == 0,
                             "stale lock should have been replaced by an openable one")

    def test_fails_closed_when_directory_not_writable(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp) / "queues"
            directory.mkdir(mode=0o700)
            (directory / ".lock").touch(mode=0o000)
            directory.chmod(0o500)
            try:
                with self.assertRaises(OSError):
                    server.Store(directory, {"node": SECRET}, MIN_QUEUE_BYTES)
            finally:
                directory.chmod(0o700)

    def test_normal_start_with_no_lock(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp) / "queues"
            directory.mkdir(mode=0o700)
            store = server.Store(directory, {"node": SECRET}, MIN_QUEUE_BYTES)
            try:
                self.assertIsNotNone(store.lockfile)
            finally:
                store.close()


if __name__ == "__main__":
    unittest.main()
