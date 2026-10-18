"""dj.py's engine log names the real reason for a fallback.

With no kokoro/ folder Kokoro is skipped, not failed, so the SAPI line must not point at a
kokoro-fail line that was never written. The engine column values are unchanged. No speech is
produced: subprocess.run is stubbed and only the SAPI branch is reachable.
"""

import unittest
from pathlib import Path
from unittest import mock

from radio_test_support import radio, reset_home  # noqa: F401  (sets AI_RADIO_HOME first)

import dj  # noqa: E402

if Path(dj.ROOT).resolve() != Path(radio.ROOT).resolve():
    raise RuntimeError(f"dj.ROOT is {dj.ROOT}, expected the test home {radio.ROOT}")


class FallbackReason(unittest.TestCase):
    def setUp(self):
        reset_home()
        for target, kw in ((dj, {"IS_WIN": True}), (dj.sys, {"platform": "win32"})):
            for name, val in kw.items():
                p = mock.patch.object(target, name, val)
                p.start()
                self.addCleanup(p.stop)
        for name, kw in (("which", {"return_value": None}),):
            p = mock.patch.object(dj.shutil, name, **kw)
            p.start()
            self.addCleanup(p.stop)
        self.run_ = mock.patch.object(dj.subprocess, "run").start()
        self.addCleanup(mock.patch.stopall)

    def log(self):
        return [ln.split("\t") for ln in dj.ENGINE_LOG.read_text(encoding="utf-8").splitlines()]

    def test_zero_model_install_says_not_installed(self):
        self.assertEqual(dj.speak("hello from the test", dj.dj_config()), "sapi")
        rows = self.log()
        self.assertEqual([r[1] for r in rows], ["kokoro-skip", "sapi"])
        self.assertEqual(rows[1][2], "ROBOTIC FALLBACK - kokoro not installed")
        self.assertNotIn("render failed", rows[1][2])

    def test_installed_but_failing_points_at_the_fail_line(self):
        kdir = dj.KOKORO_DIR
        kdir.mkdir()
        (kdir / "kokoro-v1.0.onnx").write_bytes(b"x")
        (kdir / "voices-v1.0.bin").write_bytes(b"x")
        with mock.patch.object(dj, "_kokoro_python", return_value=None):
            self.assertEqual(dj.speak("hello again", dj.dj_config()), "sapi")
        rows = self.log()
        self.assertEqual([r[1] for r in rows], ["kokoro-fail", "sapi"])
        self.assertEqual(rows[1][2], "ROBOTIC FALLBACK - kokoro render failed (see prior kokoro-fail line)")

    def test_fail_line_shows_the_exception_not_the_utf16_warnings(self):
        # On Windows onnxruntime's warnings come first, in UTF-16; the exception is the last line.
        kdir = dj.KOKORO_DIR
        kdir.mkdir()
        (kdir / "kokoro-v1.0.fp16.onnx").write_bytes(b"x")
        (kdir / "voices-v1.0.bin").write_bytes(b"x")
        warning = "2026-10-13 [W:onnxruntime:, constant_folding.cc:212]\n".encode("utf-16-le")
        exc = b"Traceback (most recent call last):\nonnxruntime.InvalidArgument: Unexpected input data type\n"
        self.run_.return_value = mock.Mock(returncode=1, stderr=warning + exc)
        with mock.patch.object(dj, "_kokoro_python", return_value="C:/py/python.exe"):
            self.assertEqual(dj.speak("hello once more", dj.dj_config()), "sapi")
        fail = self.log()[0]
        self.assertEqual(fail[1], "kokoro-fail")
        self.assertEqual(fail[2], "rc=1 (C:/py/python.exe) onnxruntime.InvalidArgument: Unexpected input data type")


if __name__ == "__main__":
    unittest.main()
