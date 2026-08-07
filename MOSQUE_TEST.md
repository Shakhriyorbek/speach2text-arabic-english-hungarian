# Testing at the mosque — step by step

For a live demonstration. **Use offline mode.** It needs no internet, no cloud
account and nothing switched on beforehand — which is exactly what you want when
people are watching. The GPU option is at the bottom, but it has more that can go
wrong on the day.

---

## Before you leave home

1. **Charge the laptop** and bring the charger. Transcription keeps the CPU busy.
2. **Bring the microphone you will actually use**, and its cable/adapter.
3. **Test once at home** exactly as below. If it works at home it will work there.
4. Confirm `config.py` is on the safe defaults (this is how it ships):
   ```python
   BACKEND          = "local"
   ASR_LOCATION     = "cpu"
   MODEL_SIZE_PART1 = "small"
   MIC_DEVICE       = None
   ```

---

## At the mosque — 5 steps

1. **Plug in the microphone.** Then make it the default input:
   Windows **Settings → System → Sound → Input** → select your mic.
   *(This must happen BEFORE starting the program — it grabs whichever device is
   default at the moment it launches.)*
2. **Connect the projector/TV**, press **`⊞ Win` + `P`**, choose **Duplicate**.
3. **Double-click `run.bat`.** Wait ~5 seconds for the black fullscreen window.
4. **Press `F1`** — the badge top-right must read `1: ARAB`.
5. **Speak into the mic**, then **pause**. The subtitle appears a few seconds
   after the pause, not while you talk. That wait is normal and expected.

To finish: press **`Esc`**.

---

## Check the microphone level first (30 seconds, worth it)

Bad audio ruins the result more than any setting. In `config.py` set:

```python
DEBUG_AUDIO = True
```

Run `run.bat`, speak, and watch the console window behind the subtitles:

```
[audio] captured 3.2s  peak=0.68
```

| peak | meaning |
|---|---|
| **0.3 – 0.8** | good — leave it alone |
| below 0.1 | too quiet — raise mic input volume, or move it closer |
| **1.00** | clipping — distorted, lower the input volume in Windows Sound settings |

Set `DEBUG_AUDIO = False` again before the real demonstration so the console
stays quiet.

---

## What to honestly expect

Tested on a real Arabic khutbah recording, so these are measured, not guesses:

- **A subtitle roughly every 10 seconds.** It waits for a pause, then translates a
  whole sentence at once.
- **Not every sentence appears.** Lines the system is unsure about are dropped on
  purpose — better to show nothing than to show something wrong.
- **Clear, formulaic Arabic works best.** The opening formulas came through well.
  Fast or melodic Quranic recitation is much harder and often produces nothing.
- **Some lines will be wrong.** This is a machine aid, not a translator. Say so
  when demonstrating — it sets the right expectation and protects you if a line
  comes out odd.

Suggested framing: *"It helps Hungarian speakers follow along. It is not an
official translation, and the Quran translations it shows are approximate."*

---

## If something goes wrong

| Problem | Fix |
|---|---|
| No subtitles at all | Did you press **F1**? Is the mic plugged in, unmuted, and set as Windows default input? Restart `run.bat` after changing the mic. |
| Wrong microphone | Set it as default in Windows Sound, then restart `run.bat`. |
| Subtitles fall further behind | `config.py`: `MODEL_SIZE_PART1 = "base"`, save, restart. |
| Text too small | Press **`+`** a few times. |
| Nothing on the projector | `⊞ Win` + `P` → **Duplicate**. |
| Frozen / odd | **`Esc`**, then `run.bat` again. |

**Fallback if it fails entirely:** press `Esc` and carry on without it. Do not
debug in front of an audience — note what happened and look at it afterwards.

---

## Optional: the GPU version (better Arabic, more setup)

Noticeably better Arabic — on the same recording it caught proper names and kept
a negation that the offline model reversed. But it needs **reliable internet at
the mosque** plus four things prepared in advance, so do not attempt it live
unless you have rehearsed it end to end.

1. **Start the VM** and wait ~2 minutes:
   ```
   az vm start -g GLOSTER-GPT-HPC-PLAYGROUND-ENV-SHAKH -n ggpt-hpc-shakh-vm
   ```
2. **Check the GPU is alive** — this breaks after kernel upgrades:
   ```
   ssh -i ~/.ssh/hpc-playground-shakh hpcadmin@<vm-ip> nvidia-smi
   ```
   No Tesla T4 in the output? See `server/README.md` for the driver fix.
3. **Start the server** (token must match the laptop's):
   ```
   ./start_whisper.sh <your-token>
   ```
4. **On the laptop**, set `ASR_LOCATION = "remote"` and `REMOTE_ASR_URL` to the
   VM, with `WHISPER_SERVER_TOKEN` in the environment. Then `run.bat` as usual.

If the server is unreachable the program says so and **automatically uses the
offline model instead** — F1/F2 keep working, so a network failure degrades
quality rather than stopping the demonstration.

**Afterwards, deallocate the VM or it keeps charging (~$0.50/hour):**
```
az vm deallocate -g GLOSTER-GPT-HPC-PLAYGROUND-ENV-SHAKH -n ggpt-hpc-shakh-vm
```
"Stopped" is not enough in the Azure portal — it must say **Deallocated**.
