# Container Gaming Stack Improvement Roadmap

> **For Hermes:** Use subagent-driven-development skill to implement this plan task-by-task. Before implementation, re-read `docs/PROJECT_STATE.md`, `docs/IMAGE-RUNBOOK.md`, `docs/STORES-PLAN.md`, and `docs/WAYLAND-ARCHITECTURE.md`; these are the live source of truth and may supersede this snapshot.

**Goal:** Preserve the current DpadPlay container-gaming architecture and the complete backlog of improvements so future work can resume without rediscovering the stack or losing priorities.

**Architecture:** One NVIDIA CDI Docker container per gaming session on an Ubuntu GPU VM. The production desktop uses `gst-wayland-display` as a render-node compositor/capture source, nested Sway for window management and XWayland, the custom Electron DpadPlay store picker, and Selkies/GStreamer/NVENC/WebRTC/coturn for browser delivery. Steam is native; other Windows stores use Heroic or `umu-launcher` + GE-Proton.

**Tech Stack:** Ubuntu 24.04, NVIDIA CUDA 12.5.1/12.8.1, Docker + NVIDIA CDI, gst-wayland-display/Smithay, Sway/wlroots, XWayland, Electron 33, SDL3 + Koffi, Steam, Heroic, Lutris, Wine, GE-Proton11-3, umu-launcher 1.4.4, PipeWire, GStreamer, Selkies, NVENC, WebRTC, coturn, Caddy, and stream-bridge.

---

## 1. Current Stack Snapshot

### Host and container

- GPU hosts generally run Ubuntu with provider-specific NVIDIA drivers.
- Final session image: `forcespt/dpadcloud-gaming:dpad-SteamOS`.
- Container base: `nvidia/cuda:12.5.1-base-ubuntu24.04`.
- Blackwell variant: CUDA 12.8.1.
- Session user: `dpad`, UID/GID 1001.
- One container per GPU/session slot, isolated through NVIDIA CDI:
  `NVIDIA_VISIBLE_DEVICES=nvidia.com/gpu=N`.
- XFS project quotas cap ephemeral storage; persistent volumes retain accounts, prefixes, saves, and games.

### Production display configuration

```text
DPAD_COMPOSITOR=wayland-display
DPAD_WAYLAND_CLIENT=sway
DPAD_STORE_SHELL=picker
```

```text
gst-wayland-display (Smithay compositor + capture, DRM render node, no DRM master)
└── nested Sway (WLR_BACKENDS=wayland)
    └── XWayland :0
        ├── DpadPlay launcher
        ├── Steam / Heroic
        ├── Wine/Proton store launchers
        └── games
```

- The old `gamescope --backend headless` compositor remains as a fallback.
- Gamescope-headless is not appropriate as the production desktop compositor because arbitrary Electron/CEF multi-window interfaces are not captured reliably.
- The validated capture tail is:

```text
waylanddisplaysrc
→ system-memory RGBx
→ cudaupload
→ cudaconvert to NV12
→ nvh264enc
→ webrtcbin
→ coturn
→ browser
```

### Session UI

- Custom `dpad-launcher` 10-foot interface.
- Electron 33 with HTML/CSS/JavaScript.
- SDL3 3.2.28 input through Koffi.
- Fullscreen/kiosk under Sway; launcher moves to scratchpad when a store opens.
- Store cards: Steam, Battle.net, Epic Games, GOG, EA App, Ubisoft Connect.

### Gaming/runtime stack

- Steam: native Linux client, pre-bootstrapped at image build time.
- Steam root is persisted on the user volume:
  `~/.steam/debian-installation -> <volume>/steam-install`.
- Epic/GOG: Heroic with Legendary/gogdl.
- Battle.net, EA App, Ubisoft Connect: store launch wrapper → umu-launcher → Steam Linux Runtime/pressure-vessel → GE-Proton11-3.
- Windows launchers use XWayland, not native Wine Wayland.
- Compatibility packages also include Wine 32/64, Winetricks, Lutris 0.5.22, DXVK 3.0.2, VKD3D-Proton 2.14.1, and DXVK-NVAPI 0.9.2.

### Audio/input/network

