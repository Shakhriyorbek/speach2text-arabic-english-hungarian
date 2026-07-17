"""
One-time model setup — run by install.bat while internet is available.

Does three things:
  1. Warms the faster-whisper model cache (downloads config.MODEL_SIZE).
  2. Converts Helsinki-NLP/opus-mt-en-hu to a quantized CTranslate2 model in
     config.MT_MODEL_DIR, copying its SentencePiece tokenizers alongside.
  3. Runs a tiny self-test so a failed setup is obvious immediately.

After this runs successfully the app is fully offline: nothing here is needed
again unless you change MODEL_SIZE or delete the models.
"""

import os
import subprocess
import sys

import config
from subtitles.console import enable_utf8_console

enable_utf8_console()

MT_MODEL_NAME = "Helsinki-NLP/opus-mt-en-hu"


def warm_whisper_cache():
    print(f"[1/3] Downloading Whisper model '{config.MODEL_SIZE}' (this is the big one)...")
    from faster_whisper import WhisperModel

    # Constructing the model downloads + caches it. We don't need the handle.
    WhisperModel(
        config.MODEL_SIZE,
        device="cpu",
        compute_type=config.WHISPER_COMPUTE_TYPE,
    )
    print("      Whisper model ready.")


def convert_en_hu():
    out_dir = config.MT_MODEL_DIR
    if os.path.isdir(out_dir) and os.path.exists(os.path.join(out_dir, "model.bin")):
        print(f"[2/3] Translation model already present at '{out_dir}' — skipping.")
        return

    print(f"[2/3] Converting {MT_MODEL_NAME} -> CTranslate2 at '{out_dir}'...")
    os.makedirs(os.path.dirname(out_dir) or ".", exist_ok=True)

    # ct2-transformers-converter ships with the ctranslate2 pip package.
    # --copy_files places the SentencePiece tokenizers next to the model so the
    # runtime (mt.py) can load them without transformers installed.
    cmd = [
        sys.executable, "-m", "ctranslate2.converters.transformers",
        "--model", MT_MODEL_NAME,
        "--output_dir", out_dir,
        "--quantization", "int8",
        "--copy_files", "source.spm", "target.spm",
        "--force",
    ]
    try:
        subprocess.run(cmd, check=True)
    except (subprocess.CalledProcessError, FileNotFoundError):
        # Fall back to the console-script form if the module form is unavailable.
        print("      Retrying with the ct2-transformers-converter CLI...")
        cmd2 = [
            "ct2-transformers-converter",
            "--model", MT_MODEL_NAME,
            "--output_dir", out_dir,
            "--quantization", "int8",
            "--copy_files", "source.spm", "target.spm",
            "--force",
        ]
        subprocess.run(cmd2, check=True)
    print("      Translation model ready.")


def self_test():
    print("[3/3] Self-test: translating a sample phrase...")
    from subtitles.mt import Translator

    tr = Translator()
    for phrase in ("Praise be to God.", "Peace be upon him."):
        hu = tr.translate(phrase)
        print(f"      EN: {phrase!r}  ->  HU: {hu!r}")
    print("      Self-test done. If the Hungarian looks sane, setup succeeded.")


def main():
    warm_whisper_cache()
    convert_en_hu()
    self_test()
    print("\nAll models are ready. You can now run the app with run.bat.")


if __name__ == "__main__":
    main()
