"""
Remote speech recognition — sends each utterance to the GPU box instead of
transcribing it on the laptop.

Why: a weak laptop CPU caps Whisper at "small". On a Tesla T4 the same audio
runs through "large-v3" — measured ~30x realtime, and it kept meaning that the
local models lost. See server/whisper_server.py for the other end.

This class is a drop-in replacement for subtitles.asr.Transcriber: same ``.mode``
attribute, same ``.transcribe(audio) -> str``. app.py can therefore swap one for
the other without touching the pipeline.

Robustness matters more than speed here — a khutbah cannot pause for a network
hiccup. If the server is slow or unreachable, this transparently falls back to
the local model, and says so once on the console rather than failing silently.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request

import numpy as np

import config
from subtitles.asr import is_hallucination, normalize


class RemoteTranscriber:
    """Transcribe via the GPU server, falling back to a local model on trouble.

    Parameters
    ----------
    local_fallback :
        An object with the same ``.transcribe(audio)`` interface (normally
        ``subtitles.asr.Transcriber``), or None to disable falling back.
        It is only *used* after repeated remote failures, but it must already be
        constructed — loading a Whisper model mid-sermon would stall the audio.
    """

    def __init__(self, local_fallback=None):
        self.url = config.REMOTE_ASR_URL.rstrip("/")
        self.timeout = config.REMOTE_ASR_TIMEOUT

        # Token from the environment only — never committed to a project file.
        self.token = os.environ.get("WHISPER_SERVER_TOKEN", "").strip()
        if not self.token:
            raise RuntimeError(
                "Remote ASR needs a shared secret in the environment:\n"
                "    setx WHISPER_SERVER_TOKEN \"<same value as on the server>\"\n"
                "Then close and reopen the terminal. See the README."
            )

        self.mode = "part1"
        self._last_text = ""
        self._fallback = local_fallback
        self._consecutive_failures = 0
        self._using_fallback = False

        # On the direct path the server must return the SPOKEN language, not
        # English — handing Arabic-expecting NLLB an English sentence produces
        # fluent nonsense rather than an error.
        self._task = (
            "transcribe"
            if getattr(config, "TRANSLATION_PATH", "pivot").lower() == "direct"
            else "translate"
        )
        self.last_language = "ar"

    # -- helpers -----------------------------------------------------------

    def _post(self, audio: np.ndarray) -> str:
        """One HTTP round trip. Raises on any failure."""
        # float32 [-1,1] -> int16 PCM halves the bytes on the wire; 5s of
        # 16 kHz mono is ~160 kB, which is nothing even on mosque wifi.
        pcm = np.clip(audio, -1.0, 1.0)
        pcm = (pcm * 32767.0).astype("<i2").tobytes()

        req = urllib.request.Request(
            f"{self.url}/transcribe",
            data=pcm,
            method="POST",
            headers={
                "Authorization": f"Bearer {self.token}",
                "Content-Type": "application/octet-stream",
                "X-Mode": self.mode,
                "X-Task": self._task,
            },
        )
        with urllib.request.urlopen(req, timeout=self.timeout) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
        self.last_language = payload.get("language") or "ar"
        return self._filter((payload.get("text") or "").strip())

    def _filter(self, text: str) -> str:
        """Apply the same hallucination guards the local Transcriber applies.

        The server runs Whisper's own confidence guards (no_speech, compression
        ratio, logprob) but cannot catch a *confident* canned phrase: during a
        live khutbah large-v3 emitted "اشتركوا في القناة" on a pause, which
        scored as perfectly good speech and went to the projector. These guards
        lived only in Transcriber, so the remote path had none at all.
        """
        if not text:
            return ""
        if is_hallucination(text):
            return ""
        # An exact repeat of the previous line is a decoding loop, not speech.
        if normalize(text) and normalize(text) == normalize(self._last_text):
            return ""
        self._last_text = text
        return text

    def _note_failure(self, exc: Exception):
        self._consecutive_failures += 1
        if self._consecutive_failures == 1:
            print(f"[remote ASR] {type(exc).__name__}: {exc}", flush=True)

        limit = config.REMOTE_ASR_FAILURES_BEFORE_FALLBACK
        if (
            not self._using_fallback
            and self._fallback is not None
            and self._consecutive_failures >= limit
        ):
            self._using_fallback = True
            print(
                f"[remote ASR] {self._consecutive_failures} failures in a row — "
                f"switching to the local model for now.",
                flush=True,
            )

    # -- public API (mirrors subtitles.asr.Transcriber) ---------------------

    @property
    def is_using_fallback(self) -> bool:
        return self._using_fallback

    def transcribe(self, audio: np.ndarray) -> str:
        """Return English text for ``audio`` (float32 mono @16 kHz), or ""."""
        if self._using_fallback:
            # Periodically probe whether the server came back, without ever
            # delaying the current utterance: retry only every Nth chunk.
            self._consecutive_failures += 1
            if self._consecutive_failures % config.REMOTE_ASR_RETRY_EVERY == 0:
                try:
                    text = self._post(audio)
                    self._using_fallback = False
                    self._consecutive_failures = 0
                    print("[remote ASR] server is back — using the GPU again.", flush=True)
                    return text
                except (urllib.error.URLError, OSError, ValueError, json.JSONDecodeError):
                    pass
            return self._fallback.transcribe(audio) if self._fallback else ""

        try:
            text = self._post(audio)
        except (urllib.error.URLError, OSError, ValueError, json.JSONDecodeError) as exc:
            self._note_failure(exc)
            if self._fallback is not None:
                return self._fallback.transcribe(audio)
            return ""

        self._consecutive_failures = 0
        return text

    def health(self) -> dict | None:
        """Ask the server what it is running. Returns None if unreachable."""
        try:
            req = urllib.request.Request(f"{self.url}/health", method="GET")
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except Exception:
            return None
