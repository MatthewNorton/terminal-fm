"""First-run help: `setup`, the `setup :` line in `status`, the commands the key messages print,
the hook launcher's note when no Python is found, and the statusline: the SessionStart copy of
statusline.py and the `>` that marks a playing track."""

import ast
import json
import os
import shlex
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from radio_test_support import REPO, patch, radio, reset_home, run


class SetupCase(unittest.TestCase):
    def setUp(self):
        reset_home()
        env = mock.patch.dict(os.environ)
        env.start()
        self.addCleanup(env.stop)
        os.environ.pop("STABILITY_API_KEY", None)
        cfg = tempfile.mkdtemp(prefix="terminal-fm-cfg-")
        self.addCleanup(shutil.rmtree, cfg, True)
        os.environ["CLAUDE_CONFIG_DIR"] = cfg          # never read the real ~/.claude/settings.json
        self.cfg = Path(cfg)
        patch(self, "_llm_paths", return_value=(None, None))

    def ready(self):
        patch(self, "detect_player", return_value=("/usr/bin/ffplay", None))
        radio.KEY_FILE.write_text("test-key-not-real", encoding="utf-8")
        (radio.OUTDIR / "a.mp3").write_bytes(b"ID3")
        radio.HOOK_SEEN.write_text("2026-10-17 09:00", encoding="utf-8")


class Setup(SetupCase):
    def test_fresh_install_lists_what_is_needed(self):
        patch(self, "detect_player", return_value=(None, None))
        patch(self, "_git_bash", return_value="C:/Program Files/Git/bin/bash.exe")
        _, out = run(radio.cmd_setup, [])
        lines = out.splitlines()
        needed = [ln for ln in lines if ln.strip().startswith("NEEDED")]
        self.assertEqual(len(needed), 3, out)                 # player, key, hooks
        self.assertIn("audio player: none found", needed[0])
        self.assertIn("Stability API key", needed[1])
        self.assertIn(radio._self_cmd("key"), out)            # the exact command, on its own line
        self.assertIn("haven't run yet", needed[2])
        self.assertTrue(any(ln.strip().startswith("next") and "gen" in ln for ln in lines), out)
        self.assertIn("Not ready yet", lines[-1])

    def test_all_set_says_ready(self):
        self.ready()
        (self.cfg / "settings.json").write_text(json.dumps(
            {"statusLine": {"type": "command", "command": "python3 ~/.claude/radio/statusline.py"}}),
            encoding="utf-8")
        _, out = run(radio.cmd_setup, [])
        self.assertNotIn("NEEDED", out)
        self.assertIn("session hooks: last ran 2026-10-17 09:00", out)
        self.assertIn("statusline: shows the radio", out)
        self.assertTrue(out.splitlines()[-1].startswith("Ready: "), out)

    def test_hooks_on_windows_without_git_bash(self):
        self.ready()
        radio.HOOK_SEEN.unlink()
        patch(self, "IS_WIN", new=True)
        patch(self, "_git_bash", return_value=None)
        _, out = run(radio.cmd_setup, [])
        self.assertIn("they need Git Bash", out)
        self.assertIn("winget install Git.Git", out)

    def test_statusline_detection(self):
        settings = self.cfg / "settings.json"
        self.assertIsNone(radio._statusline_state())
        script = self.cfg / "my-line.js"
        script.write_text('fs.readFileSync(home + "/.claude/radio/nowplaying.txt")', encoding="utf-8")
        settings.write_text(json.dumps({"statusLine": {"command": f'node "{script}"'}}), encoding="utf-8")
        self.assertEqual(radio._statusline_state(), "radio")     # found inside the script it runs
        script.write_text("console.log('git branch')", encoding="utf-8")
        self.assertEqual(radio._statusline_state(), "other")
        _, out = run(radio.cmd_setup, [])
        self.assertIn("yours doesn't show the radio", out)
        self.assertNotIn('"statusLine"', out)                     # never a snippet that replaces theirs

    def test_wav_mp3_without_ffmpeg_is_needed(self):
        self.ready()
        cfg = radio.load_config()
        cfg["stability_api"]["output_format"] = radio.BOTH_FORMATS
        patch(self, "CONFIG", new=cfg)
        patch(self, "_ffmpeg", return_value=None)
        _, out = run(radio.cmd_setup, [])
        self.assertIn(f"NEEDED ffmpeg, for `radio format wav+mp3`: {radio._install_hint('ffmpeg')}", out)

    def test_ffmpeg_hint_names_ffmpeg_on_every_os(self):
        for is_win, platform in ((True, "win32"), (False, "darwin"), (False, "linux")):
            with self.subTest(platform=platform), mock.patch.object(radio, "IS_WIN", is_win), \
                    mock.patch.object(radio.sys, "platform", platform):
                self.assertIn("ffmpeg", radio._install_hint("ffmpeg").lower())

    def test_status_flags_the_gaps(self):
        patch(self, "detect_player", return_value=(None, None))
        _, out = run(radio.cmd_status, [])
        self.assertIn("setup   : missing audio player, API key, tracks", out)
        reset_home()
        self.ready()
        _, out = run(radio.cmd_status, [])
        self.assertNotIn("setup   :", out)


