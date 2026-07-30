# DpadCloud Container Gaming — Image State & Handoff

> **Lean handoff (2026-07-30).** Current state of the
> `forcespt/dpadcloud-gaming` images: what's built, what's validated, the
> baked-in fixes, the known limitations, and the open image-side items. The full
> debug journey (gamescope breakthrough, N-on-N validation, the 6-layer
> gamepad fix chain, the bubbleroot/steamcmd dead-ends, the wrong-then-corrected
> driver diagnoses) is preserved in `git log` — this doc is the resume point,
> not the history.
>
> **Companion:** `IMAGE-RUNBOOK.md` (the launch recipe + env-var reference +
> troubleshooting — the operational runbook), `cloud/docs/STATUS.md` (the
> control-plane handoff), `cloud/docs/V2-PLAN.md` (the post-Vast architecture).

## 1. The images

One multi-stage Dockerfile; `--target` selects the image. v2 uses the
`:dpad-SteamOS` family exclusively (full-VM providers with userns → full
Steam).

| Tag | Target | CUDA | Use |
|---|---|---|---|
| `:dpad-SteamOS` | `vast-vm` | 12.5.1 | **Ada** (Turing/Ampere/Ada: RTX 20/30/40, GTX 16, T4, A10, A40, L4, L40S, RTX 6000 Ada). The default. |
| `:dpad-SteamOS-rtx50` | `vast-vm` | 12.8.1 | **Blackwell** (RTX 50, RTX PRO 6000 Blackwell; sm_120/121). Driver ≥570. |
| `:dpad-SteamOS-L4` | `vast-vm` | 12.5.1 | L4 oversubscription variant: gamescope **3.16.25** + the `drmProps` headless patch + libpixman 0.46.4. **Built locally on the UpCloud box; NOT pushed to Docker Hub** (owner step — public tag is the stale 3.16.19 image). |

**Build:**
```bash
docker build --target vast-vm -t forcespt/dpadcloud-gaming:dpad-SteamOS .
docker build --target vast-vm --build-arg CUDA_VERSION=12.8.1 --build-arg CUDA_PKG=12-8 \
  -t forcespt/dpadcloud-gaming:dpad-SteamOS-rtx50 .
```
Build-time Steam pre-bootstrap (`scripts/build-bootstrap-steam.sh`) bakes
`ubuntu12_64/steamwebhelper` in → a fresh boot skips the ~3–4 min Steam
download (cold boot ~50s). The `gamescope-builder` stage clones the gamescope
**3.16.25** tag + applies `scripts/gamescope-headless-drmprops.patch`.

**Deprecated (Vast dropped 2026-07-28):** `:dpad-heroic` / `:dpad-heroic-rtx50`
(Vast Docker, no userns → Heroic storefront via the `umu_run.py` → Proton-direct
bypass) and the headless `steamcmd` + `dpad-launch` path. v2 is SteamOS-only on
full-root VMs. See §7.

## 2. The pipeline (gamescope headless)

```
gamescope --backend headless -e -W 1920 -H 1080 -- steam -gamepadui
   │  renders Steam on the GPU via Vulkan/gamescope-WSI, NO DRM master
   │  → PipeWire video node (BGRx 1920x1080, modifier 0 = system memory)
   │  → Xwayland :0 (Steam's CEF/X11 UI runs here)
   ▼
[Selkies capture — pipewiresrc direct, NO Xvfb :2 / ximagesrc bridge]
   pipewiresrc(target-object=gamescope, always-copy=True) → videorate (FPS throttle)
   → cudaupload → cudaconvert(BGRx→NV12) → nvh264enc → webrtcbin → coturn → browser
[Audio]  pipewire-pulse null sink (dummy.monitor) → Selkies pulsesrc
[Input]  browser WebRTC datachannel → Selkies → xtest.fake_input on :0 → Xwayland → Steam
[Gamepad] browser gamepad → Selkies → /tmp/selkies_jsN.sock → root watcher mknods /dev/input/jsN
          → v1.6.2 joystick interposer (LD_PRELOAD, open() redirect) → SDL3 classic → Steam Big Picture
```

`gamescope --backend headless` is the multi-tenant enabler: it renders via
Vulkan/gamescope-WSI with **no DRM master** → no nvidia-modeset singleton →
**N sessions on N GPUs in one VM** (validated 2-GPU + 4-GPU). Capture is
`pipewiresrc` (system-memory BGRx, not true dmabuf zero-copy, but the old `:2`
Xvfb round-trip + CPU `videoconvert` passes are gone). `DPAD_VIDEO_SRC=ximagesrc`
reverts to the `:2` bridge fallback.

## 3. Validated state

- **1:1 + N-on-N:** 1-GPU (RTX 3060/580), 2-GPU + 4-GPU (RTX 5060 Ti, sm_120),
  each container sees exactly 1 GPU (CDI `NVIDIA_VISIBLE_DEVICES=nvidia.com/gpu=i`).
