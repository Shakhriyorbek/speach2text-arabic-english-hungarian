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
4. **Decide which mode you are demonstrating, and check `config.py` matches.**

   The repository ships configured for the **GPU**, not for offline — so if you
   want the safe offline demonstration you have to say so explicitly:

   ```python
   BACKEND          = "local"
   ASR_LOCATION     = "cpu"      # ships as "remote"
   MT_LOCATION      = "cpu"      # ships as "remote"
   STREAMING_PARTIALS = False    # ships as True; too slow for a laptop CPU
   MODEL_SIZE_PART1 = "small"
   ```

   For the **GPU** demonstration, leave all of those as they ship and follow the
   GPU section at the bottom of this page instead.

   Either way, check `MIC_DEVICE`. It ships as `1`, which is the built-in mic on
   the development laptop and almost certainly the wrong number on yours. Run
   `venv\Scripts\python -m sounddevice` to list devices and set the index you
   actually want — it is pinned deliberately rather than left as `None` so that
   a Bluetooth headset connecting mid-sermon cannot silently take over the input.

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

## Optional: the GPU version (better Arabic and Hungarian)

Noticeably better Arabic — on the same recording it caught proper names and kept
a negation that the offline model reversed. It needs **reliable internet at the
mosque** and costs a few dollars a month. Rehearse it once before relying on it.

### Set it up once (not on a Friday)

Someone technical does this part, once. Full instructions in `server/README.md`:

1. Create a **network volume** in a European datacenter and build the models
   onto it. Do the build on a cheap **CPU** pod — it needs no GPU, and the
   translation model needs more RAM to convert than a GPU pod usually has.
2. Put three values in `config.py`: `RUNPOD_NETWORK_VOLUME_ID`,
   `RUNPOD_DATACENTER_ID`, and the list of cards you are willing to rent.
3. On the mosque laptop, once:
   `setx RUNPOD_API_KEY "<your RunPod key>"` — then close the terminal.

### Then, every Friday

**Double-click `START.bat`.** That is the whole procedure.

It shows a window with six lines and ticks them off: it rents a GPU, waits for
the machine, waits for the models to load, checks the connection, and then the
subtitles appear. Expect **four to six minutes**, so start it before the
congregation arrives — not as the imam stands up.

There is nothing to type. No pod to create, no token to copy, no URL to paste.

**When you close the subtitle window, the GPU is given back automatically** and
the billing stops. You will see "GPU released" in the small black window.

### If it doesn't work

The window will say what went wrong and offer two buttons. Press
**"Folytatás GPU nélkül / Continue without the GPU"** — the subtitles still
work, using this laptop, exactly as they do offline. F1/F2 behave the same.

Do not try to fix it in front of the congregation. Note what it said and look
afterwards.

### Making sure you are not paying for a GPU

Three things stop the rented machine, so a forgotten one is not a disaster:

1. Closing the subtitle window gives it back.
2. The machine terminates **itself** a few hours after starting, even if this
   laptop is switched off or loses power.
3. The next `START.bat` cleans up anything left behind.

If you want to stop it **right now** — the laptop crashed, or you closed the lid
— double-click **`STOP.bat`**. It is safe to run at any time and tells you
plainly whether anything was rented.

> `run.bat` still works and still reads `pod_url.txt`, for the case where you
> have started a server by hand. `check_gpu.bat` checks such a server. Neither
> is needed for the one-click procedure above.
