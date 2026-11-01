"""release_check.py: every pattern catches a planted bad line and passes its look-alike good line.

The bad values are built at run time from neutral parts so this file does not trip the scan it
tests. The split-literal cases cover a string written as "ab" + "cd".
"""

import contextlib
import io
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

REPO = Path(__file__).resolve().parent.parent
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

import release_check as rc  # noqa: E402

BS = chr(92)
GITIGNORE = (REPO / ".gitignore").read_text(encoding="utf-8").splitlines()


def j(*parts, sep="/"):
    return sep.join(parts)


class Patterns(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name, "tree")
        self.root.mkdir()
        self.side = Path(self.tmp.name, "side")
        self.side.mkdir()
        # No .release_markers is picked up from the repo beside release_check.py.
        patcher = mock.patch.object(rc, "ROOT", str(self.side))
        patcher.start()
        self.addCleanup(patcher.stop)

    def check(self, text, markers=None):
        Path(self.root, "notes.md").write_text(text + "\n", encoding="utf-8")
        args = ["--root", str(self.root)]
        if markers is not None:
            mfile = Path(self.side, "markers.txt")
            mfile.write_text(markers, encoding="utf-8")
            args += ["--markers", str(mfile)]
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = rc.main(args)
        return code, out.getvalue()

    def assertFlags(self, text, name, markers=None):
        code, out = self.check(text, markers)
        self.assertEqual(code, 1, out)
        self.assertIn("notes.md:1: " + name, out)
        return out

    def assertClean(self, text, markers=None):
        code, out = self.check(text, markers)
        self.assertEqual(code, 0, out)
        self.assertIn("release_check: clean (1 files", out)

    def test_windows_home_path(self):
        self.assertFlags("see " + j("C:", "Users", "bob", "x.py"), "home-path")
        self.assertFlags("see " + j("C:", "Users", "bob", "x.py", sep=BS), "home-path")
        self.assertFlags("see " + j("d:", "users", "Bob") + " too", "home-path")

    def test_windows_placeholders_pass(self):
        self.assertClean("python " + j("C:", "Users", "<you>", ".claude", "radio", "statusline.py"))
        self.assertClean(j("C:", "Users", "%USERNAME%", ".claude", sep=BS))
        self.assertClean(j("C:", "Users", "$env:USERNAME"))

    def test_posix_home_path(self):
        self.assertFlags('cd "' + j("", "home", "bob", "radio") + '"', "home-path")
        self.assertFlags("open " + j("", "Users", "bob", "Music"), "home-path")

    def test_posix_placeholders_and_urls_pass(self):
        self.assertClean("cd " + j("", "home", "<you>", "radio"))
        self.assertClean("cd ~" + j("", "home"))
        self.assertClean("see " + j("https:", "", "example.com", "home", "bob"))

    def test_personal_email(self):
        self.assertFlags("mail " + "@".join(["bob.smith", "gmail.com"]), "personal-email")
        self.assertFlags("mail " + "@".join(["bob", "Proton.me"]), "personal-email")

    def test_noreply_and_project_addresses_pass(self):
        self.assertClean("author " + "@".join(["123+bob", "users.noreply.github.com"]))
        self.assertClean("mail " + "@".join(["security", "example.org"]))

    def test_api_key(self):
        self.assertFlags("key " + "sk-" + "A1" * 12, "api-key:sk-")
        self.assertClean("key sk-short")

    def test_local_marker_reported_by_line_number_never_by_text(self):
        markers = "# who I am\n\nzz-plain-marker\nzz-other-marker\n"
        out = self.assertFlags("x zz-other-marker y", "local-marker:4", markers)
        self.assertNotIn("zz-other-marker", out)
        self.assertIn("2 local markers", out)

    def test_split_literal_is_seen_joined(self):
        markers = "zz-split-marker\n"
        for text in ('name = "zz-spl" + "it-marker"', "name = 'zz-spl' 'it-marker'",
                     'name = "zz-spl"+"it-marker"'):
            with self.subTest(text=text):
                self.assertFlags(text, "local-marker:1", markers)
        self.assertFlags('p = "' + j("C:", "Users") + '/" + "bob"', "home-path")

    def test_marker_missing_from_text_passes(self):
        self.assertClean("nothing personal here", "zz-plain-marker\n")

    def test_no_marker_file_says_so(self):
        code, out = self.check("plain")
        self.assertEqual(code, 0, out)
        self.assertIn("no local markers", out)

    def test_marker_file_beside_the_checked_tree_is_found(self):
        Path(self.root, rc.MARKERS_FILE).write_text("zz-root-marker\n", encoding="utf-8")
        self.assertFlags("x zz-root-marker", "local-marker:1")

    def test_missing_marker_file_is_a_usage_error(self):
        err = io.StringIO()
        with contextlib.redirect_stderr(err), contextlib.redirect_stdout(io.StringIO()):
            code = rc.main(["--root", str(self.root), "--markers", str(Path(self.side, "nope.txt"))])
        self.assertEqual(code, 2)

    def test_marker_file_never_ships(self):
        self.assertTrue(rc.is_ignored(rc.MARKERS_FILE))
        self.assertIn(rc.MARKERS_FILE, GITIGNORE)

    def test_ignored_is_gitignore(self):
        self.assertEqual([ln for ln in GITIGNORE if ln and not ln.startswith("#")], rc.IGNORED)

    def test_claude_code_personal_files_never_ship(self):
        for rel in (".claude/settings.local.json", ".claude/worktrees/agent-1/radio.py",
                    ".claude/worktrees/agent-1/.claude/CLAUDE.md", "CLAUDE.local.md"):
            self.assertTrue(rc.is_ignored(rel), rel)
        self.assertFalse(rc.is_ignored(".claude/CLAUDE.md"))


if __name__ == "__main__":
    unittest.main()
