"""
Microphone capture + voice-activity detection (VAD) chunker.

Turns a continuous microphone stream into discrete "utterances" — chunks of
speech delimited by natural pauses — so that each utterance can be transcribed
and displayed as one subtitle line.

Design notes:
  * The sounddevice audio callback runs on a realtime thread; it must NEVER
    block or do heavy work. Here it only copies raw int16 frames into a
    thread-safe deque. All VAD/logic happens on a separate worker thread.
  * Utterances are emitted as float32 mono arrays in [-1, 1], which is exactly
    what faster-whisper accepts directly (no temp WAV files needed).
  * Emitting uses a drop-OLDEST policy on a bounded queue so that a slow CPU
    can never fall unboundedly behind: under overload we lose the oldest
    pending audio and raise a flag the UI turns into a "…" marker.
"""

import collections
import queue
import threading

import numpy as np
import sounddevice as sd

try:
    import webrtcvad
except ImportError as exc:  # pragma: no cover - guidance for setup mistakes
    raise ImportError(
        "webrtcvad is not installed. Install with:  pip install webrtcvad-wheels"
    ) from exc

import config


# States of the utterance state machine.
_IDLE = "idle"
_RECORDING = "recording"


class UtteranceChunker:
    """Captures the mic and pushes speech utterances onto ``out_queue``.

    Parameters
    ----------
    out_queue : queue.Queue
        Bounded queue (maxsize = config.ASR_QUEUE_MAX). Utterances are placed
        here as float32 numpy arrays. On overflow the oldest item is dropped.
    """

    def __init__(self, out_queue: "queue.Queue[np.ndarray]"):
        self.out_queue = out_queue

        self._frame_len = int(config.SAMPLE_RATE * config.FRAME_MS / 1000)  # 480
        self._vad = webrtcvad.Vad(config.VAD_AGGRESSIVENESS)

        # Raw frames from the audio callback land here (bytes of one VAD frame).
        self._raw = collections.deque()
        self._raw_lock = threading.Lock()

        # Rolling pre-roll buffer (frames captured just before speech starts).
        pre_roll_frames = max(1, int(config.PRE_ROLL_MS / config.FRAME_MS))
        self._pre_roll = collections.deque(maxlen=pre_roll_frames)

        self._silence_end_frames = max(1, int(config.SILENCE_END_MS / config.FRAME_MS))
        self._max_frames = int(config.MAX_UTTERANCE_S * 1000 / config.FRAME_MS)
        self._min_frames = max(1, int(config.MIN_UTTERANCE_MS / config.FRAME_MS))

        self._stream = None
        self._worker = None
        self._running = threading.Event()
        self._paused = threading.Event()  # set == paused

        # Raised (set True) once when a chunk had to be dropped due to overload.
        self.dropped = threading.Event()

    # -- lifecycle ---------------------------------------------------------

    def start(self):
        """Open the microphone stream and start the VAD worker thread."""
        self._running.set()
        self._stream = sd.InputStream(
            samplerate=config.SAMPLE_RATE,
            channels=1,
            dtype="int16",
            blocksize=self._frame_len,          # deliver exactly one VAD frame
            device=config.MIC_DEVICE,
            callback=self._audio_callback,
        )
        self._stream.start()
        self._worker = threading.Thread(
            target=self._process_loop, name="vad-worker", daemon=True
        )
        self._worker.start()

    def stop(self):
        """Stop capture and the worker thread cleanly."""
        self._running.clear()
        if self._stream is not None:
            try:
                self._stream.stop()
                self._stream.close()
            except Exception:
                pass
            self._stream = None
        if self._worker is not None:
            self._worker.join(timeout=2.0)
            self._worker = None

    def pause(self):
        """Stop emitting utterances (speaker break). Audio is discarded."""
        self._paused.set()

    def resume(self):
        self._paused.clear()

    @property
    def is_paused(self) -> bool:
        return self._paused.is_set()

    # -- audio callback (realtime thread — keep it trivial) ----------------

    def _audio_callback(self, indata, frames, time_info, status):  # noqa: D401
        # ``indata`` is an (frames, 1) int16 array. Copy the bytes out fast.
        if status:
            # Overflows etc. are non-fatal; ignore to stay realtime-safe.
            pass
        frame_bytes = bytes(indata[:, 0].tobytes())
        with self._raw_lock:
            self._raw.append(frame_bytes)

    # -- worker thread -----------------------------------------------------

    def _pop_frame(self):
        with self._raw_lock:
            if self._raw:
                return self._raw.popleft()
        return None

    def _process_loop(self):
        state = _IDLE
        voiced = []                 # list[bytes] frames of the current utterance
        num_silence = 0
        num_start_speech = 0        # consecutive speech frames seen while idle

        while self._running.is_set():
            frame = self._pop_frame()
            if frame is None:
                # Nothing buffered yet; sleep a hair so we don't busy-spin.
                threading.Event().wait(0.005)
                continue

            # While paused we keep draining the mic but throw everything away,
            # and hold the state machine idle.
            if self._paused.is_set():
                state = _IDLE
                voiced = []
                num_silence = 0
                num_start_speech = 0
                self._pre_roll.clear()
                continue

            # webrtcvad needs exactly one frame of the right length.
            if len(frame) != self._frame_len * 2:  # 2 bytes per int16 sample
                continue

            is_speech = self._vad.is_speech(frame, config.SAMPLE_RATE)

            if state == _IDLE:
                # Always keep the rolling pre-roll so the utterance's first word
                # isn't clipped once we do open.
                self._pre_roll.append(frame)
                if is_speech:
                    num_start_speech += 1
                    # Require SPEECH_START_FRAMES consecutive speech frames so a
                    # single click/cough can't open an utterance.
                    if num_start_speech >= config.SPEECH_START_FRAMES:
                        voiced = list(self._pre_roll)   # includes pre-roll + starts
                        num_silence = 0
                        num_start_speech = 0
                        state = _RECORDING
                else:
                    num_start_speech = 0
            else:  # _RECORDING
                voiced.append(frame)
                if is_speech:
                    num_silence = 0
                else:
                    num_silence += 1

                too_long = len(voiced) >= self._max_frames
                ended = num_silence >= self._silence_end_frames

                if ended or too_long:
                    self._emit(voiced, trailing_silence=num_silence)
                    state = _IDLE
                    voiced = []
                    num_silence = 0
                    self._pre_roll.clear()

    def _emit(self, frames, trailing_silence=0):
        # Drop the trailing pure-silence frames we accumulated before closing.
        if trailing_silence > 0:
            keep = len(frames) - trailing_silence
            if keep > 0:
                frames = frames[:keep]

        if len(frames) < self._min_frames:
            return  # too short — a cough, click, or PA pop.

        pcm = b"".join(frames)
        audio = np.frombuffer(pcm, dtype=np.int16).astype(np.float32) / 32768.0

        if getattr(config, "DEBUG_AUDIO", False):
            secs = len(audio) / config.SAMPLE_RATE
            peak = float(np.max(np.abs(audio))) if len(audio) else 0.0
            print(f"[audio] captured {secs:.1f}s  peak={peak:.2f}", flush=True)

        # Drop-oldest back-pressure: never let the queue block the worker.
        try:
            self.out_queue.put_nowait(audio)
        except queue.Full:
            try:
                self.out_queue.get_nowait()      # discard the oldest pending
            except queue.Empty:
                pass
            try:
                self.out_queue.put_nowait(audio)
            except queue.Full:
                pass
            self.dropped.set()
