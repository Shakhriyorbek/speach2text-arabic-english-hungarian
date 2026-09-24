"""
START.bat — rent the GPU, check it, and run the subtitles. One double-click.

The problem this solves is not technical. The GPU path worked; it just could
only be driven by someone willing to use a cloud console, and the people who
actually run this are the imam and whoever is free that morning. So everything
that used to be typed is done here instead, and the operator sees one window
with plain sentences in it.

What happens, in order:

    1. terminate anything left over from last week
    2. generate a fresh transcription token
    3. rent a GPU and start the server on it
    4. wait for the pod
    5. wait for the models to load
    6. check the server is really answering us, with our token
    7. run the subtitles
    8. terminate the pod when the window closes

Steps 3-8 cost money, so step 8 is defended three ways: this module terminates
on the way out, the pod terminates itself after RUNPOD_DEADLINE_HOURS even if
this laptop is unplugged, and step 1 catches whatever still slipped through.

**Nothing here may be able to stop a khutbah.** Every failure lands on a screen
that offers to carry on with the laptop's own models, because a worse subtitle
is worth a great deal and a blank projector is worth nothing. That is the same
trade the rest of the codebase makes (see asr_remote.py's fallback).
"""

from __future__ import annotations

import json
import queue
import secrets
import threading
import time
import tkinter as tk
import tkinter.font as tkfont
import urllib.error
import urllib.request

import config
from subtitles import pod
from subtitles.console import enable_utf8_console
from subtitles.http_client import USER_AGENT

enable_utf8_console()


# Both languages on every line. Whoever is standing at the laptop may be a
# Hungarian volunteer or an Arabic-speaking imam; guessing wrong costs more
# than the extra width.
STEPS = [
    ("Korábbi bérlés ellenőrzése", "Checking for a leftover rental"),
    ("Kód készítése", "Generating an access code"),
    ("GPU bérlése", "Renting the GPU"),
    ("Gép indítása", "Starting the machine"),
    ("Modellek betöltése", "Loading the models"),
    ("Ellenőrzés", "Checking it works"),
]


class Cancelled(Exception):
    """The operator pressed Esc while we were still setting up."""


def check_tk():
    """Fail with something readable if Tkinter cannot open a window.

    Tkinter draws the subtitle window, so a broken Tcl install stops
    everything — and it announces itself as a traceback ending in "Can't find
    a usable init.tcl", which is not a sentence anyone should have to meet on a
    Friday morning. Almost always the Python installer was run without the
    "tcl/tk and IDLE" component ticked.
    """
    try:
        probe = tk.Tk()
        probe.withdraw()
        probe.destroy()
        return True
    except Exception as exc:                # noqa: BLE001
        print()
        print("=" * 70)
        print("PYTHON CANNOT DRAW WINDOWS ON THIS MACHINE.")
        print()
        print(f"  {type(exc).__name__}: {str(exc).splitlines()[0]}")
        print()
        print("Tkinter is missing or broken, and it is what draws the subtitle")
        print("window — so nothing can run until it is fixed. It is a Python")
        print("installation problem, not a problem with this program.")
        print()
        print("To fix it:")
        print("  1. Windows Settings -> Apps -> find 'Python 3.13' -> Modify")
        print("     (Parametres -> Applications -> Python 3.13 -> Modifier)")
        print("  2. Choose 'Modify', and make sure 'tcl/tk and IDLE' IS TICKED")
        print("  3. Finish, then run install.bat again")
        print()
        print("This program already tried to locate Tcl itself and could not.")
        print("Here is what it found, which tells you whether the files are")
        print("missing or merely in the wrong place:")
        print()
        from subtitles.winfix import tcl_report
        print(tcl_report())
        print()
        print("If the tcl directory says MISSING, the component really is not")
        print("installed — repeat the Modify above and watch that the box stays")
        print("ticked. If it EXISTS, delete your venv folder and run")
        print("install.bat again: a venv built before tcl/tk was added does not")
        print("pick it up.")
        print()
        print("Meanwhile the GPU half can still be checked, since it needs no")
        print("window:")
        print("     venv\\Scripts\\python -m subtitles.launcher --selftest")
        print("=" * 70)
        return False


