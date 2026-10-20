#!/usr/bin/env python3
# SPDX-License-Identifier: CC0-1.0
"""Detect a published download APK that no longer matches the committed source.

``downloads/android-body-debug.apk`` is rebuilt by hand, so it can silently lag
``main``: on 2026-10-16 it was last built at ``d6c5113`` while ``556049c`` had
since added ``ACCESS_NETWORK_STATE`` and ``Sensors.wifiLinkUp()``, so the
documented install path shipped bytes without that change. ``tools/health-check.sh``
section 9 stayed GREEN through it because it only compares the download with its
own ``SHA256SUMS`` record, not with the source.

A debug build is deterministic in payload: two builds of the same source produce
the same entry names, uncompressed sizes and CRC-32s, differing only in zip
framing (entry order, orphaned local headers, alignment) and the ``META-INF``
signing material. Comparing the download with a build of the current source on
those three fields therefore detects the drift, while ``META-INF`` -- and so the
signing timestamp and signer -- is ignored.

Usage:
    python3 tools/check_published_apk.py [BUILT_APK]

``BUILT_APK`` defaults to ``app/build/outputs/apk/debug/app-debug.apk``. Exit
status: 0 payloads match, 1 mismatch, 2 nothing to compare (download or build
missing, or an unreadable archive).
"""

from __future__ import annotations

import argparse
import sys
import zipfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
PUBLISHED_REL = Path("downloads") / "android-body-debug.apk"
BUILT_REL = Path("app") / "build" / "outputs" / "apk" / "debug" / "app-debug.apk"
SIGNING_PREFIX = "META-INF/"

MATCH, MISMATCH, UNKNOWN = 0, 1, 2


def payload(path: Path) -> dict[str, tuple[int, int]]:
    """Map each non-signing entry to ``(uncompressed size, CRC-32)``.

    Raises ``zipfile.BadZipFile`` or ``OSError`` for an unreadable archive.
    """
    with zipfile.ZipFile(path) as archive:
        return {
            info.filename: (info.file_size, info.CRC)
            for info in archive.infolist()
            if not info.filename.startswith(SIGNING_PREFIX)
        }


def compare(published: dict[str, tuple[int, int]],
            built: dict[str, tuple[int, int]]) -> tuple[int, list[str]]:
    """Compare two payload maps; return the exit code and a report."""
    if published == built:
        return MATCH, [f"GREEN published APK payload matches the build "
                       f"({len(published)} entries)"]
    lines = ["RED published APK payload differs from the build of the current source "
             "(crc32 in hex, the `unzip -v` base)"]
    def fmt(entry: tuple[int, int] | None) -> str:
        return "absent" if entry is None else f"(size={entry[0]}, crc32={entry[1]:#010x})"
    for name in sorted(set(published) | set(built)):
        if published.get(name) == built.get(name):
            continue
        where = ("only in published" if name not in built else
                 "only in build" if name not in published else "entry differs")
        lines.append(f"  {where}: {name} "
                     f"published={fmt(published.get(name))} built={fmt(built.get(name))}")
    lines.append("  rebuild downloads/android-body-debug.apk from the current "
                 "source and refresh downloads/SHA256SUMS")
    return MISMATCH, lines


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("built", nargs="?", type=Path, default=REPO / BUILT_REL,
                        help="debug APK built from the current source")
    parser.add_argument("--published", type=Path, default=REPO / PUBLISHED_REL,
                        help="published download to check")
    args = parser.parse_args(argv)

    missing = [str(p) for p in (args.published, args.built) if not p.is_file()]
    if missing:
        print("UNKNOWN nothing to compare; missing: " + ", ".join(missing))
        return UNKNOWN
    try:
        code, lines = compare(payload(args.published), payload(args.built))
    except (OSError, zipfile.BadZipFile) as error:
        print(f"UNKNOWN unreadable archive: {error}")
        return UNKNOWN
    print("\n".join(lines))
    return code


if __name__ == "__main__":
    sys.exit(main())
