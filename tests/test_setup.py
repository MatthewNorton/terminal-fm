"""First-run help: `setup`, the `setup :` line in `status`, the commands the key messages print,
the hook launcher's note when no Python is found, and the statusline: the SessionStart copy of
statusline.py and the `>` that marks a playing track."""

import ast
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from radio_test_support import REPO, own_line, patch, radio, reset_home, run

HOOK = REPO / "hooks" / "radio-hook.sh"


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

    def setup_out(self, *args):
        return run(radio.cmd_setup, list(args))[1]


class Setup(SetupCase):
    def test_fresh_install_shows_one_step_at_a_time(self):
        patch(self, "detect_player", return_value=(None, None))
        patch(self, "_git_bash", return_value="C:/Program Files/Git/bin/bash.exe")
        out = self.setup_out()
        for row in ("[x] 1. Python", "[ ] 2. Audio player", "[ ] 3. Stability API key",
                    "[ ] 4. Session hooks", "[ ] 5. First track"):
            self.assertIn(row, out)
        self.assertIn("Step 2 of 5: Audio player", out)
        self.assertIn(own_line(radio._install_cmd()[1]), out.splitlines())
        self.assertNotIn(radio._self_cmd("key"), out)          # the key step waits its turn
        self.assertNotIn("Ready", out)

    def test_key_step_sets_the_command_apart(self):
        patch(self, "detect_player", return_value=("/usr/bin/ffplay", None))
        out = self.setup_out()
        lines = out.splitlines()
        self.assertIn("Step 3 of 5: Stability API key", out)
        i = lines.index(own_line(radio._self_cmd("key")))
        self.assertEqual((lines[i - 1], lines[i + 1]), ("", ""))   # blank lines around it: copies whole
        self.assertIn("Run /tfm setup again to check.", out)
        self.assertIn(radio.KEY_ENV_NOTE, lines)

    def test_all_set_says_ready(self):
        self.ready()
        (self.cfg / "settings.json").write_text(json.dumps(
            {"statusLine": {"type": "command", "command": "python3 ~/.claude/terminal-fm/statusline.py"}}),
            encoding="utf-8")
        out = self.setup_out()
        self.assertNotIn("[ ]", out.split("Optional extras")[0])
        self.assertIn("[x] 4. Session hooks: last ran 2026-10-17 09:00", out)
        self.assertIn("Ready: /tfm play", out)
        self.assertNotIn(radio.SETUP_RULE, out)
        self.assertIn("[x] statusline", out)

    def test_first_track_is_the_last_step(self):
        self.ready()
        (radio.OUTDIR / "a.mp3").unlink()
        out = self.setup_out()
        self.assertIn("Step 5 of 5: First track", out)
        self.assertIn(own_line("/tfm play"), out.splitlines())
        self.assertNotIn("Run /tfm setup again", out)

    def test_hooks_on_windows_without_git_bash(self):
        self.ready()
        radio.HOOK_SEEN.unlink()
        patch(self, "IS_WIN", new=True)
        patch(self, "_git_bash", return_value=None)
        out = self.setup_out()
        self.assertIn("Step 4 of 5: Session hooks", out)
        self.assertIn(own_line("winget install Git.Git"), out.splitlines())

    def test_wav_mp3_without_ffmpeg_is_a_step(self):
        self.ready()
        cfg = radio.load_config()
        cfg["stability_api"]["output_format"] = radio.BOTH_FORMATS
        patch(self, "CONFIG", new=cfg)
        patch(self, "_ffmpeg", return_value=None)
        out = self.setup_out()
        self.assertIn("Step 5 of 6: FFmpeg, for wav+mp3", out)
        self.assertIn(own_line(radio._install_cmd("ffmpeg")[1]), out.splitlines())

    def test_install_commands_on_every_os(self):
        for is_win, platform in ((True, "win32"), (False, "darwin"), (False, "linux")):
            with self.subTest(platform=platform), mock.patch.object(radio, "IS_WIN", is_win), \
                    mock.patch.object(radio.sys, "platform", platform):
                self.assertIn("ffmpeg", radio._install_cmd("ffmpeg")[1].lower())
                self.assertIn("python", radio._install_cmd("python")[1].lower())
                self.assertIn(radio._install_cmd()[1], radio._install_hint())

    def test_old_python_is_a_step(self):
        self.ready()
        patch(self, "PY_MIN", new=(99, 0))                # make this Python count as too old
        out = self.setup_out()
        self.assertIn(f"Step 1 of 5: Python 99.0 or newer (this is {sys.version.split()[0]})", out)
        self.assertIn(own_line(radio._install_cmd("python")[1]), out.splitlines())
        _, status = run(radio.cmd_status, [])
        self.assertIn("setup   : missing Python 99.0+", status)

    def test_status_flags_the_gaps(self):
        patch(self, "detect_player", return_value=(None, None))
        _, out = run(radio.cmd_status, [])
        self.assertIn("setup   : missing audio player, API key, tracks", out)
        reset_home()
        self.ready()
        _, out = run(radio.cmd_status, [])
        self.assertNotIn("setup   :", out)


