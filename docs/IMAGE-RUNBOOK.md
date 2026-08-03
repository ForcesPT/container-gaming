# DpadCloud Image — Launch Runbook

> The operational recipe for running the `:dpad-SteamOS` image on a full-root
> GPU VM (the v2 providers: UpCloud / Hyperstack / MassedCompute / OVH / Nebius).
> The validated launch, every flag + env var, the boot milestones, and the
> troubleshooting table.
>
> Companion: `PROJECT_STATE.md` (the image state + baked-in fixes + open items).
>
> (Was `VAST-VM-DEPLOY.md`; renamed 2026-07-30 — Vast was dropped, this is now the
> provider-agnostic image runbook.)

## TL;DR — the validated launch

**Primary: the one-command `vm-bootstrap.sh`** (automates host setup + pulls
the image + launches one CDI container per GPU + waits for each Selkies URL +
prints them). On a freshly-provisioned full-root Ubuntu VM (expose **one UDP
port per GPU**: `-p 3478:3478/udp` for 1 GPU), as root:

```bash
# Opt into gamescope headless mode (the validated path). vm-bootstrap sources
# /etc/environment so the systemd oneshot it installs sees this too.
grep -q DPAD_GAMESCOPE /etc/environment 2>/dev/null || echo "DPAD_GAMESCOPE=1" >> /etc/environment

# Fetch + install the bootstrap (installs itself as a systemd oneshot; survives
# the one-time modeset=Y reboot and re-runs at every boot).
mkdir -p /opt/dpadcloud && \
  curl -fsSL https://raw.githubusercontent.com/ForcesPT/container-gaming/main/scripts/vm-bootstrap.sh \
    -o /opt/dpadcloud/vm-bootstrap.sh && \
  chmod +x /opt/dpadcloud/vm-bootstrap.sh && \
  /opt/dpadcloud/vm-bootstrap.sh install

# Watch it go (modeset=Y -> nvidia-container-toolkit + CDI -> pull -> N containers -> URLs):
journalctl -u dpadcloud-bootstrap -f
# ...ends with: "DpadCloud READY" + each session's Selkies tunnel URL + login.
# URLs are also written to /opt/dpadcloud/selkies-urls.txt.
```

**Manual equivalent** (what `vm-bootstrap.sh` automates — for debugging):

```bash
# 1) One-time host setup:
nvidia-ctk runtime configure --runtime=docker && systemctl restart docker
nvidia-ctk cdi generate --output=/etc/cdi/nvidia.yaml
cat > /etc/sysctl.d/99-dpad.conf <<'EOF'
kernel.unprivileged_userns_clone=1
kernel.apparmor_restrict_unprivileged_userns=0
vm.max_map_count=1048576          # Steam+CEF under gamescope (default 65530 OOMs it)
EOF
sysctl --system
echo 'options nvidia_drm modeset=1' > /etc/modprobe.d/nvidia-drm.conf
modprobe -r nvidia_drm nvidia_modeset nvidia_uvm nvidia 2>/dev/null; modprobe nvidia_drm modeset=1 || reboot

# 2) Pull + launch ONE container (CDI, NO --privileged):
docker pull forcespt/dpadcloud-gaming:dpad-SteamOS
docker run -d --name dpad-0 --runtime=nvidia --cap-add SYS_ADMIN \
  --security-opt seccomp=unconfined --security-opt apparmor=unconfined \
  -e NVIDIA_VISIBLE_DEVICES=nvidia.com/gpu=0 \
  --device /dev/uinput --shm-size=2g --ulimit nofile=1048576:1048576 \
  -p 3478:3478/udp \
  -e DPAD_GAMESCOPE=1 -e DPAD_COTURN_PORT=3478 \
  -e DPAD_TURN_PUBLIC_IP=$PUBLIC_IPADDR -e DPAD_TURN_UDP_EXTERNAL_PORT=$EXT_PORT \
  -e SELKIES_BASIC_AUTH_USER=dpad -e SELKIES_BASIC_AUTH_PASSWORD=pass0 \
  forcespt/dpadcloud-gaming:dpad-SteamOS

# 3) Watch the boot (~50s):
docker logs -f dpad-0
# look for: GAMESCOPE SESSION READY -> Selkies running on 127.0.0.1:16100 (encoder=nvh264enc)
```

## The `docker run` flags — every flag, and why