# --- the work, on a background thread ------------------------------------


def _health(url: str, timeout: float = 10.0) -> dict:
    req = urllib.request.Request(f"{url}/health", method="GET",
                                 headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _authenticated_round_trip(url: str, token: str, timeout: float = 15.0) -> None:
    """Send half a second of silence, to prove the token is accepted.

    /health is unauthenticated on purpose, so a green health check says nothing
    at all about whether our token matches. Normally that is the risk of a
    hand-copied token — here we generated it ourselves, so this is really
    checking that the proxy passes our headers through untouched. Cheap, and it
    is the difference between finding out now and finding out on a blank screen.
    """
    import array
    import sys

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
            "User-Agent": USER_AGENT,
        },
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        resp.read()


def _bring_up(progress, should_stop) -> tuple[str, str, dict]:
    """Rent a GPU and return (url, token, health). Raises PodError/Cancelled."""

    def check_cancel():
        if should_stop.is_set():
            raise Cancelled()

    progress(0, "")
    left = pod.release_leftover()
    progress(0, "megszüntetve / released" if left else "nincs / none")
    check_cancel()

    progress(1, "")
    token = secrets.token_hex(32)
    progress(1, "kész / done")
    check_cancel()

    progress(2, "")
    info = pod.create(token)
    pod_id = info["id"]
    # Remember it the instant it exists — see pod.remember().
    pod.remember(pod_id, token)
    url = pod.proxy_url(pod_id)
    cost = info.get("costPerHr")
    gpu = (info.get("machine") or {}).get("gpuTypeId") or ""
    progress(2, f"{gpu} ~${cost}/óra" if cost else (gpu or "kész / done"))
    check_cancel()

    deadline = time.time() + getattr(config, "POD_BOOT_TIMEOUT_S", 480)

    # Stage 4: the pod exists on paper; wait until RunPod says it is running.
    progress(3, "")
    while True:
        check_cancel()
        if time.time() > deadline:
            raise pod.PodError(
                "The rented machine did not start in time.\n"
                "This usually means the datacenter is busy. Try again, or "
                "carry on without the GPU."
            )
        state = pod.get(pod_id)
        if state and state.get("desiredStatus") == "RUNNING":
            break
        time.sleep(5)
    progress(3, "fut / running")

    # Stage 5: RUNNING only means the container was handed a machine. The real
    # readiness signal is the server answering, which is gated on ~11 GB of
    # models being read off the network volume — the slow part.
    progress(4, "")
    last_error = "no answer yet"
    while True:
        check_cancel()
        if time.time() > deadline:
            raise pod.PodError(
                f"The GPU server never answered ({last_error}).\n"
                f"The machine is running but the subtitle server did not come "
                f"up on it. Carry on without the GPU; the pod will stop itself."
            )
        try:
            health = _health(url, timeout=10.0)
            if health.get("ok"):
                break
        except Exception as exc:                # noqa: BLE001 - report, keep waiting
            last_error = type(exc).__name__
        remaining = int(deadline - time.time())
        progress(4, f"még legfeljebb {remaining}s / up to {remaining}s more",
                 done=False)
        time.sleep(5)
    progress(4, f"{health.get('model')} / {health.get('device')}")

    # Stage 6: prove the round trip, not just the greeting.
    progress(5, "")
    check_cancel()
    _authenticated_round_trip(url, token)
    progress(5, "rendben / ok")

    return url, token, health


# --- the window ----------------------------------------------------------


