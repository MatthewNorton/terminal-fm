"""Files shared between processes: the config overlay (load_config / set_config), atomic writes,
and the pid-plus-program-name process checks (alive / kill)."""

import contextlib
import gc
import json
import os
import subprocess
import sys
import time
import unittest
from unittest import mock

from radio_test_support import radio, reset_home, run


class LoadConfig(unittest.TestCase):
    def setUp(self):
        reset_home()

    def test_defaults_without_a_file(self):
        self.assertFalse(radio.CONFIG_FILE.exists())
        self.assertEqual(radio.load_config(), radio.DEFAULT_CONFIG)

    def test_shallow_merge_overlay(self):
        radio.CONFIG_FILE.write_text(json.dumps({
            "volume": 50,
            "stability_api": {"duration": 90},
            "dj": {"breaking_news": True},
            "extra": 1,
        }), encoding="utf-8")
        cfg = radio.load_config()
        self.assertEqual(cfg["volume"], 50)
        self.assertEqual(cfg["stability_api"]["duration"], 90)
        self.assertEqual(cfg["stability_api"]["model"], "stable-audio-3")   # sibling default kept
        self.assertEqual(cfg["dj"], {"announce_when_idle": False, "breaking_news": True})
        self.assertEqual(cfg["extra"], 1)
        self.assertEqual(radio.DEFAULT_CONFIG["stability_api"]["duration"], 120)  # not mutated

    def test_scalar_replaces_a_section(self):
        radio.CONFIG_FILE.write_text(json.dumps({"dj": "off"}), encoding="utf-8")
        self.assertEqual(radio.load_config()["dj"], "off")

    def test_unparsable_file_gives_defaults(self):
        radio.CONFIG_FILE.write_text("{not json", encoding="utf-8")
        self.assertEqual(radio.load_config(), radio.DEFAULT_CONFIG)


class SetConfig(unittest.TestCase):
    def setUp(self):
        reset_home()

    def read(self):
        return json.loads(radio.CONFIG_FILE.read_text(encoding="utf-8"))

    def test_creates_file_and_merges(self):
        ok, out = run(radio.set_config, "dj", "breaking_news", True)
        self.assertTrue(ok)
        self.assertEqual(out, "")
        ok, _ = run(radio.set_config, "dj", "announce_when_idle", True)
        ok2, _ = run(radio.set_config, None, "library_dir", "jazz")
        self.assertTrue(ok and ok2)
        self.assertEqual(self.read(), {"dj": {"breaking_news": True, "announce_when_idle": True},
                                       "library_dir": "jazz"})

    def test_keeps_unrelated_settings(self):
        radio.CONFIG_FILE.write_text(json.dumps({"volume": 40, "stability_api": {"ca_bundle": "x.pem"}}),
                                     encoding="utf-8")
        run(radio.set_config, "stability_api", "output_format", "wav")
        self.assertEqual(self.read(), {"volume": 40, "stability_api": {"ca_bundle": "x.pem",
                                                                       "output_format": "wav"}})

    def test_non_dict_section_is_replaced(self):
        radio.CONFIG_FILE.write_text(json.dumps({"dj": "off"}), encoding="utf-8")
        run(radio.set_config, "dj", "breaking_news", False)
        self.assertEqual(self.read(), {"dj": {"breaking_news": False}})

    def test_refuses_to_overwrite_unparsable_config(self):
        for bad in ("{not json", "[1, 2]", '"text"', ""):
            with self.subTest(bad=bad):
                radio.CONFIG_FILE.write_text(bad, encoding="utf-8")
                ok, out = run(radio.set_config, "stability_api", "output_format", "wav")
                self.assertFalse(ok)
                self.assertIn("Not saved", out)
                self.assertEqual(radio.CONFIG_FILE.read_text(encoding="utf-8"), bad)


class AtomicWrite(unittest.TestCase):
    def setUp(self):
        reset_home()
        self.path = radio.ROOT / "atomic.json"

    def leftovers(self):
        return [p.name for p in radio.ROOT.iterdir() if p.name.endswith(".tmp")]

    def test_writes_and_replaces_without_temp_files(self):
        radio._atomic_write(self.path, "first")
        radio._atomic_write(self.path, "café → second")
        self.assertEqual(self.path.read_text(encoding="utf-8"), "café → second")
        self.assertEqual(self.leftovers(), [])

    def test_direct_write_when_rename_is_refused(self):
        # Windows refuses os.replace while a reader holds the target open.
        self.path.write_text("old", encoding="utf-8")
        with mock.patch.object(radio.os, "replace", side_effect=PermissionError("in use")):
            radio._atomic_write(self.path, "new")
        self.assertEqual(self.path.read_text(encoding="utf-8"), "new")
        self.assertEqual(self.leftovers(), [])

    def test_write_json_and_state(self):
        radio._write_json(self.path, {"a": [1, 2]})
        self.assertEqual(json.loads(self.path.read_text(encoding="utf-8")), {"a": [1, 2]})
        radio.write_state(status="playing", daemon_pid=None, now_playing="x.mp3")
        self.assertEqual(radio.read_state(), {"status": "playing", "daemon_pid": None,
                                              "now_playing": "x.mp3"})

    def test_torn_state_reads_as_stopped(self):
        radio.STATE_FILE.write_text('{"status": "play', encoding="utf-8")
        self.assertEqual(radio.read_state()["status"], "stopped")


