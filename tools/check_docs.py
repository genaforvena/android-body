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
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
GREEN, RED, UNKNOWN = 0, 1, 2

FENCE = re.compile(r"^\s*(`{3,}|~{3,})")
HEADING = re.compile(r"^(#{1,6})\s+(.*?)\s*$")
LINK = re.compile(r"\[([^\]]*)\]\(\s*([^)\s]+)(?:\s+[\"'][^\"']*[\"'])?\s*\)")
EXTERNAL = re.compile(r"^[a-zA-Z][a-zA-Z0-9+.-]*:")


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
