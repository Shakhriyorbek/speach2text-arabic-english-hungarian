# Khutbah Live Subtitles — Arabic / English → Hungarian (offline)

Live subtitles for the Friday khutbah. A stage microphone feeds a laptop; the
laptop shows large Hungarian subtitles on a projector or TV. It runs **fully
offline** and uses only free, open-source software — nothing to pay for, no
internet needed during the sermon.

- **Part 1** of the khutbah (all Arabic) → **Mode 1** (press **F1**).
- **Part 2** (English talk with Arabic Quran/hadith quotes) → **Mode 2** (press **F2**).

How it works internally: the speech recognizer (Whisper) is run in
*translate* mode, which turns any spoken language into **English** text; a
second offline model then translates that English into **Hungarian**.

---

## One-time setup (needs internet, do this once at home)

1. Install **Python 3** from <https://www.python.org/downloads/> — during
   install, tick **"Add Python to PATH"**.
2. Double-click **`install.bat`**. It creates an isolated environment, downloads
   the models (~700 MB — be patient), builds the translator, and runs a quick
   self-test. When it says **DONE**, you are ready.

You only ever do this once (unless you move to a new laptop or change the model
size).

---

## Every Friday (no internet needed)

1. Plug in the stage microphone.
2. Connect the projector/TV. Press **Windows key + P** and choose **Duplicate**
   so the projector mirrors the laptop screen.
3. Double-click **`run.bat`**. Wait for "Ready" (models take 10–30 seconds to
   load on a weak laptop). The subtitle window opens fullscreen.
4. **Press F1** at the start of Part 1 (Arabic). **Press F2** for Part 2.

### Keys in the subtitle window

| Key | Action |
|-----|--------|
| **F1** | Mode 1 — Part 1, Arabic |
| **F2** | Mode 2 — Part 2, auto (English + Arabic quotes) |
| **F11** | toggle fullscreen |
| **+** / **−** | bigger / smaller text |
| **P** | pause / resume (e.g. during a break) |
| **Esc** | quit |

The top-right badge shows the current mode (`1: ARAB` or `2: AUTO`) and `⏸` when
paused, so the operator can always confirm the state.

---

## Tuning for a weak laptop

Everything adjustable lives in **`config.py`**. The knobs that matter most are
the two model sizes — chosen separately per khutbah part, because Arabic needs
a bigger model than English for the same quality:

```python
MODEL_SIZE_PART1 = "small"   # Arabic khutbah (F1) — accuracy priority
MODEL_SIZE_PART2 = "base"    # English talk + quotes (F2) — speed priority
```

Ladder, slowest→fastest: `medium` → `small` → `base` → `tiny`.

- If the subtitles drift **further and further** behind the speaker (growing
  without end, not just a few seconds — that is normal), lower the size for that
  part (e.g. `small` → `base`), save, restart with `run.bat`.
- If **Arabic (Part 1) is inaccurate**, raise `MODEL_SIZE_PART1` toward `small`
  or `medium` — but note `medium` is very slow on a weak CPU and will likely lag.
  On a weak laptop, `small` is realistically the accuracy ceiling for live use;
  for better Arabic you need more compute (see the project notes / issues).

**Choosing the microphone:** if the default mic is wrong, open a terminal in this
folder and run `venv\Scripts\python -m sounddevice` to list devices, then set the
number in `config.py`:

```python
MIC_DEVICE = 3   # the index shown for your microphone
```

---

## Cloud mode (optional) — much better Arabic

The offline mode is free and private, but a weak laptop's CPU caps how good the
**Arabic** can get: the models that handle Arabic well (`medium`, `large`) are
far too slow to run live on it. If the mosque has **reliable wifi**, cloud mode
solves this.

**What changes:** Azure translates the speech **straight into Hungarian** — no
English middle step at all. Better Arabic, lower delay, and text appears *while*
the speaker is still talking (interim results). Your laptop barely works at all.