class LauncherWindow:
    """A progress window that never blocks the khutbah.

    Outcome is one of: "gpu" (ready, use it), "cpu" (carry on locally), or
    "quit". There is deliberately no fourth option where the operator is left
    with nothing.
    """

    def __init__(self):
        self.outcome = "quit"
        self.url = ""
        self.token = ""
        self.health: dict = {}

        self._q: "queue.Queue" = queue.Queue()
        self._stop = threading.Event()
        self._done = False

        self.root = tk.Tk()
        self.root.title("Khutbah Subtitles")
        self.root.configure(bg=config.BG)
        self.root.geometry("820x560")

        family = config.FONT_FAMILY
        self._f_title = tkfont.Font(family=family, size=26, weight="bold")
        self._f_step = tkfont.Font(family=family, size=15)
        self._f_note = tkfont.Font(family=family, size=12)

        tk.Label(
            self.root, text="GPU indítása  /  Starting the GPU",
            font=self._f_title, fg=config.FG_NEW, bg=config.BG, pady=18,
        ).pack(fill="x")

        body = tk.Frame(self.root, bg=config.BG)
        body.pack(expand=True, fill="both", padx=48)

        self._rows = []
        for hu, en in STEPS:
            row = tk.Label(
                body, text=f"    {hu}  /  {en}", font=self._f_step,
                fg=config.FG_OLD, bg=config.BG, anchor="w",
            )
            row.pack(fill="x", pady=3)
            self._rows.append(row)

        self._note = tk.Label(
            self.root, text="", font=self._f_note,
            fg=config.FG_PARTIAL, bg=config.BG, wraplength=740, justify="left",
        )
        self._note.pack(fill="x", padx=48, pady=(8, 4))

        self._buttons = tk.Frame(self.root, bg=config.BG)
        self._buttons.pack(fill="x", padx=48, pady=18)

        # Esc always means "I do not want to wait any more", at every stage.
        self.root.bind("<Escape>", lambda e: self._cancel())
        self.root.protocol("WM_DELETE_WINDOW", self._cancel)

        threading.Thread(target=self._worker, daemon=True, name="pod-bringup").start()
        self.root.after(100, self._poll)

    # -- worker side -------------------------------------------------------

    def _worker(self):
        def progress(index, note, done=True):
            self._q.put(("step", index, note if done else ("~" + note)))

        try:
            url, token, health = _bring_up(progress, self._stop)
        except Cancelled:
            self._q.put(("cancelled", None, None))
        except pod.PodError as exc:
            self._q.put(("error", str(exc), None))
        except Exception as exc:                # noqa: BLE001 - never crash here
            self._q.put(("error", f"{type(exc).__name__}: {exc}", None))
        else:
            self._q.put(("ready", (url, token, health), None))

    # -- UI side -----------------------------------------------------------

    def _poll(self):
        try:
            while True:
                kind, a, b = self._q.get_nowait()
                if kind == "step":
                    self._mark(a, b)
                elif kind == "ready":
                    self.url, self.token, self.health = a
                    self.outcome = "gpu"
                    self._finish()
                    return
                elif kind == "cancelled":
                    self._offer_cpu(
                        "Megszakítva. / Cancelled.",
                        detail="A GPU bérlése leállt. Feliratozás a laptopról?  /  "
                               "GPU rental stopped. Run subtitles on the laptop?",
                    )
                    return
                elif kind == "error":
                    self._offer_cpu("Nem sikerült / It did not work", detail=a)
                    return
        except queue.Empty:
            pass
        if not self._done:
            self.root.after(100, self._poll)

    def _mark(self, index, note=""):
        """Show step ``index`` as current, everything before it as done.

        The note is the only place a number ever appears ("still 240s"), and it
        matters more than it looks: loading the models off a network volume
        takes minutes, and a window that says nothing for minutes is
        indistinguishable from a window that has crashed.
        """
        for i, (hu, en) in enumerate(STEPS):
            # A note prefixed with "~" means "still working, and here is why
            # the wait is normal" — not "done". Marking a six-minute wait as OK
            # every five seconds is how a progress display stops being read.
            waiting = bool(note) and note.startswith("~")
            if i < index or (i == index and note and not waiting):
                mark, colour = "OK", config.FG_BADGE
            elif i == index:
                mark, colour = "..", config.FG_NEW
            else:
                mark, colour = "  ", config.FG_OLD
            text = f" {mark} {hu}  /  {en}"
            if i == index and note:
                text += f"   —  {note.lstrip('~')}"
            self._rows[i].configure(text=text, fg=colour)

    def _finish(self):
        self._done = True
        self.root.destroy()

    def _cancel(self):
        if self._done:
            return
        self._stop.set()

    def _offer_cpu(self, headline, detail=""):
        """Every dead end lands here, never on a closed window."""
        self._note.configure(text=f"{headline}\n\n{detail}", fg=config.FG_NEW)
        for w in self._buttons.winfo_children():
            w.destroy()

        def choose(outcome):
            self.outcome = outcome
            self._done = True
            self.root.destroy()

        tk.Button(
            self._buttons,
            text="Folytatás GPU nélkül  /  Continue without the GPU",
            font=self._f_step, command=lambda: choose("cpu"),
            padx=16, pady=10,
        ).pack(side="left")
        tk.Button(
            self._buttons, text="Kilépés  /  Quit", font=self._f_step,
            command=lambda: choose("quit"), padx=16, pady=10,
        ).pack(side="right")

    def run(self):
        self.root.mainloop()
        return self.outcome


