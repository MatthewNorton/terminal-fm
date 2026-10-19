#!/usr/bin/env python3
"""Terminal FM statusline segment. Stdlib only.

Prints one line for Claude Code's statusLine: what the radio is playing, read from
<data dir>/nowplaying.txt, where the data dir is $TERMINAL_FM_HOME or ~/.claude/terminal-fm.

  ♪ Terminal FM > <track>     magenta: playing (radio.py writes a `>` only while a track plays)
  · Terminal FM | stopped     gray: every other state

Prints nothing when the file is missing or empty. Set NO_COLOR to drop the colour codes.
Claude Code passes session JSON on stdin; this script doesn't need it and doesn't read it.

The terminal-fm plugin's SessionStart hook copies this file into the data directory, so a
settings.json statusLine can point at ~/.claude/terminal-fm/statusline.py and survive plugin updates:

  "statusLine": {"type": "command", "command": "python ~/.claude/terminal-fm/statusline.py"}
"""

import os
import sys
from pathlib import Path

MAGENTA, GRAY, RESET = "\x1b[35m", "\x1b[90m", "\x1b[0m"


def data_dir():
    return Path(os.path.expanduser(os.environ.get("TERMINAL_FM_HOME", "").strip()
                                   or str(Path.home() / ".claude" / "terminal-fm")))


def segment():
    """The text to print, or "" when there is nothing to show."""
    try:
        text = (data_dir() / "nowplaying.txt").read_text(encoding="utf-8").strip()
    except (OSError, UnicodeDecodeError):
        return ""
    if not text:
        return ""
    text = " ".join(text.split())                 # one line, whatever the file holds
    playing = ">" in text                         # the coupling radio.py's write_now() keeps
    line = ("♪ " if playing else "· ") + text
    if os.environ.get("NO_COLOR"):
        return line
    return (MAGENTA if playing else GRAY) + line + RESET


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")   # ♪ is not in cp1252
    except (AttributeError, ValueError):
        pass
    out = segment()
    if out:
        print(out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
