# DpadCloud Container Gaming — Vast.ai VM Deployment Runbook

> The complete operational recipe for running the DpadCloud gamescope cloud-gaming
> container on a **Vast.ai KVM VM**, from provisioning to a live, interactive
> browser stream. Every flag, env var, and gotcha below was validated on a Vast
> RTX 3060 / driver 580, 1-GPU VM. This is the authoritative "Vast.ai → VM → Docker
> → flags → everything" reference.
>
> Companion docs: `PROJECT_STATE.md` (project state/continuation), `README.md`
> (deploy script env vars), `RUNPOD.md` (RunPod specifics).

## TL;DR — the validated launch

**Primary method: the one-command `vm-bootstrap.sh`** (automates host setup +
pulls the image + launches one CDI container per GPU + waits for each Selkies
URL + prints them). This is what's validated end-to-end (gamepad + cursor +
video + audio). On a freshly-provisioned `vastai/kvm:ubuntu_cli_22.04-2025-11-21`
VM (expose **one UDP port per GPU**: `-p 3478:3478/udp` for 1 GPU), as root:

```bash
# Opt into gamescope headless mode (the validated MVP). vm-bootstrap sources
# /etc/environment so the systemd service it installs sees this too.
grep -q DPAD_GAMESCOPE /etc/environment 2>/dev/null || echo "DPAD_GAMESCOPE=1" >> /etc/environment

# Fetch + install the bootstrap (it installs itself as a systemd oneshot so it
# survives the one-time modeset=Y reboot and re-runs at every boot).
mkdir -p /opt/dpadcloud && \
  curl -fsSL https://raw.githubusercontent.com/ForcesPT/container-gaming/main/scripts/vm-bootstrap.sh \
    -o /opt/dpadcloud/vm-bootstrap.sh && \
  chmod +x /opt/dpadcloud/vm-bootstrap.sh && \
  /opt/dpadcloud/vm-bootstrap.sh install

# Watch it go (modeset=Y -> nvidia-container-toolkit + CDI -> pull -> N containers -> URLs):
journalctl -u dpadcloud-bootstrap -f
# ...ends with: "DpadCloud READY" + each session's Selkies tunnel URL + login.
# URLs are also written to /opt/dpadcloud/selkies-urls.txt.
# Then open a URL (login dpad / pass0) — video + audio + keyboard + mouse + gamepad all work.
#   gamepad: connect a controller in the browser + press a button; Steam Big Picture detects
#   "Selkies Controller". Check: docker exec dpad-0 tail /tmp/selkies_js.log
#   (must show the full probe: JSIOCGNAME -> JSIOCGBUTTONS -> JSIOCGAXES -> JSIOCGBTNMAP -> JSIOCGAXMAP).
```

**Manual equivalent** (what `vm-bootstrap.sh` automates — for understanding/debugging):

```bash
# 1) One-time host setup:
nvidia-ctk runtime configure --runtime=docker && systemctl restart docker
nvidia-ctk cdi generate --output=/etc/cdi/nvidia.yaml
cat > /etc/sysctl.d/99-dpad-userns.conf <<'EOF'
kernel.unprivileged_userns_clone=1
kernel.apparmor_restrict_unprivileged_userns=0
vm.max_map_count=1048576          # Steam+CEF under gamescope (default 65530 OOMs it)
EOF
sysctl --system
# nvidia_drm.modeset=Y (gamescope --backend headless on NVIDIA needs it; one reboot if N):
echo 'options nvidia_drm modeset=1' > /etc/modprobe.d/nvidia-drm.conf
modprobe -r nvidia_drm nvidia_modeset nvidia_uvm nvidia 2>/dev/null; modprobe nvidia_drm modeset=1 || reboot

# 2) Pull + launch ONE container (CDI, NO --privileged). UDP is recommended (lower
#    latency under loss); Vast forbids the same port as both tcp+udp, so pick ONE.
docker pull forcespt/dpadcloud-gaming:SteamUbuntu24.04VM
docker run -d --name dpad-0 --runtime=nvidia --cap-add SYS_ADMIN \
  --security-opt seccomp=unconfined --security-opt apparmor=unconfined \
  -e NVIDIA_VISIBLE_DEVICES=nvidia.com/gpu=0 \
  --device /dev/uinput --shm-size=2g --ulimit nofile=1048576:1048576 \
  -p 3478:3478/udp \
  -e DPAD_PROVIDER=runpod -e DPAD_COTURN_PORT=3478 \
  -e DPAD_TURN_PUBLIC_IP=$PUBLIC_IPADDR -e DPAD_TURN_UDP_EXTERNAL_PORT=$VAST_UDP_PORT_3478 \
  -e DPAD_GAMESCOPE=1 \
  -e SUNSHINE_PASSWORD=pass0 -e SELKIES_BASIC_AUTH_USER=dpad -e SELKIES_BASIC_AUTH_PASSWORD=pass0 \
  forcespt/dpadcloud-gaming:SteamUbuntu24.04VM

# 3) Watch the boot log (~50s cold boot — see §7 for the per-phase budget):
docker logs -f dpad-0
# look for: GAMESCOPE SESSION READY -> input -> gamescope Xwayland :0 -> Selkies running ->
#          ▶ gamescope browser stream: https://…trycloudflare.com  (login dpad / pass0)
```

---

## 1. Provisioning the Vast VM

### VM image — use the CLI image, NOT the desktop image
- **`vastai/kvm:ubuntu_cli_22.04-2025-11-21`** — the freshest no-desktop CLI VM tag
  (built 2025-11-24). **This is the one to use.** SSH-only, full kernel →
  user namespaces + ptrace + Docker-in-Docker.
- ❌ Do **NOT** use `vastai/kvm:ubuntu_desktop_24.04` — its **SDDM X server holds
  DRM master**, so `--privileged`/caps can't take it and the DFP Xorg path fails.
  If you must use it, stop SDDM first: `sudo systemctl isolate multi-user.target`
  (or `systemctl stop sddm`). The gamescope headless path doesn't need DRM
  master, but SDDM still grabs resources; the CLI image avoids all of it.
- ❌ Do **NOT** use the plain `vastai/kvm:ubuntu_terminal` tag — stale
  (last updated 2024-11-11).

### Vast offer filter (NVENC-safe)
```
compute_cap>=750 cuda_max_good>=12.1 gpu_display_active=false rentable=true verified=true
```
- `gpu_display_active=false` — headless host (no monitor attached); we render
  on the GPU ourselves via gamescope headless.
- `cuda_max_good>=12.1` — keeps the wide pool (driver 535/545/550/570/580/595);
  CUDA 12.5.1 (our base) runs on any driver ≥525 via minor-version compat.
