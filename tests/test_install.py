"""The automatic installs behind `setup <extra> install`: the checked, resumable download, the
archive unpacking, the plans the pages show and the installs run, the Hugging Face login lookup,
and the voice's interpreter. A local HTTP server stands in for GitHub and Hugging Face, so nothing
here uses the network, and every file lands in the temporary test home."""

import hashlib
import http.server
import io
import os
import shutil
import ssl
import sys
import tarfile
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
import zipfile
from pathlib import Path
from unittest import mock

from radio_test_support import HF_VARS, SetupCase, on_os, patch, radio, reset_home, run

import dj  # noqa: E402  (after radio_test_support, which points TERMINAL_FM_HOME at the test home)


class _Host(http.server.BaseHTTPRequestHandler):
    """Serves `server.routes`: path -> ("file", bytes) honours Range, ("norange", bytes) ignores
    it, ("short", bytes) sends half and stops, ("redirect", path), ("status", code). Each request's
    path and headers go to `server.seen`."""

    def do_GET(self):
        srv = self.server
        srv.seen.append((self.path, {k.lower(): v for k, v in self.headers.items()}))
        kind, value = srv.routes.get(self.path, ("status", 404))
        if kind in ("redirect", "status"):
            self.send_response(302 if kind == "redirect" else value)
            if kind == "redirect":
                self.send_header("Location", value)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        start, rng = 0, self.headers.get("Range")
        if rng and kind == "file":
            start = int(rng.split("=")[1].split("-")[0])
            self.send_response(206)
            self.send_header("Content-Range", f"bytes {start}-{len(value) - 1}/{len(value)}")
        else:
            self.send_response(200)
        body = value[start:len(value) // 2 if kind == "short" else len(value)]
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


class Fetch(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Host)
        cls.httpd.routes, cls.httpd.seen = {}, []
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()
        cls.base = f"http://127.0.0.1:{cls.httpd.server_address[1]}"

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()

    def setUp(self):
        reset_home()
        self.httpd.routes.clear()
        self.httpd.seen.clear()
        self.body = os.urandom(300_000)
        self.dest = radio.ROOT / "dl" / "file.bin"
        self.part = self.dest.with_name("file.bin.part")

    def fetch(self, route, **kw):
        self.httpd.routes["/f"] = route
        return radio._fetch(self.base + "/f", self.dest, len(self.body),
                            hashlib.sha256(self.body).hexdigest(), **kw)

    def test_a_download_is_checked_then_moved_into_place(self):
        self.assertIsNone(self.fetch(("file", self.body)))
        self.assertEqual(self.dest.read_bytes(), self.body)
        self.assertFalse(self.part.exists())
        self.assertEqual(self.httpd.seen[0][1]["user-agent"], radio.USER_AGENT)

    def test_a_stopped_download_continues_where_it_stopped(self):
        self.dest.parent.mkdir(parents=True)
        self.part.write_bytes(self.body[:100_000])
        self.assertIsNone(self.fetch(("file", self.body)))
        self.assertEqual(self.httpd.seen[0][1]["range"], "bytes=100000-")
        self.assertEqual(self.dest.read_bytes(), self.body)

    def test_a_server_that_ignores_the_range_gets_the_whole_file_again(self):
        self.dest.parent.mkdir(parents=True)
        self.part.write_bytes(b"x" * 100_000)                     # wrong bytes, but they get replaced
        self.assertIsNone(self.fetch(("norange", self.body)))
        self.assertEqual(self.dest.read_bytes(), self.body)

    def test_a_file_that_fails_the_check_is_deleted(self):
        err = self.fetch(("file", os.urandom(len(self.body))))
        self.assertIn("didn't match its published SHA-256, so it was deleted", err)
        self.assertFalse(self.dest.exists() or self.part.exists())

    def test_a_short_answer_keeps_what_came_for_next_time(self):
        err = self.fetch(("short", self.body))
        self.assertIn("the download stopped at", err)
        self.assertIn("Run the same command again to continue it", err)
        self.assertEqual(self.part.read_bytes(), self.body[:len(self.body) // 2])
        self.assertIsNone(self.fetch(("file", self.body)))         # ...and the next run finishes it
        self.assertEqual(self.dest.read_bytes(), self.body)

    def test_http_errors_name_the_host_and_a_refusal_says_what_to_do(self):
        self.assertEqual(self.fetch(("status", 404), refused="Accept the terms"), "127.0.0.1 answered HTTP 404")
        for code in (401, 403):
            self.assertEqual(self.fetch(("status", code), refused="Accept the terms"),
                             f"127.0.0.1 answered HTTP {code}. Accept the terms")

    def test_a_range_past_the_end_starts_over(self):
        self.dest.parent.mkdir(parents=True)
        self.part.write_bytes(b"x" * 10)
        self.assertEqual(self.fetch(("status", 416)), "127.0.0.1 answered HTTP 416")
        self.assertFalse(self.part.exists())

    def test_the_login_follows_a_redirect_only_on_the_same_host(self):
        # A second server on another port is another host to the redirect, as a CDN is.
        other = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Host)
        other.routes, other.seen = self.httpd.routes, self.httpd.seen
        threading.Thread(target=other.serve_forever, daemon=True).start()
        self.addCleanup(other.server_close)
        self.addCleanup(other.shutdown)
        self.httpd.routes["/cdn"] = ("file", self.body)
        for where, kept in (("/cdn", True), (f"http://127.0.0.1:{other.server_address[1]}/cdn", False)):
            with self.subTest(where):
                self.httpd.seen.clear()
                self.dest.unlink(missing_ok=True)
                self.assertIsNone(self.fetch(("redirect", where), token="not-a-real-token"))
                (first, sent), (second, followed) = self.httpd.seen
                self.assertEqual((first, sent["authorization"]), ("/f", "Bearer not-a-real-token"))
                self.assertEqual(second, "/cdn")
                self.assertEqual(followed.get("authorization"), "Bearer not-a-real-token" if kept else None)

    def test_only_a_network_failure_says_to_run_it_again(self):
        cert = urllib.error.URLError(ssl.SSLCertVerificationError(1, "certificate has expired"))
        for error, want in ((urllib.error.URLError("getaddrinfo failed"), "Run the same command again"),
                            (ConnectionResetError(10054, "reset"), "Run the same command again"),
                            (cert, "127.0.0.1's certificate didn't verify (URLError:"),
                            (PermissionError(13, "the .part is locked"), "the download failed (PermissionError:")):
            with self.subTest(type(error).__name__), \
                    mock.patch.object(urllib.request.OpenerDirector, "open", side_effect=error):
                err = self.fetch(("file", self.body))
                self.assertIn(want, err)
                self.assertEqual("Run the same command again" in err, "Run the same" in want)
        pem = radio.ROOT / "isrg.pem"                  # named only when it exists, so it was the one used
        with mock.patch.dict(radio.CONFIG["stability_api"], ca_bundle=str(pem)), \
                mock.patch.object(radio, "_ssl_context", return_value=ssl.create_default_context()), \
                mock.patch.object(urllib.request.OpenerDirector, "open", side_effect=cert):
            self.assertNotIn("ca_bundle", self.fetch(("file", self.body)))
            pem.write_text("not read: _ssl_context is patched", encoding="utf-8")
            self.assertTrue(self.fetch(("file", self.body)).endswith(
                f", checked against stability_api.ca_bundle ({pem})"))

    def test_a_file_already_there_is_not_downloaded_again(self):
        self.dest.parent.mkdir(parents=True)
        self.dest.write_bytes(self.body)
        self.assertIsNone(self.fetch(("file", self.body)))
        self.assertEqual(self.httpd.seen, [])


def _symlinks_work():
    d = tempfile.mkdtemp()
    try:
        os.symlink("target", os.path.join(d, "link"))
        return True
    except (OSError, NotImplementedError):
        return False
    finally:
        shutil.rmtree(d, ignore_errors=True)


class Unpack(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="terminal-fm-unpack-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.dest = self.tmp / "out"
        self.dest.mkdir()

    def tar(self, *members):
        """A .tar.gz of (name, kind, data or link target), kind being dir, file, sym or hard."""
        path = self.tmp / "a.tar.gz"
        with tarfile.open(path, "w:gz") as t:
            for name, kind, extra in members:
                info = tarfile.TarInfo(name)
                info.mode = 0o755
                info.type = {"dir": tarfile.DIRTYPE, "file": tarfile.REGTYPE,
                             "sym": tarfile.SYMTYPE, "hard": tarfile.LNKTYPE}[kind]
                if kind == "file":
                    info.size = len(extra)
                    t.addfile(info, io.BytesIO(extra))
                else:
                    info.linkname = extra if kind in ("sym", "hard") else ""
                    t.addfile(info)
        return path

    def test_a_zip_unpacks_as_it_is(self):
        path = self.tmp / "a.zip"
        with zipfile.ZipFile(path, "w") as z:
            z.writestr("llama-cli.exe", b"exe")
            z.writestr("ggml.dll", b"dll")
        self.assertIsNone(radio._unpack(path, self.dest))
        self.assertEqual(sorted(p.name for p in self.dest.iterdir()), ["ggml.dll", "llama-cli.exe"])

    def test_a_zip_reaching_outside_is_refused_whole(self):
        # On Windows "top/D:evil.dll" joins to D:evil.dll, outside the folder, so a drive in any part
        # counts. C: here: if the check ever slips, the file still lands inside the temp folder.
        for evil in ("../evil.dll", "C:evil.dll", "top/C:evil.dll", "top\\C:evil.dll"):
            with self.subTest(evil):
                path = self.tmp / "a.zip"
                with zipfile.ZipFile(path, "w") as z:
                    z.writestr("llama-cli.exe", b"exe")
                    z.writestr(evil, b"evil")
                self.assertIn("wasn't unpacked", radio._unpack(path, self.dest))
                self.assertEqual(list(self.dest.iterdir()), [])
                self.assertFalse((self.tmp / "evil.dll").exists())

    def test_a_tars_own_root_entry_is_skipped(self):
        # `tar -C dist .` writes "./" first; the path check reads it as no path at all.
        path = self.tar((".", "dir", None), ("./llama-b1", "dir", None), ("./llama-b1/llama-cli", "file", b"cli"))
        self.assertIsNone(radio._unpack(path, self.dest))
        self.assertEqual((self.dest / "llama-cli").read_bytes(), b"cli")
        self.assertIn("wasn't unpacked", radio._unpack(self.tar((".", "file", b"x")), self.dest))

    def test_a_tar_loses_its_top_folder_and_keeps_links_beside_their_files(self):
        if not _symlinks_work():
            self.skipTest("this system can't make symlinks; the .tar.gz builds are for macOS and Linux")
        path = self.tar(("llama-b1", "dir", None), ("llama-b1/llama-cli", "file", b"cli"),
                        ("llama-b1/libllama.so.0.7.0", "file", b"lib"),
                        ("llama-b1/libllama.so", "sym", "libllama.so.0.7.0"))
        self.assertIsNone(radio._unpack(path, self.dest))
        self.assertEqual((self.dest / "llama-cli").read_bytes(), b"cli")
        self.assertEqual(os.readlink(self.dest / "libllama.so"), "libllama.so.0.7.0")
        self.assertEqual((self.dest / "libllama.so").read_bytes(), b"lib")
        if os.name != "nt":
            self.assertTrue(os.access(self.dest / "llama-cli", os.X_OK))

    def test_a_tar_with_anything_but_files_and_sibling_links_is_refused_whole(self):
        top, ok = ("llama-b1", "dir", None), ("llama-b1/llama-cli", "file", b"cli")
        bad = {"absolute path": ("/etc/cron.d/x", "file", b"x"),
               "climbs out": ("llama-b1/../../x", "file", b"x"),
               "link out": ("llama-b1/x", "sym", "../../x"),
               "absolute link": ("llama-b1/x", "sym", "/etc/passwd"),
               "hard link": ("llama-b1/x", "hard", "llama-b1/llama-cli"),
               "second top folder": ("other/x", "file", b"x"),
               "file at the top": ("x", "file", b"x")}
        for why, member in bad.items():
            with self.subTest(why):
                shutil.rmtree(self.dest)
                self.dest.mkdir()
                self.assertIn("wasn't unpacked", radio._unpack(self.tar(top, ok, member), self.dest))
                self.assertEqual(list(self.dest.iterdir()), [])


class Pins(unittest.TestCase):
    def test_every_pin_is_a_size_and_a_sha256(self):
        pins = (list(radio.KOKORO_PINS.values()) + [a[1:] for a in radio.LLAMA_ASSETS.values()]
                + [radio.QWEN_PIN, radio.TOKENIZER_PIN])
        for size, sha in pins:
            self.assertGreater(size, 0)
            self.assertRegex(sha, r"^[0-9a-f]{64}$")
        self.assertEqual(set(radio.KOKORO_PINS), {dj.KOKORO_MODELS[0], dj.KOKORO_VOICES})
        self.assertEqual(radio.KOKORO_ONNX_MIN, (0, 6))
        self.assertEqual(set(radio.SETUP_COST), {name for name, *_ in radio._setup_extras()})

    def test_the_llama_build_for_each_system_and_processor(self):
        for platform, machine, want in (("win32", "AMD64", "win-cpu-x64.zip"), ("win32", "ARM64", "win-cpu-arm64.zip"),
                                        ("darwin", "arm64", "macos-arm64.tar.gz"), ("darwin", "x86_64", "macos-x64.tar.gz"),
                                        ("linux", "x86_64", "ubuntu-x64.tar.gz"), ("linux", "aarch64", "ubuntu-arm64.tar.gz"),
                                        ("linux", "riscv64", None), ("freebsd14", "amd64", None)):
            with self.subTest(platform=platform, machine=machine), \
                    mock.patch.object(radio.sys, "platform", platform), \
                    mock.patch("platform.machine", return_value=machine):
                asset = radio._llama_asset()
                self.assertEqual(asset and asset[0], want and f"llama-{radio.LLAMA_BUILD}-bin-{want}")


class InstallRunner(unittest.TestCase):
    def setUp(self):
        reset_home()

    def install(self, plan, installed=False):
        """`_install` on an extra whose plan is `plan`: a list of steps, or (None, why). Its output,
        after checking the exit code: 1 exactly when it printed `Not installed:`."""
        steps = (plan, None) if isinstance(plan, list) else plan
        code, out = run(radio._install, radio.Extra("demo", "", lambda: installed, None, lambda: steps, "it works."))
        self.assertEqual(code, 1 if "Not installed:" in out else 0)
        return out

    def test_steps_run_in_order_and_stop_at_the_first_that_fails(self):
        ran = []
        out = self.install([("one", 0, lambda: ran.append(1)), ("two", 0, lambda: ran.append(2) or "it broke"),
                            ("three", 0, lambda: ran.append(3))])
        self.assertEqual(ran, [1, 2])
        self.assertRegex(out, r"  one \.\.\. done \(\d+ s\)\n  two \.\.\. failed \(\d+ s\)\nNot installed: it broke\.\n$")

    def test_the_exit_code_reaches_the_command_line(self):
        with mock.patch.object(radio, "_install", return_value=1):
            self.assertEqual(run(radio.main, ["setup", "voice", "install"])[0], 1)
        self.assertIsNone(run(radio.main, ["setup", "voice", "now"])[0])    # anything else: no code, so 0

    def test_an_exception_is_reported_not_raised(self):
        out = self.install([("one", 0, mock.Mock(side_effect=OSError("disk full")))])
        self.assertIn("Not installed: OSError: disk full.", out)

    def test_all_done_says_what_changed(self):
        self.assertTrue(self.install([("one", 0, lambda: None)]).endswith("\nInstalled: it works.\n"))

    def test_already_installed_runs_nothing(self):
        self.assertEqual(self.install([("one", 0, self.fail)], installed=True),
                         "Already installed. /tfm setup demo says more.\n")

    def test_no_room_on_the_disk_refuses_before_anything_runs(self):
        with mock.patch.object(radio.shutil, "disk_usage", return_value=mock.Mock(free=1_000_000)):
            out = self.install([("one", 2_000_000_000, self.fail)])
        self.assertIn("Not installed: it needs about 2.0 GB free on the disk with", out)
        self.assertIn("which has 1 MB.", out)

    def test_a_plan_that_cant_run_says_why(self):
        self.assertEqual(self.install((None, "not possible here: no build.")), "Not installed: not possible here: no build.\n")

    def test_every_extra_says_how_it_ended(self):
        for extra in radio._setup_extras():
            with self.subTest(extra.name):
                self.assertTrue(extra.done.endswith(".") if extra.name != "statusline" else extra.done == "")
        statusline = radio._setup_extras()[0]._replace(installed=lambda: False)
        out = run(radio._install, statusline)[1]
        self.assertIn("Claude adds the statusline's line to settings.json itself", out)


class SetupGrammar(SetupCase):
    def setUp(self):
        super().setUp()
        self.calls = []
        patch(self, "_install", side_effect=lambda extra: self.calls.append(extra.name))

    def test_install_runs_that_extras_plan(self):
        for args, name in ((["voice", "install"], "voice"), (["ENHANCER", "Install"], "enhancer"),
                           (["tokens", "install"], "tokenizer"), (["statusline", "install"], "statusline")):
            run(radio.cmd_setup, args)
            self.assertEqual(self.calls.pop(), name)

    def test_anything_else_prints_usage(self):
        self.assertEqual(run(radio.cmd_setup, ["voice", "now"])[1], "Usage: radio setup voice [install]\n")
        self.assertEqual(run(radio.cmd_setup, ["voice", "install", "now"])[1], "Usage: radio setup voice [install]\n")
        self.assertTrue(run(radio.cmd_setup, ["install"])[1].startswith("Usage: radio setup |"))
        self.assertEqual(self.calls, [])


class Plans(SetupCase):
    """What each page's automatic install lists is what the install then runs."""

    def setUp(self):
        super().setUp()                                # SetupCase: no login, HF_TOKEN_PATH at no-login
        patch(self, "_voice_python", return_value="C:/Py312/python.exe")

    def test_the_voice_page_lists_its_steps_and_claudes_part(self):
        out = run(radio._voice_page, False)[1]
        need = radio.VOICE_ENV_BYTES + sum(size for size, _ in radio.KOKORO_PINS.values())
        self.assertIn(f"Automatic install (/tfm setup voice install), about {radio._size(need)} on disk:", out)
        for what, _, _ in radio._voice_todo()[0]:
            self.assertIn(f"  - {what}\n", out)
        self.assertIn("made with C:/Py312/python.exe", out)
        self.assertIn(radio._claude_part("voice"), out)
        self.assertIn("\nOr by hand:\n", out)

    def test_a_ready_python_needs_only_the_files(self):
        patch(self, "_voice_ready", return_value="C:/Py312/python.exe")
        steps = [what for what, _, _ in radio._voice_todo()[0]]
        self.assertEqual(steps, ["kokoro-v1.0.fp16.onnx (164 MB) from github.com", "voices-v1.0.bin (28 MB) from github.com",
                                 "a test line, rendered but not played"])

    def test_the_test_line_makes_the_ready_python_the_djs(self):
        # A cached Python that still exists outranks the one the plan found, so the check writes it first.
        patch(self, "_voice_ready", return_value="C:/PyB/python.exe")
        dj.KOKORO_PY_CACHE.write_text("C:/PyA-without-kokoro/python.exe", encoding="utf-8")
        seen = []
        with mock.patch.object(dj, "_kokoro_render",
                               side_effect=lambda text: seen.append(dj.KOKORO_PY_CACHE.read_text(encoding="utf-8"))):
            radio._voice_todo()[0][-1][2]()
        self.assertEqual(seen, ["C:/PyB/python.exe"])

    def test_a_pinned_dj_python_without_the_packages_stops_the_plan(self):
        pinned = radio.ROOT / "pinned-python.exe"
        pinned.write_bytes(b"")
        radio.set_config("dj", "python", str(pinned))
        steps, why = radio._voice_todo()
        self.assertIsNone(steps)
        self.assertIn(f"dj.python in config.json names {pinned}, which the DJ always uses", why)
        self.assertIn("Install kokoro-onnx 0.6 or newer and soundfile in that Python, or remove dj.python", why)
        radio.set_config("dj", "python", str(radio.ROOT / "gone.exe"))   # missing: dj.py doesn't use it either
        self.assertIsNotNone(radio._voice_todo()[0])

    def test_any_of_the_three_models_will_do(self):
        patch(self, "_voice_ready", return_value="C:/Py312/python.exe")
        dj.KOKORO_DIR.mkdir(parents=True)
        (dj.KOKORO_DIR / "kokoro-v1.0.int8.onnx").write_bytes(b"model")
        steps = [what for what, _, _ in radio._voice_todo()[0]]
        self.assertEqual(steps[0], "voices-v1.0.bin (28 MB) from github.com")

    def test_no_python_that_fits_gets_one_first_or_says_how(self):
        patch(self, "_voice_python", return_value=None)
        for platform, cmd in (("win32", "winget install Python.Python.3.13"), ("darwin", "brew install python@3.13")):
            with self.subTest(platform), on_os(platform):
                steps, _ = radio._voice_todo()
                self.assertEqual(steps[0][0], f"Python 3.13 for your user ({cmd})")
                self.assertIs(steps[0][2], radio._get_python)
        with on_os("linux"):
            steps, why = radio._voice_todo()
        self.assertIsNone(steps)
        self.assertIn("Install one with your package manager", why)

    def test_getting_python_runs_that_command_silently(self):
        ran = []
        patch(self, "_run", side_effect=lambda cmd, timeout: ran.append(cmd) or (0, ""))
        with on_os("win32"), mock.patch.object(radio.shutil, "which", return_value="C:/winget.exe"):
            self.assertIsNone(radio._get_python())          # _voice_python is patched to find it after
        self.assertEqual(ran[0][:3], ["C:/winget.exe", "install", "Python.Python.3.13"])
        self.assertIn("--silent", ran[0])
        self.assertEqual(ran[0][ran[0].index("--scope") + 1], "user")

    def test_the_enhancer_steps_fetch_what_they_name(self):
        got = []
        patch(self, "_get_llama", side_effect=lambda *a: got.append(("llama", a[0])))
        patch(self, "_fetch", side_effect=lambda url, dest, *a, **k: got.append(("fetch", dest.name)))
        patch(self, "_llm_check", return_value=None)
        with mock.patch.object(radio.sys, "platform", "linux"), mock.patch("platform.machine", return_value="x86_64"):
            steps, _ = radio._enhancer_todo()
            for _, _, action in steps:
                action()
        self.assertEqual(got, [("llama", f"llama-{radio.LLAMA_BUILD}-bin-ubuntu-x64.tar.gz"),
                               ("fetch", "Qwen3-4B-Instruct-2507-Q4_K_M.gguf")])
        self.assertIn("about 3 minutes at 100 Mbit/s, 33 at 10", steps[1][0])

    def test_the_enhancer_lists_only_whats_missing(self):
        patch(self, "_llm_paths", return_value=("llama-cli", None))
        steps = [what for what, _, _ in radio._enhancer_todo()[0]]
        self.assertEqual(len(steps), 2)
        self.assertTrue(steps[0].startswith("Qwen3-4B-Instruct-2507-Q4_K_M.gguf (2.5 GB"))

    def test_no_hugging_face_login_means_no_plan_yet(self):
        out = run(radio._tokenizer_page, False)[1]
        self.assertIn("Automatic install: it needs your Hugging Face login, and none was found", out)
        self.assertNotIn("(/tfm setup tokenizer install)", out)
        self.assertIn(str(radio.ROOT / "no-login"), out)               # where to save one

    def test_a_login_is_used_but_never_printed(self):
        os.environ["HF_TOKEN"] = "hf_secret_test_value"
        out = run(radio._tokenizer_page, False)[1]
        self.assertIn("(/tfm setup tokenizer install)", out)
        sent = []
        patch(self, "_fetch", side_effect=lambda *a, **k: sent.append(k["token"]) or "huggingface.co answered HTTP 403. "
                                                                                     + k["refused"])
        out += run(radio.cmd_setup, ["tokenizer", "install"])[1]
        self.assertEqual(sent, ["hf_secret_test_value"])
        self.assertIn("Accept Google's Gemma terms", out)
        self.assertNotIn("hf_secret_test_value", out)


class HuggingFaceLogin(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="terminal-fm-hf-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        env = mock.patch.dict(os.environ)
        env.start()
        self.addCleanup(env.stop)
        for var in HF_VARS:
            os.environ.pop(var, None)

    def test_where_the_login_is_read_from_first(self):
        tmp = self.tmp
        steps = [("XDG_CACHE_HOME", tmp, tmp / "huggingface" / "token"), ("HF_HOME", tmp / "hf", tmp / "hf" / "token"),
                 ("HF_TOKEN_PATH", tmp / "custom", tmp / "custom")]
        for var, value, file in steps:                             # each later one wins over the ones before
            file.parent.mkdir(parents=True, exist_ok=True)
            file.write_text(f"from-{var}\n", encoding="utf-8")
            os.environ[var] = str(value)
            self.assertEqual(radio._hf_token(), f"from-{var}")
        for var in ("HUGGING_FACE_HUB_TOKEN", "HF_TOKEN"):
            os.environ[var] = f" from-{var} "
            self.assertEqual(radio._hf_token(), f"from-{var}")

    def test_a_token_file_saved_by_hand_reads_in_any_of_its_encodings(self):
        # Windows PowerShell 5.1's > writes UTF-16 with a BOM; Notepad can save UTF-8 with one.
        file = self.tmp / "token"
        os.environ["HF_TOKEN_PATH"] = str(file)
        for encoding in ("utf-8", "utf-8-sig", "utf-16", "utf-16-be"):
            with self.subTest(encoding):
                data = "hf_abc123\r\n".encode(encoding)
                file.write_bytes(b"\xfe\xff" + data if encoding == "utf-16-be" else data)
                self.assertEqual(radio._hf_token(), "hf_abc123")
        file.write_bytes(b"\xff\xfe\x00\xd8")                  # half a UTF-16 surrogate pair
        self.assertIsNone(radio._hf_token())


class VoicePython(unittest.TestCase):
    def setUp(self):
        reset_home()

    def test_ready_means_kokoro_onnx_new_enough(self):
        patch(self, "_run", side_effect=lambda cmd, timeout: self.answer)
        with mock.patch.object(dj, "_kokoro_python", return_value="C:/Py312/python.exe") as find:
            for self.answer, want in (((0, "0.6.1\n"), "C:/Py312/python.exe"), ((0, "1.0\n"), "C:/Py312/python.exe"),
                                      ((0, "0.5.0\n"), None), ((1, "PackageNotFoundError"), None)):
                with self.subTest(self.answer):
                    radio._voice_ready.cache_clear()
                    self.assertEqual(radio._voice_ready(), want)
            self.assertEqual(find.call_args.kwargs, {"check": True})
            radio._voice_ready.cache_clear()
            radio._voice_ready(), radio._voice_ready()
            self.assertEqual(find.call_count, 5)                      # two asks, one search: once per command
        radio._voice_ready.cache_clear()
        with mock.patch.object(dj, "_kokoro_python", return_value=None):
            self.assertIsNone(radio._voice_ready())

    def test_the_test_line_is_the_djs_own_render(self):
        import wave

        def render(text):
            if self.frames is None:
                dj._kokoro_error = "rc=1 (C:/venv/python.exe) RuntimeError: boom"
                return None
            out = radio.ROOT / "_dj_1.wav"
            with wave.open(str(out), "wb") as w:
                w.setnchannels(1)
                w.setsampwidth(2)
                w.setframerate(24000)
                w.writeframes(b"\0\1" * self.frames)
            return out
        with mock.patch.object(dj, "_kokoro_render", side_effect=render):
            self.frames = 2400
            self.assertIsNone(radio._voice_check())
            self.frames = 0
            self.assertEqual(radio._voice_check(), "the test line came out empty")
            self.frames = None
            self.assertEqual(radio._voice_check(), "the test line failed: rc=1 (C:/venv/python.exe) RuntimeError: boom")
        self.assertEqual(list(radio.ROOT.glob("_dj_*.wav")), [])          # never left behind

    def test_pip_makes_the_environment_the_djs_python(self):
        patch(self, "_run", return_value=(0, ""))
        self.assertIsNone(radio._pip_voice())
        self.assertEqual(dj.KOKORO_PY_CACHE.read_text(encoding="utf-8"), str(dj.venv_python()))
        patch(self, "_run", return_value=(1, "Collecting kokoro-onnx\nERROR: No matching distribution found\n"))
        self.assertEqual(radio._pip_voice(), "pip failed (ERROR: No matching distribution found)")

    def test_an_environment_needs_venv(self):
        patch(self, "_voice_python", return_value="/usr/bin/python3")
        patch(self, "_run", return_value=(1, "The virtual environment was not created successfully because ensurepip is not\navailable.\n"))
        self.assertIn("sudo apt install python3-venv", radio._make_venv())


class GetLlama(unittest.TestCase):
    def setUp(self):
        reset_home()
        self.zip = Path(tempfile.mkdtemp(prefix="terminal-fm-llama-")) / "llama-b1-bin-test.zip"
        self.addCleanup(shutil.rmtree, self.zip.parent, True)
        with zipfile.ZipFile(self.zip, "w") as z:
            z.writestr(radio._llm_exe().name, b"exe")
            z.writestr("ggml.dll", b"dll")

        def fetch(url, dest, size, sha):
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy(self.zip, dest)
        patch(self, "_fetch", side_effect=fetch)

    def test_it_moves_in_only_after_llama_cli_runs(self):
        patch(self, "_run", return_value=(0, "version: 0.7.0-dev (build 11669)"))
        self.assertIsNone(radio._get_llama(self.zip.name, 1, "sha"))
        self.assertEqual(sorted(p.name for p in radio._llm_exe().parent.iterdir()), sorted(["ggml.dll", radio._llm_exe().name]))
        self.assertEqual(sorted(p.name for p in radio.LLM_DIR.iterdir()), ["bin"])     # no archive, no temp folder

    def test_a_build_that_doesnt_run_is_not_moved_in(self):
        patch(self, "_run", return_value=(127, "llama-cli: error while loading shared libraries: libcurl.so.4"))
        err = radio._get_llama(self.zip.name, 1, "sha")
        self.assertIn("didn't run (llama-cli: error while loading shared libraries: libcurl.so.4)", err)
        self.assertFalse(radio._llm_exe().parent.exists())
        self.assertEqual([p.name for p in radio.LLM_DIR.iterdir()], [self.zip.name])   # kept for the next run


@unittest.skipUnless(os.environ.get("TERMINAL_FM_NETWORK_TESTS"),
                     "downloads llama.cpp from GitHub; CI's newest-Python jobs set TERMINAL_FM_NETWORK_TESTS")
class RealLlamaBuild(unittest.TestCase):
    """The pinned build for the system running this, through the real download, unpack and
    `--version` check: the only test of the .tar.gz route on a real Mac and a real Linux."""

    def test_this_systems_build_installs_and_runs(self):
        reset_home()
        asset = radio._llama_asset()
        self.assertIsNotNone(asset, f"no pinned build for {sys.platform}")
        self.assertIsNone(radio._get_llama(*asset))
        code, out = radio._run([str(radio._llm_exe()), "--version"], 60)
        self.assertEqual(code, 0, out)
        self.assertIn(f"build {radio.LLAMA_BUILD[1:]}", out)


if __name__ == "__main__":
    unittest.main()
