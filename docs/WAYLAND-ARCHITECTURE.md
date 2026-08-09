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
> **Status: DECISION (not yet implemented).** The phased plan (§8) starts with a
> cheap live probe (already-wired env knobs) + a build spike, then layers the
> shell + store launchers on top. Nothing in the image changes until the spike
> validates the compositor→Selkies path on one VM.
>
> **Companion:** `STORES-PLAN.md` (the multi-store plan this unblocks — §17.3 is
> the live-test blocker this retires), `PROJECT_STATE.md` §6 #10/#11/#12 (the
> open image items this supersedes), `IMAGE-RUNBOOK.md` (the launch recipe — the
> new `DPAD_COMPOSITOR` env lands here), `cloud/docs/STATUS.md` §8 #9 (the
> control-plane multi-store item).

## 0. TL;DR — the pivot

| | Today (gamescope-headless) | After (`gst-wayland-display`) |
|---|---|---|
| **Compositor + capture** | `gamescope --backend headless` renders → PipeWire node → `pipewiresrc` (system-memory BGRx) → `cudaupload` → `cudaconvert` (NVRTC JIT) → `nvh264enc` | `waylanddisplaysrc render_node=$RENDER_NODE` → `video/x-raw(memory:CUDAMemory)` → `nvh264enc` (true zero-copy, no cudaconvert/NVRTC) |
| **XWayland / legacy apps** (Steam CEF, Wine/Proton store launchers) | gamescope *is* the compositor + the XWayland provider | gamescope runs **as a Wayland client** of gst-wayland-display; it provides XWayland to the app; gamescope's output is captured by gst-wayland-display |
| **Native-Wayland apps / full desktop** (Electron `--ozone-platform=wayland`, sway, OpenGamepadUI/Godot) | not reliably captured (the §17.3 bug) | render **directly** into gst-wayland-display → captured |
| **Transport** | Selkies `webrtcbin` + coturn + Opus inband FEC + ULP_RED video FEC + NACK rtx | **unchanged** |
| **N-on-N** | shared GPU via MPS daemon (or raw time-slice) | shared render-node EGL contexts (raw time-slice, no DRM master) — MPS still optional for loaded 3:1 |
| **Input** | Selkies datachannel → XTest on Xwayland `:0` | Selkies datachannel → gst-wayland-display input messages (mouse/kb) + inputtino virtual `/dev/input/event*` (gamepads); XTest remains *inside* gamescope for XWayland apps |
| **Gamepad** | 6-layer chain + evdev interposer (working, validated) | inputtino virtual pads (cleaner, same outcome) — or keep the existing chain initially |

**Net:** one new build stage (`wayland-display-builder`), one GStreamer source
element swap (`pipewiresrc` → `waylanddisplaysrc`), gamescope demoted from
compositor to client, plus the input-side rework. Everything downstream
(encode, coturn, FEC, the web client, the control plane, billing, volumes) is
untouched.

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
- **gamescope-as-Wayland-client stability.** gamescope's `--backend wayland`
  (run as a Wayland client instead of owning the scanout) is less battle-tested
  than `--backend headless`. The games-on-whales maintainers note gamescope
  "may be unstable with some Nvidia driver versions" (their config docs) and
  default to sway. **Mitigation:** the spike validates `gamescope --backend
  wayland -- steam -gamepadui` under gst-wayland-display on an L4 first; if it's
  flaky, the fallback for XWayland apps is sway-as-client + XWayland (sway
  provides XWayland too) — same capture, different XWayland provider.
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
   - Add the `sdl3-builder` stage (§5.6): build SDL3 from source with minimal
     backends (joystick/hidapi/events), install `libSDL3.so.0` to
     `/usr/lib/x86_64-linux-gnu/` + `ldconfig`. Retires §17.4.
   - `DPAD_STORE_SHELL=lutris` → `lutris-shell` as a Wayland client of
     gst-wayland-display (try `--ozone-platform=wayland` direct first; fall back
     to `gamescope --backend wayland` if the Electron app needs X).
   - Validate gamepad navigation of the Lutris UI end-to-end with a real
     controller (the bar the evdev path cleared 2026-08-04). Keyboard/mouse via
     Selkies Desktop mode is the fallback while the SDL3 fix lands.

