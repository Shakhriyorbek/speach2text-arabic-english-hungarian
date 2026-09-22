"""
Does the GPU server actually work? — a dependency-free check.

Runs against a server started by start_whisper.sh, from anywhere: the pod
itself, the operator's Windows laptop before a khutbah, or a dev machine.

STDLIB ONLY — deliberately. No numpy, no faster-whisper, no project venv, not
even config.py. That is what lets the same file run inside the pod's container,
on a Fedora box whose python is too new for webrtcvad-wheels, and from the
mosque laptop's plain "py" before run.bat has ever been touched. Every
dependency added here is one more reason it will not run on the morning you
need it most.

Usage:
    python smoke_test.py --url https://<POD_ID>-8756.proxy.runpod.net
    python smoke_test.py --url http://127.0.0.1:8756 --wav khutbah.wav

The token comes from WHISPER_SERVER_TOKEN, or --token.

Exit status is 0 only if every check passed, so it can gate a deploy script.
"""

import argparse
import array
import json
import os
import sys
import time
import urllib.error
import urllib.request
import wave

# "O people, fear God" — a stock khutbah exhortation, short enough to eyeball.
SAMPLE_ARABIC = "أيها الناس اتقوا الله"

TARGET_RATE = 16000


# --- tiny helpers ----------------------------------------------------------

def _arabic_ratio(text):
    """Fraction of letters that are Arabic script. Used to detect X-Task loss."""
    letters = [c for c in text if c.isalpha()]
    if not letters:
        return 0.0
    arabic = sum(1 for c in letters if "؀" <= c <= "ۿ")
    return arabic / len(letters)


def load_wav_pcm16(path):
    """Read any WAV -> (int16 PCM bytes @16 kHz mono, duration_seconds).

    Mirrors subtitles/test_pipeline.py's loader, but with array instead of
    numpy. Note that audioop was removed in Python 3.13, so the resample is
    written out by hand rather than delegated to the stdlib.
    """
    with wave.open(path, "rb") as wf:
        channels = wf.getnchannels()
        width = wf.getsampwidth()
        rate = wf.getframerate()
        raw = wf.readframes(wf.getnframes())

    if width == 2:
        samples = array.array("h")
        samples.frombytes(raw)
        if sys.byteorder == "big":
            samples.byteswap()
        data = list(samples)
    elif width == 1:
        # 8-bit WAV is unsigned, centred at 128.
        data = [(b - 128) * 256 for b in raw]
    elif width == 4:
        samples = array.array("i")
        samples.frombytes(raw)
        if sys.byteorder == "big":
            samples.byteswap()
        data = [s >> 16 for s in samples]
    else:
        raise ValueError(f"Unsupported sample width: {width} bytes")

    if channels > 1:
        data = [sum(data[i:i + channels]) // channels
                for i in range(0, len(data) - channels + 1, channels)]

    if rate != TARGET_RATE and len(data) > 1:
        n_out = int(round(len(data) * TARGET_RATE / rate))
        step = (len(data) - 1) / max(n_out - 1, 1)
        out = []
        for i in range(n_out):
            pos = i * step
            lo = int(pos)
            hi = min(lo + 1, len(data) - 1)
            frac = pos - lo
            out.append(int(data[lo] + (data[hi] - data[lo]) * frac))
        data = out

    pcm = array.array("h", (max(-32768, min(32767, s)) for s in data))
    if sys.byteorder == "big":
        pcm.byteswap()
    return pcm.tobytes(), len(data) / TARGET_RATE


def synth_speechlike_pcm(seconds=3.0):
    """A buzzy tone, for when no WAV is to hand.

    This proves the transport only. Whisper's quality guards will almost
    certainly return "" for it, and an empty result tells you nothing about
    whether the headers survived — so --wav with real speech is the check that
    actually matters. See the note printed at the end.
    """
    import math

    n = int(TARGET_RATE * seconds)
    pcm = array.array("h")
    for i in range(n):
        t = i / TARGET_RATE
        env = 0.5 + 0.5 * math.sin(2 * math.pi * 3.0 * t)      # syllable-ish
        val = math.sin(2 * math.pi * 140.0 * t) * 0.4 * env
        val += math.sin(2 * math.pi * 430.0 * t) * 0.2 * env   # a formant
        pcm.append(int(max(-1.0, min(1.0, val)) * 20000))
    if sys.byteorder == "big":
        pcm.byteswap()
    return pcm.tobytes(), seconds


