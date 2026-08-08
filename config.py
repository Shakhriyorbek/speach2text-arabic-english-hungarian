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

# Within BACKEND = "local", WHERE the speech recognition runs:
#   "cpu"    -> on this laptop (fully offline, capped at MODEL_SIZE_PART*).
#   "remote" -> on a GPU box running server/whisper_server.py, which can afford
#               "large-v3". Measured on a Tesla T4: ~30x realtime, and it kept
#               meaning that local "small"/"medium" lost. Needs internet, plus
#               WHISPER_SERVER_TOKEN in the environment. Falls back to the local
#               model automatically if the server cannot be reached.
# The Hungarian translation always stays on this laptop either way.
ASR_LOCATION = "remote"

# --- remote ASR settings (ignored when ASR_LOCATION = "cpu") ---
# Where the GPU box is reachable, no trailing slash. Two ways to point at it:
#   via SSH tunnel (recommended — nothing exposed to the internet):
#       ssh -i <key> -N -L 8756:127.0.0.1:8756 hpcadmin@<vm-ip>
#       then use  http://127.0.0.1:8756  below
#   direct: use  http://<vm-ip>:8756  and open 8756 in the Azure NSG to your
#       IP only. Never leave it open to the whole internet.
REMOTE_ASR_URL = "http://127.0.0.1:8756"
REMOTE_ASR_TIMEOUT = 10.0                   # seconds; must be well under the
                                            # time the congregation would notice
                                            # a stall. On timeout we fall back.
REMOTE_ASR_FAILURES_BEFORE_FALLBACK = 2     # consecutive failures before giving
                                            # up on the server for a while
REMOTE_ASR_RETRY_EVERY = 20                 # while fallen back, re-probe the
                                            # server every Nth utterance

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
# Measured (i7-1165G7, Arabic khutbah): medium=0.89x realtime — BELOW realtime,
# so the queue backs up and starts dropping audio. In a live test it produced
# roughly a THIRD of the subtitle coverage of "small" (1 line/33s vs 1 line/10s),
# i.e. bigger is not better once you fall under 1x. On laptops of that class
# "small" is the practical ceiling for Part 1; for real gains use cloud mode.
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


# ---------------------------------------------------------------------------
# Microphone / audio capture
# ---------------------------------------------------------------------------

# None = the Windows default input device. To use a specific mic, run
#   python -m sounddevice
# to list devices, then put the device's index number here (an int).
MIC_DEVICE = 1               # 1 = "Microphone Array (Intel Smart Sound)", the
                             # built-in mic. Pinned rather than left as None so
                             # that a Bluetooth headset connecting mid-sermon
                             # cannot silently become the Windows default and
                             # take over the input. Re-check the index with
                             # "python -m sounddevice" on a different machine.

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

# How the Arabic reaches Hungarian:
#   "pivot"  -> Whisper task="translate" gives ENGLISH, then opus-mt en->hu.
#               Fast (~0.1s/line) but every hop loses meaning. Measured failure:
#               "Satan has despaired of being worshipped" became Hungarian
#               "Satan MUST be worshipped" — an inversion, on a projector.
#   "direct" -> Whisper task="transcribe" gives ARABIC, then NLLB ar->hu with no
#               English in between, so that inversion cannot happen. Slower
#               (~1.0s/line measured on the dev laptop) and a bigger model
#               (~600 MB vs 77 MB). NLLB tends to drop qualifiers, so it is a
#               trade rather than a clean win — but it does not invert meaning.
# Whisper CANNOT translate to Hungarian itself; it only ever emits English in
# translate mode. That is why "direct" changes the ASR task as well.
#
# DEFAULT IS "direct". Measured on a real khutbah recording, same audio and same
# model: direct produced 6 subtitle lines where pivot produced 1, because plain
# transcription is an easier job for Whisper than transcribe-and-translate, so
# far more output survives the quality guards.
#
# NOTE: direct is NOT faster. It measured ~13% SLOWER overall (NLLB ~1.0s/line
# vs opus-mt ~0.1s/line). Whisper is 75-90% of the time either way; the delay
# you feel comes from MAX_UTTERANCE_S below, not from the translation stage.
# Choose "direct" for accuracy, not for speed.
TRANSLATION_PATH = "direct"

