"""
Compare two translation models on the same Arabic, honestly.

Why this is a separate tool. Swapping NLLB-1.3B for 3.3B is the obvious way to
spend a GPU budget, and it is not obviously right: names.py records that 3.3B
was already tried on the proper-name problem and was *the worst of the three*.
It should buy meaning fidelity — the failure where "we seek His forgiveness"
came out as "we forgive Him" — and nothing else. This project measures before it
changes things (see the WHISPER_INITIAL_PROMPT_AR post-mortem in config.py), and
a model swap deserves the same treatment.

Why not test_pipeline.py: that runs a whole WAV through as ONE utterance, so it
gives you a single data point. Judging a translation model needs the forty-odd
short lines a real khutbah actually produces.

The protocol, which matters more than this file does:

    1. python compare_mt.py --url <pod> --wav khutbah.wav --extract arabic.txt
       Slices the audio the way the laptop's VAD would and transcribes each
       piece. FREEZE the result.
    2. Start the server with NLLB_MODEL_DIR=<the 1.3B>, then:
       python compare_mt.py --url <pod> --lines arabic.txt --out a.tsv
    3. Restart with NLLB_MODEL_DIR=<the 3.3B> and repeat into b.tsv.
    4. Put a.tsv and b.tsv side by side and have someone who reads Arabic AND
       Hungarian mark each line better / same / worse.

Step 1 is the point of the whole thing: with the Arabic frozen, the only thing
that differs between a.tsv and b.tsv is the translation model. Transcribing
twice would mix ASR variation into the comparison and tell you nothing.

Look for the two named failure modes rather than a general impression:
    * INVERSION      — the meaning is reversed ("we forgive Him")
    * LOST QUALIFIER — a word like "forbidden" or "not" silently dropped
If 3.3B does not move those, it is not worth 6.6 GB and the extra latency.

Stdlib-only, like smoke_test.py, so it runs on the pod, on the mosque laptop,
and on any dev machine whose Python is too new for the project's dependencies.
"""

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
import wave

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from smoke_test import load_wav_pcm16, request      # noqa: E402  (same directory)

SAMPLE_RATE = 16000
BYTES_PER_SECOND = SAMPLE_RATE * 2


def extract(url, token, wav_path, out_path, window_s, mode, task):
    """Transcribe a recording in utterance-sized pieces, one line each.

    Fixed windows, not the real VAD: webrtcvad and sounddevice are not
    installed on a pod, and for THIS purpose the difference does not matter —
    we need a representative set of short Arabic lines, not a faithful replay
    of the chunker. MAX_UTTERANCE_S is the cap the VAD enforces anyway, so
    windows of that size are the same order of thing.
    """
    pcm, secs = load_wav_pcm16(wav_path)
    step = int(window_s * BYTES_PER_SECOND)
    total = (len(pcm) + step - 1) // step
    print(f"{secs:.0f}s of audio -> {total} windows of {window_s}s", flush=True)

    lines = []
    for i in range(total):
        chunk = pcm[i * step:(i + 1) * step]
        if len(chunk) < BYTES_PER_SECOND // 2:      # ignore a <0.5s tail
            continue
        try:
            res = request(url, token, "/transcribe", data=chunk, headers={
                "Content-Type": "application/octet-stream",
                "X-Mode": mode,
                "X-Task": task,
            })
        except urllib.error.HTTPError as exc:
            sys.exit(f"window {i + 1}: HTTP {exc.code} {exc.reason}")
        text = (res.get("text") or "").strip()
        print(f"  [{i + 1}/{total}] {text[:70]}", flush=True)
        if text:
            lines.append(text)

    with open(out_path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")
    print(f"\n{len(lines)} lines -> {out_path}")
    print("FREEZE this file. Both models must translate exactly these lines,")
    print("or you are measuring the transcriber as well.")


def translate_all(url, token, lines_path, out_path, src):
    with open(lines_path, encoding="utf-8") as fh:
        lines = [ln.strip() for ln in fh if ln.strip()]
    if not lines:
        sys.exit(f"{lines_path} has no lines in it.")

    info = request(url, token, "/health")
    model = info.get("translate_model")
    if not info.get("translate"):
        sys.exit("This server has translation disabled (no NLLB_MODEL_DIR). "
                 "Start it with the model you want to measure.")
    print(f"translating {len(lines)} lines with {model} "
          f"({info.get('translate_compute_type')}, "
          f"beam {info.get('translate_beam')})\n", flush=True)

    rows, total_ms = [], 0
    for i, line in enumerate(lines, 1):
        t0 = time.time()
        try:
            res = request(url, token, "/translate",
                          data=line.encode("utf-8"),
                          headers={"Content-Type": "text/plain; charset=utf-8",
                                   "X-Src-Lang": src})
        except urllib.error.HTTPError as exc:
            sys.exit(f"line {i}: HTTP {exc.code} {exc.reason}")
        hu = (res.get("text") or "").strip()
        total_ms += int((time.time() - t0) * 1000)
        rows.append((line, hu))
        print(f"  [{i}/{len(lines)}] {hu[:70]}", flush=True)

    with open(out_path, "w", encoding="utf-8") as fh:
        # A comment line so two files can never be confused for one another
        # weeks later, which is exactly when somebody will look at them again.
        fh.write(f"# model={model} lines={len(rows)} "
                 f"mean={total_ms // max(len(rows), 1)}ms\n")
        for ar, hu in rows:
            fh.write(f"{ar}\t{hu}\n")
    print(f"\n{len(rows)} lines -> {out_path}  "
          f"(mean {total_ms // max(len(rows), 1)}ms/line)")


def main():
    ap = argparse.ArgumentParser(
        description="A/B two translation models on identical Arabic.",
        epilog="See the module docstring for the full protocol.")
    ap.add_argument("--url", required=True, help="https://<POD_ID>-8756.proxy.runpod.net")
    ap.add_argument("--token", default=os.environ.get("WHISPER_SERVER_TOKEN", ""))
    ap.add_argument("--wav", help="recording to transcribe (with --extract)")
    ap.add_argument("--extract", help="write the Arabic lines here, then stop")
    ap.add_argument("--lines", help="Arabic lines to translate (from --extract)")
    ap.add_argument("--out", help="write arabic<TAB>hungarian here")
    ap.add_argument("--src", default="ar", help="source language (default ar)")
    ap.add_argument("--window", type=float, default=5.0,
                    help="seconds per window when extracting (default 5, "
                         "matching config.MAX_UTTERANCE_S)")
    ap.add_argument("--mode", default="part1", choices=("part1", "part2"))
    args = ap.parse_args()

    url = args.url.rstrip("/")
    if not args.token:
        sys.exit("No token. Pass --token or set WHISPER_SERVER_TOKEN.")

    if args.extract:
        if not args.wav:
            sys.exit("--extract needs --wav.")
        # transcribe, never translate: we want the Arabic, and the server's
        # default task is translate, which would hand us English.
        extract(url, args.token, args.wav, args.extract, args.window,
                args.mode, "transcribe")
        return 0

    if args.lines:
        if not args.out:
            sys.exit("--lines needs --out.")
        translate_all(url, args.token, args.lines, args.out, args.src)
        return 0

    ap.print_help()
    return 2


if __name__ == "__main__":
    sys.exit(main())
