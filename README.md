# 🎙️ Terminal FM

Background music for your Claude Code sessions. Terminal FM generates tracks with Stability AI's Stable Audio 3, keeps them in a local library and plays them on shuffle for as long as you like. Between songs a DJ reads out what Claude just finished. You drive it by talking to Claude: *"play the radio"*, *"skip this one"*, *"make me some synthwave"*.

It runs on Windows, macOS and Linux. The core is plain Python with nothing to `pip install`.

---

## ✅ Before you start

You need four things. Check each one in a terminal (PowerShell on Windows); if a check fails, run the install command, then close and reopen the terminal.

| You need | Check | Install |
|---|---|---|
| **Python 3.8 or newer** | Windows: `python --version` (or `py --version`)<br>macOS / Linux: `python3 --version` | Windows: `winget install Python.Python.3.12`<br>macOS: `brew install python`<br>Ubuntu / Debian: `sudo apt install python3` |
| **An audio player** | `ffplay -version` or `mpv --version` | Windows: `winget install Gyan.FFmpeg`<br>macOS: nothing to do, `afplay` is built in<br>Ubuntu / Debian: `sudo apt install ffmpeg` |
| **A Stability AI API key** | | Sign up at <https://platform.stability.ai> and create a key. Each generated track costs credits: 26 when checked in September 2026, and `gen` prints the exact cost. |
| **Git for Windows** (Windows only) | `git --version` | `winget install Git.Git`. Claude Code runs the radio's hooks with its Git Bash; without it the DJ never hears what Claude finished. |

On Windows, `Python was not found; run without arguments to install from the Microsoft Store` means Python is **not** installed: that message comes from a Windows shortcut, not from Python.

The radio uses the first player it finds. First found wins: `mpv` › `ffplay` › `afplay` (macOS) › `mpg123` › `cvlc`. Only `mpv`, `ffplay` and `cvlc` can resume a paused track mid-song (on macOS, `brew install mpv`).

---

## 🚀 Install

1. **Add the plugin**, in a terminal:
   ```
   claude plugin marketplace add MatthewNorton/terminal-fm
   claude plugin install terminal-fm@digitalbyte
   ```
2. **Start a new Claude Code session** and type:
   ```
   /tfm setup
   ```
   You get a checklist: `ok` for what's ready, and `NEEDED` with the exact fix for what isn't.
3. **Store your API key.** `setup` prints a command for this. Run it in your own terminal, not inside Claude Code, because the key is typed at a hidden prompt. It looks like this, with your own paths:
   ```
   python3 ~/.claude/plugins/cache/digitalbyte/terminal-fm/<version>/radio.py key
   ```
   Paste the key and press Enter. Setting `STABILITY_API_KEY` in the environment Claude Code starts from works too.
4. **Make a track and play it**, back in Claude Code:
   ```
   /tfm gen "warm lo-fi hip hop, rhodes, vinyl crackle, 80 BPM"
   /tfm play
   ```
   `gen` prints the length it chose, the exact prompt it sent and what it cost. `play` starts the music in the background, so you can keep working.
5. **Optional: show the track in your statusline.** A plugin can't set the statusline itself, so `setup` prints the line to add to `~/.claude/settings.json`.

Something not working? Run `/tfm setup` again, then see **Troubleshooting**.

**Updating:** `claude plugin marketplace update digitalbyte`, then `claude plugin update terminal-fm@digitalbyte`, then restart Claude Code. **Uninstalling:** `claude plugin uninstall terminal-fm@digitalbyte`. Your library, key and settings live in the data folder (see **Files**), which neither touches.

---

## 🎧 Using it

Ask Claude in your own words, or type `/tfm <command>`. Each command has a short key that works anywhere the full name does, arguments included: `/tfm g "lo-fi beats" 3 auto`.

