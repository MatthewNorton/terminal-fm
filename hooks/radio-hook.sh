#!/bin/sh
# Usage: radio-hook.sh SessionStart|Stop
#
# The ai-radio plugin's hook launcher (hooks/hooks.json). Finds a working Python and runs
# `radio.py hook <event>` with this script's stdin passed straight through, so the hook's JSON
# reaches radio.py on stdin and never on a command line. Output is discarded and the exit status
# is always 0: a missing Python or a radio error must never disturb the Claude Code session.
#
# Interpreter: python3, then python, then py (Windows launcher). Each candidate is probed with
# stdin from /dev/null so the probe can't eat the hook's JSON; a Windows Store "python3" alias
# fails the probe and is skipped. The probe prints the interpreter's own path, or on Windows the
# pythonw.exe beside it when there is one (no console window). On Windows the first candidate
# that has a pythonw.exe wins; with none, the first one that ran at all is used.
event=$1
case "$event" in
  SessionStart|Stop) ;;
  *) exit 0 ;;
esac
radio="$(dirname -- "$0")/../radio.py"
[ -f "$radio" ] || exit 0
probe='import os, sys
e = sys.executable
w = os.path.join(os.path.dirname(e), "pythonw.exe")
sys.stdout.write((w if os.name == "nt" and os.path.isfile(w) else e).replace("\\", "/"))'
py=
for candidate in python3 python py; do
  if found=$("$candidate" -c "$probe" 2>/dev/null </dev/null) && [ -n "$found" ]; then
    [ -n "$py" ] || py=$found
    case "$found" in
      *.exe) case "$found" in */pythonw.exe) py=$found; break ;; esac ;;
      *) break ;;                       # not Windows: the first working interpreter is it
    esac
  fi
done
[ -n "$py" ] || exit 0
"$py" "$radio" hook "$event" >/dev/null 2>&1
exit 0
