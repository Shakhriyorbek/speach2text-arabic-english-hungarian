"""
Azure Speech Translation backend — Arabic/English speech -> Hungarian DIRECTLY.

This is the optional "cloud" mode. Unlike the offline path (Whisper -> English
-> opus-mt -> Hungarian, two lossy hops on a weak CPU), Azure translates the
speech straight into Hungarian in one streaming step. That removes the English
pivot entirely and is dramatically better for Arabic, which is what a weak CPU
cannot do well locally.

Trade-offs vs the offline backend:
  + Much better Arabic accuracy, much lower delay (streaming + interim results)
  + No local CPU cost — works fine on a weak laptop
  - Requires reliable internet at the mosque
  - Sends audio to Microsoft (a khutbah is public speech, but be aware)
  - Needs an Azure Speech resource (free tier covers a few audio-hours/month)

CREDENTIALS: read from environment variables, never hardcoded:
    AZURE_SPEECH_KEY      your Speech resource key
    AZURE_SPEECH_REGION   e.g. "westeurope"
Set them yourself (see README) — do not paste keys into this file or share them.

Audio is captured with sounddevice (so config.MIC_DEVICE still applies) and
pushed into Azure's streaming API. Azure does its own segmentation, so the
local webrtcvad chunker is not used in this mode.
"""

import os
import threading

import sounddevice as sd

import config


def _require_sdk():
    """Import the Azure Speech SDK, with a helpful message if it's missing."""
    try:
        import azure.cognitiveservices.speech as speechsdk

        return speechsdk
    except ImportError as exc:  # pragma: no cover
        raise ImportError(
            "Cloud mode needs the Azure Speech SDK. Install it with:\n"
            "    venv\\Scripts\\pip install -r requirements-azure.txt"
        ) from exc