- Audio: application → PipeWire/pipewire-pulse → Pulse monitor → Selkies → Opus → browser.
- Keyboard/mouse: browser data channel → Selkies → XTest → XWayland → focused app.
- Mouse modes: Desktop/absolute and Gaming/pointer-lock relative mode.
- Gamepad: browser Gamepad API → Selkies sockets → virtual `/dev/input/jsN` → 32/64-bit joystick or evdev interposers → SDL3 → app/game.
- Signaling/UI requires HTTPS. Media uses WebRTC with coturn, NACK, optional audio/video FEC.
- Stream supports live 720p, 1080p, 1440p, and 4K selection.

### Driver matrix that must not be rediscovered

| Provider/build | Action |
|---|---|
| OVH desktop proprietary 580 | Keep |
| Scaleway `580-server` | Swap to open 580 |
| UpCloud 595 | Mandatory downgrade to open 580 |
| Hyperstack R570-open | Keep |
| MassedCompute R580-open | Keep |

`ensure_driver_580` must remain Scaleway-gated; making it global would break OVH.

---

## 2. Prioritised Roadmap

## P0 — Reliability, reproducibility, and security

### Task 1: Pin all externally downloaded build artifacts

**Status (2026-08-15): PARTIAL — first safe slice complete.** Completed and
validated on OVH: explicit Selkies 1.6.2, SHA-256 guards for its four consumed
assets, Wayland 1.23.1, pinned gst-wayland-display source, GE-Proton11-3, and
umu-launcher 1.4.4; bounded retries; no `curl | tar`; mandatory checksum gating;
exact checksum-to-filename and verification-chain regression checks. Commits:
`000e750`, `34313a2`, `bbfffb8`, `63eb0c0`. The second slice additionally pins
SDL3, cloudflared, VirtualGL, Heroic, VKD3D-Proton, DXVK, DXVK-NVAPI,
lutris-gamepad-ui, and Lutris. Remaining work includes base/external image
digests, NVRTC, Rust/cargo/Steam inputs, APT snapshots, and
conditional installer/prebake inputs. Do not mark Task 1 fully complete yet.

**Objective:** Make image builds reproducible and prevent an untested upstream release from silently entering production.

**Files:**
- Modify: `Dockerfile`
- Modify: build scripts under `scripts/` that download external binaries
- Update: `docs/PROJECT_STATE.md`
- Update: `docs/IMAGE-RUNBOOK.md`

**Work:**
1. Replace the Selkies GitHub `releases/latest` lookup with an explicit build argument/default version.
2. Require SHA-256 values for Selkies tarballs, wheel, web bundle, and interposer package.
3. Make `GE_PROTON_SHA256` and `UMU_SHA256` mandatory for release builds rather than optional notes.
4. Pin and hash Heroic, Lutris gamepad UI, cloudflared, DXVK, VKD3D-Proton, DXVK-NVAPI, and any installer artifacts.
5. Add a release-build mode that fails when any checksum is omitted.
6. Verify with a clean `docker build --target vast-vm ...` on the GPU/build VM.

### Task 2: Introduce immutable image releases and staged rollout

**Status (2026-08-15): PARTIAL.** Published cleanup release
`dpad-SteamOS-2026.08.15-r3` and convenience tag `dpad-SteamOS`; both resolve to
OCI digest `sha256:f0017b8a115a870eb733c715d5917e2ccfaa4ff85e2d0555ade4dee141ec3762`.
Still required: pin that digest in the control plane, canary one provider/session,
and implement/test rollback. `r3` is labeled and remotely verified against full
source commit `6699b5ffef6de628604fd103fdcb756364d3bf40`.

**Objective:** Production must use a known digest instead of depending on mutable `:dpad-SteamOS`.

**Files:**
- Modify: image build/release workflow in this repo
- Modify later in control plane: worker/bootstrap image selection
- Update: `docs/IMAGE-RUNBOOK.md`

**Work:**
1. Define release tags such as `dpad-SteamOS-YYYY.MM.DD-rN`.
2. Push both release tag and convenience tag.
3. Record and deploy the immutable digest.
4. Add canary rollout to one provider/session before global promotion.
5. Preserve rollback to the previous digest.

