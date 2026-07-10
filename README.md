# DpadCloud Gaming Containers (Ubuntu 24.04 + CUDA 12.5.1)

Two slim cloud-gaming images, **one Dockerfile (multi-stage)**, both with
**hardware NVENC** and **Selkies-GStreamer** as the only browser stream.

| Tag | Target | Use-case | Size |
|-----|--------|----------|------|
| `forcespt/dpadcloud-gaming:dpad-heroic` | `vast-docker` | **Vast Docker** (no userns): Heroic desktop + Selkies — Epic/GOG/Amazon games + a general cloud desktop (XFCE + Firefox). Steam is blocked on Vast Docker (no userns → CEF crashes). | ~3.9 GB |
| `forcespt/dpadcloud-gaming:dpad-SteamOS` | `vast-vm` | **Vast KVM VM** (userns): Steam + gamescope (full Steam, Big Picture) + Selkies. No desktop. Fast-boot: the Steam client is pre-baked (~2.1 GB) so a fresh container reaches the stream URL in ~50 s. | ~7 GB |
| `…:dpad-SteamOS-rtx50` | `vast-vm` (+`--build-arg CUDA_VERSION=12.8.1`) | same, for **RTX 50 / Blackwell** (sm_120+, needs CUDA 12.8.1) | ~7 GB |

A shared `base` stage (Selkies + coturn + cloudflared + the NVENC #1249 fix +
`cuda-cudart`/`cuda-nvrtc` + display/audio/Mesa/X/Python) is built once and both
final stages extend it. An `interposer-builder` stage compiles the joystick
interposer + NVENC-fix `.so` so `gcc` never ships in the final images.

