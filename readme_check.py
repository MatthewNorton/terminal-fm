#!/usr/bin/env python3
"""
README guard for AI Radio. README.md is the source of truth for how the radio behaves; this
script keeps that true. Stdlib-only, like the rest of the core.

Layer 1 - mechanical drift. Facts are pulled from the code with `ast` (nothing is imported, so
running this has no side effects) and each one must appear in README.md:
  * every radio.py subcommand and alias, and every keyword a command compares its input to
  * every command has its own `### ` heading in the full reference
  * the config shape and defaults (radio.py DEFAULT_CONFIG + dj.py DJ_DEFAULTS) equal README's
    ```json block, key for key and value for value
  * every file/folder name the code builds with `/` under ~/.claude/radio
  * dj.py subcommands and --flags, kokoro_tts.py --flags
  * the player search order, the enhancer's duration bounds, the User-Agent, the source names
  * every radio.py command is reachable from the /radio skill (skills/radio/SKILL.md beside
    this file, the copy the plugin ships)

Layer 2 - review stamp. Layer 1 cannot read meaning: a changed behaviour or a new default in
prose passes it. So any change to a watched file stays "unreviewed" until README has been
brought up to date and `--confirm` records a snapshot of the code. `--diff` shows exactly what
changed since that snapshot, which is what the README review has to cover.

Usage (the workflow is in AGENTS.md):
  readme_check.py              both layers; exit 1 on drift or unreviewed code changes
  readme_check.py --diff       unified diff of the watched code since the last --confirm
  readme_check.py --confirm    layer 1 must pass; then snapshot the code as reviewed
"""

import ast
import difflib
import json
import re
import shutil
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
README = HERE / "README.md"
SKILL = HERE / "skills" / "radio" / "SKILL.md"       # the plugin's skill, in this repo
WATCHED = ("radio.py", "dj.py", "kokoro_tts.py", "readme_check.py")
SYNC_DIR = HERE / ".readme_sync"
SNAP_DIR = SYNC_DIR / "snapshot"          # copies of WATCHED as of the last --confirm
CONFIRM_LOG = SYNC_DIR / "confirm.log"
SELF = f'python "{HERE / "readme_check.py"}"'

# Names that hold user input inside cmd_* / main. A string compared against one of these is a
# keyword the CLI accepts, so README has to mention it.
INPUT_NAMES = {"args", "sub", "arg", "target", "event", "cmd", "argv", "slot", "rest", "nums"}


# --------------------------------------------------------------------------- code facts
def _tree(name):
    return ast.parse((HERE / name).read_text(encoding="utf-8"), filename=name)


def _module_literals(tree):
    """Module-level NAME = <literal> (and A, B = 1, 2) assignments."""
    out = {}
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        for t in node.targets:
            pairs = [(t, node.value)]
            if isinstance(t, ast.Tuple) and isinstance(node.value, ast.Tuple):
                pairs = list(zip(t.elts, node.value.elts))
            for name, val in pairs:
                if isinstance(name, ast.Name):
                    try:
                        out[name.id] = ast.literal_eval(val)
                    except (ValueError, TypeError, SyntaxError):
                        pass
    return out


def _assigned(tree, name, kind):
    """The value node of the module-level `name = <kind node>`, or None."""
    for node in tree.body:
        if (isinstance(node, ast.Assign) and isinstance(node.value, kind)
                and any(isinstance(t, ast.Name) and t.id == name for t in node.targets)):
            return node.value
    return None


def _commands(tree):
    """COMMANDS = {"key": handler, ...} -> {key: handler_name}."""
    node = _assigned(tree, "COMMANDS", ast.Dict)
    if node is None:
        return {}
    return {k.value: getattr(v, "id", None) for k, v in zip(node.keys, node.values)
            if isinstance(k, ast.Constant)}


