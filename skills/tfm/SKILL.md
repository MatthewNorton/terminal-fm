---
name: tfm
description: Control Terminal FM — a portable, continuous music player that plays generated music from a local library. Use when the user types /tfm, names a genre or mood ("smooth jazz"), or asks to play/stop/skip the radio, check what's playing, list the music library, generate new music, improve/enhance a music prompt idea, get rid of a song they don't like or drop it into the bad song folder, look up a prompt they used before, toggle spoken updates when Claude finishes, choose whether new tracks save as mp3, wav, or both, or set the radio up and check what's missing. Subcommands - setup | play | stop | skip | status | list | gen | enhance | egen | format | archive | drop | unarchive | prompts | announce.
allowed-tools: PowerShell, Bash, Read
---

# Terminal FM

A cross-platform radio. A detached background daemon shuffles MP3 and WAV tracks from a local library continuously; new tracks come from a pluggable **source** (currently the Stability AI text-to-audio API). The Claude Code statusline shows the current track.

- Core (portable, stdlib-only Python): `${CLAUDE_PLUGIN_ROOT}/radio.py`, the `radio.py` inside this plugin
- Data directory: `~/.claude/terminal-fm`, or the folder named by `TERMINAL_FM_HOME`. Every `~/.claude/terminal-fm/...` path below means that folder.
- Library: `~/.claude/terminal-fm/output/` (`.mp3` / `.wav` files)
- State: `state.json` + `nowplaying.txt`; settings: `config.json`; API key: `.key`

## How to run

Invoke the Python core inside this plugin:

- macOS / Linux: `python3 "${CLAUDE_PLUGIN_ROOT}/radio.py" <subcommand> [args]`
- Windows: `python "${CLAUDE_PLUGIN_ROOT}/radio.py" <subcommand> [args]`. If that answers "Python was not found" (exit code 49 or 9009: the Microsoft Store shortcut, not a real Python), use `py` in place of `python`.

Run that path exactly as written above: it is filled in when the skill loads, and your shell does not have `CLAUDE_PLUGIN_ROOT` set. Take the user's words after `/tfm` (full name `/terminal-fm:tfm`), map them to a subcommand, run it, and report the script's concise output. Do not invent flags — only the subcommands below exist.

**No Python at all** (neither command runs): stop there and don't search the disk for one. Tell the user the radio needs Python 3.11 or newer, give them the install line for their OS (Windows: `winget install Python.Python.3.14`; macOS: `brew install python`; Linux: `sudo apt install python3`), and ask them to restart Claude Code and then run `/tfm setup`.

**First run, or something missing:** run `radio.py setup` and relay its output exactly as printed, in a code block. It is a wizard: a checklist, then only the next step, spelled out; when the user says they've done it, run `setup` again for the one after. Do this when the user asks to set up, install or check the radio, when `status` prints a `setup :` line, or when a command reports no key, no player or an empty library. The key step is a command the user must run in their own terminal, because the key is typed at a hidden prompt: give it to them exactly as printed, and never ask for the key in chat.