- Cheapest NVENC: `gpu_frac=1 num_gpus=1` (single-GPU machines, immune to the
  nvidia-container-toolkit #1249 multi-GPU NVENC issue on any driver).
- RTX 50/Blackwell (sm_120/sm_121) needs the **`-rtx50` image variant**
  (`:SteamUbuntu24.04VM-rtx50`, CUDA 12.8.1) — driver ≥570, in the #1249 range
  (the flexgrip interposer covers it). **`vm-bootstrap.sh` now auto-selects it**
  via `image_tag_for_gpu()` when `compute_cap ≥ 12` (no manual tag); override
  with `DPAD_IMAGE_TAG`. Build it with
  `docker build --build-arg CUDA_VERSION=12.8.1 --build-arg CUDA_PKG=12-8 -t forcespt/dpadcloud-gaming:SteamUbuntu24.04VM-rtx50 .`

### Expose ports
- **One port per GPU session**, exposed as **UDP** (recommended — lower latency under loss):
  `-p 3478:3478/udp` (GPU 0), `-p 3479:3479/udp` (GPU 1), … each is coturn's UDP TURN port for one session.
- **Vast forbids the same port as both tcp and udp** (UI: "Duplicate Port Detected"),
  so pick ONE protocol per port. UDP is recommended (coturn relays SRTP over UDP;
  no TCP head-of-line blocking/retransmit stalls under packet loss). There is no
  TCP fallback on Vast — acceptable for a UDP-native cloud-gaming product.
- Vast maps each exposed **internal** port to a **random external** port, injected
  as `VAST_UDP_PORT_<internal>` (UDP) or `VAST_TCP_PORT_<internal>` (TCP). The
  browser's TURN ICE entry uses that external port — see §5.
- **SSH still works** — Vast always auto-maps port 22 (`VAST_TCP_PORT_22`) regardless
  of your `-p` list. **Signaling rides cloudflared** (outbound HTTPS), so no inbound
  HTTP/TCP port is needed for the stream.
- **64-port limit** is no obstacle: coturn short-circuits the relay internally when
  both peers are TURN clients of the same coturn, so only the **listen port** needs
  mapping per session (no relay port range to expose).

---

## 2. One-time host setup (`vm-bootstrap.sh` does all of this)

`scripts/vm-bootstrap.sh install` automates everything below. Manual equivalent:

### a) nvidia_drm.modeset=Y
```bash
cat /sys/module/nvidia_drm/parameters/modeset   # must be Y
# if N: echo Y > /sys/module/nvidia_drm/parameters/modeset ; reboot
```
Needed for the DFP Xorg path (DRM master). The gamescope headless path
doesn't strictly need it, but set it anyway (harmless, required for the
full-Steam DFP fallback path).

### b) nvidia-container-toolkit + CDI
```bash
# install nvidia-container-toolkit (distribution packages), then:
nvidia-ctk cdi generate --output=/etc/cdi/nvidia.yaml
```
CDI (`--runtime=nvidia -e NVIDIA_VISIBLE_DEVICES=nvidia.com/gpu=i`) is what
gives per-GPU isolation **AND** injects the full device set
(`/dev/nvidiaX` + `/dev/dri/cardX` + `renderDXXX`). See §3 why this matters.

### c) Unprivileged-userns sysctls (REQUIRED for Steam)
```bash
cat > /etc/sysctl.d/99-dpad-userns.conf <<'EOF'
kernel.unprivileged_userns_clone=1
kernel.apparmor_restrict_unprivileged_userns=0
EOF
sysctl --system
```
Steam runs as the non-root `dpad` user and needs **unprivileged** user
namespaces (pressure-vessel / CEF). Docker's default seccomp + AppArmor
block `dpad` from `unshare -U` unless these host sysctls are permissive **AND**
the container has `--security-opt seccomp=unconfined --security-opt
apparmor=unconfined`. Without it → "Steam now requires user namespaces to be
enabled." These are **host-level** sysctls — not settable from inside an
unprivileged container.

### d) vm.max_map_count=1048576 (REQUIRED for Steam+CEF under gamescope)
```bash
echo 'vm.max_map_count=1048576' > /etc/sysctl.d/99-dpad-mmap.conf
sysctl -p /etc/sysctl.d/99-dpad-mmap.conf
```
Steam+CEF under gamescope open more than the default 65530 memory mappings →
`mmap() failed: Cannot allocate memory` → GL composer thread dies → SIGKILL.
Steam Deck sets 1048576. NOT a RAM issue (host can have 135 GB free).

---

## 3. The `docker run` command — every flag, and why

```bash
docker run -d --name dpad-0 --runtime=nvidia --cap-add SYS_ADMIN \
  --security-opt seccomp=unconfined --security-opt apparmor=unconfined \
  -e NVIDIA_VISIBLE_DEVICES=nvidia.com/gpu=0 \
  --device /dev/uinput --shm-size=2g --ulimit nofile=1048576:1048576 \
  -p 3478:3478 \
  -e DPAD_PROVIDER=runpod -e DPAD_COTURN_PORT=3478 \
  -e DPAD_TURN_PUBLIC_IP=$PUBLIC_IPADDR -e DPAD_TURN_EXTERNAL_PORT=$VAST_TCP_PORT_3478 \
  -e DPAD_GAMESCOPE=1 \
  -e SUNSHINE_PASSWORD=pass0 -e SELKIES_BASIC_AUTH_USER=dpad -e SELKIES_BASIC_AUTH_PASSWORD=pass0 \
  forcespt/dpadcloud-gaming:SteamUbuntu24.04VM
```

