"""
Speech recognition wrapper around faster-whisper.

The core trick of this whole project lives here: we call Whisper with
``task="translate"``, which makes it output ENGLISH text regardless of the
spoken language. So Arabic speech comes out as English, and English speech
passes through unchanged. Downstream we only ever need one English->Hungarian
translator.

Two modes (set by the UI via ``.mode``):
  * "part1"  -> language forced to Arabic  (khutbah part 1, all Arabic)
  * "part2"  -> language auto-detected     (English talk with Arabic quotes)
"""

import os
import re

import numpy as np

try:
    from faster_whisper import WhisperModel
except ImportError as exc:  # pragma: no cover
    raise ImportError(
        "faster-whisper is not installed. Install with:  pip install faster-whisper"
    ) from exc

import config


# Classic Whisper "silence hallucinations" — short canned phrases it emits when
# fed near-silence. We drop these outright. Matched case-insensitively, after
# stripping punctuation/whitespace.
#
# These originally covered English only, which was correct while every path ran
# task="translate". On the direct path Whisper emits ARABIC, so none of the
# English entries can ever match and the canned phrases reach the projector: a
# live khutbah test put "اشتركوا في القناة" ("subscribe to the channel") on
# screen during a pause. large-v3 is trained on YouTube audio and falls back to
# channel boilerplate on silence, so the Arabic equivalents are listed too.
#
# Nothing here may be a phrase a khatib would actually say. "الحمد لله" is
# deliberately absent — it is both a stock hallucination AND the opening of the
# sermon, and dropping real praise is worse than passing an occasional stray.
_HALLUCINATION_BLOCKLIST = {
    # English (task="translate" / Part 2)
    "thank you",
    "thanks for watching",
    "thank you for watching",
    "please subscribe",
    "you",
    "bye",
    "bye bye",
    ".",
    "",
    # Arabic (task="transcribe" / direct path)
    "اشتركوا في القناة",
    "اشتركوا في القناة ولا تنسوا تفعيل الجرس",
    "لا تنسوا الاشتراك في القناة",
    "لا تنسوا الاشتراك",
    "شكرا",
    "شكرا لكم",
    "شكرا لمشاهدتكم",
    "مشاهدة ممتعة",
    "ترجمة نانسي قنقر",
    "الى اللقاء",
}


def normalize(text: str) -> str:
    """Strip punctuation/case so canned phrases match however they are punctuated."""
    return re.sub(r"[^\w\s]", "", text, flags=re.UNICODE).strip().lower()


_normalize = normalize      # existing internal callers


def is_hallucination(text: str) -> bool:
    """True when `text` is a known canned phrase rather than real speech.

    Shared with the remote path so both transcribers filter identically —
    previously this lived only in Transcriber, so switching ASR_LOCATION to
    "remote" silently disabled hallucination filtering altogether.
    """
    return _normalize(text) in _HALLUCINATION_BLOCKLIST


class Transcriber:
    """Transcribe (and translate-to-English) one audio utterance at a time.

    Uses a possibly-different Whisper model per khutbah part, because Arabic
    (Part 1) needs a bigger model than English (Part 2) for the same quality:
      * Part 1 -> config.MODEL_SIZE_PART1  (Arabic, accuracy priority)
      * Part 2 -> config.MODEL_SIZE_PART2  (English, speed priority)
    Both distinct sizes are loaded at startup so switching F1/F2 never stalls
    mid-service. If the two are equal, only one model is loaded.
    """

    def __init__(self):
        self._models = {}  # size -> WhisperModel (shared cache; dedups equal sizes)
        for size in {config.MODEL_SIZE_PART1, config.MODEL_SIZE_PART2}:
            self._models[size] = WhisperModel(
                size,
                device="cpu",
                compute_type=config.WHISPER_COMPUTE_TYPE,
                cpu_threads=config.CPU_THREADS or os.cpu_count(),
            )
        # "part1" | "part2". A plain attribute is fine — it is only ever set
        # from the UI thread and read from the ASR thread; a stale read for one
        # utterance is harmless.
        self.mode = "part1"
        self._last_text = ""

        # Language of the text last returned, as a Whisper code ("ar"/"en").
        # Only meaningful on the direct path, where the translator needs to know
        # what it is being handed. Written and read by the ASR thread alone.
        self.last_language = "ar"

    def _model_for_mode(self):
        size = config.MODEL_SIZE_PART1 if self.mode == "part1" else config.MODEL_SIZE_PART2
        return self._models[size]

    def transcribe(self, audio: np.ndarray) -> str:
        """Return text for ``audio`` (float32 mono @16 kHz), or "".

        On the pivot path the text is ENGLISH (Whisper's translate task only
        ever emits English). On the direct path it is the SPOKEN language —
        Arabic for Part 1 — and ``self.last_language`` says which, so the
        translator knows what it has been handed.
        """
        direct = getattr(config, "TRANSLATION_PATH", "pivot").lower() == "direct"
        lang = "ar" if self.mode == "part1" else None
        model = self._model_for_mode()

        segments, info = model.transcribe(
            audio,
            task="transcribe" if direct else "translate",
            language=lang,
            beam_size=1,
            temperature=0.0,
            condition_on_previous_text=False,   # CRITICAL: stops repetition loops
            # Anti-hallucination guards — matter most for Arabic, where a model
            # out of its depth degenerates into "word word word..." loops that
            # are both wrong AND slow (long garbage decodes). These constrain
            # decoding cheaply, without extra passes:
            repetition_penalty=config.REPETITION_PENALTY,
            no_repeat_ngram_size=config.NO_REPEAT_NGRAM,
            without_timestamps=True,
            vad_filter=False,                   # our own VAD already ran
        )

        parts = []
        for seg in segments:
            # Drop segments the model itself signals are junk:
            if seg.no_speech_prob is not None and seg.no_speech_prob > config.NO_SPEECH_MAX:
                continue  # mostly silence / noise
            if seg.compression_ratio is not None and seg.compression_ratio > config.COMPRESSION_RATIO_MAX:
                continue  # too repetitive -> hallucination loop
            if seg.avg_logprob is not None and seg.avg_logprob < config.LOGPROB_MIN:
                continue  # model very unsure -> likely garbage
            piece = seg.text.strip()
            if piece:
                parts.append(piece)

        text = " ".join(parts).strip()
        if not text:
            return ""

        # Record what language this text is in. Part 1 pins Arabic; Part 2
        # auto-detects, and info.language carries Whisper's verdict.
        self.last_language = lang or getattr(info, "language", None) or "ar"

        # Hallucination guards.
        norm = _normalize(text)
        if norm in _HALLUCINATION_BLOCKLIST:
            return ""
        # Exact repeat of the previous emitted line -> almost always a loop.
        if norm and norm == _normalize(self._last_text):
            return ""

        self._last_text = text
        return text
