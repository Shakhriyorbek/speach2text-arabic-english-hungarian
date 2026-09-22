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

**You need less GPU than you think.** `large-v3` in fp16 is about 3 GB of VRAM
and NLLB-1.3B about 2.7 GB, so **8 GB is comfortable** and 16 GB is roomy. Live
prices at the time of writing:

| | GPU | ~$/hour |
|---|---|---|
| Vast.ai (spot) | RTX 3060 12 GB / A4000 16 GB | $0.04 – $0.05 |
| Vast.ai (on-demand) | RTX 3090 24 GB | ~$0.15 |
| **RunPod Community** | **RTX A4000 16 GB** | **~$0.17** |
| RunPod Community | RTX 3090 24 GB | ~$0.22 |
| Scaleway (EU, invoiced) | L4 24 GB | ~€0.79 |
| *Azure (what we used to use)* | *Tesla T4* | *~$0.50* |

Prefer a **European** host. Latency matters more than it looks: with
`STREAMING_PARTIALS = True` the laptop sends a refresh roughly once a second
while someone is speaking, not just once per utterance.

Avoid **spot / interruptible** instances for a live khutbah. They are half the
price and can be reclaimed with little notice, which on a Friday means the
subtitles drop to the laptop's models mid-sentence.

---

## Setup: one command

On the box (RunPod's web terminal, or over SSH):

```
curl -fsSL https://raw.githubusercontent.com/Shakhriyorbek/speach2text-arabic-english-hungarian/main/server/bootstrap.sh | bash -s -- --build-nllb
```

`bootstrap.sh` checks the GPU, fetches the four files the server needs, builds a
lean runtime venv, downloads `large-v3`, and converts NLLB-1.3B to CTranslate2.
Drop `--build-nllb` to skip the big conversion and let the laptop translate.

It is **idempotent** — running it against a box that already has everything is a
fast no-op, which is exactly what happens on the morning of a khutbah when a
fresh pod is attached to an already-built volume.

Then start it:

```
bash /workspace/start_whisper.sh $(openssl rand -hex 32)
```

It prints the token it is using. The laptop needs the same value.

### Keep it alive

**A RunPod pod is a container with no init system, so `systemd` is not
available** and the process dies when the web terminal tab closes. Use `tmux`:

```
tmux new -s whisper
bash /workspace/start_whisper.sh <token>
# detach with ctrl-b then d; reattach later with: tmux attach -t whisper
```

On a plain VM with systemd, a unit works as before — `ExecStart` should invoke
`start_whisper.sh`, which already sets `LD_LIBRARY_PATH` and `HF_HOME` for you.

---

## Persistent storage: build once, not every Friday

This is the part that turns a forty-minute setup into a three-minute one.

Attach a **network volume** (RunPod: $0.07/GB/month) at `/workspace` and point
everything at it — which is what `bootstrap.sh` does by default. **50 GB** is
right: ~3.1 GB for the Whisper cache, ~2.7 GB for NLLB-1.3B, ~2.5 GB for the
venv, and transient room for the ~5.5 GB raw NLLB download during conversion.

Then build everything the evening *before*, and **terminate the pod**. The GPU
stops billing; the volume costs about **$0.12 a night**. Next morning create a
pod, attach the same volume, re-run `bootstrap.sh` (no-op) and start the server.

> **`HF_HOME` is the whole trick.** `bootstrap.sh` sets it to `/workspace/hf`.
> Left at its default, faster-whisper caches `large-v3` under
> `~/.cache/huggingface` — which lives in the container layer and is destroyed
> with the pod. A "pre-baked" volume would then silently re-download 3 GB on the
> morning you were trying to save time.

A network volume **pins the pod to one datacenter**, so choose the datacenter
first (an EU one) and check it has GPU stock before committing.

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

On the laptop, put the URL on one line in **`pod_url.txt`** next to `run.bat`,
and set the token once:

```
setx WHISPER_SERVER_TOKEN "<the token the server printed>"
```

Close and reopen the terminal. `run.bat` and `check_gpu.bat` read `pod_url.txt`
themselves, so the pod ID changing every week never means editing Python.

To go back to fully offline, set `ASR_LOCATION = "cpu"` and `MT_LOCATION =
"cpu"` in `config.py`.

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
endpoints.** Generate a fresh one per pod (`openssl rand -hex 32`) and don't
commit it anywhere.

---

## Cost discipline

A GPU bills by the hour whether or not anyone is speaking. Start it before the
khutbah and **terminate it afterwards** — on RunPod, *stopping* a pod still
bills for its disk, and only the network volume is meant to persist.

Realistically, for a weekly khutbah: about **$3.50/month** for a 50 GB volume
plus roughly **$0.70 per Friday** — call it **$6 a month**.

## Honest limitation

This improves speech recognition and translation quality, not the fundamentals.
Machine translation of religious Arabic still makes mistakes, and the subtitles
remain a live aid to understanding rather than an authoritative translation.
