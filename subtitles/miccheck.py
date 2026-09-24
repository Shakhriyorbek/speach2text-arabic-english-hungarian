"""
Is the microphone actually reaching this computer?

Run before anything else when the screen stays blank. The subtitle app can only
report "no speech", which is the same thing it says for a muted mic, a wrong
device number, an XLR cable that is not passing signal, and a condenser
microphone with no phantom power. This tells them apart.

    venv\\Scripts\\python -m subtitles.miccheck              list the inputs
    venv\\Scripts\\python -m subtitles.miccheck --device 3   watch input 3
    venv\\Scripts\\python -m subtitles.miccheck --seconds 20

With no --device it tests config.MIC_DEVICE, i.e. exactly what the real app
would open.
"""

from __future__ import annotations

import argparse
import math
import sys
import time

import numpy as np

import config
from subtitles.console import enable_utf8_console

enable_utf8_console()

try:
    import sounddevice as sd
except Exception as exc:                        # noqa: BLE001
    sys.exit(f"sounddevice is not installed ({exc}). Run install.bat first.")


# Anything quieter than this over a whole test is not a quiet room, it is no
# connection. A silent room still floors around -60 dBFS of self-noise; a dead
# input reads as digital zero.
SILENT_DBFS = -55.0
LOUD_DBFS = -2.0            # at this point it is clipping and words are lost


def dbfs(block: np.ndarray) -> float:
    peak = float(np.max(np.abs(block))) if block.size else 0.0
    if peak <= 0:
        return -math.inf
    return 20.0 * math.log10(peak)


# Windows exposes the SAME physical microphone once per audio subsystem, so a
# single USB interface shows up four times. They are not equivalent:
#
#   MME          oldest, highest latency, works everywhere
#   DirectSound  fine
#   WASAPI       modern, lowest latency — the one to prefer
#   WDM-KS       kernel streaming. PortAudio cannot do a BLOCKING read on it,
#                which is what this program does, so it fails at open with
#                "Blocking API not supported yet [PaErrorCode -9999]".
#
# Picking the WDM-KS copy is an easy mistake — it is often last in the list and
# the name looks identical to the others.
UNUSABLE_APIS = ("wdm-ks", "windows wdm-ks")
PREFERRED_APIS = ("wasapi", "directsound", "mme")


def host_api_of(dev_index):
    try:
        return sd.query_hostapis()[sd.query_devices(dev_index)["hostapi"]]["name"]
    except Exception:
        return ""


def is_unusable(api_name):
    a = (api_name or "").lower()
    return any(bad in a for bad in UNUSABLE_APIS)


def suggest_alternatives(device):
    """Same microphone, on an audio subsystem that actually works."""
    try:
        want = sd.query_devices(device)["name"].split("(")[-1].strip(" )")
    except Exception:
        return []
    out = []
    for i, d in enumerate(sd.query_devices()):
        if i == device or d["max_input_channels"] < 1:
            continue
        api = host_api_of(i)
        if is_unusable(api):
            continue
        if want and want.lower()[:12] in d["name"].lower():
            rank = next((n for n, p in enumerate(PREFERRED_APIS)
                         if p in api.lower()), len(PREFERRED_APIS))
            out.append((rank, i, d["name"], api))
    return [(i, n, a) for _, i, n, a in sorted(out)]


def list_devices():
    print("Input devices on this computer")
    print("=" * 72)
    try:
        apis = sd.query_hostapis()
    except Exception:
        apis = []
    for i, d in enumerate(sd.query_devices()):
        if d["max_input_channels"] < 1:
            continue
        api = ""
        try:
            api = apis[d["hostapi"]]["name"]
        except Exception:
            pass
        mark = " <- config.MIC_DEVICE" if i == config.MIC_DEVICE else ""
        if is_unusable(api):
            mark += "  (UNUSABLE: kernel streaming)"
        print(f"  [{i:2}] {d['name'][:44]:44} {d['max_input_channels']}ch "
              f"{int(d['default_samplerate'])}Hz  {api[:12]}{mark}")
    print("=" * 72)
    print("A USB audio interface usually appears under a GENERIC name such as")
    print('"USB Audio CODEC" or "Line (2- USB Audio CODEC)" — not its brand.')
    print()
    print("The SAME microphone appears once per Windows audio system. Prefer a")
    print("WASAPI one; anything marked UNUSABLE cannot be recorded from by this")
    print("program, whatever its name says.")
    print()
    print("Put the number in config.py as MIC_DEVICE, then run:")
    print("    venv\\Scripts\\python -m subtitles.miccheck")


