# Changelog

All notable changes to AI Radio are documented here. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project uses [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.0.0] - 2026-10-14

The first public release.

Builds before 1.0.0 were never published. The Changed, Removed and Fixed entries describe how 1.0.0 differs from them, for anyone who ran one from a clone.

### Added

- Claude Code plugin packaging: the repo is the `ai-radio` plugin (`.claude-plugin/plugin.json`, version 1.0.0) and its own one-plugin marketplace, `digitalbyte` (`.claude-plugin/marketplace.json`, `"source": "./"`). Install with `claude plugin marketplace add MatthewNorton/terminal-fm` and `claude plugin install ai-radio@digitalbyte`.
- The skill ships in the repo as `skills/radio/SKILL.md` and is invoked as `/ai-radio:radio`; it runs `python "${CLAUDE_PLUGIN_ROOT}/radio.py"`, so it works wherever the plugin is installed.
- `hooks/hooks.json`: the `SessionStart` (on `startup` and `resume`) and `Stop` hooks, both async, run through `hooks/radio-hook.sh`, which finds a working `python3`, `python` or `py` (preferring a `pythonw.exe` on Windows, so no console window opens), passes the hook's JSON through on stdin, discards output and always exits 0.
- `statusline.py`: a stdlib statusline segment that prints the now-playing track from `<data dir>/nowplaying.txt` and honours `AI_RADIO_HOME`. The `SessionStart` hook copies it into the data directory, so a `statusLine` setting can point at a path that survives plugin updates.
- `radio format mp3 | wav | wav+mp3` (alias `filetype`) chooses the file type `gen` saves. `wav+mp3` requests the WAV once (billed once), keeps it in `<library>/_wav/` out of rotation, and encodes a 128 kbps MP3 with `ffmpeg` into the library; it is refused without `ffmpeg`, and a failed encode moves the WAV into the library so the track still plays.
- One- and two-letter short keys for most commands (`p` play, `pa` pause, `s` stop, `n` / `sk` skip, `g` gen, `e` enhance, `eg` egen, and the rest listed in README's **Short keys**).
- Unit tests and a GitHub Actions matrix, with Dependabot keeping the Actions current, and a bug-report issue template.
- `LICENSE` (MIT, Copyright (c) 2026 Matt Norton), `THIRD_PARTY_NOTICES.md` with download and license details for every optional component, `SECURITY.md` and this changelog.
- `.gitignore` covering every runtime file (`.key`, `config.json`, state, queue, logs, history, playlists, scratch WAVs, `output/`, downloaded models and the T5Gemma tokenizer) and a `config.example.json` to copy from.
- `release_check.py`: a stdlib pre-push gate that fails on a home-directory path, a personal email address, an `sk-` key pattern, any string from an untracked `.release_markers` list (also when split into adjacent string literals), any file over 5 MB, or a staged runtime file.
- `AI_RADIO_HOME` environment variable: the data directory (state, config, key, library, models, queue, logs) can live apart from the code, which resolves next to the scripts. Default stays `~/.claude/radio`.
- `radio key` subcommand: stores the Stability API key read without echo (never on the command line or in shell history), `0600` on POSIX; `radio key show` prints a masked prefix and whether `STABILITY_API_KEY` is set; `radio key clear` removes it.
- `gen` asks for confirmation above 20 tracks.

### Changed

- `prompts/enhance.md` is read from the data directory first (`<data dir>/prompts/enhance.md`), falling back to the copy shipped beside `radio.py`, because a plugin update replaces the plugin's folder and would lose a prompt tuned there.
- The `Stop` hook takes Claude's last message from the `last_assistant_message` field of its input and opens the session transcript at `transcript_path` only when that field is absent (older Claude Code versions).
- `CLAUDE.md` moved to `.claude/CLAUDE.md`, because `claude plugin validate --strict` rejects one at the plugin root; it imports `../AGENTS.md` and is trimmed to architecture, cross-file mechanics and gotchas.
- `README.md` has an install section (plugin route first, then the optional model downloads, then the manual route) and works with none of the optional downloads; `readme_check.py` checks the in-repo skill.
- `cmd_folder` creates the directory first and saves it to `config.json` only on success.
- All JSON state files (`state.json`, `config.json`, `playlist.json`, `last_list.json`, `last_archive.json`, `resume.json`) are written atomically through a temp file and `os.replace`; `set_config` refuses to overwrite a config it cannot read instead of replacing it with `{}`.
- `pause` requires a live player, mirroring `skip`; otherwise it stops without writing a resume point and says why.
- The unknown-command message is built from the command table, and `play` uses a shared flag parser that refuses a `--` value.
- `README.md` documents what the `Stop` hook reads and that `dj_engine.log` keeps the first 60 characters of every spoken line.

### Removed

- The Ollama banter layer in `dj.py` (`intro`/`break`, model picking, `agent_context.txt`) and its config keys `dj.model`, `dj.station`, `dj.mode`, `dj.enabled`, `dj.intro_on_play`; `dj.py` is now `say` only.
- The `play --about` flag, the ignored `steps` argument to `gen`/`egen`, and the four commented-out future `SOURCES` entries.

### Fixed

- Import-time creation of the library folder is guarded: an invalid `library_dir` falls back to the default with a warning instead of crashing every command.
- `parse_selection` clamps ranges to the library size before expanding them, so `1-99999999999` returns immediately.
- Process checks match the exact pid (`tasklist /FO CSV` on Windows) and verify the recorded executable name before `kill()`, so a recycled pid is never killed.
- macOS `say` and `espeak` receive the text on stdin like the SAPI path, so a spoken line is never a command-line argument.
- `stop` and `pause` re-read `state.json` after killing the daemon and kill the player it names then (plus the first-read one if different and still running). A track that ended during the daemon kill used to leave the next track's player running with nothing tracking it; `pause` now takes its position from that re-read state.
- `gen` and `egen` with no API key print `Cost: 0 credits (nothing sent)` instead of `Cost: unknown`, which read as if a charge might have happened.
- `play --say` refuses (empty library, no player) before queueing its line, so a refused sign-on is no longer spoken by some later `play`.
- `dj_engine.log` says `ROBOTIC FALLBACK - kokoro not installed` when Kokoro was skipped for missing files, instead of blaming a render failure that never happened; the engine column is unchanged.
- `radio key show` with no key adds a line naming the next step: `radio key` in a terminal, or `STABILITY_API_KEY`.
- On macOS, `stop`, `pause`, `status` and the Stop hook no longer mistake a running radio for a stopped one when it runs under Homebrew's or Xcode's `python3`: the daemon records its program name as the OS reports it (`Python`), not as `python3.14`. Found on a GitHub macOS runner, where `stop` left the music playing.
- With `cvlc` as the player, `skip`, `pause` and `stop` reach it: `cvlc` is a wrapper that starts `vlc`, so the player is recorded under that name. Before, all three missed it and the track played on (found on a GitHub Linux runner).
- A `kokoro-fail` line in `dj_engine.log` shows the last line of the error (the exception) instead of the first 120 characters, which on Windows were onnxruntime warnings in UTF-16.
- `radio key` with no terminal (input piped or redirected) prints `No terminal to read the key from` instead of waiting forever on Windows.

### Security

- `radio key` creates the key file owner-only (`0600` on POSIX) from the moment it exists, instead of writing it with the default permissions and restricting it afterwards.
- The `curl` fallback transport no longer places the API key on the command line (the Authorization header is supplied through a config read from stdin, `-K -`) and uses `--form-string` so a field value starting with `@` or `<` cannot make curl read a local file.
- No API key ships in the repository: the key lives in `<data dir>/.key` or `STABILITY_API_KEY`, and `release_check.py` refuses an `sk-` key pattern.
