#!/usr/bin/env python3
"""
Terminal FM - portable, stdlib-only continuous music player for the Claude CLI.

Cross-platform (Windows / macOS / Linux). No third-party packages.

Usage: radio.py <command> [args], no command = status. Every command and alias is in the
COMMANDS table at the bottom of this file, and README.md is the full reference. In short:
    gen "<prompt>" [duration|auto]           one track; no duration = picked to suit the prompt
    gen "<prompt>" <count> <duration|auto>   N tracks into the library
    enhance "<idea>" / egen "<idea>" ...     rewrite an idea into a prompt (and generate it)
    play [1,3,5-8] | pause | stop | skip     playback; numbers from `list` play in that order
    list | playlist | shuffle | folder       the library and what plays from it
    archive | drop | unarchive | prompts     tidy the library; look up past prompts
    say | announce | breaking | hook         the DJ voice between tracks
    format | key | status | setup            settings, state, and a first-run checklist
    __daemon                                 (internal) the detached playback loop

Architecture
------------
* SOURCE PROVIDERS decide where music comes from: one function each, registered in SOURCES.
  Today there is one, "stability-api" (Stable Audio 3).
* The PLAYER is auto-detected per OS (mpv > ffplay > afplay > mpg123 > cvlc) and plays
  files OR stream URLs uniformly.
* State lives in the data directory (~/.claude/terminal-fm, or TERMINAL_FM_HOME): state.json,
  nowplaying.txt, config.json and the other files named under "paths" below.
"""

import csv
import functools
import hashlib
import heapq
import http.client
import io
import json
import os
import random
import re
import shutil
import signal
import ssl
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from collections import namedtuple
from pathlib import Path, PurePosixPath

# --------------------------------------------------------------------------- paths
# Two roots. CODE_DIR is wherever this file lives (a clone, a plugin install, ~/.claude/terminal-fm) and
# holds the scripts and prompts/. ROOT is the data directory: state, config, the key, the library,
# downloaded models and logs. It defaults to ~/.claude/terminal-fm and TERMINAL_FM_HOME overrides it, so a
# checkout anywhere still finds dj.py next to itself and still shares one library and one config.
CODE_DIR = Path(__file__).resolve().parent
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


# File types gen can save (`radio format`) and the library plays. Non-recursive on purpose: the
# _archive subfolder must stay invisible to shuffle and playlists.
AUDIO_FORMATS = ("mp3", "wav")
# `radio format wav+mp3` (added 2026-10-11): one WAV request, encoded to MP3 locally, so
# it is billed once and both files are the same take. The MP3 plays from the library and the WAV
# master goes to <library>/_wav, which the non-recursive scan skips, so nothing plays twice.
BOTH_FORMATS = "wav+mp3"
FORMAT_CHOICES = AUDIO_FORMATS + (BOTH_FORMATS,)
WAV_SUBDIR = "_wav"
MP3_BITRATE = "128k"        # what Stable Audio 3's own mp3 output measured (ffprobe, 2026-10-11)


def _audio_in(folder):
    if not folder.is_dir():
        return []
    return sorted(p for p in folder.iterdir()
                  if p.is_file() and p.suffix.lower().lstrip(".") in AUDIO_FORMATS)


def get_library():
    return _audio_in(OUTDIR)


# ---- archive: tracks the user doesn't want, moved out of rotation but not deleted --------------
def archived_tracks():
    return _audio_in(ARCHIVE_DIR)


def _move_track(track, dest_dir, retries=16, delay=0.25):
    """Move one track into dest_dir, retrying briefly. The player may still hold the file open for
    a moment after being killed, and Windows refuses to move an open file. Returns the new Path,
    or None if every attempt failed. Never overwrites: a name clash gets a timestamp suffix."""
    try:
        dest_dir.mkdir(parents=True, exist_ok=True)
    except Exception as e:
        print(f"  Could not create {dest_dir}: {e}")
        return None
    dest = dest_dir / track.name
    if dest.exists():
        dest = dest_dir / f"{track.stem}-{time.strftime('%Y%m%d-%H%M%S')}{track.suffix}"
    last = None
    for _ in range(retries):
        try:
            shutil.move(str(track), str(dest))
            return dest
        except Exception as e:
            last = e
            time.sleep(delay)
    print(f"  Could not move {track.name}: {last}")
    return None


def _playlist_drop(names):
    """Drop names from playlist.json after archiving. Deleting the file (back to shuffle) when
    nothing is left matters: a playlist pointing only at moved files would otherwise leave the
    daemon spinning on tracks that no longer exist."""
    if not PLAYLIST_FILE.exists():
        return
    try:
        drop = set(names)
        keep = [n for n in json.loads(PLAYLIST_FILE.read_text(encoding="utf-8")) if n not in drop]
    except Exception:
        return
    try:
        if keep:
            _write_json(PLAYLIST_FILE, keep)
        else:
            PLAYLIST_FILE.unlink()
            print("  Playlist is now empty - back to full-library shuffle.")
    except Exception:
        pass


# ---- prompt history: every generated track's prompt, kept forever ------------------------------
# Set by `egen` so the history records the rough idea alongside the enhanced prompt. A module
# global is safe here: every invocation is a fresh short-lived process.
GEN_IDEA = None


def history_add(prompt, duration, filename, idea=None, source=None, kind="gen"):
    """Append one entry to the history: a generated track, or `kind="enhance"` for a rewrite that
    was only printed (no file, no credits). Append-only JSONL: a corrupt or partial line can never
    take out the records around it."""
    rec = {"ts": time.strftime("%Y-%m-%d %H:%M:%S"), "prompt": prompt,
           "duration": duration, "file": filename}
    if idea:
        rec["idea"] = idea
    if source:
        rec["source"] = source
    if kind != "gen":       # absent = generated, so every older record stays correct
        rec["kind"] = kind
    try:
        with HISTORY_FILE.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except Exception:
        pass        # history is a convenience; never let it break a generation


def history_all():
    """Every recorded generation, oldest first. Bad lines are skipped, not fatal."""
    if not HISTORY_FILE.exists():
        return []
    out = []
    try:
        lines = HISTORY_FILE.read_text(encoding="utf-8").splitlines()
    except Exception:
        return []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
            if isinstance(rec, dict):
                out.append(rec)
        except Exception:
            pass
    return out


def _history_where(rec):
    """Where the track for a history entry lives now: library, archive, gone - or never made."""
    if rec.get("kind") == "enhance":
        return "enhance"
    name = rec.get("file") or ""
    if not name:
        return "-"
    if (OUTDIR / name).exists():
        return "library"
    if (ARCHIVE_DIR / name).exists():
        return "archived"
    if (BAD_DIR / name).exists():
        return "bad song"
    return "missing"


# ---- playlist: an ordered selection of tracks the user picks by number from `radio list` -------
def _saved_order(list_file, folder):
    """The tracks a saved listing (last_list.json, last_archive.json) named, in its order, that
    are still in `folder`; [] when there is no listing or nothing in it is left."""
    try:
        names = json.loads(list_file.read_text(encoding="utf-8"))
        return [folder / n for n in names if (folder / n).exists()]
    except Exception:
        return []


def list_snapshot():
    """The ordered tracks the last `radio list` showed (so numbers stay stable even if the library
    changed since). Falls back to the live library order if there's no snapshot."""
    return _saved_order(LIST_FILE, OUTDIR) or get_library()


def _pick_unique(tracks, idx):
    """tracks[i - 1] for each 1-based i in idx, first occurrence of each name only."""
    seen, out = set(), []
    for i in idx:
        t = tracks[i - 1]
        if t.name not in seen:
            seen.add(t.name)
            out.append(t)
    return out


def load_playlist():
    """Ordered list of existing track Paths from playlist.json, or None if no playlist is set."""
    if not PLAYLIST_FILE.exists():
        return None
    try:
        names = json.loads(PLAYLIST_FILE.read_text(encoding="utf-8"))
    except Exception:
        return None
    tracks = [(Path(n) if os.path.isabs(n) else OUTDIR / n) for n in names]
    tracks = [t for t in tracks if t.exists()]
    return tracks or None


def looks_like_selection(tokens):
    """True if tokens are all track numbers / ranges (e.g. '1,3,5-8' or '1 2 4'), not a path/flag."""
    toks = " ".join(tokens).replace(",", " ").split()
    if not toks:
        return False
    for t in toks:
        a, sep, b = t.partition("-")
        if sep:
            if not (a.isdigit() and b.isdigit()):
                return False
        elif not t.isdigit():
            return False
    return True


def parse_selection(tokens, n):
    """Map selection tokens to 1-based indices within 1..n, order preserved, duplicates kept
    (so '3,3' plays a track twice). Supports single numbers and ascending/descending ranges."""
    out = []
    for tok in " ".join(tokens).replace(",", " ").split():
        a, sep, b = tok.partition("-")
        if sep and a.isdigit() and b.isdigit():
            lo, hi = int(a), int(b)
            # Clamp to 1..n BEFORE building the range: the loop is bounded by the library size,
            # not by what was typed (a stray digit in "1-99999999999" used to spin for minutes).
            first, last = max(1, min(lo, hi)), min(n, max(lo, hi))
            if first > last:
                continue
            out.extend(range(first, last + 1) if hi >= lo else range(last, first - 1, -1))
        elif tok.isdigit():
            i = int(tok)
            if 1 <= i <= n:
                out.append(i)
    return out


# ---- DJ queue (Claude writes lines; the daemon speaks them between tracks) ---
def queue_files():
    return sorted(QUEUE_DIR.glob("*.txt"))


def queue_add(text, front=False):
    text = (text or "").strip()
    if not text:
        return False
    # The daemon reads the oldest name first. A "0-" prefix sorts ahead of every timestamped
    # name, so front=True (a `play --say` sign-on) jumps lines that were already waiting.
    name = f"{'0-' if front else ''}{time.time_ns()}-{random.randint(1000, 9999)}.txt"
    (QUEUE_DIR / name).write_text(text, encoding="utf-8")
    return True


def _say_file(path):
    """Speak the line in `path` through dj.py (blocking), then delete the file."""
    try:
        if DJ_SCRIPT.exists():
            subprocess.run([sys.executable, str(DJ_SCRIPT), "say", "--file", str(path)],
                           stdout=DEVNULL, stderr=DEVNULL, timeout=180,
                           creationflags=CREATE_NO_WINDOW)
    except Exception:
        pass
    _unlink_quiet(path)


def speak_next():
    """Speak the oldest queued DJ line (blocking) via dj.py/Kokoro. Returns True if it spoke."""
    files = queue_files()
    if not files:
        return False                 # empty queue -> no DJ line before this track
    _say_file(files[0])
    return True


def speak_breaking():
    """Speak the pending breaking-news line (blocking) and clear it. Returns True if it spoke."""
    if not BREAKING_FILE.exists():
        return False
    _say_file(BREAKING_FILE)
    return True


def _speak_line(text):
    """Speak one line immediately (blocking) via dj.py/Kokoro, with no music daemon involved.

    Used by the idle-announce path. A stale-aware exclusive lock keeps two overlapping turns
    from rendering to the same WAV / talking over each other.
    """
    text = (text or "").strip()
    if not text or not DJ_SCRIPT.exists():
        return False
    try:
        fd = os.open(str(SPEAK_LOCK), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        os.close(fd)
    except FileExistsError:
        try:
            stale = (time.time() - SPEAK_LOCK.stat().st_mtime) > 180
        except Exception:
            stale = True
        if not stale:
            return False                 # another announcement is mid-flight -> skip this one
        try:
            SPEAK_LOCK.unlink()
            fd = os.open(str(SPEAK_LOCK), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.close(fd)
        except Exception:
            return False
    try:
        subprocess.run([sys.executable, str(DJ_SCRIPT), "say"], input=text.encode("utf-8"),
                       stdout=DEVNULL, stderr=DEVNULL, timeout=180,
                       creationflags=CREATE_NO_WINDOW)
    except Exception:
        pass
    finally:
        _unlink_quiet(SPEAK_LOCK)
    return True


def _proc_name(pid):
    """Executable name of a live process, or None if there is no such process."""
    try:
        if IS_WIN:
            out = subprocess.run(["tasklist", "/FI", f"PID eq {pid}", "/NH", "/FO", "CSV"],
                                 capture_output=True, text=True, creationflags=CREATE_NO_WINDOW)
            for row in csv.reader(io.StringIO(out.stdout)):   # exact match on the PID column:
                if len(row) > 1 and row[1] == str(pid):       # "123" must not match "1234"
                    return row[0]
            return None
        os.kill(pid, 0)
        try:
            return Path(f"/proc/{pid}/comm").read_text().strip() or "?"   # Linux
        except OSError:
            pass
        out = subprocess.run(["ps", "-p", str(pid), "-o", "comm="], capture_output=True, text=True)
        return os.path.basename(out.stdout.strip()) or "?"                # macOS / other POSIX
    except Exception:
        return None


def alive(pid, expect=None):
    """True if `pid` is running and, when `expect` (an executable name recorded with the pid) is
    given, is still that program. PIDs get recycled: a stale state.json must not make the radio
    report a stranger as its daemon, or `kill` one."""
    if not pid:
        return False
    name = _proc_name(pid)
    if name is None:
        return False
    if expect:
        want = Path(expect).name.lower().split(".")[0]
        return bool(want) and want in name.lower()
    return True


def kill(pid, expect=None):
    if not pid or (expect and not alive(pid, expect)):
        return
    try:
        if IS_WIN:
            subprocess.run(["taskkill", "/F", "/PID", str(pid)], stdout=DEVNULL, stderr=DEVNULL,
                           creationflags=CREATE_NO_WINDOW)
        else:
            os.kill(pid, signal.SIGTERM)
    except Exception:
        pass


_SELF_EXE = None


def _self_exe():
    """This process's program name as alive() will see it later, for state.json's daemon_exe.
    A macOS framework Python (Homebrew, python.org, Xcode's /usr/bin/python3) runs as `Python`
    whatever sys.executable says, so recording `python3.14` made a live daemon look dead: stop and
    pause left the music playing and the Stop hook queued nothing. Windows keeps the exe name."""
    global _SELF_EXE
    if _SELF_EXE is None:
        name = None if IS_WIN else _proc_name(os.getpid())
        _SELF_EXE = name if name and name != "?" else Path(sys.executable).name
    return _SELF_EXE


def _daemon_alive(st):
    return alive(st.get("daemon_pid"), st.get("daemon_exe"))


def _is_playing(st):
    """state.json says playing AND the daemon it names is still running as that program."""
    return st.get("status") == "playing" and _daemon_alive(st)


def _player_alive(st):
    return alive(st.get("player_pid"), st.get("player_exe"))


def _kill_player(st):
    kill(st.get("player_pid"), st.get("player_exe"))


def _kill_daemon(st):
    kill(st.get("daemon_pid"), st.get("daemon_exe"))


def _kill_players_after_daemon(st, now=None):
    """Call only once the daemon is dead. Kills the player state.json names NOW, plus the one `st`
    (read before the daemon was killed) named if that is a different process. Returns the re-read
    state. Killing the daemon takes long enough (a tasklist check, then taskkill) that a track can
    end inside it: the daemon then starts the next player and records its pid, so killing the pid
    from the first read hit an already-exited player and left the new one playing untracked (7 of
    16 trials stopping 0.10-0.15 s before the end of a 6 s track, 2026-10-12). kill() checks each
    pid is still the recorded program, so the stale one is skipped when it has gone.
    Still open: a daemon killed between its player Popen and the state write leaves a player
    that no state names."""
    now = read_state() if now is None else now
    _kill_player(now)
    if (now.get("player_pid"), now.get("player_exe")) != (st.get("player_pid"), st.get("player_exe")):
        _kill_player(st)
    return now


# --------------------------------------------------------------------------- player
# Each entry: (exe, builder(path_or_url, volume) -> argv). First one found wins.
def _players():
    return [
        ("mpv", lambda src, vol: ["mpv", "--no-video", "--really-quiet", f"--volume={vol}", src]),
        ("ffplay", lambda src, vol: ["ffplay", "-nodisp", "-autoexit", "-loglevel", "quiet",
                                     "-volume", str(vol), src]),
        ("afplay", lambda src, vol: ["afplay", "-v", f"{vol/100:.2f}", src]),       # macOS
        ("mpg123", lambda src, vol: ["mpg123", "-q", src]),                          # Linux
        ("cvlc", lambda src, vol: ["cvlc", "--intf", "dummy", "--play-and-exit", "--quiet", src]),
    ]


# The process name alive()/kill() will see for a player that hands off to another program:
# cvlc is a shell wrapper that execs vlc, so recording "cvlc" made skip, pause and stop miss it.
PLAYER_PROCESS = {"cvlc": "vlc"}
# Players player_argv() can start mid-track. afplay and mpg123 have no clean seconds-seek, so a
# paused or interrupted track restarts from the top on them.
SEEK_PLAYERS = ("mpv", "ffplay", "vlc")


def _can_seek(player_path):
    exe = Path(player_path or "").name.lower()
    return any(p in exe for p in SEEK_PLAYERS)


def _win_ffmpeg_tool(name):
    """C:/ffmpeg/bin/<name>.exe when on Windows and present, else None: ffmpeg's Windows builds
    are often unpacked there and never added to PATH."""
    path = Path("C:/ffmpeg/bin") / f"{name}.exe"
    return str(path) if IS_WIN and path.exists() else None


def detect_player():
    for exe, builder in _players():
        found = shutil.which(exe)
        if found:
            return found, builder
    found = _win_ffmpeg_tool("ffplay")
    if found:
        return found, dict(_players())["ffplay"]   # player_argv puts this path in argv[0]
    return None, None


def player_argv(player_path, builder, src, vol, start=0):
    argv = builder(src, vol)
    argv[0] = player_path  # use resolved absolute path
    if start and start > 1:                       # resume mid-track after a breaking-news interrupt
        exe = Path(player_path).name.lower()
        s = str(int(start))
        if "mpv" in exe:
            argv.insert(1, f"--start={s}")
        elif "ffplay" in exe:
            argv[1:1] = ["-ss", s]
        elif "vlc" in exe:                        # cvlc
            argv.insert(1, f"--start-time={s}")
        # anything else is not in SEEK_PLAYERS -> the track restarts from the top
    return argv


# --------------------------------------------------------------------------- sources
def _read_key():
    if KEY_FILE.exists():
        k = KEY_FILE.read_text(encoding="utf-8").strip()
        if k:
            return k
    return os.environ.get("STABILITY_API_KEY", "").strip()


def _cmdline(parts, call=False):
    """`parts` as one command line to paste: shlex quoting on macOS and Linux; on Windows forward
    slashes, double quotes around a part with a space, and with `call` PowerShell's `&` before a
    quoted program, which PowerShell otherwise reads as a string rather than running it."""
    if not IS_WIN:
        import shlex
        return " ".join(shlex.quote(p) for p in parts)
    parts = [f'"{p}"' if " " in p else p for p in (p.replace("\\", "/") for p in parts)]
    return ("& " if call and parts[0].startswith('"') else "") + " ".join(parts)


def _console_python():
    """The Python running now, with pythonw.exe (no console, so no hidden prompt) as python.exe."""
    exe = Path(sys.executable or "python")
    return str(exe.with_name("python.exe") if IS_WIN and exe.name.lower() == "pythonw.exe" else exe)


def _self_cmd(*args):
    """A command the user can paste into their own terminal to run this radio.py with the Python
    running now - for `key`, whose hidden prompt needs a real terminal, so a first-time user
    never has to work out which of the plugin's folders holds radio.py or which Python to call."""
    return _cmdline([_console_python(), str(CODE_DIR / "radio.py")] + list(args), call=True)


STEP_INDENT = " " * 7          # a step's command, path or address sits on its own line, this far in


def _steps(steps, again=""):
    """Numbered steps, as text. A step given as (text, line) puts `line` - a command, path or web
    address - on a line of its own between blank lines, so it can be copied whole. `again` adds a
    last step: the command to run to check the result."""
    if again:
        steps = list(steps) + [f"Run {again} again to check."]
    out = []
    for i, step in enumerate(steps, 1):
        text, line = step if isinstance(step, tuple) else (step, "")
        out.append(f"  {i}. {text}")
        if line:
            out += ["", f"{STEP_INDENT}{line}", ""]
    return "\n".join(out).rstrip("\n")


KEY_ENV_NOTE = "  Or set the STABILITY_API_KEY environment variable instead."


def _key_help(again=""):
    """The steps that store an API key, with the exact command for this install, then the
    environment variable instead. The key is typed at a hidden prompt, which needs a real
    terminal, so the user runs the command; Claude can't."""
    return _steps(["Get a key at https://platform.stability.ai",
                   ("Open a terminal outside Claude Code and run:", _self_cmd("key")),
                   "Paste the key when asked (it stays hidden) and press Enter."], again) + "\n" + KEY_ENV_NOTE


def _print_key_help(lead):
    """Every no-key message: `lead`, then the steps that store a key."""
    print(f"{lead}\n{_key_help()}")


# The oldest Python that still gets security fixes: 3.10 reached end of life on 2026-10-01
# (devguide.python.org/versions). hooks/radio-hook.sh refuses anything older; a test keeps them equal.
PY_MIN = (3, 11)
# The Python the install commands name: the newest that winget packages (3.14 on 2026-10-19).
PY_INSTALL = "3.14"


def _install_cmd(program="player", version=PY_INSTALL):
    """(name, install command) for an audio player, or with "ffmpeg" FFmpeg itself, or with "python"
    Python `version`, on this OS. Linux has one command only for the distro's own Python, so any
    other version gets ""."""
    if program == "python":
        if IS_WIN:
            return "Python", f"winget install Python.Python.{version}"
        if sys.platform == "darwin":
            return "Python", "brew install python" if version == PY_INSTALL else f"brew install python@{version}"
        return "Python", "sudo apt install python3" if version == PY_INSTALL else ""
    if IS_WIN:
        return "FFmpeg", "winget install Gyan.FFmpeg"
    if sys.platform == "darwin":
        return ("mpv", "brew install mpv") if program == "player" else ("FFmpeg", "brew install ffmpeg")
    return "FFmpeg", "sudo apt install ffmpeg"


def _install_hint():
    """How to install an audio player, in one line, for `play`'s message."""
    name, cmd = _install_cmd()
    if IS_WIN:
        return f"install {name} ({cmd}), then restart Claude Code"
    if sys.platform == "darwin":
        return f"install {name} ({cmd})"
    return f"install {name} ({cmd}, or your package manager's ffmpeg or mpv)"


def _curl():
    c = shutil.which("curl")
    if not c and IS_WIN and Path("C:/Windows/System32/curl.exe").exists():
        c = "C:/Windows/System32/curl.exe"
    return c


def _curl_run(curl, key, args, timeout=90):
    """Run curl with the bearer token supplied through a config read from stdin (-K -), so the key
    never appears on the command line, where any local process can read it from the process list."""
    cfg = f'header = "Authorization: Bearer {key}"\n'
    return subprocess.run([curl, "-sS", "-K", "-"] + list(args), input=cfg,
                          capture_output=True, text=True, timeout=timeout,
                          creationflags=CREATE_NO_WINDOW)


# Cloudflare fronts api.stability.ai and 403s the default "Python-urllib/x.y"
# agent with a challenge page, so every urllib call must send its own.
USER_AGENT = "terminal-fm/1.0"


def _auth_headers(key, accept):
    return {"Authorization": f"Bearer {key}", "Accept": accept, "User-Agent": USER_AGENT}


def _ssl_context():
    """TLS context for API calls.

    Defaults to the platform trust store. `stability_api.ca_bundle` in config.json
    overrides it with a PEM, for machines whose root store can't build a path to
    the API's chain.
    """
    return ssl.create_default_context(cafile=_ca_bundle() or None)


def _ca_bundle():
    """The PEM file `stability_api.ca_bundle` names, expanded, when it exists; else ""."""
    ca = (CONFIG.get("stability_api") or {}).get("ca_bundle") or ""
    ca = os.path.expandvars(os.path.expanduser(ca)) if ca else ""
    return ca if ca and Path(ca).exists() else ""


def _http_post(url, key, fields, timeout=60):
    """Multipart POST via urllib; returns (http_code, body_text).

    ("", message) means the request never completed (DNS/TCP/TLS), which is the
    case curl's HTTP code alone can't distinguish from an API error.
    """
    boundary = "----radio" + uuid.uuid4().hex
    parts = [f'--{boundary}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'
             for k, v in fields.items()]
    body = ("".join(parts) + f"--{boundary}--\r\n").encode("utf-8")
    req = urllib.request.Request(url, data=body, method="POST", headers={
        **_auth_headers(key, "audio/*"),
        "Content-Type": f"multipart/form-data; boundary={boundary}"})
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=_ssl_context()) as r:
            return str(r.status), r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return str(e.code), e.read().decode("utf-8", "replace")
    except Exception as e:
        return "", f"{type(e).__name__}: {e}"


def _http_get(url, key, dest, timeout=60):
    """GET to a file via urllib; returns (http_code, transport_error)."""
    req = urllib.request.Request(url, headers=_auth_headers(key, "audio/*"))
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=_ssl_context()) as r:
            dest.write_bytes(r.read())
            return str(r.status), ""
    except urllib.error.HTTPError as e:
        try:
            dest.write_bytes(e.read())
        except Exception:
            pass
        return str(e.code), ""
    except Exception as e:
        return "", f"{type(e).__name__}: {e}"


