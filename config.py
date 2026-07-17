"""
Central configuration for the live khutbah subtitle system.

Everything a volunteer might need to tune lives HERE, in one file, so that
no one has to touch the code. The single most important knob is MODEL_SIZE:
if the subtitles fall further and further behind the speaker, lower it.
"""

# ---------------------------------------------------------------------------
# Speech recognition (faster-whisper)
# ---------------------------------------------------------------------------

# THE tuning knob. If the laptop lags, step DOWN this ladder:
#   "small"  -> best quality, needs ~1 GB RAM, slowest (~1x realtime here)
#   "base"   -> ~3x faster than small, good compromise      (current default)
#   "tiny"   -> ~6x faster; snappiest but weakest Arabic accuracy
# Measured on the dev laptop: small=1.08x, base=3.17x, tiny=6.02x realtime.
# Higher = lower delay. Drop to "tiny" if base still lags on the mosque laptop;
# go back to "small" only if Arabic (Part 1) accuracy is not good enough.
MODEL_SIZE = "base"

# CPU threads faster-whisper may use. 0 = use every core (os.cpu_count()).
CPU_THREADS = 0

# Quantization for the Whisper model. "int8" is the light, fast default and
# is what the installer downloads/uses. Leave as-is unless you know better.
WHISPER_COMPUTE_TYPE = "int8"


# ---------------------------------------------------------------------------
# Microphone / audio capture
# ---------------------------------------------------------------------------

# None = the Windows default input device. To use a specific mic, run
#   python -m sounddevice
# to list devices, then put the device's index number here (an int).
MIC_DEVICE = None

SAMPLE_RATE = 16000          # Whisper and webrtcvad both require 16 kHz.
FRAME_MS = 30                # webrtcvad frame length (10/20/30 ms allowed).
                             # 30 ms @ 16 kHz = 480 samples per frame.


# ---------------------------------------------------------------------------
# Voice-activity detection (turns continuous audio into utterances)
# ---------------------------------------------------------------------------

VAD_AGGRESSIVENESS = 2       # 0-3. Higher = more aggressively treats sound as
                             # non-speech. Raise to 3 if room echo / PA hum is
                             # falsely triggering speech.
SPEECH_START_FRAMES = 3      # consecutive speech frames needed to OPEN an
                             # utterance (~90 ms). Filters out clicks/coughs.
SILENCE_END_MS = 450         # this much continuous silence CLOSES an utterance.
                             # Lower = subtitles appear sooner after a pause, but
                             # too low splits mid-sentence. ~400-500 is a good.
MAX_UTTERANCE_S = 5.0        # hard cap: force-cut long sentences so latency can
                             # never grow without bound. This is the MAIN delay
                             # knob for a continuous speaker — subtitles refresh
                             # at most this often. Lower = snappier but chops
                             # long sentences (less context for Whisper). 4-6.
PRE_ROLL_MS = 240            # audio kept from BEFORE speech onset, so the first
                             # word is never clipped.
MIN_UTTERANCE_MS = 400       # discard utterances shorter than this (blips).


# ---------------------------------------------------------------------------
# Pipeline back-pressure (keeps a weak CPU from falling minutes behind)
# ---------------------------------------------------------------------------

ASR_QUEUE_MAX = 4            # max utterances waiting for transcription.
                             # On overflow the OLDEST waiting chunk is dropped
                             # and a "…" marker is shown, instead of lagging.
NO_SPEECH_MAX = 0.6          # drop transcribed segments whose no_speech_prob
                             # exceeds this (silence / noise misfires).


# ---------------------------------------------------------------------------
# Machine translation (English -> Hungarian, CTranslate2 Marian model)
# ---------------------------------------------------------------------------

MT_MODEL_DIR = "models/en-hu-ct2"   # produced by the installer.
MT_BEAM_SIZE = 2                    # 1 = fastest, 2 = slightly better quality.


# ---------------------------------------------------------------------------
# Display / subtitle window
# ---------------------------------------------------------------------------

SHOW_ENGLISH = False         # True also shows the intermediate English line
                             # (useful for debugging; off for the congregation).
DEBUG_AUDIO = True           # True prints "[audio] captured Ns" to the console
                             # each time speech is detected — a mic/VAD check.
                             # Set to False for real use.

FONT_FAMILY = "Segoe UI"     # renders Hungarian ő / ű correctly on Windows.
FONT_SIZE = 44               # starting font size; adjustable live with + / -.
MAX_LINES = 3                # how many recent subtitle lines to keep on screen.

BG = "black"                 # background colour.
FG_NEW = "white"             # newest line colour.
FG_OLD = "#888888"           # older lines colour (dimmed).
FG_BADGE = "#44aa44"         # mode badge colour (top-right corner).

START_FULLSCREEN = True      # start in fullscreen (F11 toggles at runtime).
