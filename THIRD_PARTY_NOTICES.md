# Third-party notices

Terminal FM itself is MIT-licensed (see `LICENSE`). **This repository bundles no third-party code, model weights or tokenizers.** Everything below is optional, is downloaded by you, and is governed by its own license, which you accept when you download it. The radio degrades gracefully without each item (see `README.md`, Requirements).

`<data dir>` below is the radio's data directory: `~/.claude/terminal-fm` by default, or the folder named by the `TERMINAL_FM_HOME` environment variable.

License names were checked against the linked pages on 2026-09-28. Licenses change; the page you download from is authoritative, not this file.

## Kokoro-82M (DJ voice)

- **Used for:** the DJ voice. `dj.py` renders every spoken line through `kokoro_tts.py`, which loads these two files. Without them the DJ falls back to Piper, macOS `say`, Windows SAPI or espeak.
- **Files and placement:** `kokoro-v1.0.fp16.onnx` and `voices-v1.0.bin` in `<data dir>/kokoro/`. `kokoro_tts.py` also accepts `kokoro-v1.0.onnx` or `kokoro-v1.0.int8.onnx` in that folder if you prefer another precision.
- **License:** Apache License 2.0. Verified on the model card at <https://huggingface.co/hexgrad/Kokoro-82M> (license tag `apache-2.0`; the card describes the weights as "Apache-licensed"; the repo is not gated).
- **Download:** the ONNX export and voice pack are release assets of the `kokoro-onnx` project: <https://github.com/thewh1teagle/kokoro-onnx/releases/tag/model-files-v1.1>. Download `kokoro-v1.0.fp16.onnx` and `voices-v1.0.bin` and place them in `<data dir>/kokoro/`. The original PyTorch weights are at the Hugging Face page above.

## `kokoro-onnx` and `soundfile` (Python packages, `kokoro_tts.py` only)

- **Used for:** `kokoro_tts.py` imports `kokoro_onnx` to run the model and `soundfile` to write the WAV. They are the only third-party imports in the project; `radio.py` and `dj.py` are standard library only. Install them into any Python interpreter with `pip install -U kokoro-onnx soundfile` (the model in the `model-files-v1.1` release needs kokoro-onnx 0.6 or newer); `dj.py` finds that interpreter itself (or set `dj.python` in `config.json`).
- **`kokoro-onnx` license:** MIT for the package code; the project states "kokoro-onnx: MIT" and "kokoro model: Apache 2.0". Verified at <https://pypi.org/project/kokoro-onnx/> (latest 0.6.1 as read) and <https://github.com/thewh1teagle/kokoro-onnx>.
- **`soundfile` license:** BSD 3-Clause. Verified at <https://pypi.org/project/soundfile/> (latest 0.14.0 as read). Its page notes that file I/O goes through `libsndfile`, which is LGPL; the wheels ship it as a shared library.
- Transitive dependencies of these packages (for example the ONNX runtime `kokoro-onnx` pulls in) were not checked here; `pip show` lists them.

## Qwen3-4B-Instruct-2507, Q4_K_M GGUF (prompt enhancer and duration pick)

- **Used for:** `radio enhance`, `radio egen` and the automatic duration pick in `radio gen`. Runs CPU-only through `llama-cli` (below). Without it, `enhance` passes your idea through unchanged and `gen` picks durations from keyword rules.
- **File and placement:** `<data dir>/llm/qwen3-4b-instruct-q4km.gguf`. Any `.gguf` filename works: the radio uses the first `.gguf` in `<data dir>/llm/` in sorted order, so keep one model there.
- **License:** Apache License 2.0. Verified on the model card at <https://huggingface.co/Qwen/Qwen3-4B-Instruct-2507> (license tag `apache-2.0`, not gated). The Unsloth GGUF repository carries the same `apache-2.0` tag, verified at <https://huggingface.co/unsloth/Qwen3-4B-Instruct-2507-GGUF> (not gated).
- **Download:** from <https://huggingface.co/unsloth/Qwen3-4B-Instruct-2507-GGUF>, the `Q4_K_M` file (about 2.5 GB as listed there). Save it into `<data dir>/llm/`.