def _api_post(url, key, fields):
    """urllib first, curl as fallback. Returns (http_code, body_text)."""
    code, body = _http_post(url, key, fields)
    if code:
        return code, body
    curl = _curl()
    if not curl:
        return code, body
    c2, b2 = _curl_post(curl, url, key, fields)
    return (c2, b2) if c2 and c2 != "000" else (code, body)


def _api_get(url, key, dest):
    """urllib first, curl as fallback. Returns (http_code, transport_error)."""
    code, err = _http_get(url, key, dest)
    if code:
        return code, err
    curl = _curl()
    if not curl:
        return code, err
    res = _curl_run(curl, key, ["-o", str(dest), "-w", "%{http_code}", "-H", "Accept: audio/*", url])
    c2 = (res.stdout or "").strip()[-3:]
    if c2 and c2 != "000":
        return c2, ""
    return code, err


def _curl_post(curl, url, key, fields):
    """Multipart POST via curl; returns (http_code, body_text)."""
    args = ["-w", "\n%{http_code}", "--max-time", "60", "-X", "POST", "-H", "Accept: audio/*"]
    for k, v in fields.items():
        # --form-string, never -F: -F reads a value starting with "@" or "<" as a FILE to upload,
        # and the prompt is user text.
        args += ["--form-string", f"{k}={v}"]
    args.append(url)
    res = _curl_run(curl, key, args)
    out = (res.stdout or "").strip()
    nl = out.rfind("\n")
    return (out[nl + 1:].strip(), out[:nl]) if nl >= 0 else ("", out)


def _poll_result(key, sc, gen_id, dest, timeout=180):
    """Poll the async results endpoint; save audio to dest. Returns (ok, error)."""
    url = sc["results_url"].rstrip("/") + "/" + gen_id
    deadline = time.time() + timeout
    while time.time() < deadline:
        code, terr = _api_get(url, key, dest)
        if code == "200":
            return True, None
        if code == "202":          # still rendering
            time.sleep(2)
            continue
        if not code:
            return False, f"result transport failure: {terr[:160]}"
        err = ""
        try:
            err = dest.read_text("utf-8", "replace")[:160]
        except Exception:
            err = terr[:160]
        return False, f"result HTTP {code}: {err}"
    return False, "timed out waiting for result"


def _balance(key):
    """Credits left on the Stability account, or None if it can't be read. gen reports its exact
    cost as the drop in this number across the run, rather than a per-track price from memory."""
    url = CONFIG["stability_api"]["balance_url"]
    hdrs = _auth_headers(key, "application/json")
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=hdrs), timeout=30,
                                    context=_ssl_context()) as r:
            body = r.read().decode("utf-8", "replace")
    except Exception:
        curl = _curl()
        if not curl:
            return None
        args = ["--max-time", "30"]
        for k, v in hdrs.items():
            if k != "Authorization":            # the token travels via _curl_run's stdin config
                args += ["-H", f"{k}: {v}"]
        try:
            body = _curl_run(curl, key, args + [url], timeout=40).stdout
        except Exception:
            return None
    try:
        return float(json.loads(body)["credits"])
    except Exception:
        return None


def _spent(key, before, charged):
    """Credits used since `before`, or None if unknown. The ledger lags: a 5s track's 26-credit
    charge was still missing 5s after the result arrived (2026-09-18), so an unmoved balance after
    a charge is reported as unknown - never as 0."""
    if before is None:
        return None
    for _ in range(5):
        after = _balance(key)
        if after is None:
            return None
        if not charged or after < before:
            return round(before - after, 4)
        time.sleep(1)
    return None


def _ffmpeg():
    """ffmpeg's path, or None. Like ffplay, it often sits in C:\\ffmpeg\\bin off PATH on Windows."""
    return shutil.which("ffmpeg") or _win_ffmpeg_tool("ffmpeg")


def _wav_to_mp3(wav, mp3):
    """Encode `wav` to `mp3` with ffmpeg. Returns None on success, else the reason."""
    exe = _ffmpeg()
    if not exe:
        return "ffmpeg not found"
    try:
        r = subprocess.run([exe, "-nostdin", "-y", "-loglevel", "error", "-i", str(wav),
                            "-codec:a", "libmp3lame", "-b:a", MP3_BITRATE, str(mp3)],
                           capture_output=True, text=True, timeout=300,
                           creationflags=CREATE_NO_WINDOW)
    except Exception as e:
        return f"ffmpeg failed: {e}"
    if r.returncode != 0 or not mp3.exists() or mp3.stat().st_size == 0:
        return f"ffmpeg exit {r.returncode}: {(r.stderr or '').strip()[:160]}"
    return None


NOTHING_SENT = "nothing sent"     # a source's credits value when it refused before any request


# A new track's file name starts with its prompt, cut at a whole word: NAME_CHARS characters tell
# tracks apart and give the skill words to match a genre against, and stay short in `list` and the
# statusline. Windows' 260-character path is the tightest limit: a 52-character library path plus
# \_archive\, the stamp and a clash suffix measured ~160 (2026-10-28). NAME_BYTES keeps a prompt in a
# script with 4-byte letters under the 255-byte names of Linux and macOS.
NAME_CHARS = 60
NAME_BYTES = 180


def _slug(prompt):
    """The start of a track's file name: the prompt's words, lowercased and joined by single dashes,
    cut at a whole word to NAME_CHARS characters and NAME_BYTES UTF-8 bytes; "track" if none."""
    slug = "-".join("".join(c if c.isalnum() else " " for c in prompt.lower()).split())
    cut = slug[:NAME_CHARS].encode("utf-8")[:NAME_BYTES].decode("utf-8", "ignore")
    if cut != slug and slug[len(cut)] != "-" and "-" in cut:
        cut = cut.rsplit("-", 1)[0]                   # cut inside a word: back to the last whole one
    return cut or "track"


def source_stability_api(prompt, count, duration):
    """Stable Audio 3 (async): submit -> poll results -> save mp3 / wav to the library.
    Returns (tracks_saved, credits_spent_or_None), or (0, NOTHING_SENT) when it refused before
    sending anything (no key). Prints only failures; cmd_gen prints the summary.

    The SA3 endpoint accepts only model='stable-audio-3' and steps is fixed at 8 (config).
    With output_format 'wav+mp3' it requests a WAV into <library>/_wav and encodes the MP3 that
    plays from it; if the encode fails the WAV moves into the library so the track still plays.
    """
    sc = CONFIG["stability_api"]
    key = _read_key()
    if not key:
        _print_key_help("No API key yet. To add one:")
        return 0, NOTHING_SENT
    slug = _slug(prompt)
    both = sc["output_format"] == BOTH_FORMATS
    api_fmt = "wav" if both else sc["output_format"]
    before = _balance(key)
    made = submitted = 0
    for i in range(1, count + 1):
        stamp = time.strftime("%Y%m%d-%H%M%S")
        if both:
            (OUTDIR / WAV_SUBDIR).mkdir(parents=True, exist_ok=True)
            dest = OUTDIR / WAV_SUBDIR / f"{slug}-{stamp}-{i}.wav"
        else:
            dest = OUTDIR / f"{slug}-{stamp}-{i}.{api_fmt}"
        code, body = _api_post(sc["submit_url"], key, {
            "prompt": prompt, "model": sc["model"], "steps": sc["steps"],
            "duration": duration, "output_format": api_fmt,
        })
        if code not in ("200", "202"):
            print(f"FAILED ({i}/{count}) submit HTTP {code or '???'}: {body[:160]}")
            continue
        try:
            gen_id = json.loads(body)["id"]
        except Exception:
            print(f"FAILED ({i}/{count}) unexpected submit body: {body[:160]}")
            continue
        submitted += 1
        ok, err = _poll_result(key, sc, gen_id, dest)
        if ok and both:
            mp3 = OUTDIR / (dest.stem + ".mp3")
            why = _wav_to_mp3(dest, mp3)
            if why:
                _unlink_quiet(mp3)
                kept = OUTDIR / dest.name
                try:
                    dest.replace(kept)
                except Exception:
                    kept = dest
                print(f"MP3 ({i}/{count}) not made ({why}); kept the WAV in "
                      f"{kept.parent.name} instead.")
                dest = kept
            else:
                dest = mp3
        if ok:
            history_add(prompt, duration, dest.name, idea=GEN_IDEA, source=CONFIG["source"])
            made += 1
        else:
            print(f"FAILED ({i}/{count}) {err}")
            _unlink_quiet(dest)
    return made, _spent(key, before, submitted)


# Where music comes from, keyed by config "source". A new provider is one function with the same
# signature (prompt, count, duration) -> (tracks_saved, credits_spent_or_None) registered here.
# A provider that refuses before sending any request returns NOTHING_SENT as the credits, so gen
# prints "Cost: 0 credits (nothing sent)"; None stays "unknown", for a real submit whose balance
# change could not be read.
SOURCES = {
    "stability-api": source_stability_api,
}


# --------------------------------------------------------------------------- prompt enhancement
LLM_DIR = ROOT / "llm"
# The llama-cli and model that last gave an answer, written by _llm_run: `setup` counts the enhancer
# as installed only while that pair is still the one in use, so a model that never answered (a test
# that timed out, a llama-cli without --single-turn) isn't reported installed.
LLM_ANSWERED = LLM_DIR / ".answered"
# Bounds for gen's auto-picked duration (pick_duration), also stated to the model so its answer
# isn't silently truncated. 1-380s is the API's documented duration range: the length should be
# whatever suits the prompt, from a one-second sting up to a long build. Real generations have
# confirmed 5s and 218s; neither end of the range has been tried.
ENH_DUR_MIN, ENH_DUR_MAX = 1, 380


def _clamp_dur(secs):
    return max(ENH_DUR_MIN, min(ENH_DUR_MAX, secs))


# The enhancer's system prompt lives in a markdown file so it can be tuned without touching code,
# and it is re-read on every call. HTML comments are notes for whoever edits it and are stripped.
# The enhancer writes only the prompt: asked for a length too, the longer instructions pulled the
# 4B model off its anchors (techno 30s at temp 0.9), so length is pick_duration's job at temp 0.
# Data directory first: a plugin's own folder is replaced on every update (and old versions are
# swept), so a tuned prompt kept there would be lost. The copy beside radio.py is the shipped one.
ENHANCE_USER = ROOT / "prompts" / "enhance.md"
ENHANCE_SHIPPED = CODE_DIR / "prompts" / "enhance.md"


def enhance_file():
    """<data dir>/prompts/enhance.md when it exists, else the copy shipped beside radio.py."""
    return ENHANCE_USER if ENHANCE_USER.is_file() else ENHANCE_SHIPPED

# Stable Audio 3 reads at most 256 prompt tokens. Its T5Gemma text encoder (google/t5gemma-b-b-ul2)
# tokenizes with truncation at 256 and no BOS/EOS, so anything past that is cut off without an
# error (SA3 tech report, arXiv 2605.17991: "long prompts are truncated to 256"; the SA3 repo's
# t5gemma_mlx.py: `Encode(p)[:max_len]`, max_len=256). The hosted API takes up to 10,000
# characters, so an over-long prompt is charged in full and its tail silently ignored.
SA3_PROMPT_TOKENS = 256
# That encoder's tokenizer.json (Hugging Face google/t5gemma-b-b-ul2), for an exact count. Optional:
# without it the count is estimated at 4 characters a token (the fewest per token over the prompt
# history was 4.16, 2026-09-25), which undercounts digits, symbols and non-Latin text: chord symbols
# and Japanese both measured 1.41 characters a token.
TOKENIZER_FILE = LLM_DIR / "t5gemma-tokenizer.json"
CHARS_PER_TOKEN = 4             # the estimate without it
_TOKENIZER = None


def _tokenizer():
    """(vocab, merge ranks, added-token regex) from TOKENIZER_FILE, loaded once (~0.5s); None if
    the file is missing or unreadable."""
    global _TOKENIZER
    if _TOKENIZER is None:
        try:
            j = json.loads(TOKENIZER_FILE.read_text(encoding="utf-8"))
            ranks = {}
            for i, pair in enumerate(j["model"]["merges"]):
                a, b = pair if isinstance(pair, list) else pair.split(" ", 1)
                ranks.setdefault((a, b), i)
            added = sorted({t["content"] for t in j.get("added_tokens", [])}, key=len, reverse=True)
            _TOKENIZER = (j["model"]["vocab"], ranks,
                          re.compile("|".join(map(re.escape, added))) if added else None)
        except Exception:
            _TOKENIZER = False
    return _TOKENIZER or None


