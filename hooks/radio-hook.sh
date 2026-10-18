#!/bin/sh
# Usage: radio-hook.sh SessionStart|Stop
#
# The terminal-fm plugin's hook launcher (hooks/hooks.json). Finds a working Python and runs
# `radio.py hook <event>` with this script's stdin passed straight through, so the hook's JSON
# reaches radio.py on stdin and never on a command line. radio.py's output is discarded and the
# exit status is always 0, so a radio error never disturbs the Claude Code session. The one thing
# it prints: at SessionStart with no Python 3.8+, a JSON note telling the user (systemMessage) and
# Claude (additionalContext) how to install it, so the first /tfm needn't hunt for one.
#
# Interpreter: python3, then python, then py (Windows launcher). Each candidate is probed with
# stdin from /dev/null so the probe can't eat the hook's JSON; a Windows Store "python3" alias
# fails the probe and is skipped. The probe prints the interpreter's own path, or on Windows the
# pythonw.exe beside it when there is one (no console window). On Windows the first candidate
# that has a pythonw.exe wins; with none, the first one that ran at all is used.
# RADIO_HOOK_PYTHONS replaces the candidate list; the tests use it to simulate a machine with none.
event=$1
case "$event" in
  SessionStart|Stop) ;;
  *) exit 0 ;;
esac
radio="$(dirname -- "$0")/../radio.py"
[ -f "$radio" ] || exit 0
probe='import os, sys
if sys.version_info < (3, 8): sys.exit(1)
e = sys.executable
w = os.path.join(os.path.dirname(e), "pythonw.exe")
sys.stdout.write((w if os.name == "nt" and os.path.isfile(w) else e).replace("\\", "/"))'
py=
for candidate in ${RADIO_HOOK_PYTHONS:-python3 python py}; do
  if found=$("$candidate" -c "$probe" 2>/dev/null </dev/null) && [ -n "$found" ]; then
    [ -n "$py" ] || py=$found
    case "$found" in
      *.exe) case "$found" in */pythonw.exe) py=$found; break ;; esac ;;
      *) break ;;                       # not Windows: the first working interpreter is it
    esac
  fi
done
if [ -z "$py" ]; then
  [ "$event" = SessionStart ] || exit 0
  how='Windows: winget install Python.Python.3.12 | macOS: brew install python | Linux: sudo apt install python3'
  printf '{"systemMessage": "Terminal FM: no Python 3.8 or newer found (tried python3, python, py), so the radio cannot run yet. Install it (%s), restart Claude Code, then run /tfm setup.", "hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": "The terminal-fm plugin found no Python 3.8+ on this machine (it tried python3, python and py), so /tfm commands cannot run. If the user asks for the radio, do not search the disk for Python: tell them to install it (%s), restart Claude Code, then run /tfm setup."}}\n' "$how" "$how"
  exit 0
fi
"$py" "$radio" hook "$event" >/dev/null 2>&1
exit 0
