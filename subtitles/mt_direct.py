"""
Direct translation into Hungarian with NLLB-200 — no English in the middle.

Why this exists: the default pipeline goes Arabic -> English -> Hungarian,
because Whisper's ``task="translate"`` can ONLY emit English. Every hop loses
something, and the English hop lost the most important thing we measured: the
sentence meaning "Satan has despaired of being worshipped" came out of the
English stage phrased as "should be worshipped", which opus-mt then turned into
Hungarian "must be worshipped" — the opposite, and blasphemous on a projector.

NLLB-200 translates Arabic straight to Hungarian, so that class of inversion
cannot happen. Measured on the dev laptop CPU: ~1.0s per line (opus-mt is
~0.1s), which is absorbable given the pipeline already waits seconds for a
pause. Quality is a trade rather than a clean win — NLLB tends to drop
qualifiers (it lost "forbidden" from one test line) — but it does not invert.

Runtime deps are the same as mt.py: ctranslate2 plus ``tokenizers``, which is
already installed as a faster-whisper dependency. transformers stays a
setup-only tool.
"""

from __future__ import annotations

import os
import re

try:
    import ctranslate2
    from tokenizers import Tokenizer
except ImportError as exc:  # pragma: no cover
    raise ImportError(
        "ctranslate2 / tokenizers not installed. "
        "Install with:  pip install ctranslate2 tokenizers"
    ) from exc

try:
    import config
except ImportError:                     # running on the GPU server, which has
    config = None                       # no project config.py — see _cfg().

try:
    from names import Substituter as _Substituter          # deployed flat
except ImportError:
    try:
        from subtitles.names import Substituter as _Substituter
    except ImportError:                 # names.py not deployed: translate
        class _Substituter:             # without the fix rather than crash
            def apply(self, t):
                return t

            def reset(self):
                pass


# Tokens NLLB may emit that must never reach the screen.
_JUNK = ("</s>", "<pad>", "<unk>")

# Defaults used when config.py is absent. This module is deployed to the GPU box
# alongside whisper_server.py so that the fiddly part of NLLB — source-language
# token first, </s> last, target token as decoder prefix — exists in exactly one
# place. Getting that wrong does not raise; it returns fluent nonsense.
_DEFAULTS = {
    "NLLB_MODEL_DIR": "models/nllb-600m-ct2",
    "NLLB_TARGET_LANG": "hun_Latn",
    "NLLB_BEAM_SIZE": 2,
    "NLLB_LANG_MAP": {"ar": "arb_Arab", "en": "eng_Latn"},
}


def _cfg(name):
    return getattr(config, name, _DEFAULTS[name]) if config else _DEFAULTS[name]


class DirectTranslator:
    """Translate text in ``src_lang`` straight to Hungarian.

    Interface mirrors subtitles.mt.Translator — ``.translate(text) -> str`` — so
    app.py can swap one for the other. The one addition is ``.src_lang``, a
    plain attribute holding a Whisper language code ("ar", "en"). It is set from
    the UI/ASR thread and read here, exactly like Transcriber.mode; a stale read
    for a single utterance is harmless.
    """

    def __init__(self, model_dir: str | None = None, device: str = "cpu",
                 compute_type: str = "int8"):
        d = model_dir or _cfg("NLLB_MODEL_DIR")
        if not os.path.isdir(d):
            raise FileNotFoundError(
                f"NLLB model not found at '{d}'. Run install.bat (which builds "
                f"it) or set TRANSLATION_PATH = \"pivot\" in config.py."
            )

        tok_path = os.path.join(d, "tokenizer.json")
        if not os.path.exists(tok_path):
            raise FileNotFoundError(
                f"'{tok_path}' is missing — the model was converted without "
                f"--copy_files tokenizer.json. Re-run the conversion."
            )

        self.tr = ctranslate2.Translator(d, device=device, compute_type=compute_type)
        self.tok = Tokenizer.from_file(tok_path)
        self.tgt = _cfg("NLLB_TARGET_LANG")
        self._beam = _cfg("NLLB_BEAM_SIZE")
        self._cache: dict[tuple[str, str], str] = {}

        # Fail loudly at startup rather than producing fluent nonsense later:
        # an unknown language code is silently tokenised as ordinary text.
        if self.tok.token_to_id(self.tgt) is None:
            raise ValueError(
                f"'{self.tgt}' is not an NLLB language token. Codes look like "
                f"'hun_Latn', 'arb_Arab', 'eng_Latn'."
            )

        self.src_lang = "ar"       # Whisper code; mapped via config.NLLB_LANG_MAP
        self._names = _Substituter()

    def _nllb_src(self) -> str:
        lang_map = _cfg("NLLB_LANG_MAP")
        code = lang_map.get(self.src_lang)
        if code is None or self.tok.token_to_id(code) is None:
            # Unknown/unmapped language -> fall back to Arabic rather than
            # feeding a bogus token, which would yield confident nonsense.
            code = lang_map.get("ar", "arb_Arab")
        return code

    def translate(self, text: str) -> str:
        text = text.strip()
        if not text:
            return ""

        # Swap known proper names for their Hungarian forms before the model
        # sees them; NLLB copies a Latin-script run through verbatim but would
        # otherwise translate the name's literal meaning ("Abu Lu'lu'a" ->
        # "the father of the pearl"). See names.py.
        if self.src_lang == "ar":
            text = self._names.apply(text)

        src = self._nllb_src()
        key = (src, text)
        if key in self._cache:
            return self._cache[key]

        # NLLB expects the SOURCE language token first and </s> last; the TARGET
        # language token is supplied as the decoder prefix. Getting this wrong
        # does not raise — it just produces confident nonsense — so it is
        # verified against real output rather than assumed.
        enc = self.tok.encode(text, add_special_tokens=False)
        source = [src] + enc.tokens + ["</s>"]

        # NLLB-600M is a SENTENCE-level model. Handed a long unpunctuated run of
        # speech it degenerates into a repetition loop: measured on 90s of
        # khutbah audio it emitted "a Had-d-t, a Had-d-t, ..." for 27.5s. The
        # VAD's MAX_UTTERANCE_S normally keeps input far below that, but a dense
        # 5s utterance must never be able to freeze the subtitles, so the loop is
        # blocked here rather than assumed away upstream.
        results = self.tr.translate_batch(
            [source],
            target_prefix=[[self.tgt]],
            beam_size=self._beam,
            no_repeat_ngram_size=3,
            repetition_penalty=1.1,
            # Output should track input length; a translation several times
            # longer than its source is degeneration, not translation.
            max_decoding_length=min(256, max(32, 3 * len(enc.tokens))),
        )
        hyp = results[0].hypotheses[0]

        # Drop the target-language prefix token and any specials.
        out = [t for t in hyp if t not in _JUNK and t != self.tgt]
        ids = [self.tok.token_to_id(t) for t in out]
        result = self.tok.decode([i for i in ids if i is not None]).strip()

        # NLLB's training data is heavily subtitle corpora, so it sometimes
        # opens a line with a speaker dash ("- Köszönöm."). Harmless in meaning
        # but it reads as a rendering glitch on a projector.
        result = re.sub(r"^[-–—]\s*", "", result)

        # Liturgy repeats; bound the cache anyway for a long sermon.
        if len(self._cache) > 500:
            self._cache.clear()
        self._cache[key] = result
        return result
