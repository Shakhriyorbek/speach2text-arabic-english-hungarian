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
_HALLUCINATION_BLOCKLIST = {
    "thank you",
    "thanks for watching",
    "thank you for watching",
    "please subscribe",
    "you",
    "bye",
    "bye bye",
    ".",
    "",
}


def _normalize(text: str) -> str:
    return re.sub(r"[^\w\s]", "", text, flags=re.UNICODE).strip().lower()


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

    def _model_for_mode(self):
        size = config.MODEL_SIZE_PART1 if self.mode == "part1" else config.MODEL_SIZE_PART2
        return self._models[size]

    def transcribe(self, audio: np.ndarray) -> str:
        """Return English text for ``audio`` (float32 mono @16 kHz), or ""."""
        lang = "ar" if self.mode == "part1" else None
        model = self._model_for_mode()

        segments, _info = model.transcribe(
            audio,
            task="translate",
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

        # Hallucination guards.
        norm = _normalize(text)
        if norm in _HALLUCINATION_BLOCKLIST:
            return ""
        # Exact repeat of the previous emitted line -> almost always a loop.
        if norm and norm == _normalize(self._last_text):
            return ""

        self._last_text = text
        return text