def _bpe_count(word, vocab, ranks):
    """How many tokens BPE makes of one run of text: start from characters (one outside the vocab
    falls back to a token per UTF-8 byte), then merge the lowest-ranked adjacent pair, leftmost on
    a tie, until none is left - the order Hugging Face `tokenizers` merges in."""
    syms = []
    for ch in word:
        syms.extend([ch] if ch in vocab else [f"<0x{b:02X}>" for b in ch.encode("utf-8")])
    n = len(syms)
    nxt, prv = list(range(1, n + 1)), list(range(-1, n - 1))
    heap = [(ranks[p], i) for i, p in enumerate(zip(syms, syms[1:])) if p in ranks]
    heapq.heapify(heap)
    count = n
    while heap:
        r, i = heapq.heappop(heap)
        j = nxt[i]
        if syms[i] is None or j >= n or ranks.get((syms[i], syms[j])) != r:
            continue                # stale: one side has merged since this pair was queued
        syms[i] += syms[j]
        syms[j] = None
        nxt[i] = nxt[j]
        if nxt[i] < n:
            prv[nxt[i]] = i
        count -= 1
        for a, b in ((prv[i], i), (i, nxt[i])):
            if a >= 0 and b < n and (syms[a], syms[b]) in ranks:
                heapq.heappush(heap, (ranks[(syms[a], syms[b])], a))
    return count


