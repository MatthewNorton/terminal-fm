"""Terminal FM's shared core: the two roots, the files under the data directory, the config, the
state, and the helpers that write them. Importing it creates queue/ and the library folder.

Import the module, not its names (`from tfm import core`, then `core.ROOT`): tfm/__init__.py says why.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

# --------------------------------------------------------------------------- paths
# Two roots. CODE_DIR is wherever radio.py lives, the folder above tfm/ (a clone, a plugin install,
# ~/.claude/terminal-fm), and holds the scripts and prompts/. ROOT is the data directory: state,
# config, the key, the library, downloaded models and logs. It defaults to ~/.claude/terminal-fm
# and TERMINAL_FM_HOME overrides it, so a checkout anywhere still finds dj.py next to radio.py and
# still shares one library and one config.
CODE_DIR = Path(__file__).resolve().parent.parent
ROOT = Path(os.path.expanduser(os.environ.get("TERMINAL_FM_HOME", "").strip()
                               or str(Path.home() / ".claude" / "terminal-fm")))
DEFAULT_OUTDIR = ROOT / "output"    # library lives here unless config.json overrides library_dir
STATE_FILE = ROOT / "state.json"
NOW_FILE = ROOT / "nowplaying.txt"
KEY_FILE = ROOT / ".key"
CONFIG_FILE = ROOT / "config.json"
DJ_SCRIPT = CODE_DIR / "dj.py"
# The plugin can't set the user's statusLine and its own folder moves on every update, so the
# SessionStart hook copies this script into the data directory, a path a settings snippet can keep.
STATUSLINE_SRC = CODE_DIR / "statusline.py"
STATUSLINE_DST = ROOT / "statusline.py"
QUEUE_DIR = ROOT / "queue"          # one file per pending DJ line (race-free FIFO)
SPEAK_LOCK = ROOT / "dj_speaking.lock"   # held while an idle announcement is being spoken
BREAKING_FILE = ROOT / "breaking.txt"    # pending "breaking news": interrupt the track, speak, resume
RESUME_FILE = ROOT / "resume.json"       # pause point: {track, offset} the daemon replays on next start
PLAYLIST_FILE = ROOT / "playlist.json"   # ordered [names]; when present the daemon plays this exact order (looping) instead of shuffle
LIST_FILE = ROOT / "last_list.json"      # snapshot of the last `radio list` order so numeric selections map to what was shown
ARCHIVE_LIST_FILE = ROOT / "last_archive.json"  # same idea for `radio unarchive` numbering
HISTORY_FILE = ROOT / "prompt_history.jsonl"    # append-only: one JSON record per generated track
HOOK_SEEN = ROOT / ".hook_seen"          # time of the last SessionStart hook, for `radio setup`
ARCHIVE_DIRNAME = "_archive"             # subfolder of the library; get_library()'s non-recursive
                                         # glob is what keeps archived tracks out of rotation
# `radio drop` target: ONE shared reject pile under output/, whichever folder the track played from
# (unlike _archive, which sits inside each library), so rejects from every collection meet there.
BAD_DIR = DEFAULT_OUTDIR / "bad song"
QUEUE_DIR.mkdir(parents=True, exist_ok=True)

IS_WIN = os.name == "nt"
DEVNULL = subprocess.DEVNULL
CREATE_NO_WINDOW = 0x08000000 if IS_WIN else 0   # hide child console windows on Windows

# --------------------------------------------------------------------------- config
DEFAULT_CONFIG = {
    "source": "stability-api",
    "volume": 85,
    "library_dir": "",   # folder the radio plays from; "" = <root>/output (see resolve_outdir)
    "stability_api": {
        "submit_url": "https://api.stability.ai/v2beta/audio/stable-audio/text-to-audio",
        "results_url": "https://api.stability.ai/v2beta/audio/results",
        "balance_url": "https://api.stability.ai/v1/user/balance",   # exact cost = balance drop
        "model": "stable-audio-3",
        "steps": 8,          # SA3 is fixed at 8
        "duration": 120,     # fallback when gen's auto-pick has nothing to go on (pick_duration)
        "output_format": "mp3",
        "ca_bundle": "",     # PEM to verify against; "" = platform trust store (see _ssl_context)
    },
    "dj": {"announce_when_idle": False, "breaking_news": False},
}


def load_config():
    cfg = json.loads(json.dumps(DEFAULT_CONFIG))  # deep copy
    if CONFIG_FILE.exists():
        try:
            user = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
            for k, v in user.items():
                if isinstance(v, dict) and isinstance(cfg.get(k), dict):
                    cfg[k].update(v)
                else:
                    cfg[k] = v
        except Exception:
            pass
    return cfg


def resolve_outdir(cfg):
    """The folder the radio plays from. config.json 'library_dir' overrides the default; ~ and
    env vars expand, relative paths resolve against ROOT. Falls back to <root>/output."""
    raw = (cfg.get("library_dir") or "").strip()
    if not raw:
        return DEFAULT_OUTDIR
    p = Path(os.path.expandvars(os.path.expanduser(raw)))
    if not p.is_absolute():
        p = ROOT / p
    return p


CONFIG = load_config()
OUTDIR = resolve_outdir(CONFIG)
try:
    OUTDIR.mkdir(parents=True, exist_ok=True)
except OSError as _e:
    # A library_dir that can't be created must not take every command down with an import-time
    # traceback (it did, until 2026-09-28). Fall back to the default folder and say so.
    try:
        print(f"Warning: library folder {OUTDIR} cannot be created ({_e}); using {DEFAULT_OUTDIR}. "
              f"Fix or reset it with:  radio folder default", file=sys.stderr)
    except Exception:
        pass
    OUTDIR = DEFAULT_OUTDIR
    OUTDIR.mkdir(parents=True, exist_ok=True)
# Archived tracks live beside the library they came from. Created lazily on first archive so we
# don't litter an empty _archive into every folder the user points at.
ARCHIVE_DIR = OUTDIR / ARCHIVE_DIRNAME

# --------------------------------------------------------------------------- state
def read_state():
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"status": "stopped", "daemon_pid": None, "player_pid": None, "now_playing": None}


def _atomic_write(path, text):
    """Write a whole file so a reader never sees a half-written one: write a sibling temp file,
    then rename over the target. Several processes share these files (daemon, CLI, hook,
    statusline), and a torn state.json read as "stopped" or a torn config.json lost settings.
    If the rename is refused (Windows, when a reader has the file open) fall back to a direct write."""
    tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    try:
        tmp.write_text(text, encoding="utf-8")
        os.replace(tmp, path)
    except OSError:
        try:
            tmp.unlink()
        except OSError:
            pass
        path.write_text(text, encoding="utf-8")


def _write_json(path, obj, **dumps_kw):
    _atomic_write(path, json.dumps(obj, **dumps_kw))


def _write_private(path, text):
    """Write a secret so it is owner-only (0600 on POSIX) from the moment it exists. The temp file
    is created with that mode, never with the umask's default, and then renamed into place: the
    key used to be written world-readable under a typical umask and chmod-ed only afterwards.
    Windows ignores the mode (the file inherits the folder's permissions), and when it refuses the
    rename this writes the target directly, still through a 0600 descriptor."""
    tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    _unlink_quiet(tmp)                  # O_EXCL below: never reuse a file someone else created
    try:
        fd = os.open(str(tmp), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
        os.replace(tmp, path)
    except OSError:
        _unlink_quiet(tmp)
        # Security: not _atomic_write, whose write_text uses the umask's mode (readable by others
        # on a typical system). O_CREAT's mode skips an existing file, so tighten it before the key
        # goes in; Windows has no fchmod before 3.13.
        fd = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            if hasattr(os, "fchmod"):
                os.fchmod(fd, 0o600)
            fh.write(text)
    try:
        os.chmod(path, 0o600)           # exactly 0600 whatever the umask took off os.open's mode
    except OSError:
        pass


def _unlink_quiet(path):
    """Delete a file if it is there. Missing or locked is not an error: every caller is tidying up
    and must not take playback down over it."""
    try:
        path.unlink()
    except Exception:
        pass


def write_state(**kw):
    _write_json(STATE_FILE, kw, indent=2)


def write_now(text):
    _atomic_write(NOW_FILE, text)


def set_config(section, key, value):
    """Persist a single setting into config.json, merging with whatever is already there.
    Returns True if written. An unreadable config.json is left alone and reported, never replaced
    with {} (which silently wiped every other setting until 2026-09-28)."""
    data = {}
    if CONFIG_FILE.exists():
        try:
            data = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                raise ValueError("top level is not an object")
        except Exception as e:
            print(f"Not saved: {CONFIG_FILE} is not valid JSON ({e}). Fix or delete it first.")
            return False
    if section:
        if not isinstance(data.get(section), dict):
            data[section] = {}
        data[section][key] = value
    else:
        data[key] = value
    _write_json(CONFIG_FILE, data, indent=2)
    return True
