# DpadCloud Gaming Container (B2 + B2b)

A lean (~8 GB) headless cloud-gaming container with **hardware NVENC** for low
latency, built on `nvidia/cuda:12.1.1-runtime-ubuntu22.04` (CUDA 12.1 ≤ every
Vast.ai host's Max Cuda, so NVENC works on the widest host pool).

**Two streaming paths, one image:**
- **Browser click-and-play** → Selkies (NVENC) fronted by a **Cloudflare Tunnel**
  (HTTPS → secure context → gamepad + pointer-lock + WebCodecs decode). No client
  install, no TURN flakiness (in-image coturn relays the WebRTC media).
- **Native enthusiast** → Sunshine (NVENC) + Moonlight over **Tailscale** (lowest
  latency, direct UDP over the Tailnet).

Patterns ported from `vastai/linux-desktop` (PipeWire audio, in-image coturn,
Xvfb+Mesa-EGL display, Selkies bound to 127.0.0.1, `OPEN_BUTTON_TOKEN` creds).

## What's inside
- Ubuntu 22.04 + CUDA 12.1 runtime (matched to host driver → NVENC works)
- Steam + Proton-GE · Sunshine · Selkies-GStreamer (NVENC via cuda-nvrtc)
- PipeWire + pipewire-pulse + wireplumber + null-sink (working headless audio)
- coturn (in-image TURN, port 3478 / Vast tag 73478)
- cloudflared (Cloudflare Tunnel — quick or named) · Tailscale
- Xvfb (Mesa EGL) + XFCE · ~8 GB image (vs Vast's 17–20 GB)

## Build & push
```bash
cd dpadcloud/container-gaming
docker build -t YOUR_DOCKERHUB/dpadcloud-gaming:b2 .
docker push YOUR_DOCKERHUB/dpadcloud-gaming:b2
```

## Deploy on Vast.ai

**Pick a compatible host** — use these offer filters (same as Vast's own linux-desktop
template; they guarantee our CUDA 12.1 base runs and NVENC works):
```
compute_cap>=750 cuda_max_good>=12.1 gpu_display_active=false
```
(CLI: `vastai search offers 'compute_cap>=750 cuda_max_good>=12.1 gpu_display_active=false'`)

Docker Options (browser streaming — the 73478 identity tag is required, **TCP
only**, so the browser's WebRTC media relays through the in-image coturn. Do NOT
add `73478/udp` — Vast flags tcp+udp of the same port as a duplicate.):

```
-e SUNSHINE_PASSWORD=pass -e SELKIES_BASIC_AUTH_USER=dpad -e SELKIES_BASIC_AUTH_PASSWORD=pass -p 73478:73478
```

On boot, read the boot log (Vast **Logs** tab). It prints a **Cloudflare quick
tunnel URL** like `https://<random>.trycloudflare.com`. Open it in a browser
→ log in (`dpad` / `pass`) → gamepad + low-latency NVENC stream. (The URL is
HTTPS so the secure-context gaming APIs are enabled.)

For the **native Moonlight** enthusiast path, add Tailscale:
```
-e TAILSCALE_AUTH_KEY=tskey-... -e TAILSCALE_HOSTNAME=dpadcloud-1 -p 41641:41641/udp
```
Then in Moonlight on your client → Add PC → the container's Tailnet IP
(`100.x.x.x`, printed in the boot log) on port 47989, pair via Sunshine's Web UI.

> The encoder is auto-selected at boot by a 1-frame encode test: `nvh264enc`
> (NVENC) when the GPU is reachable, else `x264enc`. On a CPU-only host you'll
> see `x264enc`; on a Vast GPU you should see `nvh264enc`.

## Production (your website → "Play Game" → browser)

Replace the quick tunnel with a **named Cloudflare Tunnel** so each session gets
a clean `https://play-<id>.dpadcloud.com`:
```
-e CLOUDFLARED_TUNNEL_TOKEN=<token> -e CLOUDFLARED_HOSTNAME=https://play-<id>.dpadcloud.com
```
Your Fastify orchestrator creates the tunnel (Cloudflare API) + DNS CNAME per
session, provisions the Vast instance with the token + a per-session
`SELKIES_BASIC_AUTH_PASSWORD`, and returns the HTTPS URL for the website to open.
Per-session auth: set `SELKIES_BASIC_AUTH_PASSWORD` to a session token (or front
with Cloudflare Access) so a leaked URL can't be reused.

## Config (env)

| Variable | Default | Purpose |
|----------|---------|---------|
| `SCREEN_RESOLUTION` | `1920x1080x24` | Xvfb screen (fixed at boot) |
| `SUNSHINE_PASSWORD` | `dpadcloud` | Sunshine Web UI / creds |
| `SELKIES_BASIC_AUTH_USER` / `_PASSWORD` | `dpad` / `OPEN_BUTTON_TOKEN` | Browser login gate |
| `CLOUDFLARED_TUNNEL_TOKEN` + `_HOSTNAME` | (unset → quick tunnel) | Named tunnel (prod) |
| `TAILSCALE_AUTH_KEY` + `_HOSTNAME` | (unset → disabled) | Native Moonlight path |
| `TURN_USERNAME` / `TURN_PASSWORD` | `turnuser` / `OPEN_BUTTON_TOKEN` | coturn creds |
| `SELKIES_ENCODER` | (auto: NVENC else x264) | Force an encoder |

## Local test
```bash
./deploy.sh build && ./deploy.sh up   # then ./deploy.sh logs
```
(needs an NVIDIA GPU + NVIDIA Container Toolkit for NVENC; otherwise falls back
to software `x264enc`.)

## Files
| File | Purpose |
|------|---------|
| `Dockerfile` | Lean B2 image (CUDA 12.1 + Steam + Sunshine + Selkies + PipeWire + coturn + cloudflared + Tailscale) |
| `entrypoint.sh` | Boot orchestration (ported Vast patterns) |
| `configs/sunshine/sunshine.conf` | Tuned Sunshine capture/gamepad config |
| `docker-compose.yml` / `deploy.sh` / `healthcheck.sh` | Local dev helpers |

## Notes / future
- **VirtualGL** is not included (games render via Mesa software GL on Xvfb). Add
  VirtualGL + `vglrun` to give games hardware GL rendering — a perf follow-up.
- Dynamic resolution resize is disabled (`--enable_resize=false`); re-enable with
  Xvfb at 8192x4096 + `cvt` + `selkies-gstreamer-resize` if needed.
- Moonlight Web (Sunshine NVENC + WebCodecs, single WebSocket, no coturn) is an
  alternative browser path if Selkies' decode latency disappoints — additive.