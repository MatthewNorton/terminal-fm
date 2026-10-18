"""Shared set-up for the Terminal FM unit tests. Import `radio` from here, never directly.

radio.py has import-time side effects: it reads config.json and creates queue/ and the library
folder under its data directory. So this module points AI_RADIO_HOME at a fresh temporary folder
BEFORE radio is imported, and refuses to run if radio was already imported against any other
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
from pathlib import Path
from unittest import mock

REPO = Path(__file__).resolve().parent.parent
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

if "radio" in sys.modules:
    _existing = Path(getattr(sys.modules["radio"], "ROOT", "")).resolve()
    if os.environ.get("AI_RADIO_TEST_HOME") != str(_existing):
        raise RuntimeError(f"radio was imported before the test home was set (data dir {_existing}); "
                           "refusing to run tests against it")
    HOME = _existing
else:
    HOME = Path(tempfile.mkdtemp(prefix="terminal-fm-test-")).resolve()
    os.environ["AI_RADIO_HOME"] = str(HOME)
    os.environ["AI_RADIO_TEST_HOME"] = str(HOME)
    atexit.register(shutil.rmtree, str(HOME), True)

import radio  # noqa: E402  (must come after AI_RADIO_HOME is set)

if Path(radio.ROOT).resolve() != HOME:
    raise RuntimeError(f"radio.ROOT is {radio.ROOT}, expected the test home {HOME}")


def reset_home():
    """Empty the temporary data directory between tests (it is shared by the whole run) and drop
    the cached tokenizer, so no test sees another test's files."""
    root = Path(radio.ROOT).resolve()
    if root != HOME or not str(root).startswith(str(Path(tempfile.gettempdir()).resolve())):
        raise RuntimeError(f"refusing to clear {root}: not the temporary test home")
    for child in root.iterdir():
        if child.is_dir():
            shutil.rmtree(child)
        else:
            child.unlink()
    radio.QUEUE_DIR.mkdir(parents=True, exist_ok=True)
    radio.OUTDIR.mkdir(parents=True, exist_ok=True)
    radio._TOKENIZER = None


def patch(case, name, **kwargs):
    """Patch radio.<name> until the end of the test `case` (its cleanup undoes it)."""
    p = mock.patch.object(radio, name, **kwargs)
    case.addCleanup(p.stop)
    return p.start()


def run(fn, *args, **kwargs):
    """Call fn and return (result, everything it printed to stdout)."""
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        result = fn(*args, **kwargs)
    return result, buf.getvalue()
