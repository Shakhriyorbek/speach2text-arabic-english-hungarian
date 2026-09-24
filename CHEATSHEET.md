# 🕌 Khutbah Subtitles — Operator Cheat-Sheet

*Print this and keep it next to the projector laptop.*

---

## ▶️ Every Friday — 4 steps

1. **Plug in the microphone.**
2. **Connect the projector/TV.** Press **`⊞ Windows` + `P`** → choose **Duplicate**.
3. **Double-click `START.bat`.** A window ticks off six steps while it rents
   the GPU, then the black fullscreen subtitle window appears.
   **Allow 4–6 minutes** — do this before the congregation arrives.
   *(No GPU set up? Use `run.bat` instead; ~15 seconds, laptop only.)*
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
| **Subtitles fall further and further behind** | In **`config.py`** lower the size for that part — `MODEL_SIZE_PART2 = "base"` → `"tiny"` (English) or `MODEL_SIZE_PART1 = "small"` → `"base"` (Arabic). Save, restart. |
| **Arabic (Part 1) not accurate enough** | In **`config.py`** raise `MODEL_SIZE_PART1 = "small"` → `"medium"` (much slower — may lag). Save, restart. |
| **Text too small on the projector** | Press **`+`** a few times. |
| **Nothing shows on the projector** | `⊞ Windows` + `P` → **Duplicate**. Move the window with the mouse if needed. |
| **It froze / acting weird** | Press **Esc**, then start it again the same way you did the first time. |
| **`START.bat` says it did not work** | Press **"Folytatás GPU nélkül / Continue without the GPU"**. The subtitles still work, from this laptop. Do not debug now. |
| **Subtitles are suddenly worse mid-khutbah** | The GPU dropped out and the laptop took over — the designed fallback, not a fault. Carry on. |
| **Worried you are still paying for a GPU** | Double-click **`STOP.bat`**. Safe any time; it says plainly whether anything is rented. |
| **Cloud mode: "⚠ Felhő hiba" on screen** | Internet is down or the Azure key/quota has a problem. Check the console window. **Quick fallback:** set `BACKEND = "local"` in `config.py`, restart — works offline. |

---

## 💸 When you finish

Just **close the subtitle window** (or press `Esc`). The rented GPU is given
back by itself and billing stops — you will see *"GPU released"*.

If the laptop crashed or was closed without stopping, run **`STOP.bat`**. Even
if you forget entirely, the rented machine shuts itself down after a few hours.

---

## ℹ️ Good to know

- **`run.bat` runs fully offline** — no internet needed during the khutbah.
  **`START.bat` uses the internet** for much better Arabic, and falls back to
  the offline models by itself whenever it can't.
- The subtitles are a **live aid to understanding**, not an official translation. **Quran translations shown are approximate**, not authoritative.
- First-time setup on a new laptop: run **`install.bat`** once (needs internet). After that, only `START.bat` (or `run.bat`) is needed.

---

*Questions or improvements: https://github.com/Shakhriyorbek/speach2text-arabic-english-hungarian*
