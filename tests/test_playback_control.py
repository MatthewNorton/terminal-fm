"""`stop`, `pause`, `play --say` (with and without a track selection) and `key show`.

The stop/pause race is simulated deterministically: `_kill_daemon` is stubbed to do what the real
daemon did in the failing trials (a track ended during the kill, so it started the next player and
recorded its pid in state.json). The players are real child processes, so the real `kill()` path
(name check, then taskkill or SIGTERM) runs. Nothing here plays audio or starts a daemon.
"""

import io
import json
import os
import stat
import subprocess
import sys
import time
import unittest
from pathlib import Path
from unittest import mock

from radio_test_support import own_line, radio, reset_home, run


def _sleeper():
    return subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"],
                            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL,
                            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))


class RaceCase(unittest.TestCase):
    def setUp(self):
        reset_home()
        for name, kw in (("detect_player", {"return_value": (None, None)}),
                         ("_daemon_alive", {"return_value": True})):
            p = mock.patch.object(radio, name, **kw)
            p.start()
            self.addCleanup(p.stop)

    def player(self):
        """A real process standing in for ffplay, plus the program name state.json records."""
        p = _sleeper()
        self.addCleanup(p.wait, 30)
        self.addCleanup(p.kill)
        deadline = time.time() + 10
        name = None
        while name is None and time.time() < deadline:     # wait for it to exist, not a timing assert
            name = radio._proc_name(p.pid)
            time.sleep(0.05)
        self.assertTrue(name, "the stand-in player never appeared in the process list")
        return p, name

    def playing(self, proc, name, track, started):
        radio.write_state(status="playing", daemon_pid=999999, daemon_exe="python.exe",
                          player_pid=proc.pid if proc else 424242, player_exe=name,
                          now_playing=track, player_started=started, player_offset=0)

    def daemon_switches_to(self, proc, name, track, started):
        """_kill_daemon stub: the track ended mid-kill and the daemon recorded the next player."""
        def fake_kill_daemon(st):
            self.playing(proc, name, track, started)
        p = mock.patch.object(radio, "_kill_daemon", side_effect=fake_kill_daemon)
        p.start()
        self.addCleanup(p.stop)

    def assert_killed(self, proc):
        proc.wait(timeout=30)        # bounded wait for the kill to land; raises if it never does
        self.assertIsNotNone(proc.returncode)


class StopRace(RaceCase):
    def test_kills_the_player_started_during_the_daemon_kill(self):
        old, name = self.player()
        old.kill()
        old.wait(timeout=30)          # the first-read player has already exited, as in the trials
        new, _ = self.player()
        self.playing(old, name, "a.mp3", time.time() - 5.9)
        self.daemon_switches_to(new, name, "b.mp3", time.time())
        _, out = run(radio.cmd_stop, [])
        self.assertIn("Radio stopped.", out)
        self.assert_killed(new)
        st = radio.read_state()
        self.assertEqual((st["status"], st["player_pid"]), ("stopped", None))

    def test_kills_both_when_the_first_read_player_is_still_alive(self):
        old, name = self.player()
        new, _ = self.player()
        self.playing(old, name, "a.mp3", time.time() - 5.9)
        self.daemon_switches_to(new, name, "b.mp3", time.time())
        run(radio.cmd_stop, [])
        self.assert_killed(new)
        self.assert_killed(old)

    def test_no_race_kills_the_one_player(self):
        cur, name = self.player()
        self.playing(cur, name, "a.mp3", time.time() - 2)
        p = mock.patch.object(radio, "_kill_daemon")
        p.start()
        self.addCleanup(p.stop)
        run(radio.cmd_stop, [])
        self.assert_killed(cur)


