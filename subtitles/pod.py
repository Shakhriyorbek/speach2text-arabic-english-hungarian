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
from subtitles.http_client import USER_AGENT

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
    """The RunPod API key, from the environment only.

    Never from a file. This key can create and destroy machines that cost
    money, so it is held to the same rule as WHISPER_SERVER_TOKEN: environment
    only, never committed, never logged.
    """
    key = os.environ.get("RUNPOD_API_KEY", "").strip()
    if not key:
        # The mosque laptop is Windows; development happens on Linux. Printing
        # the wrong one of these wastes somebody's afternoon.
        how = ('Open a terminal and run:\n'
               '    setx RUNPOD_API_KEY "<your key>"\n'
               "then CLOSE and reopen it."
               if os.name == "nt" else
               'Run:\n'
               '    export RUNPOD_API_KEY="<your key>"\n'
               "(add it to ~/.bashrc to make it stick).")
        raise PodError(
            "RUNPOD_API_KEY is not set.\n"
            f"{how}\n"
            "The key is on the RunPod website under Settings -> API Keys."
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
            # Without this Cloudflare answers 403 before RunPod sees us.
            "User-Agent": USER_AGENT,
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
            # bootstrap.sh re-fetches the server files on every start and
            # defaults to main. Say which branch explicitly so a pod created
            # while testing a branch does not silently fall back to whatever
            # copies happen to be on the volume.
            "BRANCH": getattr(config, "RUNPOD_REPO_BRANCH", "main"),
        },
    }

    def attempt(cloud):
        body["cloudType"] = cloud
        return _request("POST", "/pods", body, timeout=60.0)

    # Availability moves minute to minute, so a refusal is worth waiting out
    # rather than reporting. Alternate the two tiers while we wait: whichever
    # frees up first wins.
    deadline = time.time() + getattr(config, "RUNPOD_CAPACITY_RETRY_S", 180)
    preferred = getattr(config, "RUNPOD_CLOUD_TYPE", "SECURE")
    other = "COMMUNITY" if preferred == "SECURE" else "SECURE"
    tiers = [preferred, other] if getattr(config, "RUNPOD_CLOUD_FALLBACK", True) else [preferred]

    announced = False
    while True:
        last = None
        for cloud in tiers:
            try:
                pod = attempt(cloud)
                if not isinstance(pod, dict) or not pod.get("id"):
                    raise PodError(f"RunPod returned no pod: {pod!r}")
                return pod
            except PodError as exc:
                if not _no_capacity(exc):
                    raise
                last = exc
        if time.time() >= deadline:
            raise PodError(
                f"No GPU is free in {config.RUNPOD_DATACENTER_ID} — kept asking "
                f"for {getattr(config, 'RUNPOD_CAPACITY_RETRY_S', 180)}s on "
                f"{' and '.join(tiers)}.\n"
                f"The models live on a network volume pinned to that datacenter, "
                f"so we cannot move. Carry on without the GPU and try again "
                f"later, or add more cards to RUNPOD_GPU_TYPES in config.py."
            ) from last
        if not announced:
            print(f"[pod] nothing free in {config.RUNPOD_DATACENTER_ID} yet — "
                  f"waiting, availability changes minute to minute", flush=True)
            announced = True
        time.sleep(15)


def _no_capacity(exc: Exception) -> bool:
    """Is this 'the datacenter is full' rather than 'we asked wrongly'?"""
    return "no instances currently available" in str(exc).lower()


def volume(volume_id: str) -> dict | None:
    """The network volume's real name, size and datacenter, or None if absent."""
    try:
        return _request("GET", f"/networkvolumes/{volume_id}", timeout=20.0)
    except PodError as exc:
        if "HTTP 404" in str(exc):
            return None
        raise


def running_pods() -> list:
    """Every pod on the account, so a leaked one cannot hide."""
    got = _request("GET", "/pods", timeout=20.0)
    if isinstance(got, dict):
        got = got.get("pods") or got.get("data") or []
    return [p for p in (got or []) if isinstance(p, dict)]


