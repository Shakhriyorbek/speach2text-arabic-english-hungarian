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

# Search width. Four of every five requests are snapshots of speech still in
# progress, overwritten a second later; only the final reaches the projector.
# Spend the GPU on that one. Lower BEAM_FINAL if the GPU is small and finals
# start arriving late.
export WHISPER_BEAM_FINAL="${WHISPER_BEAM_FINAL:-5}"
export WHISPER_BEAM_PARTIAL="${WHISPER_BEAM_PARTIAL:-1}"
export NLLB_BEAM_SIZE="${NLLB_BEAM_SIZE:-4}"

# The server reads $WORKDIR/deadline to report the automatic shutdown time.
export WORKDIR

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

# --- billing dead-man's switch --------------------------------------------

# A GPU bills whether or not anyone is speaking, and the usual way a khutbah
# ends is that somebody shuts the laptop. Nothing on this box would then ever
# stop it: ~$0.69/hour is about $500 a month, ten times the whole budget.
#
# So the pod kills itself after a fixed wall-clock deadline. Three properties
# matter, and all three are easy to get wrong:
#
#   * TERMINATE, not stop. A stopped pod keeps billing for its disks. The
#     models are on the network volume and survive either way.
#   * DETACHED. setsid puts the guard in its own session so it outlives Ctrl-C,
#     this script, the exec below, and the container's main process exiting.
#     A guard that dies with the server is worthless in exactly the case it
#     exists for.
#   * WALL-CLOCK, not idle. An idle timer can only fire while the server is
#     alive, and any threshold long enough to survive the gap between the two
#     parts of a khutbah would also be long enough to be useless. A fixed
#     deadline cannot kill us mid-sermon and cannot fail to fire.
DEADLINE_HOURS="${DEADLINE_HOURS:-6}"

if [ "$DEADLINE_HOURS" = "0" ]; then
    echo "WARNING: DEADLINE_HOURS=0 — this pod will bill until somebody stops" >&2
    echo "         it by hand. Nothing here will do it for you." >&2
elif [ -z "${RUNPOD_POD_ID:-}" ] || ! command -v runpodctl >/dev/null 2>&1; then
    # Not fatal. Refusing to serve a congregation over a billing guard is the
    # wrong trade — but this has to be said loudly, not logged quietly.
    echo "WARNING: cannot arm the automatic shutdown on this box." >&2
    if [ -z "${RUNPOD_POD_ID:-}" ]; then
        echo "         RUNPOD_POD_ID is not set (not a RunPod pod?)." >&2
    else
        echo "         runpodctl is not installed." >&2
    fi
    echo "         THIS MACHINE WILL BILL UNTIL YOU TERMINATE IT YOURSELF." >&2
else
    _deadline_secs=$(awk "BEGIN{printf \"%d\", $DEADLINE_HOURS * 3600}")
    _deadline_at=$(date -u -d "+${_deadline_secs} seconds" '+%Y-%m-%d %H:%M UTC' \
                   2>/dev/null || echo "in ${DEADLINE_HOURS}h")
    # The marker in the command line is what `pkill -f` below matches on.
    setsid nohup sh -c \
        "sleep ${_deadline_secs}; \
         echo khutbah-deadman: terminating \$RUNPOD_POD_ID; \
         runpodctl pod delete \"\$RUNPOD_POD_ID\"" \
        >"$WORKDIR/deadman.log" 2>&1 < /dev/null &
    echo "$_deadline_at" > "$WORKDIR/deadline" 2>/dev/null || true
    DEADMAN_AT="$_deadline_at"
fi

# --- go --------------------------------------------------------------------

echo "workdir     : $WORKDIR"
echo "whisper     : $WHISPER_MODEL on $WHISPER_DEVICE ($WHISPER_COMPUTE_TYPE)"
echo "beam        : $WHISPER_BEAM_FINAL final / $WHISPER_BEAM_PARTIAL partial"
echo "translation : ${NLLB_MODEL_DIR:-disabled}${NLLB_MODEL_DIR:+ (beam $NLLB_BEAM_SIZE)}"
echo "listening   : $WHISPER_SERVER_HOST:$WHISPER_SERVER_PORT"
echo "token       : $WHISPER_SERVER_TOKEN"
if [ -n "${DEADMAN_AT:-}" ]; then
    echo "auto-stop   : $DEADMAN_AT  (terminates this pod, whatever else happens)"
    echo "              to cancel it:  pkill -f khutbah-deadman"
fi
echo
echo "Put this on the laptop, in pod_url.txt, once the pod's URL is known:"
echo "    https://<POD_ID>-${WHISPER_SERVER_PORT}.proxy.runpod.net"
echo

cd "$WORKDIR"
exec "$WBENCH/bin/python" "$WORKDIR/whisper_server.py"