## llama.cpp `llama-cli` (runs the GGUF model)

- **Used for:** the executable that loads the GGUF above for `enhance`, `egen` and the duration pick.
- **File and placement:** `<data dir>/llm/bin/llama-cli` (`llama-cli.exe` on Windows), or `llama-cli` anywhere on `PATH`.
- **License:** MIT. Verified at <https://github.com/ggml-org/llama.cpp/blob/master/LICENSE> ("MIT License", "Copyright (c) 2023-2026 The ggml authors") and the README badge at <https://github.com/ggml-org/llama.cpp>.
- **Download:** prebuilt archives for Windows, macOS and Linux are on the releases page: <https://github.com/ggml-org/llama.cpp/releases> (for example `llama-bNNNN-bin-win-cpu-x64.zip`). Unpack it and copy the `llama-cli` executable (plus the shared libraries next to it in the archive) into `<data dir>/llm/bin/`. Note: the radio was verified against build b10069, which ships `llama-cli`, and on Windows against b11581 (2026-10-13), whose archive still does; the upstream README as read on 2026-09-28 shows the newer `llama cli` subcommand form, so if your archive has no `llama-cli` executable check the archive contents and the release notes before assuming the radio will find it.

## T5Gemma tokenizer (exact prompt-length check, optional)

- **Used for:** counting a prompt's tokens exactly the way Stable Audio 3's T5Gemma text encoder does, so `gen`, `egen` and `enhance` can refuse a prompt over the 256-token limit before it is billed. **Optional:** without the file the radio estimates the count at 4 characters a token and says so.
- **File and placement:** the `tokenizer.json` from <https://huggingface.co/google/t5gemma-b-b-ul2> (34.4 MB as listed), saved as `<data dir>/llm/t5gemma-tokenizer.json`.
- **License and terms:** Google's **Gemma Terms of Use**, <https://ai.google.dev/gemma/terms>, together with the **Gemma Prohibited Use Policy**, <https://ai.google.dev/gemma/prohibited_use_policy>. The model card lists its license as `gemma` (verified 2026-09-28). The Terms are not an open-source license: section 3.1 conditions any redistribution of Gemma or its derivatives on passing the use restrictions through to recipients, and section 3.2 binds users to the Prohibited Use Policy.
- **The repository is gated.** Verified 2026-09-28: the Hugging Face page says "This repository is publicly accessible, but you have to accept the conditions to access its files and content." You must log in to Hugging Face, review and accept Google's terms on that page, and download `tokenizer.json` yourself.
- **This project will never redistribute the tokenizer**, in the repository, in releases, or by download script. `.gitignore` excludes `llm/t5gemma-tokenizer.json` and `release_check.py` fails on any tracked file over 5 MB.

## Stability AI API (music generation)

- **Used for:** `radio gen` and `radio egen` send prompts to Stability AI's hosted Stable Audio 3 endpoint (`api.stability.ai`) and save the returned audio into your library. Not software and nothing is downloaded: it is a paid web service and every successful generation costs credits on your account.
- **Terms:** your use is governed by Stability AI's terms and acceptable-use rules, not by this project's MIT license. Acceptable Use Policy: <https://stability.ai/use-policy> (title verified 2026-09-28: "Acceptable Use Policy", covering Stability "models, products and services, application programming interfaces"). Terms of Service: <https://stability.ai/2025-terms-of-service> (title verified 2026-09-28 as "2025 Terms of Service"; the body did not load in this check, so read it on the site). The developer platform's own terms link is <https://platform.stability.ai/legal/terms-of-service>.
- **Key:** you need your own API key, kept in `<data dir>/.key` or the `STABILITY_API_KEY` environment variable. The repository ships no key and the key file is ignored by git. See `SECURITY.md` for how the key is used.
- Generated audio is yours to use under whatever rights Stability's terms grant; this project claims nothing over it.

## Audio players and system TTS

The radio shells out to whichever of `mpv`, `ffplay` (FFmpeg), `afplay`, `mpg123` or `cvlc` (VLC) it finds, and to Piper, macOS `say`, Windows SAPI or `espeak` as voice fallbacks. None is bundled; each is licensed by its own project and installed by you.
