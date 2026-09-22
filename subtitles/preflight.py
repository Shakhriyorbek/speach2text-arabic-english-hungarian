"""
Before the khutbah: will this actually run on the GPU?

The operator runs this (check_gpu.bat) a few minutes before starting. It answers
one question in plain language — is Friday going to run on the GPU, or has it
quietly degraded to the laptop?

That distinction is invisible during a sermon. app.py prints it once at startup
(see the "NOT responding" branches) and then the console is hidden behind a
fullscreen subtitle window for an hour. Both remote paths are designed to
degrade rather than fail, which is right for the day but means nothing goes
wrong loudly enough to notice. So the check has to happen beforehand, on
purpose.

    venv\\Scripts\\python -m subtitles.preflight

Exits non-zero if the GPU path is not fully working, so a script can gate on it.
"""

import array
import json
import os
import sys
import urllib.error
import urllib.request

import config
from subtitles.console import enable_utf8_console

enable_utf8_console()

OK = "  OK   "
WARN = "  WARN "
BAD = "  FAIL "


def _health(url, timeout):
    req = urllib.request.Request(f"{url}/health", method="GET")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _round_trip(url, token, timeout):
    """POST half a second of silence, to prove the TOKEN is right.

    /health is deliberately unauthenticated on the server, so a green health
    check says nothing at all about whether our token matches. A mismatched
    token is the single most likely day-of failure — it is copied by hand from
    the pod to the laptop — and it shows up as a 401 on every utterance, i.e. as
    a blank screen. The cheapest proof is to actually send something.
    """
    pcm = array.array("h", [0] * 8000)          # 0.5 s @ 16 kHz
    if sys.byteorder == "big":
        pcm.byteswap()
    req = urllib.request.Request(
        f"{url}/transcribe",
        data=pcm.tobytes(),
        method="POST",
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/octet-stream",
            "X-Mode": "part1",
            "X-Task": "transcribe",
        },
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def main():
    problems = []
    warnings = []

    backend = getattr(config, "BACKEND", "local").lower()
    asr_loc = getattr(config, "ASR_LOCATION", "cpu").lower()
    mt_loc = getattr(config, "MT_LOCATION", "cpu").lower()
    direct = getattr(config, "TRANSLATION_PATH", "pivot").lower() == "direct"

    print("Khutbah subtitles — pre-flight check")
    print("=" * 60)
    print(f"  backend          : {backend}")
    print(f"  transcription    : {asr_loc}")
    print(f"  translation      : {mt_loc} ({'direct AR->HU' if direct else 'via English'})")
    print(f"  server URL       : {config.REMOTE_ASR_URL}")
    print("=" * 60)

    if backend == "azure":
        print("\nBACKEND is 'azure' — this check is for the GPU server and does")
        print("not apply. Nothing to verify here.")
        return 0

    if asr_loc != "remote" and mt_loc != "remote":
        print("\nFully offline: nothing remote is configured, so there is no GPU")
        print("to check. Arabic will be transcribed by this laptop at "
              f"MODEL_SIZE_PART1 = {getattr(config, 'MODEL_SIZE_PART1', '?')!r}.")
        return 0

    if "YOUR-POD-ID" in config.REMOTE_ASR_URL:
        print(f"\n{BAD}The server URL is still the placeholder.")
        print("       Put the pod's URL on one line in pod_url.txt, next to")
        print("       run.bat, then run this again. It looks like:")
        print("           https://abc123xyz-8756.proxy.runpod.net")
        return 1

    token = os.environ.get("WHISPER_SERVER_TOKEN", "").strip()
    if not token:
        print(f"\n{BAD}WHISPER_SERVER_TOKEN is not set in this environment.")
        print("       On the laptop:  setx WHISPER_SERVER_TOKEN \"<the token>\"")
        print("       then close and reopen the terminal.")
        return 1
    print(f"\n{OK}token is set ({len(token)} characters)")

    timeout = getattr(config, "REMOTE_ASR_TIMEOUT", 10.0)

    # --- is it there at all? ---
    try:
        info = _health(config.REMOTE_ASR_URL, timeout)
    except urllib.error.HTTPError as exc:
        print(f"{BAD}server answered HTTP {exc.code} {exc.reason}")
        print("       That is not our server. Check the pod ID in pod_url.txt.")
        return 1
    except Exception as exc:
        print(f"{BAD}cannot reach the server: {type(exc).__name__}: {exc}")
        print("       Is the pod running? Is start_whisper.sh still going? Is")
        print("       8756 exposed as an HTTP port?")
        print("\n       If you cannot fix it: the subtitles WILL still work,")
        print("       on this laptop's own models, at lower quality. Nothing")
        print("       needs changing in config.py for that to happen.")
        return 1

    print(f"{OK}server is up: {info.get('model')} on {info.get('device')} "
          f"({info.get('compute_type', '?')})")

    gpu = info.get("gpu")
    if gpu:
        print(f"{OK}card: {gpu}, {info.get('vram_gb', '?')} GB")
    beam = info.get("beam") or {}
    if beam:
        print(f"{OK}beam: {beam.get('final')} final / {beam.get('partial')} partial")

    # A pod that stops itself in the middle of the khutbah is a far worse
    # surprise than one that stops afterwards, so say how long is left while
    # there is still time to do something about it.
    deadline = info.get("deadline")
    if deadline:
        print(f"{OK}the GPU stops itself at {deadline}")

    # Does what is loaded actually fit the card? float16 large-v3 is ~3.1 GB and
    # NLLB-1.3B ~2.7 GB (3.3B ~7.6 GB), plus context and activations. Running
    # out of VRAM does not happen at startup — it happens on an utterance.
    vram = info.get("vram_gb")
    if vram and info.get("compute_type") == "float16":
        need = 12 if "3.3b" in str(info.get("translate_model", "")).lower() else 8
        if vram < need:
            warnings.append(
                f"this card has {vram} GB, and what is loaded wants about "
                f"{need} GB at float16. It may run out of memory mid-khutbah. "
                f"Restart the server with WHISPER_COMPUTE_TYPE=int8_float16 "
                f"and NLLB_COMPUTE_TYPE=int8_float16 to halve that")

    if info.get("device") != "cuda":
        warnings.append(
            f"the server is running on {info.get('device')!r}, not a GPU — it "
            f"will not keep up with live speech")
    if info.get("model") not in ("large-v3", "large-v2"):
        warnings.append(
            f"the server is running {info.get('model')!r}; the whole point of "
            f"the GPU is large-v3")

    # --- does our token work? ---
    try:
        _round_trip(config.REMOTE_ASR_URL, token, timeout)
        print(f"{OK}the token is accepted")
    except urllib.error.HTTPError as exc:
        if exc.code == 401:
            print(f"{BAD}the server REJECTED our token (401).")
            print("       The laptop's WHISPER_SERVER_TOKEN does not match the")
            print("       one start_whisper.sh printed on the pod. Every")
            print("       utterance would be refused and the screen stays blank.")
            return 1
        print(f"{BAD}round trip failed: HTTP {exc.code} {exc.reason}")
        return 1
    except Exception as exc:
        print(f"{BAD}round trip failed: {type(exc).__name__}: {exc}")
        problems.append("the server answers /health but not /transcribe")

    # --- will translation run there too? ---
    if direct and mt_loc == "remote":
        if info.get("translate"):
            print(f"{OK}translation on the GPU: {info.get('translate_model')} "
                  f"({info.get('translate_compute_type', '?')}, "
                  f"beam {info.get('translate_beam', '?')})")
        else:
            warnings.append(
                "the server has translation DISABLED, so Hungarian will come "
                "from this laptop's 600M model — the one that inverts meaning. "
                "Restart the server with bootstrap.sh --build-nllb to fix it")

    # --- verdict ---
    print()
    for w in warnings:
        print(f"{WARN}{w}")
    for p in problems:
        print(f"{BAD}{p}")

    print()
    if problems:
        print("NOT READY. See above.")
        return 1
    if warnings:
        print("USABLE, BUT DEGRADED. The subtitles will appear; the quality is")
        print("not what the GPU path is supposed to give. Safe to proceed.")
        return 0
    print("READY. Friday will run on the GPU. Start run.bat and press F1.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
