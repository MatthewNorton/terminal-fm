#!/usr/bin/env python3
"""
Terminal FM DJ voice - portable, stdlib-only, cross-platform. Speaks one line of text through the
best TTS engine present. radio.py runs `dj.py say` for every on-air line (queued lines, breaking
news, idle announcements); nothing here writes text, so every word spoken is what it was given.

    dj.py say --text "<line>"        speak a line
    dj.py say --file <path>          speak the contents of a file
    echo "<line>" | dj.py say        speak stdin

Engine order: Kokoro-82M (kokoro_tts.py, run in an interpreter that has kokoro_onnx) > Piper >
macOS `say` > Windows SAPI > espeak. Which one spoke, and why, is appended to dj_engine.log.

Data directory: ~/.claude/radio, or $AI_RADIO_HOME. Voice settings live in config.json under "dj".
"""

import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

CODE_DIR = Path(__file__).resolve().parent               # kokoro_tts.py lives next to this file
ROOT = Path(os.path.expanduser(os.environ.get("AI_RADIO_HOME", "").strip()
                               or str(Path.home() / ".claude" / "radio")))
CONFIG_FILE = ROOT / "config.json"
KOKORO_DIR = ROOT / "kokoro"                              # kokoro-v1.0.*.onnx + voices-v1.0.bin
TMP_WAV = ROOT / "_dj.wav"                                # shared scratch (Piper only)
ENGINE_LOG = ROOT / "dj_engine.log"                       # one line per utterance: engine + why
KOKORO_PY_CACHE = ROOT / ".kokoro_python"                 # cached interpreter that has kokoro_onnx
IS_WIN = os.name == "nt"
DEVNULL = subprocess.DEVNULL
CREATE_NO_WINDOW = 0x08000000 if IS_WIN else 0            # hide child console windows on Windows
STALE_RENDER_SECS = 1800                                  # sweep _dj_<pid>.wav older than this

# "voice" is a Piper .onnx path or "auto"; "kokoro_voice" a Kokoro voice name; "rate" the SAPI rate.
# "python" (no default) pins the interpreter used for Kokoro instead of probing for one.
DJ_DEFAULTS = {"kokoro_voice": "am_michael", "voice": "auto", "rate": 1}


def dj_config():
    cfg = dict(DJ_DEFAULTS)
    if CONFIG_FILE.exists():
        try:
            user = json.loads(CONFIG_FILE.read_text(encoding="utf-8")).get("dj", {})
            if isinstance(user, dict):
                cfg.update(user)
        except Exception:
            pass
    return cfg


# --------------------------------------------------------------------------- TTS
def _find_piper_voice(cfg):
    v = cfg.get("voice", "auto")
    if v and v != "auto" and Path(v).exists():
        return v
    cands = list(ROOT.glob("*.onnx")) + list((ROOT / "voices").glob("*.onnx"))
    return str(cands[0]) if cands else None


def _which(exe):
    """`exe` on PATH, else C:/ffmpeg/bin/<exe>.exe on Windows (ffmpeg's tools are often unpacked
    there and never added to PATH), else None."""
    found = shutil.which(exe)
    if found:
        return found
    path = Path("C:/ffmpeg/bin") / f"{exe}.exe"
    return str(path) if IS_WIN and path.exists() else None


def _play_wav(path):
    for exe, args in (("ffplay", ["-nodisp", "-autoexit", "-loglevel", "quiet"]),
                      ("mpv", ["--no-video", "--really-quiet"]),
                      ("afplay", []), ("aplay", ["-q"])):
        found = _which(exe)
        if found:
            subprocess.run([found, *args, str(path)], stdout=DEVNULL, stderr=DEVNULL,
                           creationflags=CREATE_NO_WINDOW)
            return True
    return False


def _log_engine(engine, detail, text):
    """Append one line recording which TTS engine spoke (and why), so fallbacks are never invisible.
    The first 60 characters of the line are kept, so the log holds fragments of whatever was said."""
    try:
        snip = " ".join((text or "").split())[:60]
        with ENGINE_LOG.open("a", encoding="utf-8") as f:
            f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')}\t{engine}\t{detail}\t"
                    f"py={os.path.basename(sys.executable or '?')}\t{snip}\n")
    except Exception:
        pass


def _has_kokoro(py):
    """True if interpreter `py` can import kokoro_onnx + soundfile."""
    try:
        r = subprocess.run([py, "-c", "import kokoro_onnx, soundfile"],
                           stdout=DEVNULL, stderr=DEVNULL, timeout=30,
                           creationflags=CREATE_NO_WINDOW)
        return r.returncode == 0
    except Exception:
        return False


