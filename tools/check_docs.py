#!/usr/bin/env python3
# SPDX-License-Identifier: CC0-1.0
"""Detect broken or unclosed relative links in the tracked Markdown.

The reader-facing book is Markdown, and a link that does not resolve is a
reader-visible dead end. On 2026-10-17 commit ``337895f6`` truncated README.md's
"For offline recording" paragraph to 768 bytes and replaced the closing ``).``
of its ``[Full storage and delivery semantics](...)`` link with ``…``, so the entry
page carried a link that rendered as literal text. A target-resolution scan
alone missed it: the truncated line has no ``)`` and so no link at all. This
detector therefore checks both that every Markdown link closes and that every
relative target and anchor resolves.

Tracked files only: the gitignored site holds walls, notes and chat that are not
the book. Fenced code blocks are skipped, and a query string (``?raw=true``) is
stripped before resolving, as on the download page.
"""

from __future__ import annotations

import argparse
import re
import hashlib
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
GREEN, RED, UNKNOWN = 0, 1, 2

FENCE = re.compile(r"^\s*(`{3,}|~{3,})")
HEADING = re.compile(r"^(#{1,6})\s+(.*?)\s*$")
LINK = re.compile(r"\[([^\]]*)\]\(\s*([^)\s]+)(?:\s+[\"'][^\"']*[\"'])?\s*\)")
EXTERNAL = re.compile(r"^[a-zA-Z][a-zA-Z0-9+.-]*:")

# Content-keyed baseline of tracked Markdown lines that exceed 768 characters.
# The `read` display truncates lines longer than 768 characters and appends
# `…`; a mid-sentence truncation (like the 2026-10-17 docs/verification.md
# defect) stays GREEN under the link check. Each entry is (file, sha256[:16])
# of a known long line. Content-keying makes the gate shift-invariant: editing
# text above a baseline line does not produce false-RED, and a new long line
# at a previously-baseline position is still flagged.
LONG_LINE_BASELINE = {
    ("ble-probe/README.md", "d73dd1715d7003a1"),
    ("docs/actions.md", "8676e78e68f1355f"),
    ("docs/compatibility.md", "174ea31cd73ece81"),
    ("docs/compatibility.md", "203eb6a3499f80dd"),
    ("docs/compatibility.md", "dde1530c6b08f616"),
    ("docs/compatibility.md", "d2e53070f246a533"),
    ("docs/verification.md", "0be93d3a4089da3c"),
    ("docs/verification.md", "113ff05381f9d794"),
    ("docs/verification.md", "1223cb5dccddfca0"),
    ("docs/verification.md", "1c694a26d40adb39"),
    ("docs/verification.md", "6655994c50437919"),
    ("docs/verification.md", "4dbfdc322aaf9d18"),
    ("docs/verification.md", "5b14966dad3520b6"),
    ("docs/verification.md", "61a5a2877dac1c1c"),
    ("docs/verification.md", "707a606c9a5c1476"),
    ("docs/verification.md", "7ea229a9b6ba9dc1"),
    ("docs/verification.md", "82189260e7776e5e"),
    ("docs/verification.md", "883b50fd27002dd9"),
    ("docs/verification.md", "9091d3e7c23d63ea"),
    ("docs/verification.md", "948c9428e6db247d"),
    ("docs/verification.md", "99ad1e01e11b5591"),
    ("docs/verification.md", "a6826eddfc8c51e3"),
    ("docs/verification.md", "b5bef8e5dcdfc049"),
    ("docs/verification.md", "b8a85837b25a10cd"),
    ("docs/verification.md", "619475da81687ed6"),
    ("docs/verification.md", "c4e4fd2007f93790"),
    ("docs/verification.md", "cb3c234c12d88744"),
    ("docs/verification.md", "d076dc3681e7bc38"),
    ("docs/verification.md", "d2c732ac69f899ab"),
    ("docs/verification.md", "d38d6b79fa05e480"),
    ("docs/verification.md", "d7ac2a8b13fe5a58"),
    ("docs/verification.md", "d8709d5fdd9468db"),
    ("docs/verification.md", "dce31285ccc0ec40"),
    ("docs/verification.md", "e2161df7f7996ff8"),
    ("docs/verification.md", "ef6b9f94a40f7005"),
    ("protocol/README.md", "41ad44e94303d2a7"),
    ("protocol/README.md", "bd977b2d8ca00d7d"),
}


