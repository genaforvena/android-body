#!/usr/bin/env python3
# SPDX-License-Identifier: CC0-1.0
"""Tests for the Markdown link detector (tools/check_docs.py).

The regression that matters: on 2026-10-17 commit ``337895f6`` truncated the
README "For offline recording" paragraph to 768 bytes and replaced the closing
``).`` of its ``[Full storage and delivery semantics](...)`` link with ``…``, so
the entry page carried a link that rendered as literal text. A target scan alone
misses that shape, so the detector must also flag an unclosed link.
"""

import tempfile
import unittest
from pathlib import Path

import check_docs as detector  # noqa: E402


def write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


class DetectorTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def scan_one(self, name: str, text: str):
        return detector.scan(self.root, [write(self.root / name, text)])

    def test_resolving_link_and_anchor_are_green(self):
        write(self.root / "b.md", "# Target\n\n## Delivery, collection and restart semantics\n")
        code, lines = self.scan_one(
            "a.md",
            "See [the target](b.md#delivery-collection-and-restart-semantics).\n",
        )
        self.assertEqual(code, detector.GREEN, lines)

    def test_self_anchor_resolves(self):
        code, lines = self.scan_one("a.md", "## Checks\n\nSee [below](#checks).\n")
        self.assertEqual(code, detector.GREEN, lines)

    def test_missing_target_is_red(self):
        code, lines = self.scan_one("a.md", "See [gone](nope.md).\n")
        self.assertEqual(code, detector.RED)
        self.assertTrue(any("missing link target nope.md" in line for line in lines))

    def test_unknown_anchor_is_red(self):
        write(self.root / "b.md", "## Target\n")
        code, lines = self.scan_one("a.md", "See [wrong](b.md#not-there).\n")
        self.assertEqual(code, detector.RED)
        self.assertTrue(any("unknown anchor b.md#not-there" in line for line in lines))

    def test_unknown_self_anchor_is_red(self):
        code, lines = self.scan_one("a.md", "## Checks\n\nSee [wrong](#not-there).\n")
        self.assertEqual(code, detector.RED)
        self.assertTrue(any("unknown self-anchor #not-there" in line for line in lines))

    def test_truncated_link_is_red(self):
        # The observed defect: a 768-byte write cut the link before its ")".
        code, lines = self.scan_one(
            "a.md", "See [Full storage and delivery semantics](b.md#target…\n"
        )
        self.assertEqual(code, detector.RED)
        self.assertTrue(any("unclosed markdown link" in line for line in lines))

    def test_query_string_is_stripped(self):
        write(self.root / "apk.bin", "bytes")
        code, lines = self.scan_one("a.md", "[download](apk.bin?raw=true).\n")
        self.assertEqual(code, detector.GREEN, lines)

    def test_external_links_are_ignored(self):
        code, lines = self.scan_one(
            "a.md", "[site](https://example.com/x) and [mail](mailto:a@b.c).\n"
        )
        self.assertEqual(code, detector.GREEN, lines)

    def test_fenced_code_is_skipped(self):
        write(self.root / "b.md", "# B\n")
        code, lines = self.scan_one(
            "a.md", "```\nsee [gone](nope.md)\n```\n\n[ok](b.md)\n"
        )
        self.assertEqual(code, detector.GREEN, lines)

    def test_directory_link_is_green(self):
        (self.root / "sub").mkdir(parents=True, exist_ok=True)
        code, lines = self.scan_one("a.md", "See [sub](sub/).\n")
        self.assertEqual(code, detector.GREEN, lines)


class RepoTest(unittest.TestCase):
    def test_tracked_markdown_links_resolve(self):
        code, lines = detector.scan()
        self.assertEqual(code, detector.GREEN, "\n".join(lines))


if __name__ == "__main__":
    unittest.main()