- **Gamepad in Steam Big Picture:** D-pad/sticks/A navigate; the 6-layer fix is
  baked (§4). Validated with a real controller.
- **Cold boot ~50s** to the stream URL (was 172s before the targeted-chown fix).
- **RTX 50 / Blackwell (cuda 13.3):** RTX 5080/5090 stream with the GLVND bake
  (no zink fallback). `:dpad-SteamOS-rtx50` selected per `compute_cap ≥ 12`.
- **Stream quality:** Selkies `nvh264enc` (hardware) on all tested drivers
  (580/595/610). Built-in Opus inband FEC + ULP_RED video FEC + NACK rtx
  (gated on `DPAD_AUDIO_PACKETLOSS` / `DPAD_VIDEO_PACKETLOSS`).
- **MPS oversubscription (N-on-1) — 2:1 validated live 2026-07-30 (UpCloud L4):**
  two Casual sessions on one L4 via the host MPS daemon — 2nd session reused the
  ready VM's slot 1 (no boot), both containers `DPAD_READY`, both `gamescope`
  processes on the GPU via `nvidia-cuda-mps-server`, each with its own 200 GB
  ephemeral cap, Steam Storage showed 200 GB on both. (3:1 + active-gameplay
  frame-time still open — see `cloud/docs/STATUS.md` §8.)

## 4. The baked-in fixes (don't re-discover)