### Task 3: Produce SBOM and vulnerability reports

**Objective:** Track the large third-party binary surface in the image.

**Work:**
1. Generate CycloneDX or SPDX SBOM with Syft during releases.
2. Scan with Grype or Trivy.
3. Fail only on an agreed severity policy with documented exceptions.
4. Attach SBOM and scan report to the release.

### Task 4: Stop desktop teardown on browser disconnect

**Objective:** Browser refreshes and network blips should reconnect to the same desktop without restarting Sway or triggering the wlroots teardown assertion.

**Files:**
- Modify: `entrypoint.sh`
- Possibly modify: Selkies lifecycle patches under `scripts/`
- Test: live OVH/Scaleway L4 session

**Work:**
1. Separate compositor/Sway lifetime from WebRTC peer lifetime.
2. Keep `gst-wayland-display` and Sway alive while Selkies signaling/media is recycled.
3. Reconnect a new peer to the existing session.
4. Test refresh, tab close/reopen, temporary packet loss, and Selkies process restart.
5. Confirm store/game processes and controller state survive.

### Task 5: Upgrade and validate Sway/wlroots

**Objective:** Remove the keyboard-group teardown SIGTRAP rather than relying only on self-healing.

**Work:**
1. Build a newer pinned Sway/wlroots in a separate builder stage.
2. Test nested Wayland operation on every driver family.
3. Validate Electron picker, Steam CEF, all launchers, XWayland, input, audio, resolution switching, and 2:1/3:1 sessions.
4. Retain the current Sway package as rollback until validation passes.

### Task 6: Reduce container privilege scope

**Objective:** Replace broad unconfined options with the narrow permissions needed by Steam/umu/pressure-vessel/bwrap.

**Work:**
1. Trace required capabilities and syscalls during Steam and each umu launcher.
2. Design a targeted seccomp profile.
3. Design a targeted AppArmor profile.
4. Test whether `SYS_ADMIN` can be reduced or isolated through a helper/container boundary.
5. Validate `bwrap` `/proc` mounts, unprivileged user namespaces, Steam runtime, and all stores.
6. Do not weaken CDI GPU isolation.

---

## P1 — User experience and compatibility

### Task 7: Add real store lifecycle states to the launcher

**Objective:** Replace binary-exists “Available” status with meaningful readiness information.

**Files:**
- Modify: `launcher/src/main.js`
- Modify: `launcher/src/renderer.js`
- Modify: `launcher/src/index.html`
- Modify: `launcher/src/styles.css`
- Add tests or deterministic state fixtures under `launcher/`

**States:** Ready, needs installation, needs login, updating, unavailable, unsupported.

**Validation:** Verify every store with empty ephemeral state and with an existing persistent volume.

### Task 8: Add first-run onboarding

**Objective:** Explain essential session behaviour without requiring external documentation.

**Content:**
- Desktop vs Gaming mouse mode.
- Store login persistence.
- Persistent vs ephemeral storage.
- Controller activation/reconnect.
- Anti-cheat limitations.
- How to return to DpadPlay.

### Task 9: Add a DpadPlay in-session overlay

**Objective:** Provide console-like controls from any store or game.

**Trigger:** Guide/Home hold, with keyboard fallback.

**Controls:**
- Return to launcher.
- Desktop/Gaming mouse mode.
- Resolution, FPS, bitrate.
- Controller status.
- Network quality.
- Disconnect or end session.

### Task 10: Add a unified installed-games view

**Objective:** Preserve the neutral store picker while allowing direct game launch.

**Sources:**
- Steam `libraryfolders.vdf` and app manifests.
- Heroic/Legendary metadata.
- GOG/gogdl metadata.
- Installed Battle.net/EA/Ubisoft games where reliably detectable.

**Constraints:** Do not return to Lutris’s empty fresh-VM aggregator UX. Stores remain the guaranteed front door.

### Task 11: Validate and classify EA/Ubisoft support

**Objective:** Establish honest production support rather than equating a launch script with full compatibility.

**Validation:** Installer, login, relaunch, persistent state, game install, non-anti-cheat game launch, controller, audio, and reconnect.

