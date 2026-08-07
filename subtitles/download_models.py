"""
One-time model setup — run by install.bat while internet is available.

Does four things:
  1. Warms the faster-whisper model cache (downloads the Part 1 + Part 2 sizes).
  2. Converts Helsinki-NLP/opus-mt-en-hu to a quantized CTranslate2 model in
     config.MT_MODEL_DIR, copying its SentencePiece tokenizers alongside.
  3. On the direct path, converts NLLB-200 for Arabic -> Hungarian with no
     English in between (see config.TRANSLATION_PATH).
  4. Runs a tiny self-test so a failed setup is obvious immediately.

After this runs successfully the app is fully offline: nothing here is needed
again unless you change a MODEL_SIZE_PART*, switch TRANSLATION_PATH, or delete
the models.
"""

import os
import subprocess
import sys

import config
from subtitles.console import enable_utf8_console

enable_utf8_console()

MT_MODEL_NAME = "Helsinki-NLP/opus-mt-en-hu"
NLLB_MODEL_NAME = "facebook/nllb-200-distilled-600M"


def _convert(model_name, out_dir, copy_files):
    """Run the CTranslate2 converter, with the CLI form as a fallback."""
    os.makedirs(os.path.dirname(out_dir) or ".", exist_ok=True)
    args = [
        "--model", model_name,
        "--output_dir", out_dir,
        "--quantization", "int8",
        "--copy_files", *copy_files,
        "--force",
    ]
    try:
        subprocess.run(
            [sys.executable, "-m", "ctranslate2.converters.transformers", *args],
            check=True,
        )
    except (subprocess.CalledProcessError, FileNotFoundError):
        # Fall back to the console-script form if the module form is unavailable.
        print("      Retrying with the ct2-transformers-converter CLI...")
        subprocess.run(["ct2-transformers-converter", *args], check=True)


def _already_built(out_dir):
    return os.path.isdir(out_dir) and os.path.exists(os.path.join(out_dir, "model.bin"))


def using_direct_path():
    return getattr(config, "TRANSLATION_PATH", "pivot").lower() == "direct"


def warm_whisper_cache():
    from faster_whisper import WhisperModel

    # Download every distinct model size the two parts use (Part 1 + Part 2).
    sizes = {config.MODEL_SIZE_PART1, config.MODEL_SIZE_PART2}
    print(f"[1/4] Downloading Whisper model(s) {sorted(sizes)} (this is the big one)...")
    for size in sizes:
        # Constructing the model downloads + caches it. We don't need the handle.
        WhisperModel(size, device="cpu", compute_type=config.WHISPER_COMPUTE_TYPE)
    print("      Whisper model(s) ready.")


def convert_en_hu():
    """English -> Hungarian (opus-mt). Always built: it is tiny (~77 MB) and is
    the fallback if the direct model is missing."""
    out_dir = config.MT_MODEL_DIR
    if _already_built(out_dir):
        print(f"[2/4] English->Hungarian model already at '{out_dir}' — skipping.")
        return

    print(f"[2/4] Converting {MT_MODEL_NAME} -> CTranslate2 at '{out_dir}'...")
    # --copy_files places the SentencePiece tokenizers next to the model so the
    # runtime (mt.py) can load them without transformers installed.
    _convert(MT_MODEL_NAME, out_dir, ["source.spm", "target.spm"])
    print("      English->Hungarian model ready.")


def convert_nllb():
    """Arabic -> Hungarian directly (NLLB-200), for TRANSLATION_PATH="direct".

    Skipped on the pivot path because it is a ~2.4 GB download for a ~600 MB
    model that would go unused.
    """
    out_dir = getattr(config, "NLLB_MODEL_DIR", "models/nllb-600m-ct2")

    if not using_direct_path():
        print(f"[3/4] TRANSLATION_PATH is 'pivot' — skipping NLLB "
              f"(set it to 'direct' and re-run to build it).")
        return
    if _already_built(out_dir):
        print(f"[3/4] Direct Arabic->Hungarian model already at '{out_dir}' — skipping.")
        return

    print(f"[3/4] Converting {NLLB_MODEL_NAME} -> CTranslate2 at '{out_dir}'...")
    print("      (~2.4 GB download, ~600 MB result — be patient)")
    # tokenizer.json is what mt_direct.py loads at runtime; without it the
    # direct path cannot start. sentencepiece.bpe.model is copied for reference.
    _convert(NLLB_MODEL_NAME, out_dir,
             ["tokenizer.json", "sentencepiece.bpe.model", "special_tokens_map.json"])
    print("      Direct Arabic->Hungarian model ready.")


def self_test():
    print("[4/4] Self-test: translating a sample phrase...")

    from subtitles.mt import Translator

    tr = Translator()
    for phrase in ("Praise be to God.", "Peace be upon him."):
        print(f"      EN: {phrase!r}  ->  HU: {tr.translate(phrase)!r}")

    if using_direct_path():
        from subtitles.mt_direct import DirectTranslator

        dt = DirectTranslator()
        dt.src_lang = "ar"
        # "O people, fear God" — a stock khutbah exhortation.
        arabic = "أيها الناس اتقوا الله"
        print(f"      AR -> HU: {dt.translate(arabic)!r}")

    print("      Self-test done. If the Hungarian looks sane, setup succeeded.")


def main():
    warm_whisper_cache()
    convert_en_hu()
    convert_nllb()
    self_test()
    print("\nAll models are ready. You can now run the app with run.bat.")


if __name__ == "__main__":
    main()