| Flag | Why |
|---|---|
| `--runtime=nvidia` + `-e NVIDIA_VISIBLE_DEVICES=nvidia.com/gpu=0` | **CDI**: per-GPU isolation AND injects the **full** per-GPU device set (`/dev/nvidiaX` + `/dev/dri/cardX` + `renderDXXX`). `--gpus device=i` (without `--privileged`) isolates the GPU but does **NOT** inject `/dev/dri/cardX` → no DRM device → DFP Xorg fails → `llvmpipe` software. `--privileged` mounts **all** GPUs (no isolation) and is overkill. **CDI is the clean combo** (validated: `nvidia-smi -L` shows one GPU, `/dev/dri/card1 + renderD129` present, `OpenGL renderer: NVIDIA GeForce RTX 3060`). |
| `--cap-add SYS_ADMIN` | Restores `CAP_SYS_ADMIN` so `unshare -U` works (Steam userns/pressure-vessel) and Xorg can be DRM master (DFP path). Without it (bare `--gpus`) userns=no → gamescope Steam can't run. |
| `--security-opt seccomp=unconfined --security-opt apparmor=unconfined` | Docker's default seccomp + AppArmor block the `dpad` user from `unshare -U`. Required together with the host sysctls in §2c. After: `su - dpad -c 'unshare -U true'` → `USERNS_OK`. |
| `--device /dev/uinput` | Sunshine virtual input devices (DFP path). The gamescope path uses XTest on `:0` so doesn't strictly need uinput, but harmless and keeps the DFP path working. |
| `--shm-size=2g` | **CEF/steamwebhelper shared memory.** Docker defaults `/dev/shm` to 64 MB; Chrome/CEF needs more → "Failed creating offscreen shared JS context" → steamwebhelper crash-loops. (The entrypoint also auto-remounts `/dev/shm` to 2G on the dfp path as a safety net.) Equivalent: `--ipc=host`. |
| `--ulimit nofile=1048576:1048576` | Without `--privileged`, the nofile hard cap is **1024** (too low for Steam/Selkies). Bump it explicitly. Some hosts also need `--ulimit nproc=1048576:1048576` (hard `nproc=50` cap → whole stack hangs at PulseAudio EAGAIN; the in-image `ulimit -Hu` can't exceed a hard cap). |
| `-p 3478:3478` or `-p 3478:3478/udp` | Expose the coturn TURN port. **UDP is recommended** (lower latency under packet loss); TCP also works. Vast maps it to a random external port (`VAST_UDP_PORT_3478` / `VAST_TCP_PORT_3478`). One port per session/container. Pick ONE protocol per port — Vast forbids the same port as both tcp AND udp ("Duplicate Port Detected"). `vm-bootstrap.sh` auto-detects which is exposed and maps/passes accordingly. |

### ❌ Flags NOT to use on Vast
- `--privileged` — mounts ALL GPUs (no isolation); CDI + `--cap-add SYS_ADMIN` is the clean equivalent. (Was needed only on the old `ubuntu_desktop` SDDM workaround.)
- `--jupyter`, `--ssh`, `--onstart-cmd` — override the entrypoint and kill our services.
- `-p 3478:3478` **and** `-p 3478:3478/udp` together — Vast forbids the same port as BOTH tcp and udp ("Duplicate Port Detected"). Pick ONE protocol per port (UDP recommended). Either alone is fine.

---

## 4. Environment variables

| Variable | Default | Purpose |
|---|---|---|
| `DPAD_GAMESCOPE` | `0` | `1` = entrypoint **gamescope headless mode** (Steam via `gamescope --backend headless`, no DRM master → N-on-N-GPUs possible). `0` = the DFP Xorg / headless steamcmd path. **Set `1` for the validated interactive browser path.** |
| `DPAD_VIDEO_SRC` | `pipewiresrc` | gamescope-mode video source. `pipewiresrc` = the **zero-copy-ish path** (Selkies captures gamescope's PipeWire node directly: `pipewiresrc → videorate → cudaupload → cudaconvert → nvh264enc`, no Xvfb `:2`/ximagesrc bridge). `ximagesrc` = the fallback `:2` bridge path (Selkies 1.6.x's original X11 capture). The patcher (`scripts/patch_selkies_pipewire.py`, baked in via the Dockerfile) gates on this. |
| `NVIDIA_VISIBLE_DEVICES` | (unset) | CDI: `nvidia.com/gpu=i` for per-GPU isolation. Do NOT set `=all` on multi-GPU hosts (encoder grabs device 0 which may not be the assigned GPU). |
| `DPAD_PROVIDER` | `vast` | `runpod` triggers the **dual-ICE TURN** config (matches RunPod/Vast's TCP-only one-port model). Set `runpod` on Vast VMs. |
| `DPAD_COTURN_PORT` | `3478` | coturn listen port (internal). Expose it with `-p`. |
| `DPAD_TURN_PUBLIC_IP` | (auto) | The VM's public IP (`$PUBLIC_IPADDR` on Vast). Used for the browser-side TURN ICE entry. |
| `DPAD_TURN_EXTERNAL_PORT` | `=DPAD_COTURN_PORT` | The **external** port Vast mapped (`$VAST_TCP_PORT_3478`). The browser reaches coturn at `publicIp:externalPort`. |
| `SUNSHINE_PASSWORD` | `dpadcloud` | Sunshine/Moonlight creds (DFP path). |
| `SELKIES_BASIC_AUTH_USER` | `dpad` | Browser login username. |
| `SELKIES_BASIC_AUTH_PASSWORD` | `OPEN_TOKEN` | Browser login password — **set to a per-session token in production**. |
| `DPAD_MAX_SESSIONS` | (all GPUs) | Cap the number of containers vm-bootstrap launches (e.g. `1` for a clean single-user session even on a multi-GPU VM). |
| `DPAD_SESSION_PASSWORDS` | (unset) | Per-session password list (vm-bootstrap assigns one per container). |
| `DPAD_ISOLATION` | `cdi` | `cdi` (per-GPU, recommended) or `legacy` (`--gpus`). |
| `DPAD_IMAGE_TAG` | (auto) | Force a specific image tag (e.g. `:SteamUbuntu24.04VM-rtx50`), bypassing the `compute_cap ≥ 12 → -rtx50` auto-select. |
| `DPAD_NVENC_FIX` | `auto` | `1\|0\|auto` — enable the flexgrip `libnvenc_fix.so` NVENC #1249 interposer. `auto` = on for driver 570..609 when host GPU count > mounted `/dev/nvidiaX`. Required for N-on-N on driver 570+. |
| `DPAD_RESERVE_CPUS` | `2` | CPUs kept for the host (docker/sshd/kernel) before dividing the rest across N containers. |
| `DPAD_RESERVE_MEM_MB` | `4096` | RAM (MB) kept for the host before dividing the rest across N containers. |
| `DPAD_CPUS_PER_SESSION` | (auto) | Override the auto CPU quota with a fixed `--cpus` per container. |
| `DPAD_MEM_PER_SESSION` | (auto) | Override the auto RAM cap with a fixed `--memory` (MB) per container. |
| `DPAD_CPU_MODE` | `quota` | `quota` (`--cpus`, hard cap) \| `pinned` (`--cpuset-cpus`, core block per container) \| `shares` (`--cpu-shares`, soft, borrows idle cores). |
| `DPAD_PIDS_LIMIT` | `4096` | Per-container `--pids-limit` (caps runaway fork/threads). |
| `DPAD_LAUNCH_STAGGER` | `0` | Seconds to wait between container launches (opt-in; did NOT prevent the NVENC race — kept as a lever). |
| `STEAM_USER` | (unset) | Headless `steamcmd`/`dpad-launch` path (not the gamescope path). |
| `SDL_JOYSTICK_LINUX_CLASSIC` | `1` (gamescope) | Forces SDL3 to the classic `/dev/input/js*` joystick backend (`JSIOCG*` + 8-byte `js_event`) that the v1.6.2 interposer hooks, instead of the default evdev/libudev backend. Set by the entrypoint on the gamescope+Steam launch. |
| `SDL_JOYSTICK_DISABLE_UDEV` | `1` (gamescope) | Forces SDL3 `ENUMERATION_FALLBACK` (inotify + 3s scandir hotplug) instead of libudev — needed because `SDL_GetSandbox()` doesn't detect a plain Vast Docker container, so SDL3 would otherwise use libudev (no daemon → no devices + no hotplug). |
| `SDL_JOYSTICK_DEVICE` | `/dev/input/js0` | Hints SDL3 to `MaybeAddDevice("/dev/input/js0")` directly (harmless init-time probe; the real device comes via the watcher hotplug on whichever jsN the browser gamepad lands on). |
| `SDL_GAMECONTROLLERCONFIG` | (Selkies GUID mapping) | The SDL_GameController mapping for the Selkies virtual gamepad (`0000d60653656c6b69657320436f6e00,Selkies Controller,...`) so SDL3 treats the raw joystick as a gamepad → Steam Big Picture gamepadui can navigate. GUID = `crc16("Selkies Controller")=0x06d6` + name bytes (SDL3 `SDL_CreateJoystickGUID`, vendor=0 branch). |
| `SELKIES_INTERPOSER` | `/usr/$LIB/selkies_joystick_interposer.so` | The patched v1.6.2 joystick interposer `.so` (JSIOCGNAME returns the name length — the root-cause fix). Rebuilt in the Dockerfile from `scripts/joystick_interposer_v162.c` over the deb-installed one, for BOTH x86_64 AND i386 (Steam's main binary is 32-bit → loads the i386 `.so`; `gcc-multilib`/`libc6-dev-i386` are installed so `gcc -m32` works, and the i386 build fails the build LOUD instead of silently shipping the stale deb `.so`). |
| `CLOUDFLARED_TUNNEL_TOKEN` | (unset → quick tunnel) | Named Cloudflare tunnel token (production domain). |
| `CLOUDFLARED_HOSTNAME` | (unset) | Your domain for the named tunnel (e.g. `https://play-<id>.dpadcloud.com`). |

---

## 5. Networking — coturn TURN (UDP recommended; no SSH tunnel)

The whole networking model is **one exposed UDP port per session** (TCP also
supported), no inbound HTTPS, no SSH tunnel:

```
Browser ──HTTPS──▶ cloudflared tunnel ──▶ Selkies 127.0.0.1:16100  (signalling + WebRTC)
                                          │
                  WebRTC media ──▶ coturn (0.0.0.0:3478, UDP + TCP)
                                          │
                  browser TURN ICE: turn:<publicIp>:<udpExtPort>?transport=udp
                  in-container TURN ICE: turn:127.0.0.1:3478?transport=udp
```

- **coturn binds `0.0.0.0:3478`** and listens **both UDP and TCP** (no `--no-udp`).
  The entrypoint emits ICE entries only for the protocol(s) actually exposed:
  UDP if `VAST_UDP_PORT_3478`/`DPAD_TURN_UDP_EXTERNAL_PORT`, TCP if
  `VAST_TCP_PORT_3478`/`DPAD_TURN_EXTERNAL_PORT`. On Vast (UDP-only per port) →
  UDP only.
- **Short-circuit relay:** both WebRTC peers (browser + in-container selkies) are
  TURN clients of the **same** coturn, so it relays media internally over their
  two control connections to the listen port — the per-allocation relay ports
  are never contacted externally. **Only the listen port needs mapping** (no
  relay port range to expose — Vast's 64-port limit is no obstacle).
- **No SSH tunnel.** The old `DPAD_TURN_PUBLIC_IP=127.0.0.1` + `ssh -L
  3478:localhost:3478` workaround is **dead**. With a real public IP + the mapped
  UDP port, open the Selkies URL and media relays through coturn at the Vast
  external port directly.
- `DPAD_PROVIDER=runpod` arms the dual-ICE config (kept for the RunPod TCP path;
  on Vast the UDP path auto-activates from `VAST_UDP_PORT_*`).

### Latency reality (measured, RTX 3060 / 1 GPU)
- **UDP TURN: video ~52 ms / audio ~96 ms** — ~= the TCP-TURN baseline (~50/100 ms).
  UDP's win is **under packet loss** (no TCP head-of-line blocking / retransmit
  stalls), NOT on a stable low-loss link. So UDP TURN is the **robust** choice for
  real users (flaky Wi-Fi/mobile), but it does not shave latency on a clean
  connection.
- The ~50 ms video is the **floor** for the Vast-relay model: network RTT to Vast
  + capture/encode/browser-decode. Capture is near-zero-copy-ish (the `:2` bridge
  elimination was the real latency win); nvh264enc is ultra-low-latency tuned;
  browser decode is hardware. **Remaining lever: a Vast region closer to the user
  (lower RTT).** The transport is no longer the bottleneck on a stable link.
- The Selkies stats-panel "Peer connection type" can show `host` (the browser's
  local candidate type) even when the selected pair is `relay` — the actual path
  is TURN (the container has no public IP; only the mapped port is reachable).
  Verify with `chrome://webrtc-internals` if needed.

---

## 6. The gamescope headless pipeline (what actually runs)

The **default video path** (`DPAD_VIDEO_SRC=pipewiresrc`, the validated zero-copy-ish path):
```
gamescope --backend headless -e -W 1920 -H 1080 -- steam -gamepadui
   │  renders Steam on the GPU via Vulkan/gamescope-WSI, NO DRM master
   │  → PipeWire video node (node.name=gamescope, media.class=Video/Source, BGRx 1920x1080, modifier 0 = system memory)
   │  → Xwayland :0 (Steam's CEF/X11 UI runs here)
   ▼
[Selkies capture + encode — pipewiresrc direct, NO Xvfb :2 / ximagesrc bridge]
   pipewiresrc(target-object=gamescope, always-copy=True) → capsfilter(BGRx)
   → videorate → capsfilter(BGRx, framerate=N/1)   ← FPS slider throttles here
   → cudaupload → cudaconvert(GPU BGRx→NV12) → nvcudah264enc → rtph264pay → webrtcbin
   → WebRTC → coturn TURN (TCP) → cloudflared → browser
[Audio]  pipewire-pulse null sink (dummy.monitor) → Selkies pulsesrc
[Input — Stage 3a, DIRECT, no go-and-comeback]
   browser WebRTC datachannel → Selkies → xtest.fake_input on :0 → Xwayland → Steam
   (dpad_input_patch.py, a site-packages .pth, routes self.xdisplay to :0)
```

**Latency reality:** input is direct (local XTest, sub-ms; latency ≈ datachannel
transport only). Video is now **near-zero-copy-ish**: one GPU→CPU read (gamescope's
PipeWire buffer, sysmem because gamescope advertises `modifier: 0`) + one CPU→GPU
upload (`cudaupload`); the colorspace convert is on the GPU (`cudaconvert`). The
old `:2` round-trip + both CPU `videoconvert` passes are gone. The FPS slider
works via `videorate` (drops/duplicates to the requested rate; 15fps = lower
bandwidth). `--enable_resize=false` fixes the stream at 1920×1080 (resize on a
live PipeWire source would need a `videoscale` element — a known limitation).

**Fallback:** `DPAD_VIDEO_SRC=ximagesrc` reverts to the validated `:2` bridge
path (Selkies 1.6.x's original X11 capture) — useful if a gamescope/PipeWire
change ever breaks the pipewiresrc path. The patcher
(`scripts/patch_selkies_pipewire.py`, run from the Dockerfile) gates everything on
`DPAD_VIDEO_SRC=pipewiresrc`; unset/`ximagesrc` = original Selkies behavior.

**Architecture note:** the new `selkies-project/selkies` main is the Wayland-native
pixelflux zero-copy stack — but it needs DRM master / a dummy plug on NVIDIA,
which kills the no-DRM-master N-on-N-GPU multi-tenant model. Patching the old
X11-only `selkies_gstreamer` v1.6.x to use `pipewiresrc` keeps the no-DRM-master
advantage AND removes the `:2` detour. (gamescope's PipeWire node advertises
`modifier: 0` = no dmabuf, so this is system-memory BGRx, not true dmabuf
zero-copy — but the `:2` round-trip + CPU colorspace converts are gone.)

---

## 7. Boot milestones — what to check in `docker logs`

A healthy gamescope-mode boot prints, in order:
```
[*] NVIDIA ... NVIDIA GeForce RTX 3060, 580.95.05, ... MiB
[*] Configuring CUDA...  CUDA 12.5 selected
[*] Starting D-Bus...
[*] DPAD_GAMESCOPE mode: gamescope --backend headless + Steam (no DRM master)
[*] Steam client already bootstrapped — skipping Xvfb bootstrap      # if build-time pre-bootstrap baked in
   (or: [*] Bootstrapping Steam client on Xvfb ... — ~3-4min on an image without it)
[*] Starting PipeWire + wireplumber...  PipeWire ready
[*] Launching gamescope --backend headless -e -W 1920 -H 1080 -- steam -gamepadui
[*] GAMESCOPE SESSION READY — Steam UI rendering in headless gamescope (no DRM master).
[*] Stage 2 (zero-copy): Selkies captures gamescope's PipeWire node directly (pipewiresrc -> cudaupload -> cudaconvert -> nvh264enc); no Xvfb :2 / ximagesrc bridge   # DPAD_VIDEO_SRC=ximagesrc reverts to the :2 bridge
    audio socket OK (/run/user/1001/pulse/native)
    input -> gamescope Xwayland :0 (XTest, DPAD_INPUT_DISPLAY=:0)    # Stage 3a auto-discovery
    gamepad: SDL_JOYSTICK_LINUX_CLASSIC=1 + SDL_JOYSTICK_DISABLE_UDEV=1 + SDL_JOYSTICK_DEVICE=/dev/input/js0 + SDL_GAMECONTROLLERCONFIG (Selkies GUID) -> v1.6.2 interposer (patched: JSIOCGNAME returns name length) -> /tmp/selkies_jsN.sock (Stage 3b)
    Selkies running on 127.0.0.1:16100 (gamescope bridge, encoder=nvh264enc)
    ▶ gamescope browser stream: https://<words>.trycloudflare.com  (login dpad / pass0)
```

**Cold-boot budget (fresh `docker run`, RTX 3060, measured 2026-07-08):**

| Phase | Time | Note |
|---|---|---|
| NVIDIA driver `.run` download + install (64+32-bit) | ~14s | re-downloads ~80 MB every boot (host driver version unknown at build time) |
| CUDA + D-Bus | ~2s | |
| gamescope mode + Steam pre-bootstrap skip + PipeWire + pipewire-pulse + null sink | ~3s | Steam client baked in at build → no runtime download |
| Targeted chown + gamepad interposer setup | ~1s | was **119s** with a blanket `chown -R` (overlayfs copy-up of ~33k files / 4 GB) — fixed 2026-07-08 (see §10 "Slow cold boot") |
| gamescope + Steam → `GAMESCOPE SESSION READY` | ~12s | inherent Steam/pressure-vessel startup |
| Stage 2 + coturn | ~4s | |
| Selkies start (WebRTC + GStreamer pipeline) | ~6s | |
| cloudflared quick tunnel URL | ~10s | DNS + tunnel registration |
| **Total to stream URL** | **~50s** | was ~172s before the targeted-chown fix |

Next boot-time levers (deferred): cache the NVIDIA `.run` per driver-version (−14s on re-boots of the same VM); parallelize cloudflared/Selkies with Steam startup; the ~12s Steam startup is largely inherent.

Confirm the patch loaded (inside the container):
```bash
docker exec dpad-0 grep -E "patched Xlib|opened :0|Selkies input ->" /tmp/selkies.log
# dpad_input: patched Xlib add_extension_event (randr/xfixes bug fix)
# dpad_input: opened :0 OK
# dpad_input: Selkies input -> X display :0 (XTest, patched 2 class(es))
```

Confirm input is flowing once you move/type in the browser:
```bash
docker exec dpad-0 grep -c "on_message head=" /tmp/selkies.log   # climbs as you move/click/type
```

---

## 8. Multi-tenant — N full-Steam sessions on N GPUs in ONE VM

This is the **whole reason gamescope headless exists.** The DFP Xorg path can
only do **1 full-Steam session per VM** on consumer GPUs (nvidia-modeset is a
DRM-master singleton). `gamescope --backend headless` renders via
Vulkan/gamescope-WSI with **no DRM master** → no modesetting contention →
**N sessions on N GPUs in one VM**.

`vm-bootstrap.sh` launches one CDI container per GPU:
- per-container GPU: `-e NVIDIA_VISIBLE_DEVICES=nvidia.com/gpu=i`
- per-container port: `-p 3478:3478` (i=0), `-p 3479:3479` (i=1), …
- per-container cloudflared tunnel + Steam session + `SELKIES_BASIC_AUTH_PASSWORD`

Constraints:
- **NVENC session cap ~5** on consumer GPUs (driver ≥470); unlimited on
  datacenter. `keylase/nvidia-patch` removes the consumer cap. Enterprise
  multi-tenant: **MIG** (A100/H100 isolated slices) or MPS + the patch.
- VRAM per session, GPU compute sharing (MPS/time-slicing).
- `DPAD_MAX_SESSIONS=1` forces a single session even on a multi-GPU VM.

**✅ VALIDATED: the 2-GPU AND 4-GPU VM tests PASSED** (2026-07-08; 2× and 4×
RTX 5060 Ti, compute_cap 12.0, driver 580.95.05). N CDI containers in
`DPAD_GAMESCOPE` mode → N independent streamed+interactive Steam UIs
(video+audio+keyboard+mouse+gamepad), zero modesetting contention, each
container's `nvidia-smi -L` shows exactly 1 GPU (distinct UUIDs). The 4-GPU
test surfaced a `setup_nvenc_fix` hex-letter-slot bug (fixed, see §10) — it
now works for any N. Two prerequisites were found + fixed for this to work
(both below):

1. **NVENC #1249 (the blocker).** On driver 570+ a gamescope container pinned
   to a non-zero GPU minor (dpad-1 → `/dev/nvidia1`) can't open NVENC
   (`NvEncOpenEncodeSessionEx ... error code 2`); the regular CUDA-12.5.1 image
   also can't drive Blackwell. Fixes: the flexgrip `libnvenc_fix.so` interposer
   is now wired into the gamescope path (`setup_nvenc_fix()` in the entrypoint,
   auto-enabled on driver 570..609 when host GPU count > mounted) AND its
   `/proc` gpuId→minor matching was fixed to use the full PCI address (single-bus
   multi-GPU hosts share bus 0, differ by slot). Plus `vm-bootstrap.sh` auto-
   selects `:SteamUbuntu24.04VM-rtx50` on `compute_cap ≥ 12`. See §10.
2. **CPU + RAM resource partitioning.** `vm-bootstrap.sh` divides the host's
   CPU + RAM evenly across the N containers (1/GPU), minus a host reserve:
   `per_cpus = (nproc - DPAD_RESERVE_CPUS)/N`, `per_mem = (MemTotal -
   DPAD_RESERVE_MEM_MB)/N`, applied as `--cpus` (hard quota; `DPAD_CPU_MODE`),
   `--memory`+`--memory-swap` (hard RAM cap) + `--memory-reservation` (soft
   floor) + `--pids-limit`. The GPU is already 1:1 per container via CDI. For a
   23-cpu/101GB/2-GPU VM → each tenant gets 10 cpu + ~47.5 GB + 1 GPU.
   Defaults: reserve 2 CPU + 4 GB. See the env-var table below.

Known minor quirk: browser **refresh occasionally shows "Waiting for stream"**
(a Selkies 1.6.2 WebRTC reconnect race; self-heals on a 2nd refresh; a fresh
incognito tab always works) — not the NVENC fix, see §10. (gamescope's EIS
socket `/run/user/<uid>/gamescope-0-ei` + `Successfully initialized libei for
input emulation!` remain available as a future input path, but XTest on `:0`
is validated and sufficient.)

---

## 9. Rebuild + push

```bash
cd dpadcloud/container-gaming
docker build -t forcespt/dpadcloud-gaming:SteamUbuntu24.04VM .
# RTX 50/Blackwell:
# docker build --build-arg CUDA_VERSION=12.8.1 --build-arg CUDA_PKG=12-8 \
#   -t forcespt/dpadcloud-gaming:SteamUbuntu24.04VM-rtx50 .
docker push forcespt/dpadcloud-gaming:SteamUbuntu24.04VM
```
The build-time Steam pre-bootstrap (`scripts/build-bootstrap-steam.sh`, Dockerfile
9g) adds ~3–5 min once (cached); it bakes `ubuntu12_64/steamwebhelper` in so a
fresh boot skips the ~3–4 min Steam download. A fresh `docker run` now reaches
the stream URL in **~50s** (was ~172s before the targeted-chown fix — see §7).

---

## 10. Troubleshooting — the full fix-chain knowledge (each a real on-instance bug)

| Symptom | Cause / Fix |
|---|---|
| `502 Bad gateway` at the trycloudflare URL | Selkies crashed. `docker exec dpad-0 tail /tmp/selkies.log`. Common: (a) python-xlib `add_extension_event` crash (`TypeError: 'type' object does not support item assignment` in xfixes.init) — fixed by `dpad_input_patch.py`'s monkey-patch; (b) pipewiresrc `target not found` + gamescope `Already had a buffer`/`stream state changed: error` — the gamescope PipeWire stream died. For (b): `always-copy=True` must be set on pipewiresrc (the patcher does this); if it still happens, set `DPAD_VIDEO_SRC=ximagesrc` to fall back to the `:2` bridge path. |
| gamescope `vulkan: vkCreateDevice failed (VkResult: -7)` / `Failed to create backend` | `nvidia_drm.modeset` is N. gamescope `--backend headless` on NVIDIA **needs modeset=Y**. Set it: `echo "options nvidia-drm modeset=1" > /etc/modprobe.d/nvidia-drm.conf && modprobe -r nvidia_drm && modprobe nvidia_drm modeset=1` (live; reboot persists). vm-bootstrap does this. |
| WebRTC media fails / no video, signaling OK | No TURN port exposed (need `-p 3478:3478/udp` or `/tcp`), or `VAST_UDP_PORT_3478`/`VAST_TCP_PORT_3478` not passed to the container (`DPAD_TURN_UDP_EXTERNAL_PORT`/`DPAD_TURN_EXTERNAL_PORT`). The entrypoint logs `WARNING: no TURN port exposed`. |
| Vast UI: "Duplicate Port Detected" | You tried `-p 3478:3478` + `-p 3478:3478/udp` (same port, both protocols). Vast forbids that. Pick ONE protocol per port — UDP (`-p 3478:3478/udp`) is recommended. |
| pipewiresrc `no more input formats` / `not-negotiated` + gamescope pipewire crash on browser connect | A 144Hz browser requested 144fps and `set_framerate` forced `framerate=144/1` on the live source (gamescope offers `0/1`). Fixed by the patcher: the pipewiresrc path keeps `format=BGRx` and uses `videorate` to throttle (never forces a framerate on the source). If it recurs, the patcher didn't run — check the Dockerfile step / `DPAD_VIDEO_SRC`. |
| FPS slider doesn't change the framerate (stays ~60) | On the pipewiresrc path the `videorate` element must be present (the patcher adds it). Without it, the slider is cosmetic (gamescope is a live source). Verify `videorate` is in the pipeline (`GST_DEBUG=videorate:4`). |
| pynput `ImportError: Can't connect to display ":0": Connection refused` at selkies start | `in_dpy` discovery picked a stale Xwayland display (gamescope restarted and picked a new number). Fixed: the discovery now takes the LAST `Starting Xwayland on :N` line. On a `docker restart` (vs a fresh `docker run`), stale `/tmp/.X11-unix/X*` sockets can also confuse gamescope — prefer a fresh `docker run`, or clean stale X sockets before restart. |
| `mmap() failed: Cannot allocate memory` under gamescope | Host `vm.max_map_count` too low → set `1048576` (§2d). NOT a RAM issue. |
| Steam "requires user namespaces to be enabled" / `unshare -U` EPERM as `dpad` | Host sysctls (§2c) unset OR container missing `--security-opt seccomp=unconfined apparmor=unconfined` + `--cap-add SYS_ADMIN`. Root `unshare -U` working is NOT enough — needs *unprivileged* userns. |
| steamwebhelper crash-loop / "Failed creating offscreen shared JS context" | `--shm-size=2g` missing (CEF shared mem). |
| `~/.local` EPERM aborts Steam bootstrap | A root boot process creates `~/.local` root-owned → Steam's `mkdir ~/.local/share/icons` EPERM. Fix: the entrypoint chowns ONLY non-dpad-owned files: `find /home/dpad ! \( -user dpad -group dpad \) -exec chown dpad:dpad {} +` before Steam. **Do NOT use a blanket `chown -R /home/dpad`** — on overlayfs without `metacopy` it copy-up's all ~33k files (~4 GB, ~120s) even when already dpad-owned (see the "Slow cold boot" row below). |
| Slow cold boot (~170s, with a ~120s gap between `audio sinks` and `Launching gamescope`) | A blanket `chown -R dpad:dpad /home/dpad` in the entrypoint copy-up's ALL ~33k files / ~4 GB into the overlay upper layer on a fresh container (containerd overlayfs has no `metacopy=on`, so every `chown()` copies the full file data up — EVEN when the owner is already correct). The build-time Steam pre-bootstrap already owns everything as `dpad:dpad`, so 0 files actually need chown — the 119s was pure waste. Fix (commit 2026-07-08): the targeted `find ... ! \( -user dpad -group dpad \)` form skips the 33k already-dpad-owned files → ~0.4s. Cold boot drops 172s → ~50s. Verify on a fresh container: `UP=$(grep -oE 'upperdir=[^,]+' /proc/$(docker inspect -f '{{.State.Pid}}' dpad-0)/mountinfo|cut -d= -f2); find $UP/home/dpad -type f | wc -l` should be ~0 immediately after boot (only Steam's own runtime writes appear later). |
| Steam first-run "UpdateUI CreateGlFont regular failed" → gamescope segfault loop | Steam's GL updater UI can't create its OpenGL font texture on gamescope headless Xwayland. Fix: `bootstrap_steam_on_xvfb()` pre-bootstraps on Xvfb (mesa/llvmpipe software GL) first; gamescope then runs the already-bootstrapped client. (Build-time `build-bootstrap-steam.sh` front-loads this.) |
| Health loop SIGKILLs a HEALTHY Steam every 30s / "Illegal termination of worker thread 'GL Composer Thread'" | Health check used `pgrep -x gamescope` (the comm isn't exactly "gamescope" → always false → murders Steam). Fix: `kill -0 $gs_pid`. |
| Bootstrap wait-loop never terminates | Completion check was `ubuntu12_64/steam` (32-bit, never exists) instead of `ubuntu12_64/steamwebhelper`. |
| Xvfb `:2` "Cannot establish any listening sockets - server already running" | Stale Xvfb `:2` holds the abstract socket. Fix: `pkill -9 -f "Xvfb :2"` + `rm -f /tmp/.X2-lock /tmp/.X11-unix/X2` before start; verify `[ -S /tmp/.X11-unix/X2 ]`. |
| `gst ... no element "ximagesink"` (the bridge fails) | System gstreamer lacks ximagesink. Fix: `gstreamer1.0-x` (+ `gstreamer1.0-plugins-base`) in the image. A stale gst registry right after apt install can fail once → `rm -rf ~/.cache/gstreamer-1.0` + retry. |
| Selkies XFIXES cursor monitor crashes (`Xlib.error.ConnectionClosedError`) → session loops | Was caused by python-xlib's `add_extension_event` TypeError during `display.Display()` (xfixes.init), which crashed EVERY `Display()` in the process. Fixed by `dpad_input_patch.py`'s `.pth` monkey-patch (promotes a TYPE to a dict so the dispatcher still works), applied before any `Display()`. After the fix `xfixes.init` succeeds (`Found XFIXES version 4.0`) and `--enable_cursors=true` is SAFE on the gamescope path (and REQUIRED — see the "No mouse cursor visible" row: gamescope headless does not composite the cursor, so the XFIXES overlay is the cursor's only visible source). |
| `BadRRModeError` / `failed to send keypress` spam | pynput keyboard touches RANDR modes on gamescope's Xwayland. `dpad_input_patch.py` uses XTest only (no pynput fallback). |
| Gamepad not detected by Steam / no controller in Big Picture | The full chain (6 layers) is in PROJECT_STATE.md's top UPDATE. Quick checks: (a) browser gamepad connected? `docker exec dpad-0 ls /tmp/selkies_js*.sock` (appears after you press a button). (b) watcher mknod'd the node? `docker exec dpad-0 ls /dev/input/js*` (a char device appears when the socket does; empty at boot is correct). (c) SDL3 opened + ACCEPTED it? `docker exec dpad-0 tail /tmp/selkies_js.log` — you must see the FULL probe `JSIOCGNAME -> JSIOCGBUTTONS -> JSIOCGAXES -> JSIOCGBTNMAP -> JSIOCGAXMAP`. If you ONLY see `JSIOCGNAME` (then the open closes), SDL3 REJECTED the device after the name probe = the interposer's JSIOCGNAME returned 0 = stale i386 `.so` (see below). (d) env on Steam? `docker exec -u 0 dpad-0 bash -lc "P=\$(pgrep -x steam); tr '\0' '\n' < /proc/\$P/environ | grep -E 'SDL_JOYSTICK|SDL_GAMECONTROLLERCONFIG'"` should show LINUX_CLASSIC=1 + DISABLE_UDEV=1 + DEVICE=/dev/input/js0 + SDL_GAMECONTROLLERCONFIG=0000d606.... **Root-cause gotcha (the layer BELOW the JSIOCGNAME source fix):** Steam's MAIN binary is 32-bit (`ubuntu12_32/steam`) → loads the i386 interposer. The Dockerfile rebuilds BOTH arches, but if `gcc-multilib`/`libc6-dev-i386` are missing the i386 `gcc -m32` step silently no-ops (used to be hidden by `2>\&1 \|\| true`) → the OLD unpatched deb i386 `.so` (JSIOCGNAME returns 0) ships → SDL3 rejects → no gamepad. The x86_64 `.so` being patched is NOT enough. **Stale-image check (correct — the `.so` is stripped, so do NOT use `strings`):** `docker exec dpad-0 ls -la /usr/lib/i386-linux-gnu/selkies_joystick_interposer.so /usr/lib/x86_64-linux-gnu/selkies_joystick_interposer.so` — if the i386 one is dated ~Aug 2024 (the deb) while x86_64 is the image-build day, the i386 rebuild failed → image STALE → rebuild. Live fix: `apt-get install -y gcc-multilib libc6-dev-i386` then `gcc -shared -fPIC -O2 -m32 -ldl -o /usr/lib/i386-linux-gnu/selkies_joystick_interposer.so /tmp/joystick_interposer_v162.c` + restart Steam. **Decisive validation (use the 32-BIT test, not 64-bit — Steam is 32-bit):** `gcc -O2 -m32 -o sdl3_guid_test32 scripts/sdl3_guid_test.c -L/home/dpad/.steam/debian-installation/ubuntu12_32 -l:libSDL3.so.0 -ldl -Wl,-rpath,/home/dpad/.steam/debian-installation/ubuntu12_32`, run as `dpad` with `LD_PRELOAD=/usr/lib/i386-linux-gnu/selkies_joystick_interposer.so SDL_JOYSTICK_LINUX_CLASSIC=1 SDL_JOYSTICK_DISABLE_UDEV=1 SDL_JOYSTICK_DEVICE=/dev/input/js0 SDL_GAMECONTROLLERCONFIG=0000d606...` while a browser gamepad is connected → expect `count=1, GUID=0000d60653656c6b69657320436f6e00, IsGamepad=1`. (The 64-bit test passing while the 32-bit fails is the tell.) If still not a gamepad after the i386 fix, switch to the evdev fallback (`scripts/gamepad-evdev-fallback/README.md`). |
| `/tmp/selkies_js.log` shows `Intercepted open call` + `Read config from socket` but Steam still doesn't navigate | The device is now ACCEPTED by SDL3 (with the patched interposer) + mapped as a gamepad (IsGamepad=1). If Steam Big Picture still doesn't respond, check button/axis mapping: wiggling the LEFT STICK should move the Big Picture selection (`leftx:a0,lefty:a1`); the D-pad uses hat 0 (`dpup:h0.1` etc.). A `jstest /dev/input/js0` run under the interposer (install the `joystick` pkg) confirms raw events. If only some controls are dead, the `SDL_GAMECONTROLLERCONFIG` mapping indices may need tweaking against `STANDARD_XCONFIG` in `gamepad.py`. |
| **No mouse cursor visible** (windowed or fullscreen) in the gamescope stream | gamescope `--backend headless` does NOT composite the X cursor into its PipeWire output (the cursor's only visible source is Selkies' XFIXES CSS-cursor overlay), AND the Selkies web client auto-engages pointer lock on fullscreen+click which HIDES the CSS cursor. Fix (baked into the image): the gamescope Selkies launch uses `--enable_cursors=true` (the XFIXES overlay; safe now that `dpad_input_patch.py` fixes the old `add_extension_event` 502 crash) + `scripts/patch_gst_web_cursors.sh` injects a gate in `/opt/gst-web/input.js` that disables auto pointer lock (`window.DPAD_POINTER_LOCK` default false) so the server cursor stays visible + mouse is absolute. Verify the web client is patched: `docker exec dpad-0 grep -c DPAD_pointer-lock /opt/gst-web/input.js` (should be 1+) — if 0 the image is stale (rebuild) or hard-refresh the browser (Ctrl+Shift+R) to bypass cached JS. To re-enable pointer lock for an FPS game: browser console `window.DPAD_POINTER_LOCK = true` then click the video. |
| Mild flicker on Steam menu open/close | **NVIDIA 580 driver regression** (gamescope issue #1964, open). gamescope + Steam overlay/menu transitions cause artifacts+flicker on NVIDIA driver 580; the confirmed fix is downgrading the NVIDIA driver 580 → 575 (host-level, not image-fixable; gamescope flags `--immediate-flips`/`--force-composition` do NOT help). The `pipewire: out of buffers` + `xwm: got the same buffer committed twice` in gamescope-steam.log are symptoms, not the cause — a GStreamer `queue` after pipewiresrc + `-r 60` were live-tested and did NOT reduce either, confirming it's not a pool/always-copy/rate issue. Verify: `docker exec dpad-0 nvidia-smi --query-gpu=driver_version --format=csv,noheader` → 580.x = affected. Accepted as a known mild NVIDIA-580 limitation (no image fix). Production mitigation: offer filter preferring driver <580 (smaller pool). |
| Steam shows "no internet" / "can't reach Steam servers" icon but login+install+play work | NOT a NAT timeout and NOT a dual-login (confirmed: user not logged in elsewhere; conntrack established timeout is 432000s). The Steam connection_log shows `ConnectionDisconnected('Disconnected By Remote Host') : 'Failure'` + `RecvMsgClientLogOnResponse: 'Try another CM'` every ~70s — Steam's CM servers bounce the WebSocket session, likely the Vast datacenter IP being bounced by CM load-balancing. Steam recovers + login/install/play work; the icon + ~70s bounce persist. Steam-side, not fixable from the image. A separate cosmetic Steam-UI error `TypeError: SteamClient.System.Network?.StartScanningForNetworks is not a function` (library.js) is a Steam client/JS-API version mismatch (Steam's own code), pre-existing. |
| `webrtcnice ... failed to resolve "<uuid>.local": Temporary failure in name resolution` | Harmless — Chrome's mDNS `.local` ICE candidates the container can't resolve; the connection succeeds via the TURN relay candidate. Don't chase. |
| `remote resize is disabled, skipping resize to 2552x1308` | Harmless — hi-DPI browser asked for a bigger size; `--enable_resize=false` fixes the stream at 1920x1080. |
| On a 4+ GPU VM, dpad-2/dpad-3 (GPU slots with hex letters: `0B`, `0D`) get `NVENC_FIX: mask 0x1` (wrong) → encoder fails → Selkies DOWN; dpad-0/dpad-1 (slots `07`/`09`, no letters) are fine | `setup_nvenc_fix` compared the PCI bus string case-sensitively, but nvidia-smi `pci.bus_id` emits UPPERCASE hex (`00:0B.0`) while `/proc/driver/nvidia/gpus` is lowercase (`0000:00:0b.0`) — slots with hex letters (B,D,F…) never matched → `VISIBLE_BITMASK` fell back to index→minor (always 0) → wrong `NVENC_FIX_AVAILABLE` → interposer kept the wrong GPU. Fix (commit ee46fe4, `entrypoint.sh`): lowercase both keys with `${var,,}` before comparing. Verify: every container logs the correct `DPAD_NVENC_FIX: ... mask 0x1/0x2/0x4/0x8/...` matching its GPU index. (The 2-GPU test missed this because slots 07/09 have no letters.) |
| NVENC `element NOT FOUND` / `NvEncOpenEncodeSessionEx ... error code 2` / `NV_ENC_ERR_UNSUPPORTED_DEVICE` on a multi-GPU VM (dpad-1 on `/dev/nvidia1` has no video; encoder fails at register AND at peer-connect → 502) | nvidia-container-toolkit **#1249 / #1209** + k8s-device-plugin **#1282** (driver 570-580; only fixed in 610.x): NVENC's `GET_ATTACHED_IDS` returns ALL host GPUs, peer-inits with the unmounted `/dev/nvidia0`, bails. Fix: the flexgrip `libnvenc_fix.so` LD_PRELOAD interposer (scripts/nvenc_fix.c) filters the list to only mounted GPUs. Two fixes shipped 2026-07-08: (a) the interposer's `/proc` gpuId→minor matching now uses the FULL PCI address (`slot=gpuId&0xFF, bus=gpuId>>8, domain=gpuId>>16`) — the old bus-only match failed on single-bus multi-GPU hosts; (b) the interposer is now wired into the GAMESCOPE path (`setup_nvenc_fix()` in the entrypoint, called before the LD_PRELOAD assembly) — it was only in the DFP path (after the gamescope `exit 0`). Auto-enabled on driver 570..609 when host GPU count > mounted; `DPAD_NVENC_FIX=1\|0\|auto`. Verify: selkies.log shows `KEEPING gpuId 0x.. (minor N)`, `filtered: 2 -> 1 GPUs`, and 0 `NvEncOpenEncodeSessionEx failed`. Single-GPU hosts (`gpu_frac=1`) are immune on any driver. |
| Browser **refresh** sometimes shows "Waiting for stream" (audio-only SDP; `attempt to send data channel message before channel was open` in the browser console) | A Selkies 1.6.2 WebRTC reconnect race (each peer DOES get a fresh webrtcbin via `start_pipeline`, so it's not stale state; the new peer's ICE/data-channel occasionally doesn't re-establish). **Self-heals on a 2nd refresh; a fresh incognito tab always works.** NOT the NVENC fix (the interposer doesn't touch networking). A restart-on-disconnect supervisor would make it 100% consistent (deferred — adds a 5-8s reconnect flash). Acceptable workaround: refresh once more, or open a fresh tab. |
| selkies.log `cudanvrtc ... couldn't compile nvrtc program ... invalid value for --gpu-architecture (-arch)` on Blackwell | Non-fatal/cosmetic: the bundled GStreamer ships a CUDA **11.4** `libnvrtc` (`/opt/gstreamer/.../libnvrtc.so.11.4.152`) that can't JIT-compile for sm_120; the plugin falls back to a pre-compiled cubin so video works. (A real fix would make the CUDA 12.8 libnvrtc win, but the plugin links soname 11 — deferred.) Ignore. |
| nvenc_fix logs a ~3/sec `GET_ATTACHED_IDS ... filtered: 2 -> 1 GPUs` stream in selkies.log | Benign NVENC monitoring-thread poll, logged because `NVENC_FIX_DEBUG=1` (the entrypoint sets it when the fix is enabled). Not a loop bug; set `DPAD_NVENC_FIX=0` to disable the fix+logging if you want silence (but you lose the #1249 fix). |
| `~/.steam/root` a real dir → steam.sh `rm -f ~/.steam/root` fails | Dockerfile step 9f relocates Proton-GE to `~/.steam/debian-installation/compatibilitytools.d` and makes `~/.steam/root` a symlink. |
| `pulseaudio: command not found` (gamescope audio path) | No PulseAudio daemon in the image (only `pulseaudio-utils`/`pactl`). Fix: audio uses **`pipewire-pulse`** (the running PipeWire serves a Pulse-compatible socket) + `pactl load-module module-null-sink` for `dummy.monitor`. |

### Proven (don't re-test)
- userns→pressure-vessel→CEF stable with `--shm-size=2g` + the host sysctls.
- CDI gives per-GPU isolation + `/dev/dri/cardX`; `OpenGL renderer: NVIDIA …` (not llvmpipe).
- gamescope headless renders real Steam UI content on the PipeWire node (non-black 1080p frame).
- XTest on `:0` reaches Steam's X11 windows (keyboard + mouse + buttons + scroll) — Stage 3a validated.
- No-tunnel dual-ICE TURN works at the Vast external port; browser connects without SSH.

---

## 11. The two product paths (provider split)

| Provider | Mode | Steam UI | Multi-tenant |
|---|---|---|---|
| **Vast KVM VM (ubuntu_cli_22.04-2025-11-21)** + nested Docker | `DPAD_GAMESCOPE=1` (gamescope headless) | ✅ full interactive (video+audio+kbd+mouse in browser), cloud/online | ✅ N-on-N-GPUs (no DRM master) — **validated 2-GPU (2× RTX 5060 Ti)** + CPU/RAM partitioning |
| Vast KVM VM, DFP path (`DPAD_GAMESCOPE=0`) | Xorg + nvidia DDX, DRM master | ✅ full Steam | ❌ 1 full-Steam per VM (modeset singleton) |
| Vast Docker / RunPod Community Cloud | headless `steamcmd + dpad-launch` | ❌ (no userns → CEF crashes under bubbleroot/proot) | single-player, local saves |
| Bare-metal + QEMU/KVM/VFIO (one VM/GPU) | DFP | ✅ full Steam | ✅ N full-Steam on one host (separate driver instances) |
| RunPod Secure Cloud | (untested) DFP | likely ✅ (userns) | TBD |

The **gamescope headless path on the Vast KVM VM is the validated MVP** and the
path to N-on-N-GPUs multi-tenant full-Steam on one VM.