class AzureBackend:
    """Streams the microphone to Azure and emits Hungarian lines to ``ui_queue``.

    Interface mirrors what app.py needs from the offline path:
    ``start() / stop() / set_mode(mode) / toggle_pause() / is_paused``.
    """

    def __init__(self, ui_queue):
        self.ui_queue = ui_queue
        self.sdk = _require_sdk()

        self._key = os.environ.get("AZURE_SPEECH_KEY", "").strip()
        self._region = os.environ.get("AZURE_SPEECH_REGION", "").strip()
        if not self._key or not self._region:
            raise RuntimeError(
                "Cloud mode needs Azure credentials in environment variables:\n"
                "    AZURE_SPEECH_KEY     (your Speech resource key)\n"
                "    AZURE_SPEECH_REGION  (e.g. westeurope)\n"
                "See the 'Cloud mode' section of the README for how to set them."
            )

        self.mode = "part1"
        self._paused = threading.Event()
        self._lock = threading.Lock()

        self._recognizer = None
        self._push_stream = None
        self._mic = None

    # -- lifecycle ---------------------------------------------------------

    def start(self):
        with self._lock:
            self._start_locked()

    def stop(self):
        with self._lock:
            self._stop_locked()

    def set_mode(self, mode):
        """Switch khutbah part. Azure fixes the source language at recognizer
        creation, so this tears down and rebuilds the stream (a second or two).
        It happens once, between the two parts."""
        if mode == self.mode:
            return
        with self._lock:
            self.mode = mode
            self._stop_locked()
            self._start_locked()

    def toggle_pause(self):
        if self._paused.is_set():
            self._paused.clear()
        else:
            self._paused.set()
        return self._paused.is_set()

    @property
    def is_paused(self):
        return self._paused.is_set()

    # -- internals (call with self._lock held) -----------------------------

    def _start_locked(self):
        sdk = self.sdk

        cfg = sdk.translation.SpeechTranslationConfig(
            subscription=self._key, region=self._region
        )
        cfg.add_target_language(config.AZURE_TARGET_LANG)

        fmt = sdk.audio.AudioStreamFormat(
            samples_per_second=config.SAMPLE_RATE, bits_per_sample=16, channels=1
        )
        self._push_stream = sdk.audio.PushAudioInputStream(stream_format=fmt)
        audio_cfg = sdk.audio.AudioConfig(stream=self._push_stream)

        if self.mode == "part1":
            # Part 1 is entirely Arabic — pin the language for best accuracy.
            cfg.speech_recognition_language = config.AZURE_LANG_PART1
            self._recognizer = sdk.translation.TranslationRecognizer(
                translation_config=cfg, audio_config=audio_cfg
            )
        else:
            # Part 2 mixes an English talk with Arabic quotes — let Azure pick.
            auto = sdk.languageconfig.AutoDetectSourceLanguageConfig(
                languages=list(config.AZURE_LANGS_PART2)
            )
            self._recognizer = sdk.translation.TranslationRecognizer(
                translation_config=cfg,
                audio_config=audio_cfg,
                auto_detect_source_language_config=auto,
            )

        self._recognizer.recognized.connect(self._on_recognized)
        self._recognizer.canceled.connect(self._on_canceled)
        if config.AZURE_SHOW_INTERIM:
            self._recognizer.recognizing.connect(self._on_recognizing)

        self._recognizer.start_continuous_recognition_async().get()
        self._start_mic()

    def _stop_locked(self):
        self._stop_mic()
        if self._push_stream is not None:
            try:
                self._push_stream.close()
            except Exception:
                pass
            self._push_stream = None
        if self._recognizer is not None:
            try:
                self._recognizer.stop_continuous_recognition_async().get()
            except Exception:
                pass
            self._recognizer = None

    def _start_mic(self):
        def callback(indata, frames, time_info, status):
            # Realtime thread: only hand bytes to Azure, never block.
            if self._paused.is_set():
                return
            stream = self._push_stream
            if stream is not None:
                try:
                    stream.write(indata[:, 0].tobytes())
                except Exception:
                    pass

        self._mic = sd.InputStream(
            samplerate=config.SAMPLE_RATE,
            channels=1,
            dtype="int16",
            blocksize=int(config.SAMPLE_RATE * 0.1),  # 100 ms blocks
            device=config.MIC_DEVICE,
            callback=callback,
        )
        self._mic.start()

    def _stop_mic(self):
        if self._mic is not None:
            try:
                self._mic.stop()
                self._mic.close()
            except Exception:
                pass
            self._mic = None

    # -- Azure event handlers (called on SDK threads) ----------------------

    def _hungarian(self, result):
        try:
            return (result.translations.get(config.AZURE_TARGET_LANG, "") or "").strip()
        except Exception:
            return ""

    def _on_recognized(self, evt):
        """A finalized utterance — this is the real subtitle line."""
        if self._paused.is_set():
            return
        result = evt.result
        if result.reason != self.sdk.ResultReason.TranslatedSpeech:
            return
        hu = self._hungarian(result)
        if not hu:
            return
        source = (result.text or "").strip()
        self.ui_queue.put(("line", hu, source if config.SHOW_ENGLISH else None))
        print(f"  SRC: {source}\n  HU: {hu}", flush=True)

    def _on_recognizing(self, evt):
        """Interim (still-being-spoken) result — updates the line in place.

        This is what makes cloud mode feel fast: text appears while the speaker
        is still talking, instead of only after they pause."""
        if self._paused.is_set():
            return
        hu = self._hungarian(evt.result)
        if hu:
            self.ui_queue.put(("partial", hu))

    def _on_canceled(self, evt):
        """Errors: bad key, no network, quota exceeded, etc."""
        reason = getattr(evt, "reason", None)
        details = getattr(evt, "error_details", "") or ""
        msg = f"[Azure] cancelled: {reason} {details}".strip()
        print(msg, flush=True)
        # Surface it on screen too — otherwise the operator just sees a dead
        # screen and has no idea the cloud connection failed.
        if details or reason is not None:
            self.ui_queue.put(("line", "⚠ Felhő hiba — nézd meg a konzolt", None))
