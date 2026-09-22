#!/usr/bin/env bash
# ===========================================================================
#  Start the GPU transcription server.
#
#    bash start_whisper.sh <token>        # or set WHISPER_SERVER_TOKEN
#
#  Run bootstrap.sh first. This script only starts what that installed.
#
#  It checks everything BEFORE binding the port, and refuses to start on
#  anything it cannot serve properly. That is deliberate: a server that starts
#  and then 501s on /translate, or quietly runs Whisper on the CPU, produces a
#  screen full of bad subtitles rather than an error — and the operator is in a
#  mosque with a congregation waiting, not at a terminal reading logs.
# ===========================================================================
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WORKDIR="${WORKDIR:-$HERE}"

# Written by bootstrap.sh so overrides made at setup time survive to run time.
if [ -f "$WORKDIR/server.env" ]; then
    # shellcheck disable=SC1091
    set -a; . "$WORKDIR/server.env"; set +a
fi

WBENCH="${WBENCH:-$WORKDIR/wbench}"
export HF_HOME="${HF_HOME:-$WORKDIR/hf}"
export WHISPER_MODEL="${WHISPER_MODEL:-large-v3}"
export WHISPER_DEVICE="${WHISPER_DEVICE:-cuda}"
export WHISPER_COMPUTE_TYPE="${WHISPER_COMPUTE_TYPE:-float16}"
export WHISPER_SERVER_PORT="${WHISPER_SERVER_PORT:-8756}"

# Must stay 0.0.0.0: RunPod's proxy and TCP mapping both reach the container
# from outside, and neither can forward to the loopback interface.
export WHISPER_SERVER_HOST="${WHISPER_SERVER_HOST:-0.0.0.0}"

export NLLB_MODEL_DIR="${NLLB_MODEL_DIR:-}"
export NLLB_DEVICE="${NLLB_DEVICE:-cuda}"
export NLLB_COMPUTE_TYPE="${NLLB_COMPUTE_TYPE:-float16}"

# Token: argument beats environment, so a pasted one-liner works.
if [ "${1:-}" != "" ]; then
    export WHISPER_SERVER_TOKEN="$1"
fi
if [ "${WHISPER_SERVER_TOKEN:-}" = "" ]; then
    echo "No token." >&2
    echo >&2
    echo "  bash start_whisper.sh \$(openssl rand -hex 32)" >&2
    echo >&2
    echo "The laptop needs the same value in WHISPER_SERVER_TOKEN. On a public" >&2
    echo "proxy URL this token is the only thing between this GPU and anyone" >&2
    echo "who scans for open endpoints." >&2
    exit 1
fi

# --- preconditions ---------------------------------------------------------

if [ ! -x "$WBENCH/bin/python" ]; then
    echo "No runtime environment at $WBENCH — run bootstrap.sh first." >&2
    exit 1
fi
if [ ! -f "$WORKDIR/whisper_server.py" ]; then
    echo "whisper_server.py is not in $WORKDIR — run bootstrap.sh first." >&2
    exit 1
fi
if [ ! -f "$WORKDIR/names.py" ]; then
    # Not fatal, but it must be said out loud: mt_direct.py degrades silently to
    # a no-op substituter, and proper names start coming out as their literal
    # meaning with nothing in the logs to say why.
    echo "WARNING: names.py is missing — proper names will be mistranslated." >&2
fi

# ctranslate2 dlopen()s the CUDA 12 libraries instead of linking them, so they
# have to be found at runtime. Without this the server starts fine and then
# dies on the first utterance with "libcublas.so.12: cannot open shared object
# file" — i.e. exactly when the khutbah has begun.
CUDA_LIBS=""
for pkg in cublas cudnn; do
    d=$(echo "$WBENCH"/lib/python3*/site-packages/nvidia/$pkg/lib)
    [ -d "$d" ] && CUDA_LIBS="$CUDA_LIBS${CUDA_LIBS:+:}$d"
done
if [ -n "$CUDA_LIBS" ]; then
    export LD_LIBRARY_PATH="$CUDA_LIBS${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
else
    echo "WARNING: CUDA 12 libraries not found under $WBENCH." >&2
    echo "         Expect a libcublas failure on the first utterance." >&2
fi

if [ -n "$NLLB_MODEL_DIR" ] && [ ! -f "$NLLB_MODEL_DIR/model.bin" ]; then
    echo "NLLB_MODEL_DIR is set to '$NLLB_MODEL_DIR' but there is no model.bin" >&2
    echo "there. Re-run:  bash bootstrap.sh --build-nllb" >&2
    exit 1
fi
if [ -z "$NLLB_MODEL_DIR" ]; then
    echo "NOTE: translation is disabled on this server (no NLLB model)."
    echo "      The laptop will translate with its 600M model instead."
fi

# --- go --------------------------------------------------------------------

echo "workdir     : $WORKDIR"
echo "whisper     : $WHISPER_MODEL on $WHISPER_DEVICE ($WHISPER_COMPUTE_TYPE)"
echo "translation : ${NLLB_MODEL_DIR:-disabled}"
echo "listening   : $WHISPER_SERVER_HOST:$WHISPER_SERVER_PORT"
echo "token       : $WHISPER_SERVER_TOKEN"
echo
echo "Put this on the laptop, in pod_url.txt, once the pod's URL is known:"
echo "    https://<POD_ID>-${WHISPER_SERVER_PORT}.proxy.runpod.net"
echo

cd "$WORKDIR"
exec "$WBENCH/bin/python" "$WORKDIR/whisper_server.py"
