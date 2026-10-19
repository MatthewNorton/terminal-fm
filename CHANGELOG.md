# Changelog

All notable changes to Terminal FM (called AI Radio before 1.0.0) are documented here. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project uses [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Fixed

- `setup voice` and README's DJ voice steps now say the voice's Python packages need Python 3.13 or older, and how to give the voice its own Python 3.13 on a newer one (`py -3.13` on Windows, then `dj.python` in `config.json`). Every kokoro-onnx release since 0.4.8 requires a Python older than 3.14, so on 3.14 `pip install -U kokoro-onnx soundfile` quietly installed 0.4.7, too old for the voice, and README had told Python 3.15 users to use a 3.14 instead.

### Security

- `radio key` keeps the key file owner-only (`0600` on POSIX) when the rename of its temp file is refused. That fallback used to rewrite the key through the general file writer, which creates files with the default permissions (readable by other users under a typical umask), and only restricted it afterwards.
- `radio key show` says whether a key is set and where it came from, and no longer prints the key's first 6 characters.

## [1.1.0] - 2026-10-19

The first public release.

### Added

- An `examples/` folder: a 67-second demo video with sound, a track made with `/tfm eg lofi hip hop`, and a DJ line in the Kokoro voice. The README plays the video at the top and links the rest.

### Changed

- The data folder is now `~/.claude/terminal-fm` (was `~/.claude/radio`), and the variable that moves it is `TERMINAL_FM_HOME` (was `AI_RADIO_HOME`). To keep your library, key and settings, move the old folder before you update: close Claude Code, then rename `~/.claude/radio` to `~/.claude/terminal-fm`.
- Terminal FM needs Python 3.11 or newer (was 3.8), because 3.8, 3.9 and 3.10 no longer get security fixes. On an older Python, `setup` shows installing a newer one as a step, `status` lists it, and the session hook asks for 3.11 or newer. The install commands name Python 3.14.
- `setup` is a step-by-step wizard: a checklist of the required steps, then only the next one spelled out, with any command on a line of its own. Run it again after each step.
- `setup statusline`, `setup voice`, `setup enhancer` and `setup tokens` print the steps for each optional extra, with your own paths, and say whether it is installed.
- Every "no API key" message (`gen`, `key show`, `key` without a terminal) gives the same numbered steps, with the `key` command on a line of its own.
- `README.md` is reorganized: one command section with a table per group, the extras with step-by-step instructions, troubleshooting as a table at the end, and the internal details folded away.

## [1.0.0] - 2026-10-18

The first release, made while the repository was still private.

Builds before 1.0.0 were never published, and were called AI Radio (plugin `ai-radio`). The Changed, Removed and Fixed entries describe how 1.0.0 differs from them, for anyone who ran one.

### Added

- Claude Code plugin packaging: the repo is the `terminal-fm` plugin (`.claude-plugin/plugin.json`, version 1.0.0) and its own one-plugin marketplace, `digitalbyte` (`.claude-plugin/marketplace.json`, `"source": "./"`). Install with `claude plugin marketplace add MatthewNorton/terminal-fm` and `claude plugin install terminal-fm@digitalbyte`. The plugin and marketplace descriptions name the requirements: Python 3.8+, mpv or FFmpeg (built in on macOS) and a Stability AI API key.
- The skill ships in the repo as `skills/tfm/SKILL.md` and is invoked as `/tfm` (in full, `/terminal-fm:tfm`); it runs `python3` on macOS and Linux and `python`, then `py`, on Windows, on the `radio.py` inside the plugin, and when no Python runs it gives the install command instead of searching the disk. Name a genre instead of a command, and `/tfm smooth jazz` plays the tracks in your library that fit, and offers `egen` (which spends credits) when none do.
- `hooks/hooks.json`: the `SessionStart` hook (on `startup` and `resume`, in the foreground) and the async `Stop` hook run through `hooks/radio-hook.sh`, which finds a working `python3`, `python` or `py` (preferring a `pythonw.exe` on Windows, so no console window opens), passes the hook's JSON through on stdin, discards output and always exits 0. With no Python 3.8+ at session start it hands Claude Code a note with the install command, for the user (`systemMessage`) and for Claude (`additionalContext`), and running in the foreground gets that note to Claude before its first reply.
- `radio setup` (short key `se`): a read-only checklist of Python, the audio player, the API key, the session hooks, the library and the statusline, each `ok` or `NEEDED` with the exact fix, then the optional extras. `status` adds a `setup :` line when the player, the key or any tracks are missing.
- Every "no API key" message, and `radio key` run without a terminal, prints the exact command to paste into your own terminal, with this install's Python and `radio.py` paths; `play` with no audio player prints the install command for your OS.
- `statusline.py`: a stdlib statusline segment that prints the now-playing track from `<data dir>/nowplaying.txt` and honours `AI_RADIO_HOME`. The `SessionStart` hook copies it into the data directory, so a `statusLine` setting can point at a path that survives plugin updates.
- `radio format mp3 | wav | wav+mp3` (alias `filetype`) chooses the file type `gen` saves. `wav+mp3` requests the WAV once (billed once), keeps it in `<library>/_wav/` out of rotation, and encodes a 128 kbps MP3 with `ffmpeg` into the library; it is refused without `ffmpeg`, and a failed encode moves the WAV into the library so the track still plays.
- One- and two-letter short keys for most commands (`p` play, `pa` pause, `s` stop, `n` / `sk` skip, `g` gen, `e` enhance, `eg` egen, and the rest listed in README's command table).
- Unit tests and a GitHub Actions matrix, with Dependabot keeping the Actions current, and a bug-report issue template.
- `LICENSE` (MIT, Copyright (c) 2026 Matt Norton), `THIRD_PARTY_NOTICES.md` with download and license details for every optional component, `SECURITY.md` and this changelog.
- `.gitignore` covering every runtime file (`.key`, `config.json`, state, queue, logs, history, playlists, scratch WAVs, `output/`, downloaded models and the T5Gemma tokenizer) and a `config.example.json` to copy from.
- `release_check.py`: a stdlib pre-push gate that fails on a home-directory path, a personal email address, an `sk-` key pattern, any string from an untracked `.release_markers` list (also when split into adjacent string literals), any file over 5 MB, or a staged runtime file.
- `AI_RADIO_HOME` environment variable: the data directory (state, config, key, library, models, queue, logs) can live apart from the code, which resolves next to the scripts. Default stays `~/.claude/radio`.
- `radio key` subcommand: stores the Stability API key read without echo (never on the command line or in shell history), `0600` on POSIX; `radio key show` prints a masked prefix and whether `STABILITY_API_KEY` is set; `radio key clear` removes it.
- `gen` asks for confirmation above 20 tracks.

### Changed

- Renamed from AI Radio to **Terminal FM**. The plugin is `terminal-fm` and the command `/tfm`. If you installed a pre-release `ai-radio` plugin, run `claude plugin uninstall ai-radio@digitalbyte` first, or both plugins' hooks run; on a manual install, replace `~/.claude/skills/radio/` with a copy of `skills/tfm/`. The library, key and settings stay in `~/.claude/radio` (or `AI_RADIO_HOME`), so nothing moves. The statusline, `status` and `setup` say `Terminal FM`, and requests send `User-Agent: terminal-fm/1.0`.
- `prompts/enhance.md` is read from the data directory first (`<data dir>/prompts/enhance.md`), falling back to the copy shipped beside `radio.py`, because a plugin update replaces the plugin's folder and would lose a prompt tuned there.
- The `Stop` hook takes Claude's last message from the `last_assistant_message` field of its input and opens the session transcript at `transcript_path` only when that field is absent (older Claude Code versions).
- `CLAUDE.md` moved to `.claude/CLAUDE.md`, because `claude plugin validate --strict` rejects one at the plugin root; it imports `../AGENTS.md` and is trimmed to architecture, cross-file mechanics and gotchas.
- `README.md` is a step-by-step guide: a "Before you start" table with a check and an install command per OS (including Git for Windows, which the hooks need on Windows), five install steps built around `setup`, one command table and a shorter reference. It works with none of the optional downloads, and implementation notes are in `.claude/CLAUDE.md`; `readme_check.py` checks the in-repo skill.
- `cmd_folder` creates the directory first and saves it to `config.json` only on success.
- All JSON state files (`state.json`, `config.json`, `playlist.json`, `last_list.json`, `last_archive.json`, `resume.json`) are written atomically through a temp file and `os.replace`; `set_config` refuses to overwrite a config it cannot read instead of replacing it with `{}`.
- `pause` requires a live player, mirroring `skip`; otherwise it stops without writing a resume point and says why.
- The unknown-command message is built from the command table, and `play` uses a shared flag parser that refuses a `--` value.
- `README.md` documents what the `Stop` hook reads and that `dj_engine.log` keeps the first 60 characters of every spoken line.
- `prompts/enhance.md` is revision 1.3: `enhance` and `egen` write a one-line caption in a fixed order (genre, instruments with how they're played, production, mood, key, BPM last) instead of a paragraph, with no scene words, artist names, negations or song-section wording. Against the v1.0 instruction it was derived from, over 29 test briefs, two samples each, the briefs passing every check went from 31 to 43 of 52, prompts with a negation from 27 to 0, and music prompts with a BPM from 4 to 25 of 38; the median rewrite went from 86 words to 30, and a rewrite from 20.4 s to 14.8 s.
- `enhance` and `egen` strip any label the model writes (`Tag:`, `TrackType:` and the like), keep a `TrackType:`, `Format:` or `Genre:` tag from your own idea at the front, and treat an answer that echoes the brief back as no prompt.
- The clip-length hint sent with each idea gives a clip of 20 seconds or less fewer parts instead of asking the model to "pace the description".

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
- `play 3,5 --say "..."` ignored the track selection and played the whole library, because the sign-on text was counted as part of the selection. It now plays the selection, with the sign-on first.
- With an empty library the statusline showed "no tracks" in the playing colour, because the message's `"<prompt>"` holds the `>` that marks a playing track.

### Security

- `radio key` creates the key file owner-only (`0600` on POSIX) from the moment it exists, instead of writing it with the default permissions and restricting it afterwards.
- The `curl` fallback transport no longer places the API key on the command line (the Authorization header is supplied through a config read from stdin, `-K -`) and uses `--form-string` so a field value starting with `@` or `<` cannot make curl read a local file.
- No API key ships in the repository: the key lives in `<data dir>/.key` or `STABILITY_API_KEY`, and `release_check.py` refuses an `sk-` key pattern.