class SetupExtras(SetupCase):
    def test_cmd_setup_names_every_extra(self):
        # cmd_setup compares its argument to an inline tuple, because readme_check.py reads the
        # keywords a command accepts from such comparisons; it must name every extra in the table.
        tree = ast.parse((REPO / "radio.py").read_text(encoding="utf-8"))
        fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "cmd_setup")
        inline = next({e.value for e in c.comparators[0].elts} for c in ast.walk(fn)
                      if isinstance(c, ast.Compare) and isinstance(c.comparators[0], ast.Tuple))
        self.assertEqual(inline, {name for name, *_ in radio._setup_extras()})

    def test_statusline_detection(self):
        settings = self.cfg / "settings.json"
        self.assertIsNone(radio._statusline_state())
        script = self.cfg / "my-line.js"
        script.write_text('fs.readFileSync(home + "/.claude/terminal-fm/nowplaying.txt")', encoding="utf-8")
        settings.write_text(json.dumps({"statusLine": {"command": f'node "{script}"'}}), encoding="utf-8")
        self.assertEqual(radio._statusline_state(), "radio")     # found inside the script it runs
        script.write_text("console.log('git branch')", encoding="utf-8")
        self.assertEqual(radio._statusline_state(), "other")
        radio._install_statusline()                               # what the session-start hook does
        out = self.setup_out("statusline")
        self.assertIn(own_line(str(radio.NOW_FILE)), out.splitlines())
        self.assertNotIn('"statusLine"', out)                     # never a snippet that replaces theirs

    def test_statusline_line_parses_as_settings(self):
        radio._install_statusline()
        out = self.setup_out("statusline")                        # no settings.json yet: create it
        self.assertIn(own_line(str(radio._settings_file())), out.splitlines())
        whole = next(ln.strip() for ln in out.splitlines() if ln.strip().startswith("{"))
        self.assertIn("statusline.py", json.loads(whole)["statusLine"]["command"])
        radio._settings_file().write_text("{}", encoding="utf-8")
        out = self.setup_out("statusline")                        # settings.json exists: one line to add
        entry = next(ln.strip() for ln in out.splitlines() if ln.strip().startswith('"statusLine"'))
        self.assertIn("statusline.py", json.loads("{" + entry + "}")["statusLine"]["command"])

    def test_statusline_waits_for_the_hooks(self):
        self.assertIn("finish /tfm setup first", self.setup_out("statusline"))

    def test_pages_name_this_installs_paths(self):
        for name, path in (("voice", radio.ROOT / "kokoro"), ("enhancer", radio.LLM_DIR),
                           ("tokens", radio.TOKENIZER_FILE)):
            with self.subTest(name):
                out = self.setup_out(name)
                self.assertIn("Status: not installed", out)
                self.assertIn(own_line(str(path)), out.splitlines())
                self.assertIn(f"Run /tfm setup {name} again to check.", out)

    def test_enhancer_lists_only_what_is_missing(self):
        patch(self, "_llm_paths", return_value=(None, str(radio.LLM_DIR / "m.gguf")))
        out = self.setup_out("enhancer")
        self.assertIn("missing llama-cli", out)
        self.assertNotIn("Qwen3", out)

    def test_installed_extras_say_so(self):
        patch(self, "_llm_paths", return_value=("llama-cli", str(radio.LLM_DIR / "m.gguf")))
        self.assertIn("Status: installed (m.gguf).", self.setup_out("enhancer"))
        radio.LLM_DIR.mkdir(parents=True, exist_ok=True)
        radio.TOKENIZER_FILE.write_text("{}", encoding="utf-8")
        self.assertIn("Status: installed.", self.setup_out("tokens"))

    def test_unknown_page_prints_usage(self):
        self.assertTrue(self.setup_out("bogus").startswith("Usage: radio setup"))


