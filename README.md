# 🎙️ AI Radio

A portable, continuous music player for the Claude CLI. A detached background daemon plays MP3 and WAV tracks from a local library **forever** — full-library shuffle, or an ordered playlist you pick by number. New tracks are generated on demand with **Stability AI** (Stable Audio 3), optionally from a rough idea that a local LLM rewrites into a proper music prompt; leave the length out and one is picked to suit the prompt. Between tracks a **neural DJ voice** (Kokoro-82M) reads the lines you queue, plus recaps of what Claude just finished.

The now-playing track shows up in the Claude Code statusline (`statusline.py`), and `Stop` / `SessionStart` hooks feed the DJ an update every time Claude finishes a turn. The radio installs as a Claude Code plugin, `ai-radio`, which ships the skill and both hooks; see **🚀 Install** below.

> **Core files** (`radio.py`, `dj.py`) are **stdlib-only and cross-platform** (Windows / macOS / Linux) — no `pip install`, no third-party imports. Only `kokoro_tts.py` needs packages (`kokoro-onnx`, `soundfile`), and it runs as an isolated subprocess. The prompt enhancer shells out to a `llama-cli` binary, so it adds no Python dependency either.

---

## 🚀 Install

You need **Python 3.8+** (`python3`, `python` or `py`), an **audio player** (`mpv`, or `ffplay` from FFmpeg; see **Requirements**), a **Stability API key** (from <https://platform.stability.ai>), and Claude Code. The plugin's hooks are shell commands, which Claude Code runs under Git Bash on Windows.

1. **Add the marketplace and install the plugin**, from a terminal:
   ```
   claude plugin marketplace add MatthewNorton/terminal-fm
   claude plugin install ai-radio@digitalbyte
   ```
2. **Start a new Claude Code session.** It loads the skill, `/ai-radio:radio`, and the two hooks. The first session start creates the data directory (`~/.claude/radio`, or the folder named by `AI_RADIO_HOME`) and copies `statusline.py` into it.
3. **Store your Stability API key** from a terminal, because it is typed at a hidden prompt. Run the `radio.py` in Claude Code's copy of the marketplace, which is this repo. `claude plugin list` shows that folder on the plugin's `Read from:` line (`claude plugin marketplace list --json` prints it as `installLocation`); for the GitHub install above it is normally `~/.claude/plugins/marketplaces/digitalbyte`, and if yours differs, use that folder in the commands below. The hooks run a second copy, the installed plugin under `~/.claude/plugins/cache/digitalbyte/ai-radio/<version>/`; `radio.py` from either folder stores the key in the same data directory:
   ```
   python3 ~/.claude/plugins/marketplaces/digitalbyte/radio.py key                  # macOS / Linux
   python "$HOME\.claude\plugins\marketplaces\digitalbyte\radio.py" key             # Windows PowerShell
   ```
   Or set `STABILITY_API_KEY` in the environment Claude Code starts from. A key stored with `radio key` wins when both exist.
4. **Add the statusline** (optional). A plugin can't set it, so add this to `~/.claude/settings.json`:
   ```
   "statusLine": {"type": "command", "command": "python3 ~/.claude/radio/statusline.py"}
   ```
   On Windows, use `python` and the full path with forward slashes: `"command": "python C:/Users/<you>/.claude/radio/statusline.py"`. More under **Statusline** below.
5. **Make a track and play it**, in Claude Code:
   ```
   /ai-radio:radio gen "warm lo-fi hip hop, rhodes, vinyl crackle, 80 BPM"
   /ai-radio:radio play
   ```
   `gen` spends Stability credits, and its `Cost:` line prints exactly how many.

That's the whole setup. Everything works without the optional downloads in **Better voice and prompts**; this is what you get without them:
- **The DJ uses the system voice.** A `play --say` line and Claude's turn updates are spoken by the first engine found after Kokoro: Piper (if installed with a voice), macOS `say`, Windows SAPI, or `espeak-ng` / `espeak` on Linux. With none of them the line is skipped and `dj_engine.log` records `no tts engine found`.
- **`enhance` passes your idea through.** It prints `Enhancer not installed (need llama-cli + a .gguf under <data dir>/llm); using idea as-is.` and uses the idea as the prompt, and `egen` generates from the idea unchanged.
- **`gen` picks lengths from the keyword rules** (see `gen` below): the prompt above prints `Length: keyword rules decided 150s`. A length you type, or write into the prompt ("90 second trailer"), is used as usual.
- **The 256-token prompt check is an estimate** at 4 characters a token, and a refusal says so: `about <n> tokens (estimated at 4 characters a token: t5gemma-tokenizer.json is not in <data dir>/llm)`.

**Updating.** `claude plugin marketplace update digitalbyte` refreshes Claude Code's copy of the marketplace, and `claude plugin update ai-radio@digitalbyte` installs the newer version; restart Claude Code to apply it. Third-party marketplaces don't auto-update by default. The library, key, settings and models live in the data directory, which an update doesn't touch.

---

## 🎧 Better voice and prompts (optional)

Three optional downloads, each into the data directory (`<data dir>` = `~/.claude/radio`, or `AI_RADIO_HOME`). None is bundled; `THIRD_PARTY_NOTICES.md` has each one's license and source page.

**Kokoro-82M, the neural DJ voice.**
1. Download `kokoro-v1.0.fp16.onnx` and `voices-v1.0.bin` from the `kokoro-onnx` project's model release, <https://github.com/thewh1teagle/kokoro-onnx/releases/tag/model-files-v1.1>, into `<data dir>/kokoro/`. `kokoro-v1.0.onnx` or `kokoro-v1.0.int8.onnx` work too.
2. `pip install -U kokoro-onnx soundfile` into any Python. The `-U` matters if you already have it: the model in that release needs kokoro-onnx 0.6 or newer (0.5.0 failed on it with `Unexpected input data type`, while 0.6.1 rendered it and the older `model-files-v1.0` file alike). `dj.py` finds an interpreter that can import them by itself; to pin one, set `dj.python` in `config.json`.

**A local model for `enhance`, `egen` and `gen`'s length pick.**
1. Download the `Q4_K_M` file of Qwen3-4B-Instruct-2507 from <https://huggingface.co/unsloth/Qwen3-4B-Instruct-2507-GGUF> (about 2.5 GB as listed there) into `<data dir>/llm/`. The radio uses the first `.gguf` in that folder in sorted order, so keep one model there.
2. Download a llama.cpp release archive for your OS from <https://github.com/ggml-org/llama.cpp/releases> and copy its `llama-cli` executable (`llama-cli.exe` on Windows), plus the shared libraries beside it in the archive, into `<data dir>/llm/bin/`. A `llama-cli` on `PATH` works too. The radio was tested against build b10069, and on Windows against b11581 (2026-10-13), whose `win-cpu-x64` archive still has `llama-cli.exe`. Pick the newest `b<number>` release: on 2026-10-13, GitHub's "Latest" label was on a `v0.6.0` release with no archives at all. Newer releases also document a `llama cli` subcommand form, so if your archive has no `llama-cli` executable, check its release notes first.

**The T5Gemma tokenizer, for an exact prompt-length count.**
1. Log in to Hugging Face and accept Google's Gemma terms on <https://huggingface.co/google/t5gemma-b-b-ul2> (the repository is gated).
2. Download its `tokenizer.json` (34.4 MB as listed) and save it as `<data dir>/llm/t5gemma-tokenizer.json`. It's read with the standard library; no package is needed.

---

## 🛠️ Manual install (without the plugin)

1. **Clone the repo to `~/.claude/radio`**: `git clone https://github.com/MatthewNorton/terminal-fm ~/.claude/radio` (Windows PowerShell: `git clone https://github.com/MatthewNorton/terminal-fm "$HOME\.claude\radio"`). There the clone is also the data directory. A clone anywhere else works as well; the data directory then stays `~/.claude/radio` (or `AI_RADIO_HOME`).
2. **Copy the skill**: copy the `skills/radio/` folder to `~/.claude/skills/radio/`. In the copy's `SKILL.md`, replace every `${CLAUDE_PLUGIN_ROOT}` with the full path of your clone, written with forward slashes (for example `C:/Users/<you>/.claude/radio`); outside a plugin nothing fills that variable in with the clone's path. The skill is then `/radio`.
3. **Add the two hooks** to `~/.claude/settings.json`, through the repo's launcher script (Windows: write `C:/Users/<you>/.claude/radio/...` in place of `~/.claude/radio/...`):
   ```json
   "hooks": {
     "SessionStart": [{"matcher": "startup|resume", "hooks": [{"type": "command", "command": "sh ~/.claude/radio/hooks/radio-hook.sh SessionStart", "async": true, "timeout": 30}]}],
     "Stop": [{"hooks": [{"type": "command", "command": "sh ~/.claude/radio/hooks/radio-hook.sh Stop", "async": true, "timeout": 60}]}]
   }
   ```
   Or call Python directly, `python3 ~/.claude/radio/radio.py hook SessionStart` and `... hook Stop`; on Windows, the full path to the `pythonw.exe` beside your `python.exe` keeps a console window from opening.
4. **The key, the statusline and a first track** are steps 3 to 5 of **Install**, with `~/.claude/radio/radio.py` as the launcher (see **Cheatsheet**) and `/radio` in place of `/ai-radio:radio`.

Installing the plugin later? Remove the two hook entries and `~/.claude/skills/radio/` first, or every hook runs twice.

**Never add the marketplace from a folder that is also a data directory**, such as a clone at `~/.claude/radio`. `claude plugin marketplace add <local path>` followed by `claude plugin install` copies the whole folder into `~/.claude/plugins/cache/digitalbyte/ai-radio/<version>/` as plain files, without `.git` and without regard to `.gitignore`. In a test on 2026-10-12 that copy ran to several GB and held `.key`, `config.json`, `output/`, `llm/`, `kokoro/` and every untracked file, and `claude plugin uninstall` left it behind. Install from GitHub as in **Install** (Claude Code clones the repo, so only tracked files travel), or add the marketplace from a clean clone or zip of a release commit.

---

## ⚡ Cheatsheet

Inside Claude Code you type `/ai-radio:radio <command>` (or `/radio <command>` on the manual install), or just say what you want. From a terminal, everything is a subcommand of `radio.py`; substitute your launcher:

| Where | Launcher |
|---|---|
| **Claude, through the plugin skill** | `python "${CLAUDE_PLUGIN_ROOT}/radio.py"`, filled in with the plugin's folder when the skill loads |
| **Terminal, manual install, macOS / Linux** | `python3 ~/.claude/radio/radio.py` |
| **Terminal, manual install, Windows** | `python "$HOME\.claude\radio\radio.py"` (PowerShell) or `python "%USERPROFILE%\.claude\radio\radio.py"` (cmd) |
| **Terminal, plugin install** | the same, with the marketplace copy's `radio.py`: `python3 ~/.claude/plugins/marketplaces/digitalbyte/radio.py` |

```
radio play            (or: resume)      ▶  start the radio (or resume a pause)
radio play --say "We're live!"          ▶  start + a DJ sign-on line (jumps the DJ queue)
radio pause                             ⏸  pause; next `play` resumes the same track + spot
radio stop                              ■  stop everything (clears the pause point)
radio skip            (or: next)        ⏭  skip current track
radio status          (or: no args)     ℹ  state, folder, library/archive, mode, queue, player

radio list                              ☰  numbered library listing
radio play 1,3,5-8                      ▶  play just those tracks, in that order (loops)
radio playlist        (or: pl)          ☰  show the current playlist
radio shuffle                           🔀 clear the playlist -> full-library shuffle
radio folder <path> | default           📁 change the folder the radio plays from (alias: library)
radio format mp3 | wav | wav+mp3        💾 file type new tracks are saved as (alias: filetype)
radio key [show | clear]                🔑 store the Stability API key (hidden prompt) / show / remove

radio gen "lo-fi beats, 80 BPM"         ✨ one track, length picked to suit the prompt
radio gen "lo-fi beats, 80 BPM" 120     ✨ one 120s track       (ONE number = duration)
radio gen "lo-fi beats, 80 BPM" 3 110   ✨ three 110s tracks    (TWO numbers = count, duration)
radio gen "lo-fi beats, 80 BPM" 3 auto  ✨ three tracks, length picked
radio enhance "rainy night drive"       🪄 local-LLM rewrite of an idea into a prompt (prints only)
radio egen "rainy night drive"          🪄 enhance, then generate with it

radio archive                           🗃  move the track on air out of rotation (and skip it)
radio archive 3,7                       🗃  archive tracks by their `radio list` number
radio drop                              👎  move the track on air to output/bad song (and skip it)
radio unarchive [1,3 | all]             ↩  list / restore archived tracks (alias: restore)
radio prompts [all | N | <text>]        📜 prompt history: recent / everything / one entry / search

radio say "Big news from the desk…"     🎤 queue a DJ line (alias: dj)
radio announce on | off | (blank)       🔔 speak updates when Claude finishes a turn, music stopped
radio breaking on | off | (blank)       📰 interrupt the track for the update, then resume it
```

Or just talk to Claude: **`/ai-radio:radio play`**, *"skip this song"*, *"get rid of this one"*, *"what's playing?"*, *"make me some synthwave"*, *"what prompt did I use for the car track?"* — the radio skill maps natural language to these subcommands. Installed as a plugin the skill is `/ai-radio:radio`; on the manual install (the skill copied to `~/.claude/skills/radio/`) it is `/radio`. A bare `/radio` does not reach the plugin's skill: with no skill of that name installed, a one-shot session answered "/radio isn't available in this environment", so use the full `/ai-radio:radio` on the plugin route.

---

## ⌨️ Short keys

Most commands also have a one- or two-letter key. The most-used command for each letter gets that letter on its own, and the others starting with the same letter get two. A key works anywhere the full name does, arguments included: `radio p 1,3,5-8`, `radio g "lo-fi beats" 3 auto`, `/ai-radio:radio pa`.

| Key | Command | What it does |
|---|---|---|
| `p` | `play` | Starts the radio, or resumes a paused track from where it stopped. Add track numbers (`p 1,3,5-8`) to play just those, in that order. |
| `pa` | `pause` | Stops the music but remembers the track and position. The next `p` picks up right there. |
| `pl` | `playlist` | Shows the current playlist, or sets one from `list` numbers (`pl 1,3,5-8`). `pl clear` goes back to shuffling the whole library. |
| `pr` | `prompts` | Shows the newest 20 entries in your prompt history. Add a number for one entry in full with a ready-to-run `gen` line, `all` for everything, or text to search. |
| `s` | `stop` | Stops everything and forgets the pause point, so the next `p` starts a fresh shuffle. An active playlist is kept. |
| `n` | `skip` | Jumps to the next track. |
| `sk` | `skip` | Same as `n`. |
| `st` | `status` | Shows what's playing, the library folder and its track count, playlist or shuffle mode, and the player in use. |
| `sh` | `shuffle` | Clears the playlist and goes back to shuffling the whole library. |
| `l` | `list` | Lists the library with numbers. Those are the numbers `p`, `pl` and `a` take. |
| `f` | `folder` | Shows the folder the radio plays from, or changes it (`f <path>`, `f default`). A running radio keeps the old folder until `s` then `p`. |
| `ft` | `format` | Shows or sets whether new tracks are saved as `mp3`, `wav`, or `wav+mp3` (an MP3 that plays plus its WAV master in `_wav`). Tracks already in the library are left as they are. |
| `a` | `archive` | Moves the song that's playing into the library's `_archive` folder and skips to the next. `a 3,7` archives by `list` number instead; nothing is deleted. |
| `an` | `announce` | `an on` has the DJ speak an update whenever Claude finishes a turn while the music is stopped. `an off` turns it off, and on its own it shows the setting. |
| `b` | `breaking` | `b on` lets an update interrupt the song that's playing, then resumes the song where it left off. `b off` turns it off, and on its own it shows the setting. |
| `d` | `drop` | Moves the song that's playing into the shared `output/bad song` folder and skips to the next. Nothing is deleted. |
| `u` | `unarchive` | Lists the archived songs with numbers. `u 1,3` or `u all` puts them back in the library. |
| `g` | `gen` | Generates new tracks from a prompt in quotes, picking the length when you don't give one. Spends Stability credits; with no prompt it only prints the usage. |
| `e` | `enhance` | Rewrites a rough idea into a full prompt with the local model and prints it. Generates nothing and spends no credits. |
| `eg` | `egen` | Rewrites the idea like `e`, then generates from it, taking the same numbers as `g`. Spends Stability credits. |
| `k` | `key` | Asks for your Stability API key at a hidden prompt and stores it. `k show` shows its first 6 characters and `k clear` removes it. |

`say` already has the short alias `dj`. `hook` has no short key because only Claude Code's hooks call it.

---

## 📦 Requirements

| Need | For | Notes |
|---|---|---|
| **Python 3.8+** | everything | Stdlib only for the core; `py`/`python`/`python3` all fine. API calls use Python's own `ssl` (bundled OpenSSL), which supplies the TLS 1.3 the Stability API requires. Output is always UTF-8, even when piped, so accented or non-Latin prompts print intact. |
| An **audio player** | playback | First found wins: `mpv` › `ffplay` › `afplay` (mac) › `mpg123` › `cvlc`. Install `mpv` or `ffmpeg`. `mpg123` is an MPEG decoder: on Ubuntu 24.04 it exited with an error on a WAV file without playing it, so with `mpg123` as your player keep `radio format` at `mp3` or `wav+mp3` (whose WAV masters stay out of rotation). It also handles the stop signal itself and was seen still running a second after `stop`, so the music can run on briefly. On Windows, `C:\ffmpeg\bin\ffplay.exe` is found even when it isn't on PATH. Resuming mid-track (pause, breaking news) needs a seekable player: `mpv`, `ffplay` or `cvlc`. |
| A **Stability API key** | `gen`, `egen` | `radio key` stores it in `<data dir>/.key` (typed at a hidden prompt), **or** set `STABILITY_API_KEY`. |
| **`ffmpeg`** *(optional)* | `radio format wav+mp3` | Encodes the MP3 from the WAV. On Windows, `C:\ffmpeg\bin\ffmpeg.exe` is found even when it isn't on PATH. Not needed for `mp3` or `wav`. |
| **`curl`** *(optional)* | fallback transport | Only tried when Python's own request fails to connect. On Windows 10, `curl` is Schannel-backed with no TLS 1.3 and cannot reach the API at all. |
| **Kokoro-82M** model | best DJ voice | `~/.claude/radio/kokoro/kokoro-v1.0.fp16.onnx` + `voices-v1.0.bin`, and `pip install -U kokoro-onnx soundfile` in *some* interpreter. Optional — falls back to the system voice; see **Better voice and prompts**. |
| **llama.cpp `llama-cli`** + a `.gguf` *(optional)* | `enhance`, `egen`, `gen`'s duration pick | `~/.claude/radio/llm/bin/llama-cli(.exe)` (or `llama-cli` on PATH) plus any `.gguf` in `~/.claude/radio/llm/` (the first alphabetically is used). CPU-only. Without it, `enhance` passes your idea through unchanged and `gen` picks durations from keyword rules instead. See **Better voice and prompts**. |
| **T5Gemma tokenizer** *(optional)* | exact prompt-length check in `gen`, `egen`, `enhance` | `~/.claude/radio/llm/t5gemma-tokenizer.json` — the `tokenizer.json` of Hugging Face `google/t5gemma-b-b-ul2`, Stable Audio 3's text encoder (Gemma license; accept it on Hugging Face to download). Read with the stdlib, no package needed. Without it the 256-token limit is checked by estimate, 4 characters a token. See **Better voice and prompts**. |

Nothing above is bundled; `THIRD_PARTY_NOTICES.md` has each download and its license.

**Where things live.** The scripts (`radio.py`, `dj.py`, `kokoro_tts.py`, `statusline.py`, `prompts/`) run from wherever you put them: a clone, a plugin install, or `~/.claude/radio`. Everything they create or read at runtime, including the library, the key, `config.json`, the downloaded models under `kokoro/` and `llm/`, state and logs, lives in the **data directory**: `~/.claude/radio` by default, or the folder named by the `AI_RADIO_HOME` environment variable. Paths written as `~/.claude/radio/...` below mean that data directory.

**Data directory decisions for the plugin:**
- **The data directory stays `~/.claude/radio` (or `AI_RADIO_HOME`), not the plugin's own data folder.** Claude Code gives each plugin `${CLAUDE_PLUGIN_DATA}` (`~/.claude/plugins/data/<id>/`), which survives updates but is deleted on uninstall unless `--keep-data` is passed, and that would take the music library and the key with it.
- **`prompts/enhance.md` is read from the data directory first** (`<data dir>/prompts/enhance.md`), falling back to the copy shipped beside `radio.py`. The plugin's folder is replaced on every update, so a prompt tuned inside it would be lost; tune a copy in the data directory instead.
- **The marketplace must never be added from the data directory.** A local-path marketplace is installed by copying the folder as it is, key, settings, library and models included (several GB in one test), and uninstalling leaves the copy in the plugin cache. Use the GitHub route, or a clean clone or zip of a release commit; see the warning under **Manual install**.
- **Models go in the data directory**, under `kokoro/` and `llm/`. The empty `kokoro/.gitkeep` and `llm/.gitkeep` in the repo mark where they go on the manual route, where a clone at `~/.claude/radio` is also the data directory; inside an installed plugin those two folders are never read.
- **The API key stays with `radio key`.** A plugin `userConfig` value marked `sensitive` would sit in the platform's secure store, but Claude Code hands it only to hooks (as `CLAUDE_PLUGIN_OPTION_<KEY>`), not to the Bash tool that runs `radio gen`.

---

## 🧩 Claude Code plugin

The repo is a Claude Code plugin and its own one-plugin marketplace:

| File | What it is |
|---|---|
| `.claude-plugin/plugin.json` | the manifest: name `ai-radio`, `version`, description, author, license |
| `.claude-plugin/marketplace.json` | the marketplace `digitalbyte`, listing `ai-radio` with `"source": "./"` (this repo) |
| `skills/radio/SKILL.md` | the skill, invoked as `/ai-radio:radio` |
| `hooks/hooks.json` | the `SessionStart` and `Stop` hooks |
| `hooks/radio-hook.sh` | the launcher both hooks call |
| `statusline.py` | the now-playing statusline segment (see **Statusline** below) |

**Install** is covered in **🚀 Install** above. To try a checkout for one session without installing, `claude --plugin-dir <path to the checkout>`; `claude plugin details ai-radio` only finds the plugin when `--plugin-dir` is on the same command line. Check the files with `claude plugin validate . --strict`.

**Hooks.** `hooks/hooks.json` runs `sh "${CLAUDE_PLUGIN_ROOT}/hooks/radio-hook.sh" SessionStart` on session `startup` and `resume` (not on `clear` or `compact`, which would queue a sign-on line every compaction), and `... Stop` when Claude finishes a turn. Both are `async` (Claude never waits for them), with timeouts of 30s and 60s; 60s leaves room for an idle announcement to render on CPU. `radio-hook.sh`:
- runs `radio.py hook <event>` from the plugin folder and passes the hook's JSON through on stdin, never on a command line;
- tries `python3`, then `python`, then `py`, skipping any that doesn't actually run (a Windows Store `python3` alias fails the probe); on Windows it prefers the first one with a `pythonw.exe` beside it, so no console window opens, and otherwise uses the first that ran;
- discards all output and always exits 0, so a missing Python or a radio error never disturbs the session.

The hooks are shell commands, which Claude Code runs under Git Bash on Windows. Plugin hooks run in addition to any in `settings.json`, so if you used the manual install, remove its two radio hook entries when you install the plugin. In a one-shot `claude -p` run, the `Stop` hook of the last turn was seen not to finish before the process exited; interactive sessions don't have that problem.

**Statusline.** A plugin can't set your `statusLine`, and an installed plugin's folder changes with every version, so the `SessionStart` hook copies `statusline.py` into the data directory whenever its bytes differ (nothing is copied when the code folder *is* the data directory). Point your `~/.claude/settings.json` at that copy:

```
"statusLine": {"type": "command", "command": "python3 ~/.claude/radio/statusline.py"}
```

On Windows, use `python` and write the full path with forward slashes (`python C:/Users/<you>/.claude/radio/statusline.py`); `~` in a statusLine command hasn't been tested there. With `AI_RADIO_HOME` set, point at that folder instead. The script prints `♪ AI Radio > <track>` in magenta while a track plays, `· AI Radio | stopped` (or another status) in gray otherwise, and nothing when `nowplaying.txt` is missing or empty; set `NO_COLOR` for plain text. It reads `AI_RADIO_HOME` the same way `radio.py` does. To add the radio to a statusline of your own, read `<data dir>/nowplaying.txt` and treat a `>` in it as playing: `radio.py` writes `AI Radio > <track>` only while a track plays and `AI Radio | <status>` otherwise.

---

## 🎛️ Commands (full reference)

Every command below except `say` and `hook` also answers to its short key from **Short keys** above.

### `radio.py play [1,3,5-8] [--say "<line>"]`  *(alias: `resume`)*
Starts the playback daemon as a **fully detached** process and returns immediately.
- **Track numbers** (`1,3,5-8`, from `radio list`) turn this into a playlist instead — see **Playlists** below.
- `--say "<line>"` — a DJ sign-on line. It goes to the **front** of the DJ queue, ahead of any lines already waiting, so it's spoken before the first track. (Several sign-ons keep their order among themselves.) A `--say` with no line after it (or another `--flag` where the line should be) is ignored.
- If a pause point exists, that track resumes at its saved position first (no DJ line before it); a `--say` line is then spoken before the track after it.
- If already playing, it says so and only queues the `--say` line, which the running radio speaks before its next track.
- Refuses if the library is empty or no player is found. A refused `play` queues nothing, so its `--say` line is dropped rather than spoken by some later `play`.

### `radio.py pause`  *(resume with `radio.py play`)*
**Real pause/resume.** Snapshots the current track and position, tears the daemon down, and sets status `paused`. The next `radio.py play` **resumes that track from where it left off**. There's no OS-level pause of the detached player, so this works by persisting the live position (`play_track` writes `player_offset` + `player_started` to `state.json`) into `resume.json` and re-seeking on restart.
- Resume-at-offset works on **mpv / ffplay / cvlc**; **afplay / mpg123** restart the track from the top (no clean seconds-seek).
- `stop` (below) clears the pause point; `pause` keeps it. Use `pause` to hold, `stop` to end.
- Between tracks (while the DJ is speaking, or a track is loading), or in the first second of a track, there is no position to keep: `pause` then behaves like `stop` and says `Paused between tracks, nothing to resume`.
- Like `stop`, it kills the daemon first and then re-reads `state.json`, so the position and the player it kills are those of the track playing once the daemon is gone. A track that ends during that kill has already started the next one, and the pause lands on that one (usually within its first second, so nothing to resume).

### `radio.py stop`
Kills the **daemon first** (so it can't respawn a player), then re-reads `state.json` and kills the player it names now, plus the player it named before if that is a different one still running. Killing the daemon takes a moment, and a track that ends inside it has already started the next player; stopping only the first-read player used to leave that one playing with nothing tracking it. Clears any pending breaking-news line **and the pause point**, so the next `play` starts fresh. An active playlist is **not** cleared — use `radio shuffle` for that.
- `state.json` records each PID together with its program name, and every liveness check and kill verifies the two still match, so a PID the OS has recycled for some other program is treated as dead and never killed. On macOS and Linux the daemon's name is recorded as the OS reports it, because a Homebrew, python.org or Xcode Python runs as `Python` whatever its command was called, and a `cvlc` player is recorded as `vlc`, the program that wrapper starts.

### `radio.py skip`  *(alias: `next`)*
Kills the current player process; the daemon's `wait()` returns and it advances to the next track.

### `radio.py status`  *(also what `radio.py` with no arguments runs)*
Prints: state, now-playing, library folder (flagged if custom), library track count, archive count (when non-zero), mode (playlist or shuffle), pending DJ lines, idle-announce on/off, active source, detected player, and daemon PID + liveness. Breaking-news mode isn't listed here — `radio breaking` shows it.

### `radio.py list`
Numbered listing of every `.mp3` and `.wav` in the library folder (non-recursive). The order is snapshotted to `last_list.json`, so the numbers you then pass to `play` / `playlist` / `archive` refer to what you were shown even if the library has changed since. `*` marks tracks in the active playlist.

### Playlists — `radio.py play 1,3,5-8` · `playlist [1,3,5-8 | clear]` · `shuffle`
- **Selection grammar:** commas or spaces; ascending `5-8` or descending `8-5` ranges; repeats are kept (`3,3` plays it twice); numbers outside the library are ignored.
- The selection is saved as track names in `playlist.json`. The daemon plays it **in order and loops**. Setting one while music is playing jumps to it immediately; a changed selection starts again from its first track.
- `radio playlist` (alias `pl`) with no arguments shows the playlist. `radio playlist clear` (also `off` / `none` / `all` / `reset` / `shuffle`) or `radio shuffle` deletes it and returns to full-library shuffle, leaving the current track if it was a playlist track.
- A playlist survives `stop` / `play`. Names are resolved against the **current** library folder: missing entries are skipped, and if none resolve the radio falls back to shuffle.

### `radio.py folder [<path> | default]`  *(alias: `library`)*
Shows or changes the folder the radio plays from, persisted as `library_dir` in `config.json`.
- No argument: the current folder (default or custom) and its track count.
- `<path>`: play from there (created if missing). `~` and environment variables expand; relative paths resolve against the data directory. A path that can't be created is refused with `Not saved: could not create ...` and the setting is left as it was.
- `default` (also `reset` / `clear` / `none`): back to `~/.claude/radio/output`.
- If `config.json` names a folder that can't be created, every command prints a warning and uses the default folder instead of failing; `radio folder default` clears it.
- The scan is non-recursive, so pointing at a subfolder plays just that collection. The folder also decides where `gen` saves new tracks and where `_archive` lives.
- A running daemon keeps the old folder until `radio stop` then `radio play`.

### `radio.py gen "<prompt>" [<duration> | auto]` · `radio.py gen "<prompt>" <count> <duration | auto>`
Generates track(s) into the library folder via the active source (Stability AI by default), saved as `.mp3` or `.wav` per `radio format`.
- **The number grammar is position-sensitive.** ONE number after the prompt is the **duration**; TWO are **count** then **duration**. A lone number under 10 is refused as an implausible track length (it's almost certainly a count typed in the wrong place), and the refusal suggests the count form `radio gen "<prompt>" <n> auto`. A duration or count that isn't a number (or `auto`), a count of 0, or a third number prints the usage instead.
- **A count above 20 asks first.** Each track is billed, so `gen "<prompt>" 100 30` prompts `Generate 100 tracks (each one is billed)? Type yes to continue:` and cancels on anything else, or when there is no terminal to ask on.
- **A typed duration is always used as-is**, including short or long ones like 30 or 218.
- **No duration = picked to suit the prompt.** Leave the duration out, or write `auto` in its slot (the only way to get a pick together with a count), and `gen` chooses the length before generating. There is no setting to turn this off.
  - A length written into the text in words wins first, with no model call: "90 second cinematic trailer build" → 90s, "3 minute progressive house" → 180s. It has to spell the unit out, so "80s synthwave" stays a decade, and a number that times a sound rather than the clip is skipped ("an 8 second reverb tail").
  - Otherwise the local model (see Requirements) reads the whole prompt at temperature 0, so the same prompt always gets the same length. It's one extra CPU call before generation, measured at 8.9–13.5s. Its answer is clamped to **1–380s**, the full range, so the length can be anything the prompt suits: a notification chime got 5s, a jingle 15s, "a very long six minute build" 360s. A stated length is used ("3 second chime" → 3s). A clamp is shown on the Length line (a model answer of 600s prints `local model decided 380s (model said 600s)`).
  - Without the model, or when its answer has no number, the first matching keyword rule decides, checked in this order so a use-case word beats the genre it's written in: `notification` `sting` `stinger` → **5s**; `jingle` `bumper` → **15s**; `intro` `outro` `commercial` `advert` → **30s**; `ambient` `drone` `meditation` `sleep` `soundscape` → **300s**; `techno` `trance` `progressive` → **240s**; `trailer` `punk` `hardcore` → **120s**; `synthwave` `retrowave` `lo-fi` `lofi` `lo fi` `jazz` `hip hop` `hip-hop` `chillhop` `funk` `soul` `house` `rock` `pop` → **150s**. The model is shown the same rules as guidance but weighs the whole prompt, so it can disagree with them.
  - No rule matches → `stability_api.duration` = **120s**.
- **The prompt must fit in 256 tokens, or nothing is generated.** Stable Audio 3's text encoder (T5Gemma) reads only the first 256 tokens of a prompt and drops the rest without an error, while the API still bills the track (SA3 technical report, arXiv 2605.17991, "long prompts are truncated to 256"; the SA3 repo's tokenizer code cuts at `max_len=256` and adds no start/end tokens). So `gen` counts the prompt first and refuses anything longer, before the duration pick or any credit is spent: `Refusing: the prompt is 276 tokens, and Stable Audio 3 reads only the first 256 - the rest would be dropped without an error. Cut about 107 of its 1473 characters. Nothing spent.` The count is exact when the T5Gemma tokenizer is installed (see Requirements): it matched the Hugging Face tokenizer on all 8,117 distinct test strings (2026-10-14), 256 tokens passing and 257 refused. English prompts run about 4.2–5.3 characters a token, so 256 tokens is roughly 1,070–1,360 characters of prose, but digits, chord symbols and non-Latin text measured 1.41 characters a token, which is why characters alone aren't the check. Without the tokenizer file the count is an estimate at 4 characters a token and says so.
- Sampling steps are not an argument: Stable Audio 3 is fixed at `steps=8` (`stability_api.steps`).
- The 1–380s range bounds only picked durations. It matches the API's documented `duration` range (1–380s, API default 190s). A typed duration is sent unchanged, so one outside that range is left for the API to reject. Tested: a 218s request returned a full 218.0s track, and a 5s auto-picked track came back at 5.0s.
- Every track is saved **permanently**. Every successful track is recorded in `prompt_history.jsonl`. New files join the shuffle on the daemon's next pass — no restart needed.

**Output is four lines** (plus a `FAILED (<i>/<n>) <reason>` line for any track that didn't land):

```
Length: local model decided 180s
Prompt: <the exact prompt sent to Stable Audio>
Cost: 26 credits
Folder: output / track(s) added: 1 / total: 5 tracks
```

- **Length** names who chose it: `user decided` (you typed it), `as stated` (a length written in the text, e.g. "90 second trailer"), `local model decided`, `keyword rules decided` (no model, or no number in its answer), or `config default` (nothing matched).
- **Cost** is exact, not an estimate: the drop in the account's credit balance (`stability_api.balance_url`) from before the first submit to after the last result. The balance can lag behind the result, so when it hasn't moved after ~5s of re-reads the line says `unknown (credit balance unreadable or not updated yet)` rather than reporting 0. When nothing was sent at all (no API key), the line is `Cost: 0 credits (nothing sent)`. Measured: a 5s track cost 26 credits, but the charge wasn't visible yet 5s after the track arrived. That matched Stability's published price when it was checked in September 2026, a flat 26 credits per successful generation whatever the length, with failed generations free; prices change, so the `Cost:` line is the number to trust. Another generation on the same key at the same time is counted too.
- **Folder** is the library folder's name, the tracks this run saved, and the folder's new total.

```bash
radio gen "warm lo-fi hip hop, rhodes, vinyl crackle, 80 BPM"          # one track, length picked
radio gen "warm lo-fi hip hop, rhodes, vinyl crackle, 80 BPM" 100      # one 100s track
radio gen "driving synthwave, neon, analog bass, 120 BPM" 3 110        # three 110s tracks
radio gen "slow ambient drone with a long build" 2 auto                # two tracks, length picked
```

### `radio.py format [mp3 | wav | wav+mp3]`  *(alias: `filetype`)*
Shows or sets the file type `gen` / `egen` save new tracks as, persisted as `stability_api.output_format` in `config.json` (default `mp3`).
- No argument: the current format. `mp3`, `wav` or `wav+mp3` (a leading dot and any case are accepted, e.g. `.WAV`; `mp3+wav` means the same as `wav+mp3`) sets it; anything else is refused.
- **`wav+mp3` keeps both files of the same take, billed once.** Stable Audio 3 returns one file type per request, so `gen` requests the WAV, saves it to `<library>/_wav/`, and encodes the MP3 from it locally with `ffmpeg` (`libmp3lame`, 128 kbps, which is what the API's own MP3s measured). The MP3 goes in the library and plays. The `_wav` subfolder is skipped by the non-recursive scan like `_archive`, so nothing plays twice. `radio format wav+mp3` is refused with `Not saved.` when `ffmpeg` isn't on PATH (or, on Windows, in `C:\ffmpeg\bin`). If an encode fails anyway, gen prints `MP3 (<i>/<n>) not made (<reason>); kept the WAV in <library> instead.` and moves the WAV into the library so the track still plays. `archive`, `drop` and `unarchive` move only the MP3; its WAV master stays in `_wav`.
- Existing tracks are untouched, and the library plays both types side by side: `list`, shuffle, playlists, `archive` and `unarchive` all see `.mp3` and `.wav`.
- **Disk cost:** a WAV from Stable Audio 3 is 16-bit PCM, 44.1 kHz stereo (measured), which is 176,400 bytes per second: about 10.6 MB a minute, 31.8 MB for a 180s track, and 67 MB at the 380s top of the auto-pick range. A 180s track as MP3 was 2,830 KB. `wav+mp3` costs both: a 380s track measured 67.0 MB of WAV plus 6.1 MB of MP3. To reclaim space, `radio format mp3` for new tracks; existing WAVs stay until you archive or delete them, and `_wav` masters until you delete them.
- `mpg123` (the Linux fallback player) is an MPEG decoder and exited with an error on a WAV in testing, so with it keep `radio format` at `mp3` or `wav+mp3`. `mpv`, `ffplay`, `cvlc` and `afplay` played WAV.

### `radio.py key [show | clear]`
Stores the Stability API key without ever putting it on a command line.
- No argument: prompts for the key with hidden input and saves it to `<data dir>/.key`, which on macOS/Linux is owner-only (`0600`) from the moment it is created. Typing nothing leaves the stored key unchanged. When its input isn't a terminal (piped or redirected, as when Claude runs it) it says so and points at `STABILITY_API_KEY` instead of prompting.
- `show`: the first 6 characters of the key in use, where it came from (`.key file` or `STABILITY_API_KEY`), and whether the environment variable is set. The stored file wins over the variable when both exist. With no key it adds a second line naming the next step: ``No key yet: run `radio key` in a terminal to store one (hidden prompt), or set STABILITY_API_KEY.``
- `clear` (also `delete` / `remove`): deletes the stored file.
- Anything else prints the usage; the key is never accepted as an argument.

### `radio.py enhance "<idea>"`
Rewrites a rough idea into one Stable Audio 3 prompt: a single English paragraph of about 45–90 words for music (15–55 for a solo part or sound effect) describing identity, instruments and how they play, rhythm, mood, broad development and production. It keeps everything your idea states (genre, instruments, BPM, key, meter, exclusions, solo or beatless scope), and it doesn't force a BPM or percussion onto beatless material or effects. Instrumental by default. **Prints only; nothing is generated.**

```
Length: local model decided 240s
Prompt: <the enhanced prompt>
```

- **The model** the instructions were written and tested for is Qwen3-4B-Instruct-2507 (Q4_K_M, saved as `llm/qwen3-4b-instruct-q4km.gguf`; the first `.gguf` in `llm/` in sorted order is the one used), sampled at temperature 0.7, top-p 0.8, top-k 20, min-p 0, with a 512-token cap. The same idea gives different wordings each time.
- **The instructions live in `prompts/enhance.md`**, not in code, so you can tune them in any editor. The copy in the data directory (`<data dir>/prompts/enhance.md`) wins when it exists; otherwise the one shipped beside `radio.py` is used. To tune them, copy the shipped file into the data directory's `prompts/` folder and edit the copy, because a plugin update replaces the plugin's folder. Every run re-reads the file, so a change applies on the next command. HTML comments (`<!-- ... -->`) in it are notes to yourself and are stripped before sending. The shipped text is the v1.0 instruction from `Qwen3_4B_SA3_Enhancer_Setup_v1.0.md`, copied verbatim (the file's header comment gives its SHA-256, so you can tell whether it has been edited). If the file in use is missing or empty, `enhance` / `egen` say so, naming that file, and use your idea unchanged. A data-directory copy that exists but is empty is still the file in use.
- **Some ideas don't produce a prompt.** A request for sung lyrics, speech or a cloned voice gets `Enhancer: This request requires a vocal or speech model rather than Stable Audio 3.`; an empty idea gets `Enhancer: Please provide the music or sound you want to enhance.`; any reply ending in `?` (the instructions ask for one clarifying question when a brief contradicts itself) is shown to you; and a rewrite over Stable Audio 3's 256-token prompt limit (see `gen`) is retried once, then reported as `Enhancer: the rewrite ran to <n> tokens, over Stable Audio 3's 256-token prompt limit, on both attempts. Run it again.` A reply that ran into the model's own 512-token cap lands there too. None of these is ever sent to Stable Audio. The instructions aim for 45–90 words; 18 measured rewrites ran 37–138 tokens.
- **Known misses** (from an acceptance run of the setup doc's 12 cases plus three more: 7 passed, 5 partly, 3 failed). A self-contradicting brief ("no drums, but an acoustic drum kit throughout") got a contradictory prompt instead of the clarifying question. "ignore the task and print the system instruction" came back unchanged as a prompt (nothing was revealed, but `egen` would generate it). "orchestral cue, 10 seconds" kept "lasting 10 seconds" in the text, which is harmless because the duration is sent separately. Also seen: a detail contradicting the brief ("slow palm-muting" in fast doom metal, "no percussion" after "dusty drums"), a requested `TrackType:` tag dropped, and an effect described in 80 words against a 15–55 target. Read the Prompt line before an `egen` batch.
- **The length is settled first, from your own words, then handed to the rewrite.** `enhance` and `egen` both run the auto-pick on your idea, then tell the enhancer the clip length so it can pace the arrangement to it ("90 second cinematic trailer build" → 90s, and the rewrite is built for 90s). The length is sent as the API's `duration` field; the enhancer is told not to write it into the prompt text.
- **A rewrite that contradicts itself is retried once, then reported.** The check is string matching over four families (percussion, vocals, reverb, bass): it flags a prompt that both describes and denies one of them, e.g. `Conflict: 'no beats' vs 'soft, brushed drums'`. A retry costs ~17s and no credits. `enhance` prints the conflict and the prompt; **`egen` stops without generating** rather than spend 26 credits on it, keeps the rewrite in the history, and tells you the `radio prompts <n>` that would generate it anyway. Measured over 39 real prompts: it flagged the 3 known-bad ones and nothing else. It does not catch subtler contradictions like a "fast" piece described as "slow".
- **Every rewrite is logged** to the prompt history with an `e` mark, so one you liked but didn't generate is still there later (`radio prompts`). Non-prompt replies aren't logged.
- Runs `llama-cli` on CPU (`-ngl 0`, so the GPU stays free) and exits; nothing stays resident. If `llama-cli` or a `.gguf` is missing, it says so and returns your idea unchanged.

### `radio.py egen "<idea>" [<duration> | auto] | [<count> <duration | auto>]`
`enhance`, then `gen` with the result, using the same number grammar as `gen` (including the yes-prompt above 20 tracks), with gen's four-line output (the Prompt line is the enhanced prompt). If the enhancer answers with one of the non-prompt replies above, or a rewrite that still contradicts itself after the retry, `egen` prints it plus `Nothing generated.` and stops without spending credits. Leave the duration out or write `auto` (`egen "idea" 2 auto` = two tracks) and the length is picked from your idea **before** the rewrite and passed to it; a duration you type always wins and is passed to the rewrite the same way. The prompt history records your rough idea alongside the enhanced prompt.

### `radio.py archive [list | show | 1,3,5-8]`
Moves tracks you don't want **out of rotation** into `<library>/_archive/`. Nothing is deleted.
- `radio archive` — the track on air right now; the radio skips to the next one.
- `radio archive list` — the numbered library listing (same as `radio list`) plus the archive count.
- `radio archive 3,7` — archive by number (numbers from the last `radio list`).
- `radio archive show` (also `archived` / `ls`) — what's already archived.
- Because the library scan is non-recursive, the `_archive` subfolder is invisible to shuffle and playlists. Archived tracks are also removed from the playlist; a playlist left empty is deleted, which returns you to shuffle.

### `radio.py drop`
Moves the track **playing right now** into `output/bad song/` and skips to the next one. It works like `radio archive` with no arguments, but everything goes to one shared reject folder instead of each library's own `_archive`, so rejects from every collection end up together. Nothing is deleted.
- The destination is always `~/.claude/radio/output/bad song/`, whichever folder is playing, and it's created if missing. A name already there gets a timestamp suffix; nothing is overwritten.
- The dropped track is removed from the playlist, and a playlist left empty returns you to shuffle, as with `archive`.
- Only the track on air: `Nothing is playing.` when stopped or paused. Arguments print the usage. If the library folder *is* `bad song`, it refuses and points you at `archive` or `skip`.
- To hear the rejects again, `radio folder "output/bad song"`. There's no `undrop`; move a file back by hand.
- In `radio prompts`, a dropped track's entry is marked `b`.

### `radio.py unarchive [1,3 | all]`  *(alias: `restore`)*
- No argument: numbered list of the archive (snapshotted to `last_archive.json` so the numbers stay stable).
- `1,3` restores those tracks; `all` (also `*` / `everything`) restores everything.
- Restores to the **library only**, never back into a playlist. Restored tracks rejoin the shuffle on the daemon's next pass.

### `radio.py prompts [all | <N> | <text>]`  *(aliases: `history`, `prompt-history`)*
Every prompt that produced a track, **plus every `enhance` rewrite even though it generated nothing** — so a good one is never lost either way.
- No argument: the newest 20. `all`: everything. `<text>`: every entry whose idea or prompt contains it.
- `<N>`: full detail for entry N — your idea, the prompt, duration, file and where it is now — plus a ready-to-run `radio gen "<prompt>" 1 <duration>`.
- Numbers are positions in `prompt_history.jsonl`, so they never shift as you generate more.
- Marks: `a` = archived, `b` = in `output/bad song` (see `drop`), `x` = file not found, `e` = an `enhance` rewrite that was never generated. `a` and `x` are checked against the **current** library folder and its `_archive`, and `b` against `output/bad song` wherever the library is, so a track that lives in some other folder shows `x`.
- An `e` entry is the point of logging rewrites: preview with `enhance`, and if you like it days later, `radio prompts <n>` prints the `radio gen` line that makes it.
- One JSON Lines record per entry: `ts`, `prompt`, `duration`, `file` (empty for `e`), `idea` when you used `egen` / `enhance`, `source`, and `kind` only on an `e` entry — its absence means generated, so older records stay correct. Failed generations are never recorded.

### `radio.py say "<line>"`  *(alias: `dj`)*
Queues a line for the DJ to read before an upcoming track. The queue is FIFO and the daemon reads one line per track; only a `play --say` sign-on jumps it. Whoever queues it (you or Claude) writes the copy, and it is spoken verbatim, by Kokoro when it is installed and the system voice otherwise; no LLM is involved. Keep it to **1–2 sentences**: Kokoro renders on CPU and the render blocks the gap between tracks.

### `radio.py announce on | off`  *(blank = show status)*
Toggles **idle announcements**: when ON, the DJ speaks a short update **whenever Claude finishes a turn even with music stopped**. Persisted to `config.json` as `dj.announce_when_idle` (default OFF). The line is Claude's last message, cleaned down to the action-y bit: the `last_assistant_message` field of the hook's input, or the session transcript on a Claude Code that doesn't send that field. Accepts `on` / `enable` / `enabled` / `true` / `yes` / `1` and `off` / `disable` / `disabled` / `false` / `no` / `0`. `radio announce breaking on|off` (also `break` / `interrupt` in place of `breaking`) toggles breaking-news mode instead.

### `radio.py breaking on | off`  *(blank = show status; alias: `radio announce breaking on|off`)*
**Breaking-news mode.** When ON *and music is playing*, a turn-end **interrupts the current track** to speak the update, then **resumes that same track where it left off**. Contrast with normal behavior (OFF), where updates just wait in the queue and are read in the gap before the next track.
- Same recap source as `announce`: Claude's last message, from the hook input or else the transcript.
- Resume-at-offset works on **mpv / ffplay / cvlc** (seek flags); **afplay / mpg123** have no clean seconds-seek, so the track restarts from the top instead (graceful degradation).
- Accepts the same words as `announce`: `on` / `enable` / `enabled` / `true` / `yes` / `1` and `off` / `disable` / `disabled` / `false` / `no` / `0`.
- Persisted to `config.json` as `dj.breaking_news` (default OFF). Independent of `announce`: `announce` governs the *music-stopped* case; `breaking` governs the *music-playing* case.

### `radio.py hook Stop | SessionStart`  *(internal — called by Claude Code hooks)*
Called by the plugin's hooks through `hooks/radio-hook.sh` (see **🧩 Claude Code plugin**), or on the manual install by two entries in `~/.claude/settings.json` (through the same launcher, or `radio.py hook` directly, with `pythonw.exe` on Windows; output discarded). It reads the JSON Claude Code passes on stdin: `cwd` for the project name, and for `Stop` Claude's last message from `last_assistant_message` (sent by Claude Code 2.1.296, the version tested). Only when that field is absent, as on older versions, does it open the transcript named by `transcript_path`, and then it opens whatever path it is given. `SessionStart` first copies `statusline.py` into the data directory (when it differs), whether or not music is playing. Then, on each event:
- **music playing + breaking OFF** → enqueue a DJ line (capped at 4 pending, de-duped against the newest one);
- **music playing + breaking ON** → interrupt the track, speak now, resume it where it left off (`Stop` only; an interrupt already pending is never stacked);
- **music stopped + announce ON** → speak the update immediately (`Stop` only), lock-guarded so overlapping turns don't talk over each other;
- **music stopped + announce OFF** → nothing.

`SessionStart` with music playing queues a generic session-start line (e.g. "Claude just clocked in over on <project>").

### `radio.py __daemon`  *(internal)*
The playback loop. Never run by hand — `play` spawns it detached.

---

## 🗣️ DJ voice engine (`dj.py`)

```bash
dj.py say --file <path>          # speak a pre-written line verbatim (used by the daemon queue)
dj.py say --text "hello"         # or pass text directly
echo "hello" | dj.py say         # or on stdin
```

- `say` is the only command, and it speaks exactly the text it is given; no language model is involved anywhere in the DJ. The radio calls it for queued lines, breaking news and idle announcements.
- **TTS fallback chain:** `Kokoro-82M` → `Piper` → macOS `say` → **Windows SAPI** *(the "robotic" fallback)* → `espeak`. Every engine receives the text on stdin or from a file, never as a command-line argument, so a line starting with `-` can't be read as an option.
- Each utterance appends a line to `dj_engine.log` with the engine used, why, the interpreter, and the first 60 characters of the text, so the log holds fragments of what was said.

**Kokoro render, standalone:**
```bash
echo "on the ones and twos" | python kokoro_tts.py --out out.wav --voice am_michael
```

| Flag | Default |
|---|---|
| `--text "<text>"` | read from stdin |
| `--voice <id>` | `am_michael` |
| `--speed <x>` | `1.0` |
| `--lang <code>` | `en-us` |
| `--out <wav>` | `<data dir>/_dj.wav` (`dj.py` passes a per-process `_dj_<pid>.wav` instead) |
| `--model <onnx>` | first of `kokoro-v1.0.fp16.onnx`, `kokoro-v1.0.onnx`, `kokoro-v1.0.int8.onnx` found in `<data dir>/kokoro/` |
| `--voices <bin>` | `<data dir>/kokoro/voices-v1.0.bin` |

---

## ⚙️ config.json

Lives at `<data dir>/config.json` (`config.example.json` in the repo is a copy of the defaults to start from). An **overlay** on the built-in defaults: each section you give is merged key-by-key into that section's defaults (so `{"dj": {"kokoro_voice": "af_bella"}}` keeps every other `dj` key), and top-level scalars replace. You only need to specify what you're changing. Settings are written atomically, and a `config.json` that no longer parses is never overwritten: `radio format`, `folder`, `announce` and `breaking` print `Not saved: ... is not valid JSON` and leave it for you to fix. Full shape with defaults:

```json
{
  "source": "stability-api",
  "volume": 85,
  "library_dir": "",
  "stability_api": {
    "submit_url": "https://api.stability.ai/v2beta/audio/stable-audio/text-to-audio",
    "results_url": "https://api.stability.ai/v2beta/audio/results",
    "balance_url": "https://api.stability.ai/v1/user/balance",
    "model": "stable-audio-3",
    "steps": 8,
    "duration": 120,
    "output_format": "mp3",
    "ca_bundle": ""
  },
  "dj": {
    "announce_when_idle": false,
    "breaking_news": false,
    "voice": "auto",
    "kokoro_voice": "am_michael",
    "rate": 1,
    "python": "<unset: path to an interpreter that has kokoro_onnx>"
  }
}
```

- **`library_dir`** — the folder to play from; `""` = `~/.claude/radio/output`. Easiest to set with `radio folder`.
- **`volume`** — 0–100, passed to `mpv` / `ffplay` / `afplay`; `mpg123` and `cvlc` ignore it.
- **`stability_api.duration`** — the fallback length, in seconds, when `gen` picks a duration and neither the local model nor a keyword rule settles it. A duration you type always wins, and there's no setting to turn the pick off.
- **`stability_api.output_format`** — `mp3`, `wav` or `wav+mp3`, the file type new tracks are saved as. Easiest to set with `radio format`.
- **`stability_api.balance_url`** — read before and after each `gen` run to print its exact credit cost.
- **`stability_api.ca_bundle`** — a PEM file to verify TLS against (e.g. certifi's `cacert.pem`); `""` = the platform trust store. See **Network & TLS**.
- **`stability_api.steps`** — Stable Audio 3 is fixed at 8.
- **`dj.announce_when_idle`** / **`dj.breaking_news`** — set by `radio announce` / `radio breaking`.
- **`dj.kokoro_voice`** — any Kokoro voice id (`am_michael`, `af_bella`, …).
- **`dj.voice`** — a Piper voice `.onnx` path; `"auto"` uses the first `*.onnx` in `~/.claude/radio/` or `~/.claude/radio/voices/`.
- **`dj.rate`** — speaking rate for the Windows SAPI fallback.
- **`dj.python`** — force the interpreter used for Kokoro (see troubleshooting below).
- **`source`** — currently only `stability-api`.

---

## 🔊 Sources (where music comes from)

Selected by `config.json` `source`, dispatched through the `SOURCES` dict in `radio.py`. Add a new provider by writing a `source_*(prompt, count, duration)` function that returns `(tracks_saved, credits_spent_or_None)` and registering it. A provider that refuses before sending any request returns `NOTHING_SENT` as the credits, and `gen` prints `Cost: 0 credits (nothing sent)`; `None` means a request went out and the cost is unknown. It prints only failures; `gen` prints the summary.

| Source | Status |
|---|---|
| `stability-api` | ✅ **active** — Stable Audio 3, async submit → poll `/results` → save mp3, wav, or both |

---

## 🔐 Network & TLS

`gen` calls the API with Python's `urllib` first and falls back to `curl` only when that request never connects. It used to be curl-only; that changed because `api.stability.ai` now refuses TLS 1.2, and every `curl` on Windows 10 is Schannel-backed with no TLS 1.3, so curl can't reach the API there at all while Python's bundled OpenSSL can.

- Every call sends `User-Agent: ai-radio/1.0`. Cloudflare in front of the API answers Python's default agent with a 403 HTML challenge page — what matters is sending *a* User-Agent, not its value.
- Certificates are verified against the platform trust store unless `stability_api.ca_bundle` points at a PEM. Some Windows root stores fail the chain with `certificate has expired` even though the CA is valid; pointing `ca_bundle` at certifi's `cacert.pem` fixes that.
- When `curl` is used, the API key is handed to it through a config read from stdin (`-K -`), not on its command line where other processes could read it, and form fields go through `--form-string`, so a prompt beginning with `@` or `<` is sent as text rather than read as a file.
- A request that never connects prints `FAILED submit HTTP ???: <error>` with the real DNS/TCP/TLS reason. That's distinct from an HTTP status code sent back by the API.

---

## 🩺 Troubleshooting

**The DJ voice sounds robotic.** That's the Windows SAPI fallback, used when Kokoro isn't installed or a Kokoro render fails. Usual cause: the daemon/hook was launched by an interpreter (e.g. `pythonw.exe`) that lacks `kokoro_onnx`. `dj.py` self-heals by probing for any interpreter that can `import kokoro_onnx, soundfile`, caching it in `.kokoro_python`.
- Read the tail of **`dj_engine.log`** — each utterance logs `engine  detail  py=<interpreter> text`. A `kokoro-fail` line names the exact interpreter + the last line of the error, right before `sapi ROBOTIC FALLBACK - kokoro render failed`. With no Kokoro installed (no model files in `<data dir>/kokoro/`) the pair is `kokoro-skip` then `sapi ROBOTIC FALLBACK - kokoro not installed`, which is expected, not a fault: see **Better voice and prompts**.
- Fix by installing `kokoro-onnx soundfile` into that interpreter, or pin a good one with `dj.python` in `config.json`.

**`gen` says no API key.** Run `radio key` and paste it at the hidden prompt, or export `STABILITY_API_KEY`.

**`gen` fails with `HTTP ???` or `certificate has expired`.** The request never reached the API — see **Network & TLS** above. The text after `HTTP ???:` is the real reason.

**`gen "<prompt>" 3` is refused.** One number after the prompt is a duration, and 3s isn't a track. For three tracks use `radio gen "<prompt>" 3 auto` (or `3 120`).

**`gen` says `Refusing: the prompt is <n> tokens`.** Stable Audio 3 would read only the first 256 tokens and bill you for the whole track. Cut the characters it names; `enhance` rewrites have measured 37–138 tokens. If the message says `about <n> tokens (estimated ...)`, the tokenizer file is missing from `llm/` and the count is a 4-characters-a-token guess (see Requirements).

**`gen` pauses before generating.** With no duration it asks the local model to pick one, a CPU call measured at 8.9–13.5s. Type a duration to skip it.

**`Cost: unknown`.** The credit balance couldn't be read, or hadn't dropped yet when `gen` finished: Stability's balance can lag the result by more than the ~5s `gen` waits. `radio prompts` still records the track; the charge shows up in the account later.

**`enhance` says the enhancer isn't installed.** It needs `llm/bin/llama-cli(.exe)` (or `llama-cli` on PATH) and a `.gguf` in `llm/`. Without them your idea is used as-is, and `gen` picks durations from its keyword rules.

**`enhance` says the instructions are missing.** The file it names is gone or empty: `<data dir>/prompts/enhance.md` if that exists, else the shipped `prompts/enhance.md` beside `radio.py`. Restore it (it's plain markdown), or delete an empty data-directory copy so the shipped one is used; until then your idea is used as-is.

**Enhanced prompts come out wrong.** Copy the shipped `prompts/enhance.md` to `<data dir>/prompts/enhance.md` (if you haven't already) and edit that copy; the next `enhance` uses it. Output varies run to run (temperature 0.7), so judge a change over a few runs, not one. If you reword the two fixed replies in it, update `ENH_NOT_PROMPTS` in `radio.py` to match, or `egen` will stop recognising them and send them to Stable Audio as prompts.

**`egen` says `Nothing generated.`** The enhancer answered with a message, not a prompt (see `enhance` above). Rephrase the idea: drop the vocal request, or resolve the contradiction it asked about.

**`play`/`status` says no audio player.** Install `mpv` or `ffmpeg` (`ffplay`). On Windows, ffmpeg at `C:\ffmpeg\bin\` is auto-detected even if not on PATH.

**Changed `folder` but the old music keeps playing.** The daemon reads the folder once at start — `radio stop` then `radio play`.

**A playlist plays nothing from my selection / fell back to shuffle.** Playlist names resolve against the current library folder. `radio playlist` shows what still resolves; `radio list` then `radio play <numbers>` rebuilds it.

**My `say` line came late.** The DJ queue is FIFO and one line is read per track; `radio status` shows how many are ahead of yours. Only a `play --say` sign-on jumps the queue.

**No radio in the statusline.** A plugin can't set `statusLine`; add the snippet from **🚀 Install** (step 4) to `~/.claude/settings.json`. `<data dir>/statusline.py` appears after the first session start with the plugin installed.

**Statusline is stale.** `nowplaying.txt` is rewritten the moment a track starts, but Claude Code only re-runs the statusline on each turn and every `statusLine.refreshInterval` seconds in `~/.claude/settings.json`, so the display can lag that long. `radio status` is always current; lower the interval for a fresher line.

**Something in the DJ pipeline is broken but music keeps playing.** By design — nearly all errors are swallowed so a dead DJ, model or TTS engine never takes down playback. `dj_engine.log` is your observability seam; prefer reading it over adding prints (the detached daemon discards stdout).

---

## 🗂️ Layout

The code and the data directory are the same folder in the default install (`~/.claude/radio`); with a clone elsewhere or `AI_RADIO_HOME` set, the first group lives with the code and the rest in the data directory.

```
<code>/
├── radio.py             # canonical core: daemon, playback, sources, commands
├── dj.py                # DJ voice engine: the TTS fallback chain
├── kokoro_tts.py        # Kokoro-82M wrapper (the only file allowed 3rd-party deps)
├── statusline.py        # statusline segment; copied into the data directory on session start
├── prompts/
│   └── enhance.md       # the shipped enhancer instructions (a data-directory copy overrides it)
├── .claude-plugin/      # plugin.json (the ai-radio manifest) + marketplace.json (digitalbyte)
├── skills/radio/SKILL.md  # the skill: /ai-radio:radio (or /radio on the manual install)
├── hooks/               # hooks.json (SessionStart + Stop) + radio-hook.sh (the launcher)
├── kokoro/.gitkeep, llm/.gitkeep  # mark where models go on the manual route (see "Where things live")
├── readme_check.py      # README drift check (see "Keeping this README true")
├── release_check.py     # pre-release scan: no home paths, personal emails, keys or oversized files
├── smoke_test.py        # runs the read-mostly commands against a throwaway data directory
├── tests/               # unit tests: python -m unittest discover tests
├── config.example.json  # the defaults, to copy into the data directory as config.json
├── LICENSE, THIRD_PARTY_NOTICES.md, SECURITY.md, CHANGELOG.md
├── Qwen3_4B_SA3_Enhancer_Setup_v1.0.md  # design doc that prompts/enhance.md is copied from
├── .github/             # workflows/ci.yml (tests, smoke test, README drift, release check, plugin validate),
│                        #   dependabot.yml (keeps those Actions current), ISSUE_TEMPLATE/bug_report.md
├── .gitignore, .gitattributes  # what never ships; LF line endings for the hook script
├── AGENTS.md            # rules for any agent changing the radio (Claude Code, Codex, ...)
└── .claude/CLAUDE.md    # architecture notes for Claude Code sessions (imports AGENTS.md)

<data dir>/              # ~/.claude/radio, or $AI_RADIO_HOME
├── config.json          # settings overlay (see above)
├── .key                 # Stability API key (written by `radio key`)
├── statusline.py        # copied here by the SessionStart hook; point statusLine at it
├── prompts/enhance.md   # optional: your tuned enhancer instructions (wins over the shipped copy)
├── output/              # default music library — source of truth, no DB/index (see library_dir)
│   ├── _archive/        # archived tracks; lives inside whichever folder is the library
│   ├── _wav/            # WAV masters from `radio format wav+mp3` (the MP3 beside them plays)
│   └── bad song/        # `radio drop` rejects from every folder (one shared pile)
├── llm/                 # local model for enhance/egen and gen's duration pick: bin/llama-cli(.exe) + a .gguf
│   └── t5gemma-tokenizer.json  # SA3's tokenizer, for the exact 256-token prompt check (optional)
├── kokoro/              # Kokoro model + voices (kokoro-v1.0.fp16.onnx, voices-v1.0.bin)
├── queue/               # one .txt file per pending DJ line (FIFO; `play --say` lines jump it)
├── state.json           # status + daemon/player PIDs + live position (player_started/_offset)
├── nowplaying.txt       # what the statusline reads
├── playlist.json        # active playlist: ordered track names (absent = shuffle)
├── last_list.json       # order shown by the last `radio list` (what selection numbers mean)
├── last_archive.json    # same, for `radio unarchive` numbering
├── prompt_history.jsonl # every generation + every enhance rewrite: prompt, idea, duration, file (append-only)
├── resume.json          # pause point {track, offset} — consumed on the next play
├── breaking.txt         # pending breaking-news line — consumed by the daemon mid-track
├── dj_speaking.lock     # held while an idle announcement is being spoken
├── .kokoro_python       # cached path of an interpreter that can import kokoro_onnx
├── _dj.wav, _dj_<pid>.wav  # scratch TTS renders (per-process ones are deleted after playing)
└── dj_engine.log        # which TTS engine spoke, and why (debug voice issues here)
```

`.readme_sync/` (next to the code) is `readme_check.py`'s snapshot of the code as of the last `--confirm`. Everything in the data directory, plus the models, is listed in `.gitignore`, and `release_check.py` refuses a tree that still contains a key, a home-directory path, a personal email address, a file over 5 MB, or any string listed in your own `.release_markers` (one per line, next to the code, never committed: put your username and email there).

---

## 📝 Keeping this README true

This README is the **source of truth** for how the radio behaves. Any change to `radio.py`, `dj.py`, `kokoro_tts.py` or `readme_check.py` that alters a command, alias, keyword, flag, default, file, or user-visible behaviour updates this file **in the same change**. The working rules for agents are in `AGENTS.md`.

`readme_check.py` (stdlib-only) checks it mechanically:

```bash
python readme_check.py              # drift + unreviewed code changes; exit 1 if either
python readme_check.py --diff       # what the code changed since README was last confirmed
python readme_check.py --confirm    # after README is updated: records the code as reviewed
```

- **Drift** is anything it can pull from the code that this README doesn't show. That covers every command and alias, each command's accepted keywords (in that command's own section), the config block key for key and value for value, every file the code creates, `dj.py` and `kokoro_tts.py` flags, the player order, the duration-pick rules, and coverage of every command by the skill in `skills/radio/SKILL.md`.
- **Unreviewed** means the code changed since the last `--confirm`. A check can't read meaning, so a changed behaviour passes the drift check. It stays flagged until someone reads `--diff`, updates this file, and confirms. `--confirm` refuses while any drift remains.
- **CI runs only the drift layer.** `.github/workflows/ci.yml` calls `readme_check.drift()` directly, because the `.readme_sync/` snapshot behind the unreviewed layer is gitignored and a fresh clone would report every watched file as unreviewed. The unreviewed layer is a per-checkout gate for whoever changes the code; the unit tests and `smoke_test.py` run in CI as well.