class PauseRace(RaceCase):
    def test_position_comes_from_the_player_found_after_the_kill(self):
        old, name = self.player()
        old.kill()
        old.wait(timeout=30)
        new, _ = self.player()
        self.playing(old, name, "a.mp3", time.time() - 100)       # 100 s in: a stale position
        self.daemon_switches_to(new, name, "b.mp3", time.time() - 3)
        _, out = run(radio.cmd_pause, [])
        self.assert_killed(new)
        saved = json.loads(radio.RESUME_FILE.read_text(encoding="utf-8"))
        self.assertEqual(saved["track"], "b.mp3")
        self.assertGreater(saved["offset"], 2.5)
        self.assertLess(saved["offset"], 60)                       # not the old track's 100 s
        st = radio.read_state()
        self.assertEqual((st["status"], st["now_playing"]), ("paused", "b.mp3"))
        self.assertIn("Paused at 0:0", out)
        self.assertIn("- b", out)

    def test_track_that_just_started_leaves_nothing_to_resume(self):
        old, name = self.player()
        old.kill()
        old.wait(timeout=30)
        new, _ = self.player()
        self.playing(old, name, "a.mp3", time.time() - 100)
        self.daemon_switches_to(new, name, "b.mp3", time.time())   # under a second in
        _, out = run(radio.cmd_pause, [])
        self.assert_killed(new)
        self.assertFalse(radio.RESUME_FILE.exists())
        self.assertIn("nothing to resume", out)
        self.assertEqual(radio.read_state()["status"], "stopped")

    def test_between_tracks_after_the_kill(self):
        old, name = self.player()
        self.playing(old, name, "a.mp3", time.time() - 100)
        def track_ended(st):          # the old player exits while the daemon is being killed
            old.kill()
            old.wait(timeout=30)
        p = mock.patch.object(radio, "_kill_daemon", side_effect=track_ended)
        p.start()
        self.addCleanup(p.stop)
        _, out = run(radio.cmd_pause, [])
        self.assertFalse(radio.RESUME_FILE.exists())
        self.assertIn("Paused between tracks, nothing to resume", out)
        self.assertEqual(radio.read_state()["status"], "stopped")


class PlaySay(unittest.TestCase):
    def setUp(self):
        reset_home()

    def play(self, args):
        """`radio play` with a player found and the daemon launch stubbed; returns the Popen mock."""
        with mock.patch.object(radio, "detect_player", return_value=("ffplay", None)), \
                mock.patch.object(radio.subprocess, "Popen") as popen, \
                mock.patch.object(radio.time, "sleep"):
            run(radio.cmd_play, args)
        return popen

    def test_empty_library_queues_nothing(self):
        _, out = run(radio.cmd_play, ["--say", "Good evening, this is the sign-on."])
        self.assertIn("Library is empty", out)
        self.assertEqual(radio.queue_files(), [])

    def test_no_player_queues_nothing(self):
        (radio.OUTDIR / "a.mp3").write_bytes(b"ID3")
        with mock.patch.object(radio, "detect_player", return_value=(None, None)):
            _, out = run(radio.cmd_play, ["--say", "Good evening."])
        self.assertIn("No audio player found", out)
        self.assertEqual(radio.queue_files(), [])

    def test_sign_on_is_queued_first_when_play_starts(self):
        (radio.OUTDIR / "a.mp3").write_bytes(b"ID3")
        radio.queue_add("an older hook line")
        self.assertEqual(self.play(["--say", "Good evening."]).call_count, 1)   # the daemon launch
        files = radio.queue_files()
        self.assertEqual(len(files), 2)
        self.assertTrue(files[0].name.startswith("0-"))
        self.assertEqual(files[0].read_text(encoding="utf-8").strip(), "Good evening.")

    def test_selection_with_sign_on_plays_the_selection(self):
        for name in ("a.mp3", "b.mp3", "c.mp3"):
            (radio.OUTDIR / name).write_bytes(b"ID3")
        run(radio.cmd_list, [])                                      # the numbers play refers to
        for args in (["3,1", "--say", "Smooth jazz tonight."], ["--say", "Smooth jazz tonight.", "3", "1"]):
            with self.subTest(args=args):
                for f in radio.queue_files():
                    f.unlink()
                radio.PLAYLIST_FILE.unlink(missing_ok=True)
                self.assertEqual(self.play(args).call_count, 1)
                self.assertEqual(json.loads(radio.PLAYLIST_FILE.read_text(encoding="utf-8")),
                                 ["c.mp3", "a.mp3"])
                files = radio.queue_files()
                self.assertEqual([f.read_text(encoding="utf-8").strip() for f in files],
                                 ["Smooth jazz tonight."])
                self.assertTrue(files[0].name.startswith("0-"))


