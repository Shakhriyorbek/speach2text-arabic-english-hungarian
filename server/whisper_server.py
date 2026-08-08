"""
GPU transcription server — runs ON the Azure T4 VM, not on the mosque laptop.

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
    body: raw little-endian int16 PCM, 16 kHz, mono
    -> 200 {"text": "...", "ms": 123, "dropped": 0}

GET /health
    -> 200 {"ok": true, "model": "large-v3", "device": "cuda"}

Run it:
    export WHISPER_SERVER_TOKEN="<a long random string>"
    ~/wbench/bin/python whisper_server.py
"""

import base64
import json
import os
import sys
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
        )
        print(f"translator ready in {time.time() - t0:.1f}s", flush=True)
    return _translator


def transcribe_pcm(pcm: bytes, mode: str, task: str = "translate", prompt: str = ""):
    """int16 PCM -> (text, n_dropped_segments, detected_language).

    task="translate" gives ENGLISH (Whisper can emit no other target language).
    task="transcribe" gives the SPOKEN language — needed by the direct
    Arabic->Hungarian path, which must not be handed English by mistake.
    """
    audio = np.frombuffer(pcm, dtype=np.int16).astype(np.float32) / 32768.0

    # Part 1 only: an Arabic prompt would skew Part 2's language auto-detect.
    hint = (prompt or DEFAULT_INITIAL_PROMPT_AR) if mode == "part1" else ""

    segments, info = get_model().transcribe(
        audio,
        task=task,
        language="ar" if mode == "part1" else None,
        initial_prompt=hint or None,
        beam_size=1,
        temperature=0.0,
        condition_on_previous_text=False,      # stops repetition loops
        repetition_penalty=REPETITION_PENALTY,
        no_repeat_ngram_size=NO_REPEAT_NGRAM,
        without_timestamps=True,
        vad_filter=False,                      # the laptop's VAD already ran
    )

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
            self._json(200, {
                "ok": True,
                "model": MODEL_SIZE,
                "device": DEVICE,
                # The client uses this to decide whether it may send text here
                # at all, rather than discovering it via a 404 mid-sermon.
                "translate": bool(NLLB_MODEL_DIR),
                "translate_model": os.path.basename(NLLB_MODEL_DIR) or None,
            })
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
            tr.src_lang = src
            out = tr.translate(text)
        except Exception as exc:                    # never let one line kill it
            print(f"[translate error] {type(exc).__name__}: {exc}", flush=True)
            self._json(500, {"error": f"{type(exc).__name__}: {exc}"})
            return

        ms = int((time.time() - t0) * 1000)
        print(f"  translate[{src}] {ms}ms  {text[:40]} -> {out[:40]}", flush=True)
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
            text, dropped, lang = transcribe_pcm(pcm, mode, task, prompt)
        except Exception as exc:                    # never let one chunk kill it
            print(f"[error] {type(exc).__name__}: {exc}", flush=True)
            self._json(500, {"error": f"{type(exc).__name__}: {exc}"})
            return

        ms = int((time.time() - t0) * 1000)
        secs = len(pcm) / 2 / 16000
        print(f"  {secs:.1f}s audio -> {ms}ms ({secs / (ms / 1000 or 1):.1f}x) "
              f"[{mode}/{task}/{lang}] {text[:80]}", flush=True)
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