# CPU flavour FAMILIES, not sizes. RunPod's API takes the family here and the
# size separately as vcpuCount; the "cpu3g-8-32" form seen in its docs is the
# derived name of the result, and sending it is rejected. RAM per vCPU is
# fixed by the family letter:
#
#     c = compute   2 GB per vCPU
#     g = general   4 GB per vCPU
#     m = memory    8 GB per vCPU
#
# So "cpu3g" with 8 vCPU is 32 GB. That is what we want: converting NLLB-1.3B
# peaks around 12 GB of RAM and the 3.3B around 26 GB, and being killed for
# want of memory happens AFTER the download, which is the expensive half hour.
BUILD_CPU_FLAVORS = ["cpu3g", "cpu5g"]
BUILD_VCPUS = 8                 # x4 GB on a "g" family = 32 GB
BUILD_MIN_RAM_GB = 16           # below this, say so rather than waste an hour


def create_build_pod() -> dict:
    """Rent a CPU box with the volume attached, for the one-time model build.

    Separate from create() and deliberately dumber: no start command, no token,
    no server. It exists because the settings are what people get wrong — the
    volume not attached, the wrong datacenter, too little RAM — and each of
    those is discovered forty minutes into a download.

    No GPU, because the conversion does not use one and a GPU pod usually has
    LESS RAM than this needs. Costs a few cents.
    """
    volume = getattr(config, "RUNPOD_NETWORK_VOLUME_ID", "").strip()
    if not volume:
        raise PodError("RUNPOD_NETWORK_VOLUME_ID is not set in config.py.")

    body = {
        "name": f"khutbah-build-{time.strftime('%Y%m%d-%H%M')}",
        "computeType": "CPU",
        "cpuFlavorIds": BUILD_CPU_FLAVORS,
        "cpuFlavorPriority": "availability",
        "vcpuCount": BUILD_VCPUS,
        "dataCenterIds": [config.RUNPOD_DATACENTER_ID],
        "networkVolumeId": volume,
        "volumeMountPath": "/workspace",
        "imageName": getattr(config, "RUNPOD_BUILD_IMAGE", "python:3.11"),
        "containerDiskInGb": int(getattr(config, "RUNPOD_CONTAINER_DISK_GB", 20)),
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


def remember(pod_id: str, token: str = "") -> None:
    """Record the pod we just rented.

    Written BEFORE we start waiting on it, not after: the window where a pod
    exists and we have forgotten its ID is exactly the window in which a crash
    leaves it billing with nothing left that knows how to stop it.

    The token is kept too, so that the diagnostic tools — smoke_test.py,
    compare_mt.py, a pre-flight — can talk to a pod that START.bat rented,
    instead of it being reachable only from inside the process that made it.
    The file is gitignored and local, the same rule pod_url.txt already has.
    """
    try:
        with open(STATE_FILE, "w", encoding="utf-8") as fh:
            json.dump({"pod_id": pod_id, "token": token,
                       "created_at": time.time()}, fh)
        try:
            os.chmod(STATE_FILE, 0o600)     # it holds a credential now
        except OSError:
            pass
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
    return (_state() or {}).get("pod_id") or None


def remembered_token() -> str | None:
    """The token for that pod, so tools can reach a pod START.bat rented."""
    return (_state() or {}).get("token") or None


def _state() -> dict | None:
    try:
        with open(STATE_FILE, encoding="utf-8") as fh:
            return json.load(fh) or {}
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


# --- "is this laptop set up correctly?" -----------------------------------


def check() -> int:
    """Validate the RunPod settings WITHOUT renting anything.

    Everything here is a free API call. The point is that every mistake it can
    find — a mistyped volume ID, a volume in a different datacenter from the
    one config.py names, an expired key — would otherwise be discovered by
    START.bat failing, and the natural time to discover that is a Friday.
    """
    from subtitles.console import enable_utf8_console

    enable_utf8_console()
    OK, BAD, WARN = "  OK   ", "  FAIL ", "  WARN "
    problems = []

    print("RunPod setup check")
    print("=" * 62)
    print(f"  volume     : {getattr(config, 'RUNPOD_NETWORK_VOLUME_ID', '') or '(not set)'}")
    print(f"  datacenter : {getattr(config, 'RUNPOD_DATACENTER_ID', '') or '(not set)'}")
    print(f"  cards      : {', '.join(getattr(config, 'RUNPOD_GPU_TYPES', [])) or '(none)'}")
    print(f"  cloud      : {getattr(config, 'RUNPOD_CLOUD_TYPE', '')}")
    print(f"  branch     : {getattr(config, 'RUNPOD_REPO_BRANCH', 'main')}")
    print("=" * 62)
    print()

    try:
        api_key()
    except PodError as exc:
        print(f"{BAD}{exc}")
        return 1

    # Any authenticated call proves the key. Listing pods also tells us
    # whether something is billing right now, which is worth knowing anyway.
    try:
        pods = running_pods()
    except PodError as exc:
        print(f"{BAD}{exc}")
        return 1
    print(f"{OK}the API key works")

    vol_id = getattr(config, "RUNPOD_NETWORK_VOLUME_ID", "").strip()
    if not vol_id:
        print(f"{BAD}RUNPOD_NETWORK_VOLUME_ID is empty in config.py")
        return 1

    try:
        vol = volume(vol_id)
    except PodError as exc:
        print(f"{BAD}{exc}")
        return 1
    if vol is None:
        print(f"{BAD}there is no network volume with the id {vol_id!r}.")
        print("       Check it on the RunPod site under Storage.")
        return 1

    size = vol.get("size")
    print(f"{OK}volume {vol.get('name')!r} exists: {size} GB in {vol.get('dataCenterId')}")

    # The mismatch that produces the least helpful error later: RunPod refuses
    # to attach a volume to a pod in another datacenter, and the message does
    # not say that is what happened.
    want_dc = getattr(config, "RUNPOD_DATACENTER_ID", "").strip()
    if vol.get("dataCenterId") != want_dc:
        print(f"{BAD}config.py says RUNPOD_DATACENTER_ID = {want_dc!r}, but the "
              f"volume is in {vol.get('dataCenterId')!r}.")
        print("       A volume cannot move. Change config.py to match the volume.")
        problems.append("datacenter mismatch")
    else:
        print(f"{OK}config.py and the volume agree on the datacenter")

    if size and size < 20:
        print(f"{WARN}{size} GB is tight — the one-time model build peaks at "
              f"about 14 GB for NLLB-1.3B. Volumes can be grown, not shrunk.")

    # A branch that does not exist means the pod quietly serves whatever stale
    # copies are on the volume, which is the hardest kind of problem to notice.
    branch = getattr(config, "RUNPOD_REPO_BRANCH", "main")
    raw = (f"https://raw.githubusercontent.com/Shakhriyorbek/"
           f"speach2text-arabic-english-hungarian/{branch}/server/bootstrap.sh")
    try:
        req = urllib.request.Request(raw, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(req, timeout=20):
            print(f"{OK}branch {branch!r} has the server files on GitHub")
    except Exception:
        print(f"{BAD}branch {branch!r} has no server/bootstrap.sh on GitHub.")
        print("       The pod would fall back to whatever is already on the")
        print("       volume. Push the branch, or set RUNPOD_REPO_BRANCH.")
        problems.append("branch not published")

    if not getattr(config, "RUNPOD_GPU_TYPES", []):
        print(f"{BAD}RUNPOD_GPU_TYPES is empty — nothing to rent.")
        problems.append("no GPU types")

    # Anything already running is money being spent right now.
    live = [p for p in pods if p.get("desiredStatus") == "RUNNING"]
    if live:
        print()
        print(f"{WARN}{len(live)} pod(s) are RUNNING on this account right now:")
        for p in live:
            print(f"         {p.get('id')}  {p.get('name')}  "
                  f"${p.get('costPerHr')}/hr")
        print("       If you did not mean to leave these up, run STOP.bat or "
              "terminate them on the RunPod site.")
    else:
        print(f"{OK}no pods are running (nothing is being billed for compute)")

    print()
    if problems:
        print("NOT READY. Fix the above, then run this again.")
        return 1
    print("Settings look right. Nothing has been rented and nothing charged.")
    print()
    # What is actually ON the volume cannot be seen from here — reading it
    # needs a pod attached to it — so offer both next steps rather than
    # asserting which one applies.
    print("If the models are not on the volume yet, build them once on a CPU")
    print("pod:  python -m subtitles.pod --build-pod  (see server/README.md).")
    print("If they are, rehearse the whole GPU cycle:")
    print("      python -m subtitles.launcher --selftest")
    return 0


def recent() -> int:
    """What the GPU has actually been doing. Reads /recent on the live pod.

    Exists because RunPod's API cannot show a pod's console output, so when the
    question is "is the GPU transcribing correctly", there was nowhere to look
    except the laptop — which is the wrong place, since the laptop only ever
    sees what came back.
    """
    from subtitles.console import enable_utf8_console

    enable_utf8_console()
    pod_id, token = remembered(), remembered_token()
    if not pod_id:
        print("No pod is recorded as rented. Start one with START.bat.")
        return 1
    if not token:
        print(f"Pod {pod_id} is recorded but its token is not — it was rented")
        print("by a version that did not save it. Restart it with START.bat.")
        return 1

    url = f"{proxy_url(pod_id)}/recent"
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}",
                                               "User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            data = json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            print("This pod is running a server without /recent — restart it")
            print("with START.bat to pick up the current version.")
        else:
            print(f"Could not read it: HTTP {exc.code} {exc.reason}")
        return 1
    except Exception as exc:                # noqa: BLE001
        print(f"Could not reach the pod: {type(exc).__name__}: {exc}")
        return 1

    rows = data.get("recent") or []
    if not rows:
        print(f"Pod {pod_id} is up but has done nothing yet.")
        print("Nothing has been sent to it — check the laptop is actually")
        print("using the GPU, and that the microphone is picking up speech.")
        return 0

    print(f"Last {len(rows)} things the GPU did  (pod {pod_id})")
    print("=" * 74)
    for r in rows:
        if r.get("op") == "asr":
            print(f"  {r['t']}  ASR  {r['secs']:>4}s audio -> {r['ms']:>5}ms  "
                  f"[{r['mode']}/{r['lang']}]"
                  + (f"  dropped {r['dropped']}" if r.get("dropped") else ""))
            print(f"            {r['text'][:66]}")
        else:
            print(f"  {r['t']}  MT   {r['ms']:>5}ms  [{r.get('src')}]")
            print(f"            {r['text'][:66]}")
            print(f"         -> {r['out'][:66]}")
    print("=" * 74)
    asr = [r for r in rows if r.get("op") == "asr"]
    mt = [r for r in rows if r.get("op") == "mt"]
    if asr:
        print(f"  {len(asr)} transcriptions, mean {sum(r['ms'] for r in asr)//len(asr)}ms")
    if mt:
        print(f"  {len(mt)} translations,  mean {sum(r['ms'] for r in mt)//len(mt)}ms")
    return 0


def stock() -> int:
    """What is actually free in our datacenter, right now. Rents nothing.

    The REST API cannot answer this, so it asks the GraphQL one. Worth running
    before a khutbah: availability in a single datacenter moves minute to
    minute, and knowing there is nothing free is very different from finding
    out while people are arriving.
    """
    from subtitles.console import enable_utf8_console

    enable_utf8_console()
    dc = getattr(config, "RUNPOD_DATACENTER_ID", "")
    want = set(getattr(config, "RUNPOD_GPU_TYPES", []))

    query = ('query { gpuTypes { id memoryInGb lowestPrice(input:{gpuCount:1,'
             f'dataCenterId:"{dc}"}}) {{ uninterruptablePrice stockStatus }} }} }}')
    req = urllib.request.Request(
        "https://api.runpod.io/graphql",
        data=json.dumps({"query": query}).encode(),
        method="POST",
        headers={"Content-Type": "application/json",
                 "Authorization": f"Bearer {api_key()}",
                 "User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=40) as resp:
            rows = (json.loads(resp.read()).get("data") or {}).get("gpuTypes") or []
    except Exception as exc:                # noqa: BLE001
        print(f"Could not ask RunPod what is in stock: {exc}")
        return 1

    print(f"GPU availability in {dc}, right now")
    print("=" * 64)
    print("  (price is the LOWEST tier RunPod offers for that card; on SECURE")
    print("   you will pay more — the launcher prints the real rate when it")
    print("   rents. Measured: a card listed at $0.34 cost $0.72 on Secure.)")
    print()
    ours, others = [], []
    for g in rows:
        lp = g.get("lowestPrice") or {}
        if not lp.get("stockStatus"):
            continue
        row = (g["id"], g.get("memoryInGb") or 0,
               lp["stockStatus"], lp.get("uninterruptablePrice"))
        (ours if g["id"] in want else others).append(row)

    for gid, vram, st, price in sorted(ours, key=lambda r: (r[3] or 99)):
        print(f"  OK   {gid[:38]:38} {vram:>3}G  {st:<6} from ${price}")
    if not ours:
        print("  none of the cards in RUNPOD_GPU_TYPES are free.")
    if others:
        print()
        print("  Free, but NOT in your RUNPOD_GPU_TYPES list:")
        for gid, vram, st, price in sorted(others, key=lambda r: (r[3] or 99)):
            if vram >= 16:
                print(f"       {gid[:38]:38} {vram:>3}G  {st:<6} ${price}")
    print("=" * 64)
    if ours:
        print(f"{len(ours)} usable card(s) free. START.bat should work now.")
        return 0
    print("Nothing usable is free at this moment. START.bat will keep asking")
    print(f"for {getattr(config, 'RUNPOD_CAPACITY_RETRY_S', 180)}s before giving up —")
    print("availability changes minute to minute, so it is worth trying.")
    print("The subtitles work without the GPU either way, less accurately.")
    return 1


def build_pod_cmd() -> int:
    """Create the build box and print exactly what to do next."""
    from subtitles.console import enable_utf8_console

    enable_utf8_console()
    branch = getattr(config, "RUNPOD_REPO_BRANCH", "main")

    print("Renting a CPU box for the one-time model build...")
    try:
        info = create_build_pod()
    except PodError as exc:
        print(f"\nFAILED: {exc}")
        return 1

    pod_id = info["id"]
    flavor = info.get("cpuFlavorId") or "?"
    ram = info.get("memoryInGb") or 0
    print(f"\n  pod        : {pod_id}")
    print(f"  machine    : {flavor}, {ram or '?'} GB RAM, "
          f"{info.get('vcpuCount') or '?'} vCPU")
    if ram and ram < BUILD_MIN_RAM_GB:
        print(f"\n  WARNING: {ram} GB is below the {BUILD_MIN_RAM_GB} GB the NLLB")
        print(f"           conversion needs. It would be killed after the")
        print(f"           download. Terminate this pod and try again.")
    print(f"  volume     : mounted at /workspace")
    print(f"  cost       : ${info.get('costPerHr', '?')}/hour")
    print()
    print("=" * 70)
    print("NOW, IN YOUR BROWSER:")
    print()
    print(f"  1. Open  https://www.console.runpod.io/pods")
    print(f"  2. Find  {pod_id}  and open its web terminal")
    print(f"     (expand the pod -> Connect -> Web Terminal)")
    print()
    print("  3. Paste this into that terminal — NOT into this one:")
    print()
    print(f"     curl -fsSL https://raw.githubusercontent.com/Shakhriyorbek/"
          f"speach2text-arabic-english-hungarian/{branch}/server/bootstrap.sh"
          f" | BRANCH={branch} bash -s -- --build-nllb")
    print()
    print("  4. Watch it. About 40 minutes, mostly silent during downloads.")
    print("     When it prints '=== Done ===', come back here.")
    print()
    print("  5. TERMINATE the pod — on the site, or run:")
    print(f"        python -m subtitles.stop_pod")
    print("=" * 70)
    print()
    print("This box is billing from now until you terminate it (a few cents")
    print("an hour). It has no GPU; that is deliberate — the conversion needs")
    print("RAM, not a GPU, and a GPU pod usually has less of it.")

    remember(pod_id)
    return 0


if __name__ == "__main__":
    import sys

    if "--build-pod" in sys.argv:
        sys.exit(build_pod_cmd())
    if "--stock" in sys.argv:
        sys.exit(stock())
    if "--recent" in sys.argv:
        sys.exit(recent())
    sys.exit(check())
