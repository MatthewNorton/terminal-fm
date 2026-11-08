"""Shared set-up for the Terminal FM unit tests. Import `radio` and the tfm modules from here,
never directly.

Importing radio has side effects (tfm/core.py reads config.json and creates queue/ and the library
folder under its data directory). So this module points TERMINAL_FM_HOME at a fresh temporary
folder BEFORE radio is imported, and refuses to run if it was already imported against any other
folder. The tests can then never read or write the real data directory (state, config, the key,
the queue or the library). The temporary folder is deleted when the test process exits.
"""

import atexit
import contextlib
import io
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

REPO = Path(__file__).resolve().parent.parent
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

if "tfm.core" in sys.modules:                  # radio imports it, so this covers radio too
    _existing = Path(getattr(sys.modules["tfm.core"], "ROOT", "")).resolve()
    if os.environ.get("TERMINAL_FM_TEST_HOME") != str(_existing):
        raise RuntimeError(f"radio was imported before the test home was set (data dir {_existing}); "
                           "refusing to run tests against it")
    HOME = _existing
else:
    HOME = Path(tempfile.mkdtemp(prefix="terminal-fm-test-")).resolve()
    os.environ["TERMINAL_FM_HOME"] = str(HOME)
    os.environ["TERMINAL_FM_TEST_HOME"] = str(HOME)
    atexit.register(shutil.rmtree, str(HOME), True)

import radio  # noqa: E402  (must come after TERMINAL_FM_HOME is set)
from tfm import core  # noqa: E402

# Every module a test can patch a name in: radio and the tfm modules it loaded.
MODULES = (radio,) + tuple(m for n, m in sorted(sys.modules.items()) if n.startswith("tfm."))

if Path(core.ROOT).resolve() != HOME:
    raise RuntimeError(f"core.ROOT is {core.ROOT}, expected the test home {HOME}")


def reset_home():
    """Empty the temporary data directory between tests (it is shared by the whole run) and drop
    the cached tokenizer and every functools cache, so no test sees another test's files."""
    root = Path(core.ROOT).resolve()
    if root != HOME or not str(root).startswith(str(Path(tempfile.gettempdir()).resolve())):
        raise RuntimeError(f"refusing to clear {root}: not the temporary test home")
    for child in root.iterdir():
        if child.is_dir():
            shutil.rmtree(child)
        else:
            child.unlink()
    core.QUEUE_DIR.mkdir(parents=True, exist_ok=True)
    core.OUTDIR.mkdir(parents=True, exist_ok=True)
    radio._TOKENIZER = None
    for m in MODULES:                   # every functools cache, in whichever module a move put it
        for v in vars(m).values():
            if hasattr(v, "cache_clear") and getattr(v, "__module__", None) == m.__name__:
                v.cache_clear()


def code_files():
    """radio.py and the tfm modules it loaded: the code a radio.py command runs."""
    return [Path(m.__file__) for m in MODULES]


def patch(case, name, **kwargs):
    """Patch <name> in the one module that defines it (radio or a tfm module) until the end of the
    test `case`. A name in no module, or in several, fails here instead of patching a copy that
    nothing reads (tfm/__init__.py has the rule behind it)."""
    owners = [m for m in MODULES if name in vars(m)]
    if len(owners) != 1:
        raise AssertionError(f"patch({name!r}): defined in {[m.__name__ for m in owners] or 'no module'}; "
                             "it needs exactly one")
    p = mock.patch.object(owners[0], name, **kwargs)
    case.addCleanup(p.stop)
    return p.start()


def own_line(text):
    """`text` as setup and the key messages print a command, path or address: on a line of its own."""
    return radio.STEP_INDENT + text


def run(fn, *args, **kwargs):
    """Call fn and return (result, everything it printed to stdout)."""
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        result = fn(*args, **kwargs)
    return result, buf.getvalue()


OSES = ("win32", "darwin", "linux")


@contextlib.contextmanager
def on_os(platform):
    """radio as it runs on `platform`, one of OSES: core.IS_WIN and sys.platform to match."""
    with mock.patch.object(core, "IS_WIN", platform == "win32"), \
            mock.patch.object(radio.sys, "platform", platform):
        yield


# Where _hf_token looks for the user's Hugging Face login.
HF_VARS = ("HF_TOKEN", "HUGGING_FACE_HUB_TOKEN", "HF_TOKEN_PATH", "HF_HOME", "XDG_CACHE_HOME")


class SetupCase(unittest.TestCase):
    """`setup` tests: a fresh data folder, no API key, a throwaway Claude Code settings folder, and
    neither the enhancer, a voice Python nor a Hugging Face login from this machine."""

    def setUp(self):
        reset_home()
        env = mock.patch.dict(os.environ)
        env.start()
        self.addCleanup(env.stop)
        for var in ("STABILITY_API_KEY",) + HF_VARS:
            os.environ.pop(var, None)
        os.environ["HF_TOKEN_PATH"] = str(core.ROOT / "no-login")
        cfg = tempfile.mkdtemp(prefix="terminal-fm-cfg-")
        self.addCleanup(shutil.rmtree, cfg, True)
        os.environ["CLAUDE_CONFIG_DIR"] = cfg          # never read the real ~/.claude/settings.json
        self.cfg = Path(cfg)
        patch(self, "_llm_paths", return_value=(None, None))
        patch(self, "_voice_ready", return_value=None)     # never this machine's own Pythons

    def ready(self):
        patch(self, "detect_player", return_value=("/usr/bin/ffplay", None))
        core.KEY_FILE.write_text("test-key-not-real", encoding="utf-8")
        (core.OUTDIR / "a.mp3").write_bytes(b"ID3")
        core.HOOK_SEEN.write_text("2026-10-17 09:00", encoding="utf-8")

    def setup_out(self, *args):
        return run(radio.cmd_setup, list(args))[1]
