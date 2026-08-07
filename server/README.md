# GPU transcription server (optional)

Runs Whisper **`large-v3`** on a GPU box so the mosque laptop doesn't have to.
The laptop still records the audio and still does the Hungarian translation —
only the speech recognition moves.

**Why bother:** measured on a real Arabic khutbah recording, same 90 seconds of
audio through each path:

| Where | Model | Speed | Result |
|---|---|---|---|
| laptop CPU | `small` | 8.9x | almost nothing survived the quality guards |
| laptop CPU | `medium` | 3.9x batch / **0.89x on live 5s chunks** | one passage; inverted a negation |
| **Tesla T4** | **`large-v3`** | **30.9x** | three passages, proper names, negation intact |

`medium` on the laptop is *below realtime* for live 5-second chunks, so it falls
behind and starts dropping audio. The T4 runs the biggest model ~10x faster than
the laptop runs the smallest useful one.

**Honest limitation:** this improves speech recognition, not the English pivot.
Arabic still goes Arabic → English → Hungarian, and subtle meaning can still
shift in that second hop. Azure cloud mode (`BACKEND = "azure"`) is the only
option here that translates straight to Hungarian.

---

## One-time setup on the GPU VM

Assumes Ubuntu with a working NVIDIA driver — check with `nvidia-smi` first. If
that fails after a kernel upgrade, the kernel module needs rebuilding for the
running kernel:

```
sudo apt install -y linux-modules-nvidia-<branch>-azure
sudo modprobe nvidia
```

Then:

```
python3 -m venv ~/wbench
~/wbench/bin/pip install faster-whisper nvidia-cublas-cu12 nvidia-cudnn-cu12
```

`ctranslate2` needs the CUDA 12 libraries at runtime, so point it at them:

```
export LD_LIBRARY_PATH=$HOME/wbench/lib/python3.12/site-packages/nvidia/cublas/lib:$HOME/wbench/lib/python3.12/site-packages/nvidia/cudnn/lib
```

Generate a shared secret and start the server:

```
export WHISPER_SERVER_TOKEN="$(openssl rand -hex 32)"
echo "$WHISPER_SERVER_TOKEN"      # copy this — the laptop needs the same value
~/wbench/bin/python whisper_server.py
```

The server refuses to start without a token. That is deliberate: an open
transcription endpoint on a public IP is free compute for anyone who scans it.

### Keep it running (systemd)

`/etc/systemd/system/whisper.service`:

```ini
[Unit]
Description=Whisper transcription server
After=network.target

[Service]
User=hpcadmin
WorkingDirectory=/home/hpcadmin
Environment=WHISPER_SERVER_TOKEN=<your token>
Environment=LD_LIBRARY_PATH=/home/hpcadmin/wbench/lib/python3.12/site-packages/nvidia/cublas/lib:/home/hpcadmin/wbench/lib/python3.12/site-packages/nvidia/cudnn/lib
ExecStart=/home/hpcadmin/wbench/bin/python /home/hpcadmin/whisper_server.py
Restart=on-failure

[Install]
WantedBy=multi-user.target
```

```
sudo systemctl enable --now whisper
```

### Lock down the port

**Do not open 8756 to the whole internet.** In the Azure NSG, allow inbound 8756
only from the mosque's public IP. The bearer token is a second layer, not the
first one.

---

## On the mosque laptop

```
setx WHISPER_SERVER_TOKEN "<the same token>"
```

Close and reopen the terminal, then in `config.py`:

```python
ASR_LOCATION  = "remote"
REMOTE_ASR_URL = "http://<vm-public-ip>:8756"
```

Run `run.bat` as usual. On startup it prints which model the server reports. If
the server is unreachable it says so and quietly uses the local model instead —
F1/F2 and everything else behave identically.

To go back to fully offline, set `ASR_LOCATION = "cpu"`.

---

## Cost discipline

A GPU VM bills by the hour whether or not anyone is speaking (~$0.50/h for
`NC4as_T4_v3`). Start it before the khutbah and **deallocate it afterwards** —
left running it is a few hundred dollars a month. "Stopped" is not enough in the
Azure portal; it must say **Deallocated**.

This is the main operational argument against this setup for a volunteer-run
system, and the main argument for Azure cloud mode instead, whose free tier
covers a weekly khutbah with nothing to remember to switch off.
