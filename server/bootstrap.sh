#!/usr/bin/env bash
# ===========================================================================
#  Set up the GPU transcription server on a rented box.
#
#  Provider-neutral: anything with Ubuntu, an NVIDIA driver and python3 works
#  — RunPod, Vast.ai, Lambda, a borrowed workstation. The previous version of
#  this was a list of commands in a README tied to one Azure VM, which is why
#  losing that VM cost us a working setup.
#
#  Run it straight from the repo:
#    curl -fsSL https://raw.githubusercontent.com/Shakhriyorbek/\
# speach2text-arabic-english-hungarian/main/server/bootstrap.sh | bash -s -- --build-nllb
#
#  Or from a checkout:  bash server/bootstrap.sh --build-nllb
#
#  IDEMPOTENT ON PURPOSE. Running it against a box that already has everything
#  must be a fast no-op, because that is exactly what happens on the morning of
#  a khutbah when a fresh pod is attached to an already-built volume.
# ===========================================================================
set -euo pipefail

REPO="${REPO:-Shakhriyorbek/speach2text-arabic-english-hungarian}"
BRANCH="${BRANCH:-main}"
RAW="https://raw.githubusercontent.com/${REPO}/${BRANCH}"

# Everything lives under WORKDIR. On RunPod that is the network-volume mount,
# which is the ONLY directory that survives terminating the pod.
WORKDIR="${WORKDIR:-/workspace}"
WBENCH="${WBENCH:-$WORKDIR/wbench}"
MODELS_DIR="${MODELS_DIR:-$WORKDIR/models}"

# The single most important line in this file. faster-whisper caches models
# under HF_HOME; left at its default (~/.cache/huggingface) the 3 GB large-v3
# download lands in the container layer and is destroyed with the pod, so a
# "pre-baked" volume would silently re-download everything on the day.
export HF_HOME="${HF_HOME:-$WORKDIR/hf}"

WHISPER_MODEL="${WHISPER_MODEL:-large-v3}"
NLLB_MODEL="${NLLB_MODEL:-facebook/nllb-200-distilled-1.3B}"
NLLB_DIR="${NLLB_DIR:-$MODELS_DIR/nllb-1.3b-ct2}"

BUILD_NLLB=0
for arg in "$@"; do
    case "$arg" in
        --build-nllb) BUILD_NLLB=1 ;;
        --no-nllb)    BUILD_NLLB=0 ;;
        -h|--help)
            # Print the header comment block, however long it grows.
            awk 'NR>1 && /^#/ {sub(/^# ?/, ""); print; next} NR>1 {exit}' "$0"
            exit 0 ;;
        *) echo "unknown option: $arg" >&2; exit 2 ;;
    esac
done

say() { printf '\n=== %s ===\n' "$*"; }

# --- 0. sanity -------------------------------------------------------------

say "Checking the GPU"
if ! command -v nvidia-smi >/dev/null 2>&1; then
    echo "nvidia-smi not found. This box has no usable NVIDIA driver."
    echo "The server will still run on CPU, but far too slowly for live use."
    echo "On a rented GPU box this usually means you picked a CPU-only instance."
    sleep 3
elif ! nvidia-smi >/dev/null 2>&1; then
    echo "nvidia-smi is present but failing. After a host kernel upgrade the"
    echo "driver's kernel module often needs rebuilding for the running kernel."
    echo "On a rented pod the quick fix is to destroy it and start another."
    exit 1
else
    nvidia-smi --query-gpu=name,memory.total,driver_version \
               --format=csv,noheader || true
fi

mkdir -p "$WORKDIR" "$MODELS_DIR" "$HF_HOME"

# --- 1. project files, flat ------------------------------------------------

# mt_direct.py does "from names import Substituter" and only falls back to the
# package path. If names.py is absent it does NOT fail — it installs a no-op
# substituter and proper names start being translated literally again
# ("Abu Lu'lu'a" -> "the father of the pearl"). So names.py is not optional
# here, it just fails quietly when you forget it.
say "Fetching project files into $WORKDIR"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" 2>/dev/null && pwd || echo '')"

# Are we inside a git checkout, or piped in from curl? Test for the repo's
# actual shape rather than for "a path exists": when this is re-run from
# $WORKDIR on a later day, HERE is $WORKDIR, and a looser test would happily
# treat the flat deployment as a checkout and copy files onto themselves.
FROM_CHECKOUT=0
if [ -n "$HERE" ] && [ -f "$HERE/whisper_server.py" ] && [ -d "$HERE/../subtitles" ]; then
    FROM_CHECKOUT=1
fi