def prompt_tokens(text):
    """(tokens, exact): the prompt's length as Stable Audio 3's tokenizer counts it. Exact with
    TOKENIZER_FILE installed - 0 mismatches against Hugging Face `tokenizers` 0.22.1 over 8,117
    distinct strings (prompts, every line of the repo's text files, random Unicode, emoji, CJK,
    combining marks, special-token text, whitespace runs; 2026-10-14). Added
    tokens (newline runs, <table>, <eos>, ...) match whole first; each gap between them is one BPE
    word, because Gemma's pre-tokenizer splits on a space its normalizer has already turned to U+2581."""
    tok = _tokenizer()
    if not tok:
        return -(-len(text) // CHARS_PER_TOKEN), False
    vocab, ranks, split = tok
    total = pos = 0
    for m in (split.finditer(text) if split else ()):
        if m.start() > pos:
            total += _bpe_count(text[pos:m.start()].replace(" ", "\u2581"), vocab, ranks)
        total += 1
        pos = m.end()
    if pos < len(text):
        total += _bpe_count(text[pos:].replace(" ", "\u2581"), vocab, ranks)
    return total, True


def _tokens_desc(n, exact):
    return (f"{n} tokens" if exact else
            f"about {n} tokens (estimated at {CHARS_PER_TOKEN} characters a token: {TOKENIZER_FILE.name} "
            f"is not in {LLM_DIR})")


def enhance_system():
    """The enhancer's system prompt from enhance_file(), comments stripped; "" if unreadable."""
    try:
        text = enhance_file().read_text(encoding="utf-8")
    except Exception:
        return ""
    return re.sub(r"<!--.*?-->", "", text, flags=re.S).strip()

# The model sometimes copies placeholder punctuation ("<80 BPM>") into the prompt, or Markdown
# emphasis despite being told not to ("a soft *clink*", 2026-09-19); none of it means anything to
# Stable Audio, so drop angle brackets, stray quotes, asterisks and backticks.
_PROMPT_JUNK_RE = re.compile(r"[<>\"*`]")
_DUR_RE = re.compile(r"[|,;.\-]?\s*\(?\s*DURATION\s*[:=\-]?\s*(\d{1,5})\s*"
                     r"(?:seconds|second|secs|sec|s)?\b\s*\)?\.?", re.I)


_ANSI_RE = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")
# Lines llama-cli prints to STDOUT (not stderr, and --log-disable does not suppress them):
# the ASCII banner, build/model info and the slash-command help.
_CHROME_RE = re.compile(r"^\s*(Loading model|build\s*:|model\s*:|ftype\s*:|modalities\s*:|"
                        r"using custom system prompt|available commands:|/(exit|regen|clear|read|glob)\b|"
                        r"[▀-▟\s]+$)", re.I)


def _strip_cli_chrome(out, idea=""):
    """Isolate the model's answer in llama-cli's stdout.

    llama-cli writes its banner, build info and command list to stdout, echoes the input after
    a '> ' marker, and follows the answer with a '[ Prompt: ... t/s ]' timing line and
    'Exiting...'. Without this filter all of that ends up in the audio prompt."""
    lines = _ANSI_RE.sub("", out or "").replace("\r", "").split("\n")
    start = 0
    for i, ln in enumerate(lines):
        if ln.lstrip().startswith(">"):       # the echoed input - answer begins after it
            start = i + 1
            break
    else:
        if idea:                              # no marker (build change?) - cut after the echo text
            joined = "\n".join(lines)
            pos = joined.rfind(idea)
            if pos != -1:
                lines = joined[pos + len(idea):].split("\n")
    body = []
    for ln in lines[start:]:
        s = ln.strip()
        if s.startswith("[ ") or s.startswith("Exiting") or s.startswith(">"):
            break                             # timing footer / exit notice / next prompt
        if _CHROME_RE.match(ln):
            continue                          # backstop if the '>' marker was never found
        body.append(ln)
    return "\n".join(body).strip()


def _split_duration(text):
    """Pull a stray 'DURATION: <n>' out of the enhancer's output so it never reaches the audio
    prompt (the enhancer is no longer asked for one, but a small model can still add it).
    Returns (prompt_without_it, seconds_or_None); the value is clamped to [ENH_DUR_MIN, ENH_DUR_MAX]."""
    m = _DUR_RE.search(text)
    if not m:
        return text.strip(), None
    prompt = " ".join((text[:m.start()] + " " + text[m.end():]).split())
    secs = _clamp_dur(int(m.group(1)))
    return prompt.strip(" ,;|-"), secs


# Stable Audio 3's prompt tags (its prompt guide: TrackType, Format, Genre) as the user typed them,
# and the "Label:" words the model has been seen to write in its caption (_LABEL_RE). The model
# invented tags ("Tag: TrackType: BossBattle") when told it could copy a supplied one, and dropped
# a supplied one when told to write none, so code does both: strip those labels, then put the
# user's own tags back in front.
_SA3_TAGS = "TrackType|Format|Genre"
_SA3_TAG_RE = re.compile(rf"\b({_SA3_TAGS})\s*:\s*([A-Za-z][\w-]*)", re.I)
_LABEL_RE = re.compile(rf"\b(?:{_SA3_TAGS}|Tags?|VocalType|Instruments?|Prompt)\s*:\s*", re.I)
_NO_KEY_RE = re.compile(r",?\s*\bin no(?: particular| specific)? key\b", re.I)


def _tidy_caption(text, idea):
    """The enhancer's caption with invented labels and an "in no key" removed (told to give a
    sound effect no key, the model once wrote exactly that), trailing punctuation stripped, and
    the brief's own SA3 tags restored at the front, once each."""
    pairs = list(dict.fromkeys(_SA3_TAG_RE.findall(idea)))
    for label, value in pairs:
        text = re.sub(rf"\b{label}\s*:\s*{re.escape(value)}\b\s*,?\s*", "", text, flags=re.I)
    text = _NO_KEY_RE.sub("", _LABEL_RE.sub("", text))
    text = " ".join(text.split()).strip(" ,;.")
    tags = [f"{label}: {value}" for label, value in pairs]
    return ", ".join(tags + [text]) if text else ""


def _llm_exe():
    """Where llama-cli goes: <data dir>/llm/bin."""
    return LLM_DIR / "bin" / ("llama-cli.exe" if IS_WIN else "llama-cli")


def _llm_paths():
    exe = _llm_exe()
    exe = str(exe) if exe.exists() else shutil.which("llama-cli")
    ggufs = sorted(LLM_DIR.glob("*.gguf"))
    return exe, (str(ggufs[0]) if ggufs else None)


def _llm_run(system, user, temp, n_predict, timeout=180, top_p=None, top_k=None, min_p=None):
    """One-shot local LLM call (llama.cpp CLI, CPU-only, -ngl 0 so the GPU stays free). The
    process loads, answers, and exits - nothing stays resident. Returns the model's answer with
    llama-cli's stdout chrome stripped, or "" if it isn't installed or the call fails. Sampling
    knobs left as None keep llama-cli's own defaults."""
    exe, model = _llm_paths()
    if not exe or not model:
        return ""
    knobs = []
    for flag, v in (("--top-p", top_p), ("--top-k", top_k), ("--min-p", min_p)):
        if v is not None:
            knobs += [flag, str(v)]
    try:
        out = subprocess.run(
            [exe, "-m", model, "-ngl", "0", "--single-turn", "--no-display-prompt",
             "--simple-io", "--temp", str(temp), "-n", str(n_predict)] + knobs
            + ["-sys", system, "-p", user],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=timeout, creationflags=CREATE_NO_WINDOW).stdout
    except Exception:
        return ""
    answer = _strip_cli_chrome(out, user)
    if answer and _llm_answered() != [exe, model]:
        try:
            _write_json(LLM_ANSWERED, [exe, model])
        except OSError:
            pass                                      # setup then offers the test; the answer still counts
    return answer


def _llm_answered():
    """[llama-cli, model] as they were when one last answered (LLM_ANSWERED), or None."""
    try:
        pair = json.loads(LLM_ANSWERED.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return pair if isinstance(pair, list) and len(pair) == 2 else None


def _enhancer_ready():
    """llama-cli and a model are here, and that pair has answered."""
    paths = list(_llm_paths())
    return all(paths) and _llm_answered() == paths


# Qwen sampling for the enhancer: section 3 of Qwen3_4B_SA3_Enhancer_Setup_v1.0.md (Qwen's own
# recommendation for Instruct-2507, plus a 512-token cap sized for a one-paragraph rewrite).
ENH_SAMPLING = {"temp": 0.7, "top_p": 0.8, "top_k": 20, "min_p": 0, "n_predict": 512}
# Replies prompts/enhance.md tells the model to give INSTEAD of a prompt. They are for the user,
# never for Stable Audio, so egen stops on them (setup doc section 4: only a successful rewrite may
# be forwarded). Keep these in step with the wording in enhance.md.
ENH_NOT_PROMPTS = ("This request requires a vocal or speech model",
                   "Please provide the music or sound you want to enhance")


# Families of sound the rewrite has both asked for and denied in one paragraph ("brushed drums ...
# no beats", "dusty drums ... No percussion patterns"): 3 of the 15 rewrites read on 2026-09-19/20.
# String matching, not comprehension - it catches an explicit denial of something the same prompt
# also describes, and nothing subtler (a "fast" piece described as "slow" is not caught).
CONFLICT_TERMS = {
    "percussion": ("drums", "drum", "percussion", "beat", "beats", "kick", "snare", "hi-hat",
                   "hi-hats", "hihat", "cymbal", "cymbals", "drum kit"),
    "vocals": ("vocal", "vocals", "voice", "voices", "singing", "choir"),
    "reverb": ("reverb", "echo", "delay"),
    "bass": ("bass", "bassline", "basslines", "sub-bass"),
}
_NEG_RE = re.compile(r"\b(?:no|not|without|never|free of|devoid of|lacking|absent)\b")


def _contradictions(text):
    """Sound families the text both denies and describes, as ["'no beats' vs 'brushed drums'"].

    Negation is scoped to the sentence: "no vocals, with driving drums" keeps the drums positive,
    while "No percussion, rhythm, or beat structure" reads as one denial. Scoping wider produced
    false alarms on legitimately beatless prompts, and a false alarm costs a generation."""
    found = []
    for family, terms in CONFLICT_TERMS.items():
        neg = pos = None
        for s in re.split(r"(?<=[.!?])\s+", text or ""):
            low = s.lower()
            for t in terms:
                for m in re.finditer(rf"\b{re.escape(t)}\b", low):
                    cues = list(_NEG_RE.finditer(low[:m.start()]))
                    if cues and neg is None:
                        neg = s[cues[-1].start():m.end()]
                    elif not cues and pos is None:
                        pos = " ".join((s[:m.start()].split()[-2:]) + [s[m.start():m.end()]])
        if neg and pos:
            found.append(f"'{neg.strip()}' vs '{pos.strip()}'")
    return found


def enhance_prompt(idea, duration=None):
    """Rewrite a rough idea into an SA3 prompt with the local LLM. `duration` is the clip length
    in seconds, already chosen, handed over so the rewrite can scale the number of parts to the
    clip (enhance.md: a short clip gets fewer parts and no build words); it stays an external
    control and the instructions forbid writing it into the prompt.

    Returns (prompt, None, conflicts), or (None, reply, []) when the model answered with something
    that must not reach Stable Audio: a capability or missing-input message, a clarification
    question, or a rewrite over SA3_PROMPT_TOKENS on both attempts (a runaway that hit the 512-token
    cap is far over it too). `conflicts` is what `_contradictions` still finds after one retry - a
    second sample at temp 0.7 is genuinely different and usually clean. Falls back to
    (idea, None, []) if the enhancer isn't installed, has no instructions file, or errors."""
    if not idea.strip():            # the model's own missing-input reply, without a model call
        return None, ENH_NOT_PROMPTS[1] + ".", []
    exe, model = _llm_paths()
    if not exe or not model:
        print(f"Enhancer not installed (need llama-cli + a .gguf under {LLM_DIR}); using idea as-is.")
        return idea, None, []
    system = enhance_system()
    if not system:
        print(f"Enhancer instructions missing ({enhance_file()}); using idea as-is.")
        return idea, None, []
    s = ENH_SAMPLING
    # One line: llama-cli echoes the brief back and _strip_cli_chrome only skips the echo's first
    # line, so a second line ended up glued to the front of the prompt ("Clip A cinematic...").
    head = f"clip length {duration} seconds"      # also how an echoed brief is recognised below
    brief = idea if duration is None else f"{idea} ({head} - do not mention the length)"
    # Attempt 2 runs only when attempt 1 is over SA3's prompt limit or contradicts itself.
    for attempt in (1, 2):
        answer = _llm_run(system, brief, s["temp"], s["n_predict"],
                          top_p=s["top_p"], top_k=s["top_k"], min_p=s["min_p"])
        answer = _PROMPT_JUNK_RE.sub("", " ".join(answer.split()).strip())
        if not answer:
            return idea, None, []
        if answer.startswith(ENH_NOT_PROMPTS) or answer.endswith("?"):
            return None, answer, []
        if duration is not None and head in answer.lower():   # the brief echoed back: no rewrite
            return None, ENH_NOT_PROMPTS[1] + ".", []
        enhanced, _ = _split_duration(answer)
        enhanced = _tidy_caption(enhanced, idea) or idea
        n, exact = prompt_tokens(enhanced)
        too_long = n > SA3_PROMPT_TOKENS
        if too_long:
            continue
        conflicts = _contradictions(enhanced)
        if not conflicts:
            return enhanced, None, []
    if too_long:
        return None, (f"the rewrite ran to {_tokens_desc(n, exact)}, over Stable Audio 3's "
                      f"{SA3_PROMPT_TOKENS}-token prompt limit, on both attempts. Run it again."), []
    return enhanced, None, conflicts


# ---- auto duration: `gen` with no duration picks a length that suits the prompt ----------------
# Typical lengths by what the prompt asks for. Checked in order and the first match wins, so a
# use-case word ("commercial bed", "intro") beats the genre it's written in. These are taste
# defaults, not measured optima. They are the whole answer when no local model is installed, and
# the model's anchors when one is, so both paths agree on the common cases.
DUR_RULES = [
    (5, ("notification", "sting", "stinger")),
    (15, ("jingle", "bumper")),
    (30, ("intro", "outro", "commercial", "advert")),
    (300, ("ambient", "drone", "meditation", "sleep", "soundscape")),
    (240, ("techno", "trance", "progressive")),
    (120, ("trailer", "punk", "hardcore")),
    (150, ("synthwave", "retrowave", "lo-fi", "lofi", "lo fi", "jazz", "hip hop", "hip-hop",
           "chillhop", "funk", "soul", "house", "rock", "pop")),
]


def _dur_guide(default):
    return ("; ".join(f"{', '.join(words)}: about {secs}s" for secs, words in DUR_RULES)
            + f"; anything else: about {default}s")


def _dur_sys(default):
    return ("You pick the length of an instrumental track for the Stable Audio 3 music model. "
            "Choose the duration in whole seconds that best suits the music prompt, between "
            f"{ENH_DUR_MIN} and {ENH_DUR_MAX}. Typical lengths - {_dur_guide(default)}. "
            "A use-case word (intro, commercial, jingle) outweighs the genre it is "
            "written in. If the prompt states a length, use it. Otherwise adjust within the range "
            "for energy, tempo and how much the piece needs to develop. Reply with ONE line only: "
            "DURATION: <seconds> - <reason in at most 10 words>")


# A length the user actually wrote beats the model's guess: "90 second cinematic trailer build"
# came back as 120s at temp 0, the DUR_RULES trailer anchor, ignoring the stated 90. Only a
# spelled-out unit counts, so "80s synthwave" stays a decade, and the lookahead skips a number
# that times a sound rather than the clip ("an 8 second reverb tail").
_STATED_DUR_RE = re.compile(
    r"\b(\d{1,4})\s*-?\s*(sec|secs|second|seconds|min|mins|minute|minutes)\b"
    r"(?!\s*(?:delay|reverb|tail|decay|fade|attack|release|sustain|pause|gap|silence))", re.I)


def _stated_duration(text):
    """The clip length written into the text in plain words, clamped, or None."""
    m = _STATED_DUR_RE.search(text or "")
    if not m:
        return None
    secs = int(m.group(1)) * (60 if m.group(2).lower().startswith("min") else 1)
    return _clamp_dur(secs)


def pick_duration(prompt):
    """Choose a track length for a prompt (or, from egen, for the rough idea) that came with none.
    Returns (seconds, who, note): `who` names the decider for gen's "Length:" line, `note` flags a
    clamp ("" otherwise).

    The local model reads the whole text (tempo, energy, "long build", a stated length), clamped to
    [ENH_DUR_MIN, ENH_DUR_MAX]. Without a model, or with an answer that has no number in it, the
    first DUR_RULES keyword decides; with no match either, the configured default. Temp 0 so the
    same text always gets the same length."""
    stated = _stated_duration(prompt)
    if stated is not None:
        return stated, "as stated", ""
    default = int(CONFIG["stability_api"]["duration"])
    exe, model = _llm_paths()
    if exe and model:
        ans = " ".join(_llm_run(_dur_sys(_clamp_dur(default)),
                                prompt, 0, 48, timeout=120).split())
        m = _DUR_RE.search(ans) or re.search(r"\b(\d{1,4})\b", ans)
        if m:
            raw = int(m.group(1))
            secs = _clamp_dur(raw)
            # A clamp is reported, not hidden: the model's own number is overridden.
            return secs, "local model decided", ("" if secs == raw else f" (model said {raw}s)")
    low = prompt.lower()
    for secs, words in DUR_RULES:
        for w in words:
            if re.search(rf"\b{re.escape(w)}\b", low):
                return secs, "keyword rules decided", ""
    return default, "config default", ""


def _fmt_credits(n):
    return f"{n:.2f}".rstrip("0").rstrip(".")


# --------------------------------------------------------------------------- commands
GEN_USAGE = ('Usage: radio gen "<prompt>"                    <- one track, length picked to suit the prompt\n'
             '       radio gen "<prompt>" <duration>         <- one track, that many seconds\n'
             '       radio gen "<prompt>" <count> <duration> <- N tracks (duration may be "auto")')
GEN_COUNT_CONFIRM = 20      # above this many tracks in one call, ask for "yes" before spending


def cmd_gen(args, decided=None):
    """`decided` is the (who, note) of a caller that already picked the duration and wrote it into
    the args - egen, which picks before rewriting - so gen reports who chose it and doesn't treat
    it as a number the user typed."""
    if not args:
        print(GEN_USAGE)
        return
    prompt = args[0]
    nums = list(args[1:])
    if len(nums) > 2:                   # the old third number (steps) is gone: SA3 fixes steps at 8
        print(GEN_USAGE)
        return
    # The duration slot is nums[0] with one arg, nums[1] with two or more. Leaving it out, or
    # writing "auto" there (the only way to auto-pick for a count), means "pick one for me".
    slot = nums[0] if len(nums) == 1 else (nums[1] if len(nums) > 1 else None)
    asked_auto = slot is not None and slot.lower() == "auto"
    try:
        if len(nums) == 1:
            # ONE number after the prompt is a DURATION, not a count. That is how people write
            # it, and the old count-first reading made `gen "..." 218` mean 218 tracks
            # (~4,360 credits) when a 218-second track was meant. Two numbers = count, duration.
            count, duration = 1, (None if asked_auto else int(nums[0]))
            # Only a typed number can be a misplaced count; egen's picked length is not.
            if decided is None and duration is not None and duration < 10:
                print(f"Refusing: {duration}s is not a plausible track length - a single number "
                      f"after the prompt is the DURATION.\n"
                      f'To generate {duration} tracks instead:  radio gen "<prompt>" {duration} auto')
                return
        else:
            count = int(nums[0]) if nums else 1
            duration = None if (slot is None or asked_auto) else int(slot)
    except ValueError:
        print(GEN_USAGE)
        return
    if count < 1:
        print(GEN_USAGE)
        return
    if count > GEN_COUNT_CONFIRM:       # a typo here is paid for per track; make sure it's meant
        try:
            answer = input(f"Generate {count} tracks (each one is billed)? Type yes to continue: ")
        except Exception:               # no terminal (hook / piped): refuse rather than guess
            answer = ""
        if answer.strip().lower() not in ("y", "yes"):
            print(f"Cancelled. Nothing spent. (Counts above {GEN_COUNT_CONFIRM} need a yes.)")
            return
    # SA3 bills the whole prompt and reads only its first 256 tokens, so refuse before the duration
    # pick or the balance read rather than pay for a track whose prompt was cut short.
    n, exact = prompt_tokens(prompt)
    if n > SA3_PROMPT_TOKENS:
        cut = -(-len(prompt) * (n - SA3_PROMPT_TOKENS) // n)
        print(f"Refusing: the prompt is {_tokens_desc(n, exact)}, and Stable Audio 3 reads only the "
              f"first {SA3_PROMPT_TOKENS} - the rest would be dropped without an error. Cut about "
              f"{cut} of its {len(prompt)} characters. Nothing spent.")
        return
    source = SOURCES.get(CONFIG["source"])
    if not source:
        print(f"Unknown source '{CONFIG['source']}'. Available: {', '.join(SOURCES)}")
        return
    # Output is deliberately four lines (Length / Prompt / Cost / Folder) plus any FAILED lines.
    if duration is None:
        duration, who, note = pick_duration(prompt)
    else:
        who, note = decided or ("user decided", "")
    print(f"Length: {who} {duration}s{note}")
    print(f"Prompt: {prompt}", flush=True)
    made, cost = source(prompt, count, duration)
    if cost == NOTHING_SENT:
        print("Cost: 0 credits (nothing sent)")
    else:
        print("Cost: " + (f"{_fmt_credits(cost)} credits" if cost is not None
                          else "unknown (credit balance unreadable or not updated yet)"))
    total = len(get_library())
    print(f"Folder: {OUTDIR.name} / track(s) added: {made} / total: {total} "
          f"track{'' if total == 1 else 's'}")


def cmd_enhance(args):
    if not args:
        print('Usage: radio enhance "<idea>"')
        return
    if not args[0].strip():
        print(f"Enhancer: {ENH_NOT_PROMPTS[1]}.")
        return
    secs, who, note = pick_duration(args[0])        # from the idea, exactly as egen does it
    prompt, reply, conflicts = enhance_prompt(args[0], duration=secs)
    if reply:
        print(f"Enhancer: {reply}")
        return
    print(f"Length: {who} {secs}s{note}")
    print(f"Prompt: {prompt}")
    if conflicts:                   # printed, not withheld: enhance spends nothing either way
        print(f"Conflict: {'; '.join(conflicts)} - the rewrite contradicts itself (both attempts).")
    # Logged like a generation, marked "enhance": a rewrite worth keeping shouldn't be lost just
    # because nothing was generated from it. `radio prompts <n>` still prints a gen line for it.
    history_add(prompt, secs, "", idea=args[0], kind="enhance")


def cmd_egen(args):
    global GEN_IDEA
    if not args:
        print('Usage: radio egen "<idea>" [count] [duration]')
        return
    idea = args[0]
    if not idea.strip():        # no model calls for an empty idea; enhance_prompt's own reply
        print(f"Enhancer: {ENH_NOT_PROMPTS[1]}.\nNothing generated.")
        return
    GEN_IDEA = idea             # recorded alongside the enhanced prompt in the history
    rest = list(args[1:])
    # The length is settled BEFORE the rewrite and handed to the enhancer, so the rewrite can scale
    # its arrangement to the clip. An empty or "auto" duration slot is filled by the auto-pick,
    # reading the user's own words rather than the rewrite (which can drop a stated "90 second").
    # A typed duration wins and is passed on as it stands.
    slot = 0 if len(rest) <= 1 else 1
    auto = (not rest) or rest[slot].lower() == "auto"
    decided = None
    try:
        if len(rest) > 1:
            int(rest[0])                    # count, checked before the slow model calls
        length = None if auto else int(rest[slot])
    except ValueError:
        print(GEN_USAGE)
        return
    if not auto and len(rest) == 1 and length < 10:
        cmd_gen([idea] + rest)          # same refusal as gen, before the slow model calls
        return
    if auto:
        length, who, note = pick_duration(idea)
        decided = (who, note)
        rest = [str(length)] if not rest else rest[:slot] + [str(length)] + rest[slot + 1:]
    # gen's "Prompt:" line shows the enhanced prompt, so nothing is printed here. A non-prompt
    # reply stops here: it would otherwise be sent to Stable Audio as music ("Please provide the
    # music..." generated as a track).
    prompt, reply, conflicts = enhance_prompt(idea, duration=length)
    if reply:
        print(f"Enhancer: {reply}\nNothing generated.")
        return
    if conflicts:
        # Stop rather than spend credits on a prompt that argues with itself. The rewrite is kept
        # in the history, so `radio prompts <n>` can still generate it if the call looks wrong.
        history_add(prompt, length, "", idea=idea, kind="enhance")
        print(f"Prompt: {prompt}")
        print(f"Conflict: {'; '.join(conflicts)} - the rewrite contradicts itself (both attempts).")
        print(f"Nothing generated. Run egen again, or generate this one anyway: "
              f"radio prompts {len(history_all())}")
        return
    cmd_gen([prompt] + rest, decided=decided)


def _pop_flag(args, flag):
    """(the value after `flag` or "", args without the flag and its value). A value never starts
    with "--", so a flag with its value missing does not swallow the next flag (`play --say
    --about x` used to)."""
    if flag not in args:
        return "", list(args)
    i = args.index(flag)
    has = i + 1 < len(args) and not args[i + 1].startswith("--")
    return (args[i + 1] if has else ""), args[:i] + args[i + 1 + has:]


def cmd_play(args):
    # "radio play 1,3,5-8" is a track selection, not a resume -> build a playlist and start it.
    # The --say value is left out first, or `play 3,5 --say "hi"` would not look like a selection.
    say, rest = _pop_flag(args, "--say")
    selection = [a for a in rest if not a.startswith("--")]
    if looks_like_selection(selection):
        cmd_playlist(selection, say)
        return
    _play(say)


def _play(say=""):
    """Start the daemon, or resume a pause point, with `say` as the DJ sign-on."""
    st = read_state()
    if _is_playing(st):
        if say:                              # spoken before the next track of the live daemon
            queue_add(say, front=True)
        print(f"Already playing (daemon {st['daemon_pid']}). Now: {st.get('now_playing')}")
        return
    # Refuse before queueing the sign-on: a line queued by a refused play used to be spoken on
    # some later play, out of context.
    if not get_library():
        print('Library is empty. Generate first:  radio gen "lo-fi beats"')
        return
    player, _ = detect_player()
    if not player:
        print(f"No audio player found: {_install_hint()}.")
        return
    if say:                                  # Claude-written sign-on -> front of the DJ queue
        queue_add(say, front=True)
    resuming = RESUME_FILE.exists()          # a pause point the daemon will pick up on start
    argv = [sys.executable, os.path.abspath(__file__), "__daemon"]
    if IS_WIN:
        DETACHED_PROCESS = 0x00000008
        CREATE_NEW_PROCESS_GROUP = 0x00000200
        subprocess.Popen(argv, creationflags=DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP,
                         stdin=DEVNULL, stdout=DEVNULL, stderr=DEVNULL, close_fds=True)
    else:
        subprocess.Popen(argv, start_new_session=True,
                         stdin=DEVNULL, stdout=DEVNULL, stderr=DEVNULL, close_fds=True)
    time.sleep(1.0)
    st = read_state()
    verb = "Resumed" if resuming else "Radio started"
    print(f"{verb} (daemon {st.get('daemon_pid')}). Now: {st.get('now_playing')}")


def cmd_stop(_args):
    st = read_state()
    _kill_daemon(st)             # stop the loop first so it can't spawn a new player
    _kill_players_after_daemon(st)   # then re-read: a track may have ended during that kill
    for f in (BREAKING_FILE, RESUME_FILE):   # drop pending interrupt + pause point (fresh shuffle)
        _unlink_quiet(f)
    write_state(status="stopped", daemon_pid=None, player_pid=None, now_playing=None)
    write_now("Terminal FM | stopped")
    print("Radio stopped.")


def cmd_pause(_args):
    """Pause playback and remember the track + position so `radio play` resumes right there.

    There's no OS-level pause of a detached player, so we snapshot the live position (persisted by
    play_track as player_offset + elapsed-since player_started), tear the daemon down like `stop`,
    and leave a resume.json the next daemon replays via a seek offset.
    """
    st = read_state()
    if not _is_playing(st):
        print("Not playing.")
        return
    _kill_daemon(st)             # daemon first so it can't advance/respawn
    # Re-read after the kill: if the track ended meanwhile, the daemon started the next one and
    # recorded it, and the position must come from that player, not the one first read.
    now = read_state()
    track = now.get("now_playing")
    pos = 0.0
    if _player_alive(now):
        try:
            started = now.get("player_started")
            if started:
                pos = float(now.get("player_offset") or 0) + max(0.0, time.time() - float(started))
        except Exception:
            pos = 0.0
    else:
        # Between tracks (the DJ is talking or the next track is loading): state.json still names
        # the track that just ended, so a saved position would replay it past its end.
        track = None
    saved = False
    if track and pos > 1:
        try:
            _write_json(RESUME_FILE, {"track": track, "offset": pos})
            saved = True
        except Exception:
            pass
    _kill_players_after_daemon(st, now)
    if not saved:
        # Nothing worth resuming (between tracks, or within the first second of a track that may
        # have started during the kill): stop clean so the next play is a fresh shuffle.
        cmd_stop([])
        print("Paused between tracks, nothing to resume; `radio play` starts a fresh shuffle.")
        return
    _unlink_quiet(BREAKING_FILE)
    write_state(status="paused", daemon_pid=None, player_pid=None, now_playing=track)
    stem = Path(track).stem if track else ""
    write_now(f"Terminal FM | paused: {stem}" if stem else "Terminal FM | paused")
    where = f"{int(pos) // 60}:{int(pos) % 60:02d}"
    print(f"Paused at {where}"
          + (f" - {stem}" if stem else "")
          + ("" if _can_seek(detect_player()[0]) else "  (players without seek resume from the top)")
          + ".  Resume with:  radio play")


def cmd_skip(_args):
    st = read_state()
    if not _is_playing(st):
        print("Not playing.")
        return
    if _player_alive(st):
        _kill_player(st)         # daemon's wait() returns -> advances to next track
        print("Skipped.")
    else:
        print("Nothing to skip.")


def cmd_status(_args):
    st = read_state()
    print("Terminal FM status")
    print(f"  state   : {st.get('status')}")
    print(f"  now     : {st.get('now_playing')}")
    print(f"  folder  : {OUTDIR}{'' if OUTDIR == DEFAULT_OUTDIR else '  (custom)'}")
    lib = get_library()
    print(f"  library : {len(lib)} track(s)")
    n_arch = len(archived_tracks())
    if n_arch:
        print(f"  archive : {n_arch} track(s) out of rotation  (radio unarchive)")
    pl = load_playlist()
    print(f"  mode    : {'playlist - ' + str(len(pl)) + ' track(s), in order' if pl else 'shuffle (full library)'}")
    print(f"  queue   : {len(queue_files())} DJ line(s) pending")
    print(f"  announce: {'on' if CONFIG.get('dj', {}).get('announce_when_idle') else 'off'} (idle updates)")
    print(f"  source  : {CONFIG['source']}")
    player, _ = detect_player()
    print(f"  player  : {Path(player).name if player else '(none found)'}")
    print(f"  daemon  : {st.get('daemon_pid')} (alive: {'yes' if _daemon_alive(st) else 'no'})")
    gaps = [what for what, have in (("Python %d.%d+" % PY_MIN, sys.version_info >= PY_MIN),
                                    ("audio player", player), ("API key", _read_key()),
                                    ("tracks", lib)) if not have]
    if gaps:
        print(f"  setup   : missing {', '.join(gaps)} - `radio setup` shows how to fix it")


def _git_bash():
    """Git Bash's path on Windows, found the way Claude Code is documented to find it
    (CLAUDE_CODE_GIT_BASH_PATH, else beside git), or None. Without it plugin hooks run in
    PowerShell, where the radio's `sh` hook command can't start."""
    env = os.environ.get("CLAUDE_CODE_GIT_BASH_PATH", "").strip()
    cands = [Path(env)] if env else []
    git = shutil.which("git")
    if git:
        root = Path(git).resolve().parent.parent          # <Git>/cmd/git.exe -> <Git>
        cands += [root / "bin" / "bash.exe", root.parent / "bin" / "bash.exe"]
    cands.append(Path("C:/Program Files/Git/bin/bash.exe"))
    return next((str(p) for p in cands if p.is_file()), None)


def _settings_file():
    """Claude Code's user settings.json: in CLAUDE_CONFIG_DIR when that is set, else ~/.claude."""
    base = os.environ.get("CLAUDE_CONFIG_DIR", "").strip() or "~/.claude"
    return Path(os.path.expanduser(base)) / "settings.json"


def _statusline_state():
    """"radio" when the user's Claude Code settings run a statusLine that shows the radio (its
    command, or a script file the command names, mentions statusline.py or nowplaying), "other"
    for a statusLine of their own that doesn't, None for no statusLine."""
    try:
        cmd = json.loads(_settings_file().read_text(encoding="utf-8"))["statusLine"]["command"]
    except Exception:
        return None
    texts = [str(cmd)]
    for tok in re.findall(r'"([^"]+)"|(\S+)', str(cmd)):
        p = Path(os.path.expanduser(tok[0] or tok[1]))
        try:
            if p.is_file() and p.stat().st_size < 1_000_000:
                texts.append(p.read_text(encoding="utf-8", errors="replace"))
        except OSError:
            pass
    return "radio" if any("statusline.py" in t or "nowplaying" in t for t in texts) else "other"


SETUP_RULE = "-" * 64


def _setup_required():
    """The required steps in order, as (title, done, text): a done title says what was found, and
    text spells out the steps that finish one that isn't."""
    again = "/tfm setup"
    restart = ["Restart Claude Code."] if IS_WIN else []

    def install(program):
        name, cmd = _install_cmd(program)
        return _steps([(f"Install {name} in a terminal:", cmd)] + restart, again)

    py, ok = sys.version.split()[0], sys.version_info >= PY_MIN   # an older one runs, unpatched
    rows = [(f"Python {py}" if ok else "Python %d.%d or newer (this is %s)" % (*PY_MIN, py), ok,
             install("python"))]
    player, _ = detect_player()
    if player:
        seek = "" if _can_seek(player) else " (restarts a paused track from the top; mpv resumes mid-track)"
        rows.append((f"Audio player: {Path(player).stem}{seek}", True, ""))
    else:
        rows.append(("Audio player", False, install("player")))
    key = _read_key()
    rows.append(("Stability API key: found" if key else "Stability API key", bool(key), _key_help(again)))
    try:
        seen = HOOK_SEEN.read_text(encoding="utf-8").strip()
    except Exception:
        seen = ""
    if IS_WIN and not seen and not _git_bash():
        hooks = [("Install Git for Windows in a terminal (Claude Code runs the hooks with its Git Bash):",
                  "winget install Git.Git")] + restart
    else:
        hooks = ["Start a new Claude Code session: the hooks run when a session starts."]
    rows.append((f"Session hooks: last ran {seen}" if seen else "Session hooks", bool(seen),
                 _steps(hooks, again)))
    if CONFIG["stability_api"].get("output_format") == BOTH_FORMATS:
        ff = _ffmpeg()
        rows.append(("FFmpeg, for wav+mp3: found" if ff else "FFmpeg, for wav+mp3", bool(ff), install("ffmpeg")))
    n = len(get_library())
    rows.append((f"Library: {n} track(s) in {OUTDIR.name}" if n else "First track", bool(n),
                 _steps([("Make one (this spends Stability credits):",
                          '/tfm gen "warm lo-fi hip hop, rhodes, 80 BPM"'), ("Play it:", "/tfm play")])))
    return rows


# --------------------------------------------------------------------------- setup: the optional extras
# What `setup <extra> install` downloads. Each is pinned to the file tested here, with the size and
# SHA-256 its publisher lists (GitHub's asset digest, Hugging Face's LFS hash), checked 2026-10-21; a
# download that doesn't match is deleted, never used. A new pin needs the same tests again: the voice
# rendering through kokoro_tts.py, llama-cli's answers passing _strip_cli_chrome, and the tokenizer
# loading in prompt_tokens.
KOKORO_URL = "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.1/"
KOKORO_PINS = {"kokoro-v1.0.fp16.onnx": (163_527_961, "f3a290d384fbb27966d462905c71a46cef9e5fd00516b40df32a0b4afe77ac96"),
               "voices-v1.0.bin": (28_214_398, "bca610b8308e8d99f32e6fe4197e7ec01679264efed0cac9140fe9c29f1fbf7d")}
# The same two files from model-files-v1.0, which kokoro-onnx 0.6.1 runs too: GitHub lists their sizes
# but no digest (checked 2026-11-01). A file of either size is kept; any other size, such as a hand
# download that stopped, is downloaded again.
KOKORO_V10_SIZES = {"kokoro-v1.0.fp16.onnx": 177_464_787, "voices-v1.0.bin": 28_214_398}
# llama.cpp's CPU builds, by system and processor. b11669 is the build its v0.7.0 release points at.
LLAMA_RELEASES = "https://github.com/ggml-org/llama.cpp/releases"
LLAMA_BUILD = "b11669"
LLAMA_ASSETS = {
    ("win32", "x64"): ("win-cpu-x64.zip", 19_537_886, "37b3efcf962847ca869745fd4ccf7f5e7e8dacfeff9fa3523b4ca8cdc66d632b"),
    ("win32", "arm64"): ("win-cpu-arm64.zip", 12_442_177, "9cff39ffed17edcd03a7d876073f74d7b48cd43a1e5eafdd59ee094185ad871b"),
    ("darwin", "arm64"): ("macos-arm64.tar.gz", 12_191_582, "dbed55493d72bc1ba2babc8770d669c2289b5bc4ee9fb2a4dfc158d45b7d13fd"),
    ("darwin", "x64"): ("macos-x64.tar.gz", 11_677_404, "cab28238d78158109b48deb27b05d50e0dcef56275d2e76da9ca8281526c7532"),
    ("linux", "x64"): ("ubuntu-x64.tar.gz", 17_851_611, "cf07c1c112d709bd67e522017471de57ed0ec8bea031d732c5422351c07f65ac"),
    ("linux", "arm64"): ("ubuntu-arm64.tar.gz", 13_900_160, "9ac6fda2058d35677608a06f751a50122ddfa4ce0ddb7f084466b8e79b6d4a99"),
}
_MACHINES = {"amd64": "x64", "x86_64": "x64", "arm64": "arm64", "aarch64": "arm64"}   # platform.machine()
QWEN_PAGE = "https://huggingface.co/unsloth/Qwen3-4B-Instruct-2507-GGUF"
QWEN_URL = QWEN_PAGE + "/resolve/a06e946bb6b655725eafa393f4a9745d460374c9/Qwen3-4B-Instruct-2507-Q4_K_M.gguf"
QWEN_PIN = (2_497_281_120, "3605803b982cb64aead44f6c1b2ae36e3acdb41d8e46c8a94c6533bc4c67e597")
QWEN_FILE = LLM_DIR / QWEN_URL.rsplit("/", 1)[1]
TOKENIZER_PAGE = "https://huggingface.co/google/t5gemma-b-b-ul2"
TOKENIZER_URL = TOKENIZER_PAGE + "/resolve/97ea9b7e92738bb57437867277ae38e65345b8d7/tokenizer.json"
TOKENIZER_PIN = (34_362_429, "7794135caa3ea73918949c902a781cc61dab674a4b59c17d85931c77c1114cbd")
# The voice's own environment on disk, with kokoro-onnx 0.6.1 and its packages: 158 MB measured on
# Windows (2026-10-21), plus what pip downloads for it, 39 MB of wheels there.
VOICE_ENV_BYTES = 200_000_000
BREW_BINS = "/opt/homebrew/bin:/usr/local/bin"    # Homebrew's programs on Apple silicon, then on Intel
# Claude's part of an install once the user says yes: (API calls, new tokens, how it was found). Measured
# on SETUP_COST_DATE with `claude -p` and Claude Opus 5.5, `/tfm setup <extra>` and then "Install it" in
# a new session, from the usage Claude Code reported: voice 1,419 new tokens, enhancer 2,513 (run in the
# background, so it reads its output when done), tokenizer 1,308. The voice's ran in the foreground, but
# the skill now runs every voice install in the background like the enhancer's, because the Bash tool
# stops a command at 10 minutes: the two model files (191,742,359 bytes) alone pass that below 2.56 Mbit/s
# (x 8 / 600 s), and pip may take its 900 s. So the voice's figure is the enhancer's background run, an
# estimate until measured. The tokenizer stays in the foreground: its 34 MB pass 10 minutes only below
# 0.46 Mbit/s, and running it again continues the download.
# New tokens are the install's output and Claude's replies; every call also re-reads the conversation so
# far, 45k tokens in that new session. The statusline couldn't be measured without editing the real
# settings.json: its 3 calls are a Read, an Edit and the reply, and its tokens are estimated at the
# measured ~0.65k a call plus a settings.json's text.
SETUP_COST = {"statusline": (3, 3000, "estimated"), "voice": (4, 2500, "estimated"),
              "enhancer": (4, 2500, "measured"), "tokenizer": (2, 1300, "measured")}
SETUP_COST_DATE = "2026-10-21"


def _size(n):
    """Bytes as the pages say them: 164 MB, 2.5 GB."""
    return f"{n / 1e9:.1f} GB" if n >= 1e9 else f"{max(1, round(n / 1e6))} MB"


def _sha256(path):
    with open(path, "rb") as f:
        return hashlib.file_digest(f, "sha256").hexdigest()


def _origin(url):
    """A URL's (scheme, host, port): where a login may go, and whether an answer came from there."""
    u = urllib.parse.urlsplit(url)
    return u.scheme, u.hostname, u.port


class _LoginStaysOnHost(urllib.request.HTTPRedirectHandler):
    """Follows a redirect with the login (an unredirected Authorization header) only when it stays
    on the same scheme, host and port: a hop within huggingface.co still needs it, its CDN never
    gets it. urllib on its own drops it on every redirect."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        new = super().redirect_request(req, fp, code, msg, headers, newurl)
        auth = req.unredirected_hdrs.get("Authorization")
        if new is not None and auth and _origin(req.full_url) == _origin(newurl):
            new.add_unredirected_header("Authorization", auth)
        return new


def _download_context():
    """TLS for the installs' downloads: the system's certificates, plus stability_api.ca_bundle's
    when it names a file. The API's context (_ssl_context) checks that file alone, because it is set
    where the system's path to the API's chain fails; a download from GitHub, Hugging Face or their
    CDNs still has to verify when the file holds only the API's chain."""
    ctx, bundle = ssl.create_default_context(), _ca_bundle()
    if bundle:
        ctx.load_verify_locations(bundle)
    return ctx


def _part(dest):
    """Where a download of `dest` collects until it passes its check."""
    return dest.with_name(dest.name + ".part")


def _whole(path, *sizes):
    """`path` is a file of one of `sizes` bytes: a download there didn't stop partway."""
    return path.is_file() and path.stat().st_size in sizes


def _still_to_fetch(dest, size):
    """The bytes a download of `dest` still needs: none when the file is already there whole, else
    its size less what a stopped download left in its .part. The plans count this, so a download a
    full disk stopped fits again once the rest of it is free."""
    if _whole(dest, size):
        return 0
    part = _part(dest)
    return max(0, size - (part.stat().st_size if part.is_file() else 0))


def _fetch_step(what, url, dest, size, sha256, replacing="is the wrong size", **kw):
    """A plan's download step: what it says (naming a file at `dest` it replaces, and why), the
    bytes still to come and the _fetch that gets them."""
    if dest.is_file() and not _whole(dest, size):
        what += f", replacing the file there, which {replacing}"
    return what, _still_to_fetch(dest, size), functools.partial(_fetch, url, dest, size, sha256, **kw)


def _fetch(url, dest, size, sha256, token=None, refused=""):
    """Download `url` to `dest` and check it against its published size and SHA-256. Returns None,
    or what went wrong. The bytes go to <dest>.part first, so a download that stops (a dropped
    connection, a killed command) continues from there the next time, with an HTTP Range request; a
    file that fails the check is deleted. It is hashed as it arrives, the .part's earlier bytes
    once, so a 2.5 GB file isn't read again to check it. `token` goes to `url`'s own host only, never
    to a host it redirects to: GitHub and Hugging Face both hand the file over from a CDN, which
    needs no login. `refused` follows the message for a 401 or 403 from `url`'s own host."""
    if _whole(dest, size) and _sha256(dest) == sha256:
        return None
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = _part(dest)
    have = part.stat().st_size if part.is_file() else 0
    digest = None
    if have < size:
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        if have:
            req.add_header("Range", f"bytes={have}-")
        if token:
            req.add_unredirected_header("Authorization", f"Bearer {token}")
        opener = urllib.request.build_opener(urllib.request.HTTPSHandler(context=_download_context()),
                                             _LoginStaysOnHost)
        try:
            with opener.open(req, timeout=60) as r:
                resume = have and r.status == 206     # 200: the whole file again, from the top
                if resume:
                    with open(part, "rb") as f:
                        digest = hashlib.file_digest(f, "sha256")
                else:
                    digest = hashlib.sha256()
                with open(part, "ab" if resume else "wb") as f:
                    while chunk := r.read(1 << 20):
                        digest.update(chunk)
                        f.write(chunk)
        except urllib.error.HTTPError as e:
            answered = _origin(e.url or url)          # after a redirect, the CDN that refused
            msg = f"{answered[1]} answered HTTP {e.code}"
            if e.code == 416:                         # the .part doesn't fit the file: start over
                _unlink_quiet(part)
                return f"{msg}. Run the same command again to start the download over"
            if refused and e.code in (401, 403) and answered == _origin(url):
                return f"{msg}. {refused}"
            return msg
        except Exception as e:
            # With a login sent, only an OS error (the network, a locked .part, a full disk) keeps its
            # text: any other could quote the request, Authorization header and all.
            why = f"{type(e).__name__}: {e}" if not token or isinstance(e, OSError) else type(e).__name__
            if isinstance(getattr(e, "reason", e), ssl.SSLCertVerificationError):   # rerunning won't help
                bundle = _ca_bundle()
                return f"{_origin(url)[1]}'s certificate didn't verify ({why})" + (
                    f", checked against your system's certificates and stability_api.ca_bundle ({bundle})"
                    if bundle else "")
            if isinstance(e, (urllib.error.URLError, http.client.HTTPException, ConnectionError,
                              TimeoutError, ssl.SSLError)):         # DNS, a dropped connection
                return f"the download stopped ({why}). Run the same command again to continue it"
            return f"the download failed ({why})"     # a locked .part, a full disk: said as it is
    got = part.stat().st_size
    if got < size:
        return f"the download stopped at {_size(got)} of {_size(size)}. Run the same command again to continue it"
    if got > size or (digest.hexdigest() if digest else _sha256(part)) != sha256:
        _unlink_quiet(part)
        return f"{dest.name} didn't match its published SHA-256, so it was deleted"
    os.replace(part, dest)
    return None


def _member_parts(name):
    """An archive member's path as parts (() for the archive's own "./"), or None when it is
    absolute, names a drive or climbs out with ..; a drive in any part counts, since on Windows
    joining "top/C:x" lands outside the folder."""
    p = PurePosixPath(name.replace("\\", "/"))
    if p.is_absolute() or any(part == ".." or ":" in part for part in p.parts):
        return None
    return p.parts


def _unpack(archive, dest):
    """Unpack a llama.cpp release into `dest`: a .zip as it is, a .tar.gz without its one top folder.
    Plain files only, and links to a file beside them (a folder entry is skipped: its files make it);
    any other member, or a path that is absolute, names a drive or climbs out with .., refuses the
    whole archive. Returns None, or why it refused."""
    import tarfile
    import zipfile
    refused = f"{archive.name} holds something other than plain files, so it wasn't unpacked"
    if archive.name.endswith(".zip"):
        with zipfile.ZipFile(archive) as z:
            files = [(m, _member_parts(m.filename)) for m in z.infolist() if not m.is_dir()]
            if any(not parts for _, parts in files):
                return refused
            for m, parts in files:
                out = dest.joinpath(*parts)
                out.parent.mkdir(parents=True, exist_ok=True)
                with z.open(m) as src, open(out, "wb") as f:
                    shutil.copyfileobj(src, f)
        return None
    with tarfile.open(archive, "r:gz") as t:
        members, tops, plan = t.getmembers(), set(), []
        for m in members:
            parts = _member_parts(m.name)
            if parts == () and m.isdir():             # "./", the archive itself
                continue
            if not parts:
                return refused
            tops.add(parts[0])
            if m.isdir():                             # the top folder, or one inside it
                continue
            link_ok = (m.issym() and m.linkname not in ("", ".", "..")
                       and m.linkname == PurePosixPath(m.linkname).name)
            if len(parts) == 1 or not (m.isfile() or link_ok):
                return refused
            plan.append((m, parts[1:]))
        if len(tops) != 1:
            return refused
        for m, rel in plan:
            out = dest.joinpath(*rel)
            out.parent.mkdir(parents=True, exist_ok=True)
            if m.issym():
                os.symlink(m.linkname, out)
                continue
            with t.extractfile(m) as src, open(out, "wb") as f:
                shutil.copyfileobj(src, f)
            os.chmod(out, 0o755 if m.mode & 0o111 else 0o644)
    return None


def _run(cmd, timeout):
    """(exit code, stdout + stderr) of a helper program, or (None, why it didn't start)."""
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace",
                           timeout=timeout, creationflags=CREATE_NO_WINDOW)
        return r.returncode, r.stdout + r.stderr
    except Exception as e:
        return None, f"{type(e).__name__}: {e}"


def _no_room(need):
    """Why `need` more bytes won't fit on the data folder's disk, or None."""
    free = shutil.disk_usage(ROOT).free
    return None if free >= need else (f"it needs about {_size(need)} free on the disk with {ROOT},"
                                      f" which has {_size(free)}")


def _claude_part(name):
    calls, new, how = SETUP_COST[name]
    return (f"  Claude's part: {calls} more calls and about {new / 1000:g}k new tokens, each call also"
            f" re-reading the conversation so far ({how} {SETUP_COST_DATE}).")


def _auto_block(name, todo):
    """A page's automatic install: what `setup <name> install` would do here, the disk it needs and
    Claude's measured share, which the skill asks the user about before running it."""
    steps, why = todo
    if steps is None:
        print(f"\nAutomatic install: {why}")
        return
    print(f"\nAutomatic install (/tfm setup {name} install), about"
          f" {_size(sum(b for _, b, _ in steps))} on disk:")
    for what, _, _ in steps:
        print(f"  - {what}")
    print(_claude_part(name))


def _install(extra):
    """`setup <name> install`: the steps the page listed, in order, each line finished as it goes,
    stopping at the first that fails. Run again, it skips what is done and resumes a download.
    Returns the exit code: 1 when it printed `Not installed:`."""
    if extra.installed():
        print(f"Already installed. /tfm setup {extra.name} says more.")
        return 0
    steps, why = extra.plan()
    if steps is None:
        print(f"Not installed: {why}")
        return 1
    room = _no_room(sum(b for _, b, _ in steps))
    if room:
        print(f"Not installed: {room}.")
        return 1
    for what, _, action in steps:
        print(f"  {what} ...", end="", flush=True)
        start = time.time()
        try:
            err = action()
        except Exception as e:                        # a locked file, a full disk: said, not a traceback
            err = f"{type(e).__name__}: {e}"
        print(f" {'failed' if err else 'done'} ({time.time() - start:.0f} s)")
        if err:
            print(f"Not installed: {err}.")
            return 1
    print(f"Installed: {extra.done}")
    return 0


def _statusline_page(done):
    print("Statusline: the playing track under Claude Code's prompt")
    if done:
        print("Status: done. Your statusline shows the radio.")
    elif not STATUSLINE_DST.is_file():
        print("Status: finish /tfm setup first. The session hooks put statusline.py in place.")
    elif _statusline_state() == "other":
        print("Status: you have your own statusline, and it doesn't show the radio yet.\n")
        print(_steps([("Have your statusline script print the text of this file:", str(NOW_FILE))]))
        print('  It reads "Terminal FM > <track>" while a track plays and "Terminal FM | <status>"'
              ' otherwise, so ">" means playing.')
    else:
        cmd = _cmdline([_console_python() if IS_WIN else "python3", str(STATUSLINE_DST)])
        entry = json.dumps({"statusLine": {"type": "command", "command": cmd}})
        settings = _settings_file()
        if settings.is_file():
            steps = [("Open this file in a text editor:", str(settings)),
                     ("Add this line inside its outer { }, with a comma after the line before it:",
                      entry[1:-1])]
        else:
            steps = [("Create this file:", str(settings)), ("Put this in it:", entry)]
        print("Status: not set up.")
        print(f"\nAutomatic install (Claude edits {settings.name}): Claude adds the line below for you, and"
              f" Claude Code asks you before that file changes.\n{_claude_part('statusline')}")
        print("\nOr by hand:")
        print(_steps(steps + ["Save it. If the line doesn't show at your next prompt, restart Claude Code."]))


# pip's arguments for the voice's packages. 0.6 is the kokoro-onnx the voice needs, so on a Python
# no such release supports, pip refuses instead of quietly taking an older one; the double quotes
# keep the > from being a redirect in bash, PowerShell and cmd. readme_check.py holds README to it,
# and the automatic install splits it with shlex.
KOKORO_PIP_ARGS = 'install -U "kokoro-onnx>=0.6" soundfile'
# kokoro-onnx 0.5.0 can't run the pinned model: onnxruntime refuses its int32 input where the model
# wants float (measured 2026-10-21). 0.6.1 runs both the pinned model and model-files-v1.0's.
KOKORO_ONNX_NEED = "kokoro-onnx %s or newer" % re.search(r"kokoro-onnx>=([\d.]+)", KOKORO_PIP_ARGS)[1]
KOKORO_ONNX_MIN = tuple(int(n) for n in KOKORO_ONNX_NEED.split()[1].split("."))


@functools.cache
def _voice_ready():
    """The Python the DJ would render the voice with (dj.py's own search, caching nothing), when it
    has kokoro-onnx KOKORO_ONNX_MIN or newer; else None. Asked once per command: the voice page and the
    install's plan both need it, and it starts a Python or more each time."""
    import dj
    py = dj._kokoro_python(dj.dj_config(), check=True)
    if not py:
        return None
    code, out = _run([py, "-c", "import importlib.metadata as m; print(m.version('kokoro-onnx'))"], 30)
    version = tuple(int(n) for n in re.findall(r"\d+", out)[:len(KOKORO_ONNX_MIN)]) if code == 0 else ()
    return py if version >= KOKORO_ONNX_MIN else None


def _voice_python():
    """A Python the voice's packages install on, to make its environment from: this one when its
    version fits, else one beside it (dj._side_by_side, and on Windows where winget puts one, which
    no py launcher may know about yet in this session), or None."""
    import dj
    if dj.PY_VOICE_MIN <= sys.version_info[:2] <= dj.PY_VOICE_MAX:
        return _console_python()
    found = next(dj._side_by_side(), None)
    if found:
        return found
    if IS_WIN:      # Python313, or with a suffix: 32-bit and ARM64 installs add one (not tried on those)
        home = Path(os.path.expandvars(r"%LOCALAPPDATA%\Programs\Python"))
        found = sorted(home.glob("Python%d%d*/python.exe" % dj.PY_VOICE_MAX))
        return str(found[0]) if found else None
    if sys.platform == "darwin":
        return shutil.which("python%d.%d" % dj.PY_VOICE_MAX, path=BREW_BINS)
    return None


def _python_getter():
    """The program that installs the voice's Python for this user: winget on Windows (its App
    Installer link too, which Claude Code's shells may not have on PATH), Homebrew on macOS. None
    elsewhere, or when it isn't installed."""
    if IS_WIN:
        alias = os.path.expandvars(r"%LOCALAPPDATA%\Microsoft\WindowsApps\winget.exe")
        return shutil.which("winget") or (alias if os.path.isfile(alias) else None)
    if sys.platform == "darwin":
        return shutil.which("brew") or shutil.which("brew", path=BREW_BINS)
    return None


def _get_python():
    """Install the newest Python the voice supports for this user, with the command _install_cmd
    names: winget's made silent and per-user, Homebrew's as it is. None when that Python is there
    afterwards, else why not."""
    import dj
    ver = "%d.%d" % dj.PY_VOICE_MAX
    tool = _python_getter()
    if not tool:                                      # the plan doesn't offer this step without one
        return f"{'winget' if IS_WIN else 'Homebrew'} isn't installed: install Python {ver} yourself, then run this again"
    cmd = [tool] + _install_cmd("python", ver)[1].split()[1:]
    if IS_WIN:
        cmd += ["-e", "--scope", "user", "--silent", "--accept-package-agreements",
                "--accept-source-agreements", "--disable-interactivity"]
    _, out = _run(cmd, 900)
    if _voice_python():
        return None
    return f"{Path(tool).name} didn't install Python {ver} ({dj.last_line(out)})"


def _make_venv():
    import dj
    base = _voice_python()
    if not base:
        return "no Python from %d.%d to %d.%d was found" % (*dj.PY_VOICE_MIN, *dj.PY_VOICE_MAX)
    code, out = _run([base, "-m", "venv", "--clear", str(dj.KOKORO_VENV)], 300)
    if code == 0 and dj.venv_python().is_file():
        return None
    if "ensurepip" in out:                            # Debian and Ubuntu leave venv out of python3
        return "this Python can't make environments. On Debian or Ubuntu: sudo apt install python3-venv"
    return f"python -m venv failed ({dj.last_line(out)})"


def _pip_voice():
    import dj
    import shlex
    py = str(dj.venv_python())
    code, out = _run([py, "-m", "pip", "--disable-pip-version-check", "-q"] + shlex.split(KOKORO_PIP_ARGS), 900)
    if code != 0:
        return f"pip failed ({dj.last_line(out)})"
    _atomic_write(dj.KOKORO_PY_CACHE, py)             # the DJ's interpreter from now on
    return None


def _voice_check():
    """Render a line on the DJ's own path (dj._kokoro_render: its Python, its configured voice),
    without playing it. None when it made speech. A stale cached Python doesn't fail it: after a
    failed render, dj searches again and retries the line with the interpreter it finds."""
    import dj
    import wave
    wav = dj._kokoro_render("Terminal FM voice check.")
    if not wav:
        return f"the test line failed: {dj._kokoro_error}"
    try:
        with wave.open(str(wav), "rb") as w:
            return None if w.getnframes() else "the test line came out empty"
    finally:
        _unlink_quiet(wav)


def _voice_todo():
    """The steps of `setup voice install` here, as (what, bytes on disk, action returning None or
    why it failed), and None; or None and why it can't run."""
    import dj
    steps = []
    if not _voice_ready():
        pinned = dj.pinned_python(dj.dj_config())
        if pinned:
            return None, (f"dj.python in config.json names {pinned}, which the DJ always uses, and it has no"
                          f" {KOKORO_ONNX_NEED}. Install {KOKORO_ONNX_NEED} and soundfile in that Python, or"
                          " remove dj.python, then run /tfm setup voice again.")
        base, ver = _voice_python(), "%d.%d" % dj.PY_VOICE_MAX
        if not base:
            need = "the voice needs Python %d.%d to %s, and none was found" % (*dj.PY_VOICE_MIN, ver)
            get = _install_cmd("python", ver)[1] if IS_WIN or sys.platform == "darwin" else ""
            if not get:
                return None, (f"not possible here: {need}. Install one with your package manager, then run"
                              " /tfm setup voice again.")
            if not _python_getter():
                tool, other = (("winget", "App Installer from the Microsoft Store, which brings winget") if IS_WIN
                               else ("Homebrew", "Homebrew from https://brew.sh"))
                return None, (f"not possible here: {need}, and {tool}, which would install it, isn't on this"
                              f" computer. Install Python {ver} from https://www.python.org/downloads/, or"
                              f" {other}, then run /tfm setup voice again.")
            steps.append((f"Python {ver} for your user ({get})", 0, _get_python))
            base = f"Python {ver}"
        steps += [(f"a private Python environment in {dj.KOKORO_VENV}, made with {base}", 0, _make_venv),
                  ("kokoro-onnx and soundfile from PyPI, into that environment", VOICE_ENV_BYTES, _pip_voice)]
    for name in _kokoro_missing():
        size, sha = KOKORO_PINS[name]
        steps.append(_fetch_step(f"{name} ({_size(size)}) from github.com", KOKORO_URL + name,
                                 dj.KOKORO_DIR / name, size, sha))
    steps.append(("a test line, rendered but not played", 0, _voice_check))
    return steps, None


def _kokoro_missing():
    """The pinned voice files `setup voice install` downloads: each one that isn't here at the size
    of its download or of model-files-v1.0's, so a hand download that stopped is replaced. Another of
    the three models will do while no fp16 model is there, since kokoro_tts.py loads that one first."""
    import dj
    fp16 = dj.KOKORO_MODELS[0]
    another = not (dj.KOKORO_DIR / fp16).exists() and any((dj.KOKORO_DIR / m).exists() for m in dj.KOKORO_MODELS[1:])
    return [n for n in KOKORO_PINS if not _whole(dj.KOKORO_DIR / n, KOKORO_PINS[n][0], KOKORO_V10_SIZES[n])
            and not (n == fp16 and another)]


def _voice_installed():
    """The voice files are whole and the interpreter the DJ tries first has spoken a Kokoro line
    (dj.rendered_with): file reads only. Probing for a Python with kokoro-onnx took about 1 s on
    every plain `setup`; the page and the plan still probe when it isn't installed."""
    import dj
    return not _kokoro_missing() and bool(dj.rendered_with())


def _voice_pip_steps():
    """The steps by hand that give a Python the voice's packages."""
    import dj
    top = "%d.%d" % dj.PY_VOICE_MAX
    if sys.version_info[:2] <= dj.PY_VOICE_MAX:          # pip runs in the very Python just checked
        steps, pip = [], _cmdline([_console_python(), "-m", "pip"], call=True)
        title = f"Install its Python packages in a terminal. They need Python {top} or older:"
    else:                                                # a second Python, which dj.py finds by itself
        get = _install_cmd("python", top)[1]
        how = (", if you don't have it:" if get
               else " with your system's package manager, if you don't have it.")
        steps = [(f"Its Python packages need Python {top} or older, and this is Python"
                  f" {sys.version.split()[0]}. Install Python {top}{how}", get)]
        pip = (f"py -{top}" if IS_WIN else f"python{top}") + " -m pip"
        title = "Install the packages with it:"
    return steps + [(title, f"{pip} {KOKORO_PIP_ARGS}")]


def _voice_page(done):
    import dj
    print("DJ voice: Kokoro-82M, a natural voice for the DJ. Without it the DJ uses your system voice.")
    if done:
        print("Status: installed.")
        return
    files = not _kokoro_missing()
    if not files:
        print("Status: not installed.")
    elif _voice_ready():
        print(f"Status: the model files and a Python with {KOKORO_ONNX_NEED} are here, but the voice hasn't"
              " spoken a line with them yet.")
    else:
        print(f"Status: the model files are here, but no Python has {KOKORO_ONNX_NEED} and soundfile.")
    _auto_block("voice", _voice_todo())
    steps = [] if files else [(f"Download {dj.KOKORO_MODELS[0]} and {dj.KOKORO_VOICES} from:",
                               KOKORO_URL.replace("/download/", "/tag/").rstrip("/")),
                              ("Put both files in this folder:", str(dj.KOKORO_DIR))]
    pip = [] if _voice_ready() else _voice_pip_steps()
    print("\nOr by hand:\n" + _steps(steps + pip, again="/tfm setup voice"))
    if sys.platform.startswith("linux") and not any(
            shutil.which(t) for t in ("piper", "espeak-ng", "espeak")):
        print("  No system voice was found either. For a basic one: sudo apt install espeak-ng")


def _llama_asset():
    """(file name, bytes, SHA-256) of the llama.cpp build for this system and processor, or None."""
    import platform
    osname = "linux" if sys.platform.startswith("linux") else sys.platform
    pin = LLAMA_ASSETS.get((osname, _MACHINES.get(platform.machine().lower())))
    return (f"llama-{LLAMA_BUILD}-bin-{pin[0]}",) + pin[1:] if pin else None


def _get_llama(name, size, sha256):
    """Download llama.cpp, unpack it beside llm/bin, check that llama-cli runs, then move it in,
    llama-cli last, so a stop halfway never leaves a llama-cli without its libraries."""
    import dj
    import tempfile
    archive = LLM_DIR / name
    err = _fetch(f"{LLAMA_RELEASES}/download/{LLAMA_BUILD}/{name}", archive, size, sha256)
    if err:
        return err
    new = Path(tempfile.mkdtemp(prefix="bin-", dir=LLM_DIR))
    try:
        err = _unpack(archive, new)
        if err:
            return err
        exe = new / _llm_exe().name
        if not exe.is_file():
            return f"{name} has no {exe.name}"
        code, out = _run([str(exe), "--version"], 60)
        if code != 0:
            return f"{exe.name} didn't run ({dj.last_line(out)})"
        bin_dir = _llm_exe().parent
        bin_dir.mkdir(exist_ok=True)
        for f in sorted(new.iterdir(), key=lambda p: p.name == exe.name):
            os.replace(f, bin_dir / f.name)
        _unlink_quiet(archive)
        return None
    finally:
        shutil.rmtree(new, ignore_errors=True)


def _llm_check():
    """A test answer; _llm_run records the pair that gave it, which is what `installed` reads. A
    .gguf of the user's own isn't size-checked, so a failure names it in case it stopped partway."""
    if _llm_run("Answer in one word.", "Say hello.", 0, 8, timeout=300):
        return None
    why, model = "the model gave no answer", _llm_paths()[1]
    if model and Path(model) != QWEN_FILE:
        why += f". If {Path(model).name} is a download that stopped, delete it and run this again for the tested model"
    return why


@functools.cache
def _takes_single_turn(exe):
    """llama-cli `exe` starts and lists --single-turn, which _llm_run passes. A copy without the
    files beside it doesn't start; an older build lacks the option. Asked once a command: the
    enhancer's page and its plan both need it."""
    code, out = _run([exe, "--help"], 60)
    return code == 0 and "--single-turn" in out


def _llama_wanted(exe):
    """llama.cpp's pinned build belongs in llm/bin: no llama-cli is here, or the one here hasn't
    answered and can't (see _takes_single_turn), in llm/bin or on PATH alike."""
    if not exe:
        return True
    answered = _llm_answered()
    return not (answered and answered[0] == exe) and not _takes_single_turn(exe)


def _qwen_wanted(model):
    """The pinned model belongs in llm/: no .gguf is there, or the pinned one is there at another size
    than its download's (a download of your own that stopped). Another .gguf is yours to judge."""
    return not model or (Path(model) == QWEN_FILE and not _whole(QWEN_FILE, QWEN_PIN[0]))


def _enhancer_todo():
    """The steps of `setup enhancer install` here, shaped like _voice_todo's."""
    import platform
    exe, model = _llm_paths()
    steps = []
    asset = _llama_asset() if _llama_wanted(exe) else None
    if asset:
        archive = LLM_DIR / asset[0]                  # the download, then about 3 times its size unpacked
        steps.append((f"llama.cpp {LLAMA_BUILD} ({_size(asset[1])}) from github.com, into {_llm_exe().parent}",
                      _still_to_fetch(archive, asset[1]) + asset[1] * 3, functools.partial(_get_llama, *asset)))
    elif not exe:
        return None, (f"not possible here: llama.cpp publishes no CPU build for {sys.platform}"
                      f" on {platform.machine()}.")
    if _qwen_wanted(model):
        size, sha = QWEN_PIN
        minutes = [round(size * 8 / (mbit * 1e6) / 60) for mbit in (100, 10)]
        steps.append(_fetch_step(f"{QWEN_FILE.name} ({_size(size)}: about {minutes[0]} minutes at 100 Mbit/s,"
                                 f" {minutes[1]} at 10) from huggingface.co, into {LLM_DIR}", QWEN_URL, QWEN_FILE, size, sha))
    steps.append(("a test answer from the model", 0, _llm_check))
    return steps, None


def _enhancer_page(done):
    print("Prompt enhancer: turns a rough idea into a full prompt (/tfm enhance, /tfm egen) and"
          " picks better track lengths. Runs on your CPU, free.")
    exe, model = _llm_paths()
    if done:
        print(f"Status: installed ({Path(model).name}).")
        return
    missing = " and ".join(n for n, have in (("the model", model), ("llama-cli", exe)) if not have)
    qwen = _qwen_wanted(model)
    if missing:
        print(f"Status: not installed (missing {missing}).")
    elif qwen:
        print(f"Status: not installed ({Path(model).name} is the wrong size: a download that stopped?).")
    else:
        print("Status: llama-cli and the model are here, but haven't given an answer yet.")
    _auto_block("enhancer", _enhancer_todo())
    steps = []
    if qwen:
        steps += [("Download the Q4_K_M file of Qwen3-4B-Instruct-2507 (about 2.5 GB) from:", QWEN_PAGE),
                  ("Put it in this folder (keep only one .gguf there):", str(LLM_DIR))]
    if _llama_wanted(exe):
        asset = _llama_asset()
        steps += [(f"Download {asset[0] if asset else 'the CPU build for your system'} from:",
                   f"{LLAMA_RELEASES}/tag/{LLAMA_BUILD}"),
                  (f"Unpack it, and copy {_llm_exe().name} and the files beside it into:", str(_llm_exe().parent))]
    steps.append(("Check that it answers:", '/tfm enhance "lofi coffee music"'))
    print("\nOr by hand:\n" + _steps(steps, again="/tfm setup enhancer"))


def _hf_token_file():
    """Where huggingface_hub and its hf command keep the user's Hugging Face login."""
    home = os.environ.get("HF_HOME") or os.path.join(os.environ.get("XDG_CACHE_HOME") or "~/.cache", "huggingface")
    return Path(os.path.expanduser(os.environ.get("HF_TOKEN_PATH") or os.path.join(home, "token")))


def _hf_token():
    """The user's own Hugging Face login, from the environment or _hf_token_file(), or None. Read
    only to download the gated tokenizer the user asked for, and never printed. Line breaks inside
    it are dropped, as huggingface_hub does: urllib refuses a header with one, quoting the value."""
    def clean(text):
        return text.replace("\r", "").replace("\n", "").strip() or None
    for var in ("HF_TOKEN", "HUGGING_FACE_HUB_TOKEN"):
        token = clean(os.environ.get(var, ""))
        if token:
            return token
    try:            # a file saved by hand: Windows PowerShell 5.1's > writes UTF-16, Notepad can add a BOM
        raw = _hf_token_file().read_bytes()
        text = raw.decode("utf-16") if raw[:2] in (b"\xff\xfe", b"\xfe\xff") else raw.decode("utf-8-sig")
    except (OSError, UnicodeDecodeError):
        return None
    return clean(text)


def _tokenizer_ready():
    """The tokenizer file is whole: the pinned download's size (no load needed), or another that
    loads. A download that stopped is neither, so `setup tokenizer install` replaces it."""
    return _whole(TOKENIZER_FILE, TOKENIZER_PIN[0]) or bool(_tokenizer())


def _tokenizer_check():
    global _TOKENIZER
    _TOKENIZER = None                                 # load the new file
    return None if prompt_tokens("warm lo-fi hip hop, rhodes, 80 BPM")[1] else "the file didn't load"


def _tokenizer_todo():
    """The steps of `setup tokenizer install` here, shaped like _voice_todo's."""
    token = _hf_token()
    if not token:
        return None, ("it needs your Hugging Face login, and none was found on this computer.\n"
                      + _steps([("Accept Google's Gemma terms with your Hugging Face account at:", TOKENIZER_PAGE),
                                ("Make a read token at huggingface.co/settings/tokens and save it, as the file's"
                                 " only text, in:", str(_hf_token_file())),
                                "Or, instead of step 2, log in with Hugging Face's own command: hf auth login"],
                               again="/tfm setup tokenizer"))
    size, sha = TOKENIZER_PIN
    refused = (f"Accept Google's Gemma terms at {TOKENIZER_PAGE} with the account you're logged in as,"
               " check that the login is current, then run this again")
    return [_fetch_step(f"tokenizer.json ({_size(size)}) from huggingface.co with your login, saved as {TOKENIZER_FILE}",
                        TOKENIZER_URL, TOKENIZER_FILE, size, sha, replacing="doesn't load", token=token, refused=refused),
            ("a test count", 0, _tokenizer_check)], None


def _tokenizer_page(done):
    print(f"Exact prompt-length check: Stable Audio 3 reads only the first {SA3_PROMPT_TOKENS} tokens"
          f" of a prompt, so gen refuses longer ones. Without this file it estimates at {CHARS_PER_TOKEN}"
          " characters a token.")
    if done:
        print("Status: installed.")
        return
    print(f"Status: not installed ({TOKENIZER_FILE.name} is there but doesn't load, so gen estimates)."
          if TOKENIZER_FILE.is_file() else "Status: not installed (estimating).")
    _auto_block("tokenizer", _tokenizer_todo())
    print("\nOr by hand:\n" + _steps([("Sign in to Hugging Face and accept Google's Gemma terms at:", TOKENIZER_PAGE),
                                      "Download tokenizer.json from its \"Files and versions\" tab.",
                                      ("Save it as:", str(TOKENIZER_FILE))], again="/tfm setup tokenizer"))


# One optional extra: its name and what it adds (the list), whether it is installed, the page
# `setup <name>` prints given that answer, the plan `setup <name> install` runs (_voice_todo's
# shape), and what the install's last line says when it worked.
Extra = namedtuple("Extra", "name what installed page plan done")


def _setup_extras():
    """The optional extras in order. One table, so the list, the pages and the installs agree."""
    return [Extra("statusline", "the playing track under Claude Code's prompt",
                  lambda: _statusline_state() == "radio", _statusline_page,
                  lambda: (None, "Claude adds the statusline's line to settings.json itself, so that Claude Code"
                                 " asks you first. /tfm setup statusline shows the line."), ""),
            Extra("voice", "a natural DJ voice (Kokoro) instead of the system voice",
                  _voice_installed, _voice_page, _voice_todo,
                  "the DJ speaks with Kokoro from its next line."),
            Extra("enhancer", "turns a rough idea into a full prompt (enhance, egen)",
                  _enhancer_ready, _enhancer_page, _enhancer_todo,
                  'try /tfm enhance "lofi coffee music".'),
            Extra("tokenizer", "an exact prompt-length check instead of an estimate",
                  _tokenizer_ready, _tokenizer_page, _tokenizer_todo,
                  "gen, enhance and egen count prompt tokens exactly now.")]


def cmd_setup(args):
    """Setup, one step at a time. With no argument: the required steps as a checklist, the first
    unfinished one spelled out, then the optional extras. `setup statusline | voice | enhancer |
    tokenizer`: what that extra adds, the plan of its automatic install and its steps by hand, with
    this machine's paths. Both are read-only, safe to run at any time. `setup <extra> install` runs
    that plan, after the skill has asked the user; the statusline's is Claude's own edit. It alone
    returns an exit code, 1 when it didn't install."""
    sub = args[0].lower() if args else ""
    if sub == "tokens":                                       # the tokenizer's old name
        sub = "tokenizer"
    if sub in ("statusline", "voice", "enhancer", "tokenizer"):       # inline, for readme_check.py
        extra = next(e for e in _setup_extras() if e.name == sub)
        if len(args) == 1:
            extra.page(extra.installed())
        elif len(args) == 2 and args[1].lower() == "install":
            return _install(extra)
        else:
            print(f"Usage: radio setup {sub} [install]")
        return
    if sub:
        print("Usage: radio setup | radio setup statusline | voice | enhancer | tokenizer [install]")
        return
    rows = _setup_required()
    print("Terminal FM setup\n")
    for i, (title, done, _) in enumerate(rows, 1):
        print(f"  [{'x' if done else ' '}] {i}. {title}")
    todo = next((i for i, row in enumerate(rows) if not row[1]), None)
    if todo is None:
        print("\nReady: /tfm play")
    else:
        title, _, text = rows[todo]
        print(f"\n{SETUP_RULE}\nStep {todo + 1} of {len(rows)}: {title}\n\n{text}\n{SETUP_RULE}")
    print("\nOptional extras (/tfm setup <name> shows one, and how to add it):")
    for e in _setup_extras():
        print(f"  [{'x' if e.installed() else ' '}] {e.name:<12}{e.what}")


def cmd_say(args):
    line = args[0] if args else ""
    if not line:
        print('Usage: radio say "<line for the DJ to read on air>"')
        return
    queue_add(line)
    print(f"Queued for the DJ ({len(queue_files())} line(s) pending).")


_ON_WORDS = ("on", "enable", "enabled", "true", "1", "yes")
_OFF_WORDS = ("off", "disable", "disabled", "false", "0", "no")


def cmd_announce(args):
    """Toggle whether the DJ speaks an update when Claude finishes a turn while music is stopped.

    `radio announce breaking on|off` toggles breaking-news mode instead: while music IS playing,
    interrupt the current track to speak the update, then resume the track where it left off.
    """
    if args and args[0].lower() in ("breaking", "break", "interrupt"):
        cmd_breaking(args[1:])
        return
    sub = (args[0].lower() if args else "status")
    if sub in _ON_WORDS:
        set_config("dj", "announce_when_idle", True)
        print("DJ idle announcements: ON")
        print("  Claude will get a short spoken update when it finishes a turn, even with music stopped.")
    elif sub in _OFF_WORDS:
        set_config("dj", "announce_when_idle", False)
        print("DJ idle announcements: OFF")
    else:
        cur = bool(CONFIG.get("dj", {}).get("announce_when_idle", False))
        brk = bool(CONFIG.get("dj", {}).get("breaking_news", False))
        print(f"DJ idle announcements: {'ON' if cur else 'OFF'}")
        print(f"DJ breaking news    : {'ON' if brk else 'OFF'}")
        print("  Toggle with:  radio announce on|off   |   radio announce breaking on|off")


def cmd_breaking(args):
    """Toggle breaking-news mode: interrupt the playing track to speak an update, then resume it."""
    sub = (args[0].lower() if args else "status")
    if sub in _ON_WORDS:
        set_config("dj", "breaking_news", True)
        print("DJ breaking news: ON")
        print("  When Claude finishes a turn, the current track is interrupted for the spoken")
        print("  update, then resumes where it left off (mpv/ffplay/cvlc seek; others restart).")
    elif sub in _OFF_WORDS:
        set_config("dj", "breaking_news", False)
        print("DJ breaking news: OFF (updates just queue between tracks).")
    else:
        cur = bool(CONFIG.get("dj", {}).get("breaking_news", False))
        print(f"DJ breaking news: {'ON' if cur else 'OFF'}")
        print("  Toggle with:  radio breaking on   |   radio breaking off")


def _hook_line(event, proj):
    if event.lower() == "sessionstart":
        pool = [f"Claude just clocked in over on {proj}. Let's set the mood.",
                f"Fresh session firing up in {proj} - here we go.",
                f"Look who's back: Claude, live from {proj}."]
    else:  # Stop / anything else = "finished a turn"
        pool = [f"Update from the {proj} desk: Claude just wrapped another task.",
                f"That's a wrap on the latest over in {proj}.",
                f"Claude just pushed through more work on {proj}.",
                f"Quick note from the {proj} newsroom: another one done."]
    return random.choice(pool)


_ACTION_WORDS = ("built", "build", "fix", "wired", "wire", "added", "adding", "ship", "creat",
                 "implement", "generat", "set up", "setup", "switch", "replac", "confirm",
                 "verif", "tested", "updat", "remov", "refactor", "wrote", "made", "hooked",
                 "install", "download", "enqueu", "rewir", "cleared", "spoke", "fixed", "swapped")
_DIRECTED = ("want me", "should i", "do you want", "you want", "let me know", "your call",
             "tell me", "which way", "want it", "wanna")
_OPENERS = (r"right|on it|let me|so|now|okay|ok|done|got it|sure|alright|yep|yeah|ah|oh|hmm|"
            r"great|perfect|exactly|good|well|nice|huh|yikes|ha")


def _clean_blurb(text, max_chars=280):
    """Strip markdown/code, then pick the most descriptive 1-2 sentences (skips filler/questions)."""
    text = re.sub(r"```.*?```", " ", text, flags=re.S)        # fenced code
    kept = []
    for ln in text.splitlines():
        s = ln.strip()
        if not s or s.startswith("|") or set(s) <= set("-|:= "):   # blank / table / rule
            continue
        s = re.sub(r"^(?:[-*•]|\d+\.)\s+", "", s)                  # drop list markers
        if s:
            kept.append(s if s[-1] in ".!?:" else s + ".")        # each line = its own sentence
    text = " ".join(kept)
    text = re.sub(r"`([^`]*)`", r"\1", text)                  # inline code
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)      # links -> label
    text = re.sub(r"[#*_>`]+", "", text)                      # md symbols
    text = re.sub(r"\s+", " ", text).strip()
    text = text.lstrip("-—–:•✅⚠️🎙🎵♪·✓ ").strip()
    if not text:
        return ""
    sents = [s for s in re.split(r"(?<=[.!?])\s+", text) if s.strip()]

    def directed(s):
        return s.rstrip().endswith("?") or any(p in s.lower() for p in _DIRECTED)

    cand = [s for s in sents if not directed(s)] or sents
    # start at the first sentence that actually describes an action; else the first one
    start = next((i for i, s in enumerate(cand)
                  if any(k in s.lower() for k in _ACTION_WORDS)), 0)
    out = ""
    for s in cand[start:]:
        if out and len(out) + len(s) + 1 > max_chars:
            break
        out = (out + " " + s).strip()
        if len(out) >= max_chars:
            break
    out = re.sub(rf"^(?:{_OPENERS})[\s,:.\-—–]+", "", out, flags=re.I).strip()   # drop filler opener
    out = out[:max_chars].strip()
    if len(out.split()) < 3:                  # too short / junk -> fall back to the generic line
        return ""
    return out[0].upper() + out[1:]


def _blurb_from_transcript(path):
    """Pull the last assistant text message from the session transcript JSONL."""
    try:
        lines = Path(path).read_text(encoding="utf-8", errors="replace").splitlines()
    except Exception:
        return ""
    for ln in reversed(lines):
        try:
            o = json.loads(ln)
        except Exception:
            continue
        if o.get("type") != "assistant":
            continue
        content = (o.get("message") or {}).get("content")
        if isinstance(content, list):
            for b in content:
                if isinstance(b, dict) and b.get("type") == "text" and b.get("text", "").strip():
                    return _clean_blurb(b["text"])
    return ""


def _install_statusline():
    """Copy statusline.py from beside radio.py into the data directory when the bytes differ, so
    a statusLine setting can point at <data dir>/statusline.py across plugin updates. Skipped
    when the two are the same file (a clone run in place as the data directory). Never raises."""
    try:
        if not STATUSLINE_SRC.is_file():
            return
        if STATUSLINE_DST.exists() and os.path.samefile(STATUSLINE_SRC, STATUSLINE_DST):
            return
        data = STATUSLINE_SRC.read_bytes()
        if STATUSLINE_DST.is_file() and STATUSLINE_DST.read_bytes() == data:
            return
        ROOT.mkdir(parents=True, exist_ok=True)
        tmp = STATUSLINE_DST.with_name(f"{STATUSLINE_DST.name}.{os.getpid()}.tmp")
        try:
            tmp.write_bytes(data)
            os.replace(tmp, STATUSLINE_DST)
        finally:
            _unlink_quiet(tmp)                      # still there only when a step was refused
    except Exception:
        pass


def cmd_hook(args):
    """Auto-feed the DJ from a Claude Code hook (SessionStart/Stop): the plugin's hooks/hooks.json
    through hooks/radio-hook.sh, or a settings.json entry on the manual install.

    * Music playing  -> enqueue a line; the daemon reads it between tracks.
    * Music stopped  -> if dj.announce_when_idle is on, speak the update right now (Stop only),
                        so Claude still narrates itself with no music running. Off by default.

    Prefers a real blurb from Claude's last message; falls back to a generic project line. The
    message comes from the hook's stdin JSON: `last_assistant_message` (Stop input on current
    Claude Code; seen on 2.1.296), else the JSONL at `transcript_path` for CLIs that don't send it.
    The transcript is only opened when the field is absent.

    SessionStart also copies statusline.py into the data directory first, whatever is playing.
    """
    event = args[0] if args else "Stop"
    finished = event.lower() != "sessionstart"   # Stop / anything-but-start == "wrapped a turn"
    if not finished:
        _install_statusline()
        try:                                       # lets `radio setup` tell whether hooks run at all
            _atomic_write(HOOK_SEEN, time.strftime("%Y-%m-%d %H:%M"))
        except Exception:
            pass
    st = read_state()
    playing = _is_playing(st)
    announce_idle = bool(CONFIG.get("dj", {}).get("announce_when_idle", False))
    breaking = bool(CONFIG.get("dj", {}).get("breaking_news", False)) and finished

    if playing:
        if BREAKING_FILE.exists():                # an interrupt is already pending -> don't stack
            return
        if not breaking and len(queue_files()) >= 4:   # cap the between-track queue (not breaking)
            return
    elif not (announce_idle and finished):
        return                                     # idle + setting off (or a session-start) -> nothing

    cwd = transcript = ""
    last_msg = None                               # None = the field wasn't sent (older CLI)
    try:
        if not sys.stdin.isatty():
            raw = sys.stdin.read()
            if raw.strip():
                j = json.loads(raw)
                cwd = str(j.get("cwd", ""))
                transcript = str(j.get("transcript_path", ""))
                if isinstance(j.get("last_assistant_message"), str):
                    last_msg = j["last_assistant_message"]
    except Exception:
        pass
    proj = os.path.basename(cwd.rstrip("/\\")) if cwd else (os.path.basename(os.getcwd()) or "the lab")
    line = ""
    if finished:
        if last_msg is not None:
            blurb = _clean_blurb(last_msg)
        else:
            blurb = _blurb_from_transcript(transcript) if transcript else ""
        if blurb:
            line = f"Here's the latest from the {proj} desk. {blurb}"
    if not line:
        line = _hook_line(event, proj)

    if playing:
        if breaking:                             # cut the current track, speak now, then resume it
            try:
                BREAKING_FILE.write_text(line, encoding="utf-8")
            except Exception:
                return
            _kill_player(st)                     # daemon's wait() returns -> speaks + resumes track
            return
        pending = queue_files()
        if pending:                              # de-dupe against the most recent queued line
            try:
                if pending[-1].read_text(encoding="utf-8").strip() == line:
                    return
            except Exception:
                pass
        queue_add(line)
    else:
        _speak_line(line)                        # idle announcement: speak it now (lock-guarded)


def cmd_list(_args):
    lib = get_library()
    if not lib:
        print(f"Library is empty ({OUTDIR}).")
        return
    try:                                    # snapshot the order so `play <numbers>` maps to this list
        _write_json(LIST_FILE, [t.name for t in lib])
    except Exception:
        pass
    pl = load_playlist()
    in_pl = {p.name for p in pl} if pl else set()
    width = len(str(len(lib)))
    print(f"Library ({len(lib)} tracks) in {OUTDIR}:")
    for i, t in enumerate(lib, 1):
        mark = " *" if t.name in in_pl else "  "
        print(f"  {str(i).rjust(width)}.{mark} {t.stem}")
    print('\nPlay a selection in order:  radio play 1,3,5-8      (back to shuffle: radio shuffle)')
    if in_pl:
        print("  (* = currently in the playlist)")


def _start_or_jump(say=""):
    """After changing the playlist: if the daemon is live, jump to the new order now (kill the
    player so it advances and re-reads); otherwise start playback. `say` is a `play --say`
    sign-on, spoken before the selection's first track either way."""
    st = read_state()
    if _is_playing(st):
        if say:
            queue_add(say, front=True)
        if _player_alive(st):
            _kill_player(st)                # player dies -> daemon advances -> re-reads playlist at top
        print("Playing your selection now.")
    else:
        _play(say)


def cmd_playlist(args, say=""):
    """Show, set, or clear the ordered playlist. Numbers come from `radio list`.

    radio playlist                 show the current playlist
    radio playlist 1,3,5-8         play only those tracks, in that order (loops); alias: radio play 1,3,5-8
    radio playlist clear           clear it -> back to full-library shuffle (alias: radio shuffle)
    """
    if not args:
        pl = load_playlist()
        if not pl:
            print("No playlist set - playing the full library on shuffle.")
            print("Build one with:  radio play 1,3,5-8   (numbers from `radio list`)")
            return
        print(f"Playlist ({len(pl)} tracks, in order):")
        for i, t in enumerate(pl, 1):
            print(f"  {i}. {t.stem}")
        print("Clear with:  radio shuffle")
        return
    if args[0].lower() in ("clear", "off", "shuffle", "none", "all", "reset"):
        cmd_shuffle(args)
        return
    if not looks_like_selection(args):
        print("Give track numbers from `radio list`, e.g.  radio playlist 1,3,5-8")
        return
    snap = list_snapshot()
    idx = parse_selection(args, len(snap))
    if not idx:
        print(f"No valid track numbers (library has {len(snap)}). Run `radio list` to see them.")
        return
    tracks = [snap[i - 1] for i in idx]
    try:
        _write_json(PLAYLIST_FILE, [t.name for t in tracks])
    except Exception as e:
        print(f"Could not save playlist: {e}")
        return
    print(f"Playlist set ({len(tracks)} tracks, in order):")
    for pos, t in zip(idx, tracks):
        print(f"  {pos}. {t.stem}")
    _start_or_jump(say)


def cmd_shuffle(_args):
    existed = PLAYLIST_FILE.exists()
    _unlink_quiet(PLAYLIST_FILE)
    print("Playlist cleared - back to full-library shuffle." if existed
          else "Already on full-library shuffle.")
    st = read_state()                       # if playing, leave the playlist track and reshuffle
    if existed and _is_playing(st) and _player_alive(st):
        _kill_player(st)


def cmd_format(args):
    """Show or set the file type gen saves new tracks as (config.json stability_api.output_format).
    Existing tracks are untouched, and the library plays both types. wav+mp3 (either order) keeps
    a WAV master in <library>/_wav beside the MP3 that plays, and needs ffmpeg for the encode."""
    cur = CONFIG["stability_api"]["output_format"]
    if not args:
        print(f"Output format: {cur}   (change: radio format {' | '.join(FORMAT_CHOICES)})")
        return
    fmt = args[0].lower().lstrip(".")
    if fmt == "mp3+wav":
        fmt = BOTH_FORMATS
    if fmt not in FORMAT_CHOICES:
        print(f"Unknown format '{args[0]}'. Use: radio format {' | '.join(FORMAT_CHOICES)}")
        return
    if fmt == BOTH_FORMATS and not _ffmpeg():
        where = " or in C:\\ffmpeg\\bin" if IS_WIN else ""
        print(f"wav+mp3 needs ffmpeg to make the MP3, and it wasn't found on PATH{where}. Not saved.")
        return
    set_config("stability_api", "output_format", fmt)
    if fmt == BOTH_FORMATS:
        print(f"Output format: {fmt}   (new tracks play as .mp3; the .wav master is kept in "
              f"{OUTDIR.name}/{WAV_SUBDIR})")
    else:
        print(f"Output format: {fmt}   (new tracks save as .{fmt})")


def _stdin_is_console():
    """True when a person can type at stdin. isatty() alone is not enough on Windows: it is also
    true for NUL (`< /dev/null`, subprocess.DEVNULL), so ask the console for its input mode."""
    try:
        if not (sys.stdin and sys.stdin.isatty()):
            return False
        if not IS_WIN:
            return True
        import ctypes
        import msvcrt
        mode = ctypes.c_uint32()
        handle = msvcrt.get_osfhandle(sys.stdin.fileno())
        return bool(ctypes.windll.kernel32.GetConsoleMode(handle, ctypes.byref(mode)))
    except Exception:
        return False


def cmd_key(args):
    """Store, inspect or remove the Stability API key.

    radio key             prompt for the key (hidden input, never on the command line or in
                          shell history) and save it to <data dir>/.key, owner-readable only
    radio key show        whether a key is set and where it came from (never any of its
                          characters), and whether STABILITY_API_KEY is also set
    radio key clear       delete the stored key
    """
    sub = args[0].lower() if args else ""
    if sub == "show":
        k = _read_key()
        src = ".key file" if KEY_FILE.exists() and KEY_FILE.read_text(encoding="utf-8").strip() \
            else ("STABILITY_API_KEY" if k else "none")
        env = "set" if os.environ.get("STABILITY_API_KEY", "").strip() else "not set"
        # Security: say whether there is a key, never print any of it. This output ends up in
        # terminal scrollback and, when Claude runs `key show`, in its session transcript; it used
        # to print the key's first 6 characters.
        print(f"Key: {'set' if k else '(none)'}   source: {src}   STABILITY_API_KEY: {env}")
        if not k:
            _print_key_help("To add one:")
        return
    if sub in ("clear", "delete", "remove"):
        try:
            KEY_FILE.unlink()
            print(f"Removed {KEY_FILE}.")
        except FileNotFoundError:
            print("No stored key.")
        return
    if args:
        print("Usage: radio key | radio key show | radio key clear\n"
              "  (the key is typed at a hidden prompt, not passed as an argument)")
        return
    # Windows getpass reads the console, not stdin, so with input piped or redirected (as when
    # Claude runs it) it waited forever instead of reaching the except below.
    no_tty = "No terminal to type the key into here. To add it:"
    if not _stdin_is_console():
        _print_key_help(no_tty)
        return
    import getpass
    try:
        k = getpass.getpass("Stability API key (input hidden): ").strip()
    except Exception:
        _print_key_help(no_tty)
        return
    if not k:
        print("Nothing entered; key unchanged.")
        return
    _write_private(KEY_FILE, k)
    print(f"Key saved to {KEY_FILE}.")


def cmd_folder(args):
    """Show or change the folder the radio plays from (persisted to config.json 'library_dir').

    radio folder                 show the current library folder + track count
    radio folder <path>          play from <path> (created if missing); ~ and env vars expand
    radio folder default|reset   revert to the built-in <root>/output folder
    """
    if not args:
        n = len(get_library())
        kind = "default" if OUTDIR == DEFAULT_OUTDIR else "custom"
        print(f"Library folder: {OUTDIR}  ({kind})")
        print(f"  {n} track(s)")
        print("Change with:  radio folder <path>   |   radio folder default")
        return
    target = " ".join(args).strip().strip('"').strip("'")
    if target.lower() in ("default", "reset", "clear", "none"):
        new, value = DEFAULT_OUTDIR, ""
    else:
        new, value = resolve_outdir({"library_dir": target}), target
    # Create first, save second: a path that can't be created must never reach config.json, where
    # it would break every later command at import.
    try:
        new.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        print(f"Not saved: could not create {new}: {e}")
        return
    set_config(None, "library_dir", value)
    n = len(_audio_in(new))
    print(f"Library folder set to: {new}")
    print(f"  {n} track(s) found")
    if n == 0:
        print('  Empty - generate tracks (radio gen "<prompt>") or drop .mp3 / .wav files in.')
    if _is_playing(read_state()):
        print("  Note: restart playback to pick up the new folder:  radio stop  then  radio play")


def _on_air(nothing_msg):
    """(track path, name) for the track on air, or None after printing why there is none."""
    st = read_state()
    name = st.get("now_playing")
    if st.get("status") != "playing" or not name:
        print(nothing_msg)
        return None
    track = OUTDIR / name
    if not track.exists():
        print(f"Current track is not in the library folder: {name}")
        return None
    return track, name


def _archive_paths(tracks, playing_name, dest_dir=None, label="archived"):
    """Move tracks into _archive (or `dest_dir`: `drop` passes BAD_DIR), dropping them from the
    playlist. If one of them is on air, the player is killed first so the file isn't locked and the
    daemon moves on to the next track."""
    if playing_name and any(t.name == playing_name for t in tracks):
        st = read_state()
        if _player_alive(st):
            _kill_player(st)            # daemon's wait() returns -> it advances past the moved track
    moved = []
    for t in tracks:
        dest = _move_track(t, dest_dir or ARCHIVE_DIR)
        if dest:
            moved.append(t.name)
            print(f"  {label}: {t.stem}")
    if moved:
        _playlist_drop(moved)
    return moved


def cmd_archive(args):
    """Move tracks you don't want out of rotation, into <library>/_archive. Nothing is deleted -
    the files stay on disk and `radio unarchive` puts them back.

    radio archive              archive the track playing right now (and move on to the next)
    radio archive list         numbered library listing, so you can pick what to archive
    radio archive 1,3,5-8      archive those tracks (numbers from `radio list` / `archive list`)
    radio archive show         list what's already archived
    """
    sub = args[0].lower() if args else ""

    if sub == "list":                       # cmd_list also snapshots the order for the numbers below
        cmd_list([])
        n = len(archived_tracks())
        print(f"\nArchive: {n} track(s) in {ARCHIVE_DIR}")
        print("  Archive some with:  radio archive 1,3,5-8      (put back: radio unarchive)")
        return

    if sub in ("show", "archived", "ls"):
        arch = archived_tracks()
        if not arch:
            print(f"Archive is empty ({ARCHIVE_DIR}).")
            return
        print(f"Archived ({len(arch)} tracks) in {ARCHIVE_DIR}:")
        for i, t in enumerate(arch, 1):
            print(f"  {i}. {t.stem}")
        print("Put one back with:  radio unarchive 1")
        return

    if not args:                            # archive whatever is on air right now
        on_air = _on_air("Nothing is playing. Use `radio archive list` to pick tracks by number.")
        if not on_air:
            return
        track, name = on_air
        print(f"Archiving the current track: {track.stem}")
        if _archive_paths([track], name):
            print("Skipped to the next track.")
        return

    if not looks_like_selection(args):
        print("Give track numbers from `radio list`, e.g.  radio archive 3,7")
        print("Or:  radio archive        (the track playing now)")
        print("     radio archive list   (numbered library)")
        print("     radio archive show   (what's already archived)")
        return

    snap = list_snapshot()
    idx = parse_selection(args, len(snap))
    if not idx:
        print(f"No valid track numbers (library has {len(snap)}). Run `radio list` to see them.")
        return
    # De-duped: archiving the same track twice is a no-op.
    tracks = [t for t in _pick_unique(snap, idx) if t.exists()]
    if not tracks:
        print("Those tracks are no longer in the library.")
        return
    moved = _archive_paths(tracks, read_state().get("now_playing"))
    print(f"Archived {len(moved)} track(s) -> {ARCHIVE_DIR}")
    print(f"Library now has {len(get_library())} track(s). Put them back with: radio unarchive")


def cmd_drop(args):
    """Move the track playing right now into BAD_DIR (output/bad song) and skip to the next one.
    `radio archive` with no args, except the destination is the one shared reject folder rather
    than this library's _archive, so rejects from every folder end up together."""
    if args:
        print("Usage: radio drop   (moves the track playing now to the bad song folder)")
        return
    on_air = _on_air("Nothing is playing.")
    if not on_air:
        return
    track, name = on_air
    if track.parent.resolve() == BAD_DIR.resolve():
        print(f"Already in {BAD_DIR.name} (it's the folder playing now): {track.stem}\n"
              f"Use `radio archive` or `radio skip` instead.")
        return
    print(f"Dropping the current track: {track.stem}")
    if _archive_paths([track], name, BAD_DIR, f"moved to {BAD_DIR.name}"):
        print("Skipped to the next track.")


def cmd_unarchive(args):
    """Move tracks back out of _archive into the library.

    radio unarchive            list the archive, numbered
    radio unarchive 1,3        restore those tracks
    radio unarchive all        restore everything
    """
    arch = archived_tracks()
    if not arch:
        print(f"Archive is empty ({ARCHIVE_DIR}).")
        return

    if not args:                            # snapshot so the numbers below stay stable
        try:
            _write_json(ARCHIVE_LIST_FILE, [t.name for t in arch])
        except Exception:
            pass
        print(f"Archived ({len(arch)} tracks) in {ARCHIVE_DIR}:")
        for i, t in enumerate(arch, 1):
            print(f"  {i}. {t.stem}")
        print("\nRestore with:  radio unarchive 1,3      (everything: radio unarchive all)")
        return

    if args[0].lower() in ("all", "*", "everything"):
        picks = arch
    else:
        if not looks_like_selection(args):
            print("Give numbers from `radio unarchive`, e.g.  radio unarchive 1,3")
            return
        snap = _saved_order(ARCHIVE_LIST_FILE, ARCHIVE_DIR) or arch   # the order the user was shown
        idx = parse_selection(args, len(snap))
        if not idx:
            print(f"No valid numbers (archive has {len(snap)}). Run `radio unarchive` to see them.")
            return
        picks = _pick_unique(snap, idx)

    restored = 0
    for t in picks:
        if _move_track(t, OUTDIR):
            print(f"  restored: {t.stem}")
            restored += 1
    print(f"Restored {restored} track(s). Library now has {len(get_library())} track(s).")
    if restored:
        print("  They rejoin the shuffle on the daemon's next pass.")


def cmd_prompts(args):
    """Every prompt you've generated a track from, plus every `enhance` rewrite - so a good one is
    never lost, whether or not it became audio.

    radio prompts              recent generations, newest first
    radio prompts all          the whole history
    radio prompts 7            full detail for entry 7, with a ready-to-run regenerate command
    radio prompts <text>       only entries matching <text>
    """
    recs = history_all()
    if not recs:
        print(f"No prompt history yet ({HISTORY_FILE.name}).")
        print('  It fills up automatically: every `radio gen` / `radio egen` track, and every'
              '\n  `radio enhance` rewrite even though that generates nothing.')
        return

    numbered = list(enumerate(recs, 1))     # numbers are positions in the file, so they never shift
    arg = " ".join(args).strip()

    if arg.isdigit():                       # detail view for one entry
        n = int(arg)
        if not 1 <= n <= len(numbered):
            print(f"No entry {n}. History has {len(numbered)}.")
            return
        rec = numbered[n - 1][1]
        print(f"Prompt #{n}   {rec.get('ts', '?')}")
        if rec.get("idea"):
            print(f"  your idea : {rec['idea']}")
        print(f"  prompt    : {rec.get('prompt', '')}")
        print(f"  duration  : {rec.get('duration', '?')}s")
        if _history_where(rec) == "enhance":
            print("  file      : none - enhanced only, never generated")
        else:
            print(f"  file      : {rec.get('file', '?')}  ({_history_where(rec)})")
        print(f"\nMake another like it:\n  radio gen \"{rec.get('prompt', '')}\" 1 "
              f"{rec.get('duration') or CONFIG['stability_api']['duration']}")
        return

    show_all = arg.lower() == "all"
    if arg and not show_all:                # text search across idea + prompt
        q = arg.lower()
        numbered = [(i, r) for i, r in numbered
                    if q in (r.get("prompt", "") + " " + r.get("idea", "")).lower()]
        if not numbered:
            print(f"No prompts matching '{arg}'.")
            return

    total = len(numbered)
    view = list(reversed(numbered))         # newest first
    limit = None if (show_all or arg) else 20
    if limit and total > limit:
        view = view[:limit]

    width = len(str(max(i for i, _ in numbered)))
    print(f"Prompt history ({total} entr{'y' if total == 1 else 'ies'}) - newest first:")
    for i, rec in view:
        text = rec.get("idea") or rec.get("prompt", "")
        text = " ".join(text.split())
        if len(text) > 68:
            text = text[:67] + "…"
        where = _history_where(rec)
        mark = {"library": " ", "archived": "a", "bad song": "b", "missing": "x",
                "enhance": "e"}.get(where, " ")
        print(f"  {str(i).rjust(width)}.{mark} {rec.get('ts', '?')[:16]}  "
              f"{str(rec.get('duration', '?')).rjust(3)}s  {text}")
    if limit and total > limit:
        print(f"  ... {total - limit} older - see them all with:  radio prompts all")
    print("\nFull detail + a regenerate command:  radio prompts <number>"
          "\n  (a = archived, b = dropped to bad song, x = file no longer on disk,"
          " e = enhanced only, never generated)")


def _take_resume():
    """Consume a pause point written by `radio pause`. Returns (track_path, offset_seconds) or None."""
    try:
        if not RESUME_FILE.exists():
            return None
        r = json.loads(RESUME_FILE.read_text(encoding="utf-8"))
        RESUME_FILE.unlink()
        t = OUTDIR / str(r.get("track", ""))
        off = float(r.get("offset", 0) or 0)
        if t.exists() and off > 1:
            return (t, off)
    except Exception:
        pass
    return None


def play_track(track, player, builder, vol, start_at=0):
    """Play one track to its end. `start_at` seeks in (pause/breaking resume). Persists the live
    position (player_started + player_offset) so `radio pause` can compute where to resume. Returns
    when the track ends naturally or the player is killed (skip/pause); loops on breaking-news."""
    resume_at = start_at
    while True:
        count = len(get_library())
        write_now(f"Terminal FM > {track.stem}  ({count} tracks)")
        started = time.time()
        try:
            proc = subprocess.Popen(
                player_argv(player, builder, str(track), vol, resume_at),
                stdin=DEVNULL, stdout=DEVNULL, stderr=DEVNULL,
                creationflags=CREATE_NO_WINDOW)
        except Exception:
            time.sleep(1)
            return
        write_state(status="playing", daemon_pid=os.getpid(), daemon_exe=_self_exe(),
                    player_pid=proc.pid, player_exe=PLAYER_PROCESS.get(Path(player).name, Path(player).name),
                    now_playing=track.name, player_started=started, player_offset=resume_at)
        proc.wait()
        # Breaking news: the hook wrote a line + killed the player mid-track. Speak it now (music
        # paused), then resume THIS track where it left off. No file -> ended naturally, or was
        # skipped/paused -> return so the daemon advances (or exits, if paused killed the daemon).
        if BREAKING_FILE.exists():
            resume_at += time.time() - started
            write_now("Terminal FM | breaking news...")
            speak_breaking()
            continue
        return


def daemon_loop():
    player, builder = detect_player()
    if not player:
        write_now("Terminal FM | no audio player found")
        return
    vol = int(CONFIG.get("volume", 85))
    write_state(status="playing", daemon_pid=os.getpid(), daemon_exe=_self_exe(),
                player_pid=None, now_playing=None)
    write_now("Terminal FM | on air")
    resume_first = _take_resume()   # (track, offset) from a pause -> play it first, mid-track
    shuffle_queue = []              # remaining shuffled tracks (shuffle mode)
    pl_pos = 0                      # cursor within the active playlist
    last_pl = None                  # last playlist contents seen (detect a changed selection)
    # One track per outer iteration: state (playlist vs shuffle) is re-read every track, so a
    # `radio play 1,3,5` / `radio shuffle` mid-playback takes effect on the very next track.
    while True:
        lib = get_library()
        if not lib:
            write_now('Terminal FM | no tracks - run: radio gen "your prompt"')
            time.sleep(5)
            continue

        if resume_first:                       # resume the paused track at its offset (no DJ line)
            t, off = resume_first
            resume_first = None
            if t.exists():
                play_track(t, player, builder, vol, off)
            continue

        playlist = load_playlist()
        if playlist:                           # play the user's selection in order, then loop it
            names = [t.name for t in playlist]
            if names != last_pl:               # a new/changed selection -> start from the top
                pl_pos, last_pl = 0, names
            if pl_pos >= len(playlist):
                pl_pos = 0
            track = playlist[pl_pos]
            pl_pos += 1
        else:                                  # shuffle the full library, one pass at a time
            last_pl = None
            if not shuffle_queue:
                shuffle_queue = lib[:]
                random.shuffle(shuffle_queue)
            track = shuffle_queue.pop(0)

        if not track.exists():
            continue
        speak_next()           # DJ reads one queued line (if any) before this track
        play_track(track, player, builder, vol)


# --------------------------------------------------------------------------- main
COMMANDS = {
    "gen": cmd_gen, "egen": cmd_egen, "enhance": cmd_enhance,
    "play": cmd_play, "resume": cmd_play, "stop": cmd_stop,
    "pause": cmd_pause, "skip": cmd_skip,
    "next": cmd_skip, "status": cmd_status, "list": cmd_list,
    "folder": cmd_folder, "library": cmd_folder,
    "format": cmd_format, "filetype": cmd_format, "key": cmd_key,
    "playlist": cmd_playlist, "pl": cmd_playlist, "shuffle": cmd_shuffle,
    "say": cmd_say, "dj": cmd_say, "hook": cmd_hook, "announce": cmd_announce,
    "breaking": cmd_breaking,
    "archive": cmd_archive, "unarchive": cmd_unarchive, "restore": cmd_unarchive,
    "drop": cmd_drop,
    "prompts": cmd_prompts, "history": cmd_prompts, "prompt-history": cmd_prompts,
    "setup": cmd_setup,
    # Short keys: the most-used command in a letter gets the letter,
    # the rest two letters. Kept after the full names so the unknown-command hint still lists those.
    "p": cmd_play, "pa": cmd_pause, "pr": cmd_prompts,
    "s": cmd_stop, "n": cmd_skip, "sk": cmd_skip, "st": cmd_status, "sh": cmd_shuffle,
    "se": cmd_setup,
    "l": cmd_list, "f": cmd_folder, "ft": cmd_format,
    "a": cmd_archive, "an": cmd_announce, "b": cmd_breaking, "d": cmd_drop, "u": cmd_unarchive,
    "g": cmd_gen, "e": cmd_enhance, "eg": cmd_egen, "k": cmd_key,
}


def main(argv):
    # Piped output (how Claude runs this) defaults to the ANSI codepage on Windows (cp1252): "é"
    # shows up as "�" to a UTF-8 reader, and a character cp1252 lacks ("→", "☕") raised
    # UnicodeEncodeError on gen's Prompt: line, before the track was even submitted.
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass                # pythonw has no stdout; a non-TextIOWrapper stream can't reconfigure
    cmd = argv[0].lower() if argv else "status"
    rest = argv[1:]
    if cmd == "__daemon":
        daemon_loop()
        return
    handler = COMMANDS.get(cmd)
    if not handler:
        # Built from COMMANDS so it can't go stale: one name per handler, in table order.
        seen, names = set(), []
        for k, h in COMMANDS.items():
            if h not in seen:
                seen.add(h)
                names.append(k)
        print(f"Unknown command '{cmd}'. Use: {' | '.join(names)}")
        return
    return handler(rest)            # the exit code: only `setup <extra> install` returns one


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
