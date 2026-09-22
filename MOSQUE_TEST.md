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

## Optional: the GPU version (better Arabic, more setup)

Noticeably better Arabic — on the same recording it caught proper names and kept
a negation that the offline model reversed. But it needs **reliable internet at
the mosque** plus a rented GPU, so do not attempt it live unless you have
rehearsed it end to end.

**Prepare the night before, not on the day.** Build the models onto a RunPod
network volume, then terminate the pod; the volume costs about $0.12 a night and
turns the morning's setup from forty minutes into three. Full instructions in
`server/README.md`.

### On the morning

1. **Create a pod** in the same datacenter as your volume, attach the volume at
   `/workspace`, and expose port **8756** as an **HTTP port**.
2. **Set it up and start it** in the pod's web terminal:
   ```
   bash /workspace/bootstrap.sh              # a no-op on a prepared volume
   tmux new -s whisper
   bash /workspace/start_whisper.sh <your-token>
   ```
   Use `tmux` — a pod has no systemd, so closing the terminal tab kills the
   server. Detach with `ctrl-b` then `d`.
3. **Point the laptop at it.** Put the pod's URL on one line in `pod_url.txt`
   next to `run.bat`:
   ```
   https://<POD_ID>-8756.proxy.runpod.net
   ```
   The token goes in the environment once, not in a file:
   `setx WHISPER_SERVER_TOKEN "<the token>"`, then reopen the terminal.
4. **Check it before anyone arrives.** Double-click **`check_gpu.bat`**. It says
   in plain words whether Friday will run on the GPU. Expect:
   ```
   OK   server is up: large-v3 on cuda
   OK   the token is accepted
   OK   translation on the GPU: nllb-1.3b-ct2
   READY.
   ```
   Anything else is explained on screen. Do this **before** the congregation
   arrives — once `run.bat` is fullscreen you cannot see the console.
5. Then `run.bat` as usual. F1/F2 work exactly the same.

If the server is unreachable the program says so and **automatically uses the
offline models instead** — F1/F2 keep working, so a network failure degrades
quality rather than stopping the demonstration. Worth seeing that happen once,
deliberately, before you rely on it.

**Afterwards, terminate the pod** or it keeps billing (~$0.17/hour). On RunPod,
*stopping* a pod still charges for its disk — terminate it and keep only the
network volume.
