"""
Offline smoke test — no microphone needed.

Runs a WAV file through the exact same Transcriber + Translator the live app
uses, printing the intermediate English and final Hungarian with per-stage
timings. Use it to verify the model chain works before ever touching a mic.

Usage:
    python -m subtitles.test_pipeline path/to/file.wav
    python -m subtitles.test_pipeline path/to/file.wav --mode part2

Record a short test clip with the Windows "Voice Recorder" app (export/convert
to .wav), or use any WAV you have. Any sample rate / channel count is accepted;
it is resampled to 16 kHz mono here.
"""

import argparse
import time
import wave

import numpy as np

from subtitles.asr import Transcriber
from subtitles.mt import Translator
from subtitles.console import enable_utf8_console

enable_utf8_console()


def load_wav_16k_mono(path: str) -> np.ndarray:
    """Load a WAV as float32 mono @16 kHz in [-1, 1] using only the stdlib."""
    with wave.open(path, "rb") as wf:
        n_channels = wf.getnchannels()
        sampwidth = wf.getsampwidth()
        rate = wf.getframerate()
        frames = wf.readframes(wf.getnframes())

    if sampwidth == 2:
        data = np.frombuffer(frames, dtype=np.int16).astype(np.float32) / 32768.0
    elif sampwidth == 4:
        data = np.frombuffer(frames, dtype=np.int32).astype(np.float32) / 2147483648.0
    elif sampwidth == 1:
        # 8-bit WAV is unsigned, centred at 128.
        data = (np.frombuffer(frames, dtype=np.uint8).astype(np.float32) - 128) / 128.0
    else:
        raise ValueError(f"Unsupported sample width: {sampwidth} bytes")

    # De-interleave channels and average to mono.
    if n_channels > 1:
        data = data.reshape(-1, n_channels).mean(axis=1)

    # Resample to 16 kHz with simple linear interpolation (good enough for ASR).
    target = 16000
    if rate != target:
        n_out = int(round(len(data) * target / rate))
        if n_out > 1:
            x_old = np.linspace(0.0, 1.0, num=len(data), endpoint=False)
            x_new = np.linspace(0.0, 1.0, num=n_out, endpoint=False)
            data = np.interp(x_new, x_old, data).astype(np.float32)

    return np.ascontiguousarray(data, dtype=np.float32)


def main():
    ap = argparse.ArgumentParser(description="Offline WAV -> EN -> HU smoke test.")
    ap.add_argument("wav", help="path to a .wav file")
    ap.add_argument("--mode", choices=("part1", "part2"), default="part1",
                    help="part1 = force Arabic, part2 = auto-detect (default part1)")
    args = ap.parse_args()

    print(f"Loading audio: {args.wav}")
    audio = load_wav_16k_mono(args.wav)
    print(f"  {len(audio) / 16000:.1f}s of audio at 16 kHz mono.")

    print("Loading models...")
    t = time.time()
    transcriber = Transcriber()
    transcriber.mode = args.mode
    translator = Translator()
    print(f"  models loaded in {time.time() - t:.1f}s (mode={args.mode})")

    t = time.time()
    english = transcriber.transcribe(audio)
    t_asr = time.time() - t

    t = time.time()
    hungarian = translator.translate(english) if english else ""
    t_mt = time.time() - t

    print("\n--- RESULT ---")
    print(f"EN ({t_asr:.2f}s): {english!r}")
    print(f"HU ({t_mt:.2f}s): {hungarian!r}")


if __name__ == "__main__":
    main()
