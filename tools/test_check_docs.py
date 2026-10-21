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
import hashlib
import subprocess
import re
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

    def _create_link_targets(self, line: str) -> None:
        """Create files for relative links in *line* so fixtures resolve."""
        for m in re.finditer(r"\]\(([^)]+)\)", line):
            url = m.group(1)
            if url.startswith(("http:", "https:", "mailto:", "#")):
                continue
            target = (self.root / "docs" / url).resolve()
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("# target\n", encoding="utf-8")

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
    def test_long_line_not_in_baseline_is_red(self):
        # A line > 768 chars not in the frozen baseline is flagged.
        long_line = "x" * 769
        code, lines = self.scan_one("a.md", f"# T\n\n{long_line}\n")
        self.assertEqual(code, detector.RED)
        self.assertTrue(any("line exceeds 768 characters" in line for line in lines))

    def test_long_line_in_baseline_is_green(self):
        # A line whose content matches a baseline entry is NOT flagged.
        # Read the actual baseline line from the repo.
        text = (detector.REPO / "docs/verification.md").read_text(encoding="utf-8")
        lines = text.split("\n")
        long_line = next(
            line
            for line in lines
            if len(line) > 768
            and ("docs/verification.md", hashlib.sha256(line.encode("utf-8")).hexdigest()[:16])
            in detector.LONG_LINE_BASELINE
        )
        key = hashlib.sha256(long_line.encode("utf-8")).hexdigest()[:16]
        self.assertIn(("docs/verification.md", key), detector.LONG_LINE_BASELINE)
        self._create_link_targets(long_line)
        code, report = self.scan_one("docs/verification.md", f"# T\n\n{long_line}\n")
        self.assertEqual(code, detector.GREEN, report)

    def test_long_line_shift_is_green(self):
        # Prepending blank lines must not false-RED (shift-invariant).
        text = (detector.REPO / "docs/verification.md").read_text(encoding="utf-8")
        lines = text.split("\n")
        long_line = next(
            line
            for line in lines
            if len(line) > 768
            and ("docs/verification.md", hashlib.sha256(line.encode("utf-8")).hexdigest()[:16])
            in detector.LONG_LINE_BASELINE
        )
        self._create_link_targets(long_line)
        shifted = "\n".join(["", "", "", long_line])
        code, report = self.scan_one("docs/verification.md", f"# T\n\n{shifted}\n")
        self.assertEqual(code, detector.GREEN, report)

    def test_new_long_line_at_baseline_position_is_red(self):
        # A new long line at a previously-baseline position is still flagged.
        long_line = "y" * 769
        text = "\n".join(["# T"] + [""] * 8 + [long_line] + [""])
        code, lines = self.scan_one("docs/verification.md", text)
        self.assertEqual(code, detector.RED)
        self.assertTrue(any("line exceeds 768 characters" in line for line in lines))

    def test_repo_long_lines_match_baseline(self):
        """All tracked long lines must match a baseline entry (content-keyed)."""
        listed = subprocess.run(
            ["git", "-C", str(detector.REPO), "ls-files", "--", "*.md"],
            capture_output=True, text=True,
        )
        paths = [detector.REPO / rel for rel in listed.stdout.split()]
        for path in paths:
            rel = str(path.relative_to(detector.REPO))
            text = path.read_text(encoding="utf-8")
            for lineno, line in enumerate(text.split("\n"), 1):
                if len(line) > 768:
                    key = hashlib.sha256(line.encode("utf-8")).hexdigest()[:16]
                    self.assertIn(
                        (rel, key),
                        detector.LONG_LINE_BASELINE,
                        f"{rel}:{lineno} long line not in baseline",
                    )
    def test_baseline_entries_match_repo_long_lines(self):
        """Every baseline entry must still match a tracked long line.

        The forward direction (``test_repo_long_lines_match_baseline``) stops a
        new long line passing unkeyed. This is the reverse: a content-keyed
        baseline keeps no entry for a line that was edited, shortened or
        removed. Four such dead entries (``README.md 9101ddacd2e63e05``,
        ``docs/actions.md ab2a8105b4c14b32``, ``docs/verification.md
        6dd89120828f6584``/``db12ada776b64e86``) had accumulated by 2026-10-21,
        so the gate could not tell a maintained baseline from a stale one.
        """
        listed = subprocess.run(
            ["git", "-C", str(detector.REPO), "ls-files", "--", "*.md"],
            capture_output=True, text=True,
        )
        live = set()
        for path in [detector.REPO / rel for rel in listed.stdout.split()]:
            rel = str(path.relative_to(detector.REPO))
            for line in path.read_text(encoding="utf-8").split("\n"):
                if len(line) > 768:
                    live.add((rel, hashlib.sha256(line.encode("utf-8")).hexdigest()[:16]))
        self.assertEqual(
            sorted(set(detector.LONG_LINE_BASELINE) - live),
            [],
            "baseline entries with no matching tracked long line",
        )


    def test_short_line_is_green(self):
        # A line <= 768 chars is NOT flagged.
        short_line = "x" * 768
        code, lines = self.scan_one("a.md", f"# T\n\n{short_line}\n")
        self.assertEqual(code, detector.GREEN, lines)

    def test_baseline_is_nonempty(self):
        # The baseline must be non-empty (it carries the known long lines).
        self.assertTrue(len(detector.LONG_LINE_BASELINE) > 0)


class RepoTest(unittest.TestCase):
    def test_tracked_markdown_links_resolve(self):
        code, lines = detector.scan()
        self.assertEqual(code, detector.GREEN, "\n".join(lines))


if __name__ == "__main__":
    unittest.main()
