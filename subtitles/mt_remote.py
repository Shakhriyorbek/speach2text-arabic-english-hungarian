"""
Translate on the GPU box instead of this laptop.

Why: once transcription moved to the T4, translation became the accuracy
bottleneck. NLLB-600M on the laptop CPU — the largest that fits the latency
budget there — inverted meaning on flawless input during a live khutbah test:
"we seek His forgiveness" became "we forgive Him", "we seek refuge in God from
the evil of our souls" became "God is freed from our evil", and the name
Abu Lu'lu'a al-Majusi became "the father makes magical pearl". Those are not
audio problems; a bigger model is the only fix, and a bigger model needs a GPU.

Interface mirrors subtitles.mt_direct.DirectTranslator (``.translate(text)`` plus
a ``.src_lang`` attribute) so app.py can swap one for the other.

Degradation, not failure: if the server is unreachable this falls back to the
local translator and keeps producing subtitles. A dropped SSH tunnel mid-sermon
should cost accuracy, never a blank screen.
"""

from __future__ import annotations

import http.client
import json
import os
import urllib.error
import urllib.request

import config
from subtitles.http_client import KeepAliveClient


class RemoteTranslator:
    """POST text to the GPU server; fall back to `local_fallback` on failure."""

    def __init__(self, local_fallback=None):
        self.url = config.REMOTE_MT_URL.rstrip("/")
        self.timeout = config.REMOTE_MT_TIMEOUT
        self._http = KeepAliveClient(self.url)
        self._fallback = local_fallback
        self._consecutive_failures = 0
        self._using_fallback = False
        self.src_lang = "ar"

        self.token = os.environ.get("WHISPER_SERVER_TOKEN", "").strip()
        if not self.token:
            raise RuntimeError(
                "Remote translation needs a shared secret in the environment:\n"
                '    setx WHISPER_SERVER_TOKEN "<same value as on the server>"\n'
                "then open a new terminal."
            )

    # -- internals ----------------------------------------------------------

    def _post(self, text: str) -> str:
        raw = self._http.post(
            "/translate",
            text.encode("utf-8"),
            {
                "Authorization": f"Bearer {self.token}",
                "Content-Type": "text/plain; charset=utf-8",
                "X-Src-Lang": self.src_lang,
            },
            self.timeout,
        )
        payload = json.loads(raw.decode("utf-8"))
        return (payload.get("text") or "").strip()

    def _fallback_translate(self, text: str) -> str:
        if self._fallback is None:
            return ""
        # Keep the fallback pointed at the same source language.
        self._fallback.src_lang = self.src_lang
        return self._fallback.translate(text)

    def _note_failure(self, exc: Exception):
        self._consecutive_failures += 1
        if self._consecutive_failures == 1:
            print(f"[remote MT] {type(exc).__name__}: {exc}", flush=True)

        limit = config.REMOTE_MT_FAILURES_BEFORE_FALLBACK
        if (
            not self._using_fallback
            and self._fallback is not None
            and self._consecutive_failures >= limit
        ):
            self._using_fallback = True
            print(
                f"[remote MT] {self._consecutive_failures} failures in a row — "
                f"translating on this laptop for now (lower quality).",
                flush=True,
            )

    # -- public API ---------------------------------------------------------

    @property
    def is_using_fallback(self) -> bool:
        return self._using_fallback

    def translate(self, text: str) -> str:
        text = (text or "").strip()
        if not text:
            return ""

        if self._using_fallback:
            # Re-probe occasionally, without delaying the current utterance.
            self._consecutive_failures += 1
            if self._consecutive_failures % config.REMOTE_MT_RETRY_EVERY == 0:
                try:
                    out = self._post(text)
                    self._using_fallback = False
                    self._consecutive_failures = 0
                    print("[remote MT] server is back — using the GPU again.",
                          flush=True)
                    return out
                except (urllib.error.URLError, http.client.HTTPException,
                        OSError, ValueError, json.JSONDecodeError):
                    pass
            return self._fallback_translate(text)

        try:
            out = self._post(text)
        except (urllib.error.URLError, http.client.HTTPException,
                OSError, ValueError, json.JSONDecodeError) as exc:
            self._note_failure(exc)
            return self._fallback_translate(text)

        self._consecutive_failures = 0
        return out

    def health(self) -> dict | None:
        try:
            # The User-Agent is not decoration: Cloudflare fronts the pod
            # proxy and answers 403 to Python's default. Without it this
            # returns None, which app.py reads as "the server is not there".
            req = urllib.request.Request(
                f"{self.url}/health", method="GET",
                headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except Exception:
            return None