4. **Store launchers via gamescope-as-client (XWayland) — ~1 day.** Battle.net /
   Epic under GE-Proton11-3 via `gamescope --backend wayland -- <launcher>`.
   Validate the §5 Xwayland path captures the launcher window + the game. (This
   is the real multi-store validation — the launchers rendering is the thing
   gamescope-headless could not do.) This is the step that proves multi-store;
   the Lutris shell from step 3 is the picker that gets the user *to* the
   launcher.

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
# This doc = the decision. §8 step 1 (the probe) is DONE (2026-08-08, OVH L4):
# DPAD_LUTRIS_DISABLE_GPU=1 did NOT fix §17.3 → the pivot is strictly necessary.
# §17.4 (libSDL3) is SHIPPED (sdl3-builder, commit af5bda6, image b403937b on
# Docker Hub) + live-validated (sdl_manager "SDL3 initialized! libSDL3.so.0").
#
# §8 step 2 BUILD + COMPOSITOR-CAPTURE HALVES — DONE + LIVE-VALIDATED 2026-08-08:
# the wayland-display-builder stage is committed to Dockerfile (orphan) + builds;
# on a real OVH L4 (open R580) the compositor starts on the render node (NO DRM
# master → N-on-N), EGL/GBM glamor works, CUDAMemory zero-copy engages, nvh264enc
# inits, NVRTC-error=0 (extract-nvrtc.sh redundant here), + the wayland socket is
# created (client-discovery via polling works). See §13.13–§13.14. The prod image
# already has libwayland 1.24.0 → vast-vm needs only the plugin .so COPY'd.
#
# §8 step 2 REMAINING (the Selkies + browser-stream half) — NEXT:
#   1. gamescope `--backend wayland` is AVAILABLE (live-confirmed: "Post-Initted
#      Wayland backend"; auto-selects when WAYLAND_DISPLAY set). No rebuild/sway.
#   2. Wire vast-vm: COPY --from=wayland-display-builder the plugin .so to the
#      gstreamer plugin dir (DONE — committed; the prod libwayland 1.24.0
#      suffices, no libwayland COPY). Add `--device /dev/dri` to the container
#      launch (the CDI /dev/dri group perms block the compositor's raw
#      render-node open, §13.14). DONE: the patch_selkies_waylanddisplay.py
#      (the waylanddisplaysrc branch) is written + applied in vast-vm.
#   3. patch_selkies_waylanddisplay.py (mirror patch_selkies_pipewire.py): DONE —
#      the waylanddisplaysrc cuda-device-id=$CUDA_ID ! CUDAMemory ! nvh264enc
#      branch in build_video_pipeline (gated on DPAD_VIDEO_SRC=waylanddisplaysrc).
#   4. entrypoint DPAD_COMPOSITOR=wayland-display gate (default gamescope = no
#      regression): start selkies (waylanddisplaysrc) [needs a dummy Xvfb for
#      pynput to import, §13.14], poll $XDG_RUNTIME_DIR/wayland-* for the socket,
#      launch gamescope --backend wayland -- <shell> with WAYLAND_DISPLAY (pre-
#      create /tmp/.X11-unix root-owned 1777, §13.14).
#   5. Live selkies webrtcbin peer test: provision an OVH L4, run with
#      DPAD_COMPOSITOR=wayland-display, connect a WebRTC peer (aiortc headless
#      client OR a browser) → confirm m=video:2 (the §17.3 metric) + N-on-N.
#
# Then: Lutris shell (native Wayland, --ozone-platform=wayland) for gamepad nav
#   (sdl3-builder already ships libSDL3) → store launchers via gamescope-as-client
#   (XWayland) → flip default → inputtino migration (last).
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
   of gst-wayland-display than gamescope on Nvidia. Add a
   `DPAD_WAYLAND_CLIENT=gamescope|sway` gate; the entrypoint launches
   `sway` (with `WAYLAND_DISPLAY=wayland-N`) instead of `gamescope --backend
   wayland`. Same compositor capture; different XWayland provider.
2. **A gamescope rebuild** with a newer gamescope tag (the image's gamescope is
   3.16.25) — upstream may have fixed the Wayland-client connection issue. Lower-
   priority (a build change); try sway first.

### 16.5 Resume (the client-stability layer)

```bash
cd dpadplay/container-gaming && git pull
# §16: the EGL-vendor bug is FIXED (21dfb1e, ships via the entrypoint hotfix).
# gamescope --backend wayland now reaches Steam launch before the connection drop.
#
# NEXT — the gamescope-wayland client stability (§16.3/§16.4):
# 1. Provision an OVH L4 (§12). vm-bootstrap.sh install (fetches the EGL-fixed
#    entrypoint). The open R580 is now AUTOMATED for OVH too (§16.6 FIXED:
#    has_proprietary_580 now detects OVH's plain nvidia-driver-580/nvidia-dkms-580
#    + ensure_driver_580 swaps to nvidia-driver-580-open with NO purge — apt
#    resolves the plain variant's Conflicts+Replaces; the -580-server broad-purge
#    path for Scaleway is unchanged). One cold-boot reboot for the swap (~12-18 min).
# 2. VM_IP=<ip> SHELL=steam bash /tmp/wayland-display-probe.sh
# 3. Connect a peer (selkies-sdp-probe.py) → gamescope launches → opens the browser
#    at http://$VM_IP:16100 to SEE the compositor surface (black until a client renders).
# 4. Try the sway fallback (§16.4 #1): DPAD_WAYLAND_CLIENT=sway gate in the entrypoint
#    (launch sway with WAYLAND_DISPLAY=wayland-N instead of gamescope --backend wayland).
# 5. If sway stays up + Steam renders, the browser shows Steam Big Picture (the full
#    multi-store path unblocked: §8 step 3 Lutris shell → §8 step 4 store launchers).
```

### 16.6 ✅ FIXED — `ensure_driver_580` now swaps OVH's plain proprietary 580 too

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
