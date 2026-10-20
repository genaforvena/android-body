#!/usr/bin/env python3
# SPDX-License-Identifier: CC0-1.0
"""Tests for the published-APK drift detector (tools/check_published_apk.py).

The regression that matters: on 2026-10-16 the published download still held the
``d6c5113`` payload while ``556049c`` had changed ``AndroidManifest.xml`` and
``classes.dex``, and section 9 of ``tools/health-check.sh`` stayed GREEN because
it only compared the download with its own ``SHA256SUMS`` record. The detector
must flag a changed, added or removed payload entry, and must ignore the
``META-INF`` signing material that legitimately differs between two builds of the
same source.
"""

import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import check_published_apk as detector  # noqa: E402


def write_apk(path: Path, entries: dict[str, bytes]) -> None:
    with zipfile.ZipFile(path, "w") as archive:
        for name, data in entries.items():
            archive.writestr(name, data)


class CompareTest(unittest.TestCase):
    def test_identical_payloads_match(self):
        payload = {"classes.dex": (10, 1), "AndroidManifest.xml": (4, 2)}
        code, lines = detector.compare(payload, dict(payload))
        self.assertEqual(code, detector.MATCH)
        self.assertIn("GREEN", lines[0])

    def test_changed_entry_is_flagged(self):
        code, lines = detector.compare({"classes.dex": (10, 1)},
                                       {"classes.dex": (12, 9)})
        self.assertEqual(code, detector.MISMATCH)
        self.assertTrue(any("entry differs: classes.dex" in line for line in lines))

    def test_crc32_is_reported_in_hex(self):
        # research-methods wake 122240: the decimal CRC-32 nearly produced a
        # false drift report against hex `unzip -v` output. The report must
        # carry the base.
        code, lines = detector.compare({"classes.dex": (10, 1)},
                                       {"classes.dex": (12, 9)})
        self.assertEqual(code, detector.MISMATCH)
        entry = next(line for line in lines if "entry differs" in line)
        self.assertIn("crc32=0x00000001", entry)
        self.assertIn("crc32=0x00000009", entry)
        self.assertNotIn("(10, 1)", entry)

    def test_added_and_removed_entries_are_flagged(self):
        code, lines = detector.compare(
            {"classes.dex": (10, 1), "res/old.xml": (1, 1)},
            {"classes.dex": (10, 1), "AndroidManifest.xml": (4, 2)})
        self.assertEqual(code, detector.MISMATCH)
        self.assertTrue(any("only in published: res/old.xml" in line for line in lines))
        self.assertTrue(any("only in build: AndroidManifest.xml" in line for line in lines))


class PayloadTest(unittest.TestCase):
    def test_meta_inf_is_ignored(self):
        with tempfile.TemporaryDirectory() as tmp:
            published, built = Path(tmp) / "a.apk", Path(tmp) / "b.apk"
            write_apk(published, {"classes.dex": b"same",
                                  "META-INF/CERT.RSA": b"old-signature"})
            write_apk(built, {"classes.dex": b"same",
                              "META-INF/CERT.RSA": b"new-signature"})
            code, _ = detector.compare(detector.payload(published),
                                       detector.payload(built))
        self.assertEqual(code, detector.MATCH)

    def test_zip_framing_does_not_change_the_payload(self):
        # The download and the build may order entries differently and the build
        # may carry orphaned local headers; only name/size/CRC count.
        with tempfile.TemporaryDirectory() as tmp:
            published, built = Path(tmp) / "a.apk", Path(tmp) / "b.apk"
            write_apk(published, {"classes.dex": b"x" * 50,
                                  "AndroidManifest.xml": b"m" * 5})
            write_apk(built, {"AndroidManifest.xml": b"m" * 5,
                              "classes.dex": b"x" * 50})
            code, _ = detector.compare(detector.payload(published),
                                       detector.payload(built))
        self.assertEqual(code, detector.MATCH)


class MainTest(unittest.TestCase):
    def test_missing_download_is_unknown(self):
        with tempfile.TemporaryDirectory() as tmp:
            built = Path(tmp) / "b.apk"
            write_apk(built, {"classes.dex": b"x"})
            code = detector.main([str(built), "--published", str(Path(tmp) / "gone.apk")])
        self.assertEqual(code, detector.UNKNOWN)

    def test_mismatch_through_the_cli(self):
        with tempfile.TemporaryDirectory() as tmp:
            published, built = Path(tmp) / "a.apk", Path(tmp) / "b.apk"
            write_apk(published, {"classes.dex": b"old"})
            write_apk(built, {"classes.dex": b"new"})
            code = detector.main([str(built), "--published", str(published)])
        self.assertEqual(code, detector.MISMATCH)


if __name__ == "__main__":
    unittest.main()
