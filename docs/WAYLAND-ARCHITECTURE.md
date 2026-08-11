# DpadCloud Image — Full-Desktop Wayland Architecture (`gst-wayland-display`)

> **Decision + spec (2026-08-08).** The architectural answer to the multi-store
> blocker (`STORES-PLAN.md` §17.3 — `lutris-gamepad-ui` / Electron does not
> render into gamescope-headless's `pipewiresrc` capture node; and the deeper
> problem: the store launchers themselves — Battle.net / Epic / GOG Galaxy / EA
> App / Ubisoft Connect — are all Chromium/CEF Windows apps that need a real
> multi-window desktop to render). This doc specifies the pivot from
> **gamescope-as-the-compositor** to **`gst-wayland-display` (a Smithay
> micro-compositor) as the compositor + capture layer**, with gamescope demoted
> to an XWayland-providing *client*. It preserves everything that matters
> (N-on-N, Selkies+coturn transport, volumes, the control plane, billing) and
> fixes what gamescope-headless structurally cannot.
>
> **Status: DECISION + LIVE-VALIDATED through §16.7 (2026-08-09).** The phased
> plan (§8) started with a cheap probe + a build spike and has validated the
> compositor→Selkies path on a real OVH L4. See the **Current validated state**
> banner below for what's proven vs. what's still open.
>
> **Current validated state (as of §16.7, 2026-08-09; Scaleway Paris added 2026-08-11):**
> - **2026-08-11: Scaleway (Paris) VALIDATED end-to-end on the wayland path** (cloud `5297f1f` + container-gaming `de1f40f`). The `-580-server` → open swap is confirmed required for the compositor's EGL/GBM glamor too (with the swap skipped the compositor EGL-inits off the render node but crashes `driver (null)`/`failed to create dri2 screen` → segfault → "connection error"; after the swap: `GL Renderer: NVIDIA L4`, `EGL hardware-acceleration enabled`, `m=video:9`, sway + the dpad-launcher picker render, image + audio work). The swap is ~2 min (faster than the old 12-18 min estimate). The cloud default is now `DPAD_COMPOSITOR=wayland-display` + `DPAD_WAYLAND_CLIENT=sway` + `DPAD_STORE_SHELL=picker` (flipped 2026-08-11) — so every provider's new sessions boot the wayland path + the dpad-launcher (this was a real fix: the prior deployed default was `picker` + gamescope-headless, which CAN'T capture Electron → no video). The `start_cursor_monitor` latent bug (the §17.2 gap — selkies' own `start_cursor_monitor` derefs `self.xdisplay=None` at startup on the inverted boot) is FIXED (`de1f40f`, a bounded wait-for-`:0` guard in `dpad_input_patch.py`) + ships via the new `dpad_input_patch.py` bind-mount hotfix path (`vm-bootstrap` fetch + `dpad-launch-session` bind-mount — no rebuild). See `cloud/docs/STATUS.md` (the 2026-08-11 Scaleway note) for the full record + the UpCloud handoff.
> - **Compositor + capture PROVEN** — `gst-wayland-display` runs off the DRM
>   render node (no DRM master → N-on-N linchpin holds), EGL/GBM glamor works on
>   the open R580, `waylanddisplaysrc` engages inside selkies' `webrtcbin` at
>   runtime (§13.14, §15: the `m=video:9` gate PASSED → the §17.3 Lutris-capture
>   blocker is RETIRED).
> - **sway is the XWayland client (NOT gamescope-wayland).** `gamescope --backend
>   wayland` drops the connection once Steam's CEF commits surfaces (§16.3);
>   `DPAD_WAYLAND_CLIENT=sway` (`WLR_BACKENDS=wayland`) is validated end-to-end
>   — video + audio + interaction (§16.7).
> - **Capture tail is system-memory RGBx → cudaupload → cudaconvert → nvh264enc**
>   (NVRTC JIT runs, `nvrtc: error`=0, covered by `extract-nvrtc.sh`), NOT
>   CUDAMemory-direct — selkies' static `Gst.Element.link()` can't negotiate
>   CUDAMemory-BGRA→nvh264enc (§15.2 Bug 2). CUDAMemory zero-copy is a §13.3
>   *follow-up*, not the default.
> - **`sdl3-builder` SHIPPED** (§5.6, commit `af5bda6`, image `b403937b`) —
>   `libSDL3.so.0` on the system lib path, live-validated.
> - **Still open (the §8 phasing tail):** Lutris shell + store launchers under
>   sway, the `--device /dev/dri` CDI-perm fix for prod multi-GPU hosts (§14),
>   selkies audio-peer reconnect robustness (§16.7), + the 1080p/1440p +
>   dynamic-resize compositor-mode fix (§17.3 — **DONE 2026-08-09 §18.6**: a sway
>   `output * mode --custom` config line, NOT a plugin-source change; default
>   bumped to 1080p), then the default flip. **N-on-N on the sway path is DONE
>   2026-08-09 (§16.8): 2:1 + 3:1 compositor gate validated.** **Mouse/keyboard under sway are now RESOLVED** (§17.2, the lazy
>   `DPAD_INPUT_DISPLAY` open) + gamepad already worked. The spec sections
>   §2.2/§4/§5.2/§5.3/§5.6/§13.3/§13.9/§13.12 carry `⚠️ SUPERSEDED` markers where
>   the live results changed the design — trust those over the original prose.
>
> **Companion:** `STORES-PLAN.md` (the multi-store plan this unblocks — §17.3 is
> the live-test blocker this retires), `PROJECT_STATE.md` §6 #10/#11/#12 (the
> open image items this supersedes), `IMAGE-RUNBOOK.md` (the launch recipe — the
> new `DPAD_COMPOSITOR` env lands here), `cloud/docs/STATUS.md` §8 #9 (the
> control-plane multi-store item).

## 0. TL;DR — the pivot

| | Today (gamescope-headless) | After (`gst-wayland-display`) |
|---|---|---|
| **Compositor + capture** | `gamescope --backend headless` renders → PipeWire node → `pipewiresrc` (system-memory BGRx) → `cudaupload` → `cudaconvert` (NVRTC JIT) → `nvh264enc` | `waylanddisplaysrc render_node=$RENDER_NODE` → system-memory **RGBx** → `cudaupload` → `cudaconvert` (NVRTC JIT, covered by `extract-nvrtc.sh`) → `nvh264enc` (**validated** §15.2/§16.7). CUDAMemory zero-copy is a §13.3 *follow-up*, not the default — selkies' static `Gst.Element.link()` can't negotiate CUDAMemory-BGRA → nvh264enc (§15.2 Bug 2). |
| **XWayland / legacy apps** (Steam CEF, Wine/Proton store launchers) | gamescope *is* the compositor + the XWayland provider | **sway** runs as a Wayland client of gst-wayland-display (`WLR_BACKENDS=wayland`, no DRM master) + provides XWayland to the app — **validated live §16.7** (video+audio+interaction). `gamescope --backend wayland` was the planned client but **drops the connection once Steam's CEF commits surfaces** (§16.3); the `DPAD_WAYLAND_CLIENT` gate selects the client (sway is the working one). |
| **Native-Wayland apps / full desktop** (Electron `--ozone-platform=wayland`, sway, OpenGamepadUI/Godot) | not reliably captured (the §17.3 bug) | render **directly** into gst-wayland-display → captured |
| **Transport** | Selkies `webrtcbin` + coturn + Opus inband FEC + ULP_RED video FEC + NACK rtx | **unchanged** |
| **N-on-N** | shared GPU via MPS daemon (or raw time-slice) | shared render-node EGL contexts (raw time-slice, no DRM master) — MPS still optional for loaded 3:1 |
| **Input** | Selkies datachannel → XTest on Xwayland `:0` | Selkies datachannel → gst-wayland-display input messages (mouse/kb) + inputtino virtual `/dev/input/event*` (gamepads); XTest remains *inside* gamescope for XWayland apps |
| **Gamepad** | 6-layer chain + evdev interposer (working, validated) | inputtino virtual pads (cleaner, same outcome) — or keep the existing chain initially |

**Net:** one new build stage (`wayland-display-builder`), one GStreamer source
element swap (`pipewiresrc` → `waylanddisplaysrc`), sway (or gamescope) demoted
to a Wayland client of the compositor, plus the input-side rework. Everything
downstream (encode, coturn, FEC, the web client, the control plane, billing,
volumes) is untouched.

## 1. The problem (why gamescope-headless can't get there)

`gamescope --backend headless` was chosen for **one** reason: it renders via
Vulkan/gamescope-WSI with **no DRM master** → no `nvidia-modeset` singleton →
**N sessions on N GPUs in one VM** (and N-on-1 oversubscription via MPS). That
single property is what made the whole datacenter-GPU economics work
(`PROVIDERS.md` §3). It is non-negotiable — any replacement must preserve it.

The cost of that choice: gamescope-headless is a **minimal, game-focused
compositor**. It captures reliably only the thing it was built for — a single
fullscreen app (Steam Big Picture, a game) rendered via Vulkan into one PipeWire
node. It does **not** composite an arbitrary desktop of windows reliably.

This has now hit two walls:

1. **The picker wall (live-confirmed, `STORES-PLAN.md` §17.3):** with
   `DPAD_STORE_SHELL=lutris`, the video webrtcbin adds **`m=video: 0`** (vs
   `m=video: 2` for Steam on the *same* VM/image). `lutris-gamepad-ui` (an
   Electron AppImage) does not render into the gamescope `pipewiresrc` capture
   node the way Steam's CEF does. Audio works; no video. The decisive probe
   (`DPAD_LUTRIS_DISABLE_GPU=1`) was wired but never run (the session crashed at
   the context limit before reaching it).

2. **The store-launcher wall (the real one, not yet hit live because #1 blocks
   first):** the actual store launchers — Battle.net, Epic Games Launcher, GOG
   Galaxy, EA App, Ubisoft Connect — are **all Chromium/CEF-based Windows apps**
   run via Wine/Proton. When a user launches a Battle.net game, *Battle.net-Setup*
   (a Chromium UI) has to render + the user navigates it before the game starts.
   Same for Epic, GOG, EA. These are multi-window desktop apps, not single-
   fullscreen games. Multi-store is not "render a picker, then games render" —
   it is "render a picker, then a CEF launcher renders, then the game renders,"
   all in one captured compositor. gamescope-headless is the wrong shape for
   that.

So the picker is a symptom. The launchers are the disease. Your instinct is
correct: we need a **real compositor that any app renders into** — and it must
keep the no-DRM-master property that makes N-on-N possible.

## 2. The reference architecture — games-on-whales / Wolf / `gst-wayland-display`