def _line_key(line: str) -> str:
    """Return the content-key for a baseline lookup (shift-invariant)."""
    return hashlib.sha256(line.encode("utf-8")).hexdigest()[:16]


def slug(heading: str) -> str:
    """GitHub-style anchor for a Markdown heading."""
    text = re.sub(r"[^\w\s-]", "", heading.strip().lower())
    return re.sub(r"\s+", "-", text)


def headings(text: str) -> list[str]:
    """Anchors of the headings outside fenced code blocks."""
    found: list[str] = []
    fence: str | None = None
    for line in text.split("\n"):
        mark = FENCE.match(line)
        if mark:
            token = mark.group(1)[0] * 3
            if fence is None:
                fence = token
            elif fence == token:
                fence = None
            continue
        if fence is not None:
            continue
        m = HEADING.match(line)
        if m:
            found.append(slug(m.group(2)))
    return found


def scan(root: Path = REPO, paths: list[Path] | None = None) -> tuple[int, list[str]]:
    """Return ``(code, lines)`` for every tracked Markdown file under ``root``.

    ``paths`` overrides the tracked-file listing so tests can scan fixtures.
    """
    lines: list[str] = []
    problems = 0
    if paths is None:
        listed = subprocess.run(
            ["git", "-C", str(root), "ls-files", "--", "*.md"],
            capture_output=True,
            text=True,
        )
        if listed.returncode != 0:
            return UNKNOWN, ["could not list tracked markdown: " + listed.stderr.strip()]
        paths = [root / rel for rel in listed.stdout.split()]

    for path in paths:
        try:
            rel = str(path.relative_to(root))
        except ValueError:
            rel = str(path)
        try:
            text = path.read_text(encoding="utf-8")
        except OSError as exc:
            lines.append(f"{rel}: unreadable: {exc}")
            problems += 1
            continue
        own = headings(text)
        fence: str | None = None
        for lineno, line in enumerate(text.split("\n"), 1):
            mark = FENCE.match(line)
            if mark:
                token = mark.group(1)[0] * 3
                if fence is None:
                    fence = token
                elif fence == token:
                    fence = None
                continue
            if fence is not None:
                continue
            cut = line.rfind("](")
            if cut != -1 and ")" not in line[cut + 2:]:
                lines.append(
                    f"{rel}:{lineno}: unclosed markdown link: {line.strip()[:100]}"
                )
                problems += 1
                continue
            for m in LINK.finditer(line):
                url = m.group(2)
                if EXTERNAL.match(url):
                    continue
                target, _, anchor = url.partition("#")
                target = target.split("?", 1)[0]
                if not target:
                    if anchor and anchor not in own:
                        lines.append(f"{rel}:{lineno}: unknown self-anchor #{anchor}")
                        problems += 1
                    continue
                resolved = (path.parent / target).resolve()
                if not resolved.exists():
                    lines.append(f"{rel}:{lineno}: missing link target {url}")
                    problems += 1
                    continue
                if anchor:
                    try:
                        target_headings = headings(resolved.read_text(encoding="utf-8"))
                    except OSError:
                        target_headings = []
                    if anchor not in target_headings:
                        lines.append(f"{rel}:{lineno}: unknown anchor {url}")
                        problems += 1
            # Length gate: flag lines > 768 chars not in the frozen baseline.
            # The `read` display truncates at 768 chars; a truncated line is a
            # mid-sentence cut that the link check cannot see.
            if len(line) > 768 and (rel, _line_key(line)) not in LONG_LINE_BASELINE:
                lines.append(
                    f"{rel}:{lineno}: line exceeds 768 characters ({len(line)}): {line.strip()[:100]}"
                )
                problems += 1

    if problems:
        return RED, lines
    return GREEN, ["GREEN no broken or unclosed relative links in tracked markdown"]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=REPO)
    args = parser.parse_args(argv)
    code, lines = scan(args.root)
    for line in lines:
        print(line)
    return code


if __name__ == "__main__":
    sys.exit(main())