# --- self-test -----------------------------------------------------------


def selftest() -> int:
    """Rent the GPU, prove it works, release it — without the subtitle app.

    Everything START.bat does except show subtitles: create the pod, wait for
    it, wait for the models, check the token round-trips, report what is
    loaded, terminate. It exists so the GPU half can be rehearsed from any
    machine, including a Linux dev box with no microphone, sounddevice or
    faster-whisper installed — and so the first time the pod is exercised is
    not the morning of a khutbah.

    It ALWAYS terminates the pod, including on Ctrl-C.
    """
    import urllib.request

    stop = threading.Event()
    t0 = time.time()

    def progress(index, note, done=True):
        hu, en = STEPS[index]
        mark = "OK" if (note and done) else ".."
        line = f"  [{mark}] {en}"
        if note:
            line += f"  —  {note}"
        print(f"{line}   ({time.time() - t0:.0f}s)", flush=True)

    print("GPU self-test — this rents a real GPU and will bill for a few minutes.")
    print("=" * 70)
    try:
        url, token, health = _bring_up(progress, stop)
    except KeyboardInterrupt:
        print("\ninterrupted")
        _release()
        return 130
    except (Cancelled, pod.PodError) as exc:
        print(f"\nFAILED: {exc}")
        _release()
        return 1
    except Exception as exc:                    # noqa: BLE001
        print(f"\nFAILED: {type(exc).__name__}: {exc}")
        _release()
        return 1

    print("=" * 70)
    print(f"  url             : {url}")
    for k in ("model", "device", "compute_type", "gpu", "vram_gb",
              "beam", "translate", "translate_model", "translate_compute_type",
              "translate_beam", "deadline"):
        if k in health:
            print(f"  {k:16}: {health[k]}")

    problems = []
    if health.get("device") != "cuda":
        problems.append(f"running on {health.get('device')!r}, not a GPU")
    if health.get("model") not in ("large-v3", "large-v2"):
        problems.append(f"model is {health.get('model')!r}, not large-v3")
    if not health.get("translate"):
        problems.append("translation is disabled on the server")
    if not health.get("deadline"):
        problems.append("no automatic shutdown is armed — a forgotten pod "
                        "would bill until someone noticed")

    # Translation is the half the health check cannot vouch for: a server can
    # report a model loaded and still return nonsense. Send one real line.
    if health.get("translate"):
        try:
            req = urllib.request.Request(
                f"{url}/translate",
                data="أيها الناس اتقوا الله".encode("utf-8"),
                method="POST",
                headers={"Authorization": f"Bearer {token}",
                         "Content-Type": "text/plain; charset=utf-8",
                         "X-Src-Lang": "ar",
                         "User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, timeout=30) as resp:
                hu = (json.loads(resp.read().decode("utf-8")).get("text") or "").strip()
            print(f"\n  AR -> HU        : {hu!r}")
            if not hu:
                problems.append("translation returned nothing")
        except Exception as exc:                # noqa: BLE001
            problems.append(f"translation failed: {type(exc).__name__}: {exc}")

    print()
    for p in problems:
        print(f"  PROBLEM: {p}")
    print()
    _release()

    if problems:
        print("\nNOT READY — see above.")
        return 1
    print(f"\nREADY. Whole cycle took {time.time() - t0:.0f}s.")
    print("If that Hungarian above is sane, the GPU path works end to end.")
    return 0


# --- entry point ---------------------------------------------------------


def main():
    import app

    if not pod.is_configured():
        # Not set up to rent GPUs — that is a legitimate configuration, so run
        # exactly as run.bat would rather than complaining about it.
        print("RunPod is not configured; starting with the settings in "
              "config.py as they are.", flush=True)
        app.main()
        return 0

    if not check_tk():
        return 2

    win = LauncherWindow()
    outcome = win.run()

    if outcome == "quit":
        # The operator chose to stop, but a pod may already exist and be
        # billing. Releasing it is the last thing we do.
        leftover = pod.remembered()
        if leftover:
            try:
                pod.terminate(leftover)
                pod.forget()
                print("GPU released.", flush=True)
            except pod.PodError as exc:
                print(f"Could not release the GPU: {exc}", flush=True)
        return 1

    if outcome == "cpu":
        # config was imported long ago, so setting the environment now would
        # change nothing — write the values app.py reads, directly.
        config.ASR_LOCATION = "cpu"
        config.MT_LOCATION = "cpu"
        # Re-transcribing the whole utterance every second is affordable on a
        # GPU and not on this laptop's CPU; leaving it on here is what makes a
        # degraded run feel broken rather than merely worse. See config.py.
        config.STREAMING_PARTIALS = False
        print("Running on this laptop's own models.", flush=True)
        try:
            app.main()
        finally:
            _release()
        return 0

    # GPU is up and answered us.
    import os

    os.environ["WHISPER_SERVER_TOKEN"] = win.token
    config.REMOTE_ASR_URL = win.url
    config.REMOTE_MT_URL = win.url
    # Set BOTH explicitly rather than leaning on the defaults in config.py:
    # config_local.py may have forced them to "cpu" on this laptop, and the
    # whole point of getting here is that the GPU is up and answering.
    config.ASR_LOCATION = "remote"
    config.MT_LOCATION = "remote"
    if not win.health.get("translate"):
        # The server came up without NLLB. Say so once, here, rather than
        # letting app.py discover it and print a line nobody is looking at.
        print("NOTE: the GPU has no translation model — Hungarian will come "
              "from this laptop.", flush=True)
        config.MT_LOCATION = "cpu"

    print(f"GPU ready: {win.health.get('model')} on {win.health.get('device')} "
          f"at {win.url}", flush=True)
    try:
        app.main()
    finally:
        _release()
    return 0


def _release():
    """Give the GPU back. Runs however the subtitle window ended."""
    pod_id = pod.remembered()
    if not pod_id:
        return
    print("Releasing the GPU...", flush=True)
    try:
        pod.terminate(pod_id)
        pod.forget()
        print("GPU released — billing has stopped.", flush=True)
    except pod.PodError as exc:
        # The pod's own deadline is the backstop, so say what will happen
        # rather than leaving the operator thinking money is draining.
        print(f"Could not release the GPU: {exc}\n"
              f"It will stop itself within "
              f"{getattr(config, 'RUNPOD_DEADLINE_HOURS', 6)} hours. To stop it "
              f"now, double-click STOP.bat.", flush=True)


if __name__ == "__main__":
    import sys

    if "--selftest" in sys.argv:
        sys.exit(selftest())
    sys.exit(main())
