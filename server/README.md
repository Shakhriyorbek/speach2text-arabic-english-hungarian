# GPU transcription server (optional)

Runs Whisper **`large-v3`** on a rented GPU so the mosque laptop doesn't have
to, and — when you build it — NLLB-1.3B for the Hungarian as well. The laptop
still records the audio and still shows the subtitles; the models move.

**Why bother:** measured on a real Arabic khutbah recording, same 90 seconds of
audio through each path:

| Where | Model | Speed | Result |
|---|---|---|---|
| laptop CPU | `small` | 8.9x | almost nothing survived the quality guards |
| laptop CPU | `medium` | 3.9x batch / **0.89x on live 5s chunks** | one passage; inverted a negation |
| **rented GPU** | **`large-v3`** | **30.9x** *(on a T4; a 3090 is faster)* | three passages, proper names, negation intact |

`medium` on the laptop is *below realtime* for live 5-second chunks, so it falls
behind and starts dropping audio. A T4-class GPU runs the biggest model ~10x
faster than the laptop runs the smallest useful one.

Translation moved here for the same reason. NLLB-600M — the largest that fits
the latency budget on a laptop CPU — was measured turning *"we seek His
forgiveness"* into *"we forgive Him"* on flawless input. That is not an audio
problem, and a bigger model is the only fix.

---

## Which box

Provider-neutral: anything with Ubuntu, an NVIDIA driver and `python3`. It was
originally an Azure `NC4as_T4_v3`; nothing here depends on that any more.

**VRAM, measured rather than guessed** (float16, `beam_size` 5 on finals):

| | weights | peak with context + activations |
|---|---|---|
| Whisper `large-v3` | 3.1 GB | ~4 GB |
| NLLB-200-distilled-1.3B | 2.7 GB | ~3 GB |
| NLLB-200-3.3B | 7.6 GB | ~8.5 GB |

So **12 GB is the floor** for `large-v3` + the 1.3B, 16 GB is comfortable, and
you want **24 GB** if you run the 3.3B. An earlier version of this file said
8 GB was comfortable; that was wrong — it leaves no margin, and running out of
VRAM does not happen at startup, it happens on an utterance.

If you are stuck with a smaller card, both models can be loaded at int8 without
rebuilding anything (CTranslate2 converts at load time):

```
WHISPER_COMPUTE_TYPE=int8_float16 NLLB_COMPUTE_TYPE=int8_float16 \
  bash /workspace/start_whisper.sh
```

That roughly halves both. Treat it as an emergency lever, not a default —
nothing here has measured what int8 does to religious Arabic, and this system's
whole reason for moving translation to a GPU was that a *smaller* model silently
inverted meaning.

**Prices at the time of writing.** At about ten GPU-hours a month, the hourly
rate is not the thing to optimise — reliability is.

| | GPU | ~$/hour |
|---|---|---|
| RunPod Community | RTX A5000 24 GB | ~$0.27 |
| RunPod Community | RTX 4090 24 GB | ~$0.34 |
| **RunPod Secure** | **RTX 4090 24 GB** | **~$0.69** |
| Vast.ai (on-demand) | RTX 3090 24 GB | ~$0.15 |
| Vast.ai (spot) | RTX 3060 12 GB | ~$0.04 |

**Take Secure Cloud.** Community Cloud is other people's idle hardware. A
network volume pins you to one datacenter, so if the Community pool there has
nothing free at 11:00 on a Friday you have a disk you cannot attach to a GPU and
no way to move. The difference is about $4 a month at this usage.

For the same reason, `config.RUNPOD_GPU_TYPES` is a **list**: RunPod is asked
for whichever of those cards is actually free. Before committing to a
datacenter, check it stocks more than one 24 GB model.

Prefer a **European** datacenter. Latency matters more than it looks: with
`STREAMING_PARTIALS = True` the laptop makes about two requests a second while
someone is speaking.

Avoid **spot / interruptible** instances. They are half the price and can be
reclaimed with little notice, which on a Friday means the subtitles drop to the
laptop's models mid-sentence.

### What it costs

| | $/month | bills when |
|---|---|---|
| RTX 4090 Secure, ~12 h/month @ $0.69/h | 8.28 | only while a pod exists |
| 25 GB network volume @ $0.07/GB | 1.75 | **always, 24/7** |
| One CPU pod to build the models | ~0.20 | once, ever |
| **Total** | **~$10** | |

On RunPod Community instead of Secure the card is ~$0.34/h, which brings it to
about **$5.80/month** — at the cost of the availability risk described above.
With the 3.3B and a 60 GB volume it is about **$13**.

You buy no hardware. This is prepaid credit, and the only standing charge is
the volume: about **$1.75 a month whether or not there is a khutbah**.

The number that dwarfs all of these is a pod nobody stopped: $0.69 × 730 hours
is about **$500 a month**. See *Cost discipline* below — three separate
mechanisms exist for that, and none of them is you remembering.

---

## Setup: build the volume once

Do this **once**, weeks before you need it, and never on a Friday.

### 1. Create the network volume