| Flag | Why |
|---|---|
| `--runtime=nvidia` + `-e NVIDIA_VISIBLE_DEVICES=nvidia.com/gpu=0` | **CDI**: per-GPU isolation AND injects the full per-GPU device set (`/dev/nvidiaX` + `/dev/dri/cardX` + `renderDXXX`). `--gpus device=i` (no `--privileged`) isolates but doesn't inject `/dev/dri/cardX` → no DRM device. `--privileged` mounts all GPUs (no isolation). CDI is the clean combo. |
| `--cap-add SYS_ADMIN` | Restores `CAP_SYS_ADMIN` so `unshare -U` works (Steam userns/pressure-vessel). Without it userns=no → Steam can't run. |
| `--security-opt seccomp=unconfined --security-opt apparmor=unconfined` | Docker's default seccomp + AppArmor block `dpad` from `unshare -U`. Required with the host sysctls above. |
| `--shm-size=2g` | CEF/steamwebhelper shared memory (Docker defaults /dev/shm to 64 MB → crash-loop). |
| `--ulimit nofile=1048576:1048576` | Without `--privileged` the nofile hard cap is 1024. Some hosts also need `--ulimit nproc=1048576:1048576` (hard `nproc=50` → PulseAudio EAGAIN hang). |
| `-p 3478:3478/udp` | coturn TURN. UDP recommended (lower latency under loss); TCP also works. One port per session. |

**Don't use:** `--privileged` (mounts all GPUs), `--gpus` without CDI (no
`/dev/dri`), `--jupyter`/`--ssh`/`--onstart-cmd` (override the entrypoint).

## Environment variables

| Variable | Default | Purpose |
|---|---|---|
| `DPAD_GAMESCOPE` | `0` | `1` = gamescope headless mode (the validated path). |
| `DPAD_VIDEO_SRC` | `pipewiresrc` | `pipewiresrc` = direct PipeWire capture (zero-copy-ish). `ximagesrc` = the `:2` Xvfb bridge fallback. |
| `DPAD_SELKIES_BIND` | `127.0.0.1` | Selkies signaling bind. `127.0.0.1` for the SSH-tunnel path; **`0.0.0.0` for direct-IP providers** (UpCloud/Hyperstack/MassedCompute) so Caddy reverse-proxies HTTP straight to `<public-ip>:16100`. |
| `DPAD_TUNNEL` | (unset) | `ssh` gates cloudflared OFF (the B1 self-hosted `play-<id>.dpadplay.com` path). Unset = cloudflared quick tunnel (legacy). |
| `DPAD_AUDIO_PACKETLOSS` | `0` | Opus inband FEC % (e.g. `10`). 0 = off. |
| `DPAD_VIDEO_PACKETLOSS` | `0` | ULP_RED video FEC % (e.g. `10`, RFC 2198 forward redundancy). Auto-trims `fec_video_bitrate = video_bitrate / (1 + %/100)`. 0 = off. NACK rtx is always on. |
| `DPAD_COTURN_PORT` | `3478` | coturn listen port (internal). Expose with `-p`. |
| `DPAD_TURN_PUBLIC_IP` | (auto from `$PUBLIC_IPADDR`) | The VM's public IP for the browser-side TURN ICE entry. |
| `DPAD_TURN_UDP_EXTERNAL_PORT` / `DPAD_TURN_EXTERNAL_PORT` | `=DPAD_COTURN_PORT` | The external mapped port the browser reaches coturn at. |
| `DPAD_MAX_SESSIONS` | (all GPUs) | Cap the containers vm-bootstrap launches (e.g. `1` for a clean single session). |
| `DPAD_SESSION_PASSWORDS` | (unset) | Per-session password list (vm-bootstrap assigns one per container). |
| `DPAD_IMAGE_TAG` | (auto by `compute_cap`) | Force a specific image tag (e.g. `:dpad-SteamOS-L4`), bypassing the `compute_cap ≥ 12 → -rtx50` auto-select. |
| `DPAD_NVENC_FIX` | `auto` | `1\|0\|auto` — the flexgrip `libnvenc_fix.so` NVENC #1249 interposer. `auto` = on for driver 570..609 when host GPU count > mounted. |
| `DPAD_RESERVE_CPUS` / `DPAD_RESERVE_MEM_MB` | `2` / `4096` | Host reserve before dividing CPU/RAM across N containers. |
| `DPAD_CPUS_PER_SESSION` / `DPAD_MEM_PER_SESSION` | (auto) | Override the per-container `--cpus` / `--memory`. |
| `DPAD_CPU_MODE` | `quota` | `quota` (`--cpus`) \| `pinned` (`--cpuset-cpus`) \| `shares` (`--cpu-shares`). |
| `DPAD_PIDS_LIMIT` | `4096` | Per-container `--pids-limit`. |
| `SELKIES_BASIC_AUTH_USER` / `SELKIES_BASIC_AUTH_PASSWORD` | `dpad` / token | Browser login. Set the password to a per-session token in production. |
| `NVIDIA_VISIBLE_DEVICES` | (unset) | CDI: `nvidia.com/gpu=i`. Don't set `=all` on multi-GPU hosts (encoder grabs device 0). |

