#!/usr/bin/env python3
"""
Kokoro-82M TTS wrapper for AI Radio. Renders text -> WAV using kokoro-onnx
(onnxruntime; no PyTorch). Called by dj.py; also runnable standalone.

    echo "hello" | python kokoro_tts.py --out out.wav --voice am_michael

Model files live in <data dir>/kokoro/ (kokoro-v1.0.fp16.onnx + voices-v1.0.bin), where the data
dir is ~/.claude/radio or $AI_RADIO_HOME. Requires: pip install -U kokoro-onnx soundfile (the
current kokoro-v1.0.fp16.onnx download needs kokoro-onnx 0.6 or newer).
"""
import argparse
import os
import sys
from pathlib import Path

ROOT = Path(os.path.expanduser(os.environ.get("AI_RADIO_HOME", "").strip()
                               or str(Path.home() / ".claude" / "radio")))
KDIR = ROOT / "kokoro"
MODEL_CANDIDATES = ("kokoro-v1.0.fp16.onnx", "kokoro-v1.0.onnx", "kokoro-v1.0.int8.onnx")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--text", default=None, help="text (default: read stdin)")
    ap.add_argument("--voice", default="am_michael")
    ap.add_argument("--speed", type=float, default=1.0)
    ap.add_argument("--lang", default="en-us")
    ap.add_argument("--out", default=str(ROOT / "_dj.wav"))
    ap.add_argument("--model", default=None)
    ap.add_argument("--voices", default=str(KDIR / "voices-v1.0.bin"))
    a = ap.parse_args()

    text = (a.text if a.text is not None else sys.stdin.read()).strip()
    if not text:
        print("no text", file=sys.stderr)
        return 1

    model = a.model
    if not model:
        for c in MODEL_CANDIDATES:
            if (KDIR / c).exists():
                model = str(KDIR / c)
                break
    if not model or not Path(model).exists():
        print(f"kokoro model not found in {KDIR}", file=sys.stderr)
        return 2

    try:
        from kokoro_onnx import Kokoro
        import soundfile as sf
    except Exception as e:
        print(f"kokoro-onnx not installed: {e}", file=sys.stderr)
        return 3

    k = Kokoro(model, a.voices)
    samples, sr = k.create(text, voice=a.voice, speed=a.speed, lang=a.lang)
    sf.write(a.out, samples, sr)
    print(a.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
