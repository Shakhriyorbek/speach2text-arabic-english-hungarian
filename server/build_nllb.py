"""
Convert an NLLB-200 checkpoint to CTranslate2, on the GPU box.

Why this is separate from subtitles/download_models.py: that script builds the
600M model for the LAPTOP, imports config.py, and assumes the project layout.
The server has none of those things — mt_direct.py already copes with config.py
being absent (see its import guard) and this follows the same rule. Everything
is an argument; nothing is read from project settings.

The model this exists to build is nllb-200-distilled-1.3B. The 600M that runs on
the laptop was measured inverting meaning on flawless input — "we seek His
forgiveness" became "we forgive Him" — which is the whole reason translation
moved to the GPU. Building the 600M here would defeat the point, so the default
is 1.3B and you have to ask for anything else.

Usage:
    python build_nllb.py --out /workspace/models/nllb-1.3b-ct2
    python build_nllb.py --model facebook/nllb-200-distilled-600M --out ... 

Needs transformers + torch (see requirements-server-build.txt). Those are setup
tools only; the server itself never imports them.
"""

import argparse
import os
import subprocess
import sys

DEFAULT_MODEL = "facebook/nllb-200-distilled-1.3B"

# mt_direct.py loads tokenizer.json at startup and refuses to run without it
# (it raises rather than guessing, because a missing tokenizer does not fail
# loudly at translate time — it fails as fluent nonsense). The other two are
# carried for reference and for any tooling that expects the HF layout.
COPY_FILES = ["tokenizer.json", "sentencepiece.bpe.model", "special_tokens_map.json"]


def already_built(out_dir):
    return os.path.isdir(out_dir) and os.path.exists(os.path.join(out_dir, "model.bin"))


def convert(model, out_dir, quantization):
    os.makedirs(os.path.dirname(out_dir.rstrip("/")) or ".", exist_ok=True)
    args = [
        "--model", model,
        "--output_dir", out_dir,
        "--quantization", quantization,
        "--copy_files", *COPY_FILES,
        "--force",
    ]
    try:
        subprocess.run(
            [sys.executable, "-m", "ctranslate2.converters.transformers", *args],
            check=True,
        )
    except (subprocess.CalledProcessError, FileNotFoundError):
        # Same two-form fallback as subtitles/download_models.py: some installs
        # ship only the console script, some only the module.
        print("      retrying with the ct2-transformers-converter CLI...")
        subprocess.run(["ct2-transformers-converter", *args], check=True)


def verify(out_dir, quantization):
    """Load it the way mt_direct.py will, and translate one line.

    A conversion that produced files but a broken tokenizer looks identical on
    disk to a good one. NLLB's failure mode is not an exception, it is confident
    nonsense, so the only honest check is to run a sentence through it.
    """
    missing = [f for f in ("model.bin", "tokenizer.json")
               if not os.path.exists(os.path.join(out_dir, f))]
    if missing:
        sys.exit(f"Conversion finished but {missing} are missing from {out_dir}.")

    try:
        import ctranslate2
        from tokenizers import Tokenizer
    except ImportError:
        print("      (ctranslate2/tokenizers not importable here — skipping the "
              "load check; start_whisper.sh will catch a bad model.)")
        return

    # float16 needs a GPU; fall back to CPU so the check still runs on a CPU pod.
    device = "cuda" if quantization == "float16" else "cpu"
    try:
        tr = ctranslate2.Translator(out_dir, device=device, compute_type=quantization)
    except Exception as exc:
        print(f"      (could not load on {device}: {exc} — trying cpu/int8)")
        tr = ctranslate2.Translator(out_dir, device="cpu", compute_type="int8")

    tok = Tokenizer.from_file(os.path.join(out_dir, "tokenizer.json"))
    for code in ("arb_Arab", "hun_Latn", "eng_Latn"):
        if tok.token_to_id(code) is None:
            sys.exit(f"'{code}' is not in this tokenizer — wrong model converted?")

    text = "أيها الناس اتقوا الله"
    enc = tok.encode(text, add_special_tokens=False)
    res = tr.translate_batch([["arb_Arab"] + enc.tokens + ["</s>"]],
                             target_prefix=[["hun_Latn"]], beam_size=2)
    out = [t for t in res[0].hypotheses[0]
           if t not in ("</s>", "<pad>", "<unk>", "hun_Latn")]
    ids = [tok.token_to_id(t) for t in out]
    print(f"      AR: {text}")
    print(f"      HU: {tok.decode([i for i in ids if i is not None]).strip()!r}")
    print("      If that Hungarian is sane, the model is good.")


def main():
    ap = argparse.ArgumentParser(description="Build an NLLB CTranslate2 model.")
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument("--out", required=True, help="output directory")
    ap.add_argument("--quantization", default="float16",
                    choices=("float16", "int8", "int8_float16", "float32"),
                    help="float16 for a GPU (default), int8 for CPU")
    ap.add_argument("--force", action="store_true",
                    help="rebuild even if the model is already there")
    args = ap.parse_args()

    if already_built(args.out) and not args.force:
        print(f"      {args.out} already built — skipping. (--force to redo.)")
        verify(args.out, args.quantization)
        return

    print(f"      converting {args.model} -> {args.out} ({args.quantization})")
    print(f"      the 1.3B is a ~5.5 GB download; be patient.")
    convert(args.model, args.out, args.quantization)
    verify(args.out, args.quantization)


if __name__ == "__main__":
    main()
