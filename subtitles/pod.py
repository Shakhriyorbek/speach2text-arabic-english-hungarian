"""
Rent and release the GPU box, from the laptop.

Why this exists: the GPU half of this system worked, but only for someone
willing to drive a cloud console. The Friday procedure was "create a pod, open
its web terminal, run two scripts, copy a 64-character token by hand, paste the
pod's URL into a text file, then start the subtitles" — and the people who
actually run it are the imam and whoever is free. Every one of those steps is a
way for Friday to go wrong silently.

So the laptop does it. This module is the whole RunPod side: create a pod, wait
for it, tear it down. ``launcher.py`` drives it and shows progress.

Deliberately stdlib-only — no ``runpod`` package, no ``requests`` — for the same
reason ``smoke_test.py`` is: this has to keep working on a locked-down mosque
laptop years from now, and the fewer things that can go stale between here and
a working Friday, the better.

The API key is read from the environment (``RUNPOD_API_KEY``) and never written
to a file. It can create and destroy machines that cost money, so it is treated
like the transcription token: environment only, never committed, never logged.
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request

import config

API_ROOT = "https://rest.runpod.io/v1"

# A pod's own name in the console. Dated so that a leaked one is obvious at a
# glance, and so two weeks' pods never look alike.
POD_NAME_PREFIX = "khutbah-subtitles"


class PodError(RuntimeError):
    """Anything that stopped us renting or releasing a GPU.

    Always carries a message written for the person standing in the mosque, not
    for a stack trace: launcher.py prints ``str(exc)`` straight onto the screen.
    """


def api_key() -> str:
    key = os.environ.get("RUNPOD_API_KEY", "").strip()
    if not key:
        raise PodError(
            "RUNPOD_API_KEY is not set on this laptop.\n"
            'Open a terminal and run:  setx RUNPOD_API_KEY "<your key>"\n'
            "then close it and try again. The key is on the RunPod website "
            "under Settings -> API Keys."
        )
    return key


def _request(method: str, path: str, body: dict | None = None, timeout: float = 30.0):
    """One REST call. Returns parsed JSON, or None for an empty body."""
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(
        f"{API_ROOT}{path}",
        data=data,
        method=method,
        headers={
            "Authorization": f"Bearer {api_key()}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8").strip()
    except urllib.error.HTTPError as exc:
        detail = ""
        try:
            detail = exc.read().decode("utf-8", errors="replace").strip()[:400]
        except Exception:
            pass
        # 401 is worth naming explicitly: it is the one failure an operator can
        # actually fix by themselves, and it looks identical to "RunPod is down"
        # if we only print the status code.
        if exc.code == 401:
            raise PodError(
                "RunPod rejected our API key (401).\n"
                "The key in RUNPOD_API_KEY is wrong, expired, or was revoked. "
                "Make a new one in the RunPod console and set it again with "
                "setx."
            ) from exc
        raise PodError(f"RunPod said HTTP {exc.code} {exc.reason}. {detail}") from exc
    except Exception as exc:
        raise PodError(
            f"Could not reach RunPod ({type(exc).__name__}). "
            f"Is this laptop online?"
        ) from exc

    if not raw:
        return None
    try:
        return json.loads(raw)
    except ValueError as exc:
        raise PodError(f"RunPod sent something that is not JSON: {raw[:200]!r}") from exc


# --- the three things we actually do -------------------------------------


def create(token: str) -> dict:
    """Rent a GPU and start the transcription server on it. Returns the pod."""
    volume = getattr(config, "RUNPOD_NETWORK_VOLUME_ID", "").strip()
    if not volume:
        raise PodError(
            "RUNPOD_NETWORK_VOLUME_ID is not set in config.py, so there is no "
            "prepared disk to attach.\n"
            "See server/README.md — the volume holds the models, and without it "
            "a new pod would have to download about 20 GB before it could "
            "transcribe anything."
        )

    port = getattr(config, "RUNPOD_SERVER_PORT", 8756)

    # The container's main process IS the server. That is why there is no tmux
    # here and none in the runbook any more: with no init system in a pod, the
    # old procedure had the server die whenever the web terminal tab closed.
    # bootstrap.sh is a fast no-op against a prepared volume, but it is still
    # run every time, because it is also what repairs a volume that is missing
    # a file — and finding that out now is much better than mid-khutbah.
    start_cmd = (
        "bash /workspace/bootstrap.sh && "
        "bash /workspace/start_whisper.sh"
    )

    body = {
        "name": f"{POD_NAME_PREFIX}-{time.strftime('%Y%m%d-%H%M')}",
        "computeType": "GPU",
        "gpuCount": 1,
        "gpuTypeIds": list(getattr(config, "RUNPOD_GPU_TYPES", [])),
        # "availability" is what makes the list above a fallback chain rather
        # than a preference: RunPod picks whichever of our acceptable cards is
        # actually free, instead of failing on the first one being out.
        "gpuTypePriority": "availability",
        "cloudType": getattr(config, "RUNPOD_CLOUD_TYPE", "SECURE"),
        "dataCenterIds": [config.RUNPOD_DATACENTER_ID],
        "networkVolumeId": volume,
        # bootstrap.sh defaults WORKDIR to /workspace, which is also where
        # RunPod mounts a network volume — but say it out loud rather than
        # relying on two defaults happening to agree.
        "volumeMountPath": "/workspace",
        "imageName": getattr(config, "RUNPOD_IMAGE", ""),
        "containerDiskInGb": int(getattr(config, "RUNPOD_CONTAINER_DISK_GB", 20)),
        "ports": [f"{port}/http"],
        "dockerStartCmd": ["bash", "-lc", start_cmd],
        "env": {
            # The whole point: the token is generated on this laptop and handed
            # to the pod here, so it is never read off a screen and typed in.
            "WHISPER_SERVER_TOKEN": token,
            "WHISPER_SERVER_PORT": str(port),
            "DEADLINE_HOURS": str(getattr(config, "RUNPOD_DEADLINE_HOURS", 6)),
        },
    }

    pod = _request("POST", "/pods", body, timeout=60.0)
    if not isinstance(pod, dict) or not pod.get("id"):
        raise PodError(f"RunPod accepted the request but returned no pod: {pod!r}")
    return pod


def get(pod_id: str) -> dict | None:
    """Current state of a pod, or None if it no longer exists."""
    try:
        return _request("GET", f"/pods/{pod_id}", timeout=20.0)
    except PodError as exc:
        if "HTTP 404" in str(exc):
            return None
        raise


def terminate(pod_id: str) -> None:
    """Destroy a pod. Idempotent — an already-gone pod is a success.

    TERMINATE, not stop. A stopped pod keeps billing for its disks and holds
    nothing we need: the models live on the network volume, which survives
    either way.
    """
    try:
        _request("DELETE", f"/pods/{pod_id}", timeout=30.0)
    except PodError as exc:
        if "HTTP 404" in str(exc):
            return
        raise


def proxy_url(pod_id: str) -> str:
    """Where the server on ``pod_id`` will answer.

    RunPod publishes each HTTP port at a fixed hostname derived from the pod ID,
    with a real certificate and no inbound port to open. The URL is public and
    guessable, which is why WHISPER_SERVER_TOKEN is not optional.
    """
    port = getattr(config, "RUNPOD_SERVER_PORT", 8756)
    return f"https://{pod_id}-{port}.proxy.runpod.net"


def is_configured() -> bool:
    """True when this laptop is set up to rent GPUs by itself."""
    return bool(
        getattr(config, "RUNPOD_NETWORK_VOLUME_ID", "").strip()
        and getattr(config, "RUNPOD_DATACENTER_ID", "").strip()
        and os.environ.get("RUNPOD_API_KEY", "").strip()
    )


# --- remembering what we rented ------------------------------------------

# Next to run.bat, beside pod_url.txt, and gitignored for the same reason.
STATE_FILE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".pod_state.json"
)


def remember(pod_id: str) -> None:
    """Record the pod we just rented.

    Written BEFORE we start waiting on it, not after: the window where a pod
    exists and we have forgotten its ID is exactly the window in which a crash
    leaves it billing with nothing left that knows how to stop it.
    """
    try:
        with open(STATE_FILE, "w", encoding="utf-8") as fh:
            json.dump({"pod_id": pod_id, "created_at": time.time()}, fh)
    except OSError as exc:
        # Not fatal — the pod's own deadline still stops the billing — but the
        # operator should know the tidy path just broke.
        print(f"[pod] could not write {STATE_FILE}: {exc}", flush=True)


def forget() -> None:
    try:
        os.remove(STATE_FILE)
    except FileNotFoundError:
        pass
    except OSError as exc:
        print(f"[pod] could not remove {STATE_FILE}: {exc}", flush=True)


def remembered() -> str | None:
    """The pod ID from a previous run, if one was left behind."""
    try:
        with open(STATE_FILE, encoding="utf-8") as fh:
            return (json.load(fh) or {}).get("pod_id") or None
    except (OSError, ValueError):
        return None


def release_leftover() -> str | None:
    """Terminate a pod left over from a previous run. Returns its ID if so.

    This is the cleanup for "the laptop was closed without stopping", which is
    the normal way things end when the person holding it is not technical. It
    runs at the START of a session rather than being relied on at the end,
    because the end is precisely when we may not get to run any code at all.
    """
    pod_id = remembered()
    if not pod_id:
        return None
    try:
        terminate(pod_id)
    except PodError as exc:
        print(f"[pod] leftover pod {pod_id} could not be terminated: {exc}", flush=True)
        return None
    forget()
    return pod_id