| Fix | Where | What |
|---|---|---|
| **gamescope `drmProps` headless patch** | `scripts/gamescope-headless-drmprops.patch` (gamescope-builder stage) | gamescope's `VkPhysicalDeviceDrmPropertiesEXT` query returns zeros on these configs → "physical device has no primary node" → headless backend aborts. Patch relaxes the headless `!hasPrimary` abort to a warning + adds a `/dev/dri/renderD*` scan fallback when `hasRender` is false. Required on every host (driver-agnostic). Upstream PR #2073 only covers the `!hasDrmProps` branch, not ours. |
| **Vulkan ICD → `libEGL_nvidia.so.0`** | `entrypoint.sh` (after install-display-drivers) | Driver 595's `libGLX_nvidia.so.0` Vulkan ICD fails `vkCreateInstance` in a headless container (no X server). Rewrites the ICD JSON to `libEGL_nvidia.so.0` (NVIDIA's headless recommendation). No-op on 580 (GLX ICD works). |
| **Render-node GID auto-add** | `entrypoint.sh` (early, before gamescope) | Some hosts map the nvidia render node to a GID that's neither `render` nor `video` in the container (UpCloud = 993/`polkitd`) → `dpad` EACCES opening `/dev/dri/renderD128`. Detects the owning GID + `usermod -aG` dpad to it. Host-agnostic. |
| **GLVND-neutral `libglx.so` bake** | Dockerfile `base` stage | nvidia 610.x ships only `libglxserver_nvidia.so`; Mesa's `libglx.so` self-registers swrast for screen 0 first → GL falls to zink → `ximagesrc` can't capture → no stream (worst on cuda≥13.3 Blackwell). Bakes xserver-xorg-core's neutral `libglx.so` into the nvidia ModulePath + entrypoint hides Mesa's on the nvidia-DDX path. |
| **NVENC #1249 flexgrip interposer** | `scripts/nvenc_fix.c` → `libnvenc_fix.so`, wired in `setup_nvenc_fix()` | Driver 570–609: NVENC peer-inits with unmounted host GPUs → `NvEncOpenEncodeSessionEx error 2`. The interposer filters `GET_ATTACHED_IDS` to mounted GPUs (full-PCI-address match, lowercased — slots with hex letters B/D/F…). Auto-enabled on 570..609 when host GPU count > mounted. Single-GPU hosts immune on any driver. |
| **Gamepad 6-layer chain** | Dockerfile + `entrypoint.sh` `start_gamescope_session` | (1) interposer wired into the gamescope path; (2) `SDL_JOYSTICK_LINUX_CLASSIC=1` + `SDL_JOYSTICK_DEVICE=/dev/input/js0`; (3) root watcher mknods `/dev/input/jsN` on socket appear; (4) `SDL_JOYSTICK_DISABLE_UDEV=1` (ENUMERATION_FALLBACK hotplug); (5) `JSIOCGNAME` returns name length (source patch); (6) **both x86_64 AND i386 `.so` rebuilt** (`gcc-multilib`/`libc6-dev-i386`, fail loud — Steam's main binary is 32-bit). |
| **Targeted chown (no blanket `chown -R`)** | `entrypoint.sh` | A blanket `chown -R dpad:dpad /home/dpad` copy-ups all ~33k pre-baked files on overlayfs (no `metacopy`) → ~119s wasted. Use `find <dir> ! \( -user dpad -group dpad \) -exec chown dpad:dpad {} +` (skips already-owned). Cold boot 172s → 50s. **Never reintroduce `chown -R` over a large pre-baked dir.** |
| **Cursor: `--enable_cursors=true` + pointer-lock gate** | entrypoint + `patch_gst_web_cursors.sh` | gamescope headless doesn't composite the X cursor → the XFIXES CSS overlay is the only visible cursor; the web client's auto pointer-lock hides it. Fix: `--enable_cursors=true` (safe after the `dpad_input_patch.py` xfixes crash fix) + a `window.DPAD_POINTER_LOCK` gate in `/opt/gst-web/input.js` (default false → absolute mouse). FPS relative mouse: browser console `window.DPAD_POINTER_LOCK = true` + click. |
| **`unattended-upgrades` disabled (protects live sessions)** | `vm-bootstrap.sh` `ensure_no_auto_updates()` (runs FIRST) | Ubuntu's `apt-daily-upgrade.timer` ran `unattended-upgrades` mid-session, upgrading the kernel + libc6 + openssh; `needrestart` then issued `systemctl daemon-reexec` + restarted containerd/docker → every game container died exit 137 ~2 min after `DPAD_READY` (observed live 2026-07-30). Masks the apt timers + zeros `APT::Periodic::*` + sets `needrestart` to restart-mode=list (no auto-restart). |
| **CAP-PROBE corrected + FATAL verify** | `vm-bootstrap.sh` `ensure_docker_xfs_quota()` | The old `dd ... \| tail -3` dropped the `No space left on device` line (dd prints it BEFORE its summary) + `$?` was `tail`'s → a working cap falsely reported "NOT enforced." Now captures dd's full output + real exit; the verify is FATAL (`return 1`) so an uncapped ephemeral VM never ships. Also the docker drop-in `RequiresMountsFor` moved to `[Unit]` (was wrongly `[Service]`, ignored) + idempotency hardened (img + fstab entry) vs the daemon-reexec `findmnt` race. |
| **oversub cuInit forward-compat skip** | `entrypoint.sh` `configure_cuda()` | The forward-compat `cuInit(0)` test (loads the image's OLD compat `libcuda.so.555` against the newer 580 driver) **deadlocks under a 2nd concurrent MPS client** (`skb_wait_for_more_packet` on the MPS control socket) → the 2nd oversub session's boot stalled 7+ min, exceeding the launch deadline. Forward-compat is only needed when the IMAGE's CUDA is NEWER than the host max CUDA; now the test runs only then (`dpkg --compare-versions`) + is `timeout 20`-guarded. For our images (12.5/12.8 ≤ host 13.0) it's skipped → always the fast fallback path (slot-0 proved the fallback works). |
| **entrypoint bind-mount hotfix path** | `dpad-launch-session` + `vm-bootstrap.sh` `ensure_image()` | `dpad-launch-session` bind-mounts the host's `/opt/dpadcloud/entrypoint.sh` over the image's baked entrypoint (if present); `vm-bootstrap` fetches it fresh from repo `main` at bootstrap. Lets entrypoint hotfixes go live **WITHOUT an image rebuild + Docker Hub push** (the owner step that's blocked) — validated live (the cuInit fix shipped this way on the 2nd oversub session). Falls back to the baked entrypoint if the fetch/host file is absent. |

## 5. Known limitations (accepted, don't chase)

- **Mild Steam-menu flicker on driver 580** (gamescope #1964) — menu/overlay
  transitions. Accepted (same on the Vast 3060/580 baseline). The fix is a host
  driver downgrade to 575 (not image-fixable). See
  `cloud/docs/DEPLOY-RUNBOOK.md`. **Severe whole-frame flicker on driver
  595** is a different bug — the host must downgrade 595 → R580 LTS (see §6 #1).
- **Browser refresh occasionally "Waiting for stream"** — a Selkies 1.6.2
  WebRTC reconnect race. Self-heals on a 2nd refresh; a fresh incognito tab
  always works. A restart-on-disconnect supervisor would make it 100% (deferred).
- **Steam "no internet" icon + ~70s CM bounce** — Steam's CM servers bounce the
  datacenter IP. Login/install/play all work; cosmetic, not fixable from the image.
- **NVRTC "invalid value for --gpu-architecture" on Blackwell** — the bundled
  GStreamer ships a CUDA 11.4 `libnvrtc` that can't JIT for sm_120; the plugin
  falls back to a pre-compiled cubin. Non-fatal.
- **`webrtcnice … failed to resolve "<uuid>.local"`** — Chrome's mDNS `.local`
  ICE candidates the container can't resolve; the TURN relay handles it.

## 6. Open image-side items

1. **`vm-bootstrap` driver 595 → 580 auto-downgrade — DONE + validated live
   2026-07-30.** `ensure_driver_580` detected `595.58.03` on a fresh UpCloud
   AI/ML template → removed the pinning package → installed
   `nvidia-driver-580-open` → rebooted → the oneshot resumed with
   `580.173.02` (`nvidia-smi` confirmed). The full downgrade+reboot+resume path
   ran on a real v2 launch. (Was: REQUIRED for UpCloud L4 + MassedCompute L40S
   flicker-free streams — the AI/ML template + image 184 ship 595 → severe
   whole-frame flicker; see `cloud/docs/DEPLOY-RUNBOOK.md` §1.)
2. **Push `:dpad-SteamOS-L4` to Docker Hub** (owner step — the build box isn't
   logged in). The public tag is the stale 3.16.19 image; warm-pool/`docker
   pull` gets the wrong one. After pushing, re-enable the `dpadcloud-bootstrap`
   oneshot on the L4 box.
3. **`dpad-launch-session` ephemeral (`volumeId=none`) live validation** — the
   v2 ephemeral path (no `-v` bind, no `DPAD_VOLUME_MOUNT`). The script change
   is on `main`; validate on the first MassedCompute launch.
4. **`--storage-opt size=<N>g` ephemeral disk cap — DONE + validated live
   2026-07-30.** `vm-bootstrap.sh` `ensure_docker_xfs_quota()` moves `/var/lib/docker`
   onto an XFS-`pquota` loopback on the boot disk (`ftype=1` + `reflink=0`) +
   disables the containerd image store → legacy `overlay2`, which enforces
   `--storage-opt size`. `dpad-launch-session` caps ephemeral via
   `--storage-opt size=$DPAD_EPHEMERAL_DISK_GB` (cloud worker writes `=200`).
   Validated: a fresh Helsinki → Casual → no-storage container got
   `StorageOpt=map[size:200g]`, `df /` = `200G`, and Steam → Settings → Storage
   showed **200 GB / 198.23 GB free**. The CAP-PROBE is corrected + FATAL
   (see §4). (Was: plumbed but dormant; needed XFS pquota on the VM Docker store.)
5. **Steam-login persistence on the per-user volume** (the linchpin of the v2
   "your cloud PC" UX) — encrypted `config.vdf` + `loginusers.vdf` on the
   volume; the container decrypts + injects on boot → silent Steam auto-login.
   First launch: one-time Steam login + Steam Guard. `cloud/docs/V2-PLAN.md` §5.
6. **`dpad-launch-session` live validation** (v2 worker side) — the SSH launch
   + volume mount + per-slot coturn + the `DPAD_READY` readiness marker (the
   worker currently uses a `docker ps` count heuristic).
7. **(optional) restart-on-disconnect supervisor** for 100%-consistent refresh.
8. **(optional) NVRTC soname-11 real fix** (make CUDA 12.8 libnvrtc win).

## 7. Deprecated (Vast era — in git history only)

- `:dpad-heroic` / `:dpad-heroic-rtx50` (Vast Docker, no userns → Heroic
  storefront via the `umu_run.py` → Proton-direct bypass).
- The headless `steamcmd` + `dpad-launch` path (Proton-direct, single-player,
  no Steam UI).
- `bubbleroot` (proot-based bwrap shim) — dead-end (CEF crashes under ptrace).
- The DFP Xorg / `--connected-monitor=DFP-0` single-user path (nvidia-modeset
  singleton → 1 full-Steam per VM). Superseded by gamescope headless N-on-N.
- `mws` / Sunshine / Tailscale / native-Moonlight — removed; Selkies is the
  only browser stream.
- The `ximagesrc` `:2` Xvfb bridge — replaced by `pipewiresrc` direct capture
  (`DPAD_VIDEO_SRC=ximagesrc` keeps it as a fallback).

## 8. Cross-references

- `IMAGE-RUNBOOK.md` — the launch recipe (`vm-bootstrap.sh` one-command + the
  manual `docker run` with the flag table) + the env-var reference + boot
  milestones + troubleshooting. The operational runbook.
- `cloud/docs/STATUS.md` — the control-plane handoff (v2 flow, the 3 live
  provider adapters, the open control-plane items).
- `cloud/docs/V2-PLAN.md` — the post-Vast architecture (regions, tiers,
  volumes, on-demand N-to-N, billing).
- `cloud/docs/DEPLOY-RUNBOOK.md` — the driver-per-pool recommendations
  (R580 LTS for the L4) + the regression registry.

## 9. Resume

```bash
cd dpadplay/container-gaming && git pull
docker build --target vast-vm -t forcespt/dpadcloud-gaming:dpad-SteamOS .
# Then read §6 — the driver-595→580 downgrade + the Docker Hub push are the
# two owner steps blocking flicker-free v2 streams.
```