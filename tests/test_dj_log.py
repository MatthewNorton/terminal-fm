"""dj.py's engine log names the real reason for a fallback, and its Kokoro interpreter search ends
with the Pythons installed side by side.

With no kokoro/ folder Kokoro is skipped, not failed, so the SAPI line must not point at a
kokoro-fail line that was never written. The engine column values are unchanged. No speech is
produced and no interpreter runs: subprocess.run is stubbed and only the SAPI branch is reachable.
"""

import unittest
from pathlib import Path
from unittest import mock

from radio_test_support import radio, reset_home  # noqa: F401  (sets TERMINAL_FM_HOME first)

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


class SideBySidePython(unittest.TestCase):
    """A Python 3.13 installed beside a newer default is found without dj.python: after the usual
    candidates, PY_VOICE_MAX down to PY_VOICE_MIN, through `py -3.X` on Windows and python3.X on PATH
    elsewhere. Fakes stand in for every interpreter and for PATH."""
    PY = "C:/Windows/py.exe"
    PYTHON = str(Path("C:/Py314/python.exe"))    # in the OS's own form, like the pythonw.exe sibling

    def setUp(self):
        reset_home()
        self.path = {"python": self.PYTHON, "py": self.PY}             # what shutil.which finds
        self.versions = {}                                              # what `py -3.X` runs
        self.kokoro = set()                                             # the ones that have kokoro_onnx
        self.calls, self.asked = [], []
        for target, name, kw in ((dj.subprocess, "run", {"side_effect": self.fake_run}),
                                 (dj.shutil, "which", {"side_effect": self.fake_which}),
                                 (dj.sys, "executable", {"new": "C:/Py314/pythonw.exe"}),
                                 (dj, "IS_WIN", {"new": True})):
            p = mock.patch.object(target, name, **kw)
            p.start()
            self.addCleanup(p.stop)

    def fake_which(self, name):
        self.asked.append(name)
        return self.path.get(name)

    def fake_run(self, argv, **kw):
        self.calls.append(argv)
        if argv[0] == self.PY and argv[1].startswith("-3."):           # resolve: py -3.X -c <print path>
            exe = self.versions.get(argv[1][1:])
            return mock.Mock(returncode=0 if exe else 103, stdout=(exe or "").encode())
        return mock.Mock(returncode=0 if argv[0] in self.kokoro else 1)   # <exe> -c "import kokoro_onnx..."

    def resolved(self):
        return [c[1] for c in self.calls if c[0] == self.PY and c[1].startswith("-3.")]

    def test_finds_a_side_by_side_313_after_the_usual_candidates(self):
        self.versions = {"3.13": "C:/Py313/python.exe", "3.12": "C:/Py312/python.exe"}
        self.kokoro = {"C:/Py313/python.exe"}
        self.assertEqual(dj._kokoro_python({}), "C:/Py313/python.exe")
        self.assertEqual(dj.KOKORO_PY_CACHE.read_text(encoding="utf-8"), "C:/Py313/python.exe")
        first = next(i for i, c in enumerate(self.calls) if c[1] == "-3.13")
        self.assertEqual([c[0] for c in self.calls[:first]],                      # every usual one first
                         ["C:/Py314/pythonw.exe", self.PYTHON, self.PY])
        self.assertEqual(self.resolved(), ["-3.13"])                             # and stops at the winner

    def test_newest_first_down_to_kokoro_onnx_floor(self):
        self.versions = {"3.12": "C:/Py312/python.exe", "3.10": "C:/Py310/python.exe"}
        self.assertIsNone(dj._kokoro_python({}))
        self.assertEqual(self.resolved(), ["-3.13", "-3.12", "-3.11", "-3.10"])
        self.assertFalse(dj.KOKORO_PY_CACHE.exists())

    def test_a_usual_candidate_with_kokoro_skips_the_search(self):
        self.kokoro = {self.PYTHON}
        self.assertEqual(dj._kokoro_python({}), self.PYTHON)
        self.assertEqual(self.resolved(), [])

    def test_elsewhere_python3_x_on_path(self):
        self.path = {"python3": "/usr/bin/python3", "python3.12": "/usr/bin/python3.12"}
        self.kokoro = {"/usr/bin/python3.12"}
        with mock.patch.object(dj, "IS_WIN", False), mock.patch.object(dj.sys, "executable", "/usr/bin/python3"):
            self.assertEqual(dj._kokoro_python({}), "/usr/bin/python3.12")
        self.assertEqual([n for n in self.asked if n.startswith("python3.")], ["python3.13", "python3.12"])


if __name__ == "__main__":
    unittest.main()
