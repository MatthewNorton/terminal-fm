# AGENTS.md — Terminal FM

Rules for any agent changing this folder (Claude Code, Codex, or anything else). `.claude/CLAUDE.md` imports this file; architecture and gotchas live in `.claude/CLAUDE.md`, which is plain markdown worth reading whatever agent you are.

## README.md is the source of truth

`README.md` is the source of truth for how the radio behaves, and it must stay true. If the code and the README disagree, one of them is wrong: fix it in the same change, never leave them disagreeing.

**When you change `radio.py`, `dj.py`, `kokoro_tts.py` or `readme_check.py`, update `README.md` in the same change** if you added, removed or altered any of:

- a subcommand, an alias, or a keyword a command accepts (`clear`, `all`, `auto`, the on/off words, …)
- a flag (`play --say`, `dj.py --file`, `kokoro_tts.py --voice`, …)
- a config key or default value (README's `json` config block must equal the code's defaults exactly)
- a file or folder the code creates or reads under `~/.claude/radio`
- a default behaviour, number, limit, fallback, or message a user would notice
- anything an example in the README relies on (every example must run as written against the current grammar)

In the same change, also update:

- `skills/tfm/SKILL.md` (the plugin's skill) when a command is added or its usage changes, because that's how Claude maps natural language to commands.
- `CLAUDE.md` when internals change. `CLAUDE.md` covers internals and `README.md` covers behaviour, and the two must never contradict each other.

## Run the check — at the start and before you finish

```bash
python readme_check.py              # both layers must print "none"
python readme_check.py --diff       # the code changes README has to cover
python readme_check.py --confirm    # only after README.md reflects them
```

- **Start of a session:** run `python readme_check.py` before editing. "Unreviewed" there means someone changed the code without updating the README, whether by hand or from another session. Reconcile that first. In a fresh clone there is no snapshot yet (`.readme_sync/` is never committed), so every watched file shows as unreviewed: check that drift is none, then run `--confirm` once.
- **Layer 1, drift, is mechanical.** Facts pulled from the code (commands, keywords, config, files, flags, player order, duration rules, `/tfm` skill coverage) must appear in README. Fix README until it reports none. If the check itself is wrong, fix `readme_check.py`; that's a watched file, so document that change too.
- **Layer 2, unreviewed, lists code changed since the last `--confirm`.** A check can't read meaning, so this is how behaviour changes get caught. Read `--diff` and update README for anything a user would notice, then run `--confirm`. If a change has no user-visible effect, tell the user so and confirm.
- **Never run `--confirm` just to clear the warning without reading `--diff`.** `--confirm` refuses while any drift remains, and every confirm is logged in `.readme_sync/confirm.log`.
- **When you report back,** tell the user the README was updated and what the check printed.

## Other rules

- `radio.py`, `dj.py` and `readme_check.py` stay stdlib-only and cross-platform. Only `kokoro_tts.py` may import third-party packages.
- Don't hard-wrap prose in `.md` files: one line per paragraph or bullet.
- Other people or agent sessions may be editing the same files. Before a large edit, check whether a file changed under you, and coordinate rather than overwrite.