| Command | Key | What it does |
|---|---|---|
| `play` (also `resume`) | `p` | Start the radio, or resume a paused track where it stopped. `play 1,3,5-8` plays just those tracks from `list`, in order. |
| `pause` | `pa` | Stop, remembering the track and position. |
| `stop` | `s` | Stop, and forget the pause point. |
| `skip` (also `next`) | `n` `sk` | Next track. |
| `status` | `st` | What's playing, the folder, playlist or shuffle, and the player. |
| `setup` | `se` | What's ready, what's missing, and how to fix it. |
| `list` | `l` | The library, numbered. |
| `playlist` | `pl` | Show the playlist, set one (`pl 1,3,5-8`), or `pl clear` to shuffle again. |
| `shuffle` | `sh` | Back to shuffling the whole library. |
| `gen "<prompt>"` | `g` | Generate tracks. Spends credits. |
| `enhance "<idea>"` | `e` | Turn a rough idea into a full prompt with a local model. Free; an optional extra. |
| `egen "<idea>"` | `eg` | `enhance`, then `gen`. Spends credits. |
| `archive` | `a` | Move the playing track (or `a 3,7`) out of rotation. Nothing is deleted. |
| `drop` | `d` | Move the playing track to the shared `bad song` folder. |
| `unarchive` (also `restore`) | `u` | List archived tracks; `u 1,3` or `u all` puts them back. |
| `prompts` (also `history`, `prompt-history`) | `pr` | Your past prompts; `pr 4` shows one with a ready-to-run `gen` line. |
| `folder` (also `library`) | `f` | Show or change the folder the radio plays from. |
| `format` (also `filetype`) | `ft` | Save new tracks as `mp3`, `wav` or `wav+mp3`. |
| `key` | `k` | Store the API key; `key show`, `key clear`. |
| `say "<line>"` (also `dj`) | | Queue a line for the DJ. |
| `announce on` / `off` | `an` | Have the DJ speak Claude's updates while the music is stopped. |
| `breaking on` / `off` | `b` | Let an update interrupt the song, which then resumes. |

Things you can just say: *"play the radio"*, *"skip this one"*, *"get rid of this song"*, *"what's playing?"*, *"make me three synthwave tracks"*, *"what prompt did I use for the car track?"*.

Or name a kind of music: `/tfm smooth jazz` plays the tracks in your library that fit, and offers to make some (which costs credits) when none do. `/tfm` is short for `/terminal-fm:tfm`; `/radio` is Claude Code's own built-in radio, not this one. In a terminal, every command is also `python3 <plugin folder>/radio.py <command>` (`python` on Windows), using the folder from the `key` command in step 3.

---

## 🧩 Optional extras

Everything above works without these. Each goes into the data folder, `~/.claude/radio`. Their licenses are in `THIRD_PARTY_NOTICES.md`.

**A better DJ voice: Kokoro-82M.** Without it the DJ uses your system voice: Windows SAPI, macOS `say`, or on Linux `espeak-ng` (`sudo apt install espeak-ng`) or Piper with a voice.
1. Download `kokoro-v1.0.fp16.onnx` and `voices-v1.0.bin` from <https://github.com/thewh1teagle/kokoro-onnx/releases/tag/model-files-v1.1> into `~/.claude/radio/kokoro/`.
2. Run `pip install -U kokoro-onnx soundfile` (it needs kokoro-onnx 0.6 or newer). The radio finds a Python that has it on its own; to pin one, set `dj.python` in `config.json`.

**A local prompt writer, for `enhance`, `egen` and better track lengths.** Without it, `enhance` uses your idea as written and `gen` picks lengths from keyword rules.
1. Download the `Q4_K_M` file of Qwen3-4B-Instruct-2507 (about 2.5 GB) from <https://huggingface.co/unsloth/Qwen3-4B-Instruct-2507-GGUF> into `~/.claude/radio/llm/`. Keep one `.gguf` there: the first in sorted order is the one used.
2. From the newest `b<number>` release at <https://github.com/ggml-org/llama.cpp/releases>, copy `llama-cli` (`llama-cli.exe` on Windows) and the libraries beside it into `~/.claude/radio/llm/bin/`. A `llama-cli` on `PATH` works too. It runs on the CPU and exits when done.

