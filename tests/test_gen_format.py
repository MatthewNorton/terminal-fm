"""`radio format` and `radio gen` with the Stability API stubbed out: wav+mp3 end to end (the
manual test described in CLAUDE.md, as code), plus gen's argument grammar and refusals.

Nothing here talks to the network. `_api_post`, `_poll_result` and `_balance` are replaced, and
the real HTTP helpers are patched to fail the test if anything reaches them. `_poll_result` is
stubbed to save a real WAV: an ffmpeg sine when ffmpeg is installed (the wav+mp3 encode tests
need it and are skipped without it), otherwise a stdlib `wave` sine.
"""

import json
import math
import shutil
import struct
import subprocess
import unittest
import wave
from unittest import mock

from radio_test_support import patch, radio, reset_home, run

FFMPEG = shutil.which("ffmpeg")


def write_sine(dest, seconds, use_ffmpeg):
    """A real 44.1 kHz stereo 16-bit WAV, the shape Stable Audio 3 returns for output_format=wav."""
    if use_ffmpeg:
        subprocess.run([FFMPEG, "-nostdin", "-y", "-loglevel", "error", "-f", "lavfi",
                        "-i", f"sine=frequency=440:duration={seconds}:sample_rate=44100",
                        "-ac", "2", "-c:a", "pcm_s16le", str(dest)], check=True, timeout=120)
        return
    rate = 44100
    with wave.open(str(dest), "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(rate)
        frames = bytearray()
        for i in range(int(rate * seconds)):
            v = int(8000 * math.sin(2 * math.pi * 440 * i / rate))
            frames += struct.pack("<hh", v, v)
        w.writeframes(bytes(frames))


class FakeStability:
    """Stands in for the API: records every submit and writes a file on every poll."""

    def __init__(self, use_ffmpeg=False, balances=(100.0, 48.0)):
        self.submits = []
        self.use_ffmpeg = use_ffmpeg
        self.balances = list(balances)

    def api_post(self, url, key, fields):
        self.submits.append(dict(fields))
        return "200", json.dumps({"id": f"gen-{len(self.submits)}"})

    def poll_result(self, key, sc, gen_id, dest, timeout=180):
        fields = self.submits[int(gen_id.split("-")[1]) - 1]
        if fields["output_format"] == "wav":
            write_sine(dest, fields["duration"], self.use_ffmpeg)
        else:
            dest.write_bytes(b"ID3\x04\x00\x00\x00\x00\x00\x00fake mp3 payload")
        return True, None

    def balance(self, key):
        return self.balances.pop(0) if self.balances else None


class GenTestCase(unittest.TestCase):
    def setUp(self):
        reset_home()
        radio.KEY_FILE.write_text("test-key-not-real", encoding="utf-8")
        self.config(radio.load_config())
        for name in ("_http_post", "_http_get", "_curl"):       # tripwires: no real network
            self.patch(name, side_effect=AssertionError(f"{name} reached in a stubbed test"))
        self.patch("_llm_paths", return_value=(None, None))      # no local model, ever
        self.patch("GEN_IDEA", new=None)

    def patch(self, name, **kw):
        return patch(self, name, **kw)

    def config(self, cfg):
        """Install a config as a fresh process would see it (CONFIG is read once at import)."""
        p = mock.patch.object(radio, "CONFIG", cfg)
        p.start()
        self.addCleanup(p.stop)

    def use_api(self, fake):
        self.patch("_api_post", side_effect=fake.api_post)
        self.patch("_poll_result", side_effect=fake.poll_result)
        self.patch("_balance", side_effect=fake.balance)

    def history(self):
        return [json.loads(line) for line in
                radio.HISTORY_FILE.read_text(encoding="utf-8").splitlines() if line.strip()]

    def lines(self, out):
        return [ln for ln in out.splitlines() if ln.strip()]


class Format(GenTestCase):
    def saved(self):
        return radio.load_config()["stability_api"]["output_format"]

    def test_show(self):
        _, out = run(radio.cmd_format, [])
        self.assertIn("Output format: mp3", out)
        self.assertIn("wav+mp3", out)

    def test_set_and_aliases(self):
        self.patch("_ffmpeg", return_value="ffmpeg")
        for arg, want in (("wav", "wav"), (".MP3", "mp3"), ("WAV+MP3", "wav+mp3"),
                          ("mp3+wav", "wav+mp3"), ("wav", "wav")):
            with self.subTest(arg=arg):
                _, out = run(radio.cmd_format, [arg])
                self.assertIn(f"Output format: {want}", out)
                self.assertEqual(self.saved(), want)
        self.assertEqual(radio.load_config()["stability_api"]["model"], "stable-audio-3")

    def test_unknown_format_not_saved(self):
        _, out = run(radio.cmd_format, ["flac"])
        self.assertIn("Unknown format 'flac'", out)
        self.assertFalse(radio.CONFIG_FILE.exists())

    def test_wav_mp3_refused_without_ffmpeg(self):
        self.patch("_ffmpeg", return_value=None)
        _, out = run(radio.cmd_format, ["wav+mp3"])
        self.assertIn("needs ffmpeg", out)
        self.assertIn("Not saved", out)
        self.assertFalse(radio.CONFIG_FILE.exists())

    def test_corrupt_config_left_alone(self):
        radio.CONFIG_FILE.write_text("{broken", encoding="utf-8")
        _, out = run(radio.cmd_format, ["wav"])
        self.assertIn("Not saved", out)
        self.assertEqual(radio.CONFIG_FILE.read_text(encoding="utf-8"), "{broken")


class GenGrammar(GenTestCase):
    def setUp(self):
        super().setUp()
        self.fake = FakeStability()
        self.use_api(self.fake)

    def test_refusals_spend_nothing(self):
        cases = [
            (["calm piano", "5"], "Refusing: 5s"),           # one number < 10 is a duration
            (["calm piano", "1", "2", "3"], "Usage"),        # the old third number (steps)
            (["calm piano", "0", "auto"], "Usage"),
            (["calm piano", "abc"], "Usage"),
            (["calm piano", "2", "long"], "Usage"),
            ([], "Usage"),
        ]
        for args, want in cases:
            with self.subTest(args=args):
                _, out = run(radio.cmd_gen, args)
                self.assertIn(want, out)
        self.assertEqual(self.fake.submits, [])
        self.assertEqual(radio.get_library(), [])

    def test_large_count_needs_a_typed_yes(self):
        with mock.patch("builtins.input", side_effect=EOFError):
            _, out = run(radio.cmd_gen, ["calm piano", "21", "30"])
        self.assertIn("Cancelled. Nothing spent.", out)
        with mock.patch("builtins.input", return_value="no"):
            _, out = run(radio.cmd_gen, ["calm piano", "21", "30"])
        self.assertIn("Cancelled", out)
        self.assertEqual(self.fake.submits, [])

    def test_prompt_token_limit_boundary(self):
        # No tokenizer in the test home, so the count is the ceil(chars/4) estimate.
        _, out = run(radio.cmd_gen, ["x" * 1025, "30"])
        self.assertIn("Refusing: the prompt is about 257 tokens", out)
        self.assertIn("Nothing spent.", out)
        self.assertEqual(self.fake.submits, [])
        _, out = run(radio.cmd_gen, ["x" * 1024, "30"])
        self.assertNotIn("Refusing", out)
        self.assertEqual(len(self.fake.submits), 1)

    def test_one_number_is_a_duration(self):
        _, out = run(radio.cmd_gen, ["calm piano", "218"])
        self.assertEqual(len(self.fake.submits), 1)
        self.assertEqual(self.fake.submits[0]["duration"], 218)
        self.assertEqual(self.lines(out)[0], "Length: user decided 218s")

    def test_auto_pick_without_a_model(self):
        _, out = run(radio.cmd_gen, ["dark techno", "2", "auto"])
        self.assertEqual([s["duration"] for s in self.fake.submits], [240, 240])
        self.assertEqual(self.lines(out)[0], "Length: keyword rules decided 240s")


class GenSaves(GenTestCase):
    def set_format(self, fmt):
        cfg = radio.load_config()
        cfg["stability_api"]["output_format"] = fmt
        self.config(cfg)

    def test_mp3_four_line_block_and_history(self):
        fake = FakeStability()
        self.use_api(fake)
        _, out = run(radio.cmd_gen, ["Calm piano!", "12"])
        lines = self.lines(out)
        self.assertEqual(lines, [
            "Length: user decided 12s",
            "Prompt: Calm piano!",
            "Cost: 52 credits",
            f"Folder: {radio.OUTDIR.name} / track(s) added: 1 / total: 1 track",
        ])
        sub = fake.submits[0]
        self.assertEqual((sub["prompt"], sub["model"], sub["steps"], sub["duration"], sub["output_format"]),
                         ("Calm piano!", "stable-audio-3", 8, 12, "mp3"))
        lib = radio.get_library()
        self.assertEqual(len(lib), 1)
        self.assertRegex(lib[0].name, r"^calm-piano-\d{8}-\d{6}-1\.mp3$")
        rec = self.history()[-1]
        self.assertEqual((rec["prompt"], rec["duration"], rec["file"], rec["source"]),
                         ("Calm piano!", 12, lib[0].name, "stability-api"))
        self.assertNotIn("kind", rec)

    def test_cost_unknown_when_balance_unreadable(self):
        fake = FakeStability(balances=())
        self.use_api(fake)
        _, out = run(radio.cmd_gen, ["calm piano", "12"])
        self.assertIn("Cost: unknown", out)

    def test_no_key_says_nothing_was_sent(self):
        radio.KEY_FILE.unlink()
        fake = FakeStability()
        self.use_api(fake)
        with mock.patch.dict(radio.os.environ):
            radio.os.environ.pop("STABILITY_API_KEY", None)
            _, out = run(radio.cmd_gen, ["calm piano", "12"])
        lines = self.lines(out)
        self.assertTrue(lines[2].startswith("No API key yet."), lines)
        self.assertEqual(lines[-2], "Cost: 0 credits (nothing sent)")
        self.assertNotIn("unknown", out)
        self.assertEqual(fake.submits, [])
        self.assertEqual(radio._balance.call_count, 0)

    def test_failed_submits_are_not_reported_as_nothing_sent(self):
        fake = FakeStability(balances=(100.0, 100.0))
        self.use_api(fake)
        self.patch("_api_post", return_value=("500", "server error"))
        _, out = run(radio.cmd_gen, ["calm piano", "12"])
        self.assertIn("FAILED (1/1) submit HTTP 500", out)
        self.assertIn("Cost: 0 credits", self.lines(out))
        self.assertNotIn("nothing sent", out)

    def test_plain_wav(self):
        self.set_format("wav")
        self.use_api(FakeStability())
        run(radio.cmd_gen, ["calm piano", "12"])
        lib = radio.get_library()
        self.assertEqual([p.suffix for p in lib], [".wav"])
        self.assertFalse((radio.OUTDIR / radio.WAV_SUBDIR).exists())

    def test_wav_mp3_without_ffmpeg_keeps_the_wav_playable(self):
        self.set_format("wav+mp3")
        self.patch("_ffmpeg", return_value=None)
        fake = FakeStability(use_ffmpeg=False)
        self.use_api(fake)
        _, out = run(radio.cmd_gen, ["calm piano", "12"])
        self.assertEqual(fake.submits[0]["output_format"], "wav")
        self.assertIn("MP3 (1/1) not made (ffmpeg not found); kept the WAV in "
                      f"{radio.OUTDIR.name} instead.", out)
        lib = radio.get_library()
        self.assertEqual([p.suffix for p in lib], [".wav"])
        self.assertEqual(list((radio.OUTDIR / radio.WAV_SUBDIR).iterdir()), [])
        self.assertEqual(self.history()[-1]["file"], lib[0].name)
        self.assertIn("track(s) added: 1", out)

    @unittest.skipUnless(FFMPEG, "ffmpeg not on PATH: the wav+mp3 encode needs it")
    def test_wav_mp3_batch_encodes_each_take(self):
        # Through the real path: cmd_format persists the choice, a fresh config is read the way a
        # new process would, then gen saves WAV masters in _wav and plays MP3s from the library.
        _, out = run(radio.cmd_format, ["wav+mp3"])
        self.assertIn(f"{radio.OUTDIR.name}/{radio.WAV_SUBDIR}", out)
        self.config(radio.load_config())
        fake = FakeStability(use_ffmpeg=True)
        self.use_api(fake)
        _, out = run(radio.cmd_gen, ["calm piano", "2", "5"])
        self.assertEqual([s["output_format"] for s in fake.submits], ["wav", "wav"])
        self.assertIn("track(s) added: 2 / total: 2 tracks", out)
        self.assertNotIn("not made", out)
        lib = radio.get_library()
        masters = sorted((radio.OUTDIR / radio.WAV_SUBDIR).iterdir())
        self.assertEqual([p.suffix for p in lib], [".mp3", ".mp3"])
        self.assertEqual([p.stem for p in masters], [p.stem for p in lib])
        for mp3, wav in zip(lib, masters):
            head = mp3.read_bytes()[:3]
            self.assertTrue(head == b"ID3" or (head[0] == 0xFF and head[1] & 0xE0 == 0xE0),
                            f"{mp3.name} does not start like an MP3: {head!r}")
            self.assertEqual(wav.read_bytes()[:4], b"RIFF")
            with wave.open(str(wav)) as w:
                self.assertAlmostEqual(w.getnframes() / w.getframerate(), 5.0, places=2)
        self.assertEqual([r["file"] for r in self.history()], [p.name for p in lib])

    @unittest.skipUnless(FFMPEG, "ffmpeg not on PATH: the wav+mp3 encode needs it")
    def test_wav_mp3_longest_track(self):
        # Production scale: 380 s is ENH_DUR_MAX, a 67 MB WAV master.
        self.set_format("wav+mp3")
        self.use_api(FakeStability(use_ffmpeg=True))
        _, out = run(radio.cmd_gen, ["long ambient drone", "380"])
        self.assertNotIn("not made", out)
        lib = radio.get_library()
        self.assertEqual([p.suffix for p in lib], [".mp3"])
        probe = shutil.which("ffprobe")
        if probe:
            secs = subprocess.run([probe, "-v", "error", "-show_entries", "format=duration",
                                   "-of", "default=nw=1:nk=1", str(lib[0])],
                                  capture_output=True, text=True, timeout=60).stdout.strip()
            self.assertAlmostEqual(float(secs), 380.0, delta=0.2)


if __name__ == "__main__":
    unittest.main()