def _keys_for(cmds, handler):
    """Every COMMANDS key (name, alias, short key) that runs `handler`, in table order."""
    return [k for k, h in cmds.items() if h == handler]


def _is_input(node):
    if isinstance(node, ast.Name):
        return node.id in INPUT_NAMES
    if isinstance(node, ast.Subscript):
        return _is_input(node.value)
    if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
            and node.func.attr in ("lower", "strip")):
        return _is_input(node.func.value)
    return False


def _str_consts(node):
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return [node.value]
    if isinstance(node, (ast.Tuple, ast.List, ast.Set)):
        return [e.value for e in node.elts
                if isinstance(e, ast.Constant) and isinstance(e.value, str)]
    return []


def _keywords(tree, want):
    """{keyword: {functions}} for every string a matching function compares its input against."""
    out = {}
    for fn in ast.walk(tree):
        if not (isinstance(fn, ast.FunctionDef) and want(fn.name)):
            continue
        for node in ast.walk(fn):
            if not isinstance(node, ast.Compare):
                continue
            ops = [node.left] + node.comparators
            if any(_is_input(o) for o in ops):
                for o in ops:
                    if not _is_input(o):
                        for s in _str_consts(o):
                            out.setdefault(s, set()).add(fn.name)
    return out


def _path_names(tree):
    """Every string literal on the right of a `/` path join (state files, folders)."""
    return {n.right.value for n in ast.walk(tree)
            if isinstance(n, ast.BinOp) and isinstance(n.op, ast.Div)
            and isinstance(n.right, ast.Constant) and isinstance(n.right.value, str)}


def _players(tree):
    for fn in ast.walk(tree):
        if isinstance(fn, ast.FunctionDef) and fn.name == "_players":
            for node in ast.walk(fn):
                if isinstance(node, ast.Return) and isinstance(node.value, ast.List):
                    return [e.elts[0].value for e in node.value.elts
                            if isinstance(e, ast.Tuple) and isinstance(e.elts[0], ast.Constant)]
    return []


def _opt_keys(tree):
    """Option names dj.py main() reads: opt.get("x") / opt["x"] -> --x."""
    keys = set()
    for fn in tree.body:
        if not (isinstance(fn, ast.FunctionDef) and fn.name == "main"):
            continue
        for node in ast.walk(fn):
            if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                    and node.func.attr == "get" and isinstance(node.func.value, ast.Name)
                    and node.func.value.id == "opt" and node.args
                    and isinstance(node.args[0], ast.Constant)):
                keys.add(node.args[0].value)
            if isinstance(node, ast.Subscript) and isinstance(node.value, ast.Name) \
                    and node.value.id == "opt":
                sl = node.slice
                if hasattr(ast, "Index") and isinstance(sl, getattr(ast, "Index")):
                    sl = sl.value                      # Python 3.8 wraps subscripts
                if isinstance(sl, ast.Constant) and isinstance(sl.value, str):
                    keys.add(sl.value)
    return keys


def _argparse_flags(tree):
    return {n.args[0].value for n in ast.walk(tree)
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
            and n.func.attr == "add_argument" and n.args
            and isinstance(n.args[0], ast.Constant)}


def _dur_rules(tree, literals):
    """DUR_RULES = [(secs, ("word", ...)), ...] -> [(secs, [words])], secs resolved via literals."""
    node = _assigned(tree, "DUR_RULES", ast.List)
    if node is None:
        return []
    out = []
    for e in node.elts:
        if isinstance(e, ast.Tuple) and len(e.elts) == 2:
            s = e.elts[0]
            secs = s.value if isinstance(s, ast.Constant) else literals.get(getattr(s, "id", ""))
            out.append((secs, _str_consts(e.elts[1])))
    return out


def _all_strings(trees):
    return {n.value for t in trees for n in ast.walk(t)
            if isinstance(n, ast.Constant) and isinstance(n.value, str)}