[**games-on-whales**](https://games-on-whales.github.io/wolf/) (Wolf, ~2k★, MIT)
is the gold reference for multi-user headless GPU streaming. They built exactly
this for the same reason we need it. The architecture (from their
["How does it work?"](https://games-on-whales.github.io/wolf/stable/dev/how-it-works.html)):

- **Virtual desktop:** a custom micro Wayland compositor,
  [`gst-wayland-display`](https://github.com/games-on-whales/gst-wayland-display)
  (Smithay, Rust, MIT). It exposes the raw framebuffer / DMA-BUF / CUDAMemory
  directly to a GStreamer pipeline — the compositor *is* the capture source.
  Crucially, it does **not** do XWayland itself.
- **XWayland apps (Steam, Wine launchers):** they run **gamescope as a Wayland
  client** of gst-wayland-display. gamescope provides XWayland to the downstream
  app; gamescope's composited output becomes a Wayland surface that
  gst-wayland-display captures.
- **Native Wayland apps + full desktop:** they run **sway** (a wlroots
  compositor) as a Wayland client of gst-wayland-display — `RUN_SWAY=1` is the
  default in their app containers. `RUN_GAMESCOPE=1` is the fallback for
  XWayland-heavy apps. (Their `launch-comp.sh` picks one from env.)
- **Virtual audio:** standalone PulseAudio per session (we already have
  pipewire-pulse null sinks — keep ours).
- **Virtual input:** [`inputtino`](https://github.com/games-on-whales/inputtino)
  — abstracts `uinput`/`uhid` to create virtual mouse/keyboard/gamepad devices +
  a `fake-udev` for hotplug inside the app container.
- **Streaming:** GStreamer → their custom `rtpmoonlightpay` Moonlight RTP+FEC
  plugin. **They use Moonlight, not Selkies/browser.** This is the one piece we
  do NOT take.

### 2.1 The N-on-N linchpin: render node, no DRM master

This is the make-or-break property, and gst-wayland-display has it.

gst-wayland-display initialises its EGL display straight off the **DRM render
node** (`/dev/dri/renderD128`) via the `EGL_EXT_device_drm_render_node`
extension — **not** off a DRM master fd. Confirmed in the
[Smithay `EGLDevice` docs](https://smithay.github.io/smithay/smithay/backend/egl/struct.EGLDevice.html):
`EGLDevice::render_device_path()` + `try_get_render_node()` +
`EGLNativeDisplay` (creates the display from the EGLDevice, no DRM fd). The C
binding example in the gst-wayland-display README: `display_init("/dev/dri/renderD128")`.

A DRM render node has **no master singleton** — any process with permission can
open it and get a GL/Vulkan/CUDA context. Multiple compositor instances each
open the same render node → the GPU time-slices between contexts. The Wolf
maintainer states it plainly (GitHub Discussion #236): *"Wolf doesn't require
GPU partitioning, you can share a single GPU with multiple users whilst keeping
them isolated between each other … without any VM involved."* They do this
**without MPS by default** — just shared render-node contexts. (Our docs note our
own 3-on-1 L4 boot test ran as "raw GPU time-slice, no MPS daemon yet" — the same
model. MPS remains an option for better behaviour under active 3:1 load; it is
not required for correctness.)

This is the same property gamescope-headless gives us. We lose nothing.

### 2.2 The capture is genuinely better than what we have

> ⚠️ **SUPERSEDED by §15.2 Bug 2 (live, 2026-08-08).** The CUDAMemory zero-copy
> path below does **not** work through selkies' *static* `Gst.Element.link()`
> (nvh264enc narrows CUDAMemory to NV12/Y444 at static query_caps → no common
> format with the compositor's BGRA). The **validated** path is system-memory
> **RGBx** → `cudaupload` → `cudaconvert` (NVRTC JIT, covered by
> `extract-nvrtc.sh`, `nvrtc: error`=0) → `nvh264enc` — the *same* encode tail
> as `pipewiresrc`, with a different source. CUDAMemory zero-copy is retained
> below as a §13.3 *follow-up* (`link_pads_full(NO_CAPS_CHECK)` or PR #35 NV12
> DMABuf→CUDAMemory), not the default.

Today's pipeline (system-memory round-trip + a JIT we had to patch):

```
pipewiresrc(target-object=gamescope, always-copy=True)   # system-memory BGRx
  → videorate → cudaupload → cudaconvert(BGRx→NV12)      # NVRTC JIT (sm_89/sm_120 bug → §6 #10)
  → nvh264enc → webrtcbin → coturn → browser
```

The gst-wayland-display zero-copy path (Nvidia CUDAMemory, gated behind its
`cuda` feature flag):

```
waylanddisplaysrc render_node=$RENDER_NODE cuda-device-id=$CUDA_ID
  ! video/x-raw(memory:CUDAMemory),width=1920,height=1080,framerate=60/1
  ! nvh264enc → webrtcbin → coturn → browser
```

The compositor produces CUDAMemory **directly** via
`cuGraphicsEGLRegisterImage` (it re-uses the GL context it already has in
Smithay) — **no `cudaupload`, no `cudaconvert`, no NVRTC JIT**. Two wins:

- **Lower latency + less CPU** (true zero-copy; the current path is
  system-memory BGRx with an `always-copy=True` copy at the PipeWire boundary +
  a CPU→GPU upload + a JIT colour-convert).
- **The NVRTC sm_89/sm_120 bug (`PROJECT_STATE.md` §6 #10, `STORES-PLAN.md`
  §17.2) likely becomes moot on this path** — the failing element (`cudaconvert`'s
  NVRTC JIT) is not in the pipeline. The `extract-nvrtc.sh` bake is still
  valuable (it's the hotfix path for existing gamescope-headless images + the
  fallback `DMABuf`/system-memory path of gst-wayland-display), so it is NOT
  removed — but it may no longer be on the critical path. Confirm with a live
  probe in the spike.

The `DMABuf` path (AMD/Intel, or Nvidia without the `cuda` feature) and a
plain `video/x-raw,format=RGBx` software path (`render_node=software`) are also
available — graceful fallbacks if CUDAMemory fails on a given host.

### 2.3 Multi-GPU is now solved (the last open Wolf issue, as of Nov 2025)

Wolf's multi-GPU story was rough through 2025 (issue #233 — GStreamer nvcodec
fell back to software encoding when `WOLF_RENDER_NODE` pointed past renderD128).
This was fixed Nov 2025: PR #287 (wolf) + PR #22 (gst-wayland-display) —
`get cuda_device_id from render node` / `get CUDA device index in ascending
order based on PCI addresses`. Merged to `wolf:stable`, confirmed working by the
reporter. So `WOLF_RENDER_NODE=/dev/dri/renderD129` now correctly drives both
the compositor render and the encoder on the right GPU.

The one lingering Nvidia gotcha (issue #233 tail +
[NVIDIA/nvidia-container-toolkit#1249](https://github.com/NVIDIA/nvidia-container-toolkit/issues/1249)):
nvcodec's session enumeration needs **all** `/dev/nvidia*` devices passed to the
container, or GStreamer can't instantiate the HW encoders. This is the *same* bug
our `libnvenc_fix.so` interposer already works around (`PROJECT_STATE.md` §4 —
NVENC #1249 flexgrip interposer filters `GET_ATTACHED_IDS` to mounted GPUs). So
this is a known, already-handled limitation for us, not a new blocker.

### 2.4 What we do NOT take from Wolf

- **The Moonlight transport** (`rtpmoonlightpay`, their custom RTP+FEC plugin).
  We keep **Selkies `webrtcbin` + coturn + Opus inband FEC + ULP_RED video FEC +
  NACK rtx**. The compositor→GStreamer interface is transport-agnostic
  (`waylanddisplaysrc` is a generic GStreamer source); we swap only the source
  element, not the sink.
- **The Wolf app-container orchestration** (Wolf spins up a Docker container
  per app session, owns the docker socket). We keep our one-container-per-slot
  model (`dpad-launch-session` launches one `:dpad-SteamOS` CDI container per
  GPU/slot). We adopt the *compositor* and *input* libraries, not the Wolf server
  process.
- **Their PulseAudio sidecar.** We have pipewire-pulse null sinks; keep ours.

## 3. The decision

**Adopt `gst-wayland-display` as the compositor + capture layer. Run gamescope
as a Wayland client (XWayland provider) for legacy/Steam/Wine-Proton apps. Run
native-Wayland apps + a full desktop directly into gst-wayland-display. Keep
Selkies + coturn as the transport. Keep N-on-N via shared render-node EGL
contexts (MPS optional). Adopt `inputtino` for virtual input devices (staged;
XTest stays for the gamescope-XWayland path initially).**

This is a fundamental change to the image's compositor/capture stage — but it is
a **proven** architecture (games-on-whales runs it in production for multi-user
headless streaming), not greenfield. It is contained: one new build stage, one
GStreamer source-element swap, gamescope demoted from compositor to client, and
the input rework. Everything downstream is untouched.

### Why this over the alternatives

| Option | Verdict |
|---|---|
| **Keep gamescope-headless, fix Electron capture with flags** (`DPAD_LUTRIS_DISABLE_GPU` etc.) | ❌ Doesn't solve the store-launcher wall (§1 #2). Even if the picker renders, Battle.net/Epic/EA CEF apps still won't composite cleanly. A patch, not a fix. (Run the probe anyway — §8 step 1 — to characterise the Electron bug; it doesn't change the decision.) |
| **gamescope-headless + sway as the shell inside gamescope** | ❌ sway-as-gamescope-client still funnels through gamescope's PipeWire capture, which is the thing that doesn't capture Electron reliably. The compositor is still gamescope. |
| **Replace gamescope with a wlroots compositor that grabs DRM master** (sway/wlroots standalone, Hyprland) | ❌ DRM master is a singleton per GPU → kills N-on-N → kills the economics. Hard no. |
| **`gst-wayland-display` as compositor + gamescope/sway as clients** (the decision) | ✅ Render node, no DRM master, N-on-N preserved; true CUDAMemory zero-copy; any app (native Wayland, Electron, XWayland/Wine) renders + is captured; proven by games-on-whales. |
| **Sunshine + Moonlight** (the GFN/Shadow transport Wolf uses) | ❌ Browser stream is a core product requirement (no client install). Selkies stays. |

## 4. The new pipeline

> ⚠️ **PARTIALLY SUPERSEDED (live, 2026-08-08/09):** (1) The capture tail is
> **system-memory RGBx → cudaupload → cudaconvert → nvh264enc**, NOT the
> CUDAMemory-direct path shown below (§15.2 Bug 2 — selkies' static link can't
> negotiate CUDAMemory-BGRA→nvh264enc). CUDAMemory zero-copy is a §13.3 follow-up.
> (2) The XWayland client is **sway** (`WLR_BACKENDS=wayland`), not `gamescope
> --backend wayland` — gamescope-wayland drops the connection once Steam's CEF
> commits surfaces (§16.3); sway is validated end-to-end (§16.7). The diagram
> below shows the *intended* design; read it with those two corrections.

```
┌─ gst-wayland-display (compositor + capture) ──────────────────────────────┐
│  EGL display off /dev/dri/renderD128 (render node, NO DRM master)          │
│  Wayland socket: wayland-N (per session, in $XDG_RUNTIME_DIR)              │
│  Output: video/x-raw(memory:CUDAMemory) 1920x1080@60                        │
└────────────────────────────────────────────────────────────────────────────┘
        ▲ Wayland clients                                   │ CUDAMemory
        │                                                     ▼
┌───────────────────────┐   ┌───────────────────────────────────────────────┐
│ Native-Wayland apps    │   │ XWayland apps (Steam CEF, Wine/Proton         │
│  • Lutris gamepad-UI   │   │   store launchers: Battle.net/Epic/GOG/EA)    │
│    (Electron,          │   │                                              │
│    --ozone-platform=   │   │  gamescope (runs as a Wayland CLIENT of       │
│    wayland) — primary  │   │    gst-wayland-display; provides XWayland :0   │
│  • sway full-desktop   │   │    to the app; its surface is captured)       │
│    (window mgmt;       │   │  -- steam -gamepadui  OR  -- lutris-shell      │
│    fallback)           │   │    OR  -- <wine/Proton launcher>              │
└───────────────────────┘   └───────────────────────────────────────────────┘
        │ Wayland socket wayland-N                              │
        └──────────────────────┬─────────────────────────────────┘
                               ▼
[Selkies capture — CUDAMemory direct, NO pipewiresrc / NO cudaupload / NO cudaconvert]
   waylanddisplaysrc cuda-device-id=$CUDA_ID
     ! video/x-raw(memory:CUDAMemory),width=1920,height=1080,framerate=60/1
     ! nvh264enc (zerolatency, preset p1) → webrtcbin → coturn → browser
[Audio]  pipewire-pulse null sink → Selkies pulsesrc  ← UNCHANGED
[Input]  browser WebRTC datachannel → Selkies
           ├─ mouse/kb → gst-wayland-display input messages (MouseMoveRelative etc.)
           └─ gamepad  → inputtino virtual /dev/input/event* (uinput/uhid) + fake-udev
                         → compositor (native Wayland) + gamescope XWayland :0 (legacy)
[Gamepad under gamescope-XWayland] the existing 6-layer chain + evdev interposer
   stays initially (working, validated); migrate to inputtino in a later phase.
```

N-on-N: one gst-wayland-display + one gamescope-client (or native app) per
container, one container per GPU/slot, all compositors sharing the render node
via EGL. Identical to today's N-on-N from the host's perspective.

## 5. What changes in the image (layer by layer)

### 5.1 New build stage: `wayland-display-builder`

Mirror the existing `gamescope-builder` stage. Build from source:

- **`gst-wayland-display`** — Rust + [`cargo-c`](https://github.com/lu-zero/cargo-c)
  (`cargo cinstall --prefix=/usr/local`). Needs Smithay's `backend_egl` +
  `backend_drm` + the `cuda` feature flag (for CUDAMemory output). Installs the
  GStreamer plugin to `/usr/local/lib/gstreamer-1.0/libgstwaylanddisplaysrc.so`
  + the C library `libgstwaylanddisplay` (for the input-message API).
- **`gst-cuda-1.0`** — the build dep for the `cuda` feature (provides the
  `CUDAMemory` GStreamer memory type + the `cuda-device-id` property). Runtime
  needs `libcuda.so` (already present via the nvidia runtime/CDI).
- **`inputtino`** — the virtual-input library (uinput/uhid) + its `fake-udev`
  CLI. Build from `games-on-whales/inputtino`.

Build-time deps: Rust toolchain, `libgstreamer1.0-dev`, `libgstreamer-plugins-bad-dev`,
`libegl-dev`, `libwayland-dev`, `cargo-c`. The CUDAMemory feature also needs the
CUDA toolkit headers (already in the image).

### 5.2 Entrypoint: a new `DPAD_COMPOSITOR` gate

> ⚠️ **UPDATED by §14 (implementation) + §16.3/§16.4/§16.7 (live).** The gate as
> built adds a second knob `DPAD_WAYLAND_CLIENT=gamescope|sway` (default
> `gamescope` = no regression) selecting the XWayland-providing *client* of the
> compositor. **sway is the validated path** (§16.7 — video+audio+interaction);
> `gamescope --backend wayland` drops the connection once Steam's CEF commits
> surfaces (§16.3) → kept as a fallback env, not the working path. The capture
> tail is system-memory **RGBx → cudaupload → cudaconvert → nvh264enc** (§15.2),
> NOT the CUDAMemory-direct pipeline in step 3 below. The inverted boot order
> (selkies first → peer connects → compositor starts → client launches) + the
> `--device /dev/dri` + dummy-Xvfb-for-pynput + `/tmp/.X11-unix` fixes are in §14.

Add `DPAD_COMPOSITOR` (default `gamescope` = the **current, unchanged, no-
regression** path; `wayland-display` = the new path). The new path:

1. Start `gst-wayland-display` (via `waylanddisplaysrc` in the Selkies GStreamer
   pipeline, OR as a standalone compositor that Selkies' pipeline reads from —
   Wolf runs it as the GStreamer source directly, which is cleanest). It exposes
   a `wayland-N` socket in `$XDG_RUNTIME_DIR` + the device/env list the app
   needs (`WAYLAND_DISPLAY=wayland-N`, the render node, the input devices).
2. Launch the shell as a Wayland client of that socket:
   - **Native Wayland shell** (Lutris gamepad-UI with `--ozone-platform=wayland`
     / sway full-desktop / the OpenGamepadUI fallback): set
     `WAYLAND_DISPLAY=wayland-N` + run directly.
   - **XWayland shell** (Steam / Wine-Proton launchers): run
     `gamescope --backend wayland -- WAYLAND_DISPLAY=wayland-N -- <app>` —
     gamescope as a Wayland client provides XWayland `:0` to the app. (This is
     the games-on-whales `RUN_GAMESCOPE=1` path.)
3. Selkies capture pipeline swaps `pipewiresrc …` for
   `waylanddisplaysrc render_node=$RENDER_NODE cuda-device-id=$CUDA_ID !
   video/x-raw(memory:CUDAMemory),… ! nvh264enc …`. The `webrtcbin` + coturn +
   FEC side is unchanged.
4. Input: Selkies datachannel → mouse/kb as `MouseMoveRelative`/key GStreamer
   messages to `waylanddisplaysrc`; gamepads via inputtino virtual devices
   (stage-gated — see §5.4).

The `DPAD_STORE_SHELL` gate (steam/lutris) stays; it selects *what* runs as the
client, orthogonal to *which compositor*. Under `DPAD_COMPOSITOR=wayland-display`:
- `DPAD_STORE_SHELL=steam` → `gamescope --backend wayland -- steam -gamepadui`.
- `DPAD_STORE_SHELL=lutris` → `lutris-shell` with `--ozone-platform=wayland`
  (native Wayland; the §17.3 fix) OR `gamescope --backend wayland --
  lutris-shell` (XWayland, if the Electron app needs X).
- `DPAD_STORE_SHELL=opengamepadui` (fallback, not built yet) → native Wayland,
  no gamescope.
  (XWayland; Electron under XWayland) OR `lutris-shell` with
  `--ozone-platform=wayland` direct (native Wayland — the §17.3 fix).

### 5.3 The `DPAD_VIDEO_SRC` semantics change

> ⚠️ **SUPERSEDED by §15.2 (live).** The `cuda`/CUDAMemory-zero-copy default
> does **not** work through selkies' static link. The **validated** capture is
> system-memory **RGBx** → `cudaupload` → `cudaconvert` → `nvh264enc` (the
> selkies patch's `waylanddisplaysrc` branch uses waylanddisplaysrc's
> system-memory src-pad template, not the CUDAMemory one — §15.2 Bug 2). So
> under `DPAD_COMPOSITOR=wayland-display`, `DPAD_VIDEO_SRC=waylanddisplaysrc`
> selects the compositor source with a **system-memory RGBx** output; CUDAMemory
> zero-copy is a §13.3 follow-up, not a `DPAD_VIDEO_SRC` mode today.

Today `DPAD_VIDEO_SRC` (`pipewiresrc` default, `ximagesrc` = the `:2` Xvfb
fallback) selects the capture source for the gamescope-headless path. Under
`DPAD_COMPOSITOR=wayland-display`, `DPAD_VIDEO_SRC` becomes the
gst-wayland-display output mode: `cuda` (default, CUDAMemory zero-copy),
`dmabuf` (DMA-BUF, for the fallback/AMD/Intel path), `software` (system-memory
RGBx, the `render_node=software` option — for a CPU-only host or a hard
failure). Keep the name for operational familiarity; document the new semantics
in `IMAGE-RUNBOOK.md`.

### 5.4 Input — staged, lowest-risk-first

Today: Selkies datachannel → `xtest.fake_input` on Xwayland `:0` → Xwayland →
the focused app. This works for XWayland apps (Steam, Wine/Proton). It does NOT
reach native-Wayland apps (Electron `--ozone-platform=wayland`, sway,
OpenGamepadUI) — there is no X server for them. (Lutris gamepad-UI under
`--ozone-platform=wayland` is native-Wayland too.)

The target: Selkies datachannel →
- **mouse/keyboard** → gst-wayland-display input messages (`MouseMoveRelative`,
  key events — the C API `display_add_input_device` + the GStreamer-message
  path Wolf uses). Reaches native-Wayland clients directly + (via gamescope's
  XWayland) the legacy apps.
- **gamepad** → inputtino virtual `/dev/input/event*` + `fake-udev` hotplug →
  compositor + gamescope-XWayland see real-looking gamepad devices.

**Staging (do not big-bang the input rewrite):**
1. **Phase A (spike):** keep XTest for the gamescope-XWayland path (it already
   works there). Add the gst-wayland-display message-based path for mouse/kb to
   reach native-Wayland clients. Gamepad stays on the existing 6-layer chain
   under gamescope-XWayland.
2. **Phase B:** inputtino gamepads (cleaner; the games-on-whales way). Retire
   the 6-layer chain + evdev interposer once inputtino gamepads are validated
   end-to-end with a real controller (the same bar the evdev path cleared
   2026-08-04).

### 5.5 N-on-N / oversubscription — unchanged host-side

From the host's perspective nothing changes: still one CDI container per GPU
(`NVIDIA_VISIBLE_DEVICES=nvidia.com/gpu=i`), per-container coturn port, per-
container `--cpus`/`--memory`, MPS optional. The compositor instances share the
render node via EGL — no DRM master, no modesetting contention. The
`DPAD_OVERSUBSCRIBE=N` MPS extension is orthogonal and still applies if we want
it for loaded 3:1. Validate 2:1 + 3:1 on the new path in the spike (§8 step 2).

### 5.6 `libSDL3` for the Lutris shell (the §17.4 item — now on the critical path)

> ✅ **DONE + LIVE-VALIDATED 2026-08-08** (commit `af5bda6`, image `b403937b`).
> The `sdl3-builder` stage (SDL3 3.2.28 from source, minimal backends →
> `libSDL3.so.0` on the system lib path) is shipped in the public `:dpad-SteamOS`
> image + live-validated on an OVH L4 (`lutris-shell.log` → `[sdl_manager] SDL3
> initialized! libSDL3.so.0` vs the old `Unable to load`). Retires §17.4. The
> spec text below is the design record.

With Lutris as the primary shell (§6), the `libSDL3.so.0`-unfindable-by-
`lutris-gamepad-ui` bug (`PROJECT_STATE.md` §6 #12 / `STORES-PLAN.md` §17.4) is
**on the critical path**, not deferred. `lutris-gamepad-ui`'s Electron app uses
koffi (FFI) `dlopen("libSDL3.so.0")`; libSDL3 lives only in Steam's runtime
dirs, not on the system library path → the SDL3 gamepad path
(`LUTRIS_GAMEPAD_UI_ENABLE_SDL_INPUT=1`) is broken → gamepad won't navigate
the UI (keyboard/mouse via Selkies Desktop mode still work).

**Fix (one new build stage, `sdl3-builder`):** build SDL3 from source with
**minimal backends** (joystick/hidapi/events — the app only needs gamepad
*input*; rendering is Chromium/Electron), install `libSDL3.so.0` to
`/usr/lib/x86_64-linux-gnu/` + `ldconfig`. Do NOT pull the oracular `libsdl3-0`
.deb — it drags a newer `libpipewire-0.3-0t64` + `gstreamer1.0-pipewire` that
would churn the carefully-pinned GStreamer/Selkies stack. SDL3 is not in
Noble (24.04) repos (landed in 24.10 oracular) — source build is the safe path.
Note: SDL3's SOVERSION is **0** (deliberate — the SDL3 CMakeLists.txt keeps
SOVERSION 0 across the 3.x series and only bumps it on an incompatible change,
which would rename the lib to SDL4), so `cmake --install` already emits
`libSDL3.so.0` as the canonical SONAME — no manual symlinks. This retires
§17.4 and unblocks gamepad navigation of the Lutris UI.

## 6. The picker-shell sub-decision

Independent of the compositor. The new compositor makes *any* shell capturable
— that was the §17.3 blocker, now retired — so the shell choice is back to
**which 10-foot gamepad UI best covers the stores**. Re-evaluated 2026-08-08:
the earlier OpenGamepadUI-first call was over-weighted by the *old* Electron-
capture problem, which the new compositor retires. Under the new compositor
Electron captures fine, so the differentiator is really store coverage + how
much is already built. Three candidates:

| Shell | Renderer | Multi-store coverage | Already built? | Remaining bug | Verdict |
|---|---|---|---|---|---|
| **Lutris gamepad-UI** (`andrew-ld/lutris-gamepad-ui` over Lutris v0.5.22) | Electron/Chromium (captures fine under the new compositor) | **Steam + Epic + GOG + Battle.net** — the whole v1 set, natively (that's why Lutris was chosen, `STORES-PLAN.md` §0/§1) | ✅ yes — GE-Proton11-3 + Lutris + the AppImage + the entrypoint gate + `lutris-shell` wrapper + the control-plane env are all built + deployed (`STORES-PLAN.md` §16) | `libSDL3.so.0` unfindable → gamepad nav broken (§17.4) — **one contained `sdl3-builder` stage fixes it** (§5.6) | **Recommended v1.** Built, covers all stores, one contained fix. |
| **OpenGamepadUI** ([ShadowBlip](https://github.com/ShadowBlip/OpenGamepadUI), ~922★, GPL3, Godot 4 / Vulkan) | Godot/Vulkan (renders like a game) | "launch games from multiple sources" is a feature, but **store-source coverage unverified** — confirm it actually has Epic/GOG/Battle.net sources (vs Steam-library-import + standalone games) before relying on it | ❌ new integration work | unknown (untested in our stack) | **Verified fallback.** Only if the Lutris UX fails *and* its store coverage is confirmed. The Vulkan-renders-like-a-game advantage shrinks to near-zero once the new compositor captures Electron. |
| **Custom picker** (B1 from `STORES-PLAN.md` §1) | ours | ours | ❌ | ours | **Only if both above fail UX-wise.** |

**Decision (revised 2026-08-08): Lutris gamepad-UI as the v1 shell under the new
compositor; OpenGamepadUI as the verified fallback.** Lutris is already built +
deployed, covers all v1 stores natively, and its one remaining bug (libSDL3 for
gamepad nav) is a contained `sdl3-builder` stage (§5.6) — not architectural. The
new compositor retires the §17.3 capture bug that made Lutris "the wrong shape,"
so Electron is no longer a disqualifier. Wire it as `DPAD_STORE_SHELL=lutris` →
`lutris-shell` as a Wayland client of gst-wayland-display, either direct
(`--ozone-platform=wayland`, native Wayland) or via `gamescope --backend
wayland` (XWayland, if the Electron app needs X). The §5 Xwayland rule
(`STORES-PLAN.md` §5) for the Windows store launchers still applies — they run
via `gamescope --backend wayland -- <wine/Proton launcher>`.

**OpenGamepadUI is kept as a documented fallback, not built yet.** If the Lutris
UX doesn't feel right after live validation, *then* evaluate OpenGamepadUI — but
verify its Epic/GOG/Battle.net source coverage first (it may only import the
Steam library + launch standalone games, which would not satisfy multi-store on
its own). Do not invest in the OpenGamepadUI integration until that coverage is
confirmed.

## 7. Risks / unknowns (honest)

- **Bus factor.** `gst-wayland-display` is ~68★, one main maintainer (ABeltramo)
  + a few contributors. MIT + Rust/Smithay — we *can* fork/maintain, but it is a
  dependency on a small project. **Mitigation:** vendor/fork it into our repo
  (`container-gaming/third_party/gst-wayland-display` or a pinned git tag) so a
  upstream break or abandonment doesn't strand us. Track upstream; contribute
  fixes back (we'll be a real user — e.g. the Selkies-webrtcbin integration +
  any inputtino-to-evdev-bridge parity).
- **Second real user / first browser-WebRTC consumer.** Wolf is the only major
  consumer, and it uses Moonlight out. We'd be the first to drive
  `waylanddisplaysrc` into a Selkies `webrtcbin`+coturn sink. The compositor→
  GStreamer interface is transport-agnostic (`waylanddisplaysrc` is a generic
  source emitting `video/x-raw(memory:CUDAMemory)`), so this is low-risk, but
  **unproven** — the spike (§8 step 2) exists to de-risk exactly this.
- **NVRTC interaction.** The CUDAMemory path may bypass `cudaconvert`'s NVRTC
  JIT entirely (the compositor emits CUDAMemory via `cuGraphicsEGLRegisterImage`,
  not NVRTC). If so, `PROJECT_STATE.md` §6 #10 / `STORES-PLAN.md` §17.2 (the
  `extract-nvrtc.sh` bake) becomes redundant *on the new path* — but it is NOT
  removed: it remains the hotfix path for existing gamescope-headless images +
  the gst-wayland-display `DMABuf`/software fallbacks. Confirm with a live
  probe in the spike (does `nvh265enc` init cleanly on sm_89 with no NVRTC
  extraction under `waylanddisplaysrc ! CUDAMemory`?).
- **Input rewrite risk.** Moving from XTest-on-Xwayland to compositor-input is
  the highest-risk piece. **Mitigation:** stage it (§5.4) — keep XTest for the
  gamescope-XWayland path (where it works today), add the compositor-message
  path only for native-Wayland clients first. inputtino gamepads last, behind
  the same real-controller validation bar the evdev path cleared.
- **The cheap probe was never run.** `DPAD_LUTRIS_DISABLE_GPU=1` (already wired,
  `STORES-PLAN.md` §17.5 #2) was the decisive test for the *old* Electron-capture
  bug. Run it once on a live VM (§8 step 1). If `m=video:2` appears with
  `--disable-gpu`, the Electron bug is a GPU-init/GL-context issue under
  gamescope-headless and a *cheap* partial fix exists for the picker. **This
  does not change the strategic decision** (the store launchers still need the
  new compositor), but it tells us whether the new architecture is *strictly
  necessary now* or *the right direction + the current path is recoverable*.
  Either way we proceed to the spike.
- **gamescope-as-Wayland-client stability — CONFIRMED BROKEN; sway is the
  workaround (§16.3/§16.7, live 2026-08-09).** gamescope's `--backend wayland`
  inits fine but **drops the connection** to gst-wayland-display once Steam's
  CEF commits surfaces (`IWaitable hung up` / `Connection reset by peer`,
  §16.3). The games-on-whales caveat ("may be unstable with some Nvidia driver
  versions") is confirmed on R580-open. **Resolution (validated):** sway as the
  Wayland client (`WLR_BACKENDS=wayland` → no DRM master → N-on-N preserved) +
  XWayland, gated by `DPAD_WAYLAND_CLIENT=gamescope|sway` — sway stays up
  (self-heals on drop via the health loop), Steam renders, audio plays,
  clickable (§16.7). gamescope-wayland is kept as a fallback env, not the path.
- **Driver-variant sensitivity.** gst-wayland-display uses EGL/GBM glamor —
  the same path that **requires the OPEN Nvidia driver variant**
  (`PROJECT_STATE.md` §5 — the proprietary 580.126.20 → black screen on
  gamescope-headless; the open variant works). The Scaleway driver-swap
  (`ensure_driver_580`, `STATUS.md` §4 #42) already ensures the open variant on
  every provider. gst-wayland-display inherits the same requirement (and the
  same fix). No new driver work; just confirm in the spike that the open driver
  + gst-wayland-display EGL init is clean.
- **`/dev/dma_heap/system` + nvidia-drm.** Issue #379 (a user panic
  `Failed to create GsCUDABuf`) traced to an nvidia-container-toolkit EGL device
  enumeration issue, NOT a DRM-master issue (the maintainer's read). It needs
  the manual-nvidia-driver-volume method or a correct toolkit config. We use
  CDI + the toolkit — confirm in the spike that CUDAMemory init succeeds under
  our CDI setup (the `libnvenc_fix.so` #1249 handling + the open driver should
  cover it).

## 8. Phased plan (lowest-risk-first)

1. **Probe — 1 live session, ~30 min.** On a Paris or OVH L4 (open driver, NVRTC
   fix live), `DPAD_STORE_SHELL=lutris DPAD_LUTRIS_DISABLE_GPU=1` → does
   `m=video:2` appear? Confirms the nature of the §17.3 Electron-capture bug
   under the *current* compositor. Does not change the decision; characterises
   the bug. (If it fixes the picker, ship it as a stopgap while the new
   compositor is built — the store launchers still need the new compositor.)

   **✅ RUN 2026-08-08 (OVH Gravelines L4 `188.165.71.21`, image `b403937b…` with
   the libSDL3 fix): `DPAD_LUTRIS_DISABLE_GPU=1` did NOT fix it — the browser
   still showed "Waiting for stream" (the video m-line stayed 0).** gamescope's
   PipeWire stream oscillated `paused`↔`streaming` + the `gamescope:capture_1`
   node was active, but Selkies' `pipewiresrc → webrtcbin` produced no video
   track (a parallel `gst-launch pipewiresrc` grab captured 0 frames in 14s).
   So the Lutris Electron app does NOT deliver capturable frames to Selkies
   under gamescope-headless, even with software compositing — the bug is
   fundamental to gamescope-headless + Electron, NOT a GPU-init issue. **The
   `gst-wayland-display` pivot (step 2) is strictly necessary, not optional.**
   (Side win: the same session validated §17.4 — `sdl_manager: SDL3
   initialized! libSDL3.so.0` — so the libSDL3 fix is shipped regardless.)

2. **Spike — build + 1 VM, ~1–2 days.**
   > ⚠️ **Live results (§15 m=video:9 gate PASSED + §16.7 sway validated) supersede
   > several bullets below:** the capture tail is system-memory RGBx → cudaconvert
   > (NOT CUDAMemory-direct — §15.2 Bug 2); the XWayland client is **sway**
   > (gamescope `--backend wayland` drops the connection, §16.3); NVRTC JIT *does*
   > run (`nvrtc: error`=0, covered by `extract-nvrtc.sh` — the "NVRTC moot on this
   > path" hypothesis is FALSE on the validated system-memory path). N-on-N on the
   > sway path + the `--device /dev/dri` CDI-perm fix for multi-GPU hosts remain
   > open (§16.5, §14).
   - **✅ BUILD HALF DONE + VALIDATED 2026-08-08** — the `wayland-display-builder`
     stage is committed to `Dockerfile` (after the `base` stage, before
     `vast-docker`) + builds clean (`docker build --target wayland-display-builder`):
     libwayland 1.23.1 from source → `/usr/local`, the plugin via cargo-c with the
     `cuda` feature → `/out/lib/x86_64-linux-gnu/gstreamer-1.0/libgstwaylanddisplaysrc.so`.
     `gst-inspect-1.0 waylanddisplaysrc` loads it: all 5 properties
     (`render-node`/`cuda-device-id`/`mouse`/`keyboard`/`disable-intel-workaround`)
     + the `video/x-raw(memory:CUDAMemory)` caps present (the cuda feature is
     compiled in). The "CUDA initialization failed" in the no-GPU builder is
     EXPECTED — `libcuda.so` is dlopen'd at runtime (only on a GPU VM, §13.2).
     See §13.9–§13.13 for the build notes. The stage is an ORPHAN (not referenced
     by `vast-vm`) → a normal `docker build .` (target `vast-vm`) does NOT build
     it → no regression to the live image. It builds `gst-cuda-1.0` from the
     `/opt/gstreamer` bundle (§13.1, no separate build). `inputtino` is NOT in
     this stage (phase-A input work, §13.5) — the spike validates Steam via
     gamescope-as-client (XTest), not native-Wayland input.
   - **REMAINING (the live half of the spike):** wire the stage into `vast-vm`
     (`COPY --from=wayland-display-builder /out/.../libgstwaylanddisplaysrc.so`
     + `/usr/local/lib/x86_64-linux-gnu/libwayland-*.so.0*` to a runtime dir on
     `LD_LIBRARY_PATH`, §13.9) + add the entrypoint `DPAD_COMPOSITOR` gate
     (default `gamescope` — no regression). New capture: `waylanddisplaysrc
     render_node=$RENDER_NODE cuda-device-id=$CUDA_ID !
     video/x-raw(memory:CUDAMemory),… ! nvh264enc ! webrtcbin` (Selkies transport
     unchanged — wired via the same `patch_selkies_*.py` build_video_pipeline
     pattern as `pipewiresrc`, §13.12).
   - Add `DPAD_COMPOSITOR=wayland-display` (default stays `gamescope` — no
     regression). New path: `waylanddisplaysrc render_node=$RENDER_NODE
     cuda-device-id=$CUDA_ID ! video/x-raw(memory:CUDAMemory),… ! nvh265enc !
     webrtcbin` (Selkies transport unchanged).
   - Run **Steam** via `gamescope --backend wayland -- steam -gamepadui` as a
     Wayland client of gst-wayland-display. Confirm: stream works, audio works,
     input works (XTest under gamescope-XWayland for phase A).
   - Confirm **N-on-N**: 2 `gst-wayland-display` instances on 1 GPU (raw
     time-slice), both stream. Then 3.
   - Confirm **CUDAMemory zero-copy** engages (`GST_DEBUG=waylanddisplaysrc:5`
     + `nvh265enc:5`; check the caps negotiate `memory:CUDAMemory`; check the
     NVRTC `nvrtc: error` count is 0 *without* the `extract-nvrtc.sh` extraction
     — validates the "NVRTC moot on this path" hypothesis).
   - Confirm the **open driver** EGL init is clean (no #379-style panic) under
     our CDI setup.

3. **Lutris shell under the new compositor + the libSDL3 fix — ~1 day.**
   > ✅ `sdl3-builder` is **DONE + shipped** (§5.6, 2026-08-08). The remaining
   > work is the Lutris-under-**sway** validation (the §5.2 client is sway, not
   > gamescope-wayland). NOT yet validated live.
   - ~~Add the `sdl3-builder` stage (§5.6): build SDL3 from source with minimal
     backends (joystick/hidapi/events), install `libSDL3.so.0` to
     `/usr/lib/x86_64-linux-gnu/` + `ldconfig`. Retires §17.4.~~ ✅ DONE (§5.6).
   - `DPAD_STORE_SHELL=lutris` → `lutris-shell` as a Wayland client of
     gst-wayland-display (try `--ozone-platform=wayland` direct first; fall back
     to **sway's XWayland** if the Electron app needs X — NOT `gamescope --backend
     wayland`, which drops the connection, §16.3).
   - Validate gamepad navigation of the Lutris UI end-to-end with a real
     controller (the bar the evdev path cleared 2026-08-04). Keyboard/mouse via
     Selkies Desktop mode is the fallback while the SDL3 fix lands.

4. **Store launchers under sway (XWayland) — ~1 day.** Battle.net /
   Epic under GE-Proton11-3 via **sway's XWayland** (NOT `gamescope --backend
   wayland -- <launcher>`, which drops the connection, §16.3). Validate the
   §5 Xwayland path captures the launcher window + the game. (This is the real
   multi-store validation — the launchers rendering is the thing gamescope-headless
   could not do.) This is the step that proves multi-store; the Lutris shell from
   step 3 is the picker that gets the user *to* the launcher.

5. **Flip the default — after a parallel-run validation period.**
   `DPAD_COMPOSITOR=wayland-display` becomes the default; `gamescope` (headless)
   stays as a fallback env. Retire gamescope-headless-as-compositor only after a
   full live session on each provider (Helsinki/Gravelines/Des Moines/Quebec/
   Paris) streams clean.

6. **Input migration to inputtino — last.** Phase B (§5.4): inputtino virtual
   gamepads, validated with a real controller to the same bar the evdev path
   cleared (2026-08-04). Retire the 6-layer chain + evdev interposer +
   `libnvenc_fix.so`-adjacent gamepad plumbing only after inputtino is proven.

7. **Vendor `gst-wayland-display`** — pin a tag + vendor into the repo (or a
   pinned submodule) so an upstream break doesn't strand the image. Track
   upstream; contribute the Selkies-webrtcbin integration back.

## 9. What does NOT change

- **The transport:** Selkies `webrtcbin` + coturn + Opus inband FEC + ULP_RED
  video FEC + NACK rtx. The web client. The `play-<id>.dpadplay.com` tunnel /
  direct-IP Caddy. All unchanged.
- **N-on-N / oversubscription:** one container per GPU/slot, CDI per-GPU
  isolation, per-container coturn ports + CPU/mem quotas. MPS optional. The
  host-side story is identical.
- **Volumes + Steam-login persistence:** the install-root-on-volume fix
  (`PROJECT_STATE.md` §4), the per-store volume layout (`STORES-PLAN.md` §9),
  Steam Guard auto-login. All unchanged (the compositor is orthogonal to
  storage).
- **The control plane:** the cloud worker, the bootstrap, the providers, the
  billing, the scheduler. The image-side change ships via the existing
  entrypoint bind-mount hotfix path (`STATUS.md` §4 #19) during the spike, then a
  Docker Hub rebuild for the flip.
- **Proton / Wine:** GE-Proton11-3 + Xwayland for all Windows launchers
  (`STORES-PLAN.md` §4/§5). Unchanged — gamescope-as-client still provides the
  Xwayland the launchers expect.
- **The evdev gamepad path** (shipped 2026-08-05): stays as the default gamepad
  path through phase A of the input migration; inputtino replaces it in phase B
  only after validation.

## 10. Cross-references

- `STORES-PLAN.md` §17 — the live-test findings; §17.3 (the Lutris video-capture
  blocker this retires), §17.4 (the libSDL3 blocker the `sdl3-builder` stage
  fixes — now on the critical path, §5.6, since Lutris is the primary shell),
  retires), §17.5 (the resume plan — this doc supersedes §17.5 #2's "fix the
  Lutris video capture" with the compositor pivot).
- `PROJECT_STATE.md` §6 #10 (NVRTC — likely moot on the new path, kept as
  fallback), #11 (Lutris no-capturable-video — retired by this doc), #12
  (libSDL3 — retired by the `sdl3-builder` stage, §5.6, for the Lutris primary
  path).
- `IMAGE-RUNBOOK.md` — the `DPAD_COMPOSITOR` env + the new `DPAD_VIDEO_SRC`
  semantics land here when built.
- `cloud/docs/STATUS.md` §8 #9 — the control-plane multi-store item; the image-
  side change ships via the entrypoint bind-mount hotfix path (§4 #19) during
  the spike, then a rebuild for the default flip.
- `PROVIDERS.md` §5 — the oversubscription architecture (MPS); the new path
  keeps raw time-slice as the default, MPS optional.
- `games-on-whales/wolf` + `games-on-whales/gst-wayland-display` +
  `games-on-whales/inputtino` — the reference implementations (MIT).

## 11. Resume

```bash
cd dpadplay/container-gaming && git pull
# This doc = the decision + the live-validation log (§13–§16). Current state as
# of §16.9 (2026-08-09, end of session): the compositor pivot is LIVE-VALIDATED
# end-to-end via the sway-as-client fallback (video + audio + interaction on
# an OVH L4); N-on-N 2:1 + 3:1 validated (§16.8); the Lutris Electron shell
# streams VIDEO on the prod tag (§16.9) BUT a stable Lutris session is BLOCKED
# by the sway SIGTRAP (BUG 1, §16.9). The test VM (79.137.11.29) was torn down
# at session end — re-provision via §12 to resume.
#
# DONE + validated:
#  - §8 step 1 probe: DPAD_LUTRIS_DISABLE_GPU=1 did NOT fix §17.3 → pivot
#    strictly necessary.
#  - §5.6 sdl3-builder: SHIPPED (commit af5bda6, image b403937b) + live-validated
#    (sdl_manager "SDL3 initialized! libSDL3.so.0").
#  - §13.14 compositor + EGL + CUDAMemory-capable build: proven on a real L4
#    (render node, no DRM master → N-on-N linchpin holds).
#  - §15 m=video:9 GATE PASSED — waylanddisplaysrc engages inside selkies'
#    webrtcbin at runtime (the §17.3 Lutris-capture blocker is RETIRED).
#  - §16.7 sway-as-client: video + audio + clickable, end-to-end. gamescope
#    --backend wayland DROPS the connection (§16.3) → sway is the path.
#
# CORRECTIONS to the original spec (the validated path differs from §2.2/§4/§5):
#  - Capture tail = system-memory RGBx → cudaupload → cudaconvert (NVRTC JIT
#    runs, nvrtc: error=0, covered by extract-nvrtc.sh) → nvh264enc. NOT
#    CUDAMemory-direct (§15.2 Bug 2 — selkies' static link can't negotiate
#    CUDAMemory-BGRA→nvh264enc). CUDAMemory zero-copy is a §13.3 follow-up.
#  - XWayland client = SWAY (WLR_BACKENDS=wayland), not gamescope-wayland.
#    DPAD_WAYLAND_CLIENT=gamescope|sway gates it (sway is the working one).
#
# NEXT — the remaining §8 phasing (priority order, see §16.5 resume):
#   1. ✅ DONE 2026-08-09 (§18) — Lutris shell under sway (§8 step 3): renders +
#      captures + clickable + gamepad-navigable (libSDL3). The §17.3 blocker is
#      retired for the real Electron shell.
#   2. store-launcher path — DE-RISKED 2026-08-09 (§18, winecfg under sway's
#      Xwayland) + PROBED 2026-08-09 (§16.9): the Lutris Electron shell streams
#      VIDEO on the prod tag (§17.3 retired for the real Electron shell). A
#      stable Lutris session is BLOCKED by the sway SIGTRAP (BUG 1, §16.9). See
#      the STORE-VALIDATION BLOCKER note below for the cheap next test.
#   3. ✅ DONE 2026-08-09 (§18) — gamepad input under sway (§5.4 phase A): the
#      6-layer interposer is compositor-agnostic → the user navigated the Lutris
#      UI with a real controller (SDL3 saw the pads). inputtino migration (§8
#      step 6) is the last, cleaner-but-not-blocking step.
#   4. ✅ DONE 2026-08-09 (§16.8) — N-on-N on the sway path: 2:1 + 3:1 compositor
#      gate validated (3 concurrent sway/wayland-display compositors on 1 L4, all
#      streaming video+audio, 48% GPU / 1.9 GB of 23 GB; raw render-node
#      time-slice, no MPS). The raster cliff (3 active games) is the remaining
#      human-play gate.
#   5. --device /dev/dri CDI-perm fix for prod multi-GPU hosts (§14) — the
#      spike mounts ALL GPUs' /dev/dri; prod needs a scoped render-node mount.
#   6. selkies audio-peer reconnect robustness (§16.7) — stale uid in
#      self.peers; validate browser-refresh / network-blip audio recovery.
#   7. CUDAMemory zero-copy (§13.3 follow-up, non-blocking) — link_pads_full
#      (NO_CAPS_CHECK) or PR #35 NV12 DMABuf→CUDAMemory.
#   8. Flip the control-plane default to DPAD_COMPOSITOR=wayland-display after
#      a parallel-run on all 5 regions (§8 step 5). Keep gamescope-headless as
#      a fallback env. Vendor gst-wayland-display (§8 step 7).
#
# STORE-VALIDATION BLOCKER (§16.9) — the cheap next test: relaunch the Lutris
# shell with the SDL3 gamepad path OFF (LUTRIS_GAMEPAD_UI_ENABLE_SDL_INPUT=0 —
# override the lutris-shell wrapper via DPAD_LUTRIS_SHELL_ARGS or a wrapper edit)
# to see if the SDL3 gamepad path is the sway-SIGTRAP trigger. If sway then stays
# up past 33s → a targeted fix exists (avoid the SDL3 seat-device add/remove);
# if it still crashes → BUG 1 is deeper (a wlroots seat-teardown assert) → needs
# a sway/wlroots version bump or a config to not add the compositor's unused
# wayland input devices. Also fix BUG 3 (entrypoint chown ~/.cache/lutris, the
# §4 .local-class gotcha) + bake legendary/gogdl (the Epic/GOD image-bake gap)
# before the full store validation. gamescope-wayland is NOT a fallback (BUG 2,
# §16.3 drops for Electron too).
#
# Reproducible test: §12 (provision an OVH L4 via createOvhAdapter) + §16.7
# (DPAD_COMPOSITOR=wayland-display DPAD_WAYLAND_CLIENT=sway, browser as the
# FIRST peer — do NOT run selkies-sdp-probe.py first, it pollutes self.peers).
# The 2026-08-09 session's VM (79.137.11.29) was torn down at session end.
```

## 12. Reproducible test-VM provisioning (OVH API, no website)

The 2026-08-08 validation provisioned a raw OVH Gravelines L4 **directly via the
OVH API** (not through the dpadplay website) — the clean way to test an image
change in isolation. The creds + the adapter live in the worker container on
the VPS. From the build host (with VPS SSH access via the orchestrator key):

```bash
# 0. Deploy the read-only ops helper into the worker container (one-time):
scp cloud/scripts/ovh-ops.mjs root@187.124.187.252:/tmp/ovh-ops.mjs
ssh root@187.124.187.252 'docker cp /tmp/ovh-ops.mjs dpadplay-worker-1:/tmp/ovh-ops.mjs'
# Pre-flight (read-only): confirm creds + l4-90 stock + no leftover instance:
ssh root@187.124.187.252 'docker exec dpadplay-worker-1 node /tmp/ovh-ops.mjs time;
  docker exec dpadplay-worker-1 node /tmp/ovh-ops.mjs flavors | grep -A3 l4-90;
  docker exec dpadplay-worker-1 node /tmp/ovh-ops.mjs instances'

# 1. Create the VM via the adapter (run in the worker container; pipe the script
#    to `node -` so it inherits the OVH_* env):
ssh root@187.124.187.252 'docker exec -i dpadplay-worker-1 node -' <<'NODE'
const { createOvhAdapter } = require('/repo/packages/providers/dist/index.js');
(async () => {
  const a = createOvhAdapter({
    appKey: process.env.OVH_APP_KEY, appSecret: process.env.OVH_APP_SECRET,
    consumerKey: process.env.OVH_CONSUMER_KEY, serviceName: process.env.OVH_SERVICE_NAME,
    sshPublicKey: process.env.OVH_SSH_PUBLIC_KEY, image: process.env.OVH_IMAGE,
  });
  const c = await a.createVm({ region:'gravelines', gpuClass:'L4', tier:'standard',
    sshPublicKey: process.env.OVH_SSH_PUBLIC_KEY, label:'dpadtest-spike' });
  console.log('vmId=' + c.vmId);
  const t0=Date.now();
  while (Date.now() < t0+6*60*1000) {
    const v = await a.getVm(c.vmId);
    console.log('status=' + v.status + ' ip=' + (v.publicIp||'(none)'));
    if (v.publicIp) { console.log('READY ip=' + v.publicIp); process.exit(0); }
    await new Promise(r=>setTimeout(r,10000));
  }
  process.exit(2);
})().catch(e=>{ console.error('FATAL '+(e&&e.message||e)); process.exit(1); });
NODE

# 2. SSH to the VM as `ubuntu` with the orchestrator key (decode VAST_SSH_PRIVATE_KEY
#    from cloud/.env to a file, BINARY mode so LF line endings are preserved):
python -c "import base64,os; v=open('cloud/.env').read(); [print(os.path.join(os.path.expanduser('~'),'dpad_orchestrator_key')) or open(os.path.join(os.path.expanduser('~'),'dpad_orchestrator_key'),'wb').write(base64.b64decode(l.split('=',1)[1])) for l in v.splitlines() if l.startswith('VAST_SSH_PRIVATE_KEY=')]"
KEY="$HOME/dpad_orchestrator_key"; chmod 600 "$KEY"   # pubkey must match OVH_SSH_PUBLIC_KEY (dpadplay-orchestrator)
IP=<the-IP-from-step-1>
ssh -i "$KEY" ubuntu@$IP 'nvidia-smi --query-gpu=name,driver_version --format=csv,noheader'

# 3. vm-bootstrap (host setup + pulls the image + MPS) — write the session env
#    to /etc/environment first so the systemd oneshot sees it:
ssh -i "$KEY" ubuntu@$IP 'sudo bash -c "grep -q DPAD_GAMESCOPE /etc/environment 2>/dev/null || echo DPAD_GAMESCOPE=1 >> /etc/environment; grep -q DPAD_STORE_SHELL /etc/environment 2>/dev/null || echo DPAD_STORE_SHELL=lutris >> /etc/environment; grep -q DPAD_SELKIES_BIND /etc/environment 2>/dev/null || echo DPAD_SELKIES_BIND=0.0.0.0 >> /etc/environment"; sudo mkdir -p /opt/dpadcloud; sudo curl -fsSL https://raw.githubusercontent.com/ForcesPT/container-gaming/main/scripts/vm-bootstrap.sh -o /opt/dpadcloud/vm-bootstrap.sh; sudo chmod +x /opt/dpadcloud/vm-bootstrap.sh; sudo /opt/dpadcloud/vm-bootstrap.sh install'
# follow: ssh -i "$KEY" ubuntu@$IP 'sudo journalctl -u dpadcloud-bootstrap -f'
# ...ends with DPAD_VM_READY + the image digest (confirm it matches the push).

# 4. Launch a session container manually (vm-bootstrap leaves the VM warm, 0
#    containers; the worker normally launches via dpad-launch-session):
ssh -i "$KEY" ubuntu@$IP 'sudo docker run -d --name dpad-0 --runtime=nvidia --cap-add SYS_ADMIN --security-opt seccomp=unconfined --security-opt apparmor=unconfined -e NVIDIA_VISIBLE_DEVICES=nvidia.com/gpu=0 --device /dev/uinput --shm-size=2g --ulimit nofile=1048576:1048576 -p 3478:3478/udp -p 16100:16100 -e DPAD_GAMESCOPE=1 -e DPAD_STORE_SHELL=lutris -e DPAD_SELKIES_BIND=0.0.0.0 -e DPAD_TUNNEL=ssh -e DPAD_COTURN_PORT=3478 -e DPAD_TURN_PUBLIC_IP='$IP' -e DPAD_TURN_UDP_EXTERNAL_PORT=3478 -e SELKIES_BASIC_AUTH_USER=dpad -e SELKIES_BASIC_AUTH_PASSWORD=testpass forcespt/dpadcloud-gaming:dpad-SteamOS'
# stream: http://$IP:16100  (login dpad/testpass). logs: sudo docker logs dpad-0

# 5. Tear down (stop billing; OVH removes the boot disk with the instance):
ssh root@187.124.187.252 'docker exec -i dpadplay-worker-1 node -' <<'NODE'
const { createOvhAdapter } = require('/repo/packages/providers/dist/index.js');
(async () => {
  const a = createOvhAdapter({ appKey:process.env.OVH_APP_KEY, appSecret:process.env.OVH_APP_SECRET, consumerKey:process.env.OVH_CONSUMER_KEY, serviceName:process.env.OVH_SERVICE_NAME, sshPublicKey:process.env.OVH_SSH_PUBLIC_KEY, image:process.env.OVH_IMAGE });
  await a.destroyVm('<vmId-from-step-1>');
  console.log('destroyed');
})().catch(e=>{ console.error('FATAL '+(e&&e.message||e)); process.exit(1); });
NODE
ssh root@187.124.187.252 'docker exec dpadplay-worker-1 node /tmp/ovh-ops.mjs instances'   # [] = gone
```

Key facts for the spike: `l4-90` quota=1 (one L4 at a time); image
`Ubuntu 24.04 - NVIDIA - v580` ships the open R580 driver (no driver-swap
reboot — `ensure_driver_580` is a no-op); TCP 16100 + UDP 3478 are open in the
OVH GRA11 security group (Selkies + coturn reach the browser direct); the
orchestrator SSH key (`VAST_SSH_PRIVATE_KEY` in `cloud/.env`, base64 PEM) is
authorized on the VM as `ubuntu` with NOPASSWD sudo.

## 13. Spike build notes (from the 2026-08-08 gst-wayland-display research)

Concrete findings that de-risk §8 step 2 — captured so the spike doesn't
rediscover them.

### 13.1 The gst-cuda build dep is ALREADY in our image
The `cuda` feature of `waylanddisplaysrc` links `gst-cuda-1.0` (GStreamer's CUDA
library — the `CUDAMemory` buffer type + the `cudaupload`/`cudaconvert`
context negotiation). It is **already present in the Selkies GStreamer bundle**
at `/opt/gstreamer` in the `:dpad-SteamOS` image (verified 2026-08-08):
- `libgstcuda-1.0.so.0.2406.0` (+ the SONAME + bare `.so`) at
  `/opt/gstreamer/lib/x86_64-linux-gnu/`
- `gstreamer-cuda-1.0.pc` at `/opt/gstreamer/lib/x86_64-linux-gnu/pkgconfig/`
- `gstreamer-1.0.pc` + `gstreamer-base-1.0.pc` + `gstreamer-plugins-bad-1.0.pc`
  (same pkgconfig dir)
- headers at `/opt/gstreamer/include/gstreamer-1.0`
→ **no need to build gst-plugins-bad cuda from source.** The `wayland-display-
builder` stage just COPYs `/opt/gstreamer` from the `base` stage + builds with
`PKG_CONFIG_PATH=/opt/gstreamer/lib/x86_64-linux-gnu/pkgconfig`. (Do NOT apt-install
`libgstreamer-plugins-bad1.0-dev` — that's the system GStreamer 1.22, not our
1.24.6 bundle; linking it would mismatch the runtime.)

### 13.2 The cuda feature + dynamic CUDA linking landed Sept–Oct 2025
- commit `6593619` (2025-09-29) "feat: added basic cuda and gst-cuda FFI bindings"
- commit `e89d9f5` (2025-10-21) "feat: dynamically link to CUDA" — `libcuda.so`
  is `dlopen`'d at **runtime**, not linked at build time → the builder stage
  does NOT need the CUDA toolkit / `libcuda.so`, only `gstreamer-cuda-1.0.pc`.
→ build from the `stable` branch (or any tag ≥ 2025-10) to get a working
`cuda` feature. Pin a commit/tag in the builder (vendor-risk mitigation, §7).

### 13.3 The exact CUDAMemory pipeline (confirmed from the README + Wolf PR #156)

> ⚠️ **SUPERSEDED by §15.2 Bug 2 (live).** This CUDAMemory-direct pipeline does
> **not** work through selkies' static `Gst.Element.link()` (nvh264enc narrows
> CUDAMemory to NV12/Y444 at static query_caps → no common format with the
> compositor's BGRA). The **validated** capture is system-memory **RGBx** →
> `cudaupload` → `cudaconvert` (NVRTC JIT runs; `nvrtc: error`=0, covered by
> `extract-nvrtc.sh`) → `nvh264enc`. Retained below as the CUDAMemory-zero-copy
> *follow-up* (`link_pads_full(NO_CAPS_CHECK)` or PR #35 NV12 DMABuf→CUDAMemory).

```
waylanddisplaysrc cuda-device-id=$CUDA_ID
  ! video/x-raw(memory:CUDAMemory),width=1920,height=1080,framerate=60/1
  ! nvh264enc (zerolatency, preset p1) → webrtcbin → coturn → browser
```
**No `cudaupload`, no `cudaconvert`, no NVRTC JIT** — the compositor emits
`CUDAMemory` directly via `cuGraphicsEGLRegisterImage` (re-uses Smithay's GL
context). This is the §2.2 win: the §6 #10 NVRTC fix is likely moot on this
path (confirm `nvrtc: error` count = 0 in the spike WITHOUT `extract-nvrtc.sh`).
The `DMABuf` path (the Nvidia fallback `waylanddisplaysrc ! DMABuf ! glupload !
glcolorconvert ! GLMemory ! nvh264enc`) has a known format-negotiation bug on
some drivers (`drm-format=AB24:… in anything we support`, Hotcooler 4070Ti,
PR #156) → **prefer CUDAMemory**; only fall back to DMABuf if CUDAMemory fails.

### 13.4 Zero-copy is production in Wolf (PR #156, merged 2025-06-17)
Big perf wins vs the old system-memory path (from the maintainer's table):
- Nvidia 3070 4K@60: GPU 88%→10%, CPU 185%→14%
- AMD RX 9070 4K@60: GPU 20%→2%, CPU 100%→16%
→ the CUDAMemory path is proven + production. De-risks the spike's
"CUDAMemory zero-copy engages" validation.

### 13.5 Input — inputtino virtual devices, not GStreamer messages (for our case)
`waylanddisplaysrc` takes mouse/keyboard two ways: (a) GStreamer messages
(`MouseMoveRelative`/key structs, the Wolf path) or (b) **`keyboard=`/`mouse=`
properties pointing at `/dev/input/eventN` devices**. inputtino creates virtual
`/dev/input/event*` (uinput/uhid) + `fake-udev` for hotplug → pass them to
`waylanddisplaysrc keyboard=/dev/input/eventN mouse=/dev/input/eventM`. Cleaner
than message-passing for our single-container case (no Wolf-style separate
app container). **inputtino** is at `games-on-whales/inputtino` (build from
source; interface TBD — C++ lib / CLI — needed only for §5.4 phase B gamepad
migration; phase A keeps XTest under gamescope-XWayland, so inputtino is NOT
on the spike critical path). The README fetch was empty — check the repo's
actual build system (likely CMake, C++) before the spike.

### 13.6 We are the first `waylanddisplaysrc → webrtcbin` consumer
Wolf is **Moonlight-only** (`rtpmoonlightpay` custom RTP+FEC). No one drives
`waylanddisplaysrc` into a Selkies `webrtcbin`+coturn sink. The compositor→
GStreamer interface is transport-agnostic (`waylanddisplaysrc` is a generic
source emitting `video/x-raw(memory:CUDAMemory)`), so this is low-risk, but the
spike IS the de-risk. Watch for: webrtcbin caps negotiation with CUDAMemory
(the Moonlight path uses `interpipesink`→`interpipesrc`→`nvh265enc`; we go
`waylanddisplaysrc ! nvh264enc ! webrtcbin` directly — confirm the caps link).

### 13.7 The build-stage approach
Mirror `gamescope-builder`/`sdl3-builder`, but it needs the Selkies GStreamer
(only in the `base` stage). So `COPY --from=base /opt/gstreamer /opt/gstreamer`
into a fresh `wayland-display-builder` stage (FROM nvidia/cuda-base), install
Rust + `cargo install cargo-c`, then:
```bash
git clone --depth 1 https://github.com/games-on-whales/gst-wayland-display.git /tmp/gwd
# pin a tag/commit ≥ 2025-10 for the cuda feature (vendor-risk, §7)
cd /tmp/gwd
export PKG_CONFIG_PATH=/opt/gstreamer/lib/x86_64-linux-gnu/pkgconfig
export PKG_CONFIG_SYSTEM_LIBRARY_PATH=/opt/gstreamer/lib/x86_64-linux-gnu
cargo cinstall --prefix=/out --features cuda   # confirm the feature name in Cargo.toml
# → /out/lib/gstreamer-1.0/libgstwaylanddisplaysrc.so + /out/lib/libgstwaylanddisplay.*
```
Then in `vast-vm`: `COPY --from=wayland-display-builder /out /opt/wayland-display`
+ `GST_PLUGIN_PATH=/opt/wayland-display/lib/gstreamer-1.0` (or copy the .so
into the existing `/opt/gstreamer/lib/x86_64-linux-gnu/gstreamer-1.0/`).

### 13.8 Known issues to watch in the spike (from PR #156 testers)
- **`nvrtcGetCUBINSize` undefined symbol** warning — the NVRTC lib version
  mismatch (adjacent to NVIDIA #1249). Our `extract-nvrtc.sh` bake (§6 #10)
  covers it; on the CUDAMemory path nvrtc may not even load. Confirm.
- **Sway segfault under the nvidia container-toolkit** (alibell, 3090) — fixed
  by the manual nvidia-driver-volume method. We use CDI + the open driver
  (the Scaleway `ensure_driver_580` path) → should be fine, but if `sway` is
  used as the full-desktop client (§5.2) and segfaults, fall back to
  `gamescope --backend wayland` as the XWayland client.
- **Steam Big Picture tripping under sway** (alibell) — fixed by Windowed mode.
  Not our path (Lutris shell, not Steam-as-shell, under the new compositor);
  but the spike's Steam-as-Wayland-client validation (§8 step 2) may hit it.
- **GStreamer 1.24.6 (our bundle) vs 1.26 (Wolf's)** — CUDAMemory works on
  1.24.6 (the cuda library is present), but 1.26 is more battle-tested for
  zero-copy. If the spike hits CUDAMemory caps-negotiation issues, a GStreamer
  1.26 upgrade is the (heavy, risky — §3 AV1 note) fallback.
- **Multi-NVIDIA-GPU** — fixed Nov 2025 (PR #287, the render-node→CUDA-device-id
  mapping). Our N-on-N is one-GPU-per-container (CDI), so this is less relevant,
  but `cuda-device-id=$CUDA_ID` must match the CDI-assigned GPU.

### 13.9 libwayland 1.23 is REQUIRED (build it from source) — VALIDATED
The plugin's `wayland-display-core` depends on `wayland-server` (Rust) with the
`libwayland_1_23` feature, which gates the `set_default_max_buffer_size` /
`wl_client_set_max_buffer_size` APIs. **These are CALLED in code** (not just
extern decls) — confirmed by the `E0599: no method named
set_default_max_buffer_size found for struct DisplayHandle` compile error when
the feature is dropped. So the plugin genuinely needs **libwayland ≥ 1.23**
(those C APIs are `Since: 1.22.90`, released in 1.23.0).

**Ubuntu 24.04 (noble) ships libwayland 1.22 only** (client/cursor/egl; no
`libwayland-server0` installed at all in the base image). So the
`wayland-display-builder` stage builds **libwayland 1.23.1 from source** (meson,
~5 s) → `/usr/local/lib/x86_64-linux-gnu/` (SONAME `libwayland-server.so.0`, real
file `libwayland-server.so.0.23.1`). `PKG_CONFIG_PATH` puts `/usr/local`'s
`wayland-server.pc` (1.23) BEFORE the apt 1.22 one → the plugin links 1.23.
`meson` deps: `libffi-dev` + `libxml2-dev` + `libexpat1-dev` (the scanner uses
expat — the build errors `Dependency "expat" not found` without it) +
`wayland-protocols` (apt noble 1.36 is fine).

> ⚠️ **SUPERSEDED by §13.14 (live):** the prod `:dpad-SteamOS` image already
> ships **libwayland 1.24.0** (a noble backport), so the runtime does **not**
> need the builder's 1.23 `.so` — the 1.23 build is needed only in the BUILDER
> (cuda-base has 1.22). vast-vm needs only the plugin `.so` COPY'd. The text
> below was the pre-validation requirement.

**vast-vm runtime:** the image must SHIP the built libwayland 1.23 `.so` (the
apt 1.22 server lacks the symbols → the plugin fails to load with `undefined
symbol: wl_client_set_max_buffer_size`). Ship `/usr/local/lib/x86_64-linux-gnu/
libwayland-{server,client,cursor,egl}.so.0*` (all 4, for a consistent 1.23 set)
to a dedicated runtime dir (e.g. `/opt/wayland-display/lib`) + put it FIRST on
`LD_LIBRARY_PATH` so it overrides the apt 1.22 set. gamescope bundles its own
wayland so this override is safe; mesa's wayland-egl is backwards-compatible with
1.23. The apt 1.22 `libwayland-client0`/`cursor0`/`egl1` can stay (deps of
other packages) — just shadowed. (Only the server is strictly needed by the
plugin, but a mixed 1.23-server/1.22-client is untested → ship all 4.)

### 13.10 The `cuda` feature must be FORWARDED to wayland-display-core
The plugin crate's `[features] cuda = []` is EMPTY — it does NOT forward to
`wayland-display-core` (whose `cuda = ["dep:libloading"]` enables the CUDA
allocator + the `Command::UpdateCUDABufferPool` / `GstVideoInfo::CUDA` variants
the plugin's `#[cfg(feature="cuda")]` code references). Building the plugin alone
with `--features cuda` → `E0599: no variant UpdateCUDABufferPool` /
`no variant CUDA` compile errors.

**Fix:** `cargo cinstall --features "cuda,wayland-display-core/cuda"` (the
`<dep>/<feature>` syntax activates the dependency's feature). Wolf's own build
(`wolf.Dockerfile`) runs `cargo cinstall --features="cuda"` from the WORKSPACE
ROOT, where cargo feature-unification across the workspace members handles it;
building from the crate dir in isolation requires the explicit forwarding. The
committed stage builds from `gst-plugin-wayland-display/` with the forwarded
feature (validated). The `c-bindings` C-API crate is NOT built (phase-A input,
§13.5).

### 13.11 The exact build deps (the gotchas the spike found)
The `wayland-display-builder` apt line (all `--no-install-recommends`):
- `build-essential pkg-config curl ca-certificates python3 meson ninja-build`
- `libglib2.0-dev` — provides glib/gobject/gmodule (the plugin's `Requires.private`).
  **`libgobject-2.0-dev` / `libgmodule-2.0-dev` are NOT separate Ubuntu 24.04
  packages** — listing them fails `Unable to locate package`.
- `libwayland-dev wayland-protocols` — the wayland-server headers (1.22, for
  the apt fallback) + the protocol XML.
- `libdrm-dev libgbm-dev libegl-dev libgles2-mesa-dev libgl-dev` — Smithay's
  `backend_drm`/`backend_egl`/`backend_gbm` + the `gstreamer-cuda-1.0.pc`
  `Requires` (wayland-client/cursor/egl, x11, glesv2, opengl).
- `libxkbcommon-dev libx11-dev libx11-xcb-dev libxcb1-dev` — Smithay's keyboard/
  X11 paths.
- `libclang-dev` — Smithay's bindgen (drm/gbm/egl FFI).
- `libssl-dev` — **cargo-c links openssl-sys** (without it: `Could not find
  directory of OpenSSL installation` → cargo-c fails to compile).
- `libudev-dev libinput-dev` — Smithay's `backend_libinput`/`backend_udev`; the
  link needs `-ludev -linput` (without libinput-dev: `rust-lld: error: unable to
  find library -linput` at the wayland-display-core link).
- `libffi-dev libxml2-dev libexpat1-dev` — the libwayland 1.23 meson build (§13.9).

Rust: `rustup --default-toolchain stable --profile minimal` (apt rustc is too
old for edition 2024 / rust-version 1.88). `cargo install cargo-c` (latest;
Wolf pins `cargo-c@0.10.23 --locked` + Rust 1.96.0 — both work; the committed
stage uses stable + latest for simplicity, validated).

### 13.12 The install path + the Selkies integration + the socket-discovery bus msg
- **Install path:** cargo-c's `[package.metadata.capi.library] install_subdir =
  "gstreamer-1.0"` puts the plugin at `/out/lib/x86_64-linux-gnu/gstreamer-1.0/
  libgstwaylanddisplaysrc.so` (Debian multiarch `lib/x86_64-linux-gnu`, NOT
  `/out/lib/gstreamer-1.0/`). vast-vm COPYs it to its `gstreamer-1.0/` plugin
  dir + sets `GST_PLUGIN_PATH`.
- **Selkies integration:** mirror the existing `scripts/patch_selkies_pipewire.py`
  (which patches `gstwebrtc_app.py`'s `build_video_pipeline` to add the
  `pipewiresrc` branch gated on `DPAD_VIDEO_SRC=pipewiresrc`). A new
  `patch_selkies_waylanddisplay.py` adds a `waylanddisplaysrc` branch gated on
  `DPAD_COMPOSITOR=wayland-display` (or `DPAD_VIDEO_SRC=waylanddisplaysrc`):
  `waylanddisplaysrc cuda-device-id=$CUDA_ID !
  video/x-raw(memory:CUDAMemory),width=1920,height=1080,framerate=60/1 !
  nvh264enc` — directly into the encoder (no `cudaupload`/`cudaconvert`/NVRTC,
  §2.2). Same idempotent-patch pattern, applied at build time in the Dockerfile.
- **Socket discovery (the §13.6 answer):** `waylanddisplaysrc`'s `start()` posts
  an **`Application` message named `"wayland.src"`** to the GStreamer bus,
  carrying fields from `display.env_vars()` — i.e. `WAYLAND_DISPLAY=wayland-N`
  + the device paths the compositor needs. A bus watch (a small sidecar, or a
  hook in the selkies patch) reads that message → writes `WAYLAND_DISPLAY` to a
  known file (e.g. `/tmp/dpad-wayland-display`) → the entrypoint polls it →
  launches `gamescope --backend wayland -- steam -gamepadui` (or `lutris-shell`)
  as a Wayland client of THAT compositor's socket. (The element has no
  socket-name property — the socket is auto-assigned; the bus message is the
  only way to discover it when the compositor runs inside the selkies pipeline.)
  ⚠️ **SUPERSEDED by §13.14 (live):** a simpler path won — **polling
  `$XDG_RUNTIME_DIR/wayland-*`** for the auto-assigned socket works (the
  compositor creates `wayland-N` + `.lock` there); the entrypoint health loop
  uses polling, not the bus message. The bus-message approach above is retained
  as the alternative.

### 13.13 Spike build — VALIDATED 2026-08-08
`docker build --target wayland-display-builder .` (in `container-gaming`) succeeds:
libwayland 1.23.1 (meson, ~5 s) + the plugin (cargo-c, ~3 min for
wayland-display-core + ~1 min for the plugin) compile + install. `gst-inspect-1.0
waylanddisplaysrc` loads the `.so` against libwayland 1.23 + the /opt/gstreamer
1.24.6 bundle: `Long-name "Wayland display source"`, `Klass "Source/Video"`, all
5 properties present (`render-node`/`cuda-device-id`/`mouse`/`keyboard`/
`disable-intel-workaround`), + the `video/x-raw(memory:CUDAMemory)` caps (the cuda
feature is compiled in). The `CUDA initialization failed: Failed to load CUDA
library` log line is EXPECTED in the no-GPU builder (`libcuda.so` is dlopen'd at
runtime, only on a GPU VM via the nvidia container toolkit, §13.2). The stage is
an orphan (not referenced by `vast-vm`) → no regression to the live image until
it's wired in (the §8 step 2 live half).

### 13.14 LIVE VALIDATION 2026-08-08 — compositor + CUDAMemory + EGL PROVEN on a real OVH L4
Provisioned an OVH Gravelines L4 via the worker's `createOvhAdapter` (vmId
`10f5d05c-…`, IP 164.132.255.195, driver 580.159.03 = open R580; the §12
provisioning pattern). Built a throwaway spike image
`forcespt/dpadcloud-gaming:dpad-SteamOS-wd-spike` = the prod `:dpad-SteamOS`
+ 2 COPY layers (the plugin → `/opt/wayland-display/lib/gstreamer-1.0/`, + the
libwayland 1.23 set → `/opt/wayland-display/lib/`), pushed as a SEPARATE tag so
prod `:dpad-SteamOS` is untouched. Ran (via `--entrypoint sh`, nvidia runtime +
CDI `nvidia.com/gpu=0`, `--device /dev/dri`, `--cap-add SYS_ADMIN`):
```
gst-launch-1.0 waylanddisplaysrc cuda-device-id=0 \
  ! video/x-raw(memory:CUDAMemory),width=1920,height=1080,framerate=60/1 \
  ! nvh264enc ! fakesink sync=false
```
**Results — the core architecture is PROVEN on real L4 hardware:**
- ✅ `CUDA initialization successful` (libcuda via the nvidia runtime).
- ✅ `EGL platform: PLATFORM_DEVICE_EXT on /dev/dri/renderD128` — the **render
  node, NO DRM master** → the N-on-N linchpin (§2.1) holds.
- ✅ `GL Renderer: "NVIDIA L4/PCIe/SSE2"`, `OpenGL ES 3.2 NVIDIA 580.159.03` —
  the **open R580 driver's EGL/GBM glamor works** (NOT the black-screen
  proprietary-driver issue, §5). EGL hardware-acceleration enabled + explicit
  sync (linux-drm-syncobj-v1) engaged.
- ✅ `Creating CUDA buffer (DrmFourcc AR24)` + `Configured CUDA buffer pool` →
  **CUDAMemory zero-copy engages** (no `cudaupload`/`cudaconvert`).
- ✅ `Pipeline is PREROLLED … Setting pipeline to PLAYING` → **nvh264enc inits**
  + the pipeline runs.
- ✅ **NVRTC errors = 0** in the log → the §7 "NVRTC moot on the CUDAMemory
  path" hypothesis is **CONFIRMED** — `extract-nvrtc.sh` (§6 #10) is redundant
  here (the failing element `cudaconvert`'s NVRTC JIT is not in the pipeline).
- ✅ The **wayland socket is created** (`$XDG_RUNTIME_DIR/wayland-1` + `.lock`)
  → client-discovery by polling `$XDG_RUNTIME_DIR/wayland-*` works (§13.12);
  the compositor's auto-assigned socket name is discoverable WITHOUT reading
  the `wayland.src` bus message (a simpler integration path).
- ✅ **libwayland runtime simplification:** the prod `:dpad-SteamOS` image
  already ships **libwayland 1.24.0** (`/lib/x86_64-linux-gnu/libwayland-server.so.0
  → …0.24.0`, a noble backport) — ≥1.23, so it already has
  `wl_client_set_max_buffer_size`. The plugin LOADS against the prod libwayland
  1.24.0 (`ldd` confirms `libwayland-server.so.0 => /lib/x86_64-linux-gnu/…`). So
  the **runtime does NOT need the builder's shipped libwayland 1.23** — the 1.23
  build is only needed in the BUILDER (the cuda-base has 1.22). The vast-vm
  integration simplifies to **just COPY the plugin `.so`** (drop the libwayland
  COPY + the /opt/wayland-display/lib on LD_LIBRARY_PATH); the prod libwayland
  1.24.0 suffices.
- ✅ **gamescope `--backend wayland` WORKS (the earlier "no wayland backend"
  finding was a `grep | head -3` truncation artifact — retracted):** the gamescope
  build's `--backend` help lists `wayland` (unconditional — `meson_options.txt` has
  no `wayland_backend` feature; `parse_backend_name`/`CWaylandBackend` are ungated
  in `main.cpp`). Live-confirmed on the OVH L4: `gamescope --backend wayland -W
  1920 -H 1080 -- sleep 30` with `WAYLAND_DISPLAY=wayland-1` (the compositor's
  socket) logged `[gamescope] xdg_backend: Post-Initted Wayland backend` +
  `wlserver: Running compositor on wayland display 'gamescope-0'` + stayed
  RUNNING. So gamescope connects to gst-wayland-display as a Wayland client,
  renders to it, + runs its own wlserver/Xwayland for the child app — exactly
  the §4/§5.2 model. **No gamescope rebuild OR sway needed.** (gamescope also
  auto-selects the wayland backend when `WAYLAND_DISPLAY` is set, so explicit
  `--backend wayland` is optional.) gamescope's `pipewire: pw_context_connect
  failed` log is its OWN capture pipewire (harmless — the compositor captures
  gamescope; gamescope's pipewire is unused on this path).
- ⚠️ **Container `/dev/dri` perms gotcha:** the first probe panicked at
  `comp/mod.rs:741 PermissionDenied` — the CDI-injected `/dev/dri` nodes have
  group perms (`card0 root:video`, `renderD128 root:992`) the container user
  couldn't open r/w. Fix: pass `--device /dev/dri` explicitly on the `docker
  run` (r/w). The entrypoint `DPAD_COMPOSITOR` gate / `dpad-launch-session` must
  include `--device /dev/dri` (the existing gamescope path uses CDI's `/dev/dri`
  via `NVIDIA_VISIBLE_DEVICES=nvidia.com/gpu=0`, which has the same group-perms
  issue — but the gamescope path opens the render node via the nvidia ICD, not
  raw `/dev/dri` open, so it didn't hit this; gst-wayland-display opens
  `/dev/dri/renderD128` directly via `EGL_EXT_device_drm_render_node`).
- ⚠️ **gamescope Xwayland socket gotcha:** gamescope's Xwayland setup checks
  `/tmp/.X11-unix` is owned by root or the gamescope user; a stale/wrong-owned
  dir makes gamescope die (`/tmp/.X11-unix not owned by root or us`). The
  entrypoint gate must pre-create it (`rm -rf /tmp/.X11-unix; mkdir -p
  /tmp/.X11-unix; chown root:root /tmp/.X11-unix; chmod 1777 /tmp/.X11-unix`;
  or run gamescope as the `dpad` user with the dir owned accordingly).
- ⚠️ **selkies-gstreamer `pynput` needs an X display at import** (`Can't connect
  to display :0` → selkies fails to start). The gamescope-headless path has
  gamescope's Xwayland :0 up before selkies; the wayland path starts selkies
  FIRST (the compositor), so a dummy Xvfb (e.g. `:99`) is needed for pynput to
  import. selkies' pynput/XTest input then targets the dummy, NOT gamescope's
  Xwayland → **input routing is the §5.4 follow-up** (compositor input /
  inputtino, not pynput/XTest). The VIDEO path is unaffected.
- ⚠️ **selkies builds the video pipeline only on a peer's video request** — so
  the waylanddisplaysrc compositor (inside selkies' `build_video_pipeline`)
  starts only when a WebRTC peer connects + asks for video. Validating the
  selkies patch live (the `m=video:2` metric, §17.3) needs a WebRTC peer (a
  headless client like aiortc, or a real browser). The standalone-compositor
  probe above (gst-launch + gamescope-as-client) bypasses this + proves the
  compositor+client+capture directly.

**Net: §8 step 2's compositor + capture + gamescope-as-client are DONE +
live-validated on a real OVH L4.** The wayland-display-builder stage is
committed (orphan) + builds; the plugin ships in vast-vm (`dpad-SteamOS-wd`
spike tag — prod `:dpad-SteamOS` untouched) + the selkies
`patch_selkies_waylanddisplay.py` (the `waylanddisplaysrc` branch, §13.12) is
written + applied + builds. Live: compositor on the render node (EGL/CUDAMemory,
NVRTC=0) → wayland socket → gamescope `--backend wayland` connects + renders
("Post-Initted Wayland backend") → compositor captures. **Remaining:** the
entrypoint `DPAD_COMPOSITOR` gate (start selkies with waylanddisplaysrc → poll
for the wayland socket → launch `gamescope --backend wayland -- <shell>` with
`WAYLAND_DISPLAY`, incl. the dummy-Xvfb-for-pynput + the /tmp/.X11-unix +
`--device /dev/dri` fixes) + the live selkies `webrtcbin` peer test (the
`m=video:2` browser-stream validation — needs a WebRTC peer) + N-on-N. VM torn
down after the probe (`adapter.destroyVm`, 0 leftover instances, no orphan billing).

## 14. The entrypoint `DPAD_COMPOSITOR` gate — implementation (2026-08-08)

> **The implementation of §8 step 2's remaining half** (the entrypoint integration
> + the live selkies `webrtcbin` validation path). The compositor + capture +
> gamescope-as-client were live-proven via `gst-launch` in §13.14; this section
> covers the entrypoint gate that wires them into the real session boot + the
> probe script that validates the runtime selkies patch (the unvalidated-at-
> runtime `patch_selkies_waylanddisplay.py` branch). **Status: IMPLEMENTED,
> pending live validation.**

### 14.1 The central design problem (confirmed from the selkies source)

Traced in selkies-gstreamer v1.6.2 `__main__.py:654`: `app.start_pipeline()` is
called from `on_session_handler`, wired to `signalling.on_session` — **selkies
builds the video pipeline (and thus the `waylanddisplaysrc` compositor) ONLY
when a WebRTC peer establishes a session.** This inverts today's boot order:

| | Today (gamescope-headless) | After (wayland-display) |
|---|---|---|
| 1st | gamescope launches + Steam renders | **selkies launches** (listening, no compositor yet) |
| 2nd | selkies captures gamescope's PipeWire | **a peer connects** → selkies builds the pipeline → `waylanddisplaysrc` starts the compositor → `wayland-N` socket appears |
| 3rd | — | **gamescope launches** `--backend wayland` as a client of `wayland-N` |
| DPAD_READY | after selkies is streaming + gamescope up | **after selkies is listening** (before gamescope — it can't launch until a peer connects) |

**Consequence for the control plane:** DPAD_READY fires when selkies is
*listening* (not when gamescope is up). The worker marks the session ready →
sets up the stream-bridge → the user's browser connects → the compositor starts
→ gamescope launches → video appears ~30-40s later (GFN-like). A loading
indicator is a prod-flip polish item; for the spike the browser shows
"Waiting for stream" during the gamescope boot window (acceptable — it
self-heals when gamescope renders).

**Three options were considered; (A) was chosen** (accept peer-connects-first,
no selkies patch beyond the committed `patch_selkies_waylanddisplay.py`):
- **(A) Accept peer-connects-first [CHOSEN].** DPAD_READY = selkies listening.
  The entrypoint polls `$XDG_RUNTIME_DIR/wayland-*` + launches gamescope once
  the socket appears. Matches §5.2/§11.
- **(B) Patch selkies to build the pipeline eagerly on startup.** Invasive
  (`start_pipeline()` creates webrtcbin + the data channel + sets PLAYING with
  no peer; re-negotiation when a real peer connects is fragile). Rejected.
- **(C) A headless aiortc "trigger peer" inside the container.** Complex, heavy
  dep, disconnect may tear down the pipeline. Rejected.

### 14.2 What was implemented (3 files)

**`entrypoint.sh`** — 2 changes:
1. **Extracted `setup_gamepad_interposer()`** from the inline gamepad if/else
   block in `start_gamescope_session` (~60 lines). Sets globals `DPAD_PRELOAD`,
   `SDL_GP_ENV`, `SELKIES_INTERPOSER`, `LD_PRELOAD`, `SDL_GAMECONTROLLERCONFIG`
   + starts the hotplug watcher (classic) / `evdev_bridge.py` (evdev) daemon.
   Called after `setup_nvenc_fix` (reads `NVENC_FIX_ENABLED`). **Shared by both
   session functions** so the gamescope-headless + wayland-display paths get
   identical gamepad wiring. The inline block in `start_gamescope_session` is
   now a one-line `setup_gamepad_interposer` call — zero behavior change.
2. **Added `start_wayland_display_session()`** — the new session function,
   gated on `DPAD_COMPOSITOR=wayland-display` (default `gamescope` = the
   unchanged headless path, **zero regression**). It mirrors
   `start_gamescope_session`'s shared prep (input hotfix, resolution, shell app,
   `setup_user_volume`, `bootstrap_steam_on_xvfb`, PipeWire + pipewire-pulse +
   null sink, `setup_nvenc_fix`, `setup_gamepad_interposer`) then does the new
   wayland-display-specific boot:
   - Pre-creates `/tmp/.X11-unix` (root:root 1777) — §13.14 gamescope Xwayland
     gotcha.
   - Starts a **dummy `Xvfb :99`** for pynput to import (selkies' pynput needs
     an X display at import; the compositor has no X server, §13.14).
   - Starts coturn + builds `rtc_config.json` (mirrors `start_gamescope_stream`).
   - **Launches selkies FIRST** with `DPAD_VIDEO_SRC=waylanddisplaysrc` +
     `DISPLAY=:99` + `DPAD_STREAM_WIDTH/HEIGHT` (the patch reads these for the
     CUDAMemory caps). Fires `DPAD_READY` once selkies is listening (NOT after
     gamescope — see §14.1).
   - **Health loop polls `$XDG_RUNTIME_DIR/wayland-*`** for the compositor
     socket (appears when a peer connects → selkies builds the pipeline →
     `waylanddisplaysrc` starts). On the socket appearing → launches
     `gamescope --backend wayland -e -W GS_W -H GS_H -- ${SHELL_APP}` with
     `WAYLAND_DISPLAY=<socket>` (a nested `_launch_gs_wayland()` helper, reused
     for the initial launch + the restart-on-death path). Supervises: gamescope
     restart (if it dies + the socket is still there), selkies restart (the
     compositor dies with it → `gs_launched=0` → wait for the new socket),
     `evdev_bridge.py` supervisor (evdev mode).

   The gate at the `DPAD_GAMESCOPE` block:
   ```bash
   if [ "${DPAD_COMPOSITOR:-gamescope}" = "wayland-display" ]; then
       start_wayland_display_session
   else
       start_gamescope_session
   fi
   ```

**`scripts/dpad-launch-session`** — 2 changes:
1. **`--device /dev/dri`** (gated on `DPAD_COMPOSITOR=wayland-display`) — the
   compositor opens the DRM render node directly via
   `EGL_EXT_device_drm_render_node`; the CDI-injected `/dev/dri` group perms
   block that raw open (§13.14). Gated so the gamescope-headless path (default)
   is untouched (CDI's `/dev/dri` via `NVIDIA_VISIBLE_DEVICES` suffices there,
   where gamescope opens the render node via the nvidia ICD, not a raw open).
   ⚠️ Prod N-on-N on multi-GPU hosts: `--device /dev/dri` mounts ALL GPUs'
   `/dev/dri` (breaks CDI per-GPU isolation) — for the spike (single L4, 1:1
   then 2:1 MPS) it's safe; the prod-flip needs a CDI-perm fix instead.
2. **Forwards `-e DPAD_COMPOSITOR` + `-e DPAD_STREAM_WIDTH` (default 1920) +
   `-e DPAD_STREAM_HEIGHT` (default 1080)** — the selkies patch reads the
   latter for the CUDAMemory BGRA caps (the compositor's output WxH@framerate).

**`scripts/wayland-display-probe.sh`** (new) — the Step 2a probe launcher. Run
ON THE VM (after `vm-bootstrap.sh install`) as root: `VM_IP=<ip> bash
/opt/dpadcloud/wayland-display-probe.sh`. Launches a probe container with
`DPAD_COMPOSITOR=wayland-display` + `DPAD_GAMESCOPE=1` + the right flags (CDI,
`--device /dev/dri`, coturn+selkies ports), waits for `DPAD_READY`, then prints
the validation checklist (open the browser → watch for the "Compositor socket
appeared" log → the gate: `m=video:2` in the SDP + Steam renders, not black).
Env: `IMAGE` (use `dpad-SteamOS-wd-spike` for the spike tag), `SHELL` (steam
default; `lutris` validates the §17.3 Lutris capture fix), `EXTRA_ENV`.

### 14.3 Risks retired by reading the source (before writing the gate)

1. **`self.gpu_id` in the selkies patch is real.** selkies-gstreamer v1.6.2
   `__init__(…, gpu_id=0, …)` → `self.gpu_id = gpu_id` (line 89). The patch's
   `if self.gpu_id >= 0: set_property("cuda-device-id", self.gpu_id)` is valid.
   selkies' `--gpu_id` defaults to 0 (single-GPU-per-container via CDI → 0 is
   correct). ✅
2. **The patch's assembly anchor matches.**
   `pipeline_elements += [cudaupload, cudaconvert, cudaconvert_capsfilter,
   nvh264enc, …]` is at `gstwebrtc_app.py:944` verbatim. The patch applies. ✅
3. **The plugin is in the default `/opt/gstreamer/.../gstreamer-1.0/` dir** —
   selkies' `gst-env` already puts that on `GST_PLUGIN_PATH`. No extra path
   config. ✅

### 14.4 The validation gate (Step 2a — the live probe)

The §13.14 live validation proved the compositor + CUDAMemory + EGL + gamescope-
as-client via `gst-launch` (a standalone GStreamer pipeline, NOT through
selkies). The **unvalidated** part is: does selkies' `waylanddisplaysrc` branch
(the `patch_selkies_waylanddisplay.py` patch) work when a WebRTC peer connects
+ selkies builds the pipeline? The probe (`scripts/wayland-display-probe.sh`)
tests exactly this:

1. Provision a fresh OVH Gravelines L4 via the §12 API pattern (open R580,
   `l4-90` quota=1).
2. `vm-bootstrap.sh install` (pulls the image + host setup + fetches the new
   entrypoint from repo `main` via the bind-mount hotfix path).
3. `VM_IP=<ip> bash /opt/dpadcloud/wayland-display-probe.sh` (or `docker run`
   directly with `DPAD_COMPOSITOR=wayland-display`).
4. Open `http://$VM_IP:16100` (login dpad/testpass) in a browser.
5. **GATE:** `docker logs wd-probe 2>&1 | grep -E 'm=video|waylanddisplaysrc|nvrtc: error'`
   - `m=video:2` = video track negotiated (**SUCCESS** — the §17.3 Lutris-capture
     bug is retired; the pivot works at runtime).
   - `m=video:0` = no video track (the pivot did NOT fix §17.3 — investigate
     the selkies patch's caps negotiation with `GST_DEBUG=waylanddisplaysrc:5`).
   - `nvrtc: error` count = 0 (confirms NVRTC is moot on the CUDAMemory path,
     §13.14 — `extract-nvrtc.sh` is redundant here).
   - The browser shows Steam Big Picture (not black) within ~30-40s.

If the probe passes → proceed to N-on-N (2 compositors on 1 L4 via MPS) → then
§8 step 3 (Lutris shell under the new compositor). If it fails → fix the selkies
patch in isolation (the `patch_selkies_waylanddisplay.py` branch's caps
negotiation with `webrtcbin` — §13.6 flagged this as the one unproven seam; we
are the first `waylanddisplaysrc → webrtcbin` consumer).

### 14.5 What is NOT touched in this pass (deferred, per §8 phasing)

- **Input routing under the new compositor** (§5.4 phase A) — pynput/XTest
  targets the dummy `:99`; XTest-to-gamescope-Xwayland needs `DPAD_INPUT_DISPLAY`
  set *after* gamescope launches (dynamic re-target or a selkies restart). The
  spike validates VIDEO only; keyboard/mouse via Selkies Desktop mode is the
  fallback. Gamepad works (the interposer is shell-agnostic, §6).
- **Lutris shell under the new compositor** (§8 step 3) — once 2a proves Steam
  streams, validate `DPAD_STORE_SHELL=lutris` with `--ozone-platform=wayland`
  direct (native Wayland) or via gamescope-XWayland. `libSDL3` already shipped
  (§5.6) so gamepad nav works.
- **Store launchers** (§8 step 4), **default flip** (§8 step 5),
  **inputtino migration** (§8 step 6), **vendoring gst-wayland-display** (§8
  step 7).
- **The prod Docker Hub rebuild.** The entrypoint gate ships via the
  **entrypoint bind-mount hotfix path** (vm-bootstrap fetches `entrypoint.sh`
  from repo `main` — gotcha #19) so a fresh VM gets it without a rebuild. The
  plugin `.so` + the selkies patch ARE baked into the image (Dockerfile:812 +
  818-820); the spike tag `dpad-SteamOS-wd-spike` has them. Prod `:dpad-SteamOS`
  also has them (committed in `96d8442`). So no rebuild is needed for the probe
  — just `docker pull` + the entrypoint hotfix.

### 14.6 Resume

```bash
cd dpadplay/container-gaming && git pull
# §14 IMPLEMENTED (entrypoint gate + dpad-launch-session + probe script).
# bash -n entrypoint.sh OK + bash -n scripts/dpad-launch-session OK + bash -n scripts/wayland-display-probe.sh OK
#
# NEXT — the Step 2a live probe (§14.4):
# 1. Provision an OVH Gravelines L4 (§12 pattern; createOvhAdapter from the worker container).
# 2. vm-bootstrap.sh install (pulls the image + fetches the new entrypoint from main).
# 3. VM_IP=<ip> bash /opt/dpadcloud/wayland-display-probe.sh
#    (or: docker run -e DPAD_COMPOSITOR=wayland-display -e DPAD_GAMESCOPE=1 ... — the entrypoint does the rest)
# 4. Open http://$VM_IP:16100 -> watch 'docker logs -f wd-probe' -> GATE: m=video:2 + Steam renders.
# 5. If pass -> N-on-N (2 compositors on 1 L4 via MPS) -> §8 step 3 (Lutris shell).
# 6. Teardown: docker rm -f wd-probe; adapter.destroyVm (§12 step 5).
#
# Open questions to resolve during the probe (§14.1):
# - Does selkies tolerate the ~30s gap between peer-connect + first video frame
#   (while gamescope boots)? If webrtcbin times out, patch selkies to delay the
#   offer or send a black frame first.
# - Socket discovery: polling $XDG_RUNTIME_DIR/wayland-* (§13.14 confirmed it
#   works). Fallback: the wayland.src GStreamer bus message (§13.12).
```

## 15. Step 2a LIVE-VALIDATED 2026-08-08 — m=video:9 GATE PASSED + 2 selkies-patch bugs found + fixed

> **The §14.4 probe gate PASSED on a real OVH Gravelines L4.** The
> gst-wayland-display compositor engages inside selkies' `webrtcbin` pipeline
> at runtime — the §17.3 Lutris-capture blocker is RETIRED. Two real selkies-
> patch bugs (invisible to the §13.14 `gst-launch` probe, which uses dynamic
> negotiation) were found + fixed by live-probing the actual GStreamer pad caps
> at the failing `Gst.Element.link`. Commit `2170019`; image pushed
> `forcespt/dpadcloud-gaming:dpad-SteamOS` digest `aaa880f2`. **VM torn down**
> (no orphan, billing stopped).

### 15.1 What the live probe proved (the full inverted boot order)

Provisioned an OVH Gravelines L4 (`c92c5b67-…` @ `164.132.255.146`, open R580,
`l4-90` quota=1) via the §12 API pattern. `vm-bootstrap.sh install` →
`DPAD_VM_READY` (fresh image pull). Ran the probe container
(`DPAD_COMPOSITOR=wayland-display DPAD_GAMESCOPE=1 DPAD_STORE_SHELL=steam`),
waited for `DPAD_READY`, then connected a headless signaling probe
(`scripts/selkies-sdp-probe.py`) AS peer 1 (the selkies app actively calls
`SESSION 1`; the browser is peer 1 — §15.3 below). The full inverted boot order
ran end-to-end:

1. Entrypoint `start_wayland_display_session`: PipeWire + pipewire-pulse +
   gamepad interposer → coturn → **selkies FIRST** with
   `DPAD_VIDEO_SRC=waylanddisplaysrc` + `DISPLAY=:99` (dummy Xvfb for pynput
   import) → `DPAD_READY slot=0 bind=0.0.0.0:16100 encoder=nvh264enc`
   (selkies **listening**, compositor NOT yet up).
2. The probe connected as peer 1 (HELLO + the app's `SESSION 1`) → selkies'
   `on_session` → `start_pipeline()` → `build_video_pipeline()` instantiated
   `waylanddisplaysrc` → `gstwaylanddisplaysrc: CUDA initialization successful`
   → the compositor created `wayland-1` in `$XDG_RUNTIME_DIR`.
3. The entrypoint health loop detected `wayland-1` →
   `[*] Compositor socket wayland-1 appeared (peer connected) — launching
   gamescope --backend wayland -- steam -gamepadui`.
4. The probe received the SDP offer:
   **`m=video 9 UDP/TLS/RTP/SAVPF 97 96`** → `m=video:9` (a non-zero port = a
   video track was negotiated) → **GATE PASSED** (vs `m=video:0` for the broken
   Lutris-under-gamescope-headless case, §17.3).

`m=video:9` is the §17.3 gate — the waylanddisplaysrc compositor engages
inside selkies at runtime. The §17.3 Lutris-capture blocker is RETIRED: the
pivot works. `nvrtc: error` count = 0 in the log (NVRTC JIT ran clean on the
cudaconvert path; `extract-nvrtc.sh` covered it). `Supported DMA formats: []`
in the log is the compositor's empty DMABuf list (harmless — we use the RGBx
path, not DMABuf; §15.2 #2).

### 15.2 The two selkies-patch bugs (found + fixed by live-probing the pad caps)

The §13.14 `gst-launch` probe (compositor + gamescope-as-client via a
standalone GStreamer pipeline) worked because `gst-launch` uses **dynamic**
caps negotiation at PLAYING. Selkies uses **static** `Gst.Element.link()`
before PLAYING — which exposed two bugs invisible to §13.14.

A debug-patch (`scripts/dbg-patch-link.py`, run live on the container) printed
the actual pad `query_caps` + the capsfilter's `caps` property at each link
attempt, revealing the mismatches.

**Bug 1 — the idempotency check skipped the source-branch insertion.**
`patch_selkies_waylanddisplay.py`'s idempotency marker was
`WAYLAND_MARK = 'os.environ.get("DPAD_VIDEO_SRC", "") == "waylanddisplaysrc"'`
— a string that ALSO appears in the assembly branch + the `set_framerate`
guard. So on the second+ build the check matched → the patch **skipped the
source-branch insertion** → `waylanddisplaysrc` was never created → the
pipeline fell through to `else: ximagesrc` → the compositor never ran. The
container log showed `CUDA initialization successful` (a stale §13.14
leftover) but the link failed because the source element was `ximagesrc`, not
`waylanddisplaysrc`. **Fix:** a source-branch-specific marker,
`SOURCE_MARK = 'Gst.ElementFactory.make("waylanddisplaysrc", "x11")'` (the
element-creation line, which only the source branch has).

**Bug 2 — the CUDAMemory-zero-copy assumption was WRONG for selkies' static
link.** The §2.2/§13.3 thesis was "waylanddisplaysrc emits CUDAMemory BGRA
directly → skip cudaupload/cudaconvert → link waylanddisplaysrc → nvh264enc."
The live pad-caps dump showed:
- `capsfilter0` (waylanddisplaysrc's capsfilter) src caps:
  `video/x-raw(memory:CUDAMemory), format={BGRA, RGBA}`
- `nvenc` sink query_caps (static, at link time): `video/x-raw(memory:CUDAMemory),
  format={NV12, Y444}` (NOT BGRA)
- → **no common format** → `Failed to link capsfilter0 -> nvenc`.

`nvh264enc`'s pad *template* lists BGRA, but its *static* `query_caps`
(restricting the format set once the encoder is configured) narrows CUDAMemory
to `{NV12, Y444}` before PLAYING. The §13.14 `gst-launch` worked because
`gst-launch` defers caps negotiation to PLAYING (dynamic), where the encoder's
runtime query accepts BGRA. Selkies' `Gst.Element.link()` does a static
accept-caps check → fails. **Fix:** use **system-memory RGBx**
(waylanddisplaysrc's other src-pad template) + the original
`cudaupload → cudaconvert(BGRx→NV12) → cudaconvert_capsfilter(CUDAMemory,NV12)
→ nvh264enc` path — the validated encode tail that ximagesrc/pipewiresrc use.
NVRTC JIT runs (the `extract-nvrtc.sh` bake covers it). CUDAMemory zero-copy
is now a **§13.3 follow-up**: either `link_pads_full` with a no-caps-check flag
(Gst.PadLinkCheckTypes.NO_CAPS), OR PR #35's NV12 DMABuf→CUDAMemory path (the
compositor does RGB→NV12 itself + `dmabuftocuda` imports to CUDAMemory at the
encoder). Both bypass the static-caps mismatch.

**Bug 3 (adjacent) — `set_framerate` clobbered the waylanddisplaysrc caps.**
`patch_selkies_pipewire.py`'s `set_framerate` (called from the browser FPS
slider, but also reachable during pipeline build) had an `else:` branch that
overwrote `self.ximagesrc_caps` with `video/x-raw` (system memory, NO
CUDAMemory/RGBx) → re-broke the link even after the source branch was fixed.
**Fix:** added an `elif os.environ.get("DPAD_VIDEO_SRC", "") ==
"waylanddisplaysrc": pass` guard so the else branch doesn't clobber.

### 15.3 The signaling-probe insight (why the first attempts got no SDP)

The first probe attempts sent `SESSION 1` themselves — **backwards**. selkies-
gstreamer's `__main__.py` (traced in the v1.6.2 source): the **app** connects
as `my_id=0` (video) + `my_id=2` (audio) and ACTIVELY calls `SESSION 1` /
`SESSION 3` — it waits for a **browser peer 1** (video) + peer 3 (audio) to
connect. So the probe must connect **as peer 1** and WAIT for the app to call
it (do NOT send SESSION). The `signaling.on_session` callback fires on
`SESSION_OK` → `on_session_handler` → `app.start_pipeline()` → the offer is
generated by webrtcbin's `on-negotiation-needed` + relayed to peer 1. The
fixed `scripts/selkies-sdp-probe.py` does exactly this + parses the relayed
`{"sdp":{"type":"offer","sdp":"..."}}` JSON for the `m=video` line.

### 15.4 The remaining live half — gamescope `--backend wayland` died

The compositor→selkies→webrtcbin pipeline is proven (the gate). gamescope
`--backend wayland -- steam -gamepadui` launched (the entrypoint's
`_launch_gs_wayland` detected `wayland-1` + fired), but **died shortly after**
(the health loop logged `WARNING: gamescope died — restarting...` then retried).
This is the §13.14 caveat verbatim: *"gamescope `--backend wayland` (run as a
Wayland client) is less battle-tested than `--backend headless`... the
games-on-whales maintainers note gamescope 'may be unstable with some Nvidia
driver versions'."* The gamescope-as-client stability is the **next layer**;
it does NOT invalidate the compositor+capture pipeline (which is the §17.3
gate that just passed). The §13.14 fallback applies: if `gamescope --backend
wayland` is flaky, use **sway as the Wayland client** (sway provides XWayland
too) — same compositor capture, different XWayland provider.

### 15.5 Resume (the next layer — gamescope-as-client stability)

```bash
cd dpadplay/container-gaming && git pull
# §15 VALIDATED (commit 2170019, image aaa880f2):
#   m=video:9 GATE PASSED — the waylanddisplaysrc compositor engages in selkies
#   at runtime (the §17.3 Lutris-capture blocker is RETIRED).
#   The two selkies-patch bugs (idempotency + CUDAMemory static-link) are FIXED.
#
# NEXT — gamescope --backend wayland stability (§15.4):
# 1. Provision a fresh OVH L4 (§12 pattern). vm-bootstrap.sh install.
# 2. VM_IP=<ip> SHELL=steam bash /tmp/wayland-display-probe.sh
# 3. Connect a peer (browser at http://$VM_IP:16100 OR scripts/selkies-sdp-probe.py).
# 4. Watch 'docker logs -f wd-probe' for the gamescope death:
#    - tail -50 /tmp/gamescope-steam.log (gamescope's own log) for the crash.
#    - GST_DEBUG=gamescope:5 in the gamescope launch (the _launch_gs_wayland line)
#      to see the Wayland-backend error (EGL init? surface creation? Xwayland?).
# 5. If gamescope --backend wayland is flaky on R580, try the §13.14 fallback:
#    sway as the Wayland client (sway provides XWayland; the compositor still
#    captures it). Add a DPAD_WAYLAND_CLIENT=gamescope|sway gate.
# 6. Once gamescope/sway stays up + Steam renders, the full multi-store path is
#    unblocked: §8 step 3 (Lutris shell) → §8 step 4 (store launchers).
#
# CUDAMemory zero-copy (§13.3 follow-up, NOT blocking): swap the RGBx capture
# path for link_pads_full(no-caps-check) OR PR #35 NV12 DMABuf->CUDAMemory.
```

## 16. Browser-test session 2026-08-08 — 2 more bugs found (1 fixed), gamescope-wayland client drops

> **Followed up the §15 validation by opening the browser path + diagnosing why
> gamescope `--backend wayland` died.** Found + fixed a second EGL-vendor bug
> (the gamescope-as-client crash was NOT the §15.4 Nvidia-driver caveat — it was
> the Mesa EGL vendor override leaking into the wayland-client launch). After
> the fix, gamescope gets through Wayland-backend init + Xwayland + Steam launch,
> THEN hits the genuine §13.14 gamescope-wayland-client connection-drop
> (`IWaitable hung up`), which is the remaining layer. Commit `21dfb1e`. **VM
> torn down** (no orphan, billing stopped).

### 16.1 The browser-test result (with the open driver)

Reprovisioned a fresh OVH Gravelines L4 (`dba62614-…` @ `91.134.95.115`).
The first gamescope crash log showed the **exact `PROJECT_STATE.md` §5 EGL
failure**:

```
libEGL warning: pci id for fd 7: 10de:27b8, driver (null)
libEGL warning: egl: failed to create dri2 screen
[gamescope] Error: waitable: IWaitable hung up. Aborting.
```

**Initial (wrong) hypothesis:** OVH's `Ubuntu 24.04 - NVIDIA - v580` ships the
**proprietary** 580 (`nvidia-dkms-580` / `nvidia-driver-580`, `license: NVIDIA` —
NOT `-open`), the same black-screen class as Scaleway §5. So I installed
`nvidia-driver-580-open` + rebooted → the open kernel module loaded
(`license: Dual MIT/GPL`, `580.178.04`). **But the crash persisted** — so it
was NOT the proprietary-vs-open variant (unlike Scaleway). The open driver is
still the right choice (the compositor's EGL/GBM glamor needs it), but it was
not the gamescope crash cause.

### 16.2 The real bug — the Mesa EGL vendor override leaked into gamescope (FIXED)

The container's `eglinfo` with the NVIDIA ICD forced worked perfectly
(`EGL vendor: NVIDIA`, `renderer: NVIDIA L4`). But gamescope's launch did NOT
force it → Mesa EGL got picked → `driver (null)`. Root cause: the entrypoint's
Xvfb path exports `__EGL_VENDOR_LIBRARY_FILENAMES=50_mesa.json` globally (so
Xvfb doesn't segfault on NVIDIA EGL GBM) — + the wayland-client gamescope
launch (`_launch_gs_wayland`) inherited it. Mesa EGL can't match the L4 PCI id
→ `failed to create dri2 screen` → Steam's CEF can't init → gamescope aborts.

**Fix (commit `21dfb1e`):** in `_launch_gs_wayland`, `unset
__EGL_VENDOR_LIBRARY_FILENAMES` + force the NVIDIA EGL vendor
(`__EGL_VENDOR_LIBRARY_FILENAMES=/usr/share/glvnd/egl_vendor.d/10_nvidia.json`).
The open R580 EGL/GBM glamor path works off the render node (§13.14 confirmed
EGL init). Ships via the entrypoint bind-mount hotfix path (no image rebuild —
vm-bootstrap fetches entrypoint.sh from `main`). **Validated:** after the fix
the `libEGL warning: driver (null)` / `dri2 screen` errors are GONE + gamescope
gets through Wayland-backend init + Xwayland :0 + Steam launch.

### 16.3 The remaining layer — gamescope-wayland client connection drop

With the EGL fix, gamescope's crash log now shows a **different, later failure**:

```
[gamescope] wlserver: Running compositor on wayland display 'gamescope-0'
[gamescope] wlserver: Starting Xwayland on :0
steam.sh[729]: Running Steam on ubuntu 24.04 64-bit
[gamescope] Error: waitable: IWaitable hung up. Aborting.
(EE) failed to read Wayland events: Connection reset by peer
Aborted (core dumped)
```

gamescope's Wayland backend inits ("Post-Initted Wayland backend"), its own
wlserver starts, Xwayland :0 comes up, Steam launches — then gamescope's
client connection to the gst-wayland-display compositor (`wayland-1`) **drops**
(`Connection reset by peer`). The compositor side is solid throughout
(selkies log: `EGL hardware-acceleration enabled`, full GL extension list,
`Supported DMA_formats` populated, `Creating new wl_output HEADLESS-1`).

This is the genuine **§13.14 caveat** verbatim: *"gamescope `--backend wayland`
(run as a Wayland client) is less battle-tested than `--backend headless`...
the games-on-whales maintainers note gamescope 'may be unstable with some
Nvidia driver versions.'"* The §13.14 spike (`gamescope --backend wayland --
sleep 30`) didn't hit it because `sleep` doesn't render/commit surfaces; Steam's
CEF does, which is what triggers the connection drop. **The compositor +
capture + webrtcbin pipeline (the §17.3 gate) is proven** — this is purely the
gamescope-as-Wayland-client stability layer.

### 16.4 The two documented fallbacks for the client stability (§13.14)

1. **sway as the Wayland client** (the games-on-whales default, `RUN_SWAY=1`):
   sway provides XWayland to the app too, + is more stable as a Wayland client
   of gst-wayland-display than gamescope on Nvidia. **✅ IMPLEMENTED + ✅ VALIDATED
   LIVE 2026-08-09 (OVH Gravelines L4, image `dpad-SteamOS-wd-spike`):** a
   `DPAD_WAYLAND_CLIENT=gamescope|sway` gate (default `gamescope` = no regression)
   in the entrypoint's `start_wayland_display_session` (`_launch_wayland_client`,
   replacing `_launch_gs_wayland`) launches `sway --unsupported-gpu -c
   /tmp/dpad-sway.config -d` nested under gst-wayland-display (`WLR_BACKENDS=wayland`
   forces the Wayland backend → NO DRM master → N-on-N preserved, §2.1;
   `WLR_LIBINPUT_NO_DEVICES=1` for headless) instead of `gamescope --backend
   wayland`. The sway config auto-fullscreens + `exec`s the shell app
   (Steam/Lutris) as a sway client. sway + xwayland are baked into the vast-vm
   stage (Dockerfile). **sway STAYS UP** (self-heals via the entrypoint health
   loop on the occasional drop — `relaunch` path) + **Steam renders + audio plays +
   the user can click/navigate** — the §16.3 gamescope-wayland client drop is
   **BYPASSED end-to-end** (video `m=video:9` + audio `m=audio:9` + interaction).
   See §16.7 for the live results + the audio-peer caveat. `dpad-launch-session`
   + `wayland-display-probe.sh` forward `DPAD_WAYLAND_CLIENT`. Same compositor
   capture; different XWayland provider.
2. **A gamescope rebuild** with a newer gamescope tag (the image's gamescope is
   3.16.25) — upstream may have fixed the Wayland-client connection issue. Lower-
   priority (a build change); try sway first.

### 16.5 Resume

```bash
cd dpadplay/container-gaming && git pull
# §16.4 sway fallback: ✅ VALIDATED LIVE 2026-08-09 (OVH L4). sway stays up +
#   Steam renders + audio plays + clickable. The §16.3 gamescope-wayland drop is
#   BYPASSED. See §16.7. The prod image now bakes sway + the gate (dpad-SteamOS).
# §16.6 OVH plain-proprietary-580 → open swap: ✅ validated live on the same VM.
#
# NEXT — the remaining §8 phasing:
# 1. §8 step 3: Lutris shell under the new compositor (DPAD_STORE_SHELL=lutris +
#    --ozone-platform=wayland) — libSDL3 already ships, so gamepad nav should work.
# 2. §8 step 4: store launchers (Battle.net/Epic) via sway-as-client (XWayland).
# 3. §5.4 input: keyboard/mouse are reaching Steam under sway (clickable); the
#    gamepad path under sway (vs the gamescope-XWayland evdev interposer) needs a
#    real-controller test + the inputtino migration (§8 step 6, last).
# 4. §8 step 5: flip the control-plane default to DPAD_COMPOSITOR=wayland-display
#    after a parallel-run period (the image is ready; the default is still
#    gamescope-headless = no regression).
# 5. ✅ DONE 2026-08-09 (§16.8) — N-on-N on the sway path: 2:1 + 3:1 compositor
#    gate validated (3 concurrent sway compositors on 1 L4, all streaming video+
#    audio, 48% GPU / 1.9 GB / load 4.45 on 22 cores, 3 coturn relays
#    3478/3479/3480 forwarding; raw time-slice, no MPS). Remaining: the raster
#    cliff (3 active games, human-play).
#
# Audio caveat (§16.7): the selkies AUDIO peer (SESSION 3, the separate-audio-
#   webrtcbin architecture, PR #96) is flaky on reconnect — a stale uid in the
#   signalling server's self.peers blocks the audio app's reconnect. DO NOT run
#   selkies-sdp-probe.py on a session VM before the browser (it pollutes
#   self.peers); a fresh container + the browser as the first peer = audio works.
```

### 16.6 ✅ FIXED — `ensure_driver_580` now swaps OVH's plain proprietary 580 too

> **⚠️ SUPERSEDED 2026-08-11 — the OVH plain-proprietary swap is REVERTED. It
> was never needed.** Empirically validated on a fresh OVH GRA11 l4-90
> (580.159.03, plain desktop `nvidia-driver-580`, license: NVIDIA): the DESKTOP
> proprietary build's render-node EGL/GBM glamor works for BOTH compositors —
> gamescope-headless + Steam (frame mean 38.4/255) AND wayland-display + sway +
> dpad-launcher picker (compositor EGL-inits off /dev/dri/renderD128, sway
> stable, picker renders + captures, umu/Battle.net prefix init). The §16.6
> rationale below ("OVH plain must swap for the compositor's EGL/GBM glamor")
> was a MISDIAGNOSIS — it inferred the compositor need from the §16.1 gamescope-
> as-client crash, which §16.2 reattributed to a Mesa EGL-vendor override leak,
> NOT the proprietary variant. The real distinction is the driver BUILD:
> `nvidia-dkms-580-server` (Scaleway, SERVER build) genuinely black-screens
> (mean 0.3/255) + crashes the compositor → must swap; `nvidia-driver-580`
> (OVH, DESKTOP build) works as-is → no swap. **Fix shipped (`c00784a`):**
> `ensure_driver_580` keeps the plain desktop proprietary 580 (return 0, no swap,
> no reboot); only the `-580-server` branch still swaps. **OVH cold boot
> ~12-18 min → ~6.2 min, no reboot.** The §16.6 prose below is kept as the
> (now-reverted) design record — read it with this correction. The Hyperstack
> R570-open finding (same session) confirms: an OPEN driver on a different
> provider also needs no swap — the `*` case keeps R570.

OVH's `Ubuntu 24.04 - NVIDIA - v580` ships `nvidia-dkms-580` + `nvidia-driver-580`
(the plain proprietary variant, `license: NVIDIA` — no `-server`, no `-open`).
Previously `vm-bootstrap.sh`'s `has_proprietary_580` gate matched `-580-server`
only (the Scaleway variant), so on OVH the gate returned false → `ensure_driver_580`
skipped the swap → the proprietary 580 stayed → the compositor's EGL/GBM glamor
hit the `dri2 screen` crash (§5) on OVH wayland-display sessions.

**Fix (IMPLEMENTED, scripts/vm-bootstrap.sh):**
- `has_proprietary_580` now also matches the plain `nvidia-(dkms|driver)-580$`
  (non-open, non-server). The shared packages (`nvidia-utils-580` /
  `nvidia-kernel-common-580` / `libnvidia-*-580` — deps of `-open` too) are
  deliberately NOT matched for the plain case, so an already-open host doesn't
  falsely read as proprietary.
- A new `has_580_server` gate chooses the PURGE strategy:
  - **`-580-server` (Scaleway):** unchanged — broad purge of the whole
    `-580-server` stack first (its userspace is separate from `-open`'s + its
    packages Conflict WITHOUT Replaces → apt can't auto-resolve; the purge is
    the proven workaround).
  - **plain `-580` (OVH):** NO purge — `apt install nvidia-driver-580-open`
    resolves it alone: the plain metapackages have clean Conflicts+Replaces to
    `-open` (apt removes the 2 conflicting metapackages) + the shared userspace
    stays. This matches the §16.1 live evidence (a manual `apt install
    nvidia-driver-580-open` loaded the open module, `license: Dual MIT/GPL`). A
    purge here would risk a cascade (removing the shared libs) for no benefit.
- The swap is now UNCONDITIONAL on the compositor: a warm VM may host either the
  gamescope-headless OR the wayland-display compositor via N-to-N reuse, and the
  host driver (VM-level) must support both — the open variant does. Cost: one
  cold-boot reboot on OVH (~12-18 min, same as Scaleway) where previously OVH
  booted without a driver swap. UpCloud (already open post-595-downgrade) is
  untouched. Verified by a dpkg-list simulation (OVH plain → no-purge+install;
  Scaleway server → broad purge; already-open → no-op).

### 16.7 ✅ LIVE-VALIDATED 2026-08-09 — sway fallback end-to-end (video + audio + interaction)

Provisioned a fresh OVH Gravelines L4 (`f4742340-…` @ `217.182.104.61`) via the
§12 `createOvhAdapter` pattern, image `forcespt/dpadcloud-gaming:dpad-SteamOS-wd-spike`
(= prod `:dpad-SteamOS` `aaa880f2` + `apt install sway xwayland` + the latest
`entrypoint.sh` with the §16.2 EGL fix + the §16.4 sway gate; a shortcut build,
no full rebuild). `vm-bootstrap.sh install` triggered the **§16.6 driver swap**
(plain proprietary `nvidia-driver-580` → `nvidia-driver-580-open`, `580.178.04`,
`license: Dual MIT/GPL`, one cold-boot reboot — the FIRST live validation of the
§16.6 fix on OVH) → `DPAD_VM_READY` → probe container with
`DPAD_COMPOSITOR=wayland-display DPAD_WAYLAND_CLIENT=sway DPAD_STORE_SHELL=steam`.
A real browser peer connected.

**Results — the §16.3 gamescope-wayland client drop is BYPASSED end-to-end:**
- **sway STAYS UP** (`sway` 1.9, `WLR_BACKENDS=wayland` nested under
gst-wayland-display). The occasional sway drop is caught + **self-healed by the
entrypoint health loop's restart-on-death path** (`_launch_wayland_client` is
re-called when sway dies + the compositor socket is still there) — sway was
observed dropping once then relaunching; the user kept seeing Steam.
- **Steam renders**: `steam` + `Xwayland` + `steamwebhelper` (×12) running;
`m=video 9` (H264) negotiated → the user sees Steam Big Picture.
- **Audio plays**: `m=audio 9` negotiated (the separate selkies audio peer,
`SESSION 3`); the user hears game audio.
- **Clickable**: with both video + audio connected, the web-client `status` reaches
`'connected'` → the `scale-loader` overlay (`:loading="(status !== 'connected')"`,
index.html) clears → the user can click + navigate Steam.
- **NVRTC errors = 0** (the CUDAMemory/compositor path; `extract-nvrtc.sh`
redundant here — §13.14 confirmed).
- sway's `[ERROR] Proprietary Nvidia drivers are in use` is a **false positive**
(the kernel module is open `580.178.04`; sway's heuristic flags the nvidia
userspace regardless) — `--unsupported-gpu` skips the abort, harmless.

**Audio caveat — the selkies separate-audio-peer flakiness (NOT a sway issue):**
This selkies-gstreamer uses the PR #96 architecture (separate webrtcbins for
video + audio; the app is `my_id=0`/`SESSION 1` video + `my_id=2`/`SESSION 3`
audio; the browser is peer 1 video + peer 3 audio). The audio app's signaling
connection is flaky on **reconnect**: when it drops, the signalling server
(`signalling_web.py:hello_peer`) does NOT clean up the dead uid `2` from
`self.peers` → the audio app's reconnect is rejected with `Invalid uid '2'
from …` / `invalid peer uid` (signalling_web.py:421: `if … uid in self.peers …`).
A stale uid blocks all subsequent audio. **Trigger observed:** running
`scripts/selkies-sdp-probe.py` on the session VM BEFORE the browser pollutes
`self.peers` (the sdp-probe's disconnect leaves uid 2 stale → the browser run's
audio app can't connect → no `m=audio` → `audioConnected != 'connected'` → the
overlay stays → not clickable). **Fix for testing:** a FRESH container (browser as
the first/only peer) = audio connects cleanly + stays. **DO NOT run
selkies-sdp-probe.py on a session VM before the browser.** The prod flow (browser
is the first peer) is unaffected. The deeper fix (server-side dead-peer cleanup on
WS close) is an upstream selkies issue (the #109 "audio randomly disabled" class)
+ a future hardening; not blocking the wayland path.

**Net:** the multi-store wayland path (compositor + sway-as-client + Steam + audio
+ interaction) is **VALIDATED**. Remaining §8 phasing: the Lutris shell + store
launchers under sway, the gamepad input under sway (§5.4 — keyboard/mouse already
reach Steam; the gamepad interposer was for gamescope's XWayland), N-on-N on the
sway path, then flip the control-plane default.

**Reproducible test (§12 pattern):** provision an OVH L4, `vm-bootstrap.sh install`
(fetches the fixed `vm-bootstrap.sh` + `entrypoint.sh` from repo `main` — the
§16.6 + §16.4 commits are pushed), launch the probe with
`DPAD_COMPOSITOR=wayland-display DPAD_WAYLAND_CLIENT=sway` + the sway-capable image
(`:dpad-SteamOS` now bakes sway + the gate, or the `:dpad-SteamOS-wd-spike` tag),
open the browser (do NOT run sdp-probe first), connect. VM torn down after
validation (`adapter.destroyVm`, 0 orphans, billing stopped).

## 16.8 ✅ LIVE-VALIDATED 2026-08-09 — N-on-N on the sway path (2:1 + 3:1 compositor gate)

> **Closes the §16.5 open item** ("Re-verify N-on-N on the sway path — 2 sway
> compositors on 1 L4"), extended to **3:1** (the actual Casual/Enthusiast tier
> slice ratio). The new `gst-wayland-display` compositor **preserves the
> no-DRM-master render-node property** that makes v2 oversubscription economics
> work: N compositors share `/dev/dri/renderD128` via EGL, all init, all
> capture, all stream — **raw render-node time-slice, no MPS needed** even at
> 3:1 idle.

Validated on the §17 OVH Gravelines L4 (`e6d4b0ca-…` @ `79.137.11.29`, open R580
`580.178.04`, prod `:dpad-SteamOS` tag) — the same warm VM as §17/§18, with the
1st container (`wd-probe`) already streaming. Launched 2 more identical
`DPAD_COMPOSITOR=wayland-display DPAD_WAYLAND_CLIENT=sway DPAD_STORE_SHELL=steam`
containers on the **same GPU** (`NVIDIA_VISIBLE_DEVICES=nvidia.com/gpu=0`), each
with its own coturn/selkies port (`wd-probe-2`: 3479/16101, `wd-probe-3`:
3480/16102, `testpass2`/`testpass3`). A real browser connected to each as the
first peer.

**Results — 3 concurrent compositors on 1 L4, all streaming video + audio:**
- **Compositor gate holds at 3:1.** Each container's `waylanddisplaysrc` inits
  EGL off the shared `/dev/dri/renderD128` while the others are active (no DRM
  master → no singleton contention); the 2nd/3rd compositor's `wayland-N` socket
  appears + `m=video:9` is negotiated (the §15 sdp-probe on wd-probe-2: `GATE
  PASSED: m=video:9`). **The N-on-N linchpin (§2.1) holds on the new compositor.**
- **GPU headroom is large:** 3 compositors + 3 Steam Big Picture = **48% util,
  1942 MiB / 23034 MiB (8%)**, 3 `nvidia-smi` compute apps (328+254+254 MiB).
  ~21 GB free at 3:1 idle.
- **CPU is light:** load avg 4.45 on 22 cores (the `l4-90` flavor is 22 vCPU,
  not 12 — comfortably above the ~3 cores/session rule at 3:1 idle).
- **UDP coturn scales:** all three relay ports forward media (nft counters:
  3478, 3479, 3480 all > 0). **OVH does NOT block 3480** — the OVH SG (or its
  default) allows the additional coturn ports; the docs' "open UDP 3478" was
  sufficient (no per-port rule needed for N>1). So prod N-on-N with N coturn
  ports is not SG-blocked.
- **NVRTC errors = 0** on each compositor (the `cudaconvert` JIT on the
  system-memory RGBx capture tail, covered by `extract-nvrtc.sh`).
- **Bonus:** `wd-probe-2` streamed at **3840×2160** — the user picked 4K from the
  live Resolution dropdown (§18.7), so live-resize works on a 2nd compositor
  concurrently.

**Methodology note (the first attempt was a red herring):** the first peer test
on `wd-probe-2` "didn't connect" — NOT an N-on-N or an OVH-SG failure. Two
stacked causes: (a) a headless `scripts/selkies-sdp-probe.py` run against
`wd-probe-2` (to capture the §15 `m=video:9` gate headlessly) polluted selkies'
`self.peers` with a stale peer-1 uid (the §16.7 quirk) → the browser's later
`HELLO 1` was rejected → no session → empty logs; (b) the browser-stripped
`http://user:pass@host` URL form (modern browsers drop the userinfo) → no
basic-auth. Fix: kill + relaunch a **fresh** `wd-probe-2` (no sdp-probe) + open
the bare URL (`http://79.137.11.29:16101`) + use the browser's basic-auth popup
(`dpad`/`testpass2`). All three then streamed immediately. **Lesson:** to visually
validate an Nth compositor, do NOT run `selkies-sdp-probe.py` on it first — the
browser must be the first peer (the §16.7 caveat, now confirmed to apply to the
video peer too, not just audio).

**What is NOT proven by this (the remaining gate):** the **raster cliff** —
3 concurrent *active* games (real raster load), not 3 idle Steam Big Pictures.
The compositor N-on-N at 3:1 is proven (the economics linchpin), but whether
3 simultaneous AAA playthroughs hold frame-time (or need MPS / vGPU) is the
§8 "UpCloud L4 oversub active-gameplay + 3:1" human-play gate. MPS remains
optional (raw time-slice sufficed at 3:1 idle); it becomes relevant only if
active 3:1 stutters.

**Reproduce:** on a warm wayland-display VM (§12), launch N identical
`DPAD_COMPOSITOR=wayland-display DPAD_WAYLAND_CLIENT=sway` containers on
`nvidia.com/gpu=0` with distinct coturn/selkies ports (`-p 3478+i:3478/udp -p
16100+i:16100/tcp`, `DPAD_TURN_UDP_EXTERNAL_PORT=3478+i`), open each in a browser
as the first peer. `nvidia-smi` shows N compute apps; `nft list ruleset | grep
"udp dport 347"` shows all N relay counters > 0.

## 16.9 🔬 Store-validation probe (2026-08-09) — Lutris video WORKS on the prod tag; sway SIGTRAP + .cache/lutris bugs block a stable Lutris session

> **2026-08-10 UPDATE — the Lutris shell is RETIRED by the dpad-launcher;
> the §16.9 SIGTRAP is re-characterized + the SDL3 hypothesis is DISPROVEN.**
> The multi-store pivot switched from lutris-gamepad-ui (Option B2) to a
> custom **dpad-launcher** Electron store-picker shell (Option B1) — see
> `PROJECT_STATE.md` (2026-08-10 session) + `STORES-PLAN.md` + `launcher/`.
> Lutris is a *library aggregator* (showed "no games found" on a fresh VM
> until each store was logged in + synced); the dpad-launcher is a *store
> launcher* front door. BUG 3 (`.cache/lutris`) was already gone in the newer
> image (the targeted chown now covers `~/.cache`) + is moot under the
> launcher (no Lutris backend). **The BUG 1 SIGTRAP isolation (2026-08-10):**
> A/B'd SDL3 ON vs OFF (the `DPAD_LUTRIS_SDL3` knob) — both crash
> **identically** → **SDL3 is NOT the trigger** (the §16.9 hypothesis below is
> disproven). The crash is the **wlroots 0.17.1 keyboard-group-destroy assert**
> during sway's *shutdown*, triggered by **compositor teardown on peer
> disconnect** (browser refresh / network blip): selkies tears down the
> pipeline → `waylanddisplaysrc` socket closes → sway gets "failed to read
> Wayland events: Broken pipe" → sway shuts down (`Shutting down sway`,
> main.c:418) → removes the compositor's `wayland-pointer/touch/keyboard-
> seat-0` devices → "Destroying empty keyboard group" → wlroots aborts
> (SIGTRAP). It **self-heals** (~20s stall; the entrypoint health loop
> relaunches sway on the new compositor socket) — NOT a hard blocker. The
> devices being torn down are the *compositor's own* wayland-backend seats
> (offered to sway regardless of shell), so it affects any shell under the
> sway client (Steam too — §16.7's occasional self-healing "drop" was likely
> this). Hardening = a wlroots bump or keeping the compositor alive across
> peer disconnect (open). The original §16.9 prose below is kept as the
> record; read it with this correction.

> **A short store-validation probe (§8 step 3/4) on the §17 OVH L4.** The key
> positive result: the Lutris Electron picker shell **streams video on the prod
> tag** (the §17.3 blocker is retired for the real shell, extending §18.2 from
> the sdp-probe to the browser). Two new bugs block a *stable* Lutris session:
> a sway SIGTRAP crash under the Lutris shell + a `.cache/lutris` permission
> bug. gamescope-as-client is NOT a fallback (it drops for Electron too).

Probed `DPAD_STORE_SHELL=lutris` under `DPAD_COMPOSITOR=wayland-display` on the
prod `:dpad-SteamOS` tag (the §17 OVH L4, `79.137.11.29`, open R580). Findings:

**✅ Lutris shell video WORKS on the prod tag.** With `DPAD_WAYLAND_CLIENT=sway`,
a real browser peer received the Lutris gamepad-UI image (the user saw the UI)
before sway crashed at ~33s — i.e. the `waylanddisplaysrc` compositor captured
the Electron app's surface + the WebRTC video track delivered it. This retires
§17.3 for the real Electron picker shell on the shippable image (§18.2 confirmed
it via the headless sdp-probe `m=video:9`; this confirms the browser path).

**🐛 BUG 1 — sway SIGTRAP crash under the Lutris shell (~33s).** sway 1.9 hits a
`Trace/breakpoint trap (core dumped)` (SIGTRAP = assertion/abort in wlroots)
~33s after start, during **wayland-backend input-device teardown**:
```
00:00:33.756 [DEBUG] [sway/input/seat.c:994] removing device 0:0:wayland-pointer-seat-0 from seat seat0
00:00:33.765 [DEBUG] [sway/input/input-manager.c:202] removing device: '0:0:wayland-touch-seat-0'
00:00:33.765 [DEBUG] [sway/input/seat.c:994] removing device 0:0:wayland-keyboard-seat-0 from seat seat0
...
Trace/breakpoint trap (core dumped)
```
The health loop relaunches sway but it crashes again at ~33s → the browser sees
the last captured frame + "Waiting for stream" (the live video stalls when sway
dies). **Not seen with the Steam shell** (sway stayed up, §16.7 — only the
occasional self-healing drop). The trigger is likely the Lutris/SDL3 gamepad
input path (the gamepad-UI inits SDL3, `LUTRIS_GAMEPAD_UI_ENABLE_SDL_INPUT=1`)
causing a compositor→sway input-device add/remove that hits a wlroots seat-teardown
assert. The compositor's wayland-backend input devices (wayland-pointer/touch/
keyboard) are UNUSED for actual input (input goes via XTest to XWayland,
`DPAD_INPUT_DISPLAY=:0`, §17.2) — so a fix is to prevent sway from adding/tearing
them down (a sway/wlroots config or an inputtino-virtual-device change), OR a
sway/wlroots version bump. **Open — blocks the Lutris shell.**

**🐛 BUG 2 — `gamescope --backend wayland` drops for the Lutris Electron app too
(§16.3 confirmed NOT Steam-specific).** `DPAD_WAYLAND_CLIENT=gamescope` +
`DPAD_STORE_SHELL=lutris` → the browser connects but the screen is **black**
(gamescope-wayland drops the compositor connection once the Electron app commits
surfaces, same as §16.3 for Steam's CEF). So gamescope-as-client is **NOT** a
fallback for the Lutris shell — sway is the only working client, + it hits BUG 1.

**🐛 BUG 3 — `/home/dpad/.cache/lutris/` created root-owned → Lutris backend
`PermissionError`.** The Lutris Python backend (the `lutris_wrapper` the gamepad-UI
calls) crashes on startup: `PermissionError: [Errno 13] Permission denied:
'/home/dpad/.cache/lutris/lutris.log'` — a root boot process creates `.cache/lutris`
root-owned (the §4 `.local`-class gotcha, not yet applied to `.cache/lutris`). The
gamepad-UI (Electron) still renders (it showed the UI before sway crashed), but
the backend is down → no library / store config (the §18.2 "No games found" was
this). **Fix:** the entrypoint's targeted-chown (`find <dir> ! -user dpad`) should
cover `~/.cache` (not just `~/.local`), OR `setup_stores()` should `chown -R dpad:dpad
~/.cache/lutris` before launching the shell. Low effort; image/entrypoint fix.

**Net for the store-validation gate:** the compositor pivot **does** unblock the
Lutris Electron shell for video (§17.3 retired on the prod tag) — but a stable
multi-store session is blocked by BUG 1 (the sway SIGTRAP). BUG 3 (the .cache
perm) is a quick entrypoint fix; BUG 2 confirms sway is the only viable client
(no gamescope fallback for Electron). **Next:** investigate BUG 1 (a sway/wlroots
input-device teardown assert under the Lutris/SDL3 gamepad path) — the blocker
for the Lutris shell + thus the multi-store flip.

## 17. Prod-tag re-validation + the input & resolution fixes (2026-08-09)

> **Followed up the §16.7 spike-tag validation by re-running the full sway path
> on the freshly-rebuilt + pushed public `:dpad-SteamOS` tag (no shortcut build),
> then fixed the two issues it surfaced — mouse/keyboard input + the 720p
> letterbox — both live-validated. The prod image is now CONFIRMED end-to-end on
> the real tag; the fixes are committed to `main` + ship via the entrypoint/
> `dpad_input_patch.py` bind-mount hotfix path until the next image rebuild bakes
> them.**

### 17.1 The prod-tag gate (the §8 step-2 "remaining" half, closed)

Provisioned a fresh OVH Gravelines L4 (`e6d4b0ca-…` @ `79.137.11.29`) via the
§12 `createOvhAdapter` pattern. `vm-bootstrap.sh install` ran the §16.6 driver
swap (plain proprietary `nvidia-driver-580` 580.159.03 → open
`nvidia-driver-580-open` 580.178.04, one cold-boot reboot) + pulled the user's
fresh rebuild of `forcespt/dpadcloud-gaming:dpad-SteamOS` (digest
`sha256:7d6a840e…`) + reached `DPAD_VM_READY` (0 containers, `DPAD_MAX_SESSIONS=0`).

**#prereq gate PASSED on the real prod tag** (no `:dpad-SteamOS-wd-spike`
shortcut): `command -v sway` (1.9), `gst-inspect-1.0 waylanddisplaysrc` (all 5
properties + the `video/x-raw(memory:CUDAMemory)` caps), `libSDL3.so.0.2.28`,
the entrypoint `DPAD_COMPOSITOR` gate + `start_wayland_display_session` — all
baked into the public tag. The §16.7 ambiguity (spike vs prod) is resolved: the
shippable image has the full wayland-display stack.

Launched `DPAD_COMPOSITOR=wayland-display DPAD_WAYLAND_CLIENT=sway
DPAD_STORE_SHELL=steam` → browser as the first peer → **video + audio + gamepad
all work end-to-end on the real prod tag.** The §17.3 Lutris-capture blocker is
retired on the shippable image, not just the spike. Two issues found + fixed
live (below).

### 17.2 FIX — mouse/keyboard now work under sway (the §5.4 phase-A gap, closed)

**Symptom:** gamepad worked (the classic/evdev interposer is compositor-agnostic
— browser → `/dev/input/jsN` → SDL3 → Steam, never touches X), but mouse +
keyboard did NOT reach Steam.

**Root cause (confirmed in the entrypoint):** `start_wayland_display_session`
launches selkies with `DISPLAY=:99` (the dummy Xvfb, needed for pynput to import)
and did **not** set `DPAD_INPUT_DISPLAY` — so selkies' XTest injected into the
dummy `:99`, never reaching sway's `Xwayland :0` (which the ps confirmed was up
+ running Steam). The gamescope-headless path sets `DPAD_INPUT_DISPLAY=:0`
(line 244/488) because gamescope's `:0` is up *before* selkies starts; the
wayland-display path inverts the boot order (selkies first → peer connects →
compositor → sway → `:0`), so `:0` is NOT up when selkies starts.

**The blocker:** `dpad_input_patch.py` (the baked-in selkies input router,
auto-loaded via `dpad_input_patch.pth`) opened `DPAD_INPUT_DISPLAY` **at import
time** (`_gs_dpy = display.Display(dpy)`). With the inverted boot order, that
open fails (`:0` not up yet) → the patch returns → XTest is dead for the whole
session, even after sway's `:0` later appears. So simply adding
`DPAD_INPUT_DISPLAY=:0` to the selkies env would NOT work.

**Fix (2 files, committed to `main`):**
1. **`scripts/dpad_input_patch.py` — lazy open.** Reworked the display open into
   a cached `_get_dpy()` that opens `DPAD_INPUT_DISPLAY` **on the first input
   event** + retries until `:0` is up (logs `waiting for :0 (will retry on
   input): DisplayConnectionError` at start, then `opened :0 OK (lazy)` once
   sway's Xwayland is up). The overrides (`connect`/`send_x11_keypress`/
   `send_mouse`) are installed at import regardless; `send_*` drop events until
   `_get_dpy()` succeeds, then XTest into `:0`. Also drops + reopens the display
   if it dies (sway restart). No-op when `DPAD_INPUT_DISPLAY` is unset (the
   gamescope-headless path's behavior unchanged — `:0` is already up there, so
   the lazy open succeeds immediately).
2. **`entrypoint.sh` `start_wayland_display_session` (line 910)** — added
   `DPAD_INPUT_DISPLAY=:0` to the selkies env (route XTest to sway's
   `Xwayland :0`), matching the gamescope path's pattern.

**✅ VALIDATED LIVE 2026-08-09:** relaunched the probe with both fixes
bind-mounted (entrypoint + the lazy `dpad_input_patch.py` over the image's
site-packages copy) → selkies logged `waiting for :0 ... Connection refused` at
start (expected) → on the browser connecting, the compositor started → sway
launched → `Xwayland :0` came up → the user's mouse + keyboard reached Steam
Big Picture. **This retires §5.4 phase A for the sway path** (keyboard/mouse
under sway); gamepad was already working. The remaining §5.4 work is the
inputtino migration (§8 step 6, last) — a cleaner path, not a blocker.

### 17.3 FIX — the 720p letterbox (interim) + the 1080p/1440p follow-up

**Symptom:** the stream had **black bars** around the video (letterboxed).

**Root cause (confirmed via `xrandr` on sway's `Xwayland :0`):** the
`waylanddisplaysrc` compositor's `wl_output` (WL-1) advertises a fixed
**1280×720** mode (the Smithay headless default). sway/Xwayland/Steam Big
Picture render at 1280×720. selkies, however, requested 1920×1080 capture caps
(`DPAD_STREAM_WIDTH/HEIGHT` defaulted to `GS_W/GS_H` = 1920/1080) → the
compositor's 1280×720 output was composited onto a 1920×1080 framebuffer,
centered → black bars. The `waylanddisplaysrc` element exposes **no size/mode
property** (only `render-node`/`cuda-device-id`/`mouse`/`keyboard`/
`disable-intel-workaround`), so the `wl_output` mode is not settable from the
pipeline; it does not follow the negotiated caps.

**Interim fix (committed to `main`):** `entrypoint.sh` line 910 now uses
`DPAD_STREAM_WIDTH=${DPAD_WD_WIDTH:-1280} DPAD_STREAM_HEIGHT=${DPAD_WD_HEIGHT:-720}`
for the wayland-display path (overridable via `DPAD_WD_WIDTH/HEIGHT`), matching
the compositor's native 1280×720 mode → no letterbox. The gamescope-headless
path is unaffected (still `GS_W/GS_H` = 1920/1080). **✅ VALIDATED LIVE
2026-08-09:** the black bars are gone; the stream is a clean 1280×720.

**✅ RESOLVED 2026-08-09 (§18.6) — the real fix is a sway config line, NOT a plugin-source change.** The §17.3 root-cause diagnosis above was partly wrong: the compositor was NOT capping at 720p. `wayland-info` on an isolated `gst-launch waylanddisplaysrc ! video/x-raw,format=RGBx,width=1920,height=1080` compositor confirmed the `wl_output` IS 1080p (`logical_width: 1920, logical_height: 1080`), + the `e657806` resolution-propagation fix is already in our pinned ref `b15285a2`. The bug is **sway's nested Wayland backend** (`WLR_BACKENDS=wayland`): it ignores the compositor's `wl_output.mode` (`swaymsg` shows `modes: []` + `current_mode` defaulting to 1280×720) and renders at 720p, which the compositor centers on the 1080p capture caps → black bars.

**The fix (commit `fefe3f4`):** a one-line sway config — `output * mode --custom ${DPAD_WD_WIDTH:-1920}x${DPAD_WD_HEIGHT:-1080}` — forces sway's output to the desired resolution (sway accepts it: `swaymsg 'output WL-1 mode --custom 1920x1080'` → success + rect 1920×1080). The compositor's caps (DPAD_WD_WIDTH/HEIGHT via the selkies capsfilter) and the sway output mode now BOTH derive from DPAD_WD_WIDTH/HEIGHT → always match → no bars at any resolution. The DPAD_WD_WIDTH/HEIGHT default is bumped 1280×720 → 1920×1080 (the 720p interim was only because 1080p letterboxed; now the sway side adopts the mode). This also **enables the future user-facing resolution dropdown**: the control plane / web sets DPAD_WD_WIDTH/HEIGHT; the entrypoint + sway follow.

**Still a follow-up (non-blocking):** dynamic resize — turn on selkies `--enable_resize=true` so the browser's window size drives the stream resolution at runtime (the "host catches the client resolution" UX). That needs the compositor's wl_output mode to follow the re-negotiated caps + the sway `output * mode` to re-apply; a later enhancement on top of the fixed-resolution path.

### 17.4 The live result + the resume

**Net (2026-08-09, prod tag):** video + audio + gamepad + **mouse + keyboard**
all work end-to-end on the freshly-rebuilt `:dpad-SteamOS` via the sway-as-client
wayland-display path — no shortcut build. The pivot is shippable; the remaining
gaps are (a) ~~the 1080p/1440p + dynamic-resize compositor-mode fix~~
   (**DONE §18.6** — a sway config line, default 1080p) + (b) the §8 phasing tail
   (Lutris shell + store launchers
under sway, N-on-N on sway, the `--device /dev/dri` CDI-perm fix for multi-GPU
hosts, selkies audio-peer reconnect, then the default flip).

**Shipped to `main` (this session):**
- `scripts/dpad_input_patch.py` — lazy `DPAD_INPUT_DISPLAY` open (§17.2).
- `entrypoint.sh` line 910 — `DPAD_INPUT_DISPLAY=:0` + `DPAD_WD_WIDTH/HEIGHT`
  (1280×720 default, §17.2 + §17.3).
- `scripts/relaunch-probe.sh` — a probe-relaunch helper (the extra
  `dpad_input_patch.py` bind-mount the probe script doesn't add).
- this §17.

**Until the next image rebuild bakes them**, the two fixes ship to existing VMs
via the entrypoint bind-mount hotfix path (vm-bootstrap fetches `entrypoint.sh`
from `main`) **+** a new `dpad_input_patch.py` bind-mount (the probe /
`dpad-launch-session` must mount `/opt/dpadcloud/dpad_input_patch.py` over
`/usr/local/lib/python3.12/dist-packages/dpad_input_patch.py` — `relaunch-probe.sh`
shows the pattern; `dpad-launch-session` needs the same `-v` added for prod
sessions). The next `:dpad-SteamOS` rebuild + push bakes both → no bind-mount
needed.

**Reproducible test:** §12 (provision an OVH L4 via `createOvhAdapter`) +
`vm-bootstrap.sh install` + `sudo bash /tmp/relaunch-probe.sh` (or the probe
script + the `dpad_input_patch.py` bind-mount) → browser as the first peer at
`http://$IP:16100` → Steam Big Picture (1280×720, no bars) + mouse/keyboard +
gamepad.

## 18. Lutris shell + Windows-app/launcher path — LIVE-VALIDATED 2026-08-09

> **§8 step 3 (Lutris shell under sway) + §8 step 4 (store-launcher path,
de-risked) + §5.4 phase A (gamepad under sway) — all VALIDATED LIVE on the
same OVH Gravelines L4 that was left warm from §17** (`dpadtest-wayland`,
`e6d4b0ca-…` @ `79.137.11.29`, open R580 `580.178.04`, prod `:dpad-SteamOS`
tag). Retires the original §17.3 blocker for the real Electron picker shell;
proves the Windows-app/launcher path (Battle.net's class) renders + captures +
interacts under the new compositor. No code changed this session (the §17.2
lazy-input + §16.4 sway + §16.6 driver-swap + §5.6 sdl3-builder fixes already
ship via the entrypoint/`dpad_input_patch.py` bind-mount hotfix path).

### 18.1 Setup
The §17 `wd-probe` container (steam shell) was torn down + relaunched with
`DPAD_STORE_SHELL=lutris` on the same proven path: `DPAD_COMPOSITOR=wayland-
display DPAD_WAYLAND_CLIENT=sway` + the entrypoint / `extract-nvrtc.sh` /
`dpad_input_patch.py` bind-mounts (the `relaunch-probe.sh` pattern, §17.4), prod
image `forcespt/dpadcloud-gaming:dpad-SteamOS`. A real browser connected as the
first peer (the §16.7 blessed path — do NOT run `selkies-sdp-probe.py` first; it
pollutes the selkies signalling `self.peers` + breaks the audio app).

### 18.2 §8 step 3 — Lutris shell: VALIDATED (render + click + gamepad)
- **Renders + captures:** the browser shows the `lutris-gamepad-ui` UI (not
  black / not "Waiting for stream") — the §17.3 `m=video:0` blocker is retired
  for the real Electron shell. `lutris-gamepad-ui.bin` runs under sway's
  `Xwayland :0`; sway registered its xwayland surface; the compositor captures
  it. (The library shows "No games found" — an empty-library content state, not
  a bug; no stores are configured on the probe container.)
- **`[sdl_manager] SDL3 initialized! libSDL3.so.0`** (the §5.6 `sdl3-builder`
  fix) — the SDL3 gamepad path is live.
- **Mouse/keyboard reach Lutris (§17.2 lazy XTest→:0):** `dpad_input: waiting
  for :0 … Connection refused` at start (selkies launches before sway/Xwayland)
  → `opened :0 OK (lazy)` once sway's `:0` came up → 76 `head=m` mouse-move
  events flowed → the user clicked the UI.
- **Gamepad navigates the Lutris UI** — the user confirmed. The 6-layer
  interposer is compositor-agnostic (browser → Selkies → `/dev/input/jsN` →
  SDL3 → Lutris, never touches X/Wayland) → gamepad works under sway with no
  new plumbing (retires §5.4 phase A for the sway path; inputtino is the last,
  cleaner-but-not-blocking step).
- **sway + Xwayland stable** — one transient sway drop self-healed by the
  health loop's restart-on-death path (the §16.7 behavior).
- **One non-fatal error:** `remote_desktop_manager: No such interface
  org.freedesktop.portal.RemoteDesktop` — `lutris-gamepad-ui` tries to use
  xdg-desktop-portal for *its own* remote-desktop feature (not our stream). A
  missing portal package; the app continues, input + stream unaffected. Polish
  item (install `xdg-desktop-portal` + a backend, or ignore).

### 18.3 §8 step 4 — store-launcher path: DE-RISKED (Windows app under sway's XWayland)
The real §1 #2 wall is the Chromium/CEF Windows store launchers (Battle.net is
the v1 one) rendering under Wine/Proton. Before the big Battle.net download,
a trivial Windows app was launched under GE-Proton11-3 to de-risk the path:
`winecfg.exe` (the standard Wine settings GUI) via
`…/GE-Proton11-3/files/bin/wine`, as the `dpad` user, with `DISPLAY=:0`
(sway's Xwayland) + `WAYLAND_DISPLAY=wayland-1`, `WINEPREFIX=/home/dpad/.wine-test`.
- **It rendered + was captured + was interactive.** `winecfg.exe` + `wineserver`
+ `explorer.exe /desktop` ran; sway registered the xwayland surface
(`_WINE_ALLOW_FLIP`, `WM_ICON_NAME`, `View … updated CSD`); the sway tree
showed `"Wine configuration" class=steam_proton focused=true`; the user saw the
Wine configuration window + clicked its tabs.
- **Net:** the Wine/Proton + XWayland + sway + gst-wayland-display-capture path
  works for a Windows GUI app. Battle.net (a Chromium/CEF Windows launcher,
  the same Wine/Proton path, §5 Xwayland rule) has **no architectural unknown
  left** — the full store validation is now pure execution: run the Lutris
  Battle.net install script (downloads `Battle.net-Setup.exe` + creates the
  prefix — STORES-PLAN §7) + login + install a small game. The Battle.net
  launcher+prefix pre-bake (STORES-PLAN §16 piece #2) is still deferred.
- **Cleanup:** `wineserver -k` + `pkill winecfg.exe` + `rm -rf .wine-test`;
the Lutris shell was left up.

### 18.4 What's now proven vs. still open
**Proven on the prod tag (this session):** the Lutris picker shell + gamepad +
mouse/keyboard under sway, AND a Windows app via GE-Proton11-3 under sway's
Xwayland — both captured + interactive. The pivot delivers the multi-store
picker + the store-launcher rendering path.

**Still open (the §8 phasing tail, unchanged):**
1. **The FULL store validation** (the execution tail of §8 step 4): Battle.net
   install + login + a game, OR Epic/GOG via Lutris sources (Legendary/gogdl —
   no Windows launcher, lighter). Needs store creds + a download. **⚠️ 2026-08-09
   probe (§16.9): the Lutris shell video WORKS on the prod tag (§17.3 retired for
   the real Electron shell), but a stable Lutris session is BLOCKED by a sway
   SIGTRAP crash (~33s, BUG 1) + the `.cache/lutris` permission bug (BUG 3);
   gamescope-wayland drops for Electron too (BUG 2). The `legendary`/`gogdl`
   backends are NOT installed in the image (Epic/GOG via Lutris needs them — a
   STORES-PLAN §16 image-bake gap). BUG 1 is the blocker to clear before the full
   store validation can run.**
2. **✅ DONE 2026-08-09 (§16.8) — N-on-N on the sway path.** 2:1 + 3:1 compositor
   gate validated: 3 concurrent sway/wayland-display compositors on 1 L4, all
   streaming video+audio (48% GPU / 1.9 GB of 23 GB, load 4.45/22 cores, 3 coturn
   relays 3478/3479/3480 all forwarding; raw render-node time-slice, no MPS). The
   oversub economics hold on the new compositor. **Remaining:** the raster cliff
   (3 concurrent *active* games, human-play) — the §8 UpCloud L4 active-gameplay
   gate.
3. **✅ DONE 2026-08-09 (§18.6)** — 1080p/1440p fix: a one-line sway config
   (`output * mode --custom WxH`), NOT a plugin-source change. sway's nested
   Wayland backend ignored the compositor's `wl_output.mode` (defaulted to
   720p); forcing the sway output mode matches the compositor caps → no bars.
   Default bumped to 1920×1080. Dynamic resize (`--enable_resize=true`) is a
   non-blocking follow-up.
4. **`--device /dev/dri` CDI-perm fix** for prod multi-GPU hosts (§14) — the
   spike mounts ALL GPUs' `/dev/dri`; prod needs a scoped render-node mount.
5. **selkies audio-peer reconnect robustness** (§16.7) — stale uid in
   `self.peers`.
6. **CUDAMemory zero-copy** (§13.3 follow-up, non-blocking).
7. **Flip the control-plane default** to `DPAD_COMPOSITOR=wayland-display` after
   a parallel-run on all 5 regions; **vendor `gst-wayland-display`** (§8 step 7).
8. **inputtino gamepad migration** (§8 step 6, last) — then retire the evdev
   interposer.

### 18.5 Resume
```bash
cd dpadplay/container-gaming && git pull
# §18 VALIDATED 2026-08-09 on the live OVH L4 (79.137.11.29, dpadtest-wayland):
#   §8 step 3 (Lutris shell under sway) + §8 step 4 de-risk (winecfg Windows app)
#   + §5.4 phase A (gamepad under sway) all PASS. No code changed this session
#   (the §17.2/§16.4/§16.6/§5.6 fixes already ship via bind-mount hotfix).
#   The §17.3 m=video:0 blocker is retired for the real Electron picker.
#
# NEXT (priority order):
#   A. FULL store validation — Battle.net (Lutris install script + login + a
#      game) OR Epic/GOG (Legendary/gogdl, lighter, no Windows launcher).
#      Needs store creds + a download. The path is de-risked (§18.3).
#   B. N-on-N on the sway path (2 sway compositors on the 1 L4; MPS optional).
#   C. ✅ DONE (§18.6) — the 1080p fix is a sway `output * mode --custom` config
#      line (default 1920x1080), NOT a plugin-source change. Dynamic resize
#      (--enable_resize=true) is a non-blocking follow-up.
#   Then: --device /dev/dri CDI-perm fix (§14), selkies audio-peer reconnect
#   (§16.7), CUDAMemory zero-copy (§13.3), flip the default + vendor (§8 step 5/7),
#   inputtino migration (§8 step 6, last).
#
# The live VM is warm (wd-probe = the Lutris shell). Reproduce: §12 (provision an
# OVH L4) + vm-bootstrap.sh install + relaunch-probe.sh with DPAD_STORE_SHELL=lutris
# (the probe script's SHELL=lutris, or edit the docker run) → browser as the
# first peer at http://$IP:16100 → Lutris UI + mouse/keyboard + gamepad.
```
## 18.6 Resolution fix — sway `output * mode --custom` (LIVE-VALIDATED 2026-08-09)

> **Retires the §17.3 letterbox with a one-line sway config — NOT the plugin-source
> change the §17.3 backlog speculated.** The §17.3 diagnosis blamed the compositor;
> the real bug is sway's nested Wayland backend ignoring the compositor's
> `wl_output.mode`. Validated live on the §17 OVH L4 (default 1080p → no bars).

### 18.6.1 The diagnosis (the compositor is NOT the bug)
Three checks on the live `wd-probe` container (DPAD_WD_WIDTH=1920 DPAD_WD_HEIGHT=1080):
1. **The caps ARE 1080p** — the selkies patch's capsfilter is 1920×1080 RGBx
   (DPAD_STREAM_WIDTH/HEIGHT from DPAD_WD_WIDTH/HEIGHT); the waylanddisplaysrc
   `set_caps` receives 1080p → `apply_video_info(1080p)`. Confirmed via
   `GST_DEBUG=waylanddisplaysrc:6` + `RUST_LOG=waylanddisplaycore=debug`:
   `Requested video format: RGBx` + `Handling allocation query video/x-raw,
   format=RGBx, width=1920, height=1080, framerate=60/1`.
2. **The compositor's wl_output IS 1080p** — install `wayland-utils` + run an
   isolated `gst-launch-1.0 waylanddisplaysrc ! video/x-raw,format=RGBx,
   width=1920,height=1080,framerate=60/1 ! fakesink` (no selkies) → `wayland-info`
   on its socket reports `logical_width: 1920, logical_height: 1080`. The
   `e657806` "propagate runtime resolution changes" fix is already in our pinned
   ref `b15285a2` (`apply_video_info` runs `change_current_state` on every
   VideoInfo; `output_already_running` only guards `map_output`).
3. **But sway sees 720p** — launch sway on that same 1080p compositor → `swaymsg
   -t get_outputs` shows `"modes": []` + `current_mode: {width:1280,height:720}`
   + `rect: 1280x720`. sway's nested Wayland backend (`WLR_BACKENDS=wayland`)
   ignores the compositor's `wl_output.mode` (its wlr_wl_output exposes no modes)
   and defaults to 720p → the compositor centers the 720p sway surface on its
   1080p capture caps → black bars.

### 18.6.2 The fix (commit `fefe3f4`)
`swaymsg 'output WL-1 mode --custom 1920x1080'` → `success` + `rect: 1920x1080`.
So the entrypoint's sway config (the `start_wayland_display_session` heredoc,
`/tmp/dpad-sway.config`) now emits `output * mode --custom
${DPAD_WD_WIDTH:-1920}x${DPAD_WD_HEIGHT:-1080}` before the `exec ${SHELL_APP}`.
Both the compositor's caps (the selkies capsfilter, DPAD_STREAM_WIDTH/HEIGHT)
and the sway output mode now derive from DPAD_WD_WIDTH/HEIGHT → always match →
no bars at any resolution. The DPAD_WD_WIDTH/HEIGHT default is bumped 1280×720
→ 1920×1080 (the §17.3 720p interim existed only because 1080p letterboxed;
now that sway adopts the mode, 1080p is the correct default, matching
`gamescope --backend headless -W 1920 -H 1080`).

### 18.6.3 ✅ LIVE-VALIDATED
`DPAD_COMPOSITOR=wayland-display DPAD_WAYLAND_CLIENT=sway` + the default 1080p
(no DPAD_WD_WIDTH) → Steam Big Picture fills the frame, **no black bars**;
`swaymsg` `rect: 1920x1080`, `current_mode: {width:1920,height:1080}`; `xrandr
WL-1 connected 1920x1080+0+0, 1920x1080 59.96*+`. Resolution is now
controllable via DPAD_WD_WIDTH/HEIGHT (the lever for the future user-facing
resolution dropdown — the control plane / web sets it; the entrypoint + sway
follow).

### 18.6.4 Follow-up (non-blocking)
Dynamic resize: turn on selkies `--enable_resize=true` so the browser's window
size drives the stream resolution at runtime (the "host catches the client
resolution" UX). That needs the compositor's wl_output mode to follow the
re-negotiated caps + the sway `output * mode` to re-apply on the fly. A later
enhancement on top of this fixed-resolution path. The `gst-wayland-display`
plugin-source change the §17.3 backlog speculated is NOT needed.

### 18.6.5 Reproduce
```bash
# On a warm wayland-display VM (§12), confirm the compositor emits the caps' res:
docker exec -u 0 wd-probe bash -lc 'apt-get install -y -qq wayland-utils >/dev/null;
  su -s /bin/bash dpad -c "export XDG_RUNTIME_DIR=/run/user/1001 GST_PLUGIN_PATH=/opt/gstreamer/lib/x86_64-linux-gnu/gstreamer-1.0;
  . /opt/gstreamer/gst-env; nohup gst-launch-1.0 waylanddisplaysrc ! video/x-raw,format=RGBx,width=1920,height=1080,framerate=60/1 ! fakesink sync=false >/tmp/g.log 2>&1 &"; sleep 3;
  su -s /bin/bash dpad -c "WAYLAND_DISPLAY=\$(ls -t /run/user/1001/wayland-* | grep -v lock | head -1 | xargs basename) XDG_RUNTIME_DIR=/run/user/1001 timeout 4 wayland-info" | grep -E "logical_width|logical_height"'
# → logical_width: 1920, logical_height: 1080  (compositor follows the caps)
# Then confirm sway ignores it (the bug) + the fix:
# swaymsg -t get_outputs  → modes: [], current_mode 1280x720  (the bug)
# swaymsg -t command "output * mode --custom 1920x1080"  → success; rect 1920x1080  (the fix)
```
