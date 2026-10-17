#!/usr/bin/env python3
# SPDX-License-Identifier: CC0-1.0
"""Tests for the runtime-pin detector (tools/runtime_pin.py).

The regression that matters: on 2026-10-17 a hand edit to the pinned release's
own ``src/mishe_tauftauf/session_watch.py`` left
``releases/1543b3a0...`` dirty while ``health/runtime-release.json`` still named
it, so every ``seed run`` channel of the co-resident core plant exited 2 with
``runtime pin invalid: runtime source changed or is not a clean exact-SHA
worktree`` on each 15 s restart (NRestarts=478 by 10:48Z) and no line in this
plant's check read the pin at all. The detector must RED on exactly the
predicates ``mishe_tauftauf.runtime_source.checked_source`` applies -- a dirty
working tree (tracked or untracked), a HEAD that is not the pin, a source that
is not the worktree root, a missing package, an unreadable or schema-invalid
document, a pin path that exists but is not a readable document, a source that
cannot be resolved, a git that runs and fails or cannot run at all -- and read
UNKNOWN, never a pass, for the one case ``source_for`` tolerates: a site that
declares no pin. The fixtures are real git worktrees because the predicates are
git's own. The kernel's verdicts for these inputs were checked against the
pinned release's ``runtime_source`` with a differential harness (independent
review, wake 106233); the two cases where the detector is deliberately *not*
the kernel's verdict are named in the tests that carry them.
"""

import contextlib
import io
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

import runtime_pin


def git(repo, *args):
    return subprocess.run(["git", "-C", str(repo), *args], check=True,
                          capture_output=True, text=True)


class PinCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.repo = self.root / "releases" / "abc"
        self.site = self.root / "site"
        (self.site / "health").mkdir(parents=True)
        package = self.repo / runtime_pin.PACKAGE_REL
        package.parent.mkdir(parents=True)
        package.write_text("# fixture package\n", encoding="utf-8")
        (self.repo / "other.txt").write_text("tracked\n", encoding="utf-8")
        subprocess.run(["git", "init", "-q", str(self.repo)], check=True, capture_output=True)
        for key, value in (("user.email", "t@example.invalid"), ("user.name", "t")):
            git(self.repo, "config", key, value)
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-qm", "fixture")
        self.sha = git(self.repo, "rev-parse", "HEAD").stdout.strip()

    @property
    def pin_path(self):
        return self.site / runtime_pin.PIN_REL

    def write_pin(self, source=None, sha=None, **extra):
        if sha is None:
            sha = git(self.repo, "rev-parse", "HEAD").stdout.strip()
        doc = {"version": 1, "source": str(source if source is not None else self.repo),
               "sha": sha}
        doc.update(extra)
        self.pin_path.write_text(json.dumps(doc), encoding="utf-8")

    def run_check(self, **kwargs):
        return runtime_pin.check(self.site, **kwargs)

    def assert_red(self, rc, lines, fragment):
        self.assertEqual(rc, 1, lines)
        self.assertIn(fragment, lines[0])

    # --- the precondition holds -------------------------------------------------

    def test_clean_worktree_at_pin_is_green(self):
        self.write_pin()
        rc, lines = self.run_check()
        self.assertEqual(rc, 0, lines)
        self.assertEqual(len(lines), 1)
        self.assertTrue(lines[0].startswith("GREEN"), lines)
        self.assertIn(self.sha[:12], lines[0])
        self.assertIn(str(self.repo), lines[0])

    def test_symlinked_release_path_is_green_like_the_kernel(self):
        """Both sides resolve the pin path before comparing, so a symlink agrees."""
        link = self.root / "release-link"
        os.symlink(self.repo, link)
        self.write_pin(source=link)
        rc, lines = self.run_check()
        self.assertEqual(rc, 0, lines)

    # --- the failing predicates -------------------------------------------------

    def test_modified_tracked_file_is_red_and_named(self):
        self.write_pin()
        (self.repo / "other.txt").write_text("edited\n", encoding="utf-8")
        rc, lines = self.run_check()
        self.assert_red(rc, lines, "worktree dirty")
        self.assertIn("1 path(s)", lines[0])
        self.assertIn("other.txt", lines[0])

    def test_untracked_file_is_red_like_the_kernel(self):
        self.write_pin()
        (self.repo / "new.txt").write_text("untracked\n", encoding="utf-8")
        rc, lines = self.run_check()
        self.assert_red(rc, lines, "worktree dirty")
        self.assertIn("new.txt", lines[0])

    def test_head_not_the_pin_is_red(self):
        self.write_pin(sha="0" * 40)
        rc, lines = self.run_check()
        self.assert_red(rc, lines, "!= pin 000000000000")
        self.assertIn(self.sha[:12], lines[0])

    def test_source_below_the_worktree_root_is_red(self):
        sub = self.repo / "sub"
        sub.mkdir()
        (sub / "f.txt").write_text("x\n", encoding="utf-8")
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-qm", "sub")
        self.write_pin(source=sub)
        rc, lines = self.run_check()
        self.assert_red(rc, lines, "is not a worktree root")

    def test_missing_package_is_red(self):
        (self.repo / runtime_pin.PACKAGE_REL).unlink()
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-qm", "drop package")
        self.write_pin()
        rc, lines = self.run_check()
        self.assert_red(rc, lines, "runtime source package is missing")

    def test_whitespace_source_is_red_before_any_git_call(self):
        self.write_pin(source=str(self.repo) + "/with space")
        rc, lines = self.run_check(git=lambda *a, **k: self.fail("git must not run"))
        self.assert_red(rc, lines, "whitespace")

    def test_nonexistent_source_is_red(self):
        self.write_pin(source=self.root / "not-there")
        rc, lines = self.run_check()
        self.assert_red(rc, lines, "failed (rc")
        self.assertIn("rev-parse HEAD", lines[0])

    def test_source_that_is_a_file_is_red(self):
        self.write_pin(source=self.repo / "other.txt")
        rc, lines = self.run_check()
        self.assert_red(rc, lines, "failed (rc")

    def test_symlink_loop_source_is_red_not_a_traceback(self):
        loop = self.root / "loop"
        os.symlink(loop, loop)
        self.write_pin(source=loop)
        rc, lines = self.run_check()
        self.assert_red(rc, lines, "cannot be resolved")

    # --- the pin document -------------------------------------------------------

    def test_absent_pin_is_unknown(self):
        rc, lines = self.run_check()
        self.assertEqual(rc, 2, lines)
        self.assertTrue(lines[0].startswith("UNKNOWN"), lines)

    def test_dangling_symlink_pin_is_unknown_like_the_kernel(self):
        """``source_for`` uses ``pin.exists()``, so a dangling link is absence and
        the channel starts on the respawner's tree; UNKNOWN (not GREEN) says so."""
        os.symlink(self.root / "not-there.json", self.pin_path)
        rc, lines = self.run_check()
        self.assertEqual(rc, 2, lines)
        self.assertTrue(lines[0].startswith("UNKNOWN"), lines)

    def test_pin_path_that_is_a_directory_is_red(self):
        """``source_for`` accepts it as existing and then raises on read_text, so
        every channel refuses to start; UNKNOWN here would be a false GREEN."""
        self.pin_path.mkdir()
        rc, lines = self.run_check(git=lambda *a, **k: self.fail("git must not run"))
        self.assert_red(rc, lines, "not one the kernel accepts")

    def test_invalid_json_is_red(self):
        self.pin_path.write_text("{", encoding="utf-8")
        rc, lines = self.run_check()
        self.assert_red(rc, lines, "not one the kernel accepts")

    def test_non_utf8_pin_is_red(self):
        self.pin_path.write_bytes(b"\xff\xfe{\x00")
        rc, lines = self.run_check()
        self.assert_red(rc, lines, "not one the kernel accepts")

    def test_non_object_json_is_red(self):
        self.pin_path.write_text(json.dumps([1, 2]), encoding="utf-8")
        rc, lines = self.run_check()
        self.assert_red(rc, lines, "not one the kernel accepts")

    def test_deeply_nested_pin_is_red_not_a_traceback(self):
        self.pin_path.write_text("[" * 100000 + "]" * 100000, encoding="utf-8")
        rc, lines = self.run_check()
        self.assert_red(rc, lines, "not one the kernel accepts")

    def test_version_other_than_one_is_red(self):
        self.write_pin(version=2)
        rc, lines = self.run_check()
        self.assert_red(rc, lines, "version 2")

    def test_sha_of_wrong_length_is_red(self):
        self.write_pin(sha="abc")
        rc, lines = self.run_check()
        self.assert_red(rc, lines, "40-character")

    def test_non_string_sha_is_red(self):
        self.write_pin(sha=0)
        rc, lines = self.run_check()
        self.assert_red(rc, lines, "40-character")

    def test_non_string_source_is_red(self):
        self.pin_path.write_text(
            json.dumps({"version": 1, "source": 7, "sha": self.sha}), encoding="utf-8")
        rc, lines = self.run_check()
        self.assert_red(rc, lines, "is not a string")

    def test_missing_keys_are_red(self):
        self.pin_path.write_text(json.dumps({"version": 1}), encoding="utf-8")
        rc, lines = self.run_check()
        self.assert_red(rc, lines, "not one the kernel accepts")

    # --- git itself -------------------------------------------------------------

    def test_git_that_cannot_run_is_red(self):
        """``checked_source`` lets the OSError/TimeoutExpired propagate, so a git
        that cannot run is a startup refusal, not a missing diagnosis."""
        self.write_pin()
        rc, lines = self.run_check(git=lambda *a, **k: None)
        self.assert_red(rc, lines, "could not run")

    def test_git_that_fails_is_red(self):
        self.write_pin()
        rc, lines = self.run_check(git=lambda *a, **k: (128, "", "fatal: boom"))
        self.assert_red(rc, lines, "failed (rc 128)")
        self.assertIn("fatal: boom", lines[0])

    def test_run_git_without_git_on_path_is_none(self):
        saved = os.environ.get("PATH")
        os.environ["PATH"] = ""
        try:
            self.assertIsNone(runtime_pin.run_git(self.repo, "rev-parse", "HEAD"))
        finally:
            if saved is None:
                os.environ.pop("PATH", None)
            else:
                os.environ["PATH"] = saved

    # --- shape of the tool ------------------------------------------------------

    def test_check_writes_nothing(self):
        self.write_pin()
        before = self.snapshot()
        self.run_check()
        self.assertEqual(before, self.snapshot())

    def snapshot(self):
        return sorted((str(p), p.stat().st_size, p.stat().st_mtime_ns)
                      for p in self.root.rglob("*"))

    def test_main_returns_zero_and_prints_the_green_line(self):
        self.write_pin()
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            rc = runtime_pin.main(["--site", str(self.site)])
        self.assertEqual(rc, 0)
        self.assertIn("GREEN", out.getvalue())
        self.assertIn(self.sha[:12], out.getvalue())

    def test_main_returns_one_and_prints_the_red_line(self):
        self.write_pin(sha="0" * 40)
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            rc = runtime_pin.main(["--site", str(self.site)])
        self.assertEqual(rc, 1)
        self.assertIn("RED", out.getvalue())

    def test_main_returns_two_and_prints_the_unknown_line(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            rc = runtime_pin.main(["--site", str(self.site)])
        self.assertEqual(rc, 2)
        self.assertIn("UNKNOWN", out.getvalue())


if __name__ == "__main__":
    unittest.main()
