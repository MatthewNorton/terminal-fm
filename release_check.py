#!/usr/bin/env python3
"""Pre-release gate for the Terminal FM tree: nothing personal, secret or huge may ship.

Usage:
    python release_check.py            # check every file that would ship
    python release_check.py --staged   # check only files staged in git (pre-commit hook)
    python release_check.py --root D   # check a different checkout (default: this file's folder)
    python release_check.py --markers F  # read the local marker list from F

Which files count as "shipping":
  * When this folder is the top level of a git repository, the set is `git ls-files` plus
    anything staged (`git diff --cached --name-only`), so a forced `git add` of an ignored
    runtime file is caught.
  * Otherwise (no repo, or the folder sits inside a larger repo that ignores it) the folder
    is walked and the IGNORED patterns below, mirroring .gitignore, decide what is skipped.
  * `--staged` needs the git repository and checks only the staged set.

Each shipped file fails the check when:
  * a line holds an absolute home-directory path (a `<you>`, `%VAR%` or `$VAR` placeholder
    after `Users/` or `home/` is fine), an address at a personal mail provider, an `sk-...`
    API key pattern, or one of the local markers, either as written or with adjacent string
    literals joined (`"ab" + "cd"` reads as `abcd`); the location is printed as
    `path:line: <pattern-name>`. Not seen: text split across lines, reversed or encoded;
    reading the files is the only check for those;
  * it is larger than 5 MB;
  * its path matches an IGNORED pattern (a runtime or personal file that was force-added).
Files with a NUL byte in their first 8 KB are treated as binary: size-checked, not scanned.

Local markers are the exact strings that identify you (a username, an email's local part, a
machine-specific folder). They live in `.release_markers`, one per line (blank lines and `#`
comments skipped), which .gitignore keeps out of the repo: a marker list inside a shipped file
publishes the very strings it guards. The file is read from `--markers`, else from the checked
folder, else from this file's folder. A hit is reported by its line number in that file, never
by its text, and the summary line says how many markers were loaded.

Exit status: 0 and `release_check: clean (N files, ...)` when nothing is flagged, 1 with one
line per finding otherwise, 2 for a usage or git error. Standard library only.

Pre-commit hook (`.git/hooks/pre-commit`):
    #!/bin/sh
    exec python release_check.py --staged
"""

import argparse
import fnmatch
import os
import re
import subprocess
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
MAX_BYTES = 5 * 1024 * 1024
SNIFF_BYTES = 8 * 1024
MARKERS_FILE = ".release_markers"

# Runtime, personal and downloaded files; keep in step with .gitignore. A trailing "/" marks
# a directory, a "/" inside anchors the pattern to the root, otherwise it matches any path part.
IGNORED = [
    ".key", "config.json", ".kokoro_python", "*.jsonl", "*.log", "state.json",
    "nowplaying.txt", "last_list.json", "last_archive.json",
    "resume.json", "playlist.json", "breaking.txt", "dj_speaking.lock", "queue/", "output/",
    "_dj*.wav", "__pycache__/", ".readme_sync/", MARKERS_FILE,
    "kokoro/*.onnx", "kokoro/*.bin", "llm/*.gguf", "llm/bin/", "llm/t5gemma-tokenizer.json",
]

# Patterns that name no one, so they can ship. A GitHub no-reply address is not a personal
# provider and passes.
PATTERNS = [
    ("home-path", re.compile(r"[A-Za-z]:[\\/]+Users[\\/]+(?![<%$])[^\\/\s\"'`<>]+", re.I)),
    ("home-path", re.compile(r"(?<![\w.~-])/(?:home|Users)/(?![<%$])[A-Za-z0-9._-]+")),
    ("personal-email", re.compile(
        r"[A-Za-z0-9._%+-]+@(?:gmail|googlemail|yahoo|hotmail|outlook|live|icloud|me|aol"
        r"|proton|protonmail|gmx)\.[A-Za-z.]+", re.I)),
    ("api-key:sk-", re.compile(r"sk-[A-Za-z0-9]{20,}")),
]

# A string split into literals ("ab" + "cd", or "ab" "cd") is matched joined too, so splitting a
# string can't hide it from this check.
JOIN_RE = re.compile(r"[\"']\s*\+?\s*[\"']")


def is_ignored(rel):
    """True when the forward-slash relative path matches an IGNORED pattern."""
    parts = rel.split("/")
    dirs = parts[:-1]
    for pat in IGNORED:
        if pat.endswith("/"):
            want = pat[:-1]
            if "/" in want:
                prefixes = ["/".join(dirs[:i + 1]) for i in range(len(dirs))]
                if any(fnmatch.fnmatchcase(p, want) for p in prefixes):
                    return True
            elif any(fnmatch.fnmatchcase(d, want) for d in dirs):
                return True
        elif "/" in pat:
            if fnmatch.fnmatchcase(rel, pat):
                return True
        elif any(fnmatch.fnmatchcase(p, pat) for p in parts):
            return True
    return False


