# Examples

What Terminal FM sounds and looks like, made on 2026-10-19.

| File | What it is |
|---|---|
| `terminal-fm-demo.mp4` | A 67-second demo with sound: `/tfm setup`, `/tfm eg lofi hip hop`, `/tfm p` with the DJ's sign-on, a Claude reply, and `/tfm n` with the DJ's recap before the next track. |
| `lofi-hip-hop-track.mp3` | The track `/tfm eg lofi hip hop` made: 150 seconds, Stable Audio 3, chosen length and prompt below. |
| `dj-voice.wav` | The DJ's recap after a Claude turn, in the Kokoro voice (`am_michael`), as the radio speaks it between tracks. |

**The track's prompt,** as the enhancer wrote it from "lofi hip hop": *Mellow lo-fi hip-hop instrumental, warm Rhodes jazz chords, softly plucked upright bass, dusty swung drums, sparse piano motif, faint vinyl texture, intimate tape-warmed mix, peaceful, nostalgic, gently drifting, in F major, 74 BPM.* The local model picked 150 seconds.

**The DJ line** is what the Stop hook builds from Claude's last reply: "Here's the latest from the terminal-fm desk. The setup wizard now shows one step at a time." No language model writes or changes it; Kokoro reads it as written.

**About the video:** the command output, the voice, the music and the statusline text are real. The terminal is drawn frame by frame rather than screen-recorded, the Claude reply is a sample, and the `egen` step is sped up (it takes about a minute).