def _source_names(text):
    """SOURCES keys; an entry commented out with `#` counts too, so a planned source can be
    documented before it is enabled."""
    m = re.search(r"^SOURCES\s*=\s*\{(.*?)^\}", text, re.S | re.M)
    return re.findall(r'^\s*#?\s*"([\w-]+)"\s*:', m.group(1), re.M) if m else []


# --------------------------------------------------------------------------- README facts
def _code_tokens(text):
    """Lowercased words that appear inside `inline code` or fenced blocks."""
    spans = re.findall(r"```[^\n]*\n(.*?)```", text, re.S)
    spans += re.findall(r"`([^`\n]+)`", re.sub(r"```.*?```", " ", text, flags=re.S))
    toks = set()
    for s in spans:
        toks.update(t.lower() for t in re.split(r"[\s\[\]()|,/\"'<>=:;{}…]+", s) if t)
    return toks


def _heading_tokens(text):
    toks = set()
    for line in text.splitlines():
        if line.startswith("### "):
            toks.update(_code_tokens(line))
    return toks


def _readme_config(text):
    for m in re.finditer(r"```json\s*\n(.*?)```", text, re.S):
        try:
            obj = json.loads(m.group(1))
        except ValueError:
            continue
        if isinstance(obj, dict) and "stability_api" in obj:
            return obj
    return None


def _flat(d, pre=""):
    out = {}
    for k, v in d.items():
        if isinstance(v, dict):
            out.update(_flat(v, f"{pre}{k}."))
        else:
            out[f"{pre}{k}"] = v
    return out


def _sections_for(text, keys):
    """Every `### ` section whose heading shows one of `keys` in code - the command's own docs."""
    want = {k.lower() for k in keys}
    return "\n".join(m.group(0) for m in re.finditer(r"^### .*?(?=^### |^## |\Z)", text, re.S | re.M)
                     if _code_tokens(m.group(0).splitlines()[0]) & want)


def _section(text, heading_prefix):
    m = re.search(rf"^{re.escape(heading_prefix)}.*?(?=^### |^## |\Z)", text, re.S | re.M)
    return m.group(0) if m else ""


