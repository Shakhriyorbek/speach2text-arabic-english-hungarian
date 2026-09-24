"""
Offline smoke test — no microphone needed.

Runs a WAV file through the exact same Transcriber + Translator the live app
uses — honouring config.ASR_LOCATION and config.TRANSLATION_PATH — and prints
the transcript and final Hungarian with per-stage timings. Use it to verify the
model chain works before ever touching a mic.

Because it follows config.py, the remote paths need WHISPER_SERVER_TOKEN in the
environment and the GPU server reachable, exactly as the live app does. Point it
at a pod by setting WHISPER_SERVER_URL (run.bat does this from pod_url.txt).

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

import config
from subtitles.asr import Transcriber
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

    # Mirror app.py exactly. This harness previously hard-wired the local
    # Transcriber and the English->Hungarian Translator, so it silently tested a
    # different pipeline than the one that runs on Friday: with the direct path
    # configured it fed Arabic to an English-only model, which does not error —
    # it returns fluent, unrelated Hungarian. Selecting the same way app.py does
    # is the whole point of a smoke test.
    direct = getattr(config, "TRANSLATION_PATH", "pivot").lower() == "direct"

    transcriber = Transcriber()
    transcriber.mode = args.mode

    if direct:
        from subtitles.mt_direct import DirectTranslator
        translator = DirectTranslator()
    else:
        from subtitles.mt import Translator
        translator = Translator()

    if getattr(config, "ASR_LOCATION", "cpu").lower() == "remote":
        from subtitles.asr_remote import RemoteTranscriber
        transcriber = RemoteTranscriber(local_fallback=transcriber)
        transcriber.mode = args.mode

    # ...and the same for translation. This was missing: the harness honoured
    # ASR_LOCATION but always translated locally, so with MT_LOCATION="remote"
    # it measured the laptop's 600M while Friday ran the GPU's 1.3B. Same class
    # of bug as the one described above, one stage further down the pipeline —
    # a smoke test that quietly exercises a different chain than the live app
    # is worse than no smoke test, because it is believed.
    mt_where = getattr(config, "MT_LOCATION", "cpu").lower()
    if direct and mt_where == "remote":
        from subtitles.mt_remote import RemoteTranslator
        translator = RemoteTranslator(local_fallback=translator)

    where = getattr(config, "ASR_LOCATION", "cpu")
    path = "direct AR->HU" if direct else "pivot AR->EN->HU"
    print(f"  models loaded in {time.time() - t:.1f}s "
          f"(mode={args.mode}, asr={where}, mt={mt_where}, path={path})")

    t = time.time()
    source = transcriber.transcribe(audio)
    t_asr = time.time() - t

    # The direct translator needs to know what language it was handed; on the
    # pivot path the text is already English and src_lang is irrelevant.
    if direct:
        translator.src_lang = getattr(transcriber, "last_language", "ar")

    t = time.time()
    hungarian = translator.translate(source) if source else ""
    t_mt = time.time() - t

    label = getattr(transcriber, "last_language", "ar").upper() if direct else "EN"
    secs = len(audio) / 16000
    print("\n--- RESULT ---")
    print(f"{label} ({t_asr:.2f}s = {secs / t_asr:.1f}x realtime): {source!r}")
    print(f"HU ({t_mt:.2f}s): {hungarian!r}")

    if getattr(transcriber, "_using_fallback", False):
        print("\nNOTE: the remote server was unreachable for TRANSCRIPTION — this "
              "ran on the LOCAL Whisper model, so the quality above is not what "
              "the GPU path produces.")
    if getattr(translator, "_using_fallback", False):
        print("\nNOTE: the remote server was unreachable for TRANSLATION — the "
              "Hungarian above came from this laptop's 600M model, not the GPU's "
              "1.3B. These two fall back independently, so one can be degraded "
              "while the other is fine.")


if __name__ == "__main__":
    main()
