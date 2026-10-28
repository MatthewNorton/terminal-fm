# Terminal FM

https://github.com/user-attachments/assets/24f664ad-429b-4580-86bf-4ae5383ff785

**Demo:** 67 seconds of setup, making a track, the DJ and a skip. It starts muted, so turn the sound on. The parts on their own: [a generated track](examples/lofi-hip-hop-track.mp3), [the DJ voice](examples/dj-voice.wav) and [the video file](examples/terminal-fm-demo.mp4).

Background music for your Claude Code sessions. Terminal FM makes tracks with Stability AI's Stable Audio 3, keeps them in a library on your computer and plays them on shuffle while you work. Between songs, a DJ reads out what Claude just finished.

You control it by talking to Claude (*"play the radio"*, *"skip this one"*, *"make me some synthwave"*) or with `/tfm` commands. It runs on Windows, macOS and Linux, and the core is plain Python with nothing to `pip install`.

**Contents:** [Install](#install) · [Optional extras](#optional-extras) · [Using it](#using-it) · [Commands](#commands) · [Settings](#settings) · [Files](#files) · [Manual install](#manual-install) · [Contributing](#contributing) · [Troubleshooting](#troubleshooting)

---

## Install

### Requirements

Check each one in a terminal (PowerShell on Windows). If a check fails, run the install command, then close and reopen the terminal.

| You need | Check | Install |
|---|---|---|
| **Python 3.11 or newer** | Windows: `python --version` or `py --version`<br>macOS / Linux: `python3 --version` | Windows: `winget install Python.Python.3.14`<br>macOS: `brew install python`<br>Ubuntu 24.04+ / Debian 12+: `sudo apt install python3` (Ubuntu 22.04's is 3.10, too old) |
| **An audio player** | `ffplay -version` or `mpv --version` | Windows: `winget install Gyan.FFmpeg`<br>macOS: nothing, `afplay` is built in<br>Ubuntu / Debian: `sudo apt install ffmpeg` |
| **A Stability AI API key** | | Create one at <https://platform.stability.ai>. Each track costs credits (26 when checked in September 2026); `gen` prints the exact cost. |
| **Git for Windows** (Windows only) | `git --version` | `winget install Git.Git`. Claude Code runs the plugin's hooks with its Git Bash; without it, the DJ never hears what Claude finished. |

**Why 3.11:** it's the oldest Python that still gets security fixes. `setup` flags anything older.

**Want the DJ voice?** The optional [DJ voice](#dj-voice) needs Python 3.13 or older, so install 3.13 rather than a newer Python.

**Which player plays:** First found wins: `mpv` › `ffplay` › `afplay` (macOS) › `mpg123` › `cvlc`. Only `mpv`, `ffplay` and `cvlc` can resume a paused or interrupted track mid-song; the others restart it from the top.

### Steps

1. **Add the plugin.** In a terminal:
   ```
   claude plugin marketplace add MatthewNorton/terminal-fm
   claude plugin install terminal-fm@digitalbyte
   ```
2. **Start a new Claude Code session and run the setup wizard:**
   ```
   /tfm setup
   ```
   It shows a checklist, then spells out the next step. Do that step, run `/tfm setup` again, and repeat until it says `Ready`.

The wizard walks you through these:

| Step | What you do |
|---|---|
| 1. Python | Nothing, if it's 3.11 or newer. On an older one, install a newer Python (see Requirements). |
| 2. Audio player | Install one (see Requirements). |
| 3. Stability API key | Run the command the wizard prints in a terminal outside Claude Code (below). |
| 4. Session hooks | Start a new Claude Code session. On Windows, install Git for Windows first. |
| FFmpeg (only after `format wav+mp3`) | Install FFmpeg. |
| 5. First track | `/tfm gen "warm lo-fi hip hop, rhodes, 80 BPM"`, then `/tfm play`. |

The key step looks like this, with your own paths:

```
Step 3 of 5: Stability API key

  1. Get a key at https://platform.stability.ai
  2. Open a terminal outside Claude Code and run:

       python3 /path/to/radio.py key

  3. Paste the key when asked (it stays hidden) and press Enter.
  4. Run /tfm setup again to check.
  Or set the STABILITY_API_KEY environment variable instead.
```

### Update or uninstall

| To | Run |
|---|---|
| Update | `claude plugin marketplace update digitalbyte`, then `claude plugin update terminal-fm@digitalbyte`, then restart Claude Code |
| Uninstall | `claude plugin uninstall terminal-fm@digitalbyte` |

Neither touches your library, key or settings in `~/.claude/terminal-fm` (see [Files](#files)).

---

## Optional extras

Everything works without these. Each extra has a setup page, `/tfm setup <name>`, that prints its steps with your own paths and tells you whether it's installed.

| Extra | What you get | Without it | Setup page |
|---|---|---|---|
| Statusline | The playing track under Claude Code's prompt | Ask `/tfm status` | `/tfm setup statusline` |
| DJ voice | A natural voice (Kokoro-82M) | Your system's voice | `/tfm setup voice` |
| Prompt enhancer | `enhance` and `egen`, and better track lengths | Your idea is used as written, and keywords pick lengths | `/tfm setup enhancer` |
| Exact token count | An exact check of the 256-token prompt limit | An estimate of 4 characters a token | `/tfm setup tokens` |

### Statusline

1. Finish `/tfm setup` first: the session hooks put `statusline.py` in place.
2. Run `/tfm setup statusline`. It prints one line to add to `~/.claude/settings.json`, such as:
   ```
   "statusLine": {"type": "command", "command": "python3 /home/<you>/.claude/terminal-fm/statusline.py"}
   ```
3. Paste it inside the file's outer `{ }`, with a comma after the line before it, and save. Or ask Claude to add it for you.

**Already have your own statusline?** Have it print the text of `~/.claude/terminal-fm/nowplaying.txt`. It reads `Terminal FM > <track>` while a track plays and `Terminal FM | <status>` otherwise, so a `>` means playing.

### DJ voice

1. Download `kokoro-v1.0.fp16.onnx` and `voices-v1.0.bin` from <https://github.com/thewh1teagle/kokoro-onnx/releases/tag/model-files-v1.1>.
2. Put both files in `~/.claude/terminal-fm/kokoro/`.
3. On Python 3.13 or older, in a terminal: `pip install -U "kokoro-onnx>=0.6" soundfile`
4. On a newer one, run `/tfm setup voice`. It prints the steps to install a Python 3.13 beside it on your system.

The radio finds a Python that has these packages by itself. To pin one, set `dj.python` in `config.json`. On Linux without a system voice, `sudo apt install espeak-ng` gives a basic one.

### Prompt enhancer

1. Download the `Q4_K_M` file of Qwen3-4B-Instruct-2507 (about 2.5 GB) from <https://huggingface.co/unsloth/Qwen3-4B-Instruct-2507-GGUF>.
2. Put it in `~/.claude/terminal-fm/llm/`. Keep only one `.gguf` there.
3. Download the newest llama.cpp release for your system from <https://github.com/ggml-org/llama.cpp/releases>.
4. Copy `llama-cli` (`llama-cli.exe` on Windows) and the files beside it into `~/.claude/terminal-fm/llm/bin/`. A `llama-cli` on your PATH works too.

It runs on the CPU and exits when it's done, so it doesn't use your GPU or keep memory.

### Exact token count

1. Sign in to Hugging Face and accept Google's Gemma terms at <https://huggingface.co/google/t5gemma-b-b-ul2>.
2. Download its `tokenizer.json`.
3. Save it as `~/.claude/terminal-fm/llm/t5gemma-tokenizer.json`.

Licenses for the extras are in `THIRD_PARTY_NOTICES.md`.

---

## Using it

Ask Claude in your own words:

- *"play the radio"* · *"skip this one"* · *"get rid of this song"* · *"what's playing?"*
- *"make me three synthwave tracks"* · *"what prompt did I use for the car track?"*

**Name a genre** to hear it: `/tfm smooth jazz` plays the tracks in your library that fit. If none do, Claude offers to make some, which costs credits.

`/tfm` is short for `/terminal-fm:tfm`.

---

## Commands

Type `/tfm <command>` in Claude Code. Every command has a short key, so `/tfm g "lo-fi beats" 3 auto` is the same as `/tfm gen "lo-fi beats" 3 auto`. In a terminal, run `python3 <path to radio.py> <command>` instead (`python` on Windows); the key step of `/tfm setup` shows that path.

### Playback: `play` `pause` `stop` `skip` `status`

| Command | Key | What it does |
|---|---|---|
| `play` (also `resume`) | `p` | Start the radio, or resume a paused track where it stopped. The music plays in the background. |
| `play 1,3,5-8` | | Play only those tracks from `list`, in that order, on a loop. |
| `play --say "<line>"` | | Start with a DJ sign-on. |
| `pause` | `pa` | Stop, remembering the track and position. |
| `stop` | `s` | Stop and forget the pause point. A playlist is kept. |
| `skip` (also `next`) | `n` `sk` | Play the next track. |
| `status` | `st` | What's playing, and the radio's state. `/tfm` alone runs this. |

### Library: `list` `playlist` `shuffle` `folder` `archive` `drop` `unarchive`

| Command | Key | What it does |
|---|---|---|
| `list` | `l` | Number the tracks. The numbers stay valid for your next command. `*` marks playlist tracks. |
| `playlist 1,3,5-8` | `pl` | Same as `play 1,3,5-8`. `playlist` alone shows the playlist. |
| `playlist clear` | | Back to shuffle. `off`, `none`, `all`, `reset` and `shuffle` work too. |
| `shuffle` | `sh` | Back to shuffling the whole library. |
| `folder <path>` (also `library`) | `f` | Play from another folder, created if needed. `folder` alone shows the current one. |
| `folder default` | | Back to `~/.claude/terminal-fm/output`. `reset`, `clear` and `none` work too. |
| `archive` | `a` | Move the playing track into the library's `_archive` subfolder, and skip to the next. |
| `archive 3,7` | | Archive tracks by their `list` number. `archive list` numbers the library first. |
| `archive show` | | List the archive. `archived` and `ls` work too. |
| `drop` | `d` | Move the playing track into the shared `output/bad song` folder. |
| `unarchive` (also `restore`) | `u` | Number the archive. `unarchive 1,3` or `unarchive all` (also `*`, `everything`) puts tracks back. |

Picking tracks by number:

| You type | Plays |
|---|---|
| `1,3,5-8` | 1, 3, 5, 6, 7, 8 |
| `8-5` | 8, 7, 6, 5 |
| `3,3` | 3, twice |

- Commas or spaces both work, and numbers past the end are ignored.
- Nothing is ever deleted. Archived and dropped tracks leave the playlist; restored ones rejoin the shuffle only.
- Only the `.mp3` and `.wav` files directly in the folder play, not its subfolders.
- `folder` accepts `~` and environment variables, and a relative path starts from the data folder. A playing radio keeps the old folder until you `stop` and `play`.
- To hear your rejects: `folder "output/bad song"`.

### Making music: `gen` `enhance` `egen` `prompts` `format`

| Command | Key | What it does | Costs credits |
|---|---|---|---|
| `gen "<prompt>"` | `g` | Generate tracks. | Yes |
| `enhance "<idea>"` | `e` | Rewrite a rough idea as a full prompt, with the prompt enhancer extra. | No |
| `egen "<idea>"` | `eg` | `enhance`, then `gen` the result. | Yes |
| `prompts` (also `history`, `prompt-history`) | `pr` | Your newest 20 prompts. `prompts all` shows every one, `prompts <text>` searches, and `prompts 4` shows one in full with a ready-to-run `gen` line. | No |
| `format mp3` / `wav` / `wav+mp3` (also `filetype`) | `ft` | The file type new tracks are saved as. `format` alone shows it. | No |

**Numbers after the prompt** (the same for `gen` and `egen`):

| You type | You get |
|---|---|
| `gen "lo-fi"` | 1 track, its length picked to suit the prompt |
| `gen "lo-fi" 120` | 1 track, 120 seconds |
| `gen "lo-fi" 3 120` | 3 tracks, 120 seconds each |
| `gen "lo-fi" 3 auto` | 3 tracks, their length picked |

- One number is always a length, never a count. A lone number under 10 is refused as a likely mistake; for 3 tracks, type `gen "<prompt>" 3 auto`.
- More than 20 tracks asks you to type `yes`.

**File names.** A new track is named after the start of its prompt, up to 60 characters and cut at a whole word, then the date, time and its number: `warm lo-fi hip hop, rhodes, vinyl crackle, 80 BPM` is saved as `warm-lo-fi-hip-hop-rhodes-vinyl-crackle-80-bpm-20261028-190000-1.mp3`. That stays well inside the file name and path limits of Windows, macOS and Linux. Tracks made before this keep their names.

**How the length is picked** when you don't type one:

1. A length written in the prompt wins: "90 second trailer" gets 90s, while "80s synthwave" stays a decade.
2. Otherwise the prompt enhancer's model picks one between 1–380s, the same for the same prompt every time.
3. Without the enhancer, keywords decide (below), and with no match the length is **120s** (`stability_api.duration`).

<details>
<summary>The keyword rules, checked in this order</summary>

- `notification` `sting` `stinger` → **5s**
- `jingle` `bumper` → **15s**
- `intro` `outro` `commercial` `advert` → **30s**
- `ambient` `drone` `meditation` `sleep` `soundscape` → **300s**
- `techno` `trance` `progressive` → **240s**
- `trailer` `punk` `hardcore` → **120s**
- `synthwave` `retrowave` `lo-fi` `lofi` `lo fi` `jazz` `hip hop` `hip-hop` `chillhop` `funk` `soul` `house` `rock` `pop` → **150s**

</details>

New tracks join the shuffle without a restart.

**Prompts over 256 tokens are refused before anything is spent.** Stable Audio 3 would ignore the rest and still bill the track. The message says how much to cut.

```
/tfm gen "warm lo-fi hip hop, rhodes, vinyl crackle, 80 BPM"     # one track, length picked
/tfm gen "driving synthwave, neon, analog bass, 120 BPM" 3 110   # three 110s tracks
/tfm gen "slow ambient drone with a long build" 2 auto           # two tracks, length picked
```

**About `enhance` and `egen`:**

- The rewrite is one line: style, instruments, production, mood, then key and BPM. It never names artists, and turns "no drums" into "beatless". A tag such as `TrackType: Instrument` in your idea stays at the front.
- `egen` stops with `Nothing generated.`, spending nothing, when the enhancer answers instead of writing a prompt (sung lyrics or speech, which Stable Audio 3 can't make; an idea that contradicts itself; a rewrite over 256 tokens twice) or when the rewrite both describes and denies drums, vocals, reverb or bass (a `Conflict:` line).
- Every rewrite is saved to `prompts`, marked `e`.
- To change how it writes, copy `prompts/enhance.md` from the plugin to `~/.claude/terminal-fm/prompts/enhance.md` and edit your copy. Plugin updates replace the original.

**Marks in `prompts`:** `a` archived · `b` in `bad song` · `x` file not found · `e` a rewrite never generated. Entry numbers never change.

**File types:**

| `format` | Saves | Note |
|---|---|---|
| `mp3` (default) | MP3 | |
| `wav` | WAV, about 10.6 MB a minute | `mpg123` can't play WAV |
| `wav+mp3` (or `mp3+wav`) | Both, for one charge: the MP3 plays, the WAV goes in the library's `_wav` subfolder | Needs FFmpeg |

### DJ: `say` `announce` `breaking`

| Command | Key | What it does |
|---|---|---|
| `say "<line>"` (also `dj`) | | Queue a line for the DJ, read word for word in the next gap between tracks. |
| `announce on` / `off` | `an` | Also speak Claude's updates while the music is stopped. |
| `breaking on` / `off` | `b` | Let an update interrupt the song, which then resumes where it was. |

- When Claude finishes a turn, its update normally waits for the next gap between tracks. Both settings are off by default.
- `on` also takes `enable`, `enabled`, `true`, `yes` or `1`, and `off` takes `disable`, `disabled`, `false`, `no` or `0`. With neither, the command shows the setting.
- `announce breaking on` works too, as do `announce break` and `announce interrupt`.
- The DJ uses the first voice that works: Kokoro-82M → Piper → macOS `say` → Windows SAPI → `espeak`. Each line spoken is logged to `~/.claude/terminal-fm/dj_engine.log`.

### Setup: `setup` `key`

| Command | Key | What it does |
|---|---|---|
| `setup` | `se` | The checklist, then the next step spelled out. It changes nothing. |
| `setup statusline` / `voice` / `enhancer` / `tokens` | | The steps to add that extra, with your paths. |
| `key` | `k` | Store your API key, typed at a hidden prompt. That needs your own terminal, so in Claude Code it prints the command to run there. |
| `key show` | | Whether a key is set and where it came from. It never shows any of the key. |
| `key clear` | | Delete the stored key. `delete` and `remove` work too. |

The key is saved to `~/.claude/terminal-fm/.key`, readable only by you on macOS and Linux. A stored key wins over `STABILITY_API_KEY`. The key is never accepted as a command-line argument.

<details>
<summary>Internal commands</summary>

### `hook` and `__daemon`

`hook SessionStart` and `hook Stop` are what the plugin's hooks run, through `hooks/radio-hook.sh`, which finds a Python 3.11+ first. With no Python at session start, it gives Claude the install command to pass on. At session start the hook copies `statusline.py` into the data folder and notes the time for `setup`. When Claude finishes a turn, it queues, speaks or interrupts as `announce` and `breaking` say, using Claude's last message trimmed to its main point.

`__daemon` is the playback loop that `play` starts. Never run it by hand.

</details>

---

## Settings

Settings live in `~/.claude/terminal-fm/config.json`. Put in only what you change, and everything else keeps its default: `{"dj": {"kokoro_voice": "af_bella"}}` changes just the voice. The defaults (`config.example.json` in the repo is a copy):

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

| Setting | What it does |
|---|---|
| `volume` | 0–100, used by `mpv`, `ffplay` and `afplay` |
| `library_dir` | The folder to play from; `""` means `~/.claude/terminal-fm/output`. Set it with `folder`. |
| `stability_api.duration` | The length when nothing else decides (see `gen`) |
| `stability_api.output_format` | Set it with `format` |
| `stability_api.ca_bundle` | A PEM file to check the API's certificate against, such as certifi's `cacert.pem`; `""` uses your system's |
| `stability_api.steps` | Fixed at 8 for Stable Audio 3 |
| `stability_api.balance_url` | Read before and after each `gen` to measure its cost |
| `stability_api.submit_url`, `results_url`, `model` | The Stable Audio 3 API. Leave them as they are. |
| `dj.announce_when_idle`, `dj.breaking_news` | Set them with `announce` and `breaking` |
| `dj.kokoro_voice` | Any Kokoro voice: `am_michael`, `af_bella`, … |
| `dj.voice` | A Piper `.onnx` voice. `"auto"` takes the first `*.onnx` in `~/.claude/terminal-fm/` or `~/.claude/terminal-fm/voices/`. |
| `dj.rate` | The Windows SAPI speaking rate |
| `dj.python` | The Python to run Kokoro with |
| `source` | Where music comes from. `stability-api` is the only one. |

Commands that save a setting refuse to overwrite a `config.json` that isn't valid JSON.

---

## Files

Everything the radio creates lives in its data folder, `~/.claude/terminal-fm`. To keep it somewhere else, set the `TERMINAL_FM_HOME` environment variable. The plugin's own code sits in Claude Code's plugin cache.

```
~/.claude/terminal-fm/
├── output/                 # the library: every .mp3 and .wav here plays
│   ├── _archive/           # tracks moved out by `archive`
│   ├── _wav/               # WAV masters from `format wav+mp3`
│   └── bad song/           # `drop` rejects, from every folder
├── .key                    # your API key
├── config.json             # your settings
├── prompt_history.jsonl    # every prompt and rewrite (`prompts`)
├── statusline.py           # copied here at session start, for the statusline
├── prompts/enhance.md      # optional: your own prompt-enhancer instructions
├── kokoro/                 # optional: the Kokoro voice files
├── llm/                    # optional: llama-cli in bin/, the .gguf model, t5gemma-tokenizer.json
└── dj_engine.log           # which voice spoke, and why
```

The only network requests go to the Stability AI API (the three URLs in `config.json`), with `User-Agent: terminal-fm/1.0`.

<details>
<summary>The radio's own bookkeeping files</summary>

`state.json`, `nowplaying.txt`, `queue/`, `playlist.json`, `resume.json`, `breaking.txt`, `last_list.json`, `last_archive.json`, `dj_speaking.lock`, `.hook_seen`, `.kokoro_python`, and the voice renders `_dj.wav` and `_dj_<pid>.wav`.

</details>

---

## Manual install

Without the plugin:

1. **Clone the repo into the data folder:**
   ```
   git clone https://github.com/MatthewNorton/terminal-fm ~/.claude/terminal-fm
   ```
   In PowerShell: `git clone https://github.com/MatthewNorton/terminal-fm "$HOME\.claude\terminal-fm"`
2. **Copy the skill:** copy `skills/tfm/` to `~/.claude/skills/tfm/`. In the copy's `SKILL.md`, replace every `${CLAUDE_PLUGIN_ROOT}` with the clone's full path in forward slashes, such as `C:/Users/<you>/.claude/terminal-fm`.
3. **Add the hooks** to `~/.claude/settings.json`. On Windows, write `C:/Users/<you>/.claude/terminal-fm/...` for `~/.claude/terminal-fm/...`.
   ```json
   "hooks": {
     "SessionStart": [{"matcher": "startup|resume", "hooks": [{"type": "command", "command": "sh ~/.claude/terminal-fm/hooks/radio-hook.sh SessionStart", "timeout": 30}]}],
     "Stop": [{"hooks": [{"type": "command", "command": "sh ~/.claude/terminal-fm/hooks/radio-hook.sh Stop", "async": true, "timeout": 60}]}]
   }
   ```
4. **Start a new Claude Code session and run `/tfm setup`.**

**Switching to the plugin later:** first remove those hook entries and `~/.claude/skills/tfm/`, or every hook runs twice.

> [!CAUTION]
> **Never add the marketplace from your clone** (`claude plugin marketplace add ~/.claude/terminal-fm`). Claude Code would copy the whole folder into its plugin cache, **including your API key** and your library. Always install from GitHub, as in [Install](#install).

---

## Contributing

`README.md` must match the code: `python readme_check.py` checks it, and CI runs it. The rules for any change are in `AGENTS.md`, and the architecture notes in `.claude/CLAUDE.md`.

```
python -m unittest discover tests     # unit tests
python smoke_test.py                  # the read-only commands against a throwaway data folder
python readme_check.py                # README drift; --diff and --confirm after a code change
python release_check.py               # before publishing: home paths, personal emails, keys, big files
claude plugin validate . --strict     # the plugin manifest and hooks
claude --plugin-dir .                 # try a checkout for one session without installing it
```

`release_check.py` also refuses any string listed in an untracked `.release_markers` file beside it: put your own username and email there.

<details>
<summary>Running the voice scripts directly</summary>

```
python3 dj.py say --text "hello"                    # or: --file <path>, or text on stdin
echo "on the ones and twos" | python3 kokoro_tts.py --out out.wav --voice am_michael
```

`kokoro_tts.py` takes `--text` (default: stdin), `--voice` (`am_michael`), `--speed` (`1.0`), `--lang` (`en-us`), `--out` (`<data dir>/_dj.wav`), `--model` (the first of `kokoro-v1.0.fp16.onnx`, `kokoro-v1.0.onnx` or `kokoro-v1.0.int8.onnx` in `kokoro/`) and `--voices` (`kokoro/voices-v1.0.bin`).

</details>

Security reports: `SECURITY.md`. License: MIT (`LICENSE`).

---

## Troubleshooting

Start with `/tfm setup`. If that doesn't explain it:

| Problem | Fix |
|---|---|
| Windows says `Python was not found` | That message comes from a Microsoft Store shortcut, not from Python. Install Python (`winget install Python.Python.3.14`), reopen the terminal and restart Claude Code. |
| No audio player | Install one (see [Requirements](#requirements)). On Windows, `C:\ffmpeg\bin\` is checked even when it isn't on PATH. |
| `setup` says the session hooks haven't run | Start a new Claude Code session. On Windows, install Git for Windows (`winget install Git.Git`) and restart. Claude Code looks for `bash.exe` beside `git`, or wherever `CLAUDE_CODE_GIT_BASH_PATH` points. |
| No track in the statusline | Run `/tfm setup statusline`. The statusline refreshes each turn and every `statusLine.refreshInterval` seconds, so it can lag; `/tfm status` is always current. |
| The DJ sounds robotic | That's Windows SAPI, used when Kokoro isn't installed or fails. The end of `dj_engine.log` says which: `kokoro not installed`, or a `kokoro-fail` line naming the Python and the error. Install the voice's packages as [DJ voice](#dj-voice) shows, or point `dj.python` at a Python that has them. |
| `gen "<prompt>" 3` is refused | One number is a length, and 3 seconds isn't a track. For three tracks: `gen "<prompt>" 3 auto`. |
| `gen` refuses a long prompt | Cut what the message says, or let `enhance` rewrite it. `estimated` in the message means the exact token count isn't installed (`/tfm setup tokens`). |
| `gen` pauses before generating | With no length typed, the enhancer's model picks one, which took 9 to 14 seconds on a CPU in testing. Type a length to skip it. |
| `Cost: unknown` | Your Stability balance hadn't updated when `gen` finished. The charge shows up later. |
| `gen` fails with `HTTP ???` or `certificate has expired` | The request never reached the API, and the text after it is the reason. For `certificate has expired`, set `stability_api.ca_bundle` to certifi's `cacert.pem`. |
| `egen` says `Nothing generated.` | The enhancer answered instead of writing a prompt. Rephrase: drop the vocals, or settle what it asked about. |
| Changed `folder` but the old music plays on | `/tfm stop`, then `/tfm play`. |
| A `say` line came late | The DJ reads one queued line per gap between tracks. `/tfm status` shows how many are waiting. |
| The DJ broke but the music plays on | That's deliberate: DJ errors never stop the music. `dj_engine.log` shows what went wrong. |
| A setting says `Not saved: ... is not valid JSON` | Fix `config.json` or delete it. |
