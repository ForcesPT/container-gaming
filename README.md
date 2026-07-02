# DpadCloud Gaming Container (Ubuntu 24.04 + CUDA 12.5.1)

A lean headless cloud-gaming container with **hardware NVENC** for low latency,
built on `nvidia/cuda:12.5.1-runtime-ubuntu24.04`.

**Why 24.04 + CUDA 12.5.1?**
- **24.04 (noble, glibc 2.39)** lets the prebuilt [moonlight-web-stream](https://github.com/MrCreativ3001/moonlight-web-stream) binary run natively — no from-source Rust build, no patchelf. That gives the **browser path hardware NVENC via Sunshine** on *all* drivers (Selkies' `nvh264enc` falls back to `x264enc` on driver ≥570 / NVENC 13).
- **CUDA 12.5.1 runs on any driver ≥525** via [CUDA minor-version compatibility](https://docs.nvidia.com/deploy/cuda-compatibility/minor-version-compatibility.html) (the whole 12.x family shares the R525 baseline). So the **wide Vast pool is preserved** — keep the offer filter at `cuda_max_good>=12.1` (it includes driver 535/545/550 hosts like the 3080 Ti). NVENC is driver-gated, not CUDA-gated, so the encoder story is unchanged. (A `12.8.1` variant for RTX 50/Blackwell is buildable with `--build-arg CUDA_VERSION=12.8.1 --build-arg CUDA_PKG=12-8`.)

**Three streaming paths, one image:**
- **Browser (primary)** → `moonlight-web-stream` (Sunshine `h264_nvenc`) → in-image **coturn TURN** → **Cloudflare Tunnel** (HTTPS → secure context → gamepad + pointer-lock + WebCodecs decode). No client install, browser NVENC on every driver.
- **Browser (fallback)** → `Selkies-GStreamer` (NVENC on driver <570, `x264enc` on ≥570) → same coturn → its own Cloudflare Tunnel.
- **Native enthusiast** → `Sunshine` (NVENC) + Moonlight over **Tailscale** (lowest latency, direct UDP over the Tailnet).

## What's inside
- Ubuntu 24.04 + CUDA 12.5.1 runtime (runs on driver ≥525 via minor compat → wide pool)
- Steam + Proton-GE · Sunshine (ubuntu-24.04 deb) · Selkies-GStreamer 1.24.6 · moonlight-web-stream v2.10
- PulseAudio headless null-sink (monitor captures silence reliably — PipeWire's suspends when idle)
- VirtualGL 3.1 (GPU GL into headless Xvfb) · coturn (TCP 3478 / Vast tag 73478) · cloudflared · Tailscale
- flexgrip NVENC interposer (auto on multi-GPU slices, driver 570..609 — fixes nvidia-container-toolkit #1249)
- Xvfb (Mesa EGL) + XFCE · ~8 GB image

## Build & push
```bash
cd dpadcloud/container-gaming
./deploy.sh build                         # -> dpadcloud/gaming:ubuntu24.04 (CUDA 12.5.1)
# RTX 50/Blackwell variant:
# ./deploy.sh build 12.8                   # -> dpadcloud/gaming:ubuntu24.04-rtx50 (CUDA 12.8.1)
./deploy.sh push YOUR_DOCKERHUB_USER      # push to Docker Hub
```

## Deploy on Vast.ai

**Pick a compatible host** — the NVENC-safe offer predicate (corrected: #1249 is multi-GPU-only; single-GPU hosts are immune on any driver):
```
compute_cap>=750 cuda_max_good>=12.1 gpu_display_active=false rentable=true verified=true
```
(CLI: `vastai search offers 'compute_cap>=750 cuda_max_good>=12.1 gpu_display_active=false'`)
`cuda_max_good>=12.1` keeps the wide pool (driver 535+); the 12.5.1 image runs on those via minor compat. Cheapest NVENC: `gpu_frac=1 num_gpus=1` (single-GPU machines, any driver). RTX 50 needs the `ubuntu24.04-rtx50` (CUDA 12.8) variant.

Docker Options (browser streaming — the 73478 identity tag is required, **TCP only**, so both mws and Selkies WebRTC media relay through the in-image coturn. Do NOT add `73478/udp` — Vast flags tcp+udp of the same port as a duplicate. `--privileged` is needed so Sunshine can create virtual input devices via `/dev/uinput` on stream start; `--ulimit nproc`/`nofile` cover hosts with low hard caps.):
```
--privileged --ulimit nproc=1048576:1048576 --ulimit nofile=1048576:1048576 -p 73478:73478 -e SUNSHINE_PASSWORD=pass -e SELKIES_BASIC_AUTH_USER=dpad -e SELKIES_BASIC_AUTH_PASSWORD=pass
```

On boot, read the boot log (Vast **Logs** tab). It prints **two Cloudflare quick-tunnel URLs**:
- `mws tunnel URL: https://<random>.trycloudflare.com` — **primary** (Sunshine NVENC). Auto-pairs at boot; log in (`dpad` / your `SUNSHINE_PASSWORD`), the `localhost` host is already paired, click it → launch an app.
- `Selkies tunnel URL: https://<random>.trycloudflare.com` — fallback (login `dpad` / `pass`).

> **If mws shows no video / `WebRTC negotiation timed out`:** check `/tmp/sunshine.log` for
> `Unable to create virtual touch screen: Operation not permitted` — that means `/dev/uinput`
> access is blocked by the device cgroup (the in-image `mknod` can't bypass it). `--privileged`
> is the fix (see `docs/PROJECT_STATE.md` → "CURRENT STATUS & BLOCKER").

Both URLs are HTTPS so the secure-context gaming APIs (gamepad, WebCodecs, keyboard lock) are enabled.

For the **native Moonlight** enthusiast path, add Tailscale:
```
-e TAILSCALE_AUTH_KEY=tskey-... -e TAILSCALE_HOSTNAME=dpadcloud-1 -p 41641:41641/udp
```
Then in Moonlight on your client → Add PC → the container's Tailnet IP (`100.x.x.x`, printed in the boot log) on port 47989, pair via Sunshine's Web UI.

> The Selkies encoder is auto-selected at boot by a 1-frame encode test: `nvh264enc` (NVENC) when the GPU is reachable, else `x264enc`. mws uses Sunshine's FFmpeg `h264_nvenc` directly (confirmed working on driver 595 where Selkies' `nvh264enc` failed) — so the browser NVENC path no longer depends on the GStreamer 1.24.6 / NVENC-13 preset situation.

## Production (your website → "Play Game" → browser)

Replace the quick tunnels with a **single named Cloudflare Tunnel** that has two ingress rules in the Cloudflare dashboard:
```
play-<id>.dpadcloud.com     -> http://localhost:8080    (mws, primary)
selkies-<id>.dpadcloud.com  -> http://localhost:16100   (fallback)
```
and pass the tunnel token + the primary hostname:
```
-e CLOUDFLARED_TUNNEL_TOKEN=<token> -e CLOUDFLARED_HOSTNAME=https://play-<id>.dpadcloud.com -p 73478:73478
```
The entrypoint runs the named tunnel for mws and a quick tunnel for Selkies (or, with a two-ingress named tunnel, both are covered). Your Fastify orchestrator creates the tunnel + DNS CNAME per session, provisions the Vast instance with the token, and returns the HTTPS URL for the website to open. Per-session auth: the first mws login creates the admin user (or front with Cloudflare Access); for the Selkies fallback set `SELKIES_BASIC_AUTH_PASSWORD` to a session token.

## Config (env)

| Variable | Default | Purpose |
|----------|---------|---------|
| `SCREEN_RESOLUTION` | `1920x1080x24` | Xvfb screen (fixed at boot) |
| `SUNSHINE_PASSWORD` | `dpadcloud` | Sunshine Web UI / creds |
| `SELKIES_BASIC_AUTH_USER` / `_PASSWORD` | `dpad` / `OPEN_BUTTON_TOKEN` | Selkies (fallback) login gate |
| `CLOUDFLARED_TUNNEL_TOKEN` + `_HOSTNAME` | (unset → quick tunnels) | Named tunnel (prod); hostname is the mws/primary URL |
| `TAILSCALE_AUTH_KEY` + `_HOSTNAME` | (unset → disabled) | Native Moonlight path |
| `TURN_USERNAME` / `TURN_PASSWORD` | `turnuser` / `OPEN_BUTTON_TOKEN` | coturn creds (shared by mws + Selkies) |
| `SELKIES_ENCODER` | (auto: NVENC else x264) | Force the Selkies encoder |
| `DPAD_NVENC_FIX` | `auto` | flexgrip #1249 fix: `auto` (multi-GPU slice on driver 570..609), `1`, `0` |
| `DPAD_MWS_AUTOPAIR` | `1` | Auto-pair mws↔Sunshine at boot so the end user never sees a PIN. `0` to disable (manual pairing via the mws web UI) |
| `MWS_ADMIN_USER` / `MWS_ADMIN_PASSWORD` | `dpad` / `SUNSHINE_PASSWORD` | mws admin login; auto-pair creates it on first boot, end user logs in with it |
| `MWS_CLIENT_NAME` | `dpadcloud-web` | Friendly name registered in Sunshine for the mws client |

## Local test
```bash
./deploy.sh build && ./deploy.sh up   # then ./deploy.sh logs
```
(needs an NVIDIA GPU + NVIDIA Container Toolkit for NVENC; otherwise Selkies falls back to software `x264enc`. mws requires Sunshine to capture — Sunshine's NVENC also needs the GPU.)

## Files
| File | Purpose |
|------|---------|
| `Dockerfile` | Ubuntu 24.04 / CUDA 12.5.1 image (Steam + Sunshine + Selkies + mws + PulseAudio + coturn + cloudflared + Tailscale + VGL + flexgrip) |
| `entrypoint.sh` | Boot orchestration: Xvfb → XFCE → PulseAudio → coturn → NVENC/flexgrip → Sunshine → Selkies → mws → cloudflared(x2) → Tailscale |
| `configs/sunshine/sunshine.conf` | Tuned Sunshine capture/gamepad config |
| `scripts/nvenc_fix.c` | Vendored flexgrip interposer (built → `/opt/dpadcloud/libnvenc_fix.so`) |
| `scripts/{vgl-steam,proton-wined3d,vgl-test,install-display-drivers}` | VirtualGL launchers + matched .run graphics-lib extractor |
| `docker-compose.yml` / `deploy.sh` / `healthcheck.sh` | Local dev helpers |

## Notes / future
- **mws↔Sunshine pairing is automated** (`scripts/mws-autopair`, runs at boot): it logs in to mws (creates the admin), adds the `localhost` host, calls mws `POST /api/pair` (mws generates the PIN), and submits that PIN to Sunshine `POST /api/pin` — so by the time the end user opens the mws URL, the host is already paired and they just log in + launch an app (no PIN). Disable with `DPAD_MWS_AUTOPAIR=0`. Watch `/tmp/mws-autopair.log` (in the periodic log dump) if pairing doesn't complete.
- **Noble t64 apt renames** are applied only where the lib was actually renamed in noble (`libasound2t64`, `libssl3t64`, `libgtk-3-0t64`); `libpulse0`/`libva2`/`libvdpau1`/`libwayland-egl1`/`libjack-jackd2-0` keep their plain names, and `libvpx7`→`libvpx9`. If a package name drifts in a future point release, the first build may need a one-line fix.
- **DX12 / true DXVK perf** still needs a Vulkan present surface (gamescope), deferred. Interim Windows path = WineD3D + `vglrun` (DX9–11) via `proton-wined3d`.
- **Drop Selkies** once mws+Sunshine is validated on Vast (it's kept as a fallback now).