**An exact prompt-length check.** Stable Audio 3 reads only the first 256 tokens of a prompt, so `gen` refuses longer ones. Without this file it estimates at 4 characters a token.
1. Accept Google's Gemma terms at <https://huggingface.co/google/t5gemma-b-b-ul2> (the repository is gated).
2. Save its `tokenizer.json` as `~/.claude/radio/llm/t5gemma-tokenizer.json`.

---

## 🎛️ Command reference

`radio` below stands for `/tfm` in Claude Code, or `python3 <plugin folder>/radio.py` in a terminal. Every command except `say` and `hook` also takes its short key from the table above.

### `radio play [1,3,5-8] [--say "<line>"]` (alias `resume`)
Starts playback in the background and returns. A paused track resumes where it stopped. Track numbers from `radio list` play just those, in order, looping (see `playlist`). `--say "<line>"` puts a DJ sign-on at the front of the queue. If the library is empty or no player is found, `play` refuses and queues nothing.

### `radio pause` · `radio stop` · `radio skip` (alias `next`)
`pause` stops and remembers the track and position, and the next `play` resumes there; `afplay` and `mpg123` restart the track instead. Between tracks, or in a track's first second, there's nothing to resume: `pause` then stops and says `Paused between tracks, nothing to resume`. `stop` stops and forgets the pause point; an active playlist is kept (`radio shuffle` clears it). `skip` moves to the next track.

### `radio status` · `radio setup`
`status`, also what `radio` runs with no command, shows the state, the track, the folder and its track count, playlist or shuffle, queued DJ lines and the player. When the player, the key or any tracks are missing, it adds a `setup :` line.

`setup` checks Python, the player, the API key, whether the session hooks have run, the library and the statusline, then lists the optional extras. Each line is `ok`, `NEEDED` (with the exact fix), `next` or `extra`. It changes nothing.

### `radio list` · `radio playlist [1,3,5-8 | clear]` (alias `pl`) · `radio shuffle`
`list` numbers the library (the `.mp3` and `.wav` files in the folder, not its subfolders) and remembers that order, so the numbers you use next mean what you saw. `*` marks playlist tracks.

A selection like `1,3,5-8` takes commas or spaces, ranges in either direction (`8-5`), and repeats (`3,3` plays it twice); numbers past the end are ignored. `radio play 1,3,5-8` or `radio playlist 1,3,5-8` sets a playlist, which plays in order and loops; while music plays it switches over at once. `radio playlist` shows it. `radio playlist clear` (or `off`, `none`, `all`, `reset`, `shuffle`) or `radio shuffle` returns to shuffling everything. A playlist survives `stop`; tracks no longer in the folder are skipped, and if none are left the radio shuffles.

### `radio folder [<path> | default]` (alias `library`)
Shows or changes the folder the radio plays from and `gen` saves into, stored as `library_dir` in `config.json`. The default is `~/.claude/radio/output`. A new path is created if needed; `~` and environment variables work, and a relative path starts from the data folder. `default` (or `reset`, `clear`, `none`) goes back. A running radio keeps the old folder until `radio stop` and `radio play`.

