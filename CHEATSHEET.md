# 🕌 Khutbah Subtitles — Operator Cheat-Sheet

*Print this and keep it next to the projector laptop.*

---

## ▶️ Every Friday — 4 steps

1. **Plug in the microphone.**
2. **Connect the projector/TV.** Press **`⊞ Windows` + `P`** → choose **Duplicate**.
3. **Double-click `run.bat`.** Wait ~15 seconds for a black fullscreen window.
4. When the khutbah starts, press the mode key:
   - **`F1`** = **Part 1** (Arabic only)
   - **`F2`** = **Part 2** (English talk + Arabic quotes)

The **top-right corner** shows the current mode: `1: ARAB` or `2: AUTO`.

---

## ⌨️ Keys (press inside the subtitle window)

| Key | What it does |
|-----|--------------|
| **F1** | Part 1 — Arabic |
| **F2** | Part 2 — English + Arabic quotes |
| **F11** | Fullscreen on / off |
| **+ / −** | Bigger / smaller text |
| **P** | Pause / resume (e.g. during a break) |
| **Esc** | Quit |

> ⏱️ **The subtitle appears a couple of seconds *after* the speaker pauses** — this is normal. It waits for a natural pause, then shows the whole sentence.

---

## 🔧 If something's wrong

| Problem | Fix |
|---------|-----|
| **No subtitles when speaking** | Is the right mode on (F1/F2)? Is the mic plugged in and unmuted? Speak clearly, then pause. |
| **Wrong microphone used** | Open a terminal in the folder, run `venv\Scripts\python -m sounddevice`, note your mic's number, then set `MIC_DEVICE = <number>` in **`config.py`** and restart. |
| **Subtitles fall further and further behind** | In **`config.py`** change `MODEL_SIZE = "base"` → `"tiny"`. Save, restart. |
| **Arabic (Part 1) not accurate enough** | In **`config.py`** change `MODEL_SIZE = "base"` → `"small"` (slower but more accurate). Save, restart. |
| **Text too small on the projector** | Press **`+`** a few times. |
| **Nothing shows on the projector** | `⊞ Windows` + `P` → **Duplicate**. Move the window with the mouse if needed. |
| **It froze / acting weird** | Press **Esc**, then double-click `run.bat` again. |

---

## ℹ️ Good to know

- **Runs fully offline** — no internet needed during the khutbah.
- The subtitles are a **live aid to understanding**, not an official translation. **Quran translations shown are approximate**, not authoritative.
- First-time setup on a new laptop: run **`install.bat`** once (needs internet). After that, only `run.bat` is needed.

---

*Questions or improvements: https://github.com/Shakhriyorbek/speach2text-arabic-english-hungarian*
