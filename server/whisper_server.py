"""
GPU transcription server — runs on the rented GPU, not on the mosque laptop.

Why this exists: a weak laptop CPU caps Whisper at "small", which is not good
enough for Arabic (measured: it dropped most of a real khutbah). The same audio
through "large-v3" on a Tesla T4 runs ~30x realtime and picks up names, and
keeps negations that "small" and "medium" both mangled.

The laptop records audio exactly as before; it just sends each utterance here
instead of transcribing it locally, and falls back to the local model
automatically if this server is unreachable.

Deliberately stdlib-only (http.server) apart from faster-whisper: the VM disk is
tight and a single-client subtitle feed does not need a web framework.

Protocol
--------
POST /transcribe
    Authorization: Bearer <token>     (must match WHISPER_SERVER_TOKEN)
    X-Mode: part1 | part2             (part1 forces Arabic, part2 auto-detects)
    X-Task: transcribe | translate    (default translate, which returns ENGLISH;
                                       the direct Arabic->Hungarian path needs
                                       transcribe and breaks silently without it)
    X-Partial: 1                      (optional; a snapshot of speech still in
                                       progress — decoded at a narrower beam.
                                       Absent means final.)
    X-Prompt-B64: <base64 utf-8>      (optional vocabulary hint, Part 1 only;
                                       base64 because HTTP headers are latin-1)
    body: raw little-endian int16 PCM, 16 kHz, mono
    -> 200 {"text": "...", "ms": 123, "dropped": 0, "language": "ar"}

POST /translate
    Authorization: Bearer <token>
    X-Src-Lang: ar | en               (default ar)
    body: UTF-8 text, at most 64 KiB
    -> 200 {"text": "...", "ms": 123}
    -> 501 when this server was started without NLLB_MODEL_DIR

GET /health                           (UNAUTHENTICATED, on purpose: the laptop
                                       must be able to ask before it has proved
                                       anything, and it leaks nothing)
    -> 200 {"ok": true, "model": ..., "device": ..., "compute_type": ...,
            "beam": {...}, "translate": bool, "translate_model": ...,
            "gpu": ..., "vram_gb": ..., "deadline": ...}

Run it:
    export WHISPER_SERVER_TOKEN="<a long random string>"
    ~/wbench/bin/python whisper_server.py

Normally nobody types that: START.bat on the laptop creates the pod with this
as its start command and passes the token in through the environment.
"""

import base64
import collections
import json
import os
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import numpy as np

from faster_whisper import WhisperModel

# --- settings (env-overridable so nothing secret lives in this file) --------

HOST = os.environ.get("WHISPER_SERVER_HOST", "0.0.0.0")
PORT = int(os.environ.get("WHISPER_SERVER_PORT", "8756"))
MODEL_SIZE = os.environ.get("WHISPER_MODEL", "large-v3")
DEVICE = os.environ.get("WHISPER_DEVICE", "cuda")
COMPUTE_TYPE = os.environ.get("WHISPER_COMPUTE_TYPE", "float16")

# Optional translation on the same GPU. NLLB-600M running on the laptop CPU was
# measured as the accuracy bottleneck once transcription moved to the T4: on
# flawless Arabic it inverted "we seek His forgiveness" into "we forgive Him".
# A larger NLLB is too slow on that CPU but trivial for an idle T4, which is
# already resident for Whisper. Empty NLLB_MODEL_DIR disables the endpoint.
NLLB_MODEL_DIR = os.environ.get("NLLB_MODEL_DIR", "").strip()
NLLB_DEVICE = os.environ.get("NLLB_DEVICE", "cuda")
NLLB_COMPUTE_TYPE = os.environ.get("NLLB_COMPUTE_TYPE", "float16")

# Search width, split between the two kinds of request. Four out of every five
# calls are snapshots of an utterance still being spoken, which get overwritten
# a second later; only the fifth — the final — reaches the projector and stays
# there. So spend the GPU on the one that is read.
#
# Beam 5 roughly doubles Whisper's decode time, which used to be unaffordable
# because everything was decoded at beam 1. Paying it on 20% of requests is not.
# On the laptop these stay at 1/2 via config.py; this is a GPU-only luxury.
BEAM_FINAL = int(os.environ.get("WHISPER_BEAM_FINAL", "5"))
BEAM_PARTIAL = int(os.environ.get("WHISPER_BEAM_PARTIAL", "1"))
NLLB_BEAM_SIZE = int(os.environ.get("NLLB_BEAM_SIZE", "4"))