RunPod → Storage → Network Volume, in a **European** datacenter that stocks more
than one 24 GB card. The datacenter cannot be changed afterwards, so choose it
carefully; the **size can be increased later but never decreased**, so start at
what you need now rather than what you might need.

**Start at 25 GB** ($1.75/month). That is the NLLB-1.3B setup, which is what you
should run first — the 3.3B is gated on the A/B in *Choosing the translation
model*, and it may well lose.

| | GB |
|---|---|
| Whisper `large-v3` cache | 3.1 |
| NLLB-1.3B raw download (deleted after conversion) | 5.5 |
| NLLB-1.3B converted | 2.7 |
| `wbench` venv | 2.5 |
| **peak, during the one-time build** | **~14** |
| **steady state** | **~8.5** |

**Only if the A/B favours the 3.3B**, expand to 60 GB ($4.20/month) first — that
model is a 17.6 GB download plus 6.6 GB converted, so the build peaks around
32 GB with the 1.3B kept alongside as a baseline.

### 2. Build the models on a CPU pod

Attach the volume to a cheap **CPU** pod at `/workspace`:

```
curl -fsSL https://raw.githubusercontent.com/Shakhriyorbek/speach2text-arabic-english-hungarian/main/server/bootstrap.sh | bash -s -- --build-nllb
```

**A CPU pod, not a GPU one**, and this is not an economy: converting NLLB loads
the whole checkpoint into CPU RAM as float32 — about 26 GB for the 3.3B — while
a GPU pod typically has 24–32 GB. Losing that gamble costs forty minutes and a
finished download. The conversion needs no GPU at all; `build_nllb.py` falls
back to cpu/int8 for its verification step. bootstrap.sh warns if RAM looks
short.

Add `--nllb-3.3b` for the larger translation model, but read *Choosing the
translation model* below first — it is not a free upgrade.

When it finishes, **terminate the pod**. The volume keeps everything.

`bootstrap.sh` is **idempotent**: run against a prepared volume it is a fast
no-op, which is exactly what happens every Friday.

> **`HF_HOME` is the whole trick.** `bootstrap.sh` sets it to `/workspace/hf`.
> Left at its default, faster-whisper caches `large-v3` under
> `~/.cache/huggingface` — which lives in the container layer and is destroyed
> with the pod. A "pre-baked" volume would then silently re-download 3 GB on the
> morning you were trying to save time.

### 3. Point the laptop at it

In `config.py`: `RUNPOD_NETWORK_VOLUME_ID`, `RUNPOD_DATACENTER_ID`, and
`RUNPOD_GPU_TYPES`. Then, once, in a terminal on the laptop:

```
setx RUNPOD_API_KEY "<your RunPod API key>"
```

Close and reopen it. That is the last thing anyone has to type.

---

## Every Friday: double-click `START.bat`

That is the whole procedure, and it is the point of all of the above.

`subtitles/launcher.py` creates a pod through RunPod's REST API with
`bootstrap.sh && start_whisper.sh` as its **start command**, waits for
`/health`, proves the token round-trips, and runs the subtitles. When the
window closes it terminates the pod.

Two things that used to be copied by hand no longer exist:

* **the token** is generated on the laptop and passed to the pod in the API's
  `env` field — `preflight.py` calls a mis-copied token "the single most likely
  day-of failure", and now there is nothing to mis-copy;
* **the URL** is derived from the pod ID the laptop just created.

`tmux` is gone too. The old runbook needed it because a pod has no init system
and the server died with the web terminal tab; as the container's start command
there is no tab to close.

Budget **4–6 minutes**: ~2–3 to get a machine, then ~1–2 to read ~11 GB of
models off the network volume.

### Doing it by hand

Still supported, and the documented fallback if the RunPod API is unreachable:

```
bash /workspace/bootstrap.sh
bash /workspace/start_whisper.sh $(openssl rand -hex 32)      # inside tmux
```

It prints the token. Put the pod's URL on one line in `pod_url.txt` next to
`run.bat`, `setx WHISPER_SERVER_TOKEN "<the token>"`, then `check_gpu.bat` and
`run.bat`.

---

## Reaching it from the laptop

Two ways, and the server does not care which.

**HTTP proxy (what we use).** Expose `8756` as an **HTTP port** and RunPod
serves it at `https://<POD_ID>-8756.proxy.runpod.net`. HTTPS for free, nothing
to firewall, no SSH tunnel to drop mid-sermon. `whisper_server.py` already binds
`0.0.0.0`, which is the proxy's one requirement.

**Direct TCP (fallback).** Expose `8756` as a **TCP port** instead and read the
mapping from the pod's *Connect → Direct TCP Ports* panel
(`http://<ip>:<mapped-port>`). Use this if the proxy turns out to interfere with
the request headers — see the warning below.

`START.bat` sets both of these up by itself — it asks for `8756/http` when it
creates the pod and derives the URL from the pod ID. The paragraphs above matter
when you are driving it by hand, or debugging why the proxy is misbehaving.

