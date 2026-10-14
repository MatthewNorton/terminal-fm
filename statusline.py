#!/usr/bin/env python3
"""AI Radio statusline segment. Stdlib only, Python 3.8+.

Prints one line for Claude Code's statusLine: what the radio is playing, read from
<data dir>/nowplaying.txt, where the data dir is $AI_RADIO_HOME or ~/.claude/radio.

  ♪ AI Radio > <track>     magenta: playing (radio.py writes a `>` only while a track plays)
  · AI Radio | stopped     gray: every other state

Prints nothing when the file is missing or empty. Set NO_COLOR to drop the colour codes.
Claude Code passes session JSON on stdin; this script doesn't need it and doesn't read it.

The ai-radio plugin's SessionStart hook copies this file into the data directory, so a
settings.json statusLine can point at ~/.claude/radio/statusline.py and survive plugin updates:

  "statusLine": {"type": "command", "command": "python ~/.claude/radio/statusline.py"}
"""

import os
import sys
from pathlib import Path

MAGENTA, GRAY, RESET = "\x1b[35m", "\x1b[90m", "\x1b[0m"


def data_dir():
    return Path(os.path.expanduser(os.environ.get("AI_RADIO_HOME", "").strip()
                                   or str(Path.home() / ".claude" / "radio")))


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
