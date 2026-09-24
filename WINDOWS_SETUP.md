# Setting up the subtitle laptop (Windows)

Start to finish, for a laptop that has never run this before. Allow **about an
hour**, most of it waiting for downloads.

You only do this once. After it, running the subtitles is one double-click.

> Doing the **GPU** part as well? You need a RunPod account with credit on it,
> and the models already built onto a network volume — that is a separate
> one-time job described in `server/README.md`. Everything here works without
> it; the GPU is optional and improves the Arabic.

---

## What you need

| | |
|---|---|
| Windows laptop | any recent one; no graphics card needed |
| Internet | for setup. During the khutbah only GPU mode needs it |
| Microphone | the stage mic, or the built-in one for testing |
| ~5 GB free disk | models and the Python environment |
| *(GPU mode only)* | a RunPod API key |

---

## 1. Install Python

Get **Python 3.13** from <https://www.python.org/downloads/>.

**Tick "Add Python to PATH"** on the first screen of the installer. It is easy
to miss and nothing works without it.

> **Not 3.14 or newer.** One of the parts we need — the voice-activity detector
> that decides when someone is speaking — has no build for 3.14 yet. The
> installer checks this and refuses rather than failing halfway. 3.10 to 3.13
> are all fine.

Check it worked. Open **Command Prompt** and type:

```
py -3.13 --version
```

You should see `Python 3.13.x`. If you get an error, re-run the installer and
make sure that box is ticked.

---

## 2. Get the program

**With git:**

```
git clone https://github.com/Shakhriyorbek/speach2text-arabic-english-hungarian.git
```