class KeyShow(unittest.TestCase):
    def setUp(self):
        reset_home()
        p = mock.patch.dict(os.environ)
        p.start()
        self.addCleanup(p.stop)
        os.environ.pop("STABILITY_API_KEY", None)

    def test_no_key_names_the_next_step(self):
        _, out = run(radio.cmd_key, ["show"])
        lines = out.splitlines()
        self.assertIn("Key: (none)", lines[0])
        self.assertIn(own_line(radio._self_cmd("key")), lines)   # the exact command, on its own line
        self.assertIn(radio.KEY_ENV_NOTE, lines)

    def test_prompt_without_a_terminal_refuses_instead_of_waiting(self):
        # Windows getpass ignores redirected stdin and waits on the console forever. A real null
        # device matters: on Windows isatty() is true for NUL, which a StringIO never shows.
        for label, make in (("null device", lambda: open(os.devnull)), ("pipe", lambda: io.StringIO(""))):
            with self.subTest(stdin=label), make() as stdin:
                no_terminal = mock.patch.object(radio.sys, "stdin", stdin)
                typed = mock.patch("getpass.getpass", return_value="typed-key-not-real")
                with no_terminal, typed:
                    _, out = run(radio.cmd_key, [])
                self.assertIn("No terminal to type the key into", out)
                self.assertFalse(radio.KEY_FILE.exists())

    def typed_key(self, key):
        """cmd_key at a real terminal with `key` typed at the hidden prompt."""
        console = mock.patch.object(radio, "_stdin_is_console", return_value=True)
        typed = mock.patch("getpass.getpass", return_value=key)
        with console, typed:
            return run(radio.cmd_key, [])[1]

    def test_key_file_is_created_owner_only(self):
        # The temp file must be born 0600 with O_EXCL; writing it under the umask and chmod-ing
        # afterwards left the key readable by other users in between.
        real_open, opened = os.open, []

        def spy(path, flags, mode=0o777, *a, **kw):
            opened.append((Path(path).name, flags, mode))
            return real_open(path, flags, mode, *a, **kw)

        with mock.patch.object(radio.os, "open", side_effect=spy):
            out = self.typed_key("test-key-not-real")
        self.assertIn("Key saved to", out)
        self.assertEqual(radio.KEY_FILE.read_text(encoding="utf-8"), "test-key-not-real")
        tmp = [o for o in opened if o[0].startswith(".key.") and o[0].endswith(".tmp")]
        self.assertEqual(len(tmp), 1, opened)
        self.assertEqual(tmp[0][2], 0o600)
        self.assertTrue(tmp[0][1] & os.O_EXCL and tmp[0][1] & os.O_CREAT)
        self.assertEqual(list(radio.ROOT.glob(".key.*.tmp")), [])
        if os.name != "nt":
            self.assertEqual(stat.S_IMODE(radio.KEY_FILE.stat().st_mode), 0o600)

    def test_key_written_when_the_rename_is_refused(self):
        # Windows refuses os.replace while a reader has .key open; the key must still be saved.
        radio.KEY_FILE.write_text("old-key-not-real", encoding="utf-8")
        real_replace, calls = os.replace, []

        def refuse_first(src, dst):
            calls.append(Path(dst).name)
            if len(calls) == 1:
                raise PermissionError("in use")
            return real_replace(src, dst)

        with mock.patch.object(radio.os, "replace", side_effect=refuse_first):
            self.typed_key("new-key-not-real")
        self.assertEqual(radio.KEY_FILE.read_text(encoding="utf-8"), "new-key-not-real")
        self.assertEqual(list(radio.ROOT.glob(".key.*.tmp")), [])

    def test_stored_key_has_no_hint(self):
        radio.KEY_FILE.write_text("test-key-not-real", encoding="utf-8")
        _, out = run(radio.cmd_key, ["show"])
        self.assertEqual(len(out.strip().splitlines()), 1)
        self.assertIn("source: .key file", out)


if __name__ == "__main__":
    unittest.main()