### `radio gen "<prompt>" [<duration> | auto]` · `radio gen "<prompt>" <count> <duration | auto>`
Generates tracks with Stable Audio 3 into the library folder. Each one costs credits.
- **Numbers:** one number after the prompt is the length in seconds; two are the count, then the length. `gen "lo-fi" 120` makes one 120-second track and `gen "lo-fi" 3 120` makes three. A lone number under 10 is refused as a probable miscounted count (use `gen "<prompt>" 3 auto`). A count above 20 asks you to type `yes`.
- **No length, or `auto`, picks one to suit the prompt.** A length written in words wins: "90 second trailer" gets 90s, while "80s synthwave" stays a decade. Otherwise the local model picks within **1–380s**, the same answer for the same prompt every time. Without the model, the first matching keyword decides, checked in this order: `notification` `sting` `stinger` → **5s**; `jingle` `bumper` → **15s**; `intro` `outro` `commercial` `advert` → **30s**; `ambient` `drone` `meditation` `sleep` `soundscape` → **300s**; `techno` `trance` `progressive` → **240s**; `trailer` `punk` `hardcore` → **120s**; `synthwave` `retrowave` `lo-fi` `lofi` `lo fi` `jazz` `hip hop` `hip-hop` `chillhop` `funk` `soul` `house` `rock` `pop` → **150s**. With no match it uses `stability_api.duration`, **120s**. A length you type is always used as is.
- **Prompts over 256 tokens are refused before anything is spent**, because Stable Audio 3 ignores the rest without saying so but still bills the track. The refusal says how much to cut.
- **The output is four lines:** `Length:` (who chose it), `Prompt:` (exactly what was sent), `Cost:` (credits, from your balance before and after; `unknown` when the balance hasn't caught up yet) and `Folder:` (tracks added and the new total). A `FAILED` line is added for any track that didn't arrive. New tracks join the shuffle on its next pass.

```
radio gen "warm lo-fi hip hop, rhodes, vinyl crackle, 80 BPM"     # one track, length picked
radio gen "driving synthwave, neon, analog bass, 120 BPM" 3 110   # three 110s tracks
radio gen "slow ambient drone with a long build" 2 auto           # two tracks, length picked
```

### `radio enhance "<idea>"` · `radio egen "<idea>" [<duration> | auto] | [<count> <duration | auto>]`
`enhance` turns a rough idea into a Stable Audio 3 prompt with the local model and prints it: nothing is generated or spent. `egen` does the same, then runs `gen` on the result with the same numbers as `gen`. Both need the local prompt writer from **Optional extras**; without it the idea is used as written.
- **The prompt is a caption, in a fixed order:** the style, the instruments and how they're played, production, mood, then the key and BPM where they fit (none for sound effects or beatless pieces). It keeps everything your idea names, describes the sound rather than a scene, never names artists, and turns exclusions into positives ("no drums" becomes "beatless"). A Stable Audio tag you put in your idea, such as `TrackType: Instrument`, stays at the front.
- **The length is settled first**, from your idea as for `gen`, and the rewrite is told it, so a short clip gets fewer parts. The length is sent separately and never appears in the prompt.
- **Some ideas get a reply instead of a prompt,** and `egen` then stops with `Nothing generated.` and spends nothing: a request for sung lyrics or speech (Stable Audio 3 is instrumental), an idea that contradicts itself (you get one question back), or a rewrite over the 256-token limit twice.
- **A rewrite that both describes and denies** drums, vocals, reverb or bass is retried once. If it still conflicts, `enhance` adds a `Conflict:` line and `egen` stops without spending.
- **Every rewrite is saved** to your prompt history, marked `e`, so `radio prompts <n>` can generate it later.
- **The instructions are plain text in `prompts/enhance.md`.** To change them, copy that file to `~/.claude/radio/prompts/enhance.md` and edit the copy, which then wins; plugin updates replace the original. If you reword its two fixed replies, change `ENH_NOT_PROMPTS` in `radio.py` to match.

### `radio archive [list | show | 1,3,5-8]` · `radio drop` · `radio unarchive [1,3 | all]` (alias `restore`)
`archive` moves the playing track into the library's `_archive` subfolder and skips to the next. `archive 3,7` archives by `list` number, `archive list` numbers the library, and `archive show` (or `archived`, `ls`) lists what's archived. `drop` moves the playing track into one shared reject folder, `output/bad song`, whichever folder is playing; `radio folder "output/bad song"` plays them. `unarchive` numbers the archive, and `unarchive 1,3` or `unarchive all` (or `*`, `everything`) puts tracks back in the library. Nothing is ever deleted, and archived or dropped tracks leave the playlist.

### `radio prompts [all | <N> | <text>]` (aliases `history`, `prompt-history`)
Every prompt that made a track, plus every `enhance` rewrite. With no argument it shows the newest 20; `all` shows everything; text searches; a number shows that entry in full, with a ready-to-run `radio gen` line. Numbers never shift. Marks: `a` archived, `b` in `bad song`, `x` file not found, `e` a rewrite never generated.

### `radio format [mp3 | wav | wav+mp3]` (alias `filetype`)
Sets the file type new tracks are saved as, stored as `stability_api.output_format` (default `mp3`; `.WAV` and `mp3+wav` are accepted too). A WAV takes about 10.6 MB a minute. `wav+mp3` generates once, for one charge, keeps the WAV in the library's `_wav` subfolder and plays an MP3 made from it with `ffmpeg`, which it needs. `mpg123` can't play WAV, so with it as your player use `mp3` or `wav+mp3`.

### `radio key [show | clear]`
With no argument, asks for the API key at a hidden prompt and saves it to `~/.claude/radio/.key` (owner-only on macOS and Linux). That needs your own terminal: run inside Claude Code, it prints the exact command to use instead. `show` prints the key's first 6 characters and where it came from; `clear` (or `delete`, `remove`) deletes it. A stored key wins over `STABILITY_API_KEY`. The key is never accepted as an argument.

### `radio say "<line>"` (alias `dj`)
Queues a line for the DJ, one per gap between tracks, in order. Keep it to a sentence or two. Lines are read exactly as written; no language model is involved anywhere in the DJ.

### `radio announce on | off` · `radio breaking on | off`
When Claude finishes a turn, its update normally waits in the queue for the next gap between tracks. `announce on` also speaks it when the music is stopped (`dj.announce_when_idle`). `breaking on` interrupts the playing track, speaks, and resumes the track where it was, or from the top with `afplay` and `mpg123` (`dj.breaking_news`; `radio announce breaking on` works too, as do `break` and `interrupt`). On words: `on` `enable` `enabled` `true` `yes` `1`. Off words: `off` `disable` `disabled` `false` `no` `0`. With neither, the command shows the setting. Both are off by default.

### `radio hook Stop | SessionStart` (internal)
What the plugin's hooks run, through `hooks/radio-hook.sh`, which finds a Python 3.8+ first; with none at session start, it hands Claude Code a note with the install command, so Claude can tell you. At session start the hook copies `statusline.py` into the data folder and notes the time for `setup`. When Claude finishes a turn it queues, speaks or interrupts as set above, using Claude's last message trimmed to its main point. `radio __daemon` is the playback loop `play` starts; never run it by hand.

---

## 🗣️ DJ voice

The DJ speaks with the first engine that works: Kokoro-82M → Piper → macOS `say` → Windows SAPI → `espeak`. Each line spoken is logged to `~/.claude/radio/dj_engine.log` with the engine, the reason and its first 60 characters.

Both voice scripts run on their own too:
```
python3 dj.py say --text "hello"                    # or: --file <path>, or text on stdin
echo "on the ones and twos" | python3 kokoro_tts.py --out out.wav --voice am_michael
```
`kokoro_tts.py` takes `--text` (default: stdin), `--voice` (`am_michael`), `--speed` (`1.0`), `--lang` (`en-us`), `--out` (`<data dir>/_dj.wav`; `dj.py` uses a per-process `_dj_<pid>.wav`), `--model` (the first of `kokoro-v1.0.fp16.onnx`, `kokoro-v1.0.onnx` or `kokoro-v1.0.int8.onnx` in `kokoro/`) and `--voices` (`kokoro/voices-v1.0.bin`).

---

## ⚙️ Settings: `config.json`

`~/.claude/radio/config.json`, merged over the defaults below, so give only what you change: `{"dj": {"kokoro_voice": "af_bella"}}` keeps every other setting. `config.example.json` in the repo is a copy of the defaults. Commands that save a setting refuse to overwrite a `config.json` that isn't valid JSON.

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

- `library_dir`: the folder to play from; `""` means `~/.claude/radio/output`. Set it with `radio folder`.
- `volume`: 0–100, used by `mpv`, `ffplay` and `afplay`.
- `stability_api.duration`: the length when nothing else decides (see `gen`). `stability_api.output_format`: set it with `radio format`. `stability_api.steps`: fixed at 8 for Stable Audio 3. `stability_api.balance_url`: read before and after each `gen` to measure its cost.
- `stability_api.ca_bundle`: a PEM file to check the API's certificate against, such as certifi's `cacert.pem`; `""` uses the system's.
- `dj.announce_when_idle`, `dj.breaking_news`: set them with `radio announce` and `radio breaking`.
- `dj.kokoro_voice`: any Kokoro voice (`am_michael`, `af_bella`, …). `dj.voice`: a Piper `.onnx` voice; `"auto"` takes the first `*.onnx` in `~/.claude/radio/` or `~/.claude/radio/voices/`. `dj.rate`: the Windows SAPI speaking rate. `dj.python`: the Python to use for Kokoro.
- `source`: where music comes from; `stability-api` is the only one today.

---

## 🩺 Troubleshooting

Start with `/tfm setup`. If that doesn't explain it:

- **Windows says "Python was not found".** That's the Microsoft Store shortcut, not Python. Install Python (`winget install Python.Python.3.12`), then reopen the terminal and restart Claude Code.
- **No audio player.** Install one (see **Before you start**). On Windows, `C:\ffmpeg\bin\` is checked even when it isn't on PATH.
- **`setup` says the session hooks haven't run.** Start a new Claude Code session. On Windows, install Git for Windows (`winget install Git.Git`) and restart: without Git Bash, Claude Code runs hooks in PowerShell, which can't start the radio's hook script. Claude Code looks for `bash.exe` beside `git`, or wherever `CLAUDE_CODE_GIT_BASH_PATH` points.
- **No radio in the statusline.** Add the line `setup` prints to `~/.claude/settings.json`. With a statusline of your own, have it print `~/.claude/radio/nowplaying.txt`: it reads `Terminal FM > <track>` while a track plays and `Terminal FM | <status>` otherwise, so a `>` means playing. The display refreshes each turn and every `statusLine.refreshInterval` seconds, so it can lag; `radio status` is always current.
- **The DJ sounds robotic.** That's Windows SAPI, used when Kokoro isn't installed or fails. The end of `~/.claude/radio/dj_engine.log` says which: `kokoro not installed`, or a `kokoro-fail` line naming the Python and the error. Install `kokoro-onnx soundfile` into that Python, or point `dj.python` at one that has them.
- **`gen "<prompt>" 3` is refused.** One number is a length, and 3 seconds isn't a track. For three tracks: `gen "<prompt>" 3 auto`.
- **`gen` refuses a long prompt.** Cut what the message says, or let `enhance` rewrite it. A count marked `estimated` means the tokenizer file isn't installed.
- **`gen` pauses before generating.** With no length given it asks the local model for one, a CPU call that took 9 to 14 seconds in testing. Type a length to skip it.
- **`Cost: unknown`.** Your Stability balance hadn't updated when `gen` finished; the charge shows up later.
- **`gen` fails with `HTTP ???` or `certificate has expired`.** The request never reached the API, and the text after it is the real reason. Requests go through Python's own TLS with `User-Agent: terminal-fm/1.0`, falling back to `curl` only when Python can't connect (on Windows 10, `curl` can't reach the API at all). For `certificate has expired`, set `stability_api.ca_bundle` to certifi's `cacert.pem`.
- **`egen` says `Nothing generated.`** The prompt writer replied with a message instead of a prompt. Rephrase: drop the vocals, or settle the contradiction it asked about.
- **Changed `folder` but the old music plays on.** `radio stop`, then `radio play`.
- **A `say` line came late.** The DJ reads one queued line per gap; `radio status` shows how many are waiting.
- **The DJ broke but the music plays on.** That's deliberate: DJ errors never stop playback. `dj_engine.log` shows what went wrong.

---

## 🗂️ Files

Everything the radio creates lives in its data folder: `~/.claude/radio`, or the folder named by the `AI_RADIO_HOME` environment variable. Plugin updates and uninstalls leave it alone. The plugin's code sits in Claude Code's plugin cache and is replaced on each update.

```
~/.claude/radio/
├── output/                 # the library: every .mp3 and .wav here plays
│   ├── _archive/           # tracks moved out by `radio archive`
│   ├── _wav/               # WAV masters from `radio format wav+mp3`
│   └── bad song/           # `radio drop` rejects, from every folder
├── .key                    # your API key (`radio key`)
├── config.json             # your settings
├── prompt_history.jsonl    # every prompt and rewrite (`radio prompts`)
├── statusline.py           # copied here at session start; point statusLine at it
├── prompts/enhance.md      # optional: your own prompt-writer instructions
├── kokoro/                 # optional: Kokoro voice files
├── llm/                    # optional: llama-cli, the .gguf model, t5gemma-tokenizer.json
└── dj_engine.log           # which voice spoke, and why
```

The rest is the radio's own bookkeeping: `state.json`, `nowplaying.txt`, `queue/`, `playlist.json`, `resume.json`, `breaking.txt`, `last_list.json`, `last_archive.json`, `dj_speaking.lock`, `.hook_seen`, `.kokoro_python`, and the voice renders `_dj.wav` and `_dj_<pid>.wav`.

---

## 🛠️ Manual install (without the plugin)

1. **Clone the repo into the data folder:** `git clone https://github.com/MatthewNorton/terminal-fm ~/.claude/radio` (PowerShell: `git clone https://github.com/MatthewNorton/terminal-fm "$HOME\.claude\radio"`).
2. **Copy the skill:** copy `skills/tfm/` to `~/.claude/skills/tfm/`. In the copy's `SKILL.md`, replace every `${CLAUDE_PLUGIN_ROOT}` with the clone's full path in forward slashes, such as `C:/Users/<you>/.claude/radio`. The skill is then `/tfm`.
3. **Add the hooks** to `~/.claude/settings.json` (on Windows, write `C:/Users/<you>/.claude/radio/...` for `~/.claude/radio/...`):
   ```json
   "hooks": {
     "SessionStart": [{"matcher": "startup|resume", "hooks": [{"type": "command", "command": "sh ~/.claude/radio/hooks/radio-hook.sh SessionStart", "timeout": 30}]}],
     "Stop": [{"hooks": [{"type": "command", "command": "sh ~/.claude/radio/hooks/radio-hook.sh Stop", "async": true, "timeout": 60}]}]
   }
   ```
4. **Start a new session and run `/tfm setup`**, then carry on from step 3 of **Install**.

Moving to the plugin later? Remove those hook entries and `~/.claude/skills/tfm/` first, or every hook runs twice. Never add the marketplace from the clone itself (`claude plugin marketplace add ~/.claude/radio`): Claude Code would copy the whole folder, key and library included, into its plugin cache. Install from GitHub as above.

---

## 📝 Contributing

`README.md` must match the code. `python readme_check.py` checks it mechanically and CI runs it; the rules for any change are in `AGENTS.md`, and the architecture notes in `.claude/CLAUDE.md`.

```
python -m unittest discover tests     # unit tests
python smoke_test.py                  # the read-only commands against a throwaway data folder
python readme_check.py                # README drift; --diff and --confirm after a code change
python release_check.py               # before publishing: home paths, personal emails, keys, big files
claude plugin validate . --strict     # the plugin manifest and hooks
claude --plugin-dir .                 # try a checkout for one session without installing it
```

`release_check.py` also refuses any string listed in an untracked `.release_markers` file beside it: put your own username and email there. Security reports: `SECURITY.md`. License: MIT (`LICENSE`).