class PythonMinimum(unittest.TestCase):
    def test_hook_manifests_and_ci_use_radios_minimum(self):
        # These files can't import PY_MIN (shell, JSON, YAML), so every minimum they state must equal
        # it. readme_check.py does the same for README and the skill.
        low = "%d.%d" % radio.PY_MIN
        self.assertEqual(re.findall(r"^min=(\S+)", HOOK.read_text(encoding="utf-8"), re.M), [low])
        for manifest in ("plugin.json", "marketplace.json"):
            text = (REPO / ".claude-plugin" / manifest).read_text(encoding="utf-8")
            self.assertEqual(set(re.findall(r"Python (\d+\.\d+)\+", text)), {low}, manifest)
        ci = (REPO / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
        self.assertEqual(re.findall(r'python: \["([\d.]+)"', ci), [low])


class VoicePython(SetupCase):
    # kokoro-onnx caps the voice at PY_VOICE_MAX, below the Python the install commands name. A Python
    # that fits gets the pip step; a newer one gets steps for a second Python in its place. The limit
    # is patched, as test_old_python_is_a_step patches PY_MIN, so the Python running this can't matter.
    PIP = 'pip install -U "kokoro-onnx>=0.6" soundfile'
    AGAIN = "Run /tfm setup voice again to check."
    FITS, TOO_NEW = (99, 0), (3, 0)
    OSES = ((True, "win32"), (False, "darwin"), (False, "linux"))

    def page(self, done, limit, is_win=True, platform="win32"):
        with mock.patch.object(radio, "PY_VOICE_MAX", limit), mock.patch.object(radio, "IS_WIN", is_win), \
                mock.patch.object(radio.sys, "platform", platform):
            return run(radio._voice_page, done)[1]

    def test_a_python_that_fits_gets_only_the_pip_step(self):
        for done in (False, True):
            for is_win, platform in self.OSES:
                with self.subTest(done=done, platform=platform):
                    out = self.page(done, self.FITS, is_win, platform)
                    lines = out.splitlines()
                    self.assertIn("Install its Python packages in a terminal. They need Python 99.0 or older:", out)
                    self.assertIn(own_line(self.PIP), lines)
                    self.assertNotIn("dj.python", out)
                    self.assertEqual(self.AGAIN in out, not done)               # only before the download
                    self.assertEqual(f"  4. {self.AGAIN}" in lines, not done)    # one list
                    self.assertNotIn("  5. ", out)

    def test_a_newer_python_gets_a_second_python_instead(self):
        why = f"Its Python packages need Python 3.0 or older, and this is Python {sys.version.split()[0]}."
        first = {"win32": "winget install Python.Python.3.0", "darwin": "brew install python@3.0"}
        for done in (False, True):
            for is_win, platform in self.OSES:
                with self.subTest(done=done, platform=platform):
                    out = self.page(done, self.TOO_NEW, is_win, platform)
                    lines = out.splitlines()
                    self.assertIn(why, out)
                    self.assertNotIn(own_line(self.PIP), lines)              # replaced, not followed
                    py = "py -3.0" if is_win else "python3.0"
                    for line in (f"{py} -m {self.PIP}", str(radio.CONFIG_FILE)):
                        self.assertIn(own_line(line), lines)
                    for os_name, cmd in first.items():
                        self.assertEqual(own_line(cmd) in lines, os_name == platform)
                    self.assertEqual("with your system's package manager" in out, platform == "linux")
                    self.assertEqual(self.AGAIN in out, not done)
                    self.assertEqual(f"  7. {self.AGAIN}" in lines, not done)

    def test_printed_path_works_as_dj_python(self):
        # Pasted into config.json as printed: a C:\ path would be invalid JSON there, and the radio
        # would then ignore the whole file.
        line = next(ln for ln in self.page(False, self.TOO_NEW).splitlines()
                    if ln.startswith(own_line("py -")) and " -c " in ln)
        code = line.split(" -c ", 1)[1].strip('"')
        printed = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True,
                                 timeout=60).stdout.strip()
        self.assertNotIn("\\", printed)
        radio.CONFIG_FILE.write_text('{"dj": {"python": "%s"}}' % printed, encoding="utf-8")
        import dj
        self.assertEqual(dj._kokoro_python(dj.dj_config()), printed)

    def test_readme_states_the_same_limit_and_commands(self):
        top = "%d.%d" % radio.PY_VOICE_MAX
        readme = (REPO / "README.md").read_text(encoding="utf-8")
        voice = re.search(r"^### DJ voice$(.*?)^##", readme, re.S | re.M).group(1)
        needs = re.search(r"^### Requirements$(.*?)^### ", readme, re.S | re.M).group(1)
        for section in (voice, needs):
            self.assertIn(f"Python {top} or older", section)
        self.assertIn("(#dj-voice)", needs)
        for cmd in (self.PIP, f"py -{top} -m {self.PIP}"):                  # what the page prints
            self.assertIn(f"`{cmd}`", voice)
        for doc in ("README.md", "skills/tfm/SKILL.md"):         # nothing anywhere states another limit
            text = (REPO / doc).read_text(encoding="utf-8")
            self.assertLessEqual(set(re.findall(r"Python (\d+\.\d+) or older", text)), {top}, doc)
            self.assertLessEqual(set(re.findall(r"\bpy -(\d+\.\d+)", text)), {top}, doc)
            self.assertLessEqual(set(re.findall(r"pip install -U (\S+) soundfile", text)),
                                 {'"kokoro-onnx>=0.6"'}, doc)