**Optional extras** (`statusline`, `voice`, `enhancer`, `tokenizer`): run `radio.py setup <extra>`. When it prints an `Automatic install (/tfm setup <extra> install)` block, ask before installing anything, instead of relaying the page: one AskUserQuestion with the block's steps, disk space and `Claude's part` line, and the options `Install it`, `Show me the steps` and `Not now`. When it prints `Automatic install: <reason>` instead, the install can't run here: relay the page as printed and don't offer it. Run `radio.py setup <extra> install` only after `Install it` in this conversation, even when the user typed `install` themselves: the enhancer, and the voice when its steps include installing Python, with `run_in_background` (a 2.5 GB download, or a Python install plus pip plus 192 MB, can outlast a 10-minute command), then wait for the notification without polling; the others in the foreground with a 600000 ms timeout. Relay the result from its `Installed:` or `Not installed:` line to the end, since a reason can run to several lines; the command exits with 1 when it didn't install. An install that stopped resumes when run again. `Show me the steps`: relay the `Or by hand` steps in a code block. The statusline's install is your own edit: Read the `settings.json` the page names, then add its `statusLine` line with Edit (Write when there is no file); if that is refused, give the user the line.

**A genre or mood instead of a command** (`/tfm smooth jazz`, `/tfm something to focus to`) asks for that music. Run `radio.py list`, pick the tracks that fit (a track's name is the start of the prompt that made it; `radio.py prompts <word>` searches whole prompts), and play them with `radio.py play <numbers> --say "<sign-on>"`. If none fit, say so and offer `radio.py egen "<their words>"`, which spends Stability credits: run it only after they say yes. `/tfm` alone is `radio.py status`.

**Keep reports terse: wordy reports waste tokens.** For `gen`, `egen` and `enhance`, relay the script's `Length:` / `Prompt:` / `Cost:` / `Folder:` lines exactly as printed, in a code block, plus any `FAILED` line. Add nothing else: no restating the prompt, no explaining the length, no credit estimates, no advice about playing it. Only add a sentence when something actually went wrong.

## Subcommands

| User intent | Command |
|---|---|
| start / play | `radio.py play --say "<a short 1-2 sentence DJ sign-on you write>"` |
| resume (after a pause) | `radio.py play` (no `--say`; it picks up the paused track + spot) |
| pause | `radio.py pause` |
| stop / silence / turn off | `radio.py stop` |
| skip / next | `radio.py skip` |
| status / what's playing | `radio.py status` |
| list / show library | `radio.py list` (numbered) |
| play only certain tracks, in order | `radio.py play 1,3,5-8` (numbers from `radio list`) |
| show / clear the playlist | `radio.py playlist` \| `radio.py shuffle` (back to full shuffle) |
| change the folder it plays from | `radio.py folder "<path>"` (show: `radio.py folder`; revert: `radio.py folder default`) |
| save new tracks as mp3 / wav / both | `radio.py format mp3` \| `radio.py format wav` \| `radio.py format wav+mp3` (show: `radio.py format`; alias: `filetype`) |
| set up / what's missing / first run | `radio.py setup` (a checklist, then the next step spelled out; changes nothing) |
| add the statusline / a better DJ voice / the prompt enhancer / the exact token count | `radio.py setup statusline` \| `radio.py setup voice` \| `radio.py setup enhancer` \| `radio.py setup tokenizer` (the automatic install's plan and the steps by hand; `setup <extra> install` runs the plan, only after the user says yes: see Optional extras above) |
| set / check the Stability API key | `radio.py key` (the key is typed at a hidden prompt, which needs the user's own terminal: run it, and it prints the exact command for them to run there; never put the key on the command line) \| `radio.py key show` \| `radio.py key clear` |
| don't want THIS song / bin it | `radio.py archive` (archives what's playing, skips to the next) |
| drop THIS song into the bad song folder | `radio.py drop` (moves what's playing to `output/bad song`, skips to the next) |
| pick songs to get rid of | `radio.py archive list` then `radio.py archive 3,7` |
| what's archived / put one back | `radio.py archive show` \| `radio.py unarchive 1` (all: `radio.py unarchive all`) |
| past prompts / "what did I use for that one" | `radio.py prompts` (detail + regenerate line: `radio.py prompts 4`; search: `radio.py prompts jazz`) |
| queue a DJ line / update | `radio.py say "<short line>"`  (alias: `dj`) |
| toggle idle announcements | `radio.py announce on` \| `radio.py announce off` \| `radio.py announce` (status) |
| toggle breaking-news mode | `radio.py breaking on` \| `radio.py breaking off` \| `radio.py breaking` (status) |
| generate / make music | `radio.py gen "<prompt>"` (length auto-picked) \| `"<prompt>" <duration>` if they gave one \| N tracks: `"<prompt>" <count> <duration\|auto>` |
| improve a rough idea into a real prompt | `radio.py enhance "<idea>"` (prints Length + Prompt; generates nothing) |
| enhance then generate in one step | `radio.py egen "<idea>" [count] [duration]` |

### Short keys
When the first word after `/tfm` is one of these keys, treat it exactly as the full command and follow that command's row above. For example, `/tfm p` gets the `--say` sign-on just like `/tfm play`. `radio.py` accepts the keys itself too, so passing one straight through also works.

`p` play · `pa` pause · `pl` playlist · `pr` prompts · `s` stop · `n` / `sk` skip · `st` status · `sh` shuffle · `se` setup · `l` list · `f` folder · `ft` format · `a` archive · `an` announce · `b` breaking · `d` drop · `u` unarchive · `g` gen · `e` enhance · `eg` egen · `k` key

`g` and `eg` spend credits and `e` doesn't, so don't confuse `e` with `eg`.

### gen details
- Prompt is required and MUST be quoted. Defaults: count `1`, duration **picked automatically to suit the prompt**.
- **If the user gave no duration, pass none. Don't add `120` yourself.** `gen "<prompt>"` asks the local llama.cpp model (the same one `enhance` uses; temp 0, measured at ~9-13s on CPU) for the length that fits the prompt, anywhere in **1-380s**: a notification chime gets ~5s, a jingle ~15s, a long ambient build 300s+. A length stated in the prompt is honoured. If the model isn't installed or gives no number, a keyword table (`DUR_RULES` in `radio.py`) decides: notification/sting 5s, jingle/bumper 15s, intro/outro/commercial 30s, ambient/drone/sleep 300s, techno/trance/progressive 240s, trailer/punk 120s, synthwave/lo-fi/jazz/house 150s, anything else the configured default (120s). For several tracks at an auto length, write `auto` in the duration slot: `gen "<prompt>" 3 auto`. There is no setting to turn this off: a duration the user types is used as-is and never triggers the auto-pick.
- **A single number after the prompt is the DURATION, never a count.** `gen "<prompt>" 147` = one 147-second track. This is the radio's convention, and it's enforced in `cmd_gen`, so when the user types `/tfm gen "..." 218` pass it straight through — do not reinterpret it as a count or "correct" it. Two numbers mean count then duration: `gen "<prompt>" 3 120` = three 120s tracks. A lone typed number below 10 is refused with a message, since it's almost certainly a miscounted count; the auto-pick itself can still choose under 10s.
- Don't shorten or lengthen a duration yourself. An explicit duration the user types always wins, including values above 380s.
- **Prompts are capped at 256 tokens.** Stable Audio 3's T5Gemma encoder reads only the first 256 tokens and silently drops the rest while the track is still billed. `gen` counts the prompt with SA3's own tokenizer (`llm/t5gemma-tokenizer.json`, exact; without it an estimate at 4 characters a token) and prints `Refusing: the prompt is <n> tokens ... Cut about <c> of its <len> characters. Nothing spent.` before any credit is used. Relay that line. Don't trim the user's prompt yourself to get it through; tell them what to cut, or offer `enhance` (its rewrites have measured 37-138 tokens). Characters alone aren't a safe proxy: English prose is ~4.2-5.3 characters a token, digits/chord symbols and CJK ~1.4.
- There is no `steps` argument (a third number prints the usage); Stable Audio 3 fixes steps at `8` in `config.json`. A count above 20 makes `gen` ask for a typed `yes`, which can't be answered from a hook or a pipe, so split big batches or tell the user to run it in a terminal. Example: `radio.py gen "warm lo-fi hip hop, rhodes, vinyl crackle"`
- Output is four lines: `Length:` (who decided: user / as stated / local model / keyword rules / config default), `Prompt:` (exactly what was sent), `Cost:` (exact credits, from the account balance before and after; `unknown` when the balance lags; `0 credits (nothing sent)` when it refused before sending, e.g. no API key), and `Folder: <name> / track(s) added: N / total: N tracks`. Relay them as-is (see "Keep reports terse").
- HTTP goes through Python's `urllib` (TLS 1.3 via OpenSSL), falling back to the system `curl`. Curl alone cannot reach the API from Windows 10 — the endpoint refuses TLS 1.2 and Schannel has no TLS 1.3. Every track is saved permanently to the library, as `.mp3` or `.wav` per `radio.py format`.
- New tracks are auto-picked-up on the daemon's next shuffle pass — no restart needed.

### format (mp3 / wav / wav+mp3)
- `radio.py format wav` / `radio.py format mp3` sets the file type new tracks are saved as (`stability_api.output_format`, default mp3); bare `radio.py format` shows it. Existing files are untouched and the library plays both.
- `radio.py format wav+mp3` (or `mp3+wav`) keeps both files of the same take, billed once: gen requests the WAV into `<library>/_wav` and ffmpeg encodes the MP3 (128 kbps) that plays from the library. `_wav` is out of rotation, so nothing plays twice. It's refused (`Not saved.`) without ffmpeg. An `MP3 (i/n) not made ...` line from gen means the encode failed and the WAV went into the library instead; relay it. `archive` / `drop` move only the MP3; the WAV master stays in `_wav`.
- WAV is 16-bit 44.1 kHz stereo, about 10.6 MB per minute, so a 180s track is ~32 MB (MP3: ~2.8 MB). Mention the size once if the user switches to wav for a large batch.

### enhance / egen (prompt enhancer)
- `radio.py enhance "<idea>"` rewrites a rough idea into a Stable Audio 3 prompt using a **local** llama.cpp model (`llm/*.gguf`, CPU-only via `-ngl 0` so the GPU stays free; the process loads, generates and exits). It costs no Stability credits and generates no audio — it only prints `Length:` and `Prompt:`. Measured at ~25s on CPU: ~15s for the rewrite plus ~10s for the length pick.
- **The enhancer's instructions are `~/.claude/terminal-fm/prompts/enhance.md` when that file exists, otherwise the copy shipped beside `radio.py`** (`${CLAUDE_PLUGIN_ROOT}/prompts/enhance.md`), a plain markdown system prompt re-read on every run. To change how prompts come out, copy the shipped file to `~/.claude/terminal-fm/prompts/enhance.md` and edit the copy, not `radio.py`: the plugin folder is replaced on every update, so an edit made there is lost. It ships as revision 1.3, derived from `Qwen3_4B_SA3_Enhancer_Setup_v1.0.md` (in this plugin's folder): one line of comma-separated phrases in a fixed order (genre, instruments with how they're played, production, mood, key, BPM last; no key or BPM for effects or beatless material), keeping everything the brief states, with no scene words, artist names, negations, tags, duration or settings. Code strips any label the model writes and puts a `TrackType:` tag from the user's own idea back in front. The model it was written and tested for is Qwen3-4B-Instruct-2507 (Q4_K_M), sampled at temp 0.7 / top-p 0.8 / top-k 20 / min-p 0.
- **Some replies are not prompts.** A vocal/lyrics/speech request gets "This request requires a vocal or speech model rather than Stable Audio 3." (tested), and any reply ending in `?` counts as a clarifying question. `enhance` prints these as `Enhancer: <reply>`, and `egen` prints them plus `Nothing generated.` without spending credits. Relay that line; don't retry with the vocals silently dropped. A rewrite over the 256-token prompt limit is retried once and, if still over, comes back the same way as `Enhancer: the rewrite ran to <n> tokens, over Stable Audio 3's 256-token prompt limit, on both attempts. Run it again.`
- The 4B model doesn't always follow the instructions. In testing, "fast doom metal, clean guitars only" came back slow and overdriven, "rainy night drive" got rain sounds, a self-contradicting brief got the vocal-model reply instead of a question, and an injection-style idea got an unrelated example prompt. If an enhanced prompt contradicts the user's idea, say so in one line rather than generating more of it.
- **Self-contradicting rewrites are caught in code** ("brushed drums" + "no beats"): the rewrite is retried once, and if it still conflicts `enhance` prints a `Conflict:` line while `egen` prints it plus `Nothing generated.` and spends nothing. Relay that line. The rewrite is still logged, so the `radio prompts <n>` it names will generate it if the user wants it anyway.
- The enhancer does not choose the length; it is told one. `enhance` / `egen` pick it from the user's own idea first (a length stated in words wins outright: "90 second trailer" → 90s), then pass it to the rewrite, which gives a short clip fewer parts. A duration the user types is used and passed the same way.
- `radio.py egen "<idea>" [duration | count duration]` = enhance + gen, same number grammar as `gen`. With the duration empty or `auto`, gen auto-picks it for the enhanced prompt; a typed duration always wins (`egen "idea" 147` → 147s, `egen "idea" 3 60` → three 60s tracks). This one **does** spend credits.
- If `llama-cli` + a `.gguf` aren't present under `llm/`, or `prompts/enhance.md` is missing, both commands say so and use the idea verbatim; `gen`'s keyword table then picks the length.

## Playlists (pick tracks by number)
- `radio.py list` prints the library **numbered** (1..N) and snapshots that order, so the numbers stay stable for the next command even if the library changes.
- `radio.py play 1,3,5-8` (alias `radio.py playlist 1,3,5-8`) plays **only those tracks, in that order**, then loops the selection. Accepts commas and/or spaces, ascending or descending ranges (`8-5`), and repeats (`3,3` plays it twice). Out-of-range numbers are ignored.
- The daemon re-reads the selection every track, so setting a playlist **while playing jumps to it on the next track** (it kills the current player to advance). If stopped, it starts playback.
- `radio.py playlist` shows the current selection; `radio.py shuffle` (alias `radio.py playlist clear`) drops it and returns to full-library shuffle. `status` shows `mode: playlist` vs `shuffle`.
- Persisted in `playlist.json` as track **names**, resolved against the current library folder — so if you change folders (below), a playlist whose tracks aren't in the new folder safely reverts to shuffle. Numbers refer to whatever `radio list` last showed for the **current** folder.

## Archive (songs the user doesn't want)

- `radio.py archive` with **no args** archives the track playing right now: it kills the player first (so the file isn't locked), moves it to `_archive`, drops it from the playlist, and the daemon advances to the next track. This is the answer to "I hate this song".
- `radio.py archive list` prints the numbered library (same numbering as `radio list`, and it snapshots the order) plus the current archive count, so the user can then say `radio.py archive 3,7` or `radio.py archive 5-9`. Same `1,3,5-8` grammar as playlists.
- Archived tracks move to **`<library folder>/_archive`** — a subfolder of whatever `library_dir` points at. Nothing is deleted. They stay out of rotation for free, because `get_library()` scans for `.mp3` / `.wav` non-recursively, so a subfolder is invisible to both shuffle and playlists.
- `radio.py archive show` lists what's in there; `radio.py unarchive` lists it numbered; `radio.py unarchive 1,3` or `radio.py unarchive all` moves tracks back into the library. Restored tracks rejoin the **shuffle**, but are NOT re-added to a playlist they were dropped from — re-pick them with `radio play <numbers>` after a fresh `radio list`.
- `radio.py status` grows an `archive :` line whenever the archive is non-empty.
- **`radio.py drop`** is the same move for the track playing now, but into the one shared **`output/bad song`** folder instead of this library's `_archive`, whichever folder is playing. Use it for `/tfm drop` or "put this in bad song"; a plain "I hate this song" is still `archive`. No arguments (they print usage); `Nothing is playing.` when stopped or paused; refused when the library *is* `bad song`. There's no `undrop`; to hear the rejects, `radio.py folder "output/bad song"`. In `radio prompts` a dropped track's entry shows `b`.

## Prompt history (never lose a good prompt)

- `radio.py prompts` (aliases `history`, `prompt-history`) prints every track the radio has ever generated, newest first, as `<n>. <date> <duration> <the idea or prompt>`. `radio.py prompts all` drops the 20-entry cap; `radio.py prompts <text>` searches idea + prompt; `radio.py prompts 4` shows one entry in full and prints a **ready-to-run `radio gen` line** to make another like it.
- Numbers are positions in the file and never shift as new tracks are generated, so `radio prompts 4` means the same entry tomorrow.
- A trailing marker shows where each track is now: blank = in the library, `a` = archived, `b` = in `output/bad song`, `x` = the file is gone, `e` = an `enhance` rewrite that was never generated. So the history survives archiving and deletion — the prompt outlives the mp3.
- Stored append-only as JSON Lines in `~/.claude/terminal-fm/prompt_history.jsonl` (one record: `ts`, `prompt`, `duration`, `file`, `idea` when it came from `egen` / `enhance`, `source`, plus `kind` only on an enhance-only entry). `gen` and `egen` write a record per successful track; **`enhance` also writes one** (empty `file`, shown with an `e` mark), so a rewrite the user liked but didn't generate can still be found and generated later. Failed generations are not recorded.

## Library folder (which folder it plays from)
- By default the radio plays `.mp3` / `.wav` files from `~/.claude/terminal-fm/output/`. `radio.py folder "<path>"` points it at any other folder — an absolute path, `~`, env vars, or a path relative to `~/.claude/terminal-fm` (e.g. `radio.py folder output/<collection>` to play just that sub-collection). The folder is created if missing.
- `radio.py folder` (no arg) prints the current folder + track count; `radio.py folder default` (aliases `reset`/`clear`) reverts to `output/`. Persisted in `config.json` under `library_dir`.
- The glob is **non-recursive** (top-level `.mp3` / `.wav` only), so pointing at a parent won't pull in subfolders — point directly at the folder whose tracks you want.
- A **running daemon won't pick up the change** — it read the folder at launch. After changing it while playing, `radio.py stop` then `radio.py play` to reshuffle from the new folder. `gen` also writes new tracks into whatever the current folder is.

## Pause vs. stop
- `radio.py pause` remembers the **current track and exact position**, tears down the daemon, and sets status `paused`. The next `radio.py play` (no `--say`) **resumes right there** — the daemon replays that track from a seek offset before returning to normal shuffle.
- `radio.py stop` is a hard stop: it also clears the pause point, so the next `play` starts a **fresh shuffle** from the top of a track. Use `stop` to fully turn it off, `pause` to hold.
- Resume-at-offset works on **mpv / ffplay / cvlc**; **afplay / mpg123** restart the paused track from the top (no clean seconds-seek). The pause point lives in `resume.json`.

## DJ — the queue
- The DJ speaks from a **queue** of lines. The daemon speaks ONE queued line before each track (the first one is the sign-on, before track 1). **Empty queue = silence.**
- **YOU (Claude) write the lines.** You're the AI in the loop, so feed the queue with short, in-character radio-DJ lines about the current work:
  - On `play`: pass `--say "<short sign-on>"` (goes to the front of the queue).
  - Anytime: `radio.py say "<line>"` (alias `dj`) to enqueue an update.
- Keep each line to **1-2 sentences** — Kokoro synth on CPU is ~1s per ~3 words, and a line is spoken between tracks (blocking that gap). Voice = Kokoro-82M (`dj.py say` / `kokoro_tts.py`) when it's installed, otherwise the system voice (Windows SAPI, macOS `say`, espeak).
- No language model is involved in any of this: every line is spoken verbatim.

## DJ — idle announcements (works with music stopped)
- `radio.py announce on` makes the DJ speak a short update **whenever Claude finishes a turn, even when no music is playing**. `off` disables it; bare `announce` prints the current state. Persisted in `config.json` under `dj.announce_when_idle` (default off).
- Mechanism: the Claude Code **Stop hook** (`radio.py hook Stop`, wired by this plugin's `hooks/hooks.json`, or by `settings.json` on the manual install) normally only enqueues a line while the radio is on air. With this setting on, it instead **speaks the line immediately** when the radio is stopped. The line is Claude's last message, taken from the hook input's `last_assistant_message`, else from the session transcript (falls back to a generic line).
- Overlap-safe: a stale-aware `dj_speaking.lock` keeps two rapid turns from talking over each other. SessionStart does not trigger an idle announcement — only "finished a turn" events do.

## DJ — breaking news (interrupt playing music, then resume)
- `radio.py breaking on` makes a turn-end **interrupt the current track** to speak the update, then **resume that track where it left off**. `off` (default) means updates just queue and are read in the gap before the next track. Bare `breaking` prints the current state. Persisted in `config.json` under `dj.breaking_news`. Also reachable as `radio.py announce breaking on|off`.
- Uses the same recap source as `announce` (Claude's last message). Mechanism: the Stop hook writes the line to `breaking.txt` and kills the current player; the daemon's wait() returns, it speaks the line (music paused), then relaunches the same track with a seek offset.
- Resume-at-offset works on **mpv / ffplay / cvlc**; **afplay / mpg123** restart the track from the top instead (no clean seconds-seek). Independent of `announce` (stopped-music case).

## Troubleshooting — "robotic" DJ voice
- The good voice is Kokoro-82M (`am_michael`); the "robotic" voice is the Windows SAPI fallback `dj.py` uses when Kokoro is not installed or a render fails. With Kokoro installed, the usual cause is a daemon launched by a Python that lacks `kokoro_onnx` (it exits `rc=3` → SAPI).
- `dj.py` self-heals: it finds a `kokoro_onnx`-capable interpreter, caches it in `~/.claude/terminal-fm/.kokoro_python` (shared across all daemons/hooks), renders to a per-process WAV (no cross-process corruption), and self-clears a bad cache on failure.
- Every utterance is logged to `~/.claude/terminal-fm/dj_engine.log` (`engine  detail  py=  text`). To diagnose a flip to robotic, read the tail — a `kokoro-fail` line names the exact interpreter and error, immediately followed by `sapi ROBOTIC FALLBACK`. `kokoro-skip` then `ROBOTIC FALLBACK - kokoro not installed` just means Kokoro was never downloaded (README's "Optional extras"). Override the interpreter with `dj.python` in `config.json` if needed.

## Notes
- Audio player is auto-detected: mpv > ffplay > afplay (mac) > mpg123 > cvlc. If none is found, `play` prints the install command for the user's OS and `setup` lists it.
- The `source` is set in `config.json`; `stability-api` is the only one.
- The statusline refreshes on each turn and every `statusLine.refreshInterval` seconds (in `~/.claude/settings.json`), so the now-playing line can lag that long behind `radio status`.
- A plugin can't set the statusline. If the user asks for the radio in theirs, follow Optional extras above with `radio.py setup statusline`: it prints the exact `statusLine` line for their `settings.json`, or says what their own statusline should print. Add exactly that line, and only after they say yes. The session-start hook copies `statusline.py` to `~/.claude/terminal-fm/statusline.py`, and `statusLine` should run that copy.
- If the library is empty, `play` says so — generate a track first.