# Vocabulary hint for Arabic (Part 1). Whisper mishears rare khutbah words the
# same way every time — "المجوسي" became "المجلسي" three times in one live test,
# which then translated as "the councillor" and "the table". Sent by the client
# so the wordlist is versioned with the project, not stranded on the server.
# Falls back to this default when the client sends nothing.
DEFAULT_INITIAL_PROMPT_AR = os.environ.get("WHISPER_INITIAL_PROMPT_AR", "").strip()

# Shared secret. The server refuses to start without one — an open transcription
# endpoint on a public IP is exactly the mistake that left Ollama world-readable.
TOKEN = os.environ.get("WHISPER_SERVER_TOKEN", "").strip()

MAX_BODY_BYTES = 16 * 1024 * 1024   # ~8 minutes of 16 kHz int16; refuse beyond.

# Same anti-hallucination guards as subtitles/asr.py, so the remote path filters
# exactly like the local one and the two stay comparable.
REPETITION_PENALTY = 1.15
NO_REPEAT_NGRAM = 3
COMPRESSION_RATIO_MAX = 2.4
LOGPROB_MIN = -1.0
NO_SPEECH_MAX = 0.6

_model = None
_translator = None

# A short rolling record of what the GPU has actually been asked to do.
# RunPod's API exposes no way to read a pod's console output, so without this
# the only record of a live khutbah is the laptop's own window — and when the
# question is "is the GPU doing the right thing", the laptop is the wrong place
# to ask. Bounded and in memory: this is a diagnostic, not a transcript, and
# the contents of a sermon should not outlive the pod.
_recent = collections.deque(maxlen=60)

# faster_whisper's WhisperModel.transcribe is not thread-safe on a shared model,
# and _do_translate sets tr.src_lang before calling tr.translate — two requests
# interleaving there would translate Arabic as if it were English, which NLLB
# renders as fluent, confident nonsense rather than an error.
#
# The subtitle client is single-threaded so this is normally unreachable. It
# stops being unreachable the moment anyone runs check_gpu.bat, smoke_test.py or
# compare_mt.py while a khutbah is live — which is exactly when nobody is
# watching the console.
_model_lock = threading.Lock()
_translator_lock = threading.Lock()

# Filled once at startup. /health is unauthenticated and the pre-flight polls
# it, so it must never shell out to nvidia-smi per request.
_gpu_info = {}