class SelfCommand(unittest.TestCase):
    def test_windows_paths_with_spaces_get_the_call_operator(self):
        with mock.patch.object(radio, "IS_WIN", True), \
                mock.patch.object(radio.sys, "executable", "C:/Program Files/Python312/pythonw.exe"), \
                mock.patch.object(radio, "CODE_DIR", Path("D:/My Apps/radio")):
            cmd = radio._self_cmd("key")
        self.assertEqual(cmd, '& "C:/Program Files/Python312/python.exe" '
                              '"D:/My Apps/radio/radio.py" key')

    @unittest.skipUnless(os.name == "nt", "Windows backslash paths")
    def test_windows_paths_without_spaces_stay_bare(self):
        with mock.patch.object(radio, "IS_WIN", True), \
                mock.patch.object(radio.sys, "executable", r"C:\Python312\python.exe"), \
                mock.patch.object(radio, "CODE_DIR", Path(r"D:\Apps\radio")):
            self.assertEqual(radio._self_cmd("key"), "C:/Python312/python.exe D:/Apps/radio/radio.py key")

    @unittest.skipIf(os.name == "nt", "POSIX quoting")
    def test_posix_quoting_round_trips(self):
        with mock.patch.object(radio, "CODE_DIR", Path("/opt/my apps/radio")):
            cmd = radio._self_cmd("key")
        self.assertEqual(shlex.split(cmd)[1:], ["/opt/my apps/radio/radio.py", "key"])


class KeyMessages(SetupCase):
    def test_gen_without_key_prints_the_command(self):
        _, out = run(radio.source_stability_api, "lo-fi", 1, 30)
        self.assertTrue(out.startswith("No API key."), out)
        self.assertIn(radio._self_cmd("key"), out)

    def test_hook_marks_session_start_only(self):
        with open(os.devnull) as nul, mock.patch.object(radio.sys, "stdin", nul):
            run(radio.cmd_hook, ["Stop"])
            self.assertFalse(radio.HOOK_SEEN.exists())
            run(radio.cmd_hook, ["SessionStart"])
        self.assertRegex(radio.HOOK_SEEN.read_text(encoding="utf-8"), r"^\d{4}-\d\d-\d\d \d\d:\d\d$")


class StatuslineCopy(unittest.TestCase):
    def setUp(self):
        reset_home()

    def temp_files(self):
        return list(radio.ROOT.glob("statusline.py.*.tmp"))

    def test_copies_and_cleans_up(self):
        radio._install_statusline()
        self.assertEqual(radio.STATUSLINE_DST.read_bytes(), radio.STATUSLINE_SRC.read_bytes())
        self.assertEqual(self.temp_files(), [])

    def test_refused_rename_leaves_no_temp_file(self):
        # Windows refuses the rename while another hook (a second session, or an old and a new
        # plugin both installed) has the file open.
        with mock.patch.object(radio.os, "replace", side_effect=PermissionError("in use")):
            radio._install_statusline()
        self.assertEqual(self.temp_files(), [])

    def test_only_a_playing_track_writes_a_marker(self):
        # statusline.py, and any statusline following README, shows "playing" when the text has a `>`.
        texts = []
        for call in ast.walk(ast.parse((REPO / "radio.py").read_text(encoding="utf-8"))):
            if isinstance(call, ast.Call) and getattr(call.func, "id", "") == "write_now":
                texts.append("".join(n.value for n in ast.walk(call.args[0])
                                     if isinstance(n, ast.Constant) and isinstance(n.value, str)))
        playing = [t for t in texts if t.startswith("Terminal FM > ")]
        self.assertEqual(len(playing), 1, texts)
        self.assertEqual([t for t in texts if ">" in t], playing)


@unittest.skipUnless(shutil.which("sh"), "needs sh")
class HookLauncher(unittest.TestCase):
    def launch(self, event, pythons):
        env = dict(os.environ, RADIO_HOOK_PYTHONS=pythons, AI_RADIO_HOME=str(radio.ROOT))
        return subprocess.run(["sh", str(REPO / "hooks" / "radio-hook.sh"), event], input="{}",
                              capture_output=True, text=True, env=env, timeout=60)

    def test_no_python_at_session_start_tells_user_and_claude(self):
        r = self.launch("SessionStart", "no-such-python-a no-such-python-b")
        self.assertEqual(r.returncode, 0)
        note = json.loads(r.stdout)
        self.assertIn("winget install Python.Python.3.12", note["systemMessage"])
        ctx = note["hookSpecificOutput"]
        self.assertEqual(ctx["hookEventName"], "SessionStart")
        self.assertIn("do not search the disk", ctx["additionalContext"])

    def test_no_python_at_stop_is_silent(self):
        r = self.launch("Stop", "no-such-python")
        self.assertEqual((r.returncode, r.stdout), (0, ""))

    def test_with_python_prints_nothing(self):
        reset_home()
        r = self.launch("SessionStart", Path(sys.executable).as_posix())
        self.assertEqual((r.returncode, r.stdout), (0, ""))
        self.assertTrue(radio.HOOK_SEEN.exists())


if __name__ == "__main__":
    unittest.main()
