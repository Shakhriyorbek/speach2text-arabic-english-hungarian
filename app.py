"""
Entry point — wires the whole pipeline together.

    Mic ── audio_q ──▶ ASR+MT worker thread ── ui_q ──▶ Tkinter window (main thread)

Thread map:
  * audio worker (inside UtteranceChunker) : mic -> VAD -> utterances -> audio_q
  * asr_mt worker (here)                   : audio_q -> English -> Hungarian -> ui_q
  * main thread                            : the Tkinter subtitle window

Back-pressure lives on audio_q (bounded, drop-oldest) so a slow CPU degrades to
"occasional dropped sentence" instead of ever-growing lag. ui_q is unbounded
because the UI always drains it quickly.
"""

import queue
import threading
import time

import config
from subtitles.console import enable_utf8_console

enable_utf8_console()

from subtitles.audio import UtteranceChunker
from subtitles.asr import Transcriber
from subtitles.mt import Translator
from subtitles.ui import SubtitleWindow


def main():
    print("Loading models — this can take 10-30s on a weak laptop...")
    t0 = time.time()
    transcriber = Transcriber()
    translator = Translator()
    print(f"Models loaded in {time.time() - t0:.1f}s.")

    audio_q: "queue.Queue" = queue.Queue(maxsize=config.ASR_QUEUE_MAX)
    ui_q: "queue.Queue" = queue.Queue()

    chunker = UtteranceChunker(audio_q)
    stop_event = threading.Event()

    # -- ASR + MT worker ----------------------------------------------------

    def asr_mt_loop():
        while not stop_event.is_set():
            try:
                audio = audio_q.get(timeout=0.2)
            except queue.Empty:
                continue

            # Surface any drop that happened while this chunk waited.
            if chunker.dropped.is_set():
                chunker.dropped.clear()
                ui_q.put(("dropped",))

            try:
                english = transcriber.transcribe(audio)
            except Exception as exc:  # never let one bad chunk kill the loop
                print(f"[ASR error] {exc}")
                continue
            if not english:
                continue

            try:
                hungarian = translator.translate(english)
            except Exception as exc:
                print(f"[MT error] {exc}")
                continue
            if not hungarian:
                continue

            ui_q.put(("line", hungarian, english if config.SHOW_ENGLISH else None))
            # Console transcript log (does NOT affect the projector window).
            # Useful as a diagnostic and as a record of what was said.
            print(f"  EN: {english}\n  HU: {hungarian}", flush=True)

    worker = threading.Thread(target=asr_mt_loop, name="asr-mt", daemon=True)

    # -- UI callbacks -------------------------------------------------------

    def on_set_mode(mode):
        transcriber.mode = mode
        print(f"[mode] -> {mode}")

    def on_toggle_pause():
        if chunker.is_paused:
            chunker.resume()
        else:
            chunker.pause()
        return chunker.is_paused

    def on_quit():
        print("Shutting down...")
        stop_event.set()
        chunker.stop()
        worker.join(timeout=2.0)

    window = SubtitleWindow(
        ui_queue=ui_q,
        on_set_mode=on_set_mode,
        on_toggle_pause=on_toggle_pause,
        on_quit=on_quit,
    )

    # -- go -----------------------------------------------------------------

    chunker.start()
    worker.start()
    print("Ready. In the subtitle window: F1 = Part 1 (Arabic), F2 = Part 2 (auto).")
    print("F11 fullscreen · +/- font · P pause · Esc quit.")

    try:
        window.run()   # blocks until the window is closed
    finally:
        stop_event.set()
        chunker.stop()


if __name__ == "__main__":
    main()