# --- direct-path settings (ignored when TRANSLATION_PATH = "pivot") ---
NLLB_MODEL_DIR = "models/nllb-600m-ct2"   # produced by the installer.
NLLB_TARGET_LANG = "hun_Latn"             # NLLB code for Hungarian.
NLLB_BEAM_SIZE = 2
# Whisper language code -> NLLB language token. Part 2 auto-detects, so English
# needs an entry too; anything unmapped falls back to Arabic.
NLLB_LANG_MAP = {"ar": "arb_Arab", "en": "eng_Latn"}

# Where translation runs. Independent of ASR_LOCATION — you can transcribe on
# the GPU and translate here, or both remotely.
#   "cpu"    - NLLB-600M on this laptop. Fully offline. The largest model that
#              fits the latency budget on a laptop CPU, and measurably not good
#              enough for religious Arabic: on flawless transcription it turned
#              "we seek His forgiveness" into "we forgive Him".
#   "remote" - NLLB-1.3B on the GPU box, which is already resident for Whisper
#              and otherwise idle. Falls back to the local 600M automatically,
#              so an outage costs accuracy rather than the whole screen.
MT_LOCATION = "remote"

REMOTE_MT_URL = "http://127.0.0.1:8756"     # same server/tunnel as remote ASR
REMOTE_MT_TIMEOUT = 8.0                     # a line is ~0.2s on a T4; this is
                                            # a stall guard, not a target
REMOTE_MT_FAILURES_BEFORE_FALLBACK = 2
REMOTE_MT_RETRY_EVERY = 20

# --- Whisper vocabulary hint (Part 1 / Arabic only) ---
# Whisper accepts a short "initial_prompt" that biases decoding towards a
# vocabulary. Khutbah Arabic contains words that are rare in Whisper's training
# mix and that it mishears the SAME way every time: in a live test "المجوسي"
# (the Zoroastrian) came out as "المجلسي" three times running, which then
# translated as "the councillor" and "the table". A one-letter ASR error, but it
# erased the person the story was about.
#
# Keep this SHORT. The prompt is prepended to every window, so a long one costs
# latency on every utterance and, worse, Whisper will sometimes emit fragments
# of the prompt itself as if they had been spoken. Set to "" to disable.
# DISABLED after measurement — do not re-enable without re-running the A/B.
# The wordlist below was tried against a real khutbah recording and made things
# WORSE, in two ways that both reach the screen:
#   1. Whisper transcribed the prompt itself as if it had been spoken, emitting
#      "الحمد لله نحمده ونستعينه، رضي الله عنه، عمر بن الخطاب، المجوسي، الركعة،
#      السراج،" as a subtitle line.
#   2. It pushed decoding towards captioned-video boilerplate: "المترجم للقناة"
#      and "ترجمة نانسي قنقر" appeared repeatedly and REPLACED real speech —
#      "احذروه على دينكم أيها الناس" was lost and became a translator credit.
# It did help in places (it recovered "وإن الزمان قد استدار كهيئة يوم خلق" and
# completed "فيحرم ما حل الله"), but losing real khutbah content and printing
# the prompt on a projector is not a trade worth making.
# The underlying problem is real — "المجوسي" was misheard as "المجلسي" three
# times in one sermon — but initial_prompt is the wrong tool for it.
WHISPER_INITIAL_PROMPT_AR = ""

_TRIED_AND_REJECTED_PROMPT = (
    "خطبة الجمعة: الحمد لله نحمده ونستعينه ونستغفره، "
    "وأشهد أن لا إله إلا الله وحده لا شريك له، "
    "صلى الله عليه وسلم، رضي الله عنه، عمر بن الخطاب، "
    "المجوسي، الركعة، السراج، الرحى، القمح."
)


# ---------------------------------------------------------------------------
# Display / subtitle window
# ---------------------------------------------------------------------------

SHOW_ENGLISH = False         # True also shows the source line (Arabic on the
                             # direct path) — debugging only, off for the
                             # congregation.
DEBUG_AUDIO = False          # True prints "[audio] captured Ns peak=" per
                             # utterance — a mic/VAD check. False for real use.

FONT_FAMILY = "Segoe UI"     # renders Hungarian ő / ű correctly on Windows.
FONT_SIZE = 44               # starting font size; adjustable live with + / -.
MAX_LINES = 3                # how many recent subtitle lines to keep on screen.

BG = "black"                 # background colour.
FG_NEW = "white"             # newest line colour.
FG_OLD = "#888888"           # older lines colour (dimmed).
FG_BADGE = "#44aa44"         # mode badge colour (top-right corner).

START_FULLSCREEN = True      # start in fullscreen (F11 toggles at runtime).