**Trade-offs:** needs internet during the khutbah, and the audio is sent to
Microsoft. (A khutbah is public speech, but it's your call to make.)

### Setting it up

1. **Create a free Azure Speech resource.** In the Azure portal create a
   *Speech service* resource and pick the **free (F0)** tier. Note its **key**
   and **region** (e.g. `westeurope`). The free tier includes several audio
   hours per month — typically enough for a weekly khutbah. *Check current
   pricing/limits yourself; they change.*

2. **Install the extra dependency:**
   ```
   venv\Scripts\pip install -r requirements-azure.txt
   ```

3. **Put your key in environment variables.** Never type it into a project file
   and never share it. In PowerShell, to set it permanently for your user:
   ```powershell
   setx AZURE_SPEECH_KEY "your-key-here"
   setx AZURE_SPEECH_REGION "westeurope"
   ```
   Then **close and reopen** the terminal (or log out/in) so the values apply.

4. **Switch the backend** in `config.py`:
   ```python
   BACKEND = "azure"     # was "local"
   ```

5. Run `run.bat` as usual. F1/F2 work exactly the same.

To go back to fully offline, set `BACKEND = "local"` again. Both modes stay
installed, so you can fall back instantly if the internet fails on the day —
worth testing that fallback once before relying on cloud mode.

### Cloud settings in `config.py`

```python
AZURE_LANG_PART1  = "ar-SA"                # Part 1 is entirely Arabic
AZURE_LANGS_PART2 = ["en-US", "ar-SA"]     # Part 2: English talk + Arabic quotes
AZURE_SHOW_INTERIM = True                  # live-updating text while speaking
```

---

## Test it without a microphone

Record a short clip (Windows **Voice Recorder**, saved/converted to `.wav`) and:

```
venv\Scripts\python -m subtitles.test_pipeline myclip.wav            (Arabic — Part 1)
venv\Scripts\python -m subtitles.test_pipeline myclip.wav --mode part2
```

It prints the recognized English (`EN:`) and the Hungarian (`HU:`) plus timings.

---

## Known limitations (please read)

- **A delay of about 3–8 seconds behind the speaker is normal** on a weak
  laptop. The system waits for a pause, then transcribes and translates a whole
  sentence at once. If it can't keep up, it drops the oldest waiting audio (a
  `…` appears in the badge) rather than falling ever further behind.
- **Quranic recitation** (melodic *tajwīd*) is harder for the recognizer than
  ordinary speech, and its translation shown on screen is an **approximate,
  spoken-word rendering — NOT an authoritative Quran translation.** Treat the
  subtitles as a live aid to understanding, not as an official translation.
- Machine translation makes mistakes. It is meant to help Hungarian speakers
  follow along, not to replace a human translator for anything that must be
  exact.

---

## Contributing

Contributions are very welcome — this is a volunteer, zero-budget tool for a
mosque, so improvements that keep it **simple, free, and fully offline** are
especially valued.

**How it fits together** (`subtitles/`):

| File | Role |
|------|------|
| `audio.py` | microphone capture + voice-activity chunking |
| `asr.py` | faster-whisper: speech → English (`task="translate"`) |
| `mt.py` | CTranslate2: English → Hungarian |
| `ui.py` | fullscreen Tkinter subtitle window |
| `app.py` | wires the threads/queues together |
| `config.py` | every tunable, in one place — start here |

**Dev setup:** run `install.bat` once (see [setup](#one-time-setup-needs-internet-do-this-once-at-home)), then hack away.

**Test your change without a stage/mic:** run the offline harness on any WAV —
`venv\Scripts\python -m subtitles.test_pipeline clip.wav` (add `--mode part2`
for auto-detect). For a live check, just `run.bat` and speak.

**Good first contributions:**
- Verify and tune **Arabic (Part 1)** quality on real khutbah audio across model sizes.
- Make microphone selection friendlier (a picker instead of editing `config.py`).
- Add other source or target languages (the pipeline is language-agnostic — `mt.py` is the only Hungarian-specific piece).
- Improve robustness to room echo / PA feedback in the VAD.

**Pull requests:**
- Keep the volunteer-facing flow to "double-click `run.bat`, press F1/F2" — don't add steps a non-technical operator must perform.
- Put new options in `config.py` with a short comment, rather than hard-coding.
- Don't commit `venv/`, downloaded models, or `__pycache__` (already in `.gitignore`).
- Describe what you tested (which WAV / live speech, which `MODEL_SIZE`).

Not sure where to start? Open an issue describing the laptop, mic, and what you'd
like to improve.