To go back to fully offline, set `ASR_LOCATION = "cpu"` and `MT_LOCATION =
"cpu"` in `config.py`, and use `run.bat`.

---

## Verify before you trust it

```
python smoke_test.py --url https://<POD_ID>-8756.proxy.runpod.net --wav khutbah.wav
```

`smoke_test.py` is **stdlib-only on purpose** — no numpy, no venv, not even
`config.py` — so the same file runs on the pod, on the mosque laptop, and on any
dev machine whose Python is too new for the project's dependencies.

It checks four things: the server is up and on `cuda`; a **bad** token is
refused; a real clip comes back as text; and translation works.

> **The header check is the one that matters.** The laptop sends `X-Task:
> transcribe` so the server returns **Arabic** for the direct path. If anything
> in between strips that header, `whisper_server.py` falls back to its default
> of `task="translate"` and returns **English** — which NLLB then accepts
> without complaint and renders as fluent, confident nonsense. Nothing errors.
> `smoke_test.py` catches it by checking that Arabic audio comes back in Arabic
> script, which is why you should run it with `--wav` on real speech rather than
> trusting the synthetic tone.

Then, on the laptop, `check_gpu.bat` before every khutbah. Note that `/health`
is deliberately **unauthenticated**, so a green health check proves nothing
about your token — the pre-flight sends a real (silent) request to check that
separately. A mismatched token is the most likely day-of failure, because it is
copied by hand.

---

## Security

The server refuses to start without `WHISPER_SERVER_TOKEN`. That is deliberate
and it matters more here than it did on Azure: behind the old network security
group the token was a second layer, but a proxy URL is public and guessable, so
**the token is now the only thing between this GPU and anyone who scans for open
endpoints.**

`START.bat` generates a fresh 256-bit token for every pod and passes it through
the API, so this is now automatic and there is nothing to copy, store or
remember. Driving it by hand, use `openssl rand -hex 32` and don't commit it.

Your **RunPod API key** is the more dangerous secret — it can create and destroy
machines that cost money. It lives in `RUNPOD_API_KEY` in the environment, never
in a file, and nothing logs it.

---

## Cost discipline

A GPU bills whether or not anyone is speaking. A pod nobody stopped is about
**$500 a month** — ten times the entire budget, and the single largest financial
risk in this system. *Stopping* a pod is not enough, either: it keeps billing
for its disks. Only **terminate** frees the GPU, and the network volume survives
that just fine.

So none of the three mechanisms is you remembering:

1. **`START.bat` terminates the pod** when the subtitle window closes, and
   `STOP.bat` does it on demand if the laptop crashed.
2. **The pod terminates itself.** `start_whisper.sh` arms a detached wall-clock
   guard (`RUNPOD_DEADLINE_HOURS`, default 6) that survives Ctrl-C, the server
   dying, the container's start command exiting and the laptop being unplugged.
   It is deliberately a fixed deadline rather than an idle timer: an idle timer
   can only fire while the server is alive, which is not the case it is needed
   for, and any threshold that survives the gap between the two parts of a
   khutbah would be too long to be worth having. `check_gpu.bat` shows how long
   is left, and `pkill -f khutbah-deadman` cancels it.
3. **The next `START.bat` cleans up** anything that still got through.

Belt and braces: **keep the RunPod prepaid balance low** — around $60. If all
three somehow fail, a forgotten pod dies in a few days rather than running for a
month. Keep the floor above the volume's monthly cost, since a sustained zero
balance can eventually put the volume at risk.

## Choosing the translation model

`--nllb-3.3b` is the obvious way to spend a GPU budget, and it is **not** an
obvious win. `subtitles/names.py` records that 600M, 1.3B and 3.3B were all
tried on the proper-name problem and **3.3B was the worst of the three** — which
is why `Substituter` exists and why it stays regardless.

What a bigger model should buy is meaning fidelity: the failure where *"we seek
His forgiveness"* came back as *"we forgive Him"*. Measure that, don't assume it:

```
# 1. transcribe once, and FREEZE the Arabic
python compare_mt.py --url <pod> --wav khutbah.wav --extract arabic.txt

# 2. serve the 1.3B, translate those exact lines
python compare_mt.py --url <pod> --lines arabic.txt --out a.tsv

# 3. restart with NLLB_MODEL_DIR=<the 3.3B>, repeat
python compare_mt.py --url <pod> --lines arabic.txt --out b.tsv
```

Freezing the Arabic is the whole point: with it fixed, the only difference
between `a.tsv` and `b.tsv` is the translation model. Then have someone who
reads Arabic *and* Hungarian mark each line better/same/worse, looking for the
two named failure modes — **inversion** and **dropped qualifiers** — rather than
a general impression. If 3.3B doesn't move those, it isn't worth 6.6 GB and the
extra latency. Record the verdict in `config.py` next to `MT_LOCATION`, the way
this project records every other measurement.

---

## Honest limitation

This improves speech recognition and translation quality, not the fundamentals.
Machine translation of religious Arabic still makes mistakes, and the subtitles
remain a live aid to understanding rather than an authoritative translation.