fetch() {   # fetch <repo-path> <dest>
    local src="$1" dest="$2"
    # Never rewrite the script that is currently executing. bash reads a script
    # incrementally as it runs, so overwriting it mid-flight makes it jump to a
    # random offset of the new file. This happens on the second and every later
    # run, where $WORKDIR/bootstrap.sh IS this process.
    if [ -e "$dest" ] && [ "$dest" -ef "${BASH_SOURCE[0]}" ]; then
        echo "  $(basename "$dest") (already running — left alone)"
        return
    fi
    if [ "$FROM_CHECKOUT" = "1" ]; then
        cp "$HERE/../$src" "$dest"
    elif ! curl -fsSL "$RAW/$src" -o "$dest.new"; then
        rm -f "$dest.new"
        # A prepared volume already has every file. Refusing to start because
        # GitHub is having a bad morning would be the wrong trade on a Friday:
        # keep what is there, say so, and carry on.
        if [ -f "$dest" ]; then
            echo "  $(basename "$dest") (download failed — keeping the existing copy)"
            return
        fi
        echo "Could not download $src and there is no local copy." >&2
        exit 1
    else
        mv "$dest.new" "$dest"
    fi
    echo "  $(basename "$dest")"
}
fetch server/bootstrap.sh                 "$WORKDIR/bootstrap.sh"
fetch server/whisper_server.py            "$WORKDIR/whisper_server.py"
fetch subtitles/mt_direct.py              "$WORKDIR/mt_direct.py"
fetch subtitles/names.py                  "$WORKDIR/names.py"
fetch server/build_nllb.py                "$WORKDIR/build_nllb.py"
fetch server/smoke_test.py                "$WORKDIR/smoke_test.py"
fetch server/start_whisper.sh             "$WORKDIR/start_whisper.sh"
fetch server/requirements-server.txt      "$WORKDIR/requirements-server.txt"
fetch server/requirements-server-build.txt "$WORKDIR/requirements-server-build.txt"
chmod +x "$WORKDIR/start_whisper.sh" "$WORKDIR/bootstrap.sh"

# --- 2. runtime venv -------------------------------------------------------

say "Runtime environment at $WBENCH"
if [ ! -x "$WBENCH/bin/python" ]; then
    python3 -m venv "$WBENCH"
    "$WBENCH/bin/python" -m pip install --quiet --upgrade pip
fi
# Lean by design: faster-whisper + ctranslate2 + the CUDA 12 libs, no torch.
"$WBENCH/bin/pip" install --quiet -r "$WORKDIR/requirements-server.txt"
"$WBENCH/bin/python" - <<'PY'
import faster_whisper, ctranslate2
print(f"  faster-whisper {faster_whisper.__version__}, "
      f"ctranslate2 {ctranslate2.__version__}")
PY

# --- 3. Whisper weights ----------------------------------------------------

say "Whisper $WHISPER_MODEL (cache: $HF_HOME)"
HF_HOME="$HF_HOME" "$WBENCH/bin/python" - "$WHISPER_MODEL" <<'PY'
import sys, time
from faster_whisper import WhisperModel
size = sys.argv[1]
t0 = time.time()
# Constructing it downloads and caches it. device="cpu" so this step works on a
# CPU-only box too; the server loads the same cached files onto the GPU later.
WhisperModel(size, device="cpu", compute_type="int8")
print(f"  cached in {time.time() - t0:.0f}s")
PY

# --- 4. NLLB, converted once -----------------------------------------------

if [ "$BUILD_NLLB" = "1" ]; then
    say "Direct Arabic->Hungarian model ($NLLB_MODEL)"
    if [ -f "$NLLB_DIR/model.bin" ]; then
        echo "  already built at $NLLB_DIR — skipping."
    else
        # The conversion needs torch + transformers, which together are larger
        # than everything the server runs. Install them into the SYSTEM python,
        # not $WBENCH: the container layer is discarded when the pod is
        # terminated, while the converted model stays on the volume. That is
        # the whole trick — pay the disk cost once, in a place that evaporates.
        if ! python3 -c "import torch" >/dev/null 2>&1; then
            echo "  no system torch (not a PyTorch image) — installing CPU torch"
            python3 -m pip install --quiet torch \
                --index-url https://download.pytorch.org/whl/cpu
        fi
        python3 -m pip install --quiet -r "$WORKDIR/requirements-server-build.txt"
        HF_HOME="$HF_HOME" python3 "$WORKDIR/build_nllb.py" \
            --model "$NLLB_MODEL" --out "$NLLB_DIR" --quantization float16
    fi
else
    echo
    echo "Skipping NLLB (no --build-nllb). Translation will fall back to the"
    echo "laptop's 600M model — the one measured inverting meaning."
fi

# --- 5. record what we chose ----------------------------------------------

# start_whisper.sh sources this, so the two cannot drift apart when someone
# overrides WORKDIR or MODELS_DIR here and forgets to do it there.
cat > "$WORKDIR/server.env" <<ENV
WORKDIR=$WORKDIR
WBENCH=$WBENCH
HF_HOME=$HF_HOME
WHISPER_MODEL=$WHISPER_MODEL
NLLB_MODEL_DIR=$([ -f "$NLLB_DIR/model.bin" ] && echo "$NLLB_DIR" || echo "")
ENV

say "Done"
echo "Start the server with:"
echo
echo "    bash $WORKDIR/start_whisper.sh \$(openssl rand -hex 32)"
echo
echo "It prints the token it is using — the laptop needs the same value in"
echo "WHISPER_SERVER_TOKEN."