**Without git:** open the [project page](https://github.com/Shakhriyorbek/speach2text-arabic-english-hungarian),
click the green **Code** button, choose **Download ZIP**, and unzip it.

Put the folder somewhere permanent — `C:\khutbah` or your Documents folder.
Not in Downloads, where it will be tidied away by accident.

---

## 3. Run the installer

Double-click **`install.bat`**.

It takes **20–40 minutes** and downloads about **3 GB**. It creates a private
Python environment inside the folder and builds the laptop's own speech and
translation models. Leave it alone until it says `DONE`.

> **Why 3 GB even for GPU mode?** These are the laptop's *fallback* models. The
> program loads them at startup and uses them the moment the GPU becomes
> unreachable, so a network problem costs accuracy instead of the whole screen.
> Loading them later, mid-sermon, would stall the audio at the worst moment.

If it fails, scroll up to the **first** error. Almost always it is no internet,
or Python not on PATH.

---

## 4. Tell it which microphone to use

This step is skipped more often than any other, and skipping it produces a
blank screen that looks like a broken installation.

In the project folder, open Command Prompt (click the address bar, type `cmd`,
press Enter) and run:

```
venv\Scripts\python -m sounddevice
```

You get a numbered list. Find your microphone — the stage mic if it is plugged
in, otherwise something like `Microphone Array (Intel Smart Sound)`. Note the
number at the start of its line.

Open **`config.py`** in Notepad and set:

```python
MIC_DEVICE = 3        # <- the number you just found
```

Save it.

> The number is pinned deliberately rather than left as "the Windows default",
> so that a Bluetooth headset connecting mid-sermon cannot quietly take over
> the input. The trade is that it must be set per laptop.

The program prints which microphone it opened when it starts, and refuses to
start on a number that is not there — so you will know either way.

### Check it is actually carrying sound

```
CHECK_MIC.bat
```

It watches the input in `config.py` and draws a level bar while you speak. Bars
should move and peak around **-12 dBFS**.

If it reports `NOTHING IS ARRIVING`, the computer can see the input but no
sound is reaching it, and the tool lists what to check in order. With a **USB
audio interface** (Behringer U-Phoria UM2 and similar), the overwhelmingly
common cause is **phantom power**: a condenser microphone produces absolutely
nothing until the **+48V** switch on the interface is on. A dynamic microphone
does not need it.

Also note the interface appears in the device list under a **generic** name
like `USB Audio CODEC`, not under its brand — so do not go looking for
"Behringer".

---

## 5. GPU mode (optional)

Skip to step 6 if you are running laptop-only.

Set your RunPod key once, in Command Prompt:

```
setx RUNPOD_API_KEY "your-key-here"
```

Then **close the Command Prompt and open a new one** — `setx` only affects
windows opened afterwards.

Everything else (the storage volume, the datacenter, which cards to rent) is
already in `config.py`.

Check it, which costs nothing and rents nothing:

```
CHECK_SETUP.bat
```

Expect:

```
  OK   the API key works
  OK   volume 'khutba_volume' exists: 25 GB in EU-RO-1
  OK   config.py and the volume agree on the datacenter
  OK   branch 'main' has the server files on GitHub
  OK   no pods are running (nothing is being billed for compute)
```

---

## 6. Test it, in this order

Each step rules out one thing. Do not skip ahead — if you jump to the end and
it fails, you will not know which half is at fault.

### a. The models, without a microphone

Record a few sentences with the Windows **Voice Recorder** app and save/export
as `.wav` into the project folder. Arabic if you can.

```
venv\Scripts\python -m subtitles.test_pipeline test.wav
```

It prints the transcript and the Hungarian, with timings. This proves the model
chain works. Any sample rate or channel count is fine.

### b. The GPU, without a microphone *(GPU mode only)*

```
venv\Scripts\python -m subtitles.launcher --selftest
```

Rents a GPU, waits for it, checks it, releases it. **About 2–7 minutes and
roughly 5 cents.** It always gives the GPU back, including if it fails.

The line to read is near the end:

```
  AR -> HU        : 'Emberek, féljetek Istentől!'
```

That is real Arabic translated on the rented GPU. If it is sane, the GPU path
works.

### c. The microphone and the window, laptop-only

```
run.bat
```

Free, no internet needed. A black fullscreen window appears. Check the console
line that says which microphone it opened, press **F1**, and speak. Subtitles
appear a second or two after you pause.

Press **Esc** to quit.

### d. Everything

```
START.bat
```

This is the real thing — see below.

> **If `run.bat` shows subtitles but `START.bat` does not, the problem is the
> GPU. If neither does, it is the microphone.** That is the whole reason for
> doing them in this order.

---

## 7. Running it on the day

Double-click **`START.bat`**.

A window ticks off six steps while it rents a GPU and loads the models, then
the black subtitle window appears. **Allow up to 7 minutes** — start it before
the congregation arrives, not as the imam stands up.

Then:

| Key | |
|---|---|
| **F1** | Part 1 — Arabic |
| **F2** | Part 2 — English talk with Arabic quotes |
| **+ / −** | Bigger / smaller text |
| **P** | Pause / resume |
| **F11** | Fullscreen on / off |
| **Esc** | Quit |

Connect the projector with **⊞ Windows + P → Duplicate**.

**When you close the subtitle window the GPU is released automatically** and
billing stops. You will see `GPU released` in the small black window.

### If something goes wrong

The launcher never blocks the khutbah. Any failure offers
**"Folytatás GPU nélkül / Continue without the GPU"** — press it. The subtitles
still work from the laptop, F1 and F2 behave the same, just less accurately.

Do not debug in front of the congregation. Note what it said and look
afterwards.

---

## 8. Making sure you are not paying for a GPU

Four things stop it, and none of them is you remembering:

1. Closing the subtitle window releases it.
2. The rented machine **terminates itself after 6 hours**, even if the laptop
   is switched off or loses power.
3. The next `START.bat` cleans up anything left behind.
4. The RunPod account holds **prepaid credit with auto-pay off**, so it can
   never be charged more than what is on it.

To stop it *right now* — the laptop crashed, or you shut the lid — double-click
**`STOP.bat`**. Safe at any time; it says plainly whether anything is rented.

Running cost is about **$8–11 a month** for a weekly khutbah: the GPU for the
hour or two it is up, plus the storage that holds the models.

---

## If it does not work

| Problem | What it means |
|---|---|
| `install.bat` says no supported Python | Python 3.14+, or PATH not ticked. Install 3.13. |
| `MIC_DEVICE = n ... is not a usable input device` | Wrong number. Re-run step 4. |
| Window opens, no subtitles ever | Run **`CHECK_MIC.bat`**. Wrong microphone, no phantom power, or F1/F2 not pressed. |
| `CHECK_MIC.bat` says nothing is arriving | Condenser mic with **+48V off** is the usual cause; then gain, then the XLR cable. |
| `RUNPOD_API_KEY is not set` | You did not reopen Command Prompt after `setx`. |
| `No GPU is free ... on either tier` | RunPod has nothing free in our datacenter. Carry on without the GPU; try again later. |
| Subtitles suddenly get worse mid-khutbah | The GPU dropped out and the laptop took over. This is the designed fallback, not a fault. Carry on. |
| Everything frozen | **Esc**, then start it again. |

---

## What is on this laptop afterwards

```
config.py          every setting, in one file. MIC_DEVICE is the one you changed
install.bat        one-time setup (this guide, step 3)
CHECK_MIC.bat      is the microphone carrying sound? live level meter
CHECK_SETUP.bat    is the GPU account set up? free, rents nothing
START.bat          rent a GPU and show subtitles          <- the normal one
run.bat            subtitles on this laptop only, no GPU, free
STOP.bat           give the GPU back now
check_gpu.bat      check a GPU server started by hand
venv\              the private Python environment
models\            the laptop's own speech and translation models
```

Nothing here phones home except RunPod, and only in GPU mode.