def _kokoro_python(cfg):
    """Find a Python that has kokoro_onnx; cache it.

    The daemon/hook may be launched by an interpreter that lacks kokoro_onnx, which silently
    dropped the DJ to the robotic SAPI voice. Instead of trusting whoever launched us, locate
    ANY interpreter that can actually run Kokoro (current one, its python.exe sibling, then PATH)
    and reuse it. The cache is validated by existence only (fast) and self-heals: a failed render
    clears it so the next call re-probes.
    """
    cfgpy = cfg.get("python")                          # 1) explicit override: dj.python in config
    if cfgpy and Path(str(cfgpy)).exists():
        return str(cfgpy)
    try:                                               # 2) previously-confirmed interpreter
        if KOKORO_PY_CACHE.exists():
            cached = KOKORO_PY_CACHE.read_text(encoding="utf-8").strip()
            if cached and Path(cached).exists():
                return cached
    except Exception:
        pass
    cands = []                                         # 3) probe: us, our python.exe sibling, PATH
    exe = sys.executable or ""
    if exe:
        cands.append(exe)
        if IS_WIN and exe.lower().endswith("pythonw.exe"):
            cands.append(str(Path(exe).with_name("python.exe")))
    for name in ("python", "python3", "py"):
        w = shutil.which(name)
        if w:
            cands.append(w)
    seen = set()
    for c in cands:
        cl = c.lower()
        if not cl or cl in seen:
            continue
        seen.add(cl)
        if _has_kokoro(c):
            try:
                KOKORO_PY_CACHE.write_text(c, encoding="utf-8")
            except Exception:
                pass
            return c
    return None


def _cleanup_tmp():
    """Remove stale per-process render WAVs to bound litter."""
    try:
        cutoff = time.time() - STALE_RENDER_SECS
        for f in ROOT.glob("_dj_*.wav"):
            try:
                if f.stat().st_mtime < cutoff:
                    f.unlink()
            except Exception:
                pass
    except Exception:
        pass


# Why the last _kokoro_render returned no WAV: "skip" (not installed: no model, voices or script)
# or "fail" (installed, but no interpreter could run it or the render errored). The fallback
# engines' log lines read it, so a zero-model install isn't logged as a failed render.
_kokoro_last = ""


def kokoro_files_present():
    """The Kokoro model and voices are downloaded (README: Optional extras). `radio setup` asks too."""
    return ((KOKORO_DIR / "voices-v1.0.bin").exists() and any(
        (KOKORO_DIR / m).exists() for m in
        ("kokoro-v1.0.fp16.onnx", "kokoro-v1.0.onnx", "kokoro-v1.0.int8.onnx")))


def _kokoro_render(text):
    """Render text -> WAV with Kokoro-82M. Returns Path or None (logging why, on failure)."""
    global _kokoro_last
    _kokoro_last = "fail"
    script = CODE_DIR / "kokoro_tts.py"
    if not (kokoro_files_present() and script.exists()):
        _kokoro_last = "skip"
        _log_engine("kokoro-skip", "model/voices/script missing", text)
        return None
    cfg = dj_config()
    py = _kokoro_python(cfg)
    if not py:
        _log_engine("kokoro-fail", "no interpreter has kokoro_onnx installed", text)
        return None
    _cleanup_tmp()
    voice = cfg.get("kokoro_voice", DJ_DEFAULTS["kokoro_voice"])
    out = ROOT / f"_dj_{os.getpid()}.wav"             # per-process: no cross-process clobber
    try:
        r = subprocess.run([py, str(script), "--out", str(out), "--voice", voice],
                           input=text.encode("utf-8"), stdout=DEVNULL, stderr=subprocess.PIPE,
                           timeout=120, creationflags=CREATE_NO_WINDOW)
        if r.returncode == 0 and out.exists():
            _kokoro_last = ""
            return out
        # The last line is the exception; onnxruntime's warnings come first, in UTF-16 on Windows.
        lines = [l.strip() for l in (r.stderr or b"").decode("utf-8", "replace").replace("\0", "").splitlines()]
        err = ([l for l in lines if l] or [""])[-1][:160]
        _log_engine("kokoro-fail", f"rc={r.returncode} ({py}) {err}", text)
    except Exception as e:
        _log_engine("kokoro-fail", f"exception ({py}) {e}", text)
    try:                                               # self-heal: drop a bad cached interpreter
        if KOKORO_PY_CACHE.exists() and not cfg.get("python"):
            KOKORO_PY_CACHE.unlink()
    except Exception:
        pass
    return None


