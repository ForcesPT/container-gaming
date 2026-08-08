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
   - Add a `wayland-display-builder` stage; build `gst-wayland-display` (with
     `cuda` feature) + `gst-cuda-1.0` + `inputtino` from source.
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
# START at §8 step 2 (the spike). Nothing else in the image changes until the
# spike validates the compositor→Selkies path on one VM. The default stays
# DPAD_COMPOSITOR=gamescope (no regression) until the parallel-run validation.
#
# Spike build:
#   1. Add a wayland-display-builder stage (Rust + cargo-c, Smithay cuda feature).
#      Build gst-wayland-display + gst-cuda-1.0 + inputtino from source.
#   2. entrypoint: add DPAD_COMPOSITOR=wayland-display (default gamescope).
#      New capture: waylanddisplaysrc cuda-device-id=$CUDA_ID !
#        video/x-raw(memory:CUDAMemory) ! nvh264enc ! webrtcbin (Selkies unchanged).
#   3. Run Steam via `gamescope --backend wayland -- steam -gamepadui` as a
#      Wayland client of gst-wayland-display. Confirm stream + N-on-N (2 + 3
#      on 1 GPU) + CUDAMemory zero-copy + NVRTC-error-count=0 without extraction.
#   4. Confirm open-driver EGL init is clean under our CDI (no #379 panic).
#
# Probe (parallel, cheap):
#   DPAD_STORE_SHELL=lutris DPAD_LUTRIS_DISABLE_GPU=1 on a live L4 → m=video:2?
#   Characterises the §17.3 bug; does not change the decision.
#
# Then: Lutris shell (native Wayland, --ozone-platform=wayland) + the
#   sdl3-builder stage for gamepad nav → store launchers via gamescope-as-client
#   gamescope-as-client (XWayland) → flip default → inputtino migration (last).
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