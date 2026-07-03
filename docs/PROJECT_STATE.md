# DpadCloud Container Gaming — Project State & Continuation Guide

> **UPDATE 2026-07-01 — Ubuntu 24.04 move (mws primary browser path).** The base is
> now `nvidia/cuda:12.5.1-runtime-ubuntu24.04` (single tag `ubuntu24.04`). Two
> things drove this:
> 1. **moonlight-web-stream (mws) added as the PRIMARY browser path.** mws is a
>    Moonlight client that bridges Sunshine's `h264_nvenc` stream to a browser
>    over WebRTC. The prebuilt mws binary requires glibc 2.39 (= noble), so 24.04
>    makes it a 3-line tarball install — no from-source Rust build, no patchelf.
>    This gives the **browser hardware NVENC on ALL drivers** (Selkies'
>    `nvh264enc` falls back to `x264enc` on driver ≥570 / NVENC 13; mws sidesteps
>    that via Sunshine's FFmpeg `h264_nvenc`). Selkies is **kept as a fallback**.
> 2. **The wide Vast pool is preserved.** CUDA 12.5.1 runs on any driver ≥525 via
>    CUDA minor-version compatibility (whole 12.x family shares the R525 baseline).
>    The old PROJECT_STATE claim that 12.5.1 "forces driver ≥555" was wrong — it
>    confused the *bundled* driver with the *minimum required* (525.60.13). Keep
>    the offer filter at `cuda_max_good>=12.1` (includes 535/545/550 hosts).
>
> Remaining validation: a real Vast boot to confirm the mws↔Sunshine **auto-pair**
> (`scripts/mws-autopair`, now implemented) completes end-to-end and the browser
> streams, plus noble t64 apt names (may need one fix iteration).
>
> **Purpose:** This document captures everything a new AI session needs to continue
> the DpadCloud cloud-gaming container project. It documents what's built, what works,
> what doesn't, and the next steps (VirtualGL + gamescope).

---

## 🔖 CURRENT STATUS & BLOCKER (2026-07-02) — read this first

**Where we are (focus = Selkies browser path; Sunshine/mws parked):** Ubuntu
24.04 / CUDA 12.5.1 image is built, boots on Vast. **Selkies hardware NVENC now
works on BOTH driver classes** — RTX 3060/driver-580 and RTX 3090/driver-595 —
via the corrected encoder probe (see "Selkies encoder probe fix" below). The
browser/Selkies path is the primary path. Sunshine + mws remain installed and
auto-pair, but the mws browser-stream path is **parked** behind the
`/dev/uinput` blocker (see below): `/dev/uinput` is unreachable on Vast (cgroup
v2 device controller is BPF-based, deny-wins, can't be relaxed from inside an
unprivileged container; Vast allows neither `--privileged` nor `--device`), and
Sunshine (current `inputtino`-only builds — legacy XTest input was removed in
PR #2606) needs `/dev/uinput` for input. mws *video* likely still streams
(Sunshine warns-and-continues on uinput failure rather than segfaulting, per
upstream issues #4354/#3569), but input is the gap. Resolving mws input = a
from-source Sunshine build with legacy XTest restored
(`lunarlattice0/Sunshine-RestoreLegacyInput`); not pursued while Selkies works.

### Selkies encoder probe fix (2026-07-02) — "software encoder on some VMs" was a probe bug
The entrypoint encoder probe was testing the **literal** `nvh264enc` element.
On GStreamer 1.24.x that is the **legacy** nvcodec element using the OLD NVENC
preset GUIDs that NVIDIA **removed in driver 590+** → `Selected preset not
supported` on e.g. RTX 3090/driver-595 → false-negative → `x264enc` fallback.
But Selkies' `gstwebrtc_app.py` does NOT instantiate the literal name: on
GStreamer 1.21–1.24 it maps `--encoder=nvh264enc` → **`nvcudah264enc`** (the
modern P1–P7 + `NV_ENC_TUNING_INFO` element), which works on driver 595. The
probe now tests the element Selkies **actually instantiates**
(`nvcudah264enc` on 1.21–1.24, `nvh264enc` otherwise) via
`videoconvert ! cudaupload ! cudaconvert ! <enc>`, captures the real GStreamer
error on failure, and selects/reports the Selkies-facing name `nvh264enc`
(which Selkies re-maps). Result: `nvh264enc` (hardware) on both 3060/580 and
3090/595. **No GStreamer 1.26 build needed; no Selkies patch.** Confirmed on
Vast: `gst nvh264enc: OK (via videoconvert ! cudaupload ! cudaconvert →
nvcudah264enc)` / `Selected encoder: nvh264enc` on both hosts.

### ✅ Validated working (on Vast, built image `forcespt/dpadcloud-gaming:ubuntu24.04` / `:SteamUbuntu24.04`)
- **NVENC on all topologies** via the flexgrip interposer + a PCI-bus→minor mask:
  - single-GPU (4060 Ti / 3090): native `h264_nvenc` ✅
  - multi-GPU slice (2 /proc, 1 mounted, driver 580/595): flexgrip filters → `h264_nvenc` ✅
  - **5-GPU mining rig** (5 /proc, 5 mounted, only 1 nvidia-smi-visible at minor 2): the
    `NVENC_FIX_AVAILABLE` mask (computed from `nvidia-smi --query-gpu=pci.bus_id` → /proc
    Device Minor, with an `index→minor` fallback) correctly kept minor 2 → Sunshine found
    `h264_nvenc` + `hevc_nvenc` + `av1_nvenc` ✅ (the PCI-bus mapping was essential — the
    assigned GPU was NOT at minor 0; the naive index=minor assumption would have failed)
  - driver 580 (RTX 3060) AND driver 595 (RTX 3090): Selkies `nvh264enc` (hardware) —
    Selkies maps it to `nvcudah264enc` (modern nvcodec, works on driver 590+); the entrypoint
    probe now tests that element. Sunshine `h264_nvenc` also works (FFmpeg). See "Selkies
    encoder probe fix" above.
- **Auto-pairing** (`scripts/mws-autopair`): logs in to mws (creates admin `dpad`), adds the
  `localhost` host, calls mws `POST /api/pair` (NDJSON pin via `curl -N` — no-buffer was the
  key fix), submits the pin to Sunshine `POST /api/pin`, → `SUCCESS`. End user opens the mws
  URL → host already paired → no PIN shown.
- **mws runs** on `0.0.0.0:8080`; **Selkies streams** (browser video confirmed via Selkies on
  a 4060 Ti). VirtualGL renders on the GPU. PulseAudio null-sink, coturn TURN (TCP),
  cloudflared (two quick tunnels), all up.
- **Resource limits**: entrypoint raises `ulimit -u/-n`; hosts with a hard `nproc=50` need
  `--ulimit nproc=1048576:1048576` in the Docker options (the in-image raise can't exceed a
  hard cap). `nofile` hard cap is often 1024 → needs `--ulimit nofile=1048576:1048576`.

### ❌ The ONE blocker: `/dev/uinput` EPERM → Sunshine segfault → mws stream fails

**Vast strips `--cap-add SYS_ADMIN` (confirmed):** the container's bounding set is
exactly Docker's 14 default caps — `!cap_sys_admin`. So we **cannot become DRM
master**, which means the DFP/virtual-monitor Xorg path (`--connected-monitor=DFP`, the
Steam-Headless approach) fails with `Failed to acquire modesetting permission` even
on hosts where `nvidia_drm.modeset=Y`. **Workaround = NULL-mode Xorg**
(`UseDisplayDevice=None`, `ConnectedMonitor=None`): the nvidia DDX runs WITHOUT
KMS, so Xorg comes up and GL/Vulkan render on the GPU with no DRM master needed.
Capture is via `XGetImage` on the root window (backing store enabled). **Open:
Vulkan present (→ DXVK/Proton) on a NULL-mode Xorg** — present goes through the DDX
Present path (no KMS), to be validated. If it works → Windows/Proton games on Vast
without caps. If not → Windows games need a host that grants `--privileged`/caps
(not Vast today); Linux GL games work via `vgl-steam` regardless.

**Workaround for Steam + Proton on Vast = bubbleroot** (`scripts/bubbleroot`, vendored from codeberg.org/valpackett/bubbleroot): a proot-based drop-in `bwrap` that emulates bind-mount/chroot via ptrace — needs NO userns / NO CAP_SYS_ADMIN / NO setuid. The entrypoint auto-enables it when `unshare -U` fails (`DPAD_BUBBLEROOT=auto`), symlinks `/usr/local/bin/bwrap` -> it, and exports `BWRAP`+`PRESSURE_VESSEL_BWRAP` so Steam's runtime-tools/pressure-vessel use it instead of their bundled bwrap. GPU/Vulkan/DXVK render natively (NOT emulated); only filesystem/path syscalls are intercepted, so there is some loading-I/O overhead. PENDING validation on Vast: does the Steam client open + a Proton game launch under bubbleroot?

**VALIDATED 2026-07-02 (bubbleroot result):** bubbleroot DOES get Steam +
pressure-vessel running on Vast without userns (proot mounts the whole Steam
Linux Runtime, BWRAP/PRESSURE_VESSEL_BWRAP -> /opt/dpadcloud/bubbleroot, Steam
downloads its 493MB update and relaunches, the main steam process + pv-adverb +
proot are all alive). BUT the **Steam UI (CEF/Chromium webhelper) crash-loops
under proot's ptrace** (startcount=45 relaunches; only tiny 64x24/10x10
placeholder X windows appear, never the real UI). CEF under ptrace is a
closed-source-Chromium wall with no reliable in-container fix (linuxserver gave
up on the same). => **Vast cannot host the interactive Steam UI / Proton.**
`-no-cef-sandbox`, `STEAM_FORCE_NO_GPU=1`, `PROOT_NO_SECCOMP=1` did not help.

**`STEAM_RUNTIME=0` does NOT help** (tested): Steam's webhelper/CEF is
hardcoded into the sniper/steamrt3c pressure-vessel container since Valve's 2024
UI-containerization, so `STEAM_RUNTIME=0` only disables the *game* runtime, not
the UI's. The webhelper still goes through pressure-vessel -> bubbleroot/proot
-> CEF crash (startcount=102). No in-image path to the interactive Steam UI on
Vast exists.

**REVISED DECISION — the Vast product path is HEADLESS (no Steam UI), via
`steamcmd` + Proton-direct.** The interactive Steam UI needs pressure-vessel
(userns) -> not available on Vast. But Valve's official **`steamcmd`** is a
console client that does NOT use CEF/pressure-vessel -> runs on Vast. And
**Proton can run WITHOUT pressure-vessel** (with system libs; pressure-vessel is
only for library consistency, not required on modern Ubuntu 24.04 / glibc 2.39).

VALIDATED 2026-07-02 (steamcmd on Vast, RTX 3060): `steamcmd +login anonymous
+quit` starts, loads Steam API, connects to Steam — NO userns / pressure-vessel
error. => the headless path is viable on Vast.

VALIDATED 2026-07-03 (steamcmd REAL login + native game launch on Vast, RTX
3060/driver-580, image `forcespt/dpadcloud-gaming:ubuntu24.04`): `dpad-launch
599390` (Battle for Wesnoth, free native-Linux) — steamcmd logged in with a
real account (Steam Guard code `set_steam_guard_code` round-trip on first
login; cached credentials => silent re-login after), downloaded the game
(`+force_install_dir /home/dpad/games +app_update 599390 validate`), and the
game window rendered on the NULL-mode Xorg `:0` AND **Selkies streamed it in
the browser**. NO pressure-vessel / NO userns / NO Steam UI. This clears the
headless native-game path end-to-end. The `app_launch` scout-runtime approach
(needs `reaper` + `steam-launch-wrapper`) was NOT needed — running the game's
raw Linux binary directly with a glibc-safe compat-libs dir works and is
simpler. See the `dpad-launch` notes below for the exact recipe.

**Headless architecture (Vast):**
- `steamcmd +login <user> +app_update <appid> validate +quit` downloads a game
  (login caches a token after first Steam-Guard auth).
- **Native Linux games**: `steamcmd -globaluser +login <user> +app_launch <appid>`
  launches them via the old scout runtime (LD_LIBRARY_PATH, NOT pressure-vessel)
  -> NO userns needed. (Ref: Rosentti/steamcmd-gaming — native games work;
  needs `reaper` + `steam-launch-wrapper` copied from the Steam install into
  steamcmd's linux32 dir.) Caveats: no Steam overlay/achievements/cloud/VAC.
- **Windows games**: launch the game .exe via Proton DIRECTLY (no pressure-vessel)
  with env vars (`STEAM_COMPAT_DATA_PATH`, `STEAM_COMPAT_CLIENT_INSTALL_PATH`,
  `PROTONPATH` -> `proton waitforexitandrun game.exe`). DXVK uses Vulkan present
  on the NULL-mode Xorg (proven by vkcube). Tools: `proton-cli`/`proton-run`
  (explicitly support running WITHOUT the Steam runtime).
  **VALIDATED 2026-07-03**: War of Dots (3902430, Windows-only, free) downloaded
  via steamcmd and launched via `dpad-launch` -> GE-Proton11-1 Proton-direct.
  Proton created the prefix, protonfixes passed, `fsync: up and running`, and
  the game ran on the GPU (DXVK via the Xorg Vulkan present surface) — NO Steam
  UI, NO pressure-vessel, NO userns. See the dpad-launch PATH B notes.
- The **website** lists the user's Steam library (Steam Web API); the user clicks
  a game; the **orchestrator** launches it on the headless GPU container
  (native -> app_launch; Windows -> Proton-direct); **Selkies streams the game**.
  No in-container Steam UI. This is the Games-on-Whales / linuxserver
  `steam://rungameid` / `umu-run --config game.toml` direct-launch pattern,
  minus the userns-dependent parts.

**PENDING validation (resume here):**
1. ✅ DONE (2026-07-03) — steamcmd real login + download + native-Linux game
   launch + Selkies stream. Validated with Battle for Wesnoth (599390) via
   `dpad-launch`. See VALIDATED block above.
2. ✅ DONE (2026-07-03) — Windows game via Proton-direct. Validated with War of
   Dots (3902430) via `dpad-launch` -> GE-Proton11-1 Proton-direct (prefix
   created, fsync up, game ran on GPU, no userns/pressure-vessel). See the
   Windows-games note above. Remaining polish: steamcmd segfaults on large
   downloads (~2GB+) -> add retry-until-`fully installed` loop in dpad-launch;
   the `steamrt4_platform_*` misdetection fix is already committed.
3. ✅ DONE (2026-07-03) — `steamcmd` + the `dpad-launch <appid>` wrapper are now
   baked into the Dockerfile (step 4b + `scripts/dpad-launch`), with both the
   native (PATH A) and Windows/Proton-direct (PATH B) paths. Remaining: build
   the orchestrator's Vast provider around `dpad-launch`.

**`DPAD_BUBBLEROOT` is now a dead-end for the Steam UI** (CEF crashes under
proot). Keep the code as opt-in (`DPAD_BUBBLEROOT=1`) for experimentation, but
default it OFF and do NOT rely on it. The headless steamcmd path replaces it.

**Userns-capable provider (RunPod/Lambda) remains an OPTION** for the full
interactive Steam UI + standard Proton (zero hacks), if a UI-in-browser
experience is later desired. The image is provider-agnostic. But the primary
Vast path is headless steamcmd + Proton-direct.

**VALIDATED 2026-07-02 (RTX 3060 / driver 580, unprivileged Vast):** `vkcube
--gpu_number 0` on the NULL-mode Xorg presents a Vulkan cube to an X window AND
Selkies captures it → Vulkan present + ximagesrc capture both work WITHOUT
CAP_SYS_ADMIN / DRM master. ⇒ DXVK/Proton (Windows games) ARE supported on
Vast's unprivileged sandbox. Full cloud-gaming stack now works end-to-end:
Steam (installed + autostarts, GPU-rendered) + native Linux GL + Windows/Proton
via DXVK, streamed to the browser by Selkies with hardware NVENC, gamepad via
Selkies' XTest interposer (no /dev/uinput).

When the user clicks Play in the mws tab, mws's streamer does the RTSP handshake to
Sunshine; Sunshine starts the session and tries to create virtual keyboard/mouse/touch
via `/dev/uinput` → **`Unable to create virtual touch screen: Operation not permitted`**
→ Sunshine **segfaults** → mws `RTSP ANNOUNCE failed: -1` → mws stops the stream → the
browser's `WebRTC negotiation timed out after 15000ms` (downstream symptom; WebRTC
itself is fine, mws just gave up). Confirmed via `tail /tmp/mws.log` + `/tmp/sunshine.log`.

Root cause: `/dev/uinput` access is denied by the **device cgroup**. The entrypoint does
`mknod /dev/uinput c 10 223` + `chmod 666`, so the node exists (`crw-rw-rw- root root`),
but `open('/dev/uinput', O_WRONLY)` returns **EPERM (errno 1)** — the cgroup allowlist
blocks it; `mknod` can't bypass the cgroup. `--device /dev/uinput` in the Vast Docker
options did **not** fix it (Vast appears to strip `--device`, or the host's uinput isn't
reachable that way) — the open test still EPERM after adding it.

### ▶ NEXT STEP (the only thing left to try before mws video works)

Try **`--privileged`** in the Vast Docker options — it allows the cgroup to access the
char device the entrypoint already `mknod`'d (and grants caps). If Vast honors
`--privileged`, `open('/dev/uinput')` should succeed → Sunshine creates the virtual
devices → no segfault → mws RTSP succeeds → mws WebRTC connects → browser video + input.

Full recommended launch options (replace `<pass>`):
```
--privileged --ulimit nproc=1048576:1048576 --ulimit nofile=1048576:1048576 -p 73478:73478 -e SUNSHINE_PASSWORD=<pass> -e SELKIES_BASIC_AUTH_USER=dpad -e SELKIES_BASIC_AUTH_PASSWORD=<pass>
```
(`--device /dev/uinput` can be added too as belt-and-suspenders, but it didn't work
alone on Vast — `--privileged` is the lever.)

**If `--privileged` still shows EPERM on `open('/dev/uinput')`**, the host kernel's uinput
module isn't available. Then the fallbacks (in order):
1. Run **Sunshine as root** (entrypoint change: drop `as_user` for the Sunshine launch,
   set `HOME=/home/dpad` so it reads the config) + `--cap-add SYS_ADMIN` — in case uinput
   `UI_DEV_CREATE` needs a capability (we believe it only needs write access, but root+cap
   covers it).
2. If uinput is truly unavailable on the host, input injection can't use uinput; investigate
   whether Sunshine can be made to not crash on the touch/pen failure (it currently segfaults),
   or use a different input path. (Low probability — most Vast hosts have uinput; `--privileged`
   should expose it via the mknod'd node.)

### 🛠️ Build + test loop
```bash
cd dpadcloud/container-gaming
docker build -t forcespt/dpadcloud-gaming:ubuntu24.04 .   # build (CUDA 12.5.1/12-5)
# RTX 50/Blackwell variant: --build-arg CUDA_VERSION=12.8.1 --build-arg CUDA_PKG=12-8 -t ...:ubuntu24.04-rtx50
# Vast offer filter: compute_cap>=750 cuda_max_good>=12.1 gpu_display_active=false rentable=true verified=true
# Launch with the options above. Read the Vast Logs tab for:
#   [*] Resource limits: nproc=… nofile=… cgroup_pids.max=…
#   --- NVENC topology (#1249 check) ---  (driver_major, host/mounted/visible counts, mask)
#   DPAD_NVENC_FIX: ENABLED/DISABLED
#   [mws-autopair] SUCCESS — mws is paired with Sunshine
#   mws running on 0.0.0.0:8080
# Then open the mws tunnel URL → log in (dpad/<pass>) → click localhost host → Desktop.
# Verify uinput: python3 -c "import os; f=os.open('/dev/uinput', os.O_WRONLY); print('OPEN OK'); os.close(f)"
# Verify Sunshine encoder: grep -i 'Found H.264 encoder' /tmp/sunshine.log
# Verify mws streamer: tail -n 150 /tmp/mws.log  (look for RTSP ANNOUNCE + webrtc peer state)
```

### Fixes already in the image (don't redo these)
- `Dockerfile`: Ubuntu 24.04 / CUDA 12.5.1 base; noble t64 apt renames (libasound2t64, libssl3t64,
  libgtk-3-0t64 — but libpulse0/libva2/libvdpau1/libwayland-egl1/libjack-jackd2-0 keep plain
  names); Sunshine `sunshine-ubuntu-24.04-amd64.deb`; Selkies 24.04 tarball; mws v2.10
  prebuilt; `PIP_BREAK_SYSTEM_PACKAGES=1`; `libglu1-mesa` pre-installed for VirtualGL;
  `nvenc_fix.c` built → `/opt/dpadcloud/libnvenc_fix.so`; `.gitattributes` enforces LF.
  **Step 4b (2026-07-03):** enables multiverse+universe on noble's deb822 sources,
  preseeds the Steam License (`steam steam/question select "I AGREE"` +
  `steam steam/license note ''` via `debconf-set-selections` — otherwise the
  steamcmd preinst DECLINES the license and the build fails), and installs
  `steamcmd` + `libsdl2-mixer-2.0-0` + `libsdl2-image-2.0-0` (system SDL2
  add-ons so native games load SDL2 from the system instead of the sniper
  runtime's codec cascade).
- `entrypoint.sh`: raises `ulimit -u/-n` + prints cgroup pids; `nvidia-smi`-visible GPU bitmask
  (`NVENC_FIX_AVAILABLE`, PCI-bus→minor + index fallback) + broadened flexgrip enable
  (`host>mounted OR visible<mounted` on driver 570..609); `mknod /dev/uinput` + `chmod 666`;
  mws launch with `DISABLE_DEFAULT_WEBRTC_ICE_SERVERS=true WEBRTC_NETWORK_TYPES=udp4,tcp4
  WEBRTC_ICE_SERVER_0_*=coturn`; `scripts/mws-autopair` backgrounded after mws up; two
  cloudflared tunnels (mws + Selkies); health loop uses port checks not pgrep paths.
- `scripts/nvenc_fix.c`: `NVENC_FIX_AVAILABLE` env override in `get_available_devices()`.
- `scripts/mws-autopair`: full auto-pair (login→add host→pair→submit pin to Sunshine→confirm).
- `scripts/dpad-launch` (2026-07-03, VALIDATED): headless Steam game launcher — the Vast
  product path. `dpad-launch <appid>` runs steamcmd (`+force_install_dir
  /home/dpad/games +login $STEAM_USER +app_update <appid> validate`), fixes the
  steamcmd SDK symlinks (`~/.steam/sdk32/sdk64`), then runs the game's NATIVE
  Linux binary DIRECTLY (no pressure-vessel / no userns). The key trick: native
  games ship bundled with the Steam Linux Runtime (sniper) platform whose libs
  are version-pinned (ICU 67 vs system 74, OpenSSL 1.1 vs system 3.x). The
  wrapper builds a clean `compat-libs/` dir by iteratively symlinking ONLY the
  libs missing from the system (via `ldd ... | grep "not found"`) from the
  sniper platform's `files/lib/x86_64-linux-gnu` (+ its `pulseaudio/` subdir for
  `libpulsecommon-XX.so`), to a fixed point — **NEVER the glibc family**
  (`libc.so.6`/`libm.so.6`/`libpthread.so.0`/…; loading the sniper's older glibc
  breaks every system binary with missing `GLIBC_2.3x` symbols — hit during
  testing). `ldconfig -n $SNIPER_LIB` creates the SONAME symlinks first. Launch
  uses `DISPLAY=:0 LD_LIBRARY_PATH=compat-libs <binary>` set INLINE (not
  exported) so the surrounding shell keeps the system glibc. Env: `STEAM_USER`
  (required), `DPAD_GAME_BINARY` (override auto-detect), `DPAD_GAME_ARGS`,
  `DPAD_INSTALL_DIR`. First login on a fresh machine prompts for password +
  Steam Guard code (one-time; token caches in `~/.steam` => silent after).
  Validated with Battle for Wesnoth (599390): game window renders on the
  NULL-mode Xorg `:0` + Selkies streams it in the browser.
  **Steam credential persistence for the product (DEFERRED):** instances are
  ephemeral so the cached token (`~/.steam/config/config.vdf` +
  `loginusers.vdf`) is lost on destroy. The orchestrator will store an encrypted
  blob (per user, from a one-time "Link Steam" flow) and inject it into each
  new instance so `steamcmd +login` is silent from boot — no Steam Guard
  round-trip per session. Refresh tokens expire after ~30d inactivity but each
  login refreshes the window; re-auth flow handles expiry.

### Known host-class notes
- **nproc=50 hosts** (some RTX 3090/driver-595 instances): hard cap → MUST pass
  `--ulimit nproc=1048576:1048576` or the whole stack hangs at PulseAudio (EAGAIN on every
  thread). The entrypoint's `ulimit -Hu` can't exceed the hard cap; only the docker option can.
- `NVIDIA_VISIBLE_DEVICES=void` (Vast sets this): mounts extra `/dev/nvidiaX` for GPUs the
  container can't use → that's exactly the `visible<mounted` case the mask fix handles.
- `/dev/uinput`: see the blocker above.

---

## What This Project Is

A **lean (~8 GB) headless cloud-gaming container** that runs on Vast.ai GPU hosts.
It streams a virtual desktop + games to a browser via **moonlight-web-stream
(Sunshine NVENC → WebRTC)** or **Selkies-GStreamer** (fallback), or to a native
client via **Moonlight (Sunshine)**. Built on `nvidia/cuda:12.5.1-runtime-ubuntu24.04`.
The container is designed for per-session provisioning by a Fastify orchestrator
(in `apps/api`).

## Architecture (Ubuntu 24.04 + mws primary browser path)

```
User Browser ──(HTTPS)──▶ cloudflared tunnel ─┬─▶ mws (0.0.0.0:8080)      [PRIMARY: Sunshine h264_nvenc]
                                               │      │
                                               │      └─ WebRTC ──▶ Sunshine (localhost:47989)
                                               │                        │
                                               └─▶ Selkies (127.0.0.1:16100) [FALLBACK: NVENC or x264]
                                                        │
                                         ┌──────────────┴─────────────┐
                                         ▼                            ▼
                                    Xvfb display               coturn TURN
                                   (Mesa EGL)                (TCP 73478)
                                         │                            │
                                    PulseAudio          (shared WebRTC relay for
                                   (null-sink)          both mws + Selkies)
                                         │
                              ┌──────────┼──────────┐
                              ▼          ▼          ▼
                           XFCE       Steam      Sunshine (NVENC host)
                         desktop     (Proton)   ├── mws (browser, all drivers)
                                                  └── Tailscale ──▶ Native Moonlight client

NVENC encoder: Sunshine = h264_nvenc (FFmpeg) on all drivers (with flexgrip on
multi-GPU driver 570..609). Selkies = nvh264enc on driver<570, x264enc fallback
on driver≥570 (GStreamer 1.24.6 vs NVENC-13 preset GUIDs). Browser NVENC on
driver≥570 is via mws+Sunshine, NOT Selkies.
```

## What Works (confirmed on Vast)

- ✅ **Base moved to Ubuntu 24.04 + CUDA 12.5.1** — wide pool preserved via CUDA minor-version compat (driver ≥525). noble t64 apt renames applied.
- ✅ **moonlight-web-stream (mws) integrated as PRIMARY browser path** — prebuilt binary runs natively on noble (glibc 2.39); reuses in-image coturn TURN; fronted by its own cloudflared tunnel. Browser NVENC via Sunshine `h264_nvenc` on ALL drivers (pending Vast validation of the mws↔Sunshine pairing + capture flow).
- ✅ **Browser click-and-play (fallback)**: Selkies WebRTC + cloudflared HTTPS tunnel → gamepad + audio + video in browser (Selkies 24.04 tarball)
- ✅ **Audio**: PulseAudio headless null-sink (dummy/dummy.monitor) — pulsesrc captures silence reliably
- ✅ **TURN relay**: In-image coturn on Vast identity port 73478 (TCP only) — shared by mws and Selkies — no Open Relay flakiness
- ✅ **Sunshine**: Running (native Moonlight host AND encoder for mws) — `sunshine-ubuntu-24.04-amd64.deb`
- ✅ **Tailscale**: Installed + entrypoint hook (gated by TAILSCALE_AUTH_KEY)
- ✅ **Selkies encoder auto-probe**: 1-frame gst-launch test mirroring Selkies' `gstwebrtc_app.py` element selection — tests `nvcudah264enc` on Gst 1.21–1.24 (the element Selkies actually instantiates for `--encoder=nvh264enc`), else `nvh264enc`, via `videoconvert ! cudaupload ! cudaconvert`; captures the real error on failure; selects the Selkies-facing name. → `nvh264enc` (hardware) on 3060/580 + 3090/595; `x264enc` only on genuine NVENC failure.
- ✅ **CUDA compat**: configure_cuda ported — cleans ldconfig, tries forward-compat (datacenter), falls back to minor-version compat
- ✅ **NVENC**: Works on RTX 3060 Ti, 3080 Ti (driver ~535), and any single-GPU host on any driver (`gpu_frac=1`). On multi-GPU hosts with only a slice assigned + driver 570/580, the flexgrip interposer is implemented (opt-in, pending Vast validation) to fix #1249; x264 fallback remains the safety net. See "NVENC: What We Know".
- ✅ **Boot diagnostics**: NVENC/CUDA diag prints driver, visible GPUs, lib presence, compute_mode, cuInit, cuCtxCreate
- ✅ **Periodic log dump**: selkies.log + sunshine.log + mws.log + pulse.log to stdout (Vast Logs tab) — no SSH needed
- ✅ **Headless steamcmd + `dpad-launch` (Vast product path — VALIDATED 2026-07-03)**: `steamcmd` is baked in (step 4b, multiverse + Steam-License debconf preseed) and `dpad-launch <appid>` downloads a game via steamcmd and runs it. **PATH A (native Linux)**: runs the binary directly with a glibc-safe `compat-libs` dir from the bundled Steam Linux Runtime (sniper) platform. **PATH B (Windows/Proton-direct)**: runs the Proton `proton` script directly (NO Steam UI, NO pressure-vessel, NO userns) with `PROTONPATH`/`STEAM_COMPAT_DATA_PATH`/`STEAM_COMPAT_CLIENT_INSTALL_PATH`; DXVK uses the Vulkan present surface on the NULL-mode Xorg. Proton tool selected by `DPAD_PROTON` (default GE-Proton11-1; Proton Experimental + Proton 11.0 downloadable per-session via authenticated steamcmd — anonymous can't pull Valve Proton tools). Confirmed on Vast (RTX 3060/driver-580): Battle for Wesnoth (599390, native) + War of Dots (3902430, Windows via GE-Proton11-1) download, launch, and **Selkies streams the game window**. Steam-Guard first-login round-trip works; cached token => silent re-login.

## What Doesn't Work Yet

- ✅ **Xorg + nvidia DDX (PRIMARY gaming path)**: `install-display-drivers` now extracts the X nvidia DDX driver (`nvidia_drv.so` + `libglx.so`) from the same `.run` into `/usr/lib/xorg/modules/nvidia/` (private `ModulePath` so it does NOT shadow the mesa `libglx.so` Xvfb needs), plus `nvidia-xconfig`. The entrypoint generates `/etc/X11/xorg.conf` (busid from `nvidia-smi`, `PrimaryGPU`/`AllowEmptyInitialConfiguration`/`UseDisplayDevice=None`/`ModeValidation` relaxation, `cvt` modeline, drops `--no-multigpu` on driver≥550) and starts `/usr/bin/Xorg :0` as root via `xserver-xorg-legacy`'s `Xwrapper.config`. This gives Vulkan a **present surface** → Steam + Proton/DXVK render on the GPU directly (no vglrun). Steam auto-starts on XFCE login (`Steam.desktop` autostart). Falls back to Xvfb+Mesa+VGL (debug, `DPAD_XORG=0`) if the nvidia DDX is missing or Xorg fails to start. **PENDING**: real Vast boot validation (does Xorg acquire `vt7` under Vast's unprivileged sandbox? Sunshine/Selkies capture against a real nvidia X screen? NVENC #1249 flexgrip still covers the Xorg path on multi-GPU slices?).
- ⏸ **VirtualGL**: Installed (3.1.4) and still used by the Xvfb debug path (`vgl-steam` wraps `vglrun` only when `DPAD_XORG=0`). NOT needed under Xorg+nvidia-DDX (the X screen is already GPU-backed). Launchers kept: `vgl-steam`, `proton-wined3d` (WineD3D for the Xvfb path), `vgl-test`.
- ✅ **gamescope: NO LONGER NEEDED for the present-surface problem.** The whole reason gamescope was deferred (DXVK/Proton need a Vulkan present surface on a headless host) is solved by the real Xorg+nvidia-DDX path. gamescope may still be useful later as a micro-compositor for Steam Big Picture / resolution scaling, but it is no longer a blocker for running Windows games.
- ✅ **NVENC on RTX 3060**: RESOLVED — confirmed working on RTX 3060/driver-580 (multi-GPU slice + flexgrip). The old "3060 NVENC broken" was the #1249 multi-GPU issue + the encoder-probe artifact (see above), not a 3060 defect. Orchestrator probe-and-select still wise.
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
│   ├── dpad-launch              # Headless Steam game launcher (steamcmd download + sniper compat-libs + native binary launch) — the Vast product path, VALIDATED
│   ├── mws-autopair             # mws↔Sunshine auto-pair at boot
│   ├── bubbleroot               # proot-based bwrap shim (dead-end for Steam UI; opt-in)
│   ├── vgl-steam proton-wined3d vgl-test   # VirtualGL launchers (Xvfb debug path)
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
4b. steamcmd + libsdl2-mixer-2.0-0 + libsdl2-image-2.0-0 (multiverse+universe enabled;
    Steam License preseeded via debconf — the headless launcher path)
5. Proton-GE (GE-Proton9-25, from GitHub releases)
6. Sunshine (sunshine-ubuntu-22.04-amd64.deb from GitHub)
7. Selkies-GStreamer (gstreamer GPL tarball v1.6.2 + python wheel + web app + joystick interposer)
8. cloudflared (static binary from GitHub)
9. Tailscale (install.sh)
9b. Vulkan loader + tools (diag only)
9c. VirtualGL 3.1.4 (GPU-accelerated GL into headless Xvfb)
9d. flexgrip nvenc_fix.c → /opt/dpadcloud/libnvenc_fix.so  (NVENC #1249 multi-GPU fix, opt-in at runtime)
10. pulseaudio pulseaudio-utils xsel (late apt install)
11. COPY configs/ + entrypoint.sh + healthcheck.sh + scripts/{vgl-steam,proton-wined3d,vgl-test,install-display-drivers,mws-autopair,bubbleroot,dpad-launch}
12. EXPOSE 16100/tcp 3478/tcp 47989/tcp 47990/tcp 41641/udp
13. ENTRYPOINT ["/opt/dpadcloud/entrypoint.sh"]
```

## Entrypoint Boot Order

```
1. NVIDIA check (nvidia-smi)
2. install-display-drivers — extract matched .run OpenGL/EGL/Vulkan libs (compute-only Vast hosts)
3. configure_cuda() — clean ldconfig, try forward-compat, select CUDA ${CUDA_VERSION}
4. D-Bus (system + session)
5. Display server — **Xorg + nvidia DDX** (default, `DPAD_XORG=1`): entrypoint runs `install-display-drivers` (which now also extracts `nvidia_drv.so` + `libglx.so` into `/usr/lib/xorg/modules/nvidia/` + `nvidia-xconfig`), generates `/etc/X11/xorg.conf` (nvidia-xconfig or shipped template) with the assigned GPU's PCI busid + `PrimaryGPU`/`AllowEmptyInitialConfiguration`/`UseDisplayDevice=None`, and starts `/usr/bin/Xorg :0` as root (Xwrapper). Falls back to **Xvfb + Mesa EGL** (debug, `DPAD_XORG=0`) if the nvidia DDX is missing or Xorg fails to start.
6. VirtualGL renderer check — Xorg: plain `glxinfo` (expect the real NVIDIA renderer); Xvfb: `vglrun glxinfo`. Steam autostart `Steam.desktop` written to `~/.config/autostart` (Exec=`/usr/bin/steam` in Xorg, `/opt/dpadcloud/vgl-steam` in Xvfb).
7. XFCE desktop (xfwm4, xfsettingsd, xfce4-panel, xfdesktop — as user) — Steam then autostarts on login.
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
| `DPAD_XORG` | `1` | Display server: `1` = real **Xorg + nvidia DDX** (gaming path — Vulkan present surface so DXVK/Proton render on GPU; Steam + Proton render directly, no vglrun). `0` = Xvfb + Mesa + VirtualGL (debug/fallback only — no Vulkan present, Windows games can't render). |
| `DPAD_AUTOSTART_STEAM` | `1` | `1` writes an XFCE autostart `Steam.desktop` so Steam launches on desktop login (Steam-Headless pattern); `0` boots a bare desktop for debugging the Xorg/DXVK path. |
| `STEAM_ARGS` | `-silent` | Args passed to the autostarted Steam (e.g. `-tenfoot` for Big Picture). |
| `DPAD_BUBBLEROOT` | `auto` | proot-based `bwrap` shim for Steam/Proton when user namespaces are unavailable (Vast). `auto` enables when `unshare -U` fails; `1` force on; `0` force off. Sets `BWRAP`+`PRESSURE_VESSEL_BWRAP` to `/opt/dpadcloud/bubbleroot` and symlinks `/usr/local/bin/bwrap`. GPU/Vulkan render natively; only FS syscalls are ptrace-emulated (some loading overhead). Experimental — if a game misbehaves, set `DPAD_BUBBLEROOT=0` (needs a host with real userns). |
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
  - **CORRECTED (2026-07-02): the "GStreamer 1.24.6 cannot drive nvh264enc on driver 595" diagnosis was a probe artifact, NOT a real NVENC failure.** NVIDIA removed the legacy NVENC preset GUIDs (`NV_ENC_PRESET_DEFAULT/HP/HQ/LOW_LATENCY/LOSSLESS_*`) starting in **driver 590** (NVIDIA Video Codec SDK 13.1 deprecation notice) — this is the 580-works / 595-fails cutoff (NOT a blanket "NVENC 13 / driver ≥570" thing: driver 580 still accepts the old GUIDs). The **legacy** `nvh264enc` element (old GUIDs) fails on 595 with `Selected preset not supported`; the **modern** `nvcudah264enc` element (P1–P7 + `NV_ENC_TUNING_INFO`) works on BOTH 580 and 595. Selkies' `gstwebrtc_app.py` already maps `--encoder=nvh264enc` → `nvcudah264enc` on GStreamer 1.21–1.24 — so Selkies was always going to use the working element; only the entrypoint probe was testing the literal (legacy) `nvh264enc` and false-negativing. **Fix = probe the element Selkies actually instantiates** (see "Selkies encoder probe fix" above). Confirmed on Vast: hardware `nvh264enc` on RTX 3060/580 and RTX 3090/595.
  - **GStreamer 1.26 upgrade is NOT needed (Path B stays abandoned — now for the right reason).** The earlier rationale ("browser path is secondary, x264 fallback is fine") is obsolete: Selkies now does hardware NVENC on driver 595 via `nvcudah264enc` on the existing 1.24.6 tarball. No from-source GStreamer build, no Selkies patch. (1.26 just renames `nvcudah264enc`→`nvh264enc` and drops the legacy element; the probe already handles both via a Gst-version check.)
  - **Browser-NVENC status:** Selkies = hardware `nvcudah264enc` on all tested drivers (580, 595). Sunshine = `h264_nvenc` (FFmpeg) on all drivers. mws (Sunshine→WebRTC bridge) is integrated on 24.04 and auto-pairs, but the mws *browser stream* is parked behind the `/dev/uinput` input blocker (see CURRENT STATUS) and is now lower priority since Selkies already delivers hardware browser NVENC — the original mws motivation ("give the browser hardware NVENC on driver≥570") is moot for Selkies.
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

## Status: Ubuntu 24.04 + CUDA 12.5.1 · **Xorg + nvidia-DDX NULL mode = PRIMARY gaming path (Vulkan present → DXVK/Proton on GPU, validated on Vast: vkcube streams via Selkies)** · Xvfb+VGL = debug fallback · Selkies = browser stream (NVENC) · **Steam UI = BLOCKED on Vast** (pressure-vessel/userns; bubbleroot-proot crashes CEF) · **Vast product path = HEADLESS steamcmd + `dpad-launch`** · ✅ VALIDATED 2026-07-03: native-Linux game (Wesnoth 599390) AND Windows game (War of Dots 3902430 via GE-Proton11-1 Proton-direct) download + launch + Selkies streams, no Steam UI / no pressure-vessel / no userns · NEXT = orchestrator (Vast provider + per-user Steam token injection + dpad-launch invocation); polish: steamcmd segfault-retry, Valve Proton per-session download helper

### What was built (Ubuntu 24.04 move + mws)
- **Dockerfile**: base `nvidia/cuda:${CUDA_VERSION}-runtime-ubuntu24.04` (default `12.5.1`/`12-5`, single tag `ubuntu24.04`; `12.8.1`/`12-8` → `ubuntu24.04-rtx50` for Blackwell). noble t64 apt renames applied ONLY where actually renamed (libasound2t64, libssl3t64, libgtk-3-0t64); libpulse0/libva2/libvdpau1/libwayland-egl1/libjack-jackd2-0 keep plain names, libvpx7→libvpx9; libgl1-mesa-glx dropped; pipewire packages dropped — we use PulseAudio). Sunshine deb → `sunshine-ubuntu-24.04-amd64.deb`. Selkies tarball/deb auto-resolve to `*_ubuntu24.04_*` via `${UBUNTU_VER}`. `PIP_BREAK_SYSTEM_PACKAGES=1` for noble pip3.
- **7b. moonlight-web-stream**: prebuilt `moonlight-web-x86_64-unknown-linux-gnu.tar.gz` (v2.10.0) → `/opt/mws/{web-server,streamer,static}`. Runs natively (glibc 2.39 = noble).
- **entrypoint.sh**: writes `/opt/mws/server/config.json` at boot (bind `0.0.0.0:8080`, coturn TURN ICE), launches `web-server` as `dpad` after Sunshine, under `DISABLE_DEFAULT_WEBRTC_ICE_SERVERS=1` + `WEBRTC_NAT_1TO1_HOST`. cloudflared now runs **two** tunnels (mws primary `:8080`, Selkies fallback `:16100`); named-tunnel mode fronts mws with `CLOUDFLARED_HOSTNAME`, Selkies gets a quick tunnel. Status banner + periodic log dump (`/tmp/mws.log`) + health loop updated.
- **deploy.sh / docker-compose.yml / healthcheck.sh**: tag `ubuntu24.04`, build args 12.5.1/12-5, port 8080, mws-data volume, mws recognized as a streamer.

### Why 24.04 (and why the pool is NOT lost)
- mws prebuilt needs glibc 2.39 → noble. 24.04 makes it a tarball install (no Rust build / patchelf).
- CUDA 12.5.1 on 24.04 runs on driver ≥525 via minor-version compat. The old "12.5.1 forces driver ≥555" claim confused bundled vs minimum driver (525.60.13). Offer filter stays `cuda_max_good>=12.1` → wide pool kept.
- Latest Sunshine added XDG/Pipewire/KWin direct screencast + Vulkan encoding on Linux — a better match for 24.04 (though headless-Xvfb capture path still needs validation; we may stay on the ximagesrc/KMS path).

### NEXT steps (in order)
1. ✅ DONE (2026-07-02..03) — Build + boot on Vast; noble t64 apt clean; Xorg NULL-mode + Selkies streaming validated (vkcube); `dpad-launch` native-Linux game launch validated (Wesnoth 599390).
2. **Validate mws↔Sunshine end-to-end** (PARKED behind `/dev/uinput` — see CURRENT STATUS): `--privileged` is the remaining lever to try for uinput; else mws video-only. Lower priority now that Selkies delivers hardware browser NVENC + the headless game path works via Selkies.
3. ✅ DONE — Selkies fallback: `nvh264enc` (hardware via `nvcudah264enc`) on BOTH driver 580 and 595 (encoder-probe fix).
4. ✅ DONE (2026-07-03) — Windows game via Proton-direct. `dpad-launch` PATH B runs `$PROTONPATH/proton waitforexitandrun game.exe` under the STEAM_COMPAT_* env vars; GE-Proton11-1 baked in; Proton Experimental + Proton 11.0 downloadable per-session via authenticated steamcmd (anonymous can't). Validated with War of Dots (3902430) on Vast: prefix created, fsync up, game ran on GPU, Selkies streams. Polish: steamcmd segfault-retry loop (segfaults on ~2GB+ downloads, resumes on retry); `steamrt4_platform_*` misdetection fix committed.
5. **Orchestrator** — Vast provider in `apps/api` with the NVENC-safe offer predicate (`cuda_max_good>=12.1`), per-GPU CUDA-variant selection (RTX 50 → `ubuntu24.04-rtx50`, else `ubuntu24.04`), provision via Vast API, read boot log for the Selkies tunnel URL + encoder, create named Cloudflare tunnel, return URL to website. Per-session: inject the user's encrypted Steam credential blob (`config.vdf` + `loginusers.vdf`) so `dpad-launch` is silent from boot (DEFERRED auth design — see `scripts/dpad-launch` notes), set `SELKIES_BASIC_AUTH_PASSWORD` to a session token. Launch games by calling `dpad-launch <appid>` in the container (auto-detects native vs Windows; `DPAD_PROTON` selects the Proton tool).
6. (Later, data-driven) **Present-surface decision** — gamescope / cage, to unlock true DX12 + DLSS scaling (DXVK already works via the Xorg present surface).
7. (Cleanup) **Drop Selkies** once mws+Sunshine is validated (only if mws input is solved).

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