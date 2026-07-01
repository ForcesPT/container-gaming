# DpadCloud Container Gaming — Project State & Continuation Guide

> **Purpose:** This document captures everything a new AI session needs to continue
> the DpadCloud cloud-gaming container project. It documents what's built, what works,
> what doesn't, and the next steps (VirtualGL + gamescope).

---

## What This Project Is

A **lean (~8.3 GB) headless cloud-gaming container** that runs on Vast.ai GPU hosts.
It streams a virtual desktop + games to a browser via WebRTC (Selkies) or to a native
client via Moonlight (Sunshine). The container is designed for per-session provisioning
by a Fastify orchestrator (in `apps/api`).

## Architecture (B2 + B2b — clean lean rebuild)

```
User Browser ──(HTTPS)──▶ cloudflared tunnel ──▶ Selkies (127.0.0.1:16100)
                                                        │
                                         ┌──────────────┤
                                         ▼              ▼
                                    Xvfb display    coturn TURN
                                   (Mesa EGL)     (TCP 73478)
                                         │
                                    PulseAudio
                                   (null-sink)
                                         │
                              ┌──────────┼──────────┐
                              ▼          ▼          ▼
                           XFCE       Steam      Sunshine
                         desktop     (Proton)   (Moonlight host)
                                                  │
                                           Tailscale ──▶ Native Moonlight client

NVENC encoder: auto-selected at boot (1-frame test). nvh264enc if GPU supports it,
x264enc (software) fallback. On RTX 3060 mining-rig hosts, NVENC is unavailable
(host-level issue) — x264 fallback keeps the stream working.
```

## What Works (confirmed on Vast)