# --------------------------------------------------------------------------- layer 1
def drift():
    """Mechanical README drift. Returns a list of human-readable problems (empty = clean)."""
    readme = README.read_text(encoding="utf-8")
    toks, heads = _code_tokens(readme), _heading_tokens(readme)
    radio_src = (HERE / "radio.py").read_text(encoding="utf-8")
    radio, dj, kok = _tree("radio.py"), _tree("dj.py"), _tree("kokoro_tts.py")
    rlit, dlit = _module_literals(radio), _module_literals(dj)
    probs = []

    cmds = _commands(radio)
    if not cmds:
        probs.append("[code] could not find COMMANDS in radio.py - update readme_check.py")
    for key in sorted(cmds):
        if key.lower() not in toks:
            probs.append(f"[commands] `{key}` ({cmds[key]}) is never shown in README code")
    for handler in sorted({h for h in cmds.values() if h}):
        keys = _keys_for(cmds, handler)
        if not any(k.lower() in heads for k in keys):
            probs.append(f"[reference] no `### ` heading documents {handler} ({' / '.join(keys)})")

    # A keyword must be shown in the section of every command that accepts it - matching it
    # anywhere in README would let `auto` pass on the strength of `"model": "auto"`.
    kw = _keywords(radio, lambda n: n.startswith("cmd_") or n == "main")
    for word in rlit.get("_ON_WORDS", ()) + rlit.get("_OFF_WORDS", ()):
        kw.setdefault(word, set()).update({"cmd_announce", "cmd_breaking"})
    for word, fns in sorted(kw.items()):
        for fn in sorted(fns):
            keys = _keys_for(cmds, fn)
            where = _sections_for(readme, keys) if keys else readme
            if word.lower() not in _code_tokens(where):
                place = f"the {' / '.join(keys)} section" if keys else "README code"
                probs.append(f"[keywords] `{word}` (accepted by {fn}) is never shown in {place}")

    expected = json.loads(json.dumps(rlit.get("DEFAULT_CONFIG", {})))
    for k, v in (dlit.get("DJ_DEFAULTS") or {}).items():
        dj_sec = expected.setdefault("dj", {})
        if k in dj_sec and dj_sec[k] != v:
            probs.append(f"[code] radio.py DEFAULT_CONFIG.dj.{k}={dj_sec[k]!r} but dj.py "
                         f"DJ_DEFAULTS.{k}={v!r}")
        dj_sec.setdefault(k, v)
    doc = _readme_config(readme)
    if doc is None:
        probs.append("[config] README has no ```json config block containing \"stability_api\"")
    else:
        want, have = _flat(expected), _flat(doc)
        known = _all_strings([radio, dj, kok])
        for k in sorted(want):
            if k not in have:
                probs.append(f"[config] `{k}` (default {want[k]!r}) missing from README's block")
            elif have[k] != want[k]:
                probs.append(f"[config] `{k}` is {have[k]!r} in README but {want[k]!r} in code")
        for k in sorted(set(have) - set(want)):
            placeholder = isinstance(have[k], str) and have[k].startswith("<")
            if not (placeholder and k.rsplit(".", 1)[-1] in known):
                probs.append(f"[config] README documents `{k}`, which the code doesn't define")

    names = _path_names(radio) | _path_names(dj) | _path_names(kok)
    for extra in (rlit.get("ARCHIVE_DIRNAME"),):
        if extra:
            names.add(extra)
    for n in sorted(names):
        if n not in readme:
            probs.append(f"[files] `{n}` (built by the code) is not mentioned in README")

    for word in sorted(_keywords(dj, lambda n: n == "main")):
        if word.lower() not in toks:
            probs.append(f"[dj.py] subcommand `{word}` is never shown in README code")
    for key in sorted(_opt_keys(dj)):
        if f"--{key}".lower() not in toks:
            probs.append(f"[dj.py] flag `--{key}` is never shown in README code")
    for flag in sorted(_argparse_flags(kok)):
        if flag.lower() not in toks:
            probs.append(f"[kokoro_tts.py] flag `{flag}` is never shown in README code")

    players = _players(radio)
    order_line = next((ln for ln in readme.splitlines() if "First found wins" in ln), "")
    pos = [order_line.find(f"`{p}`") for p in players]
    if not players:
        probs.append("[code] could not find _players() in radio.py - update readme_check.py")
    elif -1 in pos or pos != sorted(pos):
        probs.append(f"[players] README's 'First found wins' line must list "
                     f"{' > '.join(players)} in that order")

    lo, hi = rlit.get("ENH_DUR_MIN"), rlit.get("ENH_DUR_MAX")
    if lo and hi and not re.search(rf"(?<!\d){lo}\s*[–-]\s*{hi}(?!\d)", readme):
        probs.append(f"[enhance] README never states the {lo}-{hi}s recommendation range")
    ua = rlit.get("USER_AGENT")
    if ua and ua not in readme:
        probs.append(f"[network] User-Agent `{ua}` is not stated in README")
    gen_sec = _section(readme, "### `radio.py gen")
    dur = (rlit.get("DEFAULT_CONFIG") or {}).get("stability_api", {}).get("duration")
    if dur and f"{dur}s" not in gen_sec:
        probs.append(f"[gen] the gen reference never states the {dur}s fallback duration")
    # The auto-duration keyword rules: every word, the seconds each group maps to (written as
    # "`last-word` → **Ns**"), and the order the groups are checked in.
    firsts = []
    for secs, words in _dur_rules(radio, rlit):
        for w in words:
            if f"`{w}`" not in gen_sec:
                probs.append(f"[gen] DUR_RULES keyword `{w}` ({secs}s) is missing from the gen section")
        if words:
            m = re.search(rf"`{re.escape(words[-1])}`\s*→\s*\*\*(\d+)s\*\*", gen_sec)
            if not m or int(m.group(1)) != secs:
                probs.append(f"[gen] the DUR_RULES group ending `{words[-1]}` must read "
                             f"'`{words[-1]}` → **{secs}s**' in the gen section")
            firsts.append(gen_sec.find(f"`{words[0]}`"))
    if -1 not in firsts and firsts != sorted(firsts):
        probs.append("[gen] DUR_RULES groups are listed out of order (the code checks them in order)")
    for src in _source_names(radio_src):
        if src.lower() not in toks:
            probs.append(f"[sources] `{src}` (SOURCES in radio.py) is missing from README")

    if SKILL.exists():
        stoks = _code_tokens(SKILL.read_text(encoding="utf-8"))
        for handler in sorted({h for h in cmds.values() if h}):
            keys = _keys_for(cmds, handler)
            if not any(k.lower() in stoks for k in keys):
                probs.append(f"[skill] /radio SKILL.md never shows {handler} ({' / '.join(keys)})")
    return probs


