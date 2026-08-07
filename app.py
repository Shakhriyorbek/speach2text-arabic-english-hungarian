"""
Entry point — wires the whole pipeline together.

Two interchangeable backends, selected by ``config.BACKEND``:

  "local"  (offline, free, private — capped by CPU on Arabic)
    Mic ── audio_q ──▶ ASR+MT worker ── ui_q ──▶ Tkinter window (main thread)
    Whisper (task=translate) -> English -> opus-mt -> Hungarian.

  "azure"  (cloud, needs internet + key — far better Arabic, lower delay)
    Mic ──▶ Azure Speech Translation ── ui_q ──▶ Tkinter window
    Speech -> Hungarian directly, no English pivot.

Either way the UI is identical and runs on the main thread; backends only ever
push messages onto ``ui_q``.
"""

import queue
import threading
import time

import config
from subtitles.console import enable_utf8_console

enable_utf8_console()

from subtitles.ui import SubtitleWindow


def run_local():
    """Fully offline pipeline: Whisper -> English -> opus-mt -> Hungarian."""
    from subtitles.audio import UtteranceChunker
    from subtitles.asr import Transcriber

    direct = getattr(config, "TRANSLATION_PATH", "pivot").lower() == "direct"

    print("Loading models — this can take 10-30s on a weak laptop...")
    t0 = time.time()
    transcriber = Transcriber()
    if direct:
        # Arabic -> Hungarian with no English in between. See mt_direct.py.
        from subtitles.mt_direct import DirectTranslator

        translator = DirectTranslator()
    else:
        from subtitles.mt import Translator

        translator = Translator()
    print(f"Models loaded in {time.time() - t0:.1f}s.")
    print(f"Translation path: {'Arabic -> Hungarian (direct, NLLB)' if direct else 'via English (opus-mt)'}")

    # Optionally hand transcription to a GPU box. The local model above stays
    # loaded regardless and becomes the automatic fallback — loading it later,
    # mid-sermon, would stall the audio at the worst possible moment.
    if getattr(config, "ASR_LOCATION", "cpu").lower() == "remote":
        from subtitles.asr_remote import RemoteTranscriber

        remote = RemoteTranscriber(local_fallback=transcriber)
        info = remote.health()
        if info:
            print(f"Remote ASR: {info.get('model')} on {info.get('device')} "
                  f"at {config.REMOTE_ASR_URL}")
        else:
            print(f"Remote ASR at {config.REMOTE_ASR_URL} is NOT responding — "
                  f"starting on the local model instead.")
        transcriber = remote

    audio_q: "queue.Queue" = queue.Queue(maxsize=config.ASR_QUEUE_MAX)
    ui_q: "queue.Queue" = queue.Queue()

    chunker = UtteranceChunker(audio_q)
    stop_event = threading.Event()

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
                # Pivot path: this is English. Direct path: it is the spoken
                # language (Arabic for Part 1).
                source_text = transcriber.transcribe(audio)
            except Exception as exc:  # never let one bad chunk kill the loop
                print(f"[ASR error] {exc}")
                continue
            if not source_text:
                continue

            try:
                if direct:
                    # Tell the translator which language it has been handed;
                    # Part 2 auto-detects, so this can change per utterance.
                    translator.src_lang = getattr(transcriber, "last_language", "ar")
                hungarian = translator.translate(source_text)
            except Exception as exc:
                print(f"[MT error] {exc}")
                continue
            if not hungarian:
                continue

            ui_q.put(("line", hungarian, source_text if config.SHOW_ENGLISH else None))
            # Console transcript log (does NOT affect the projector window).
            # Useful as a diagnostic and as a record of what was said.
            label = (getattr(transcriber, "last_language", "ar").upper()
                     if direct else "EN")
            print(f"  {label}: {source_text}\n  HU: {hungarian}", flush=True)

    worker = threading.Thread(target=asr_mt_loop, name="asr-mt", daemon=True)

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

    chunker.start()
    worker.start()
    print("Ready (offline mode). F1 = Part 1 (Arabic), F2 = Part 2 (auto).")
    print("F11 fullscreen · +/- font · P pause · Esc quit.")

    try:
        window.run()   # blocks until the window is closed
    finally:
        stop_event.set()
        chunker.stop()


def run_azure():
    """Cloud pipeline: Azure translates speech straight into Hungarian."""
    from subtitles.azure_backend import AzureBackend

    ui_q: "queue.Queue" = queue.Queue()

    print("Connecting to Azure Speech...")
    backend = AzureBackend(ui_q)

    def on_set_mode(mode):
        print(f"[mode] -> {mode} (reconnecting stream...)")
        backend.set_mode(mode)

    def on_quit():
        print("Shutting down...")
        backend.stop()

    window = SubtitleWindow(
        ui_queue=ui_q,
        on_set_mode=on_set_mode,
        on_toggle_pause=backend.toggle_pause,
        on_quit=on_quit,
    )

    backend.start()
    print("Ready (cloud mode). F1 = Part 1 (Arabic), F2 = Part 2 (auto).")
    print("F11 fullscreen · +/- font · P pause · Esc quit.")

    try:
        window.run()
    finally:
        backend.stop()


def main():
    backend = getattr(config, "BACKEND", "local").lower()
    if backend == "azure":
        run_azure()
    elif backend == "local":
        run_local()
    else:
        raise SystemExit(
            f"config.BACKEND is {backend!r}; expected \"local\" or \"azure\"."
        )


if __name__ == "__main__":
    main()