- ✅ **Browser click-and-play**: Selkies WebRTC + cloudflared HTTPS tunnel → gamepad + audio + video in browser
- ✅ **Audio**: PulseAudio headless null-sink (dummy/dummy.monitor) — pulsesrc captures silence reliably
- ✅ **TURN relay**: In-image coturn on Vast identity port 73478 (TCP only) — no Open Relay flakiness
- ✅ **Sunshine**: Running (native Moonlight host) for enthusiast path
- ✅ **Tailscale**: Installed + entrypoint hook (gated by TAILSCALE_AUTH_KEY)
- ✅ **Encoder auto-probe**: 1-frame gst-launch test → nvh264enc or x264enc
- ✅ **CUDA compat**: 05-configure-cuda.sh ported — cleans ldconfig, tries forward-compat (datacenter), falls back to minor-version compat
- ✅ **NVENC**: Works on RTX 3060 Ti, 3080 Ti (driver ~535), and **any single-GPU host on any driver** (`gpu_frac=1` — #1249 is multi-GPU-only). On multi-GPU hosts with only a slice assigned + driver 570/580, the **flexgrip interposer is now implemented (opt-in, pending Vast validation)** to fix #1249; x264 fallback remains the safety net. See "NVENC: What We Know".
- ✅ **Boot diagnostics**: NVENC/CUDA diag prints driver, visible GPUs, lib presence, compute_mode, cuInit, cuCtxCreate
- ✅ **Periodic log dump**: selkies.log + sunshine.log + pulse.log to stdout (Vast Logs tab) — no SSH needed

## What Doesn't Work Yet

- ❌ **VirtualGL**: Installed (3.1.4). `vglrun` routes GL to the GPU's EGL offscreen backend and blits to Xvfb. Boot test prints the GL renderer (`NVIDIA GeForce…` = GPU, `llvmpipe` = software fallback). Launchers: `vgl-steam` (native Linux GL), `proton-wined3d` (Windows DX9–11 via WineD3D+VGL — interim path that needs no Vulkan present surface), `vgl-test` (sanity check).
- ⏸ **gamescope**: DEFERRED (evaluated, not installed). Solves DXVK/Proton's Vulkan *present* on a headless host. On Ubuntu 22.04 the only jammy build is akdor 3.12.5-2 (Sept 2023, unsupported, dead-end on jammy). Current gamescope needs a base bump to Ubuntu 24.04 — but the earliest official `nvidia/cuda` image on 24.04 is 12.5.1, which forces host driver ≥555 (Max CUDA 12.5) and **narrows the Vast pool** (excludes driver 535/545/550, incl. the 3080 Ti hosts). Forward-compat only helps datacenter GPUs, not consumer RTX. Interim Windows-game path = **WineD3D (D3D→OpenGL) + vglrun** (no Vulkan present needed); revisit gamescope only if WineD3D perf is insufficient. Ruled out: Bazzite/CachyOS Handheld (bare-metal OS images, need kernel+modeset+display — opposite of headless rented); cage/wlroots DIY (NVIDIA+wlroots finicky); DXVK headless WSI / lavapipe (immature / too slow).
- ❌ **NVENC on RTX 3060**: Likely a misdiagnosis — mining rigs are multi-GPU, so the failure was almost certainly #1249, not a 3060-specific defect. A single-GPU 3060 (`gpu_frac=1`) should give working NVENC; re-test pending. Orchestrator probe-and-select still wise.
- ❌ **Orchestrator integration**: The Fastify API (`apps/api`) doesn't yet provision this image. Needs: provision via Vast API, read boot log for tunnel URL + encoder probe, create named Cloudflare tunnels + per-session auth, return URL to website.
- ❌ **KDE Plasma**: Not installed (using XFCE). Optional UX upgrade — doesn't affect game rendering perf. Would need KWIN_COMPOSE=N (disable compositor on Xvfb).

## File Layout

```
dpadcloud/container-gaming/
├── Dockerfile              # FROM nvidia/cuda:${CUDA_VERSION}-runtime-ubuntu22.04 — ARG CUDA_VERSION=12.1.1 (wide) | 12.8.1 (RTX 50)
├── entrypoint.sh           # Boot orchestration (display-driver install, CUDA config, NVENC topology+flexgrip, Xvfb, PulseAudio, coturn, Sunshine, Selkies, cloudflared, Tailscale)
├── healthcheck.sh          # Checks Xvfb, pulseaudio, streamer (Selkies or Sunshine)
├── docker-compose.yml      # Local testing (NVIDIA runtime, ports, volumes)
├── deploy.sh               # build [12.1|12.8] /push/up/down/logs/status/shell/clean
├── configs/
│   └── sunshine/
│       └── sunshine.conf   # Tuned capture config (gamepad=x360, resolutions, fps, wan access)
├── scripts/
│   ├── install-display-drivers  # Ported from vast-ai/base-image — extracts matched .run OpenGL/EGL/Vulkan libs for compute-only Vast hosts
│   ├── nvenc_fix.c              # Vendored flexgrip interposer (NVENC #1249 multi-GPU fix) → /opt/dpadcloud/libnvenc_fix.so
│   ├── vgl-steam proton-wined3d vgl-test   # VirtualGL launchers
│   └── (joystick interposer is from the Selkies deb)
├── README.md               # Deploy instructions, env vars, architecture
└── docs/
    └── PROJECT_STATE.md    # This file
```

## Dockerfile Structure

```
# Build-time ARGs (one Dockerfile, two tags):
#   docker build --build-arg CUDA_VERSION=12.1.1 --build-arg CUDA_PKG=12-1 -t dpadcloud/gaming
#   docker build --build-arg CUDA_VERSION=12.8.1 --build-arg CUDA_PKG=12-8 -t dpadcloud/gaming:cuda12.8
ARG CUDA_VERSION=12.1.1
ARG CUDA_PKG=12-1
FROM nvidia/cuda:${CUDA_VERSION}-runtime-ubuntu22.04
ENV NVIDIA_DRIVER_CAPABILITIES=all     # Mount all host driver libs
ENV NVIDIA_VISIBLE_DEVICES (unset)     # Let Vast assign the GPU (avoids multi-GPU device-0 issue)
ENV DISPLAY=:0  PUID=1001  XDG_RUNTIME_DIR=/run/user/1001  PULSE_SERVER=unix:/run/user/1001/pulse/native

# Build args: CUDA_VERSION=12.1.1|12.8.1, CUDA_PKG=12-1|12-8 (one Dockerfile, two tags).
# GStreamer: latest Selkies release tarball (v1.6.2 = GStreamer 1.24.6). NOTE: 1.24.6's
#   nvcodec uses old NVENC preset GUIDs removed in NVENC 13 (driver>=570), so the
#   browser (Selkies) path falls back to x264enc on driver>=570 hosts. NVENC on
#   driver>=570 is handled by Sunshine (separate solution), NOT by upgrading GStreamer.
1. apt: i386 + display + audio + gaming deps (xfce4, pulseaudio, coturn, steam-installer, etc.)
2. User: dpad (uid 1001, sudo, audio/video/input/games groups)
3. cuda-nvrtc-${CUDA_PKG} + cuda-compat-${CUDA_PKG}   (NVRTC for nvh264enc, forward-compat for datacenter GPUs)
4. Steam (steam-installer)
5. Proton-GE (GE-Proton9-25, from GitHub releases)
6. Sunshine (sunshine-ubuntu-22.04-amd64.deb from GitHub)
7. Selkies-GStreamer (gstreamer GPL tarball v1.6.2 + python wheel + web app + joystick interposer)
8. cloudflared (static binary from GitHub)
9. Tailscale (install.sh)
9b. Vulkan loader + tools (diag only)
9c. VirtualGL 3.1.4 (GPU-accelerated GL into headless Xvfb)
9d. flexgrip nvenc_fix.c → /opt/dpadcloud/libnvenc_fix.so  (NVENC #1249 multi-GPU fix, opt-in at runtime)
10. pulseaudio pulseaudio-utils xsel (late apt install)
11. COPY configs/ + entrypoint.sh + healthcheck.sh + scripts/{vgl-steam,proton-wined3d,vgl-test,install-display-drivers}
12. EXPOSE 16100/tcp 3478/tcp 47989/tcp 47990/tcp 41641/udp
13. ENTRYPOINT ["/opt/dpadcloud/entrypoint.sh"]
```

## Entrypoint Boot Order

```
1. NVIDIA check (nvidia-smi)
2. install-display-drivers — extract matched .run OpenGL/EGL/Vulkan libs (compute-only Vast hosts)
3. configure_cuda() — clean ldconfig, try forward-compat, select CUDA ${CUDA_VERSION}
4. D-Bus (system + session)
5. Xvfb (Mesa EGL, 1920x1080x24, -ac -noreset -shmem)
6. XFCE desktop (xfwm4, xfsettingsd, xfce4-panel, xfdesktop — as user)
7. PulseAudio (headless null-sink: dummy + dummy.monitor, as user, not root)
8. coturn (TCP on VAST_TCP_PORT_73478 or 3478, lt-cred-mech, PUBLIC_IPADDR)
9. NVENC topology diag (#1249 check) + flexgrip auto-enable + assemble LD_PRELOAD (joystick + libnvenc_fix.so)
10. Sunshine (creds admin/pass, config from sunshine.conf, as user, under LD_PRELOAD)
11. Selkies (127.0.0.1:16100, encoder probe under LD_PRELOAD, TURN=coturn, basic auth, as user)
12. cloudflared (quick tunnel or named tunnel via CLOUDFLARED_TUNNEL_TOKEN)
13. Tailscale (if TAILSCALE_AUTH_KEY set)
14. Status banner (tunnel URL, encoder, DPAD_NVENC_FIX, TURN, Moonlight info)
15. Periodic log dump (selkies.log + sunshine.log + pulse.log → stdout, every 30s)
16. Health loop (restart Xvfb if dead, warn on service deaths)
```

## Vast.ai Deploy

### Offer filter (NVENC-safe — corrected; #1249 is multi-GPU-only)
```
# NVENC works natively if ANY of:
#   gpu_frac=1          (single-GPU OR whole-machine: all /dev/nvidiaX mounted → no unreachable peers; any driver)
#   cuda_max_good<12.8  (driver <570, pre-regression)
#   driver_version>=610 (upstream fix)
# Plus the flexgrip interposer covers gpu_frac<1 (multi-GPU slice) on driver 570..609.
compute_cap>=750 gpu_display_active=false rentable=true verified=true
```
Cheapest NVENC: `gpu_frac=1 num_gpus=1` (single-GPU machines, any driver incl. 570/580).
RTX 50/Blackwell requires the **cuda-12.8 image variant** (driver ≥570) — use the flexgrip path there.

### Docker Options (browser streaming)
```
-p 73478:73478 -e SUNSHINE_PASSWORD=pass -e SELKIES_BASIC_AUTH_USER=dpad -e SELKIES_BASIC_AUTH_PASSWORD=pass
```

### Docker Options (+ native Moonlight enthusiast)
```
-p 73478:73478 -p 41641:41641/udp -e SUNSHINE_PASSWORD=pass -e SELKIES_BASIC_AUTH_USER=dpad -e SELKIES_BASIC_AUTH_PASSWORD=pass -e TAILSCALE_AUTH_KEY=tskey-...
```

### Docker Options (production — named Cloudflare tunnel + your domain)
```
-e CLOUDFLARED_TUNNEL_TOKEN=<token> -e CLOUDFLARED_HOSTNAME=https://play-<id>.dpadcloud.com -e SUNSHINE_PASSWORD=... -e SELKIES_BASIC_AUTH_PASSWORD=<session-token> -p 73478:73478
```

### ⚠️ Do NOT use these Vast CLI flags
- `--jupyter` — overrides entrypoint, kills our services
- `--ssh` — overrides entrypoint, kills our services
- `--direct` — only with --ssh
- `--onstart-cmd` — only needed if overriding entrypoint (we don't)
- `-p 73478:73478/udp` — Vast flags tcp+udp of same port as duplicate. TCP only.

## Key Env Variables

| Variable | Default | Purpose |
|---|---|---|
| `NVIDIA_DRIVER_CAPABILITIES` | `all` | Mount all host driver libs (compute, video, graphics, display) |
| `NVIDIA_VISIBLE_DEVICES` | (unset) | Let Vast assign the GPU. Do NOT set `=all` (multi-GPU hosts → device 0 wrong) |
| `SCREEN_RESOLUTION` | `1920x1080x24` | Xvfb screen (fixed at boot) |
| `SUNSHINE_PASSWORD` | `dpadcloud` | Sunshine Web UI / Moonlight pairing creds |
| `SELKIES_BASIC_AUTH_USER` | `dpad` | Browser login username |
| `SELKIES_BASIC_AUTH_PASSWORD` | `OPEN_BUTTON_TOKEN or dpadcloud` | Browser login password (per-session token in production) |
| `SELKIES_ENCODER` | (auto-probe) | Force encoder: nvh264enc, x264enc, etc. |
| `DPAD_NVENC_FIX` | `auto` | NVENC #1249 fix: `auto` (enable when host GPUs > mounted `/dev/nvidiaX` on driver 570..609), `1` (force on), `0` (force off). Uses `/opt/dpadcloud/libnvenc_fix.so`. |
| `SELKIES_TURN_PROTOCOL` | `tcp` | TURN protocol (TCP = one port, no relay range needed) |
| `CLOUDFLARED_TUNNEL_TOKEN` | (unset → quick tunnel) | Named Cloudflare tunnel token (production) |
| `CLOUDFLARED_HOSTNAME` | (unset) | Your domain for the named tunnel |
| `TAILSCALE_AUTH_KEY` | (unset → disabled) | Tailscale auth key for native Moonlight |
| `TAILSCALE_HOSTNAME` | `dpadcloud` | Tailscale hostname |

## Ports

| Port | Protocol | Purpose |
|---|---|---|
| 16100 | TCP | Selkies WebRTC (localhost only — cloudflared fronts it) |
| 73478 | TCP | Vast identity tag → coturn TURN (WebRTC media relay). Request as `-p 73478:73478` |
| 47989 | TCP | Sunshine (native Moonlight, over Tailnet or direct) |
| 47990 | TCP | Sunshine Web UI (HTTPS, self-signed) |
| 41641 | UDP | Tailscale WireGuard overlay |

## Audio: Why PulseAudio (not PipeWire)

PipeWire's null-sink monitor **suspends when idle** (no driver node → graph doesn't advance → pulsesrc times out → "Waiting for stream" overlay never clears). PulseAudio's null-sink monitor **synthesizes silence on demand** — pulsesrc captures immediately, no timeout. Ubuntu 22.04 defaults to PulseAudio anyway (PipeWire became default in 22.10+).

## NVENC: What We Know

- `NvEncOpenEncodeSessionEx` returns `NV_ENC_ERR_UNSUPPORTED_DEVICE` (error code 2) on some hosts.
- CUDA works (`cuInit=0`, `cuCtxCreate=0`), `libnvidia-encode.so.1` present, `compute_mode=Default`.
- **Works on**: RTX 3060 Ti, 3080 Ti (driver ~535), datacenter GPUs (with cuda-compat forward-compat).
- **Fails on**: multi-GPU hosts on driver 570/580 where the container has only a SLICE of the host (nvidia-container-toolkit #1249). **Single-GPU hosts (`gpu_frac=1`) are IMMUNE on any driver** — `GET_ATTACHED_IDS` returns 1 GPU → no peer-init → NVENC works natively. RTX 3060 "mining-rig" failures (driver 570, 2 hosts) were almost certainly #1249 too (mining rigs = multi-GPU), not a 3060-specific defect — a single-GPU 3060 should work (re-test pending).
- **NEW — driver 570/580 NVENC regression (CONFIRMED via on-host diagnostic; nvidia-container-toolkit#1249; not image-fixable)**: on RTX 3080 (driver 570.124) and RTX 4060 Ti (driver 580.95), `gst-inspect-1.0 nvh264enc` reports `element NOT FOUND` (plugin won't register) → image falls back to x264enc. Same image works on driver 535 (3080 Ti → `nvh264enc: OK`). This is **not** a stale registry (forcing a fresh rescan didn't help), **not** the standard NVENC version check (that fails on the *older* driver, not newer), and **not** a removed NVENC symbol. Root cause is **nvidia-container-toolkit#1249**: starting with driver 570, NVENC's userspace stack queries `/dev/nvidiactl` for all attached GPU IDs (`NV0000_CTRL_CMD_GPU_GET_ATTACHED_IDS`) — which returns *every host GPU* even inside a 1-GPU container — then takes a multi-GPU peer-init branch and tries to open the other GPUs' `/dev/nvidiaY` nodes (not mounted) → peer-init fails → NVENC won't come up. Open bug, assigned to NVIDIA, unfixed as of mid-2026. Selkies maintainer (ehfd) guidance: use a one-GPU host or driver ≤565.
  - **On-host diagnostic (RTX 3080 / driver 570.124) CONFIRMED class (b) — kernel peer-init, NOT a broken lib**: `gst-inspect` on the nvcodec `.so` shows the plugin LOADS and registers the CUDA elements (cudaconvert/cudascale/cudaupload/nvjpegenc) but **does NOT register the NVENC encode elements** (nvh264enc/nvh265enc) — gst-plugins-nvcodec gates those behind a runtime NVENC open-session probe that fails at plugin init. `libnvidia-encode.so.1` is healthy (`NvEncodeAPIGetMaxSupportedVersion ret=0`, ver 0xd0 = NVENC 13.0) and CUDA works (`cuInit=0`, `cuCtxCreate=0`), so the lib is fine — the failure is the NVENC open-session. Host topology: `nvidia-smi -L` shows 1 GPU but `/dev/nvidia0` + `/dev/nvidia1` are both mounted → **multi-GPU host**, the exact #1249 trigger. Vast's own `install-display-drivers` (matched-`.run` extraction of libnvidia-encode) does NOT help — the lib is already healthy (ret=0).
  - **LD_PRELOAD fix (flexgrip/nvidia-gpu-enumeration `libnvenc_fix.so`) — CORRECTED & IMPLEMENTED (opt-in, pending Vast validation)**: the earlier on-host test concluded "dead end on Vast" because it manually `rm /\​/dev/nvidia1` to force filtering, and that `rm` (deleting a runtime-managed device node) broke CUDA (`cuInit=CUDA_ERROR_NO_DEVICE`) — **not** the interposer. CUDA's `cuInit` does NOT go through `GET_ATTACHED_IDS`/`GET_ID_INFO`, so filtering the attached-IDs list cannot break CUDA; only the `rm` did. The current flexgrip code (May 2026) also has a `/proc`-based fallback (Strategy 2) that maps `gpuId`→PCI bus→`Device Minor` without calling `GET_ID_INFO` — so whether `GET_ID_INFO` returns `OBJECT_NOT_FOUND` on Vast may not even matter. We vendored the current source into `scripts/nvenc_fix.c`, build it as `/opt/dpadcloud/libnvenc_fix.so`, and auto-enable it (see "NVENC solution" below) when host GPU count > mounted device count on driver 570..609. **Open question to validate on a real Vast multi-GPU driver-570 host**: does NVENC register under the interposer with NO `rm`? If yes → multi-GPU 570/580 pool unlocked. If `GET_ID_INFO` failure still bites NVENC after filtering → extend the interposer to synthesize `GET_ID_INFO` (return `deviceInstance` = `Device Minor` from `/proc`). Watch driver 610.x for NVIDIA's upstream fix (rajatchopra: "610.x seems to have the fix").
  - **NVENC-safe offer predicate (CORRECTED)**: `gpu_frac==1` (single-GPU OR whole-machine → all `/dev/nvidiaX` mounted → no unreachable peers → NVENC works on ANY driver) **OR** `cuda_max_good<12.8` (driver <570, pre-regression) **OR** `driver_version>=610` (upstream fix). Cheapest: `gpu_frac=1 num_gpus=1`. The old policy (`driver<570` only) wrongly excluded every single-GPU host on driver 570/580 — a large, cheap pool that's actually immune. Plus the flexgrip interposer (below) now covers the `gpu_frac<1` multi-GPU slice case on 570..609.
  - **NVENC solution IMPLEMENTED (pending Vast validation)**: `scripts/nvenc_fix.c` (vendored flexgrip) → `/opt/dpadcloud/libnvenc_fix.so`; entrypoint auto-enables it when host GPU count > mounted `/dev/nvidiaX` count on driver 570..609 (override `DPAD_NVENC_FIX=1|0|auto`); prepended to `LD_PRELOAD` before Sunshine AND the Selkies encoder probe so both benefit; `NVENC_FIX_DEBUG=1` logs `[nvenc_fix]` to stderr. Worst case unchanged (x264 fallback). See https://github.com/NVIDIA/nvidia-container-toolkit/issues/1249.
  - **CONFIRMED on-host (RTX 3060 / driver 595 / CUDA 13.2): GStreamer 1.24.6 (latest Selkies tarball = v1.6.2) cannot drive nvh264enc on NVENC 13** — element registers (open-session OK) but encode fails with `Selected preset not supported`. Root cause: 1.24.6's nvcodec uses the OLD NVENC preset GUIDs (hq/hp/low-latency…) which NVIDIA REMOVED in NVENC API 13 (driver ≥570). Every preset the 1.24.6 enum exposes (default/hp/hq/low-latency/p4…) FAILs. This is a SECOND, distinct failure from #1249 (which is multi-GPU-only and fails at open-session, not preset). The latest Selkies release (v1.6.2, Aug 2024) and `main` (1.24.12) both still bundle 1.24.x; no prebuilt 1.26.x nvcodec tarball exists.
  - **DECISION: do NOT upgrade GStreamer (Path B abandoned)**. Building GStreamer 1.26.7 in-image was implemented then reverted (too heavy a build for the benefit, and the browser path is secondary). Instead: the **browser (Selkies) path keeps the 1.24.6 tarball and falls back to `x264enc` on driver ≥570** (NVENC 13) hosts — still playable, CPU-encoded. **NVENC hardware encoding on driver ≥570 hosts is handled by Sunshine** (native Moonlight path; Sunshine's FFmpeg `h264_nvenc` was confirmed working on the 3060/driver-595 even where Selkies nvh264enc failed). flexgrip (step 9d) remains for the #1249 multi-GPU case on Sunshine's NVENC path. So: browser = x264 on driver≥570 (NVENC on driver≤565); native Moonlight = Sunshine NVENC on all drivers (with flexgrip on multi-GPU driver 570+).
  - **Browser-NVENC via moonlight-web-stream (DEFERRED — attempted then reverted, try later):** to give the *browser* path hardware NVENC on driver≥570 (instead of x264), evaluated bridging Sunshine's `h264_nvenc` to the browser over WebRTC with [moonlight-web-stream](https://github.com/MrCreativ3001/moonlight-web-stream) (no Tailscale needed; reuses our coturn TURN + cloudflared HTTPS; Sunshine is the encoder, mws web-server is the WebRTC bridge). It was wired in (Dockerfile/entrypoint/configs) then REVERTED to the Selkies baseline. Blocker: the upstream prebuilt `x86_64-unknown-linux-gnu` binary is built on ubuntu 24.04 (needs glibc ≥2.39) and won't run on our 22.04 base; switching the base to 24.04 requires CUDA 12.8 (driver ≥570 only → narrows the pool) AND noble's `t64` package renames (`libasound2`→`libasound2t64`, `libgl1-mesa-glx` removed, `libvpx7`→`libvpx9`, likely `libssl3`/`libpulse0`/`libva2`/`libvdpau1`/`libgtk-3-0` t64) broke the 22.04-era apt list. Two revisit paths: **(A)** build moonlight-web-stream from source on ubuntu 22.04 (Rust nightly + npm build stage) → keeps the wide `cuda12.1` pool (preferred for coverage, ~15 min cached build); **(B)** a separate `cuda12.8`/ubuntu24.04 variant with the prebuilt binary (driver≥570 only, no build). Current shipped state = Selkies baseline; working images: `forcespt/dpadcloud-gaming:cuda12.1` and `:cuda12.8_RTX5000`.
- **Now partly fixable in the image** via the flexgrip interposer (multi-GPU slice case); single-GPU hosts need no fix; only a genuinely host-broken NVENC (rare) stays on x264.
- **Image auto-falls back to x264enc** (software) — stream works everywhere.
- **Forward-compat** (cuda-compat-12-1) installed: on datacenter GPUs, `configure_cuda()` tries compat libs (cuInit test) → if pass, uses matched NVENC libs → may fix UNSUPPORTED_DEVICE. On consumer GPUs, compat fails → host libs used.

## Key Decisions Made

1. **Base: `nvidia/cuda:${CUDA_VERSION}-runtime-ubuntu22.04`** — now parameterized (one Dockerfile, two tags): `12.1.1` (driver ≥525, widest pool, no RTX 50) and `12.8.1` (driver ≥570, RTX 50/Blackwell). 12.1 ≤ every host's Max CUDA via filter; 12.8 is required for sm_120 and puts us in the #1249 range (flexgrip handles it). Not vastai/base-image (that's a ~20GB ML image; we stay lean ~8.3GB) but we ported its `install-display-drivers` for compute-only hosts.
2. **PulseAudio (not PipeWire)** — null-sink monitor captures silence reliably. PipeWire's graph suspends without a driver node.
3. **TCP TURN (not UDP)** — one exposed port, no relay range needed under Vast's 64-port limit. Vast's own image uses TCP TURN on 73478 too.
4. **cloudflared (not Instance Portal/Caddy)** — outbound tunnel, no inbound ports for browser. Simpler, leaner. Production: named tunnel + your domain.
5. **NVIDIA_VISIBLE_DEVICES unset** — on multi-GPU Vast hosts, `=all` makes the encoder grab device 0 which may not be the assigned GPU. Letting Vast assign keeps device 0 = assigned.
6. **NVIDIA_DRIVER_CAPABILITIES=all** — mounts all host driver libs. Simplest, guarantees nothing missing for NVENC or VirtualGL.
7. **cuda-compat (parameterized)** — forward-compat for datacenter GPUs (`cuda-compat-${CUDA_PKG}`). No-op on consumer. Can't hurt.
8. **Encoder auto-probe (1-frame test)** — runtime test (not gst-inspect) catches present-but-broken NVENC. Falls back to x264enc gracefully.
9. **flexgrip NVENC fix (opt-in, auto on multi-GPU slices)** — fixes #1249 on driver 570..609 so we can support RTX 50 (CUDA 12.8) + multi-GPU hosts. Worst case = x264 fallback (no regression).
10. **install-display-drivers (ported from vast-ai/base-image)** — extracts matched .run graphics libs for compute-only Vast hosts where libGL/EGL/Vulkan are missing (de-risks the VirtualGL path).

---

## Status: VirtualGL DONE · gamescope DEFERRED · NVENC #1249 fix (flexgrip) IMPLEMENTED · GStreamer 1.24.6 kept (browser=x264 on driver≥570, Sunshine=NVENC) · NEXT = validate Sunshine NVENC path + orchestrator

### What was built (NVENC #1249 fix + display drivers + CUDA matrix)
- **Dockerfile**: `ARG CUDA_VERSION`/`ARG CUDA_PKG` → build two tags: `12.1.1` (wide pool) and `12.8.1` (RTX 50/Blackwell, driver ≥570). `9d` builds vendored `scripts/nvenc_fix.c` → `/opt/dpadcloud/libnvenc_fix.so` (flexgrip interposer).
- **entrypoint.sh**: calls `install-display-drivers` (graphics libs for compute-only hosts); `configure_cuda()` now uses `readlink -f /usr/local/cuda` (works for both 12.1 + 12.8); new NVENC topology diag (`/proc` GPU count vs mounted `/dev/nvidiaX`) auto-enables `DPAD_NVENC_FIX` on multi-GPU slices + driver 570..609; `LD_PRELOAD` (flexgrip + joystick) assembled before Sunshine AND the encoder probe so both benefit; Sunshine launch now re-exports `LD_PRELOAD`.
- **deploy.sh**: `build [12.1|12.8]` and `CUDA_VARIANT=12.8` env; `cuda12.8` tag for the RTX-50 variant.
- **VirtualGL** (earlier): `9b` Vulkan loader/tools (diag), `9c` VirtualGL 3.1.4. Launchers `vgl-steam`, `proton-wined3d`, `vgl-test`.

### What was built (VirtualGL)
- **Dockerfile**: `9b` Vulkan loader/tools (diag), `9c` VirtualGL 3.1.4 deb layer.
- **entrypoint.sh**: sets `VGL_DISPLAY=egl`/`VGL_REFRESHRATE=60`, runs a boot-time `vglrun glxinfo -B` test printing the GL renderer, and adds graphics-libs + Vulkan ICD diagnostics.
- **Launchers** (`/opt/dpadcloud/`): `vgl-steam`, `proton-wined3d` (`PROTON_USE_WINED3D=1` + `vglrun` — no Vulkan present surface needed), `vgl-test`.

### Why gamescope was deferred
gamescope gives DXVK/Proton a Vulkan *present* surface on a headless host. Without it DXVK can *render* on the GPU but can't *present* (no `VkSurfaceKHR`). On Ubuntu 22.04 the only jammy build is akdor `3.12.5-2` (Sept 2023, unsupported). Current gamescope needs Ubuntu 24.04 — but the earliest official `nvidia/cuda` image on 24.04 is **12.5.1**, forcing host driver ≥555, which narrows the Vast pool. So interim Windows path = **WineD3D + vglrun** (DX9–11 only; DX12 needs vkd3d-proton → same wall). Decision gate: validate WineD3D+VGL on real titles; revisit gamescope only if perf insufficient.

### NEXT steps (in order)
1. **Validate the Sunshine-NVENC path on a driver-570 host** (the chosen NVENC solution). Rebuild the reverted image (Selkies 1.24.6 tarball restored; flexgrip + install-display-drivers + CUDA ARGs intact): `docker build --build-arg CUDA_VERSION=12.8.1 --build-arg CUDA_PKG=12-8 -t forcespt/dpadcloud-gaming:cuda12.8 .` (fast — no gstreamer build). Rent a driver-570 host, connect via Moonlight (needs TAILSCALE_AUTH_KEY or direct Sunshine 47989/47990), and confirm Sunshine streams with hardware `h264_nvenc`/`hevc_nvenc`. Read `/tmp/sunshine.log` (already in the periodic log dump) for `Found H.264 encoder: h264_nvenc`. **Browser (Selkies) on the same host will show `Selected encoder: x264enc`** — that is expected now (1.24.6 vs NVENC 13); the browser path is the x264 fallback, the low-latency NVENC path is Sunshine/Moonlight.
   - **multi-GPU driver 570..609, 1-GPU slice** (`gpu_frac<1`): Sunshine's FFmpeg nvenc ALSO hits #1249 peer-init — flexgrip auto-enables (`DPAD_NVENC_FIX: ENABLED`, LD_PRELOAD now applied to the Sunshine launch too) and should fix it. Confirm `/tmp/sunshine.log` shows `h264_nvenc` working + boot log shows `[nvenc_fix] filtered: N -> 1`. **Branch**: (A) Sunshine NVENC works → ship the two-path model (browser=x264/Sunshine=NVENC on driver>=570). (B) Sunshine NVENC fails on multi-GPU despite flexgrip → check `[nvenc_fix] GET_ID_INFO status=0x1f` and extend `nvenc_fix.c`.
   - **single-GPU driver ≥570** (`gpu_frac=1`): Sunshine NVENC should work natively (flexgrip disabled, no #1249). Confirms the 3060/driver-595 case (where Sunshine `h264_nvenc` was already seen working).
   - **driver ≤565 host** (e.g. 3080 Ti @535): both browser nvh264enc AND Sunshine nvenc work (regression check).
2. **Validate gaming on Vast** — `vgl-test`, a native Linux title under `vgl-steam`, a Windows DX9–11 title under `proton-wined3d`, a DX12 title (expected fail until gamescope). Capture encoder + fps + latency. **Gate:** WineD3D good enough → ship MVP; else revisit gamescope.
3. **Orchestrator** (see below) — Vast provider in `apps/api` with the NVENC-safe offer predicate + per-GPU CUDA-variant selection (RTX 50 → `cuda12.8`, else `latest`) + routing (browser click-and-play via Selkies; low-latency via Sunshine/Moonlight).
4. (Later, data-driven) **Present-surface decision** — gamescope / 24.04 bump / cage, to unlock true DXVK + DX12 + DLSS.

---

## Reference: VirtualGL + gamescope install (historical — VGL done, gamescope deferred)

### VirtualGL (native OpenGL apps)

**Purpose:** Intercepts GL calls → renders on GPU (EGL offscreen) → blits to Xvfb. Without VGL, GL apps use Mesa software (llvmpipe) on Xvfb → CPU rendering → slow games.

**Install:**
```dockerfile
# VirtualGL 3.1.x from GitHub releases (amd64 .deb)
RUN cd /tmp && wget -q "https://github.com/VirtualGL/virtualgl/releases/download/3.1.4/virtualgl_3.1.4_amd64.deb" \
    && dpkg -i virtualgl_*.deb || true && apt-get install -f -y \
    && rm -f virtualgl_*.deb
```

**Configure (in entrypoint):**
```bash
export VGL_DISPLAY=egl        # Headless EGL backend (no real display needed)
export VGL_REFRESHRATE=60
# vglrun <app> redirects GL to the GPU
# e.g.: vglrun steam, vglrun glxgears (test)
```

**Verify:**
```bash
# As user, test VGL works:
su - dpad -c "DISPLAY=:0 VGL_DISPLAY=egl vglrun glxgears -info" 2>&1 | head -5
# Should show "GL_RENDERER: NVIDIA GeForce RTX ..." (not llvmpipe)
```

**Integration:**
- Launch desktop apps with `vglrun` (or use Vast's vgl-desktop-patcher approach: rewrite .desktop Exec= lines to prepend `vglrun`).
- Steam native Linux games: launch with `vglrun steam`.
- For the desktop itself: optionally `vglrun xfwm4` (compositor on GPU) — but Vast disables KWin compositor (KWIN_COMPOSE=N). For XFCE, xfwm4 with `--compositor=off` is fine without vglrun (compositor is off anyway).

### gamescope (Steam/Proton — Windows games)

**Purpose:** Valve's micro-compositor. Creates a GPU-backed virtual Wayland session for Proton/DXVK. This is what Bazzite/SteamOS use for "gaming mode." Solves the headless-GPU Vulkan/DXVK rendering problem (Vulkan needs a present surface; on headless Xvfb there's none; gamescope provides one).

**Install (Ubuntu 22.04):**
```dockerfile
# gamescope from Ubuntu 22.04 repos (may need backport or build from source)
RUN apt-get update && apt-get install -y --no-install-recommends gamescope \
    && rm -rf /var/lib/apt/lists/*
# OR build from source if the repo version is too old:
# gamescope requires: meson, ninja, wayland-protocols, libx11, libxcb, libdrm, libpipewire, libwlroots, vulkan
```

**Usage:**
```bash
# Launch Steam in gamescope (gaming mode):
gamescope -W 1920 -H 1080 -r 60 -- steam -tenfoot
# Or a specific Proton game:
gamescope -W 1920 -H 1080 -- steam steam://rungameid/<APP_ID>
```

**Integration:**
- gamescope creates a virtual Wayland session, renders on GPU (Vulkan), presents to a surface.
- Sunshine/Selkies capture the Xvfb where gamescope's output is displayed (gamescope can output to X11).
- OR gamescope can use its own DRM backend — but for our X11-capture pipeline, X11 output is simpler.

### What to Add to the Dockerfile

After the existing layers (Selkies, cloudflared, Tailscale), add:

```dockerfile
# =============================================================================
# VirtualGL (GPU-accelerated GL rendering into headless Xvfb)
# =============================================================================
RUN cd /tmp && wget -q \
      "https://github.com/VirtualGL/virtualgl/releases/download/3.1.4/virtualgl_3.1.4_amd64.deb" \
      -O vgl.deb && dpkg -i vgl.deb || true && apt-get install -f -y --no-install-recommends \
    && rm -f vgl.deb && rm -rf /var/lib/apt/lists/*

# =============================================================================
# gamescope (Valve's micro-compositor for Steam/Proton headless GPU rendering)
# =============================================================================
RUN apt-get update && apt-get install -y --no-install-recommends gamescope \
    && rm -rf /var/lib/apt/lists/*
```

### What to Add to the Entrypoint

After Xvfb starts, before launching apps:

```bash
# VirtualGL config
export VGL_DISPLAY=egl
export VGL_REFRESHRATE=60

# Test VGL (prints GPU renderer if working, llvmpipe if not)
if command -v vglrun >/dev/null 2>&1; then
    VGL_RESULT=$(as_user "DISPLAY=${DISPLAY_NUM} VGL_DISPLAY=egl vglrun glxinfo -B 2>/dev/null | grep 'OpenGL renderer' || echo 'VGL test failed'")
    echo "    VirtualGL: ${VGL_RESULT}"
fi
```

### NVIDIA Graphics Libs Check

Add to the NVENC/CUDA diag:
```bash
echo "    --- VGL graphics libs ---"
for lib in /usr/lib/x86_64-linux-gnu/libGL.so.1 /usr/lib/x86_64-linux-gnu/libEGL.so.1; do
    [ -e "$lib" ] && echo "    present: $lib" || echo "    MISSING: $lib"
done
```

If libGL/libEGL are MISSING, the `graphics` capability (part of `NVIDIA_DRIVER_CAPABILITIES=all`) didn't mount them. On Vast, this should work (all caps). If not, the NVIDIA libs might be at a different path (check `nvidia-smi -q | grep -i driver` or `ldconfig -p | grep -i nvidia | grep -iE 'libGL|libEGL'`).

### gamescope + Proton Notes

- gamescope renders via Vulkan (DXVK translates D3D→Vulkan). On a headless GPU (gpu_display_active=false), gamescope provides the Vulkan present surface that DXVK needs.
- gamescope can output to X11 (our Xvfb) or DRM. For our X11-capture pipeline (ximagesrc), X11 output is simplest.
- gamescope + Sunshine: Sunshine can capture the gamescope output window on Xvfb.
- gamescope + Selkies: Selkies captures Xvfb via ximagesrc; gamescope's X11 output appears on Xvfb → captured.
- For the product: the orchestrator could launch games in gamescope automatically, or the user launches via the desktop (Steam in Big Picture mode under gamescope).

### Testing VGL After Install

```bash
# On a Vast GPU host, after relaunch:
# 1. Check the boot log for "VirtualGL: OpenGL renderer string"
#    Should show "NVIDIA GeForce RTX ..." (GPU) not "llvmpipe" (software)
# 2. In the browser stream (Selkies), open a terminal and run:
#    vglrun glxgears
#    Should run smoothly (60fps) if VGL works
# 3. Launch a Steam game with:
#    gamescope -W 1920 -H 1080 -r 60 -- steam -tenfoot
#    Should render on GPU via Vulkan/DXVK
```

---

## After validation on Vast: The Orchestrator (next big step)

The Fastify API in `apps/api` needs to:

1. **Provision**: `vastai create instance` with the DpadCloud image + Docker Options.
2. **Read boot log**: Parse the Vast Logs tab (or use `vastai execute` / the API) for:
   - `Selected encoder:` (nvh264enc or x264enc → probe-and-select for NVENC hosts)
   - `Tunnel URL:` (the cloudflared trycloudflare URL — for MVP)
   - `Tailnet IP:` (if Tailscale enabled)
3. **Create named tunnel** (production): Use Cloudflare API to create a tunnel + DNS CNAME per session. Pass the token to the instance.
4. **Per-session auth**: Set `SELKIES_BASIC_AUTH_PASSWORD` to a session token. The website passes it (or embeds in the URL).
5. **Return URL to website**: `https://play-<id>.dpadcloud.com` → website opens in new tab.
6. **Monitor**: Health check the instance; destroy on idle timeout or user logout.

### Vast API for provisioning

```typescript
// In apps/api/src/providers/vast.ts (currently has a basic Vultr provider)
// Add a Vast.ai provider:
// 1. Search offers: vastai search offers 'compute_cap>=750 cuda_max_good>=12.1 gpu_display_active=false'
// 2. Create instance: vastai create instance <offer_id> --image <image> --env '<docker_options>' --disk 32
// 3. Poll for running: vastai show instance <id> --raw
// 4. Read logs for tunnel URL + encoder probe
// 5. Destroy: vastai destroy instance <id>
```

### Per-session flow

```
1. User clicks "Play Game" on dpadcloud.com
2. Fastify orchestrator:
   a. Searches Vast offers (filter for NVENC-capable GPUs)
   b. Creates instance with DpadCloud image + per-session env (auth token, tunnel token)
   c. Polls until running
   d. Reads boot log for tunnel URL + encoder
   e. If encoder=x264enc and NVENC required: destroy + reprovision (or accept)
   f. Returns { url: "https://play-<id>.dpadcloud.com", encoder: "nvh264enc" }
3. Website opens the URL in a new tab
4. User plays (browser + gamepad, HTTPS secure context)
5. On logout/idle: orchestrator destroys the instance
```

---

## Vast.ai Patterns We Ported (from vastai/base-image and vastai/linux-desktop)

1. **`05-configure-cuda.sh`** → `configure_cuda()` in entrypoint: clean ldconfig, try forward-compat, select CUDA ≤ host Max CUDA.
2. **`NVIDIA_DRIVER_CAPABILITIES=all`** → mount all host driver libs.
3. **`NVIDIA_VISIBLE_DEVICES` unset** → Vast assigns the GPU (avoids multi-GPU device-0 issue).
4. **PulseAudio null-sink** (from linux-desktop's pipewire, but we use pulseaudio for the monitor-capture fix) → `dummy` sink + `dummy.monitor` source for headless audio.
5. **coturn on identity port 73478 TCP** → `turnserver -p $VAST_TCP_PORT_73478 -X $PUBLIC_IPADDR --lt-cred-mech` (from linux-desktop's coturn.sh).
6. **Selkies bound to 127.0.0.1:16100** (from linux-desktop's selkies.sh) → cloudflared fronts it.
7. **Xvfb with Mesa EGL** (`__EGL_VENDOR_LIBRARY_FILENAMES=.../50_mesa.json`) → prevents NVIDIA EGL GBM segfault on virtual framebuffer (from linux-desktop's x-server.sh).
8. **cuda-compat-12-1** → forward-compat for datacenter GPUs (from base-image's cuda-compat package).

## Vast.ai vs vastai/linux-desktop vs vastai/base-image

| | Our image | vastai/base-image | vastai/linux-desktop |
|---|---|---|---|
| Base | nvidia/cuda:12.1.1-runtime-ubuntu22.04 | nvidia/cuda:*-cudnn-devel-ubuntu* | vastai/base-image + desktop layer |
| Size | ~8.3 GB | ~4-5 GB (no desktop) | ~17-20 GB (Blender, LibreOffice, KDE) |
| Desktop | XFCE (light) | None | KDE Plasma |
| Audio | PulseAudio (null-sink) | None | PipeWire (pipewire-pulse, wireplumber) |
| Selkies | ✅ + cloudflared | ❌ | ✅ (via Instance Portal/Caddy) |
| Sunshine | ✅ | ❌ | ✅ |
| Steam | ✅ + Proton-GE | ❌ | ✅ |
| coturn | ✅ (TCP 73478) | ❌ | ✅ (TCP 73478) |
| Tailscale | ✅ | ❌ | ✅ |
| Instance Portal | ❌ (cloudflared instead) | ✅ (Caddy + auth + tunnels) | ✅ |
| Supervisord | ❌ (custom entrypoint) | ✅ | ✅ |
| CUDA auto-config | ✅ (configure_cuda) | ✅ (05-configure-cuda.sh) | ✅ |
| Forward-compat | ✅ (cuda-compat-12-1) | ✅ | ✅ |
| Layer caching | Partial (nvidia/cuda base) | ✅ (optimized for Vast) | ✅ (extends base-image) |
| VirtualGL | ❌ (NEXT) | ❌ | ✅ (vgl-desktop-patcher) |
| gamescope | ❌ (NEXT) | ❌ | ❌ |