def test(device, seconds):
    try:
        info = sd.query_devices(device, "input")
    except Exception as exc:                    # noqa: BLE001
        print(f"FAIL: device {device!r} is not a usable input ({exc}).")
        print("      Run this with no arguments to list what is available.")
        return 1

    api = host_api_of(device)
    print(f"Testing [{device}] {info['name']}   ({api})")
    print(f"  channels {info['max_input_channels']}, "
          f"device default {int(info['default_samplerate'])} Hz")

    if is_unusable(api):
        print()
        print(f"  FAIL this is the {api} copy of that microphone, and this")
        print( "       program cannot record from it — kernel streaming does not")
        print( "       support the kind of read it does. The microphone is fine;")
        print( "       the entry is the wrong one.")
        alts = suggest_alternatives(device)
        if alts:
            print()
            print("       Use one of these instead — same microphone:")
            for i, name, a in alts:
                print(f"         MIC_DEVICE = {i:<3}  {name[:40]:40} ({a})")
            print()
            print(f"       Put it in config_local.py, then run this again.")
        return 1

    # The app asks for 16 kHz mono because Whisper and the VAD both require it.
    # A USB interface often runs natively at 44.1/48 kHz, and whether Windows
    # resamples for us depends on the driver — so check rather than assume.
    try:
        sd.check_input_settings(device=device, channels=1,
                                samplerate=config.SAMPLE_RATE, dtype="int16")
        print(f"  OK   {config.SAMPLE_RATE} Hz mono is accepted")
    except Exception as exc:                    # noqa: BLE001
        print(f"  FAIL this device will not give us {config.SAMPLE_RATE} Hz "
              f"mono ({exc})")
        print(f"       In Windows Sound settings, set this input's format to")
        print(f"       16000 Hz (or 48000 Hz) mono/stereo and try again.")
        return 1

    print()
    print(f"  Speak normally for {seconds} seconds. Bars should move.")
    print()

    peaks = []
    block = int(config.SAMPLE_RATE * 0.25)
    try:
        with sd.InputStream(samplerate=config.SAMPLE_RATE, channels=1,
                            dtype="int16", device=device) as stream:
            end = time.time() + seconds
            while time.time() < end:
                data, overflowed = stream.read(block)
                level = dbfs(data.astype(np.float32) / 32768.0)
                peaks.append(level)
                if level == -math.inf:
                    bar, shown = "", "  silence (digital zero)"
                else:
                    filled = max(0, min(40, int((level + 60) / 60 * 40)))
                    bar = "#" * filled
                    shown = f"{level:6.1f} dBFS"
                print(f"  |{bar:<40}| {shown}" + ("  OVERFLOW" if overflowed else ""),
                      flush=True)
    except KeyboardInterrupt:
        print("\n  stopped")
    except Exception as exc:                    # noqa: BLE001
        print(f"\nFAIL: could not record ({exc})")
        return 1

    finite = [p for p in peaks if p != -math.inf]
    loudest = max(finite) if finite else -math.inf

    print()
    print("=" * 72)
    if not finite or loudest < SILENT_DBFS:
        print("NOTHING IS ARRIVING. The computer sees this input, but it is")
        print("carrying no sound at all. In the order worth checking:")
        print()
        print("  1. PHANTOM POWER. On a Behringer UM2 and similar interfaces")
        print("     there is a +48V switch. A CONDENSER microphone produces")
        print("     absolutely nothing without it — this is the single most")
        print("     common cause. A dynamic mic (SM58 and the like) does not")
        print("     need it and is unharmed if it is on.")
        print("  2. GAIN. Turn the gain knob for the XLR channel up to about")
        print("     halfway and speak close to the microphone.")
        print("  3. The microphone's own on/off switch.")
        print("  4. The XLR cable — swap it. Cables fail more than anything.")
        print("  5. Windows Settings -> Privacy & security -> Microphone:")
        print("     'Let desktop apps access your microphone' must be ON.")
        print("  6. Windows Sound -> Recording -> this device -> Properties:")
        print("     check it is Enabled and its level is not 0.")
        return 1

    if loudest > LOUD_DBFS:
        print(f"TOO LOUD — peaked at {loudest:.1f} dBFS and is clipping.")
        print("Turn the GAIN knob down until speech peaks around -12 dBFS.")
        print("Clipped audio transcribes badly; this matters.")
        return 1

    quiet = loudest < -30
    print(f"WORKING — loudest was {loudest:.1f} dBFS.")
    if quiet:
        print()
        print("It is on the quiet side. Speech should peak around -12 dBFS.")
        print("Turn the GAIN up a little, or speak closer to the microphone.")
        print("Too quiet and the voice detector will miss the start of words.")
    print()
    print(f"Set MIC_DEVICE = {device} in config.py if it is not already.")
    return 0


def main():
    ap = argparse.ArgumentParser(description="Check the microphone reaches this PC.")
    ap.add_argument("--device", type=int, default=None,
                    help="input number to test (default: config.MIC_DEVICE)")
    ap.add_argument("--seconds", type=int, default=10)
    ap.add_argument("--list", action="store_true", help="just list the inputs")
    args = ap.parse_args()

    if args.list:
        list_devices()
        return 0

    device = args.device if args.device is not None else config.MIC_DEVICE
    if device is None:
        print("MIC_DEVICE is None (the Windows default input).")
        print()
    list_devices()
    print()
    return test(device, args.seconds)


if __name__ == "__main__":
    sys.exit(main())
