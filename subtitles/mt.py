"""
English -> Hungarian machine translation, fully offline.

Uses a CTranslate2-converted Marian model (Helsinki-NLP/opus-mt-en-hu) plus
its SentencePiece tokenizers. The installer (download_models.py) produces the
model directory at config.MT_MODEL_DIR.

A small phrase cache is kept because liturgical speech repeats the same
formulas ("praise be to God", "peace be upon him", ...) constantly — caching
those makes the common case instant and reduces CPU load.

The public surface is deliberately tiny — a Translator with .translate(str)
returning str — so that if the CT2 conversion ever has to be swapped for the
argostranslate fallback, only this file changes.
"""

from __future__ import annotations  # keep type hints valid on Python 3.9 too

import os

try:
    import ctranslate2
    import sentencepiece as spm
except ImportError as exc:  # pragma: no cover
    raise ImportError(
        "ctranslate2 / sentencepiece not installed. "
        "Install with:  pip install ctranslate2 sentencepiece"
    ) from exc

import config


# Tokens Marian may emit that should never reach the screen.
_JUNK_TOKENS = ("</s>", "<pad>", "<unk>")


class Translator:
    """Translate English text to Hungarian using a local CTranslate2 model."""

    def __init__(self, model_dir: str | None = None):
        d = model_dir or config.MT_MODEL_DIR
        if not os.path.isdir(d):
            raise FileNotFoundError(
                f"Translation model not found at '{d}'. "
                "Run install.bat (which builds it) before starting."
            )

        self.tr = ctranslate2.Translator(d, device="cpu", compute_type="int8")

        src = os.path.join(d, "source.spm")
        tgt = os.path.join(d, "target.spm")
        self.sp_src = spm.SentencePieceProcessor(model_file=src)
        self.sp_tgt = spm.SentencePieceProcessor(model_file=tgt)

        self._cache: dict[str, str] = {}
        self._beam = config.MT_BEAM_SIZE

    def translate(self, text: str) -> str:
        text = text.strip()
        if not text:
            return ""
        if text in self._cache:
            return self._cache[text]

        # CRITICAL: Marian/opus-mt models were trained with the source ending
        # in the end-of-sequence token. HuggingFace's tokenizer adds it
        # automatically; raw SentencePiece does not. Without it the model never
        # detects the input's end and degenerates into an endless repetition
        # loop ("Istennek Istennek Istennek..."). Appending "</s>" fixes it.
        tokens = self.sp_src.encode(text, out_type=str) + ["</s>"]
        results = self.tr.translate_batch(
            [tokens],
            beam_size=self._beam,
            max_decoding_length=256,   # safety net against runaway generation
        )
        hyp = results[0].hypotheses[0]

        # Strip any special tokens Marian left in the hypothesis.
        hyp = [t for t in hyp if t not in _JUNK_TOKENS]
        out = self.sp_tgt.decode(hyp).strip()

        # Bound cache size; liturgy repeats, but a long sermon still varies.
        if len(self._cache) > 500:
            self._cache.clear()
        self._cache[text] = out
        return out