# --------------------------------------------------------------------------- layer 2
def unreviewed():
    """Watched files whose content differs from the last --confirm snapshot."""
    out = []
    for n in WATCHED:
        cur, snap = HERE / n, SNAP_DIR / n
        if cur.exists() != snap.exists():
            out.append(n)
        elif cur.exists() and cur.read_bytes() != snap.read_bytes():
            out.append(n)
    return out


def show_diff():
    changed = unreviewed()
    if not changed:
        print("No code changes since README was last confirmed.")
        return
    for n in changed:
        old = (SNAP_DIR / n).read_text(encoding="utf-8").splitlines(keepends=True) \
            if (SNAP_DIR / n).exists() else []
        new = (HERE / n).read_text(encoding="utf-8").splitlines(keepends=True) \
            if (HERE / n).exists() else []
        sys.stdout.writelines(difflib.unified_diff(old, new, f"{n} (last confirmed)", f"{n} (now)"))


def confirm():
    probs = drift()
    if probs:
        print(f"Not confirmed - README still has {len(probs)} mechanical problem(s):")
        for p in probs:
            print(f"  - {p}")
        return 1
    changed = unreviewed()
    SNAP_DIR.mkdir(parents=True, exist_ok=True)
    for n in WATCHED:
        if (HERE / n).exists():
            shutil.copy2(HERE / n, SNAP_DIR / n)
        elif (SNAP_DIR / n).exists():
            (SNAP_DIR / n).unlink()
    stamp = time.strftime("%Y-%m-%d %H:%M:%S")
    with CONFIRM_LOG.open("a", encoding="utf-8") as fh:
        fh.write(f"{stamp}\tconfirmed\t{','.join(changed) or '-'}\n")
    print(f"Confirmed {stamp}: README matches the code"
          + (f" (reviewed changes in: {', '.join(changed)})." if changed else "."))
    return 0


def report():
    probs, changed = drift(), unreviewed()
    if probs:
        print(f"README drift (layer 1): {len(probs)} problem(s)")
        for p in probs:
            print(f"  - {p}")
    else:
        print("README drift (layer 1): none")
    if changed:
        print(f"Unreviewed code changes since the last confirm (layer 2): {', '.join(changed)}")
        print(f"  what changed:  {SELF} --diff")
        print(f"  once README covers it:  {SELF} --confirm")
    else:
        print("Unreviewed code changes (layer 2): none")
    return 1 if (probs or changed) else 0


def main(argv):
    # Problems quote README text (→, …); a Windows pipe defaults to cp1252 and would crash on it.
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    if argv[:1] == ["--diff"]:
        show_diff()
        return 0
    if argv[:1] == ["--confirm"]:
        return confirm()
    if argv:
        print(__doc__)
        return 2
    return report()


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