(Full set in `scripts/vm-bootstrap.sh` + `entrypoint.sh`.)

## Networking — coturn TURN

```
Browser ──HTTPS──▶ (cloudflared tunnel OR direct-IP Caddy) ──▶ Selkies 127.0.0.1:16100  (signalling + WebRTC)
                                                                │
                                WebRTC media ──▶ coturn (0.0.0.0:3478, UDP + TCP)
                                                                │
                                browser TURN ICE: turn:<publicIp>:<extPort>?transport=udp
                                in-container TURN ICE: turn:127.0.0.1:3478
```

- **coturn binds `0.0.0.0:3478`**, listens both UDP + TCP. The entrypoint emits
  ICE entries only for the protocol(s) actually exposed.
- **Short-circuit relay:** both WebRTC peers are TURN clients of the *same*
  coturn → media relays internally over the two control connections → **only
  the listen port needs mapping** (no relay port range; the 64-port limit is
  no obstacle).
- **No SSH tunnel** on direct-IP providers — the browser + Caddy reach Selkies
  at `<public-ip>:16100` direct (`DPAD_SELKIES_BIND=0.0.0.0`); media goes
  direct browser↔host via coturn.

**Latency floor (RTX 3060, 1 GPU):** ~50ms video / ~100ms audio = network RTT
+ capture/encode/browser-decode. UDP's win is under packet loss (no TCP
head-of-line blocking), not on a clean link. The remaining lever is a closer
region (lower RTT); the transport is no longer the bottleneck.

## Boot milestones (a healthy gamescope boot)

```
[*] NVIDIA ... NVIDIA GeForce RTX ..., <driver>, ... MiB
[*] Vulkan ICD: pinned to libEGL_nvidia.so.0 (headless/no-X11 fix for driver 595+)   # no-op on 580
[*] Render node /dev/dri/renderD128 is group <X> (gid N); added dpad to it
[*] DPAD_GAMESCOPE mode: gamescope --backend headless + Steam (no DRM master)
[*] GAMESCOPE SESSION READY
[*] Stage 2 (zero-copy): Selkies captures gamescope's PipeWire node directly (pipewiresrc -> cudaupload -> cudaconvert -> nvh264enc)
    Selkies running on 127.0.0.1:16100 (gamescope bridge, encoder=nvh264enc)
```

Cold-boot budget (fresh `docker run`, RTX 3060): **~50s** to the stream URL
(NVIDIA driver `.run` install ~14s · gamescope+Steam ~12s · Selkies ~6s ·
cloudflared ~10s · the rest ~8s).

## Troubleshooting (the rows that still bite)

