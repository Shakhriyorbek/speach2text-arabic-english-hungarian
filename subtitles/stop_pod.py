"""
STOP.bat — give the GPU back now.

START.bat already releases the GPU when the subtitle window closes, and the pod
stops itself after RUNPOD_DEADLINE_HOURS regardless. This covers the gap between
those two: the laptop was shut, or the program was killed, and somebody wants
the billing to stop immediately rather than in a few hours.

Deliberately says something reassuring when there is nothing to do. An operator
who runs this "just in case" and gets silence will run it again, and then start
wondering whether it worked.
"""

import sys

from subtitles import pod
from subtitles.console import enable_utf8_console

enable_utf8_console()


def main():
    pod_id = pod.remembered()
    if not pod_id:
        print("Nincs bérelt GPU.  /  No GPU is rented.")
        print()
        print("Nothing is being billed. You can close this window.")
        return 0

    print(f"Bérelt GPU / rented GPU: {pod_id}")
    print("Leállítás... / releasing...")
    try:
        pod.terminate(pod_id)
    except pod.PodError as exc:
        print()
        print(f"Nem sikerült / it did not work: {exc}")
        print()
        print("The machine stops itself within a few hours anyway, so this is")
        print("not urgent. If you want to be sure, open the RunPod website and")
        print("terminate the pod there.")
        return 1

    pod.forget()
    print()
    print("Kész — a számlázás leállt.  /  Done — billing has stopped.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