> **Why 24.04 + CUDA 12.5.1?** CUDA 12.5.1 runs on any driver ≥525 via [CUDA
> minor-version compatibility](https://docs.nvidia.com/deploy/cuda-compatibility/minor-version-compatibility.html)
> (the whole 12.x family shares the R525 baseline) → the wide Vast pool is
> preserved (offer filter `cuda_max_good>=12.1`). The base is
> `nvidia/cuda:12.5.1-BASE`, **not `-runtime`**: the runtime base's CUDA math
> libs (cublas/cusparse/cufft/npp/cusolver/curand, ~1.6 GB) are unused by
> NVENC/Selkies — only `cuda-cudart` (cudaupload/cudaconvert) + `cuda-nvrtc`
> (nvh264enc JIT) are installed. RTX 50/Blackwell needs the 12.8.1 variant
> (`--build-arg CUDA_VERSION=12.8.1 --build-arg CUDA_PKG=12-8`).

## What's inside

**Both images (base):** Selkies-GStreamer 1.24.6 (WebRTC + NVENC), coturn (TURN),
cloudflared (HTTPS tunnel), the flexgrip NVENC interposer (`libnvenc_fix.so` —
auto on multi-GPU slices, driver 570..609, fixes nvidia-container-toolkit #1249),
`cuda-cudart` + `cuda-nvrtc`, Xorg/Xvfb + Mesa/EGL + Vulkan loader, PulseAudio,
VirtualGL 3.1 (Xvfb debug path), the `dpad` user.

**`:dpad-heroic` adds:** XFCE4, **Heroic Games Launcher** (Epic+GOG+Amazon,
Electron `--no-sandbox` + umu/Proton-direct — no userns needed),
**Firefox** (real Mozilla `.deb`, apt-pinned over the Ubuntu snap stub),
accountsservice. Default `DPAD_LAUNCHER=heroic`. No Steam/gamescope/Proton.

**`:dpad-SteamOS` adds:** **Steam** (pre-bootstrapped at build time, fast-boot),
gamescope + PipeWire + wireplumber (the no-DRM-master multi-tenant path), the
`patch_selkies_pipewire` pipewiresrc zero-copy capture patch, the XTest
`dpad_input_patch`, the Steam license `zenity` wrapper. Default `DPAD_GAMESCOPE=1`.
No desktop/Heroic/Firefox. **GE-Proton is not baked in** — native Steam downloads
its own Proton at runtime.

**Removed (both images — Selkies is the only stream):** moonlight-web-stream,
Sunshine, Tailscale/native-Moonlight, steamcmd, dpad-launch, bubbleroot/proot,
the GE-Proton pre-bake, the CUDA math libs, snapd, and the build toolchain.

## Build & push

```bash
cd dpadcloud/container-gaming
# Vast Docker (Heroic desktop + Selkies)
docker build --target vast-docker -t forcespt/dpadcloud-gaming:dpad-heroic .
docker push   forcespt/dpadcloud-gaming:dpad-heroic
# Vast VM (Steam/gamescope + Selkies, fast-boot)
docker build --target vast-vm      -t forcespt/dpadcloud-gaming:dpad-SteamOS .
docker push   forcespt/dpadcloud-gaming:dpad-SteamOS
# RTX 50 / Blackwell variant of the VM tag (CUDA 12.8.1) — only if you use RTX 50
docker build --target vast-vm --build-arg CUDA_VERSION=12.8.1 --build-arg CUDA_PKG=12-8 \
  -t forcespt/dpadcloud-gaming:dpad-SteamOS-rtx50 .
docker push   forcespt/dpadcloud-gaming:dpad-SteamOS-rtx50
```

## Deploy

### Vast Docker → `:dpad-heroic`

**NVENC-safe offer predicate** (`#1249` is multi-GPU-only; single-GPU hosts are
immune on any driver):
```
compute_cap>=750 cuda_max_good>=12.1 gpu_display_active=false rentable=true verified=true
```
Cheapest NVENC: `gpu_frac=1 num_gpus=1` (single-GPU machines, any driver).

**Docker Options** (Selkies-only — coturn on the standard TURN port `3478`,
**TCP**, no `--privileged` needed; `--ulimit` covers hosts with low hard caps):
```
-p 22:22 -p 3478:3478 -e SELKIES_BASIC_AUTH_USER=dpad -e SELKIES_BASIC_AUTH_PASSWORD=pass \
  --security-opt seccomp=unconfined --security-opt apparmor=unconfined \
  --shm-size 2g --ulimit nproc=1048576:1048576 --ulimit nofile=1048576:1048576
```
- `DPAD_LAUNCHER=heroic` is the image default (no need to set it).
- The **dual-ICE TURN config is automatic** — the entrypoint writes an
  `rtc_config.json` with `turn:127.0.0.1:3478` (in-container peer) +
  `turn:<publicIp>:<extPort>` (browser) whenever a real public IP resolves, on
  **any** provider. No `DPAD_PROVIDER` needed. This fixes the old
  "Connection failed" (the container can't hairpin to its own public IP; the
  dual-ICE makes both peers TURN clients of the same coturn, which short-circuits
  the media internally).
- Vast maps `3478` to a random external port, injected as `VAST_TCP_PORT_3478`;
  the entrypoint auto-detects it. **Do NOT use the old `73478` identity tag** —
  73478 > 65535 is an invalid port (coturn wraps it to 7942 and it isn't mapped).

On boot, read the Vast **Logs** tab for:
```
▶ Browser click-and-play (Selkies):
    https://<random>.trycloudflare.com   (Login: dpad / <SELKIES_BASIC_AUTH_PASSWORD>)
```

### Vast KVM VM → `:dpad-SteamOS`

Use `scripts/vm-bootstrap.sh` run **inside** the VM — it auto-selects the tag by
GPU arch (`:dpad-SteamOS` or `:dpad-SteamOS-rtx50` for Blackwell), exposes one
coturn port per GPU, sets the gamescope + TURN env, launches one CDI container
per GPU, and prints each Selkies URL. Full recipe in
[`docs/VAST-VM-DEPLOY.md`](docs/VAST-VM-DEPLOY.md). (This is the validated
N-on-N-GPUs multi-tenant full-Steam path.)

### RunPod

RunPod is still supported (the entrypoint auto-detects `RUNPOD_POD_ID` and reads
`RUNPOD_PUBLIC_IP` / `RUNPOD_TCP_PORT_3478`). **Secure Cloud** (userns → full
Steam) → use `:dpad-SteamOS`; **Community Cloud** (no userns → Heroic) → use
`:dpad-heroic`. See [`docs/RUNPOD.md`](docs/RUNPOD.md). (mws/Sunshine/Tailscale
are removed — Selkies only.)

## Production (named Cloudflare tunnel)

Replace the quick tunnel with a named tunnel for a stable URL:
```
-e CLOUDFLARED_TUNNEL_TOKEN=<token> -e CLOUDFLARED_HOSTNAME=https://play-<id>.dpadcloud.com -p 3478:3478
```
The entrypoint runs the named tunnel for Selkies. Your orchestrator creates the
tunnel + DNS CNAME per session, provisions the instance with the token, and
returns the HTTPS URL. Per-session auth: set `SELKIES_BASIC_AUTH_PASSWORD` to a
session token (or front with Cloudflare Access).

## Config (env)

| Variable | Default | Purpose |
|----------|---------|---------|
| `SELKIES_BASIC_AUTH_USER` / `_PASSWORD` | `dpad` / `OPEN_BUTTON_TOKEN` | Selkies browser login gate (set the password to a per-session token in production) |
| `CLOUDFLARED_TUNNEL_TOKEN` + `_HOSTNAME` | (unset → quick tunnel) | Named tunnel (production) |
| `TURN_USERNAME` / `TURN_PASSWORD` | `turnuser` / `OPEN_BUTTON_TOKEN` | coturn creds (shared by the in-container peer + the browser) |
| `DPAD_COTURN_PORT` | auto (`3478`) | Internal port coturn binds; auto-detected from `VAST_TCP_PORT_3478`/`VAST_UDP_PORT_3478` |
| `DPAD_TURN_PUBLIC_IP` / `DPAD_TURN_EXTERNAL_PORT` / `DPAD_TURN_UDP_EXTERNAL_PORT` | auto | Override the browser-facing TURN address/port (auto from `PUBLIC_IPADDR` + `VAST_*_PORT_3478`) |
| `SELKIES_TURN_PROTOCOL` | `tcp` | TURN transport (match the exposed port protocol) |
| `SELKIES_ENCODER` | (auto: NVENC else x264) | Force the Selkies encoder |
| `DPAD_NVENC_FIX` | `auto` | flexgrip #1249 fix: `auto` (multi-GPU slice on driver 570..609), `1`, `0` |
| `DPAD_NVENC_FIX_DEBUG` | `0` | `1` to log the interposer's `GET_ATTACHED_IDS` filtering (noisy) |
| `DPAD_LAUNCHER` | `heroic` (`:dpad-heroic`) / `steam` (`:dpad-SteamOS` DFP path) | Frontend that auto-starts on the desktop. `heroic` / `steam` / `none` (bare desktop). Ignored when `DPAD_GAMESCOPE=1`. |
| `DPAD_HEROIC_ARGS` | `--no-sandbox` | Args for `heroic` (via `heroic-launch`) |
| `DPAD_GAMESCOPE` | `1` (`:dpad-SteamOS`) / `0` (`:dpad-heroic`) | `1` = gamescope headless + Steam (no DRM master → N-on-N-GPUs); `0` = Xorg/XFCE single-user path |
| `DPAD_VIDEO_SRC` | `pipewiresrc` (gamescope) / `ximagesrc` (Xorg) | Selkies capture source |
| `DPAD_INPUT_DISPLAY` | (auto, gamescope) | XTest input target (gamescope's Xwayland `:N`) |
| `SCREEN_RESOLUTION` | `1920x1080x24` | Xvfb/Xorg screen (fixed at boot) |
| `SUNSHINE_PASSWORD` | (unused) | Kept for back-compat only (Sunshine was removed) |

## Files

| File | Purpose |
|------|---------|
| `Dockerfile` | Multi-stage: `interposer-builder` → `base` → `vast-docker` (`:dpad-heroic`) / `vast-vm` (`:dpad-SteamOS`) |
| `entrypoint.sh` | Boot orchestration (shared): coturn → NVENC/flexgrip → display (Xorg or gamescope) → Selkies → cloudflared. mws/Sunshine/Tailscale blocks removed. |
| `scripts/vm-bootstrap.sh` | Vast VM host setup + one-CDI-container-per-GPU launcher (pulls `:dpad-SteamOS[-rtx50]`) |
| `scripts/nvenc_fix.c` | flexgrip NVENC #1249 interposer (built in `interposer-builder` → `/opt/dpadcloud/libnvenc_fix.so`) |
| `scripts/joystick_interposer_v162.c` | Patched Selkies v1.6.2 gamepad interposer (built for x86_64 + i386) |
| `scripts/{patch_selkies_pipewire.py, dpad_input_patch.py, patch_gst_web_cursors.sh}` | Selkies patches (pipewiresrc zero-copy / XTest input / cursor visibility) |
| `scripts/{vgl-steam,proton-wined3d,vgl-test,install-display-drivers,dpad-launch,heroic-launch}` | Launchers + matched `.run` graphics-lib extractor |
| `scripts/build-bootstrap-steam.sh` | Build-time Steam client pre-bootstrap (fast-boot, `vast-vm` only) |
| `docker-compose.yml` / `deploy.sh` / `healthcheck.sh` | Local dev helpers |
| `docs/` | `PROJECT_STATE.md` (history), `VAST-VM-DEPLOY.md` (VM runbook), `RUNPOD.md` (RunPod) |

## Notes / future
- **The two use-cases have near-zero heavy overlap** (desktop/Heroic vs Steam/gamescope), so they ship as two images instead of one 16 GB image carrying both.
- **Noble t64 apt renames** applied only where the lib was actually renamed in noble (`libasound2t64`, `libssl3t64`, `libgtk-3-0t64`); `libpulse0`/`libva2`/`libvdpau1`/`libwayland-egl1`/`libjack-jackd2-0` keep plain names, `libvpx7`→`libvpx9`.
- **Possible ~1 GB VM trim** (needs a runtime test): drop the `steam-libs-amd64/i386` apt packages — the pre-baked `steamrt64/32` already include the Steam Runtime, so the system steam-libs may be redundant.
- **Base-swap validation:** the `nvidia/cuda:-base` + `cuda-cudart` + `cuda-nvrtc` swap is build-validated; confirm Selkies `nvh264enc` inits on a real GPU on first boot (the math libs it replaces were unused by NVENC).