def request(url, token, path, data=None, headers=None, timeout=60):
    hdrs = {"Authorization": f"Bearer {token}"} if token else {}
    hdrs.update(headers or {})
    req = urllib.request.Request(
        f"{url}{path}",
        data=data,
        method="POST" if data is not None else "GET",
        headers=hdrs,
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


# --- the checks ------------------------------------------------------------

def check_health(url, token):
    print("[1/4] GET /health ...")
    try:
        info = request(url, token, "/health", timeout=30)
    except urllib.error.HTTPError as exc:
        print(f"      FAIL: HTTP {exc.code} {exc.reason}")
        if exc.code == 404:
            print("      A 404 here usually means the URL points somewhere that")
            print("      is not the whisper server at all — check the pod ID.")
        return None
    except Exception as exc:
        print(f"      FAIL: {type(exc).__name__}: {exc}")
        print("      The server is not reachable. Is the pod running, is 8756")
        print("      exposed as an HTTP port, and did start_whisper.sh survive?")
        return None

    print(f"      ok   model={info.get('model')} device={info.get('device')}")
    if info.get("device") != "cuda":
        print(f"      WARNING: device is {info.get('device')!r}, not 'cuda'. The")
        print("      server fell back to CPU and will be far too slow to keep up.")
    if info.get("translate"):
        print(f"      ok   translation enabled: {info.get('translate_model')}")
    else:
        print("      WARNING: translation is DISABLED on this server (no")
        print("      NLLB_MODEL_DIR). Hungarian will be produced by the laptop's")
        print("      600M model instead — the one that inverts meaning.")
    return info


def check_auth(url):
    print("[2/4] POST /transcribe with a bad token (should be refused) ...")
    try:
        request(url, "definitely-not-the-token", "/transcribe",
                data=b"\x00\x00", headers={"X-Mode": "part1"}, timeout=30)
    except urllib.error.HTTPError as exc:
        if exc.code == 401:
            print("      ok   rejected with 401")
            return True
        print(f"      FAIL: expected 401, got HTTP {exc.code}")
        return False
    except Exception as exc:
        print(f"      FAIL: {type(exc).__name__}: {exc}")
        return False
    print("      FAIL: a bad token was ACCEPTED. On a public proxy URL the")
    print("      token is the only thing standing between this GPU and the")
    print("      whole internet. Do not run the khutbah on this server.")
    return False


def check_transcribe(url, token, pcm, secs, mode, task, synthetic):
    print(f"[3/4] POST /transcribe  ({secs:.1f}s audio, mode={mode}, task={task}) ...")
    t0 = time.time()
    try:
        payload = request(
            url, token, "/transcribe", data=pcm,
            headers={
                "Content-Type": "application/octet-stream",
                "X-Mode": mode,
                "X-Task": task,
            },
            timeout=120,
        )
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")[:200]
        print(f"      FAIL: HTTP {exc.code} {exc.reason}  {body}")
        return False
    except Exception as exc:
        print(f"      FAIL: {type(exc).__name__}: {exc}")
        return False

    wall = time.time() - t0
    text = (payload.get("text") or "").strip()
    server_ms = payload.get("ms", 0)
    print(f"      ok   {server_ms} ms on the server, {wall * 1000:.0f} ms wall "
          f"({secs / max(wall, 0.001):.1f}x realtime end to end)")
    print(f"      text: {text[:120]!r}")
    if payload.get("dropped"):
        print(f"      note: {payload['dropped']} segment(s) dropped by the "
              f"quality guards — normal on hard audio.")

    if not text:
        if synthetic:
            print("      (empty is expected for the synthetic tone.)")
        else:
            print("      WARNING: empty result on real audio. Either the clip is")
            print("      too quiet, or the quality guards rejected all of it.")
        return True

    # The header check that matters. On the direct path the client sends
    # X-Task: transcribe and needs the SPOKEN language back. If a proxy strips
    # that header the server silently defaults to "translate"
    # (whisper_server.py:257) and returns English — which NLLB then accepts
    # without error and renders as fluent nonsense. Arabic script in the
    # response is the cheapest proof the header survived the trip.
    if task == "transcribe" and mode == "part1":
        ratio = _arabic_ratio(text)
        if ratio > 0.5:
            print(f"      ok   result is Arabic script — X-Task survived the proxy.")
        else:
            print("      FAIL: asked for task=transcribe on Arabic audio and got")
            print(f"      back text that is {ratio:.0%} Arabic. The X-Task header")
            print("      was probably stripped in transit, so the server ran")
            print("      task=translate and returned ENGLISH.")
            print("      Fix: expose 8756 as a TCP port instead of an HTTP port")
            print("      and point pod_url.txt at http://<ip>:<mapped-port>.")
            return False
    return True


def check_translate(url, token, info, text):
    print("[4/4] POST /translate ...")
    if info and not info.get("translate"):
        print("      skipped — this server has translation disabled.")
        return True
    t0 = time.time()
    try:
        payload = request(
            url, token, "/translate", data=text.encode("utf-8"),
            headers={"Content-Type": "text/plain; charset=utf-8",
                     "X-Src-Lang": "ar"},
            timeout=60,
        )
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")[:200]
        print(f"      FAIL: HTTP {exc.code} {exc.reason}  {body}")
        return False
    except Exception as exc:
        print(f"      FAIL: {type(exc).__name__}: {exc}")
        return False

    out = (payload.get("text") or "").strip()
    print(f"      ok   {payload.get('ms', 0)} ms, {time.time() - t0:.2f}s wall")
    print(f"      AR: {text}")
    print(f"      HU: {out!r}")
    if not out:
        print("      FAIL: empty translation.")
        return False
    if _arabic_ratio(out) > 0.2:
        print("      FAIL: the 'translation' is still Arabic — the source/target")
        print("      language tokens are probably wrong on the server.")
        return False
    return True


def main():
    ap = argparse.ArgumentParser(
        description="Check a whisper_server.py deployment end to end.")
    ap.add_argument("--url", required=True,
                    help="e.g. https://<POD_ID>-8756.proxy.runpod.net")
    ap.add_argument("--token", default=os.environ.get("WHISPER_SERVER_TOKEN", ""),
                    help="defaults to $WHISPER_SERVER_TOKEN")
    ap.add_argument("--wav", help="a real speech clip; strongly recommended")
    ap.add_argument("--mode", choices=("part1", "part2"), default="part1")
    ap.add_argument("--task", choices=("transcribe", "translate"),
                    default="transcribe",
                    help="transcribe = the direct path the app actually uses")
    ap.add_argument("--translate-text", default=SAMPLE_ARABIC)
    args = ap.parse_args()

    url = args.url.rstrip("/")
    token = args.token.strip()
    if not token:
        sys.exit("No token. Pass --token or set WHISPER_SERVER_TOKEN.")

    print(f"Target: {url}\n")

    if args.wav:
        pcm, secs = load_wav_pcm16(args.wav)
        synthetic = False
    else:
        pcm, secs = synth_speechlike_pcm()
        synthetic = True

    info = check_health(url, token)
    results = [info is not None]
    if info is not None:
        results.append(check_auth(url))
        results.append(check_transcribe(url, token, pcm, secs, args.mode,
                                        args.task, synthetic))
        results.append(check_translate(url, token, info, args.translate_text))

    print()
    if all(results):
        print("ALL CHECKS PASSED.")
        if synthetic:
            print("\nBut this ran on a synthetic tone, so the header check could")
            print("not run. Re-run with --wav on a real khutbah clip before")
            print("trusting this server in front of a congregation.")
        return 0
    print("SOMETHING FAILED — see above. Do not rely on this server yet.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