def _kokoro_why():
    """The fallback's reason, from what the last _kokoro_render did."""
    if _kokoro_last == "skip":
        return "kokoro not installed"
    if _kokoro_last == "fail":
        return "kokoro render failed (see prior kokoro-fail line)"
    return "kokoro rendered but playback failed"


def speak(text, cfg):
    """Speak `text` via the first available engine. Returns the engine name or None.

    Every engine gets the text on stdin or from a file, never as a command-line argument, so a
    line that happens to start with "-" can't be read as an option by `say` or espeak."""
    # 0) Kokoro-82M (most realistic, local) if the model is present
    wav = _kokoro_render(text)
    if wav:
        played = _play_wav(wav)
        try:
            wav.unlink()                               # the per-process render, done with
        except Exception:
            pass
        if played:
            _log_engine("kokoro", "ok", text)
            return "kokoro"
    data = text.encode("utf-8")
    # 1) Piper (cross-platform neural) if a voice model is present
    piper = shutil.which("piper")
    voice = _find_piper_voice(cfg)
    if piper and voice:
        try:
            subprocess.run([piper, "-m", voice, "-f", str(TMP_WAV)], input=data,
                           stdout=DEVNULL, stderr=DEVNULL, creationflags=CREATE_NO_WINDOW)
            if TMP_WAV.exists() and _play_wav(TMP_WAV):
                _log_engine("piper", "kokoro unavailable", text)
                return "piper"
        except Exception:
            pass
    # 2) macOS native (reads stdin when given no text argument)
    if sys.platform == "darwin" and shutil.which("say"):
        try:
            subprocess.run(["say"], input=data, stdout=DEVNULL, stderr=DEVNULL)
            _log_engine("say", "kokoro unavailable", text)
            return "say"
        except Exception:
            pass
    # 3) Windows SAPI via PowerShell (text via stdin to dodge quoting) -- the "robotic" fallback
    if IS_WIN:
        try:
            rate = int(cfg.get("rate", 1))
        except (TypeError, ValueError):
            rate = 1
        ps = ("Add-Type -AssemblyName System.Speech;"
              "$s=New-Object System.Speech.Synthesis.SpeechSynthesizer;"
              f"$s.Rate={rate};"
              "$s.Speak([Console]::In.ReadToEnd())")
        try:
            subprocess.run(["powershell", "-NoProfile", "-Command", ps], input=data,
                           stdout=DEVNULL, stderr=DEVNULL, creationflags=CREATE_NO_WINDOW)
            _log_engine("sapi", "ROBOTIC FALLBACK - " + _kokoro_why(), text)
            return "sapi"
        except Exception:
            pass
    # 4) Linux espeak (--stdin: read the text from standard input)
    for e in ("espeak-ng", "espeak"):
        if shutil.which(e):
            try:
                subprocess.run([e, "--stdin"], input=data, stdout=DEVNULL, stderr=DEVNULL)
                _log_engine(e, "kokoro unavailable", text)
                return e
            except Exception:
                pass
    _log_engine("none", "no tts engine found", text)
    return None


# --------------------------------------------------------------------------- cli
def parse(args):
    out, i = {}, 0
    while i < len(args):
        if args[i].startswith("--"):
            key = args[i][2:]
            val = args[i + 1] if i + 1 < len(args) and not args[i + 1].startswith("--") else "true"
            out[key] = val
            i += 2 if val != "true" else 1
        else:
            i += 1
    return out


def main(argv):
    if not argv or argv[0].lower() != "say":
        print('usage: dj.py say [--text "<line>" | --file <path>]   (or pipe the text on stdin)')
        return
    opt = parse(argv[1:])
    text = opt.get("text", "")
    if text == "true":                     # bare --text with no value
        text = ""
    if not text and opt.get("file"):
        try:
            text = Path(opt["file"]).read_text(encoding="utf-8").strip()
        except Exception:
            text = ""
    if not text:
        try:
            text = sys.stdin.read().strip()
        except Exception:
            text = ""
    if not text:
        return
    print(f"DJ> {text}")
    if not speak(text, dj_config()):
        print("(no TTS engine found - install kokoro-onnx + soundfile, piper, or espeak)")


if __name__ == "__main__":
    main(sys.argv[1:])