def probe_gpu():
    """Card name and VRAM, or {} when there is no usable GPU."""
    try:
        out = subprocess.run(
            ["nvidia-smi", "--query-gpu=name,memory.total",
             "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=10, check=True,
        ).stdout.strip().splitlines()[0]
        name, mib = (p.strip() for p in out.split(","))
        return {"gpu": name, "vram_gb": round(int(mib) / 1024, 1)}
    except Exception:
        return {}


def read_deadline():
    """When start_whisper.sh has arranged for this pod to terminate itself.

    Reported so the operator learns about it during check_gpu.bat rather than
    by the subtitles stopping. Read per request because the file is tiny and
    the deadline can be cancelled while we run.
    """
    try:
        with open(os.path.join(os.environ.get("WORKDIR", "/workspace"), "deadline")) as fh:
            return fh.read().strip() or None
    except OSError:
        return None


def get_model():
    global _model
    if _model is None:
        print(f"loading {MODEL_SIZE} on {DEVICE} ({COMPUTE_TYPE})...", flush=True)
        t0 = time.time()
        _model = WhisperModel(MODEL_SIZE, device=DEVICE, compute_type=COMPUTE_TYPE)
        print(f"model ready in {time.time() - t0:.1f}s", flush=True)
    return _model


def get_translator():
    """Lazily load NLLB, or None when translation is not configured here."""
    global _translator
    if not NLLB_MODEL_DIR:
        return None
    if _translator is None:
        # mt_direct.py is deployed next to this file. Reused rather than
        # reimplemented: the source-token/decoder-prefix handling it contains
        # fails silently (fluent nonsense) if it is written twice and drifts.
        from mt_direct import DirectTranslator

        print(f"loading NLLB from {NLLB_MODEL_DIR} on {NLLB_DEVICE} "
              f"({NLLB_COMPUTE_TYPE})...", flush=True)
        t0 = time.time()
        _translator = DirectTranslator(
            model_dir=NLLB_MODEL_DIR,
            device=NLLB_DEVICE,
            compute_type=NLLB_COMPUTE_TYPE,
            beam_size=NLLB_BEAM_SIZE,
        )
        print(f"translator ready in {time.time() - t0:.1f}s", flush=True)
    return _translator


def transcribe_pcm(pcm: bytes, mode: str, task: str = "translate", prompt: str = "",
                   is_partial: bool = False):
    """int16 PCM -> (text, n_dropped_segments, detected_language).

    task="translate" gives ENGLISH (Whisper can emit no other target language).
    task="transcribe" gives the SPOKEN language — needed by the direct
    Arabic->Hungarian path, which must not be handed English by mistake.

    is_partial marks a snapshot of an utterance still being spoken. It buys
    speed at the cost of accuracy, which is the right way round: a snapshot is
    replaced a second later, a final is what the congregation reads.
    """
    audio = np.frombuffer(pcm, dtype=np.int16).astype(np.float32) / 32768.0

    # Part 1 only: an Arabic prompt would skew Part 2's language auto-detect.
    hint = (prompt or DEFAULT_INITIAL_PROMPT_AR) if mode == "part1" else ""

    model = get_model()
    with _model_lock:
        segments, info = model.transcribe(
            audio,
            task=task,
            language="ar" if mode == "part1" else None,
            initial_prompt=hint or None,
            beam_size=BEAM_PARTIAL if is_partial else BEAM_FINAL,
            temperature=0.0,
            condition_on_previous_text=False,  # stops repetition loops
            repetition_penalty=REPETITION_PENALTY,
            no_repeat_ngram_size=NO_REPEAT_NGRAM,
            without_timestamps=True,
            vad_filter=False,                  # the laptop's VAD already ran
        )
        # faster-whisper yields segments lazily, so the decode has NOT happened
        # yet — draining the generator inside the lock is what actually makes
        # this exclusive.
        segments = list(segments)

    kept, dropped = [], 0
    for s in segments:
        if (s.no_speech_prob or 0) > NO_SPEECH_MAX:
            dropped += 1
        elif (s.compression_ratio or 0) > COMPRESSION_RATIO_MAX:
            dropped += 1
        elif (s.avg_logprob or 0) < LOGPROB_MIN:
            dropped += 1
        else:
            piece = s.text.strip()
            if piece:
                kept.append(piece)
    lang = "ar" if mode == "part1" else (getattr(info, "language", None) or "ar")
    return " ".join(kept).strip(), dropped, lang


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def _json(self, code, payload):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _authorized(self):
        supplied = self.headers.get("Authorization", "")
        expected = f"Bearer {TOKEN}"
        # Constant-ish comparison; token is short-lived and self-hosted, but
        # there is no reason to leak length/prefix through early exit.
        if len(supplied) != len(expected):
            return False
        return all(a == b for a, b in zip(supplied, expected))

    def do_GET(self):
        if self.path == "/health":
            # Everything here exists so that degradation is VISIBLE. The whole
            # remote path is built to fall back quietly rather than fail, which
            # is right on the day and means nothing announces itself — so the
            # pre-flight has to be able to ask.
            payload = {
                "ok": True,
                "model": MODEL_SIZE,
                "device": DEVICE,
                "compute_type": COMPUTE_TYPE,
                "beam": {"final": BEAM_FINAL, "partial": BEAM_PARTIAL},
                # The client uses this to decide whether it may send text here
                # at all, rather than discovering it via a 404 mid-sermon.
                "translate": bool(NLLB_MODEL_DIR),
                "translate_model": os.path.basename(NLLB_MODEL_DIR) or None,
                "translate_compute_type": NLLB_COMPUTE_TYPE if NLLB_MODEL_DIR else None,
                "translate_beam": NLLB_BEAM_SIZE if NLLB_MODEL_DIR else None,
            }
            payload.update(_gpu_info)
            deadline = read_deadline()
            if deadline:
                payload["deadline"] = deadline
            self._json(200, payload)
        elif self.path == "/recent":
            # Authenticated, unlike /health: this carries the words of a
            # sermon, and the proxy URL is public and guessable.
            if not self._authorized():
                self._json(401, {"error": "bad or missing bearer token"})
                return
            self._json(200, {"count": len(_recent), "recent": list(_recent)})
        else:
            self._json(404, {"error": "not found"})

    def _do_translate(self):
        tr = get_translator()
        if tr is None:
            self._json(501, {"error": "translation not enabled on this server"})
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            self._json(400, {"error": "bad Content-Length"})
            return
        if length <= 0:
            self._json(400, {"error": "empty body"})
            return
        if length > 64 * 1024:          # one utterance, not a document
            self._json(413, {"error": "text too large"})
            return

        text = self.rfile.read(length).decode("utf-8", errors="replace").strip()
        if not text:
            self._json(200, {"text": "", "ms": 0})
            return

        src = self.headers.get("X-Src-Lang", "ar")
        t0 = time.time()
        try:
            # src_lang is instance state, so setting it and translating must be
            # one operation. Interleaved, a request would be translated as the
            # other one's language — which NLLB does not reject, it just
            # produces confident nonsense.
            with _translator_lock:
                tr.src_lang = src
                out = tr.translate(text)
        except Exception as exc:                    # never let one line kill it
            print(f"[translate error] {type(exc).__name__}: {exc}", flush=True)
            self._json(500, {"error": f"{type(exc).__name__}: {exc}"})
            return

        ms = int((time.time() - t0) * 1000)
        print(f"  translate[{src}] {ms}ms  {text[:40]} -> {out[:40]}", flush=True)
        _recent.append({"t": time.strftime("%H:%M:%S"), "op": "mt",
                        "src": src, "ms": ms, "text": text, "out": out})
        self._json(200, {"text": out, "ms": ms})

    def do_POST(self):
        if self.path not in ("/transcribe", "/translate"):
            self._json(404, {"error": "not found"})
            return
        if not self._authorized():
            self._json(401, {"error": "bad or missing bearer token"})
            return
        if self.path == "/translate":
            self._do_translate()
            return

        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            self._json(400, {"error": "bad Content-Length"})
            return
        if length <= 0:
            self._json(400, {"error": "empty body"})
            return
        if length > MAX_BODY_BYTES:
            self._json(413, {"error": "audio too large"})
            return

        pcm = self.rfile.read(length)
        mode = self.headers.get("X-Mode", "part1")
        if mode not in ("part1", "part2"):
            mode = "part1"
        task = self.headers.get("X-Task", "translate")
        if task not in ("translate", "transcribe"):
            task = "translate"
        # Absent means final. An old client that does not send this header gets
        # the careful beam on everything — slower, never wrong.
        is_partial = self.headers.get("X-Partial", "") == "1"
        # Header is base64 so the Arabic survives HTTP's latin-1 header encoding.
        prompt = ""
        raw = self.headers.get("X-Prompt-B64", "")
        if raw:
            try:
                prompt = base64.b64decode(raw).decode("utf-8")
            except Exception:
                prompt = ""     # a bad hint must never fail the utterance

        t0 = time.time()
        try:
            text, dropped, lang = transcribe_pcm(pcm, mode, task, prompt, is_partial)
        except Exception as exc:                    # never let one chunk kill it
            print(f"[error] {type(exc).__name__}: {exc}", flush=True)
            self._json(500, {"error": f"{type(exc).__name__}: {exc}"})
            return

        ms = int((time.time() - t0) * 1000)
        secs = len(pcm) / 2 / 16000
        kind = "partial" if is_partial else "final"
        print(f"  {secs:.1f}s audio -> {ms}ms ({secs / (ms / 1000 or 1):.1f}x) "
              f"[{mode}/{task}/{lang}/{kind}] {text[:80]}", flush=True)
        if not is_partial:          # snapshots are drafts; keep only finals
            _recent.append({"t": time.strftime("%H:%M:%S"), "op": "asr",
                            "mode": mode, "lang": lang, "secs": round(secs, 1),
                            "ms": ms, "dropped": dropped, "text": text})
        self._json(200, {"text": text, "ms": ms, "dropped": dropped, "language": lang})

    def log_message(self, fmt, *args):
        pass    # we print our own, quieter, line per request


def main():
    if not TOKEN:
        sys.exit(
            "WHISPER_SERVER_TOKEN is not set.\n"
            "Refusing to start an unauthenticated transcription endpoint on a\n"
            "public IP. Generate one with:  openssl rand -hex 32"
        )
    global _gpu_info
    _gpu_info = probe_gpu()
    if _gpu_info:
        print(f"{_gpu_info['gpu']}, {_gpu_info['vram_gb']} GB", flush=True)

    get_model()      # load before accepting traffic, so the first khutbah
                     # utterance is not charged the model load time
    get_translator() # same for NLLB when this box also translates
    srv = ThreadingHTTPServer((HOST, PORT), Handler)
    print(f"listening on {HOST}:{PORT}", flush=True)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nshutting down")


if __name__ == "__main__":
    main()
