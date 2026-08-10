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
| `DPAD_STORE_SHELL` | `steam` | **Multi-store (STORES-PLAN.md, 2026-08-07).** `steam` (default) = the validated `gamescope ... -- steam -gamepadui` shell. `lutris` = the **Lutris gamepad-UI store-picker shell** (`gamescope ... -- /opt/dpadcloud/lutris-shell`; Epic+GOG+Battle.net, no forced Steam login). The entrypoint `DPAD_STORE_SHELL` gate is shell-aware (ready-check + health-loop). The image bakes GE-Proton11-3 + Lutris + the `lutris-gamepad-ui` AppImage; `scripts/lutris-shell` wraps it (`LUTRIS_GAMEPAD_UI_ENABLE_SDL_INPUT=1` + `--no-sandbox`). Passed per-session: the cloud worker writes it to `/etc/environment` at bootstrap (opt-in via `deploy/vps/docker-compose.yml`) + `dpad-launch-session` forwards it to the container. **Live validation PENDING** (blocked by a pre-existing worker<->Scaleway bootstrap-SSH issue, STORES-PLAN section 16). |
| `DPAD_STORES` | (unset) | The stores the entrypoint should wire/symlink (e.g. `steam,epic,gog,battlenet`). v1.1 reserved: `ea-app`,`ubisoft`. Same plumbing as `DPAD_STORE_SHELL` (worker -> `/etc/environment` -> `dpad-launch-session`). |
| `DPAD_GAMEPAD_INTERPOSER` | (unset) | `evdev` = the **evdev gamepad path** (fake-libudev + evdev interposer + `evdev_bridge.py`; SDL3 auto-detects 4 X-Box 360 pads, no GUID hack; see `scripts/gamepad-evdev-fallback/README.md`). Unset = the classic joystick path (the default; the v1.6.2 interposer + `SDL_JOYSTICK_LINUX_CLASSIC` + the hardcoded GUID). **VALIDATED END-TO-END with a real controller 2026-08-04** (Steam Big Picture navigates); two blocking bugs fixed (i386 fake-libudev SONAME + bridge socket chmod) — **needs an image rebuild + push to ship**. NOTE: the control plane does NOT pass this per-session (the worker writes only a fixed `/etc/environment` list at bootstrap) — to test/use evdev on a normal dpadplay session, wire it into the control plane (cloud `apps/worker/src/index.ts:711-726`) or run a manual container (below). |
| `DPAD_COMPOSITOR` | `gamescope` | **gst-wayland-display path (WAYLAND-ARCHITECTURE.md §14).** `gamescope` (default) = the unchanged gamescope-headless compositor (no regression). `wayland-display` = the Smithay micro-compositor runs AS the GStreamer source (`waylanddisplaysrc`): it inits EGL off the DRM render node (NO DRM master → N-on-N) + a Wayland client (gamescope `--backend wayland` OR sway) renders into it; the compositor is the capture source. Inverted boot: selkies (the compositor) launches FIRST → `DPAD_READY` (listening) → a peer connects → compositor starts → `wayland-N` socket appears → the wayland client launches. Gate `start_wayland_display_session` in entrypoint.sh. `dpad-launch-session` adds `--device /dev/dri` (the compositor opens the render node directly via `EGL_EXT_device_drm_render_node`). PENDING full live validation (§16: compositor+capture+webrtcbin proven `m=video:9`; the gamescope-wayland client connection drop §16.3 is the remaining layer). |
| `DPAD_WAYLAND_CLIENT` | `gamescope` | **The Wayland client of gst-wayland-display (§16.4).** `gamescope` (default) = `gamescope --backend wayland -- <shell>` (provides XWayland to Steam/Lutris) — hits the §16.3 client-connection drop on Nvidia after Steam launches (`IWaitable hung up`). `sway` = the §16.4 fallback: `sway --unsupported-gpu -c /tmp/dpad-sway.config` run NESTED as a Wayland client (`WLR_BACKENDS=wayland` → no DRM master → N-on-N preserved), the games-on-whales `RUN_SWAY=1` model — more stable on Nvidia. sway provides XWayland; the compositor still captures it. Needs `sway`+`xwayland` baked (Dockerfile vast-vm stage; a spike-tag rebuild) — if `sway` is missing the entrypoint falls back to gamescope with a warning. PENDING live validation. |
| `DPAD_VIDEO_SRC` | `pipewiresrc` | `pipewiresrc` = direct PipeWire capture (zero-copy-ish). `ximagesrc` = the `:2` Xvfb bridge fallback. Under `DPAD_COMPOSITOR=wayland-display`, the entrypoint sets this to `waylanddisplaysrc` (the compositor IS the capture source) — see `DPAD_COMPOSITOR`. |
| `DPAD_SELKIES_BIND` | `127.0.0.1` | Selkies signaling bind. `127.0.0.1` for the SSH-tunnel path; **`0.0.0.0` for direct-IP providers** (UpCloud/Hyperstack/MassedCompute) so Caddy reverse-proxies HTTP straight to `<public-ip>:16100`. |
| `DPAD_TUNNEL` | (unset) | `ssh` gates cloudflared OFF (the B1 self-hosted `play-<id>.dpadplay.com` path). Unset = cloudflared quick tunnel (legacy). |
| `DPAD_DEFAULT_GAMING_MODE` | `0` | `1` = default the browser to **Gaming mode** (pointer lock ON → relative mouse for FPS aim) on stream load; `0` = Desktop mode (visible cursor + absolute mouse for Steam UI). The user can still toggle at runtime (floating button / `Ctrl+Shift+G`). Wired through `patch_gst_web_cursors.sh`; the control plane can set it per region/tier. |
| `DPAD_INPUT_HOTFIX` | `0` | The 2026-08-05 image rebuild baked the input fixes (scroll direction + Gaming-mode toggle), so the boot-time overlay from repo `main` is **OFF by default** (avoids a `main`-regression overwriting the just-pushed image). Set `=1` to re-overlay `dpad_input_patch.py` + `patch_gst_web_cursors.sh` from `main` (useful to ship a NEW input hotfix before the next rebuild); on fetch failure it falls back to the baked copies. |
| `DPAD_WD_WIDTH` / `DPAD_WD_HEIGHT` | `1920` / `1080` | **Stream resolution (wayland-display path, §18.6/§18.7).** Sets the compositor's caps (`DPAD_STREAM_WIDTH/HEIGHT` in the selkies launch) + sway's `output * mode --custom` (the no-letterbox fix — sway's nested wayland backend ignores the compositor's `wl_output.mode` + defaults to 720p without it). The cloud worker reads `preferences.resolution` + passes these per-session via an `env` prefix on `dpad-launch-session`; `dpad-launch-session` forwards them to `docker run -e`. |
| `/tmp/dpad_resolution` (in-container state file) | `DPAD_WD_WIDTH x DPAD_WD_HEIGHT` | **Live resolution switch (§18.7).** Written by the selkies `_arg_res` data-channel handler (the in-stream **Resolution** dropdown). The entrypoint's `build_selkies_cmd()` + the sway heredoc read it on every selkies (re)launch, so writing it + SIGTERM-ing selkies → the health loop relaunches selkies (new caps) + sway (new output mode) at the new resolution; the browser reconnects ~6s. Not an env var — a runtime state file. |
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
| No mouse cursor visible | `--enable_cursors=true` missing OR the web client isn't patched (`patch_gst_web_cursors.sh`). Hard-refresh the browser (Ctrl+Shift+R). |
| Can't aim / no camera-look in an FPS game | The browser is in Desktop mode (absolute mouse). Toggle **Gaming mode** with the floating bottom-right button or `Ctrl+Shift+G` (a badge shows the state), then click the stream to lock the pointer → relative mouse. `Esc` releases. For a per-tier default, set `DPAD_DEFAULT_GAMING_MODE=1`. Baked in the public image since the 2026-08-05 rebuild; if the button is absent on a stale VM, hard-refresh, re-provision, or set `DPAD_INPUT_HOTFIX=1` to overlay. |
| Mouse scroll is reversed | Fixed in the public image since the 2026-08-05 rebuild (`dpad_input_patch.py` maps XTest `MOUSE_SCROLL_UP→button 5`, `MOUSE_SCROLL_DOWN→button 4` — intentionally "backwards" because Selkies v1.6.2's scroll constants are inverted vs the physical wheel; stock pynput cancels it with a flipped `dy`, XTest is literal). On a pre-rebuild VM, re-provision or set `DPAD_INPUT_HOTFIX=1` to overlay the fix. |
| Mild flicker on Steam menu open/close | NVIDIA 580 driver regression (gamescope #1964). Accepted; host-side. **Severe whole-frame flicker = driver 595** → the host must downgrade 595 → R580 LTS (see `cloud/docs/DEPLOY-RUNBOOK.md`). |
| Browser refresh occasionally "Waiting for stream" | Selkies 1.6.2 reconnect race. Self-heals on a 2nd refresh; a fresh incognito tab always works. **A restart-on-disconnect supervisor (`entrypoint.sh` `relaunch_selkies()` in the gamescope-session health loop) auto-relaunches `selkies-gstreamer` when it dies while gamescope is up, so the browser reconnects without a manual refresh — validated live 2026-08-05 (OVH Gravelines L4: killed selkies mid-stream, health loop relaunched it within ~20s)** (`PROJECT_STATE.md` §6 #7). |
| `webrtcnice … failed to resolve "<uuid>.local"` | Harmless — Chrome's mDNS `.local` ICE candidates the container can't resolve; the TURN relay handles it. |
| `remote resize is disabled, skipping resize to 2552x1308` | Harmless — hi-DPI browser asked bigger; `--enable_resize=false` fixes the stream at the compositor's caps (set by `DPAD_WD_WIDTH/HEIGHT` or the live Resolution dropdown). |
| Live Resolution dropdown missing / no `_arg_res` | The 2026-08-09 rebuild bakes the in-stream **Resolution** select (720p/1080p/1440p/4K) + the `_arg_res` handler. On a pre-08-09 image, re-provision (`docker pull forcespt/dpadcloud-gaming:dpad-SteamOS`) — the boot-time `patch_live_resolution.py` overlay also fetches it from `main` as a backstop. Picking a resolution writes `/tmp/dpad_resolution` + SIGTERMs selkies; the entrypoint health loop relaunches selkies (new compositor caps) + sway (new `output * mode --custom`) at the new res; the browser reconnects ~6s (signalling.js auto-retry). See WAYLAND-ARCHITECTURE.md §18.7. |
| Battle.net install stalls / `Agent.exe error=2` / `BLZBNTBTS0000005C` | RESOLVED by the umu-launcher pivot: `battlenet-launch` runs the Blizzard installer + Agent.exe under `umu-run` (GE-Proton inside the Steam Linux Runtime — Valve's tested wow64) instead of raw `wine`. Live-validated on an OVH L4: the 32-bit Agent.exe launches (no `error=2`), Battle.net installs + launches. Requires the `:dpad-SteamOS` rebuild that bakes `umu-launcher` 1.4.4 (digest `sha256:e5ad5baaa7ea…`). The SLR + pressure-vessel download to `$HOME/.local/share/umu` on the first `umu-run` (~1–2 GB, one-time per VM). |
| Battle.net UI white-screens (content only on hover-damage) under umu/SLR | The CEF GPU present path (`CrGpuMain`) is broken under Xwayland-in-SLR (the SLR's `libnvidia-egl-wayland` can't find `libwayland-server.so.0`; the pre-written `Battle.net.config` `HardwareAcceleration:false` is not sufficient — the GPU process still spawns). `battlenet-launch` (commit `85b6a85`) now passes `--disable-gpu --in-process-gpu` to Battle.net.exe → CEF software compositing, no `CrGpuMain`, the login UI renders solidly. Env-overridable via `DPAD_BATTLENET_CEF_ARGS`. (Games install/run separately under their own Proton, unaffected.) |
| `pressure-vessel-wrap: … bwrap: Can't mount proc on /newroot/proc: Operation not permitted` (umu/Proton launch) | The session container is missing the 4th bwrap-nest flag. The session runs `--cap-add SYS_ADMIN` + `--security-opt seccomp=unconfined apparmor=unconfined` (the umu #156 / Noble-AppArmor-userns set); add `--security-opt systempaths=unconfined` to the `docker run` so bwrap can remount `/proc` in the new pid+mount namespace. **Live-validated on OVH L4 with all 4 flags — no `/proc` error.** `dpad-launch-session` (the cloud worker's launch script) needs the same `--security-opt systempaths=unconfined` added for the `DPAD_COMPOSITOR=wayland-display` + umu path — a cloud-repo follow-up (the manual test `docker run` included it). |

## Multi-tenant — N sessions on N GPUs in one VM

`vm-bootstrap.sh` launches one CDI container per GPU (per-container GPU via
`NVIDIA_VISIBLE_DEVICES=nvidia.com/gpu=i`, per-container coturn port
3478/3479/…, per-container `--cpus`/`--memory` quota from
`compute_session_resources()`). No DRM master → no modesetting contention.
Validated 2-GPU + 4-GPU. For oversubscription (N > GPUs) under MPS, see
`cloud/docs/PROVIDERS.md` + the `DPAD_OVERSUBSCRIBE`
plan.

## Rebuild + push

The public `:dpad-SteamOS` tag is **current as of the 2026-08-09 rebuild** —
it bakes the **live in-stream Resolution dropdown** (720p/1080p/1440p/4K, next
to Video bitrate — the `_arg_res` data-channel handler + the `build_selkies_cmd`
+ sway `output * mode --custom` machinery, WAYLAND-ARCHITECTURE.md §18.7) ON TOP
of the 2026-08-05 fixes (input scroll direction + Gaming-mode toggle + evdev
i386 fake-libudev SONAME + bridge socket-chmod). A fresh `docker pull` gets all
of it; no hotfix overlay needed (`DPAD_INPUT_HOTFIX` defaults to `0`). The
boot-time `patch_live_resolution.py` overlay stays as an idempotent backstop
(it skips when the feature is already present) so future web-client/handler
fixes can ship without a rebuild. Rebuild only when new fixes land in `main`.

```bash
docker build --target vast-vm -t forcespt/dpadcloud-gaming:dpad-SteamOS .
docker build --target vast-vm --build-arg CUDA_VERSION=12.8.1 --build-arg CUDA_PKG=12-8 \
  -t forcespt/dpadcloud-gaming:dpad-SteamOS-rtx50 .
docker push forcespt/dpadcloud-gaming:dpad-SteamOS
```

**2026-08-09 rebuild — live-validated on OVH Gravelines L4** (`79.137.11.29`,
container `wd-probe`, wayland-display path): pulled the fresh image + ran it
with NO `entrypoint.sh` bind-mount (pure baked image) → the Resolution
dropdown is present in the served `index.html`, the `_arg_res` handler is in
the baked `webrtc_input.py`, + a 4K pick from the dropdown switched the live
stream to `3840x2160` (xrandr `WL-1 connected 3840x2160`, sway mode forced, no
letterbox) via the `/tmp/dpad_resolution` → selkies+sway restart path.

## Evdev gamepad path — manual real-controller test (DPAD_GAMEPAD_INTERPOSER=evdev)

The evdev path is gated behind `DPAD_GAMEPAD_INTERPOSER=evdev` (default unset =
classic). **VALIDATED END-TO-END with a real controller on 2026-08-04** (OVH
Gravelines L4 — Steam Big Picture navigated); two blocking bugs were found +
fixed (see `PROJECT_STATE.md` §6 #9): the i386 fake-libudev SONAME
(`libudev_x86.so.1` → `libudev.so.1`) + the bridge event-socket chmod
(`evdev_bridge.py` `os.chmod 0o777`). **Both fixes are baked in the public
image since the 2026-08-05 rebuild + push — evdev now works on a fresh `docker
pull` (no bind-mount workaround needed).** The bind-mount instructions below are
only for a PRE-rebuild image (or to test a newer bridge hotfix without a rebuild):
bind-mount a fixed `dpad_fake_libudev.so` (i386, soname `libudev.so.1`) + the
fixed `evdev_bridge.py`. (The `.so` must be built with `fake-udev/Makefile`
`all32` after the soname fix; the bridge is the repo `scripts/evdev_bridge.py`.)

```bash
VM_IP=<the-vm-public-ip>
docker run -d --name evdev-pad-test --runtime=nvidia \
  -e NVIDIA_VISIBLE_DEVICES=nvidia.com/gpu=0 \
  --cap-add SYS_ADMIN --security-opt seccomp=unconfined --security-opt apparmor=unconfined \
  --shm-size 2g --ulimit nofile=1048576:1048576 \
  -p 3478:3478/udp -p 16100:16100 \
  -e DPAD_GAMESCOPE=1 -e DPAD_GAMEPAD_INTERPOSER=evdev \
  -e DPAD_SELKIES_BIND=0.0.0.0 -e DPAD_TUNNEL=ssh \
  -e DPAD_TURN_PUBLIC_IP=$VM_IP -e DPAD_TURN_UDP_EXTERNAL_PORT=3478 \
  -e SELKIES_BASIC_AUTH_USER=dpad -e SELKIES_BASIC_AUTH_PASSWORD=testpass \
  forcespt/dpadcloud-gaming:dpad-SteamOS
docker logs -f evdev-pad-test
# look for: [*] Gamepad: EVDEV path (DPAD_GAMEPAD_INTERPOSER=evdev) ...
#          dpad_gamepad: patched SelkiesGamepad.__make_config -> 1360-byte evdev interposer config
#          [evdev_bridge] bridge up: 4 pads (js -> event1000-1003)
#          DPAD_READY slot=0 ... encoder=nvh264enc
```
Then open `http://$VM_IP:16100` (login `dpad`/`testpass`), **connect a controller
to your browser/machine + press a button**, and Steam Big Picture should detect
a **Microsoft X-Box 360 pad** (auto-mapped — no `SDL_GAMECONTROLLERCONFIG` GUID
hack) — verify buttons/sticks/triggers/dpad, ideally rumble + a 2nd pad. The
browser Gamepad API needs a button press to activate. Teardown:
`docker rm -f evdev-pad-test`. To make a normal dpadplay session boot evdev, wire
the env into the control plane (cloud `apps/worker/src/index.ts:711-726`: add
`echo "DPAD_GAMEPAD_INTERPOSER=evdev" >> /etc/environment` to the bootstrap) +
redeploy the worker. See `scripts/gamepad-evdev-fallback/README.md`.