**Documentation categories:** Supported, works without anti-cheat, untested, known blocked.

### Task 12: Add per-store Proton compatibility profiles

**Objective:** Allow Battle.net, EA, and Ubisoft to use independently tested GE-Proton versions and flags.

**Work:**
1. Add versioned per-store configuration.
2. Preserve current GE-Proton11-3 default.
3. Track prefix schema/version.
4. Implement prefix migration or repair while preserving installed games.

### Task 13: Pre-bake complete store prefixes through privileged CI

**Objective:** Make first launch primarily a login instead of downloading runtimes and installing launchers.

**Work:**
1. Create a privileged BuildKit builder with `security.insecure` entitlement.
2. Produce versioned prefix artifacts/layers.
3. Verify prefix content and marker files.
4. Copy to the user volume on first launch.
5. Keep runtime fallback when prebake fails or becomes stale.

### Task 14: Add microphone passthrough

**Objective:** Browser microphone should appear as a virtual PipeWire source for in-game voice and communications apps.

**Validation:** Permission flow, mute/unmute, latency, reconnect, device cleanup, and no cross-session leakage.

---

## P2 — Streaming, performance, and boot speed

### Task 15: Bake correct provider drivers into VM templates

**Objective:** Remove recurring cold-boot driver replacement on Scaleway and UpCloud.

**Work:**
1. Create/test provider-specific Ubuntu templates with open-580 already installed.
2. Retain OVH desktop proprietary 580 unchanged.
3. Confirm modeset, CDI generation, EGL/GBM, NVENC, reboot behaviour, and provider snapshot boot time.
4. Adopt only where template boot time is faster overall; OVH private snapshots were already shown to be a net loss.

### Task 16: Complete CUDA zero-copy capture

**Objective:** Replace system-memory RGBx upload/conversion with direct GPU-memory NV12 into NVENC.

**Options:**
- Add native NV12 CUDAMemory output to `gst-wayland-display`.
- Patch Selkies/GStreamer dynamic pad linking and caps negotiation.

**Validation:** Compare CPU, GPU copy utilisation, frame time, encoder latency, visual correctness, all resolutions, and multi-session load against the current validated pipeline.

### Task 17: Add adaptive bitrate

**Objective:** Dynamically react to RTT, packet loss, congestion, and decoder feedback.

**Work:**
1. Collect WebRTC stats.
2. Define safe min/max bitrate per resolution/FPS/tier.
3. Adjust encoder bitrate without destabilising the pipeline.
4. Coordinate FEC overhead with available bitrate.
5. Test clean, lossy, high-latency, and bandwidth-changing links.

### Task 18: Add codec negotiation

**Objective:** Keep H.264 as universal fallback while adding HEVC and AV1 where the GPU/browser supports them.

**Validation matrix:** GPU encoder support, browser support, hardware decode, latency, quality per bitrate, reconnect, and fallback.

### Task 19: Add 120 FPS profiles

**Objective:** Offer 1080p120 and potentially 1440p120 for suitable tiers.

**Work:** Coordinate compositor mode, GStreamer framerate, encoder settings, browser rendering, bitrate policy, and control-plane entitlements.

### Task 20: Instrument motion-to-photon latency

**Objective:** Quantify every performance change instead of relying on subjective stream feel.

**Measurement points:** Browser input, server receipt, application/compositor frame, NVENC submission/completion, RTP send, browser receive/decode/render.

### Task 21: Tune and harden audio

**Objective:** Reduce measured latency and let audio reconnect independently of the desktop.

**Work:** Validate PipeWire quantum/buffers under load, add independent audio recovery, and retain Opus FEC controls.

---

## P3 — Input, storage, and future platform work

### Task 22: Migrate controller input to inputtino/uinput

**Objective:** Replace the six-layer LD_PRELOAD/interposer path with real virtual input devices.

**Requirements:**
- Keyboard/mouse/gamepad across native Wayland and XWayland.
- Correct hotplug.
- 32-bit game compatibility.
- Multiple controllers.
- No cross-session device visibility.
- Keep existing chain until real-controller validation passes.

### Task 23: Add force-feedback return path