def markers_path(root, given=None):
    """The local marker file to read: `given`, else the checked folder's, else this file's
    folder's; None when none of them exists."""
    if given:
        return given
    for folder in (root, ROOT):
        path = os.path.join(folder, MARKERS_FILE)
        if os.path.isfile(path):
            return path
    return None


def load_markers(path):
    """[(name, needle)] from a marker file: one literal per line, blank lines and # comments
    skipped. The name carries the line number, not the text."""
    if path is None:
        return []
    with open(path, encoding="utf-8") as fh:
        lines = fh.read().splitlines()
    return [("local-marker:%d" % n, line.strip()) for n, line in enumerate(lines, 1)
            if line.strip() and not line.strip().startswith("#")]


def _git(root, *args):
    proc = subprocess.run(["git", "-C", root] + list(args), capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or "git failed: " + " ".join(args))
    return proc.stdout


def git_toplevel(root):
    """The repo's top level when `root` is one, else None."""
    try:
        top = _git(root, "rev-parse", "--show-toplevel").strip()
    except (RuntimeError, OSError):
        return None
    if not top:
        return None
    if os.path.normcase(os.path.realpath(top)) != os.path.normcase(os.path.realpath(root)):
        return None
    return top


def _git_paths(root, *args):
    out = _git(root, *args, "-z")
    return [p for p in out.split("\0") if p]


def shipped_files(root, staged_only):
    """Relative forward-slash paths of the files to check, and how they were found."""
    top = git_toplevel(root)
    if staged_only:
        if top is None:
            raise RuntimeError("--staged needs this folder to be the top level of a git repo")
        rels = _git_paths(root, "diff", "--cached", "--name-only", "--diff-filter=ACMR")
        return sorted(set(rels)), "staged"
    if top is not None:
        tracked = _git_paths(root, "ls-files")
        staged = _git_paths(root, "diff", "--cached", "--name-only", "--diff-filter=ACMR")
        rels = sorted(set(tracked) | set(staged))
        return rels, "git"
    rels = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d != ".git"]
        for name in filenames:
            full = os.path.join(dirpath, name)
            rel = os.path.relpath(full, root).replace(os.sep, "/")
            if not is_ignored(rel):
                rels.append(rel)
    return sorted(rels), "walk"


def check_file(root, rel, markers=()):
    """Yield (line, pattern-name) findings for one file; line is 0 for whole-file findings.
    Each pattern name is reported at most once per line."""
    full = os.path.join(root, rel)
    if not os.path.isfile(full):
        return  # staged deletion or a path git knows that is gone from disk
    if is_ignored(rel):
        yield 0, "ignored-runtime-file"
    size = os.path.getsize(full)
    if size > MAX_BYTES:
        yield 0, "too-large:%.1fMB" % (size / (1024.0 * 1024.0))
    with open(full, "rb") as fh:
        head = fh.read(SNIFF_BYTES)
        if b"\0" in head:
            return
        data = head + fh.read()
    text = data.decode("utf-8", errors="replace")
    for lineno, line in enumerate(text.splitlines(), 1):
        names = []
        for form in dict.fromkeys((line, JOIN_RE.sub("", line))):
            names += [name for name, rx in PATTERNS if rx.search(form)]
            names += [name for name, needle in markers if needle in form]
        for name in dict.fromkeys(names):
            yield lineno, name


def main(argv=None):
    ap = argparse.ArgumentParser(description="Check the files that would ship in a release.")
    ap.add_argument("--staged", action="store_true", help="check only files staged in git")
    ap.add_argument("--root", default=ROOT, help="folder to check (default: this file's folder)")
    ap.add_argument("--markers", help="local marker file (default: " + MARKERS_FILE
                    + " in the checked folder, then beside this script)")
    args = ap.parse_args(argv)
    root = os.path.abspath(args.root)
    if not os.path.isdir(root):
        print("release_check: not a folder: " + root, file=sys.stderr)
        return 2
    try:
        markers = load_markers(markers_path(root, args.markers))
        rels, how = shipped_files(root, args.staged)
    except (RuntimeError, OSError) as exc:
        print("release_check: " + str(exc), file=sys.stderr)
        return 2
    loaded = ("%d local marker%s" % (len(markers), "" if len(markers) == 1 else "s")
              if markers else "no local markers")
    findings = 0
    bad_files = 0
    for rel in rels:
        hits = list(check_file(root, rel, markers))
        if hits:
            bad_files += 1
        for lineno, name in hits:
            findings += 1
            where = rel if lineno == 0 else "%s:%d" % (rel, lineno)
            print("%s: %s" % (where, name))
    if findings:
        print("release_check: FAIL (%d findings in %d of %d files, %s, %s)"
              % (findings, bad_files, len(rels), how, loaded))
        return 1
    print("release_check: clean (%d files, %s)" % (len(rels), loaded))
    return 0


if __name__ == "__main__":
    sys.exit(main())