| Symptom | Cause / Fix |
|---|---|
| gamescope `vulkan: vkCreateDevice failed (VkResult: -7)` / `Failed to create backend` | `nvidia_drm.modeset` is N. Set `options nvidia_drm modeset=1` in `/etc/modprobe.d/` + `modprobe -r nvidia_drm && modprobe nvidia_drm modeset=1` (or reboot). vm-bootstrap does this. |
| gamescope `vulkan: physical device has no primary node` → `Failed to create backend` | The `drmProps` headless patch is missing (stale image). Rebuild from current `main` (the `gamescope-builder` stage applies `scripts/gamescope-headless-drmprops.patch`). |
| `vulkan: vkCreateInstance failed (VkResult: -9)` on driver 595 | The EGL-ICD entrypoint patch is missing (stale image). Rebuild. |
| `dpad` EACCES opening `/dev/dri/renderD128` | The render-node GID fix is missing (stale image) OR the host maps renderD128 to a group the entrypoint didn't handle. `usermod -aG <group> dpad`. |
| Boot log `OpenGL renderer string: zink…` + no stream (cuda≥13.3 Blackwell) | The GLVND `libglx.so` bake is missing (stale image). Rebuild. |
| WebRTC media fails / no video, signaling OK | No TURN port exposed, or `DPAD_TURN_*_EXTERNAL_PORT` not passed. Log says `WARNING: no TURN port exposed`. |
| "Connection failed" + browser gets only `host`/mDNS ICE (no `typ relay`) | The host isn't forwarding the mapped coturn port to the internet. Probe: a STUN Allocate UDP packet to `<publicIp>:<extPort>` must answer (401). No reply ⇒ destroy + relaunch on a different host (a host networking issue, not the image). |
| Steam "requires user namespaces" / `unshare -U` EPERM as `dpad` | Host sysctls unset OR container missing `--security-opt seccomp=unconfined apparmor=unconfined` + `--cap-add SYS_ADMIN`. Root `unshare -U` working is NOT enough — needs *unprivileged* userns. |
| `mmap() failed: Cannot allocate memory` under gamescope | `vm.max_map_count` too low → set `1048576`. NOT a RAM issue. |
| steamwebhelper crash-loop / "Failed creating offscreen shared JS context" | `--shm-size=2g` missing. |
| `~/.local` EPERM aborts Steam bootstrap | A root boot process creates `~/.local` root-owned. The entrypoint's targeted `find ! -user dpad` chown handles it — don't use a blanket `chown -R` (overlayfs copy-up anti-pattern, see `PROJECT_STATE.md` §4). |
| Gamepad not detected / no controller in Big Picture | Check `/tmp/selkies_js.log` for the FULL probe `JSIOCGNAME -> JSIOCGBUTTONS -> JSIOCGAXES -> JSIOCGBTNMAP -> JSIOCGAXMAP`. Only `JSIOCGNAME` then close = the i386 interposer `.so` is stale (rebuild BOTH arches — `gcc-multilib`). Stale-image check: `ls -la /usr/lib/i386-linux-gnu/selkies_joystick_interposer.so` (i386 should be the build day, not ~Aug 2024). Decisive test: the **32-bit** `sdl3_guid_test32` (Steam's main binary is 32-bit), not the 64-bit one. |
| No mouse cursor visible | `--enable_cursors=true` missing OR the web client isn't patched (`patch_gst_web_cursors.sh`). Hard-refresh the browser (Ctrl+Shift+R). FPS relative mouse: browser console `window.DPAD_POINTER_LOCK = true` + click. |
| Mild flicker on Steam menu open/close | NVIDIA 580 driver regression (gamescope #1964). Accepted; host-side. **Severe whole-frame flicker = driver 595** → the host must downgrade 595 → R580 LTS (see `cloud/docs/DEPLOY-RUNBOOK.md`). |
| Browser refresh occasionally "Waiting for stream" | Selkies 1.6.2 reconnect race. Self-heals on a 2nd refresh; a fresh incognito tab always works. **A restart-on-disconnect supervisor (`entrypoint.sh` `relaunch_selkies()` in the gamescope-session health loop) auto-relaunches `selkies-gstreamer` when it dies while gamescope is up, so the browser reconnects without a manual refresh — validated live 2026-08-05 (OVH Gravelines L4: killed selkies mid-stream, health loop relaunched it within ~20s)** (`PROJECT_STATE.md` §6 #7). |
| `webrtcnice … failed to resolve "<uuid>.local"` | Harmless — Chrome's mDNS `.local` ICE candidates the container can't resolve; the TURN relay handles it. |
| `remote resize is disabled, skipping resize to 2552x1308` | Harmless — hi-DPI browser asked bigger; `--enable_resize=false` fixes the stream at 1920×1080. |

## Multi-tenant — N sessions on N GPUs in one VM

`vm-bootstrap.sh` launches one CDI container per GPU (per-container GPU via
`NVIDIA_VISIBLE_DEVICES=nvidia.com/gpu=i`, per-container coturn port
3478/3479/…, per-container `--cpus`/`--memory` quota from
`compute_session_resources()`). No DRM master → no modesetting contention.
Validated 2-GPU + 4-GPU. For oversubscription (N > GPUs) under MPS, see
`cloud/docs/PROVIDERS.md` + the `DPAD_OVERSUBSCRIBE`
plan.

## Rebuild + push

```bash
docker build --target vast-vm -t forcespt/dpadcloud-gaming:dpad-SteamOS .
docker build --target vast-vm --build-arg CUDA_VERSION=12.8.1 --build-arg CUDA_PKG=12-8 \
  -t forcespt/dpadcloud-gaming:dpad-SteamOS-rtx50 .
docker push forcespt/dpadcloud-gaming:dpad-SteamOS
```