def _sleeper():
    """A child process this test owns (the only kind these tests may kill)."""
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    return subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"],
                            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL, creationflags=flags)


def _posix_self_exe(executable, proc_name):
    """Patches for radio._self_exe() as a POSIX daemon started from `executable` computes it,
    with the OS reporting `proc_name` for every pid."""
    stack = contextlib.ExitStack()
    stack.enter_context(mock.patch.object(radio, "IS_WIN", False))
    stack.enter_context(mock.patch.object(radio, "_SELF_EXE", None))
    stack.enter_context(mock.patch.object(radio.sys, "executable", executable))
    stack.enter_context(mock.patch.object(radio, "_proc_name", return_value=proc_name))
    return stack


class Alive(unittest.TestCase):
    def test_no_pid(self):
        for pid in (None, 0, ""):
            with self.subTest(pid=pid):
                self.assertFalse(radio.alive(pid))
                self.assertFalse(radio.alive(pid, "python"))

    def test_own_process_with_its_recorded_name(self):
        me = os.getpid()
        name = radio._proc_name(me)
        self.assertTrue(name)
        self.assertTrue(radio.alive(me))
        self.assertTrue(radio.alive(me, name))
        self.assertTrue(radio.alive(me, name.upper()))           # case-insensitive

    def test_recycled_pid_running_another_program(self):
        # The pid exists, but state.json recorded a different program for it.
        me = os.getpid()
        for other in ("ffplay.exe", "ffplay", "mpv", "/usr/bin/afplay"):
            with self.subTest(expect=other):
                self.assertFalse(radio.alive(me, other))

    def test_name_match_is_a_substring_of_the_stem(self):
        # Documents current behaviour: the recorded name is cut at its first "." and matched as a
        # substring, so a short or generic recorded name ("py") also matches.
        me = os.getpid()
        name = radio._proc_name(me)
        self.assertTrue(radio.alive(me, name[:2]))

    def test_daemon_records_the_name_the_os_reports(self):
        # A macOS framework Python runs as "Python" while sys.executable ends in python3.14; the
        # sys.executable name never matched, so a live daemon looked dead to stop/pause/status.
        with _posix_self_exe("/opt/homebrew/bin/python3.14", "Python"):
            self.assertEqual(radio._self_exe(), "Python")
            self.assertTrue(radio.alive(4242, radio._self_exe()))
            self.assertFalse(radio.alive(4242, "python3.14"))     # what used to be recorded

    def test_daemon_name_falls_back_to_sys_executable(self):
        for got in (None, "?"):
            with self.subTest(proc_name=got), _posix_self_exe("/usr/bin/python3", got):
                self.assertEqual(radio._self_exe(), "python3")

    def test_cvlc_is_recorded_as_the_vlc_it_execs(self):
        # cvlc is a shell wrapper that execs vlc; the OS reports the running player as "vlc".
        with mock.patch.object(radio, "_proc_name", return_value="vlc"):
            self.assertTrue(radio.alive(4242, radio.PLAYER_PROCESS["cvlc"]))
            self.assertFalse(radio.alive(4242, "cvlc"))           # what used to be recorded

    def test_own_name_matches_alive(self):
        with mock.patch.object(radio, "_SELF_EXE", None):
            self.assertTrue(radio.alive(os.getpid(), radio._self_exe()))

    def test_exited_process_is_not_alive(self):
        p = subprocess.Popen([sys.executable, "-c", "pass"], stdin=subprocess.DEVNULL,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                             creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        p.wait(timeout=60)
        pid = p.pid
        del p
        gc.collect()
        deadline = time.time() + 10
        while radio.alive(pid) and time.time() < deadline:
            time.sleep(0.2)
        self.assertFalse(radio.alive(pid))
        self.assertIsNone(radio._proc_name(pid))


class Kill(unittest.TestCase):
    def test_mismatched_name_is_never_killed(self):
        p = _sleeper()
        self.addCleanup(p.wait, 30)
        self.addCleanup(p.kill)
        time.sleep(0.3)
        radio.kill(p.pid, "definitely-not-this-program.exe")
        time.sleep(0.5)
        self.assertIsNone(p.poll(), "kill() terminated a process whose name did not match")

    def test_matching_name_is_killed(self):
        p = _sleeper()
        self.addCleanup(p.wait, 30)
        self.addCleanup(p.kill)
        deadline = time.time() + 10
        name = None
        while name is None and time.time() < deadline:
            name = radio._proc_name(p.pid)
            time.sleep(0.1)
        self.assertTrue(name)
        self.assertTrue(radio.alive(p.pid, name))
        radio.kill(p.pid, name)
        p.wait(timeout=30)
        self.assertIsNotNone(p.returncode)

    def test_no_pid_is_a_no_op(self):
        radio.kill(None)
        radio.kill(0, "python")


if __name__ == "__main__":
    unittest.main()
