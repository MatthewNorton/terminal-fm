#!/usr/bin/env python3
"""Smoke test for Terminal FM: run the read-mostly subcommands as real subprocesses against a
throwaway data directory and check each exits 0 with sane output.

    python smoke_test.py

Every run gets a fresh temporary AI_RADIO_HOME, so the real data directory (~/.claude/radio by
default: state, config, key, queue, library) is never read or written, and nothing is played,
generated or spent. Stdlib only. Exit status 0 when every check passes, 1 otherwise.
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
RADIO = HERE / "radio.py"
FAILS = []


def radio(home, *args):
    env = dict(os.environ)
    env["AI_RADIO_HOME"] = str(home)
    env.pop("STABILITY_API_KEY", None)
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    p = subprocess.run([sys.executable, str(RADIO)] + list(args), env=env, cwd=str(home),
                       stdin=subprocess.DEVNULL, capture_output=True, timeout=120,
                       creationflags=flags)
    out = p.stdout.decode("utf-8", "replace")
    err = p.stderr.decode("utf-8", "replace")
    return p.returncode, out, err


def check(label, home, args, must=(), must_not=(), stderr_has=None):
    code, out, err = radio(home, *args)
    problems = []
    if code != 0:
        problems.append(f"exit {code}")
    if "Traceback" in out or "Traceback" in err:
        problems.append("traceback")
    for text in must:
        if text not in out:
            problems.append(f"missing {text!r}")
    for text in must_not:
        if text in out:
            problems.append(f"unexpected {text!r}")
    if stderr_has is None and err.strip():
        problems.append("unexpected stderr")
    elif stderr_has is not None and stderr_has not in err:
        problems.append(f"stderr lacks {stderr_has!r}")
    status = "ok  " if not problems else "FAIL"
    print(f"{status} {label}: radio {' '.join(args) or '(no args)'}")
    if problems:
        FAILS.append(label)
        print(f"     {'; '.join(problems)}")
        for name, text in (("stdout", out), ("stderr", err)):
            for line in text.strip().splitlines()[:15]:
                print(f"     {name}| {line}")
    return out


def main():
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    base = Path(tempfile.mkdtemp(prefix="terminal-fm-smoke-")).resolve()
    try:
        # 1. A brand-new, empty data directory: what a first install sees.
        home = base / "fresh"
        home.mkdir()
        check("no args = status", home, [], ["Terminal FM status", "state   : stopped"])
        check("status", home, ["status"], ["Terminal FM status", "library : 0 track(s)",
                                            "mode    : shuffle", "queue   : 0 DJ line(s)"])
        check("list (empty)", home, ["list"], ["Library is empty"])
        check("folder", home, ["folder"], ["Library folder:", "(default)", "0 track(s)"])
        check("format", home, ["format"], ["Output format: mp3"])
        check("prompts (none)", home, ["prompts"], ["No prompt history yet"])
        check("unknown command", home, ["nonsense"], ["Unknown command 'nonsense'", "status"])
        for d in ("queue", "output"):
            if not (home / d).is_dir():
                FAILS.append(f"{d}/ not created in the temp home")
                print(f"FAIL AI_RADIO_HOME not honoured: {home / d} missing")

        # 2. A populated library, history with non-ASCII text, and settings changes.
        out_dir = home / "output"
        for name in ("alpha-track.mp3", "beta-track.wav", "notes.txt"):
            (out_dir / name).write_bytes(b"\0" * 16)
        recs = [{"ts": "2026-01-01 10:00:00", "prompt": "warm lofi for a café ☕ → night",
                 "duration": 150, "file": "alpha-track.mp3"},
                {"ts": "2026-01-02 10:00:00", "prompt": "rewritten only", "duration": 30,
                 "file": "", "kind": "enhance"}]
        (home / "prompt_history.jsonl").write_text(
            "\n".join(json.dumps(r, ensure_ascii=False) for r in recs) + "\nnot json\n", encoding="utf-8")
        check("list (2 tracks)", home, ["list"], ["Library (2 tracks)", "1.   alpha-track",
                                                   "2.   beta-track"], must_not=["notes"])
        check("prompts (history)", home, ["prompts"], ["Prompt history (2 entries)",
                                                        "café ☕ → night", "2.e"])
        check("prompts 1", home, ["prompts", "1"], ["Prompt #1", "(library)",
                                                     'radio gen "warm lofi for a café'])
        check("prompts search", home, ["prompts", "zzz-no-match"], ["No prompts matching"])
        check("format wav", home, ["format", "wav"], ["Output format: wav"])
        check("format (after set)", home, ["format"], ["Output format: wav"])
        check("format bogus", home, ["format", "flac"], ["Unknown format 'flac'"])
        check("folder <sub>", home, ["folder", "jazz"], ["Library folder set to:", "Empty"])
        check("folder (custom)", home, ["folder"], ["(custom)", "0 track(s)"])
        check("folder default", home, ["folder", "default"], ["Library folder set to:"])
        check("status after folder reset", home, ["status"], ["library : 2 track(s)"])

        # 3. Hostile state: a corrupt config.json and an uncreatable library folder.
        bad = base / "corrupt"
        bad.mkdir()
        (bad / "config.json").write_text("{broken", encoding="utf-8")
        check("status, corrupt config", bad, ["status"], ["Terminal FM status"])
        check("format wav, corrupt config", bad, ["format", "wav"], ["Not saved"])
        if (bad / "config.json").read_text(encoding="utf-8") != "{broken":
            FAILS.append("corrupt config.json was overwritten")
            print("FAIL corrupt config.json was overwritten")
        blocked = base / "blocked"
        blocked.mkdir()
        (blocked / "a-file").write_text("x", encoding="utf-8")
        (blocked / "config.json").write_text(json.dumps({"library_dir": "a-file/sub"}), encoding="utf-8")
        check("status, uncreatable library", blocked, ["status"], ["Terminal FM status"],
              stderr_has="cannot be created")
    finally:
        shutil.rmtree(str(base), ignore_errors=True)

    if FAILS:
        print(f"\nsmoke_test: FAIL ({len(FAILS)}): {', '.join(FAILS)}")
        return 1
    print("\nsmoke_test: all checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