class DefaultDataFolder(unittest.TestCase):
    def test_every_file_defaults_to_the_same_folder(self):
        # radio.py, dj.py, kokoro_tts.py and statusline.py each work out the data folder (statusline.py
        # is copied out alone, so it can't share the code); a file missed in a rename would split it.
        home = tempfile.mkdtemp(prefix="terminal-fm-home-")
        self.addCleanup(shutil.rmtree, home, True)
        env = {k: v for k, v in os.environ.items() if k != "TERMINAL_FM_HOME"}
        env.update(HOME=home, USERPROFILE=home)        # Path.home(): HOME on POSIX, USERPROFILE on Windows
        want = str(Path(home) / ".claude" / "terminal-fm")
        for module, expr in (("radio", "radio.ROOT"), ("dj", "dj.ROOT"), ("kokoro_tts", "kokoro_tts.ROOT"),
                             ("statusline", "statusline.data_dir()")):
            with self.subTest(module):
                code = f"import sys; sys.path.insert(0, {str(REPO)!r}); import {module}; print({expr})"
                got = subprocess.run([sys.executable, "-c", code], env=env, capture_output=True,
                                     text=True, timeout=60)
                self.assertEqual(got.stdout.strip(), want, got.stderr)


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
        self.assertTrue(out.startswith("No API key yet."), out)
        self.assertIn(own_line(radio._self_cmd("key")), out.splitlines())

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
        env = dict(os.environ, RADIO_HOOK_PYTHONS=pythons, TERMINAL_FM_HOME=str(radio.ROOT))
        return subprocess.run(["sh", str(HOOK), event], input="{}",
                              capture_output=True, text=True, env=env, timeout=60)

    def test_no_python_at_session_start_tells_user_and_claude(self):
        r = self.launch("SessionStart", "no-such-python-a no-such-python-b")
        self.assertEqual(r.returncode, 0)
        note = json.loads(r.stdout)
        for is_win, platform in ((True, "win32"), (False, "darwin"), (False, "linux")):
            with self.subTest(platform=platform), mock.patch.object(radio, "IS_WIN", is_win), \
                    mock.patch.object(radio.sys, "platform", platform):
                self.assertIn(radio._install_cmd("python")[1], note["systemMessage"])
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