**Objective:** Carry game rumble from the virtual controller back to the browser Gamepad Haptics API where supported.

### Task 24: Preserve controller identity

**Objective:** Allow Xbox, DualShock, and DualSense identities instead of always exposing an Xbox 360 device, improving button prompts and device-specific features.

### Task 25: Split profile state from game storage

**Objective:** Let users retain logins, saves, and launcher settings on a small durable volume without requiring a large games disk.

**Proposed layout:**
- Small profile volume: account tokens, configs, saves, prefix metadata.
- Large games volume: installed games, bulk prefix game data, shader caches.

### Task 26: Add save backup and volume health checks

**Objective:** Protect saves and detect stale/corrupt mounts before starting Steam or a store.

### Task 27: Evaluate shared game-data deduplication

**Objective:** Determine whether read-only seeded game data with per-user writable overlays can materially reduce download/storage costs without breaking updates or anti-cheat.

**Constraint:** Treat as a research spike only; launcher patching and anti-cheat make this risky.

### Task 28: Plan HDR separately

**Objective:** Define an end-to-end HDR architecture covering Wayland colour management, 10-bit surfaces, P010, HEVC/AV1 metadata, browser decode/render, and display capability detection.

### Task 29: Re-evaluate Electron only if measured

**Objective:** Avoid an unnecessary rewrite. Consider Tauri, GTK4, SDL3-native, or Godot only if Electron startup/memory materially affects session cost or responsiveness.

---

## 3. Cross-Cutting Verification Matrix

Every compositor, driver, streaming, or input change must verify:

1. Providers/drivers: OVH desktop 580, Scaleway open-580, UpCloud open-580, Hyperstack R570-open, MassedCompute R580-open.
2. GPU families: at least L4/Ada and RTX 50/Blackwell where affected.
3. Session density: 1:1, 2:1, and 3:1 when compositor/input/encoder code changes.
4. UI: Dpad launcher renders, gamepad navigation, store open/return, browser refresh recovery.
5. Stores: Steam, Battle.net, Epic/GOG Heroic, then EA and Ubisoft after validation.
6. Inputs: keyboard, absolute mouse, relative mouse, scroll direction, one and multiple controllers.
7. Media: image, audio, reconnect, packet loss, each supported resolution.
8. Persistence: fresh ephemeral session and reused persistent volume.
9. Security: each container sees only its assigned GPU, volume, input devices, and credentials.
10. Boot performance: record cold-boot milestones and compare with baseline.

---

## 4. Guardrails

- Do not replace the production Wayland architecture with gamescope-headless; gamescope-headless remains fallback only.
- Do not reintroduce blanket `chown -R` over the pre-baked home directory.
- Preserve the Steam install root on the persistent volume.
- Preserve volume lookup by label/exclusion rather than virtio drive letter.
- Keep unattended upgrades disabled on live gaming hosts.
- Mouse scroll mapping is intentionally inverted at the X button layer: button 5 = scroll up and button 4 = scroll down. Do not “correct” it.
- `ensure_driver_580` stays Scaleway-gated; do not apply it globally.
- UpCloud 595 → open-580 downgrade is mandatory until a newly validated driver changes the matrix.
- Browser WebRTC tests must use HTTPS.
- Keep H.264 as codec fallback.
- Keep current gamepad interposers until inputtino clears real-controller end-to-end validation.

---

## 5. Recommended Starting Sequence

When work resumes, do not attack the entire roadmap at once. Start in this order:

1. Pin Selkies and release artifacts.
2. Add immutable image release tags/digests.
3. Decouple the desktop lifetime from WebRTC peer lifetime.
4. Upgrade/test Sway/wlroots to eliminate teardown SIGTRAP.
5. Improve launcher state/onboarding and add the session overlay.
6. Validate EA/Ubisoft and implement compatibility labels.
7. Build provider templates for Scaleway/UpCloud.
8. Instrument latency, then attempt zero-copy/adaptive bitrate/codec work.
9. Migrate input to inputtino only after the desktop/stream lifecycle is stable.

This order prioritises not getting lost: first make builds and rollbacks deterministic, then remove session instability, then improve user-visible UX, and only afterward optimise performance or rewrite input internals.
