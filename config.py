"""
Central configuration for the live khutbah subtitle system.

Everything a volunteer might need to tune lives HERE, in one file, so that
no one has to touch the code. The most important knobs are the two model
sizes below: they trade accuracy against delay.
"""

# ---------------------------------------------------------------------------
# Which engine to use
# ---------------------------------------------------------------------------

# "local" -> fully offline: Whisper -> English -> opus-mt -> Hungarian.
#            Free, private, no internet. Arabic quality is capped by the CPU.
# "azure" -> cloud: Azure translates speech straight to Hungarian (no English
#            pivot). Much better Arabic and much lower delay, but needs
#            reliable internet plus AZURE_SPEECH_KEY / AZURE_SPEECH_REGION
#            environment variables. See the README "Cloud mode" section.
BACKEND = "local"

# --- cloud mode settings (ignored when BACKEND = "local") ---
AZURE_TARGET_LANG = "hu"                    # translate into Hungarian
AZURE_LANG_PART1 = "ar-SA"                  # Part 1 is entirely Arabic
AZURE_LANGS_PART2 = ["en-US", "ar-SA"]      # Part 2: English talk + Arabic quotes
AZURE_SHOW_INTERIM = True                   # show text while still being spoken
                                            # (big perceived-speed win; set False
                                            # if the updating text is distracting)


# ---------------------------------------------------------------------------
# Speech recognition (faster-whisper) — used when BACKEND = "local"
# ---------------------------------------------------------------------------

# Whisper model size, chosen SEPARATELY per khutbah part, because Arabic needs
# a much bigger model than English for the same quality. Ladder, slowest→fastest:
#   "medium" -> best Arabic, ~1.5 GB, SLOW on a weak CPU (may lag)
#   "small"  -> decent Arabic, ~1 GB, ~1x realtime on the dev laptop
#   "base"   -> weak Arabic but good English; ~3x realtime
#   "tiny"   -> fastest (~6x); weakest accuracy
# Measured (dev laptop, English): small=1.08x, base=3.17x, tiny=6.02x realtime.
#
# Part 1 is all Arabic -> favour accuracy. Part 2 is mostly English -> favour
# speed. Start here; raise PART1 toward "medium" if Arabic is inaccurate, lower
# it if it lags. If both are set to the same size, only one model is loaded.
MODEL_SIZE_PART1 = "small"   # Arabic khutbah (F1) — accuracy priority
MODEL_SIZE_PART2 = "base"    # English talk + quotes (F2) — speed priority

# CPU threads faster-whisper may use. 0 = use every core (os.cpu_count()).
CPU_THREADS = 0

# Quantization for the Whisper model. "int8" is the light, fast default and
# is what the installer downloads/uses. Leave as-is unless you know better.
WHISPER_COMPUTE_TYPE = "int8"

# Anti-hallucination decoding guards. These matter most for Arabic: when the
# model is out of its depth it degenerates into "word word word..." loops that
# are both wrong AND slow. Raising REPETITION_PENALTY or lowering
# COMPRESSION_RATIO_MAX makes the filter stricter (drops more suspected garbage).
REPETITION_PENALTY = 1.15    # >1 discourages repeating tokens while decoding
NO_REPEAT_NGRAM = 3          # forbid repeating any 3-gram (kills tight loops)
COMPRESSION_RATIO_MAX = 2.4  # drop a segment more repetitive than this
LOGPROB_MIN = -1.0           # drop a segment the model is very unsure about

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
DEBUG_AUDIO = False          # True prints "[audio] captured Ns" to the console
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
