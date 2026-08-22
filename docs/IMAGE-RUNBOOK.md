# DpadPlay Gaming Image Runbook

> **Current source architecture (2026-08-16): launcher-only desktop.** The image
> has one production runtime: Selkies with `gst-wayland-display` as the compositor
> and capture source, nested Sway as the default desktop/XWayland provider, and the
> DpadPlay store launcher as the sole session shell. Steam is Valve's official
> Linux desktop client, installed in the image and opened from the Steam card.
> There is no alternate compositor, Steam shell, or Big Picture startup path.
>
> Current release: `forcespt/dpadcloud-gaming:dpad-SteamOS-2026.08.16-r8` and
> convenience tag `:dpad-SteamOS`, both digest
> `sha256:00c837725076e8a46f083b7edc21873a58914de35f9b68c9c00a6ea827d008c2`.
> It was built and GPU/restart-tested on an OVH NVIDIA L4 from runtime revision
> `f8b69b57255f1f1ad5f634f991478f66add13cdb`. Production OVH is pinned to
> this immutable digest; `r7` digest
> `sha256:b85954a28aa37c8e9c2bb1e86db7314b5eecaa6136f4cf8c0d5fed4c5b259209`
> is the immediate rollback.
>
> **Experimental canary (2026-08-22):** candidate source also installs Labwc
> 0.7.1 from Ubuntu Noble and accepts `DPAD_DESKTOP_CLIENT=labwc`. This changes
> only the nested desktop/XWayland provider and preserves Sway as the default.
> Labwc is not production-approved until OVH GPU and user testing complete. Its
> launcher recovery and the prebuilt launcher's limited Sway IPC calls are
> translated through Noble's `wlrctl` foreign-toplevel client.
>
> `r8` preserves the same Smithay compositor, Wayland socket, nested Sway,
> XWayland, and DpadPlay launcher across transient signaling/browser disconnects.
> It also removes process-owned stale Wayland socket paths and the stale Sway
> health marker before a genuinely new Selkies process, allowing Docker restart
> and Selkies relaunch recovery without touching a live reconnect-persistent
> compositor. On a GPU builder, validate a candidate with:
> `python3 scripts/test_reconnect_persistence_gpu.py <candidate-image>`.
> A release gate also requires real Chromium decode/input cycles before and
> after Docker restart; an SDP offer alone is not sufficient media evidence.

## Build and publish

Run from the repository root on a Docker host:

```bash
docker build --target vast-vm \
  --label org.opencontainers.image.revision="$(git rev-parse HEAD)" \
  -t forcespt/dpadcloud-gaming:dpad-SteamOS .
docker push forcespt/dpadcloud-gaming:dpad-SteamOS
```

For production, also tag an immutable release and canary that exact tag before
moving the convenience tag or provider configuration.

The final image includes:

- Valve's official Steam Linux desktop client, pre-bootstrapped on Xvfb.
- `/usr/local/bin/steam`, a stable desktop-client target used by the launcher.
- DpadPlay launcher, Heroic, Lutris, umu, GE-Proton, and store wrappers.
- Selkies 1.6.2, `gst-wayland-display`, Sway/Labwc, XWayland, `wlrctl`, PipeWire, coturn, and NVENC.
- No retired compositor binaries or alternate Steam startup mode.

## Warm-VM deployment

`vm-bootstrap.sh` prepares the driver, Docker, image, MPS, and host sysctls:

```bash
curl -fsSL \
  https://raw.githubusercontent.com/ForcesPT/container-gaming/main/scripts/vm-bootstrap.sh \
  -o /root/vm-bootstrap.sh
chmod +x /root/vm-bootstrap.sh
bash /root/vm-bootstrap.sh install
journalctl -u dpadcloud-bootstrap -f
```

A normal session is launched by the control plane with:

```bash
dpad-launch-session launch \
  <slot> <volume-id-or-none> <provider-device> <selkies-password> \
  forcespt/dpadcloud-gaming:dpad-SteamOS
```

`dpad-launch-session` always supplies `/dev/dri`, one assigned NVIDIA GPU,
2 GiB shared memory, the bwrap/user-namespace security flags, TURN and Selkies
ports, the user's optional library volume, and the selected resource quota.

## Direct GPU smoke test

On a prepared GPU VM:

```bash
VM_IP=<public-ip> \
IMAGE=forcespt/dpadcloud-gaming:dpad-SteamOS \
bash scripts/wayland-display-probe.sh
```

Then open the HTTPS route that proxies the VM's Selkies port. Direct plain HTTP
may not establish WebRTC because browsers require a secure context.

Expected flow:

1. `DPAD_READY` appears when Selkies is listening.
2. The browser peer starts `waylanddisplaysrc` and creates `wayland-N`.
3. The entrypoint starts the selected nested desktop (Sway by default, Labwc for the canary).
4. The selected desktop opens the DpadPlay launcher.
5. Selecting **Steam** opens Valve's standard desktop application.
6. Closing Steam returns the user to the DpadPlay launcher.

## Runtime configuration

| Variable | Default | Purpose |
|---|---:|---|
| `DPAD_STORES` | unset | Comma-separated store state to wire, e.g. `steam,epic,gog,battlenet,ea-app,ubisoft`. It does not choose the shell; the DpadPlay launcher is always the shell. |
| `DPAD_DESKTOP_CLIENT` | `sway` | Nested desktop/XWayland provider: `sway` (production default) or `labwc` (experimental stacking canary). Any other value fails closed. |
| `DPAD_VOLUME_MOUNT` | unset | In-container persistent library mount. Steam's complete install root is linked to `<volume>/steam-install`. |
| `DPAD_GAMEPAD_INTERPOSER` | classic | Set `evdev` for the fake-libudev + evdev interposer path. |
| `DPAD_ENCODER` | `nvh264enc` | Selkies encoder. Use another validated Selkies encoder only after a GPU/browser canary. |
| `DPAD_WD_WIDTH` / `DPAD_WD_HEIGHT` | `1920` / `1080` | Initial compositor and Sway output resolution. |
| `DPAD_STREAM_WIDTH` / `DPAD_STREAM_HEIGHT` | `1920` / `1080` | Values forwarded by the session launcher; normally match the compositor size. |
| `DPAD_STREAM_FPS` | `60` | Initial Selkies/compositor capture frame rate. Supported presets are 30, 60, 120, 144, and 240; unsupported or malformed values fail closed before constructing the Selkies command. The worker passes the user's selected launch profile per session; live Selkies FPS changes continue to use the patched `set_framerate` path. |
| `DPAD_SELKIES_BIND` | `127.0.0.1` | Production session launcher sets `0.0.0.0` for stream-bridge access. |
| `DPAD_COTURN_PORT` | `3478` | Coturn listening port inside the container. |
| `DPAD_TURN_RELAY_MIN_PORT` / `DPAD_TURN_RELAY_MAX_PORT` | unset | Optional bounded coturn UDP allocation range. Production host-network sessions receive a required per-slot 64-port range from `dpad-launch-session`; both values must be present, four or five decimal digits, unprivileged, ordered, and no greater than 65535 or startup fails closed. |
| `DPAD_TURN_PUBLIC_IP` | discovered | Public VM address placed in external TURN ICE entries. |
| `DPAD_TURN_UDP_EXTERNAL_PORT` | unset | Externally mapped UDP TURN port. |
| `DPAD_TURN_EXTERNAL_PORT` | unset | Externally mapped TCP TURN fallback. |
| `DPAD_DEFAULT_GAMING_MODE` | `0` | `1` starts relative-pointer gaming mode; `0` starts visible-cursor desktop mode. |
| `DPAD_INPUT_HOTFIX` | `0` | `1` overlays the current input patches from repository `main` at boot. |
| `DPAD_AUDIO_PACKETLOSS` | `0` | Opus packet-loss/FEC percentage passed to Selkies. |
| `DPAD_VIDEO_PACKETLOSS` | `0` | Video FEC percentage passed to Selkies. |
| `DPAD_NVENC_FIX` | `auto` | Multi-GPU NVENC visibility interposer: `auto`, `1`, or `0`. |

The old compositor/shell selection variables are intentionally unsupported and
are not forwarded by `dpad-launch-session` or `vm-bootstrap.sh`.

`dpad-launch-session` reserves UDP `40000-40063` for slot 0, then advances by
64 ports per slot (`40064-40127` for slot 1, etc.). Sessions use host networking
to avoid Docker relay hairpin failures; coturn is constrained with `--min-port`
and `--max-port`. Provider firewalls/security groups must allow every active
slot's TURN listener (`3478 + slot`), Selkies listener (`16100 + slot`), and relay
range. WebSocket signaling or an input data channel alone does not prove that
video relay packets are reachable. Slot values are canonical integers `0-31`;
all other values fail before shell arithmetic.

## Healthy boot milestones

```text
[*] Launcher-only desktop: gst-wayland-display + nested Sway + DpadPlay launcher
[*] Steam is installed as a standard store application and opens from the DpadPlay launcher.
[*] Starting PipeWire + wireplumber...
[*] Starting pipewire-pulse (PulseAudio compat) + null audio sink...
[*] Launching selkies (wayland-display compositor; video_src=waylanddisplaysrc, encoder=nvh264enc)...
DPAD_READY slot=<n> bind=0.0.0.0:16100 encoder=nvh264enc
[*] Compositor socket wayland-<n> appeared — launching Sway + DpadPlay launcher
```

Useful logs inside the container:

- `/tmp/selkies.log`
- `/run/dpadcloud/sway-client.log`
- `/run/dpadcloud/labwc-client.log` (Labwc canary only)
- `/tmp/launcher.log`
- `/tmp/pipewire.log`
- `/tmp/pipewire-pulse.log`
- `/tmp/coturn.log`
- `/tmp/steam-bootstrap.log`

## Driver matrix

- OVH desktop proprietary 580: keep.
- Scaleway 580-server: swap to open 580.
- UpCloud 595: downgrade to open 580.
- Hyperstack R570-open: keep.
- MassedCompute R580-open: keep.
- `ensure_driver_580` remains provider-gated; do not make it universal.

## Troubleshooting

| Symptom | Cause / fix |
|---|---|
| Container exits before `DPAD_READY` | Inspect `/tmp/selkies.log`, PipeWire logs, and `docker logs`. Verify `/dev/dri` and the assigned NVIDIA device are exposed. |
| `waylanddisplaysrc` EGL init fails with `dri2 screen` | Wrong provider driver variant. Apply the driver matrix above; Scaleway server-580 and UpCloud 595 are not usable. |
| `DPAD_READY` appears but no launcher after connecting | Inspect `/run/dpadcloud/${DPAD_DESKTOP_CLIENT:-sway}-client.log`; verify the browser reached Selkies through HTTPS and created a real WebRTC peer. |
| Steam card appears to do nothing | Inspect `/tmp/launcher.log`, `/tmp/steam-bootstrap.log`, and Steam processes. Verify `/usr/local/bin/steam` and `/usr/bin/steam` are executable. |
| Steam opens an unexpected presentation mode | The image is stale. Current source installs `/usr/local/bin/steam`, which always starts the standard desktop client even if a cached launcher bundle supplies obsolete flags. |
| Steam login or games disappear after relaunch | Verify the volume is mounted at `DPAD_VOLUME_MOUNT` and `~/.steam/debian-installation` resolves to `<volume>/steam-install`. |
| Steam CEF crash-loop / shared-context failure | Ensure the container has `--shm-size=2g` and `vm.max_map_count=1048576`. |
| No audio | Verify `pipewire`, `pipewire-pulse`, the Pulse socket, `dummy` sink, and `dummy.monitor`. |
| No gamepad | Check Selkies joystick sockets/nodes and the selected interposer. The DpadPlay launcher itself uses SDL3 through koffi. |
| No TURN relay / browser stays on `Waiting for stream` while input works | Verify host networking and that the slot's TURN listener, Selkies listener, and complete relay range are allowed by the provider firewall. Confirm coturn received matching `DPAD_TURN_RELAY_MIN_PORT`/`MAX_PORT` values and its process includes the expected `--min-port`/`--max-port`. Signaling and an open input data channel do not prove media relay reachability. |
| Browser remains on waiting state after reconnect | A peer disconnect must not restart Selkies or the selected desktop. Check `/tmp/selkies.log` for pipeline errors and verify the selected-desktop/XWayland/launcher PID+start-time identities and the `wayland-N` socket inode did not change. A dead Selkies process is a separate process-relaunch path. |
| Container remains `starting` after Docker restart | Confirm the entrypoint cleaned stale numeric `wayland-N` socket/lock paths and both protected desktop logs immediately before starting the new Selkies process. Do not move this cleanup into peer-disconnect handling. |
| Live resolution changed but old size remains | Use the drawer's Refresh action after selecting a resolution; NVENC/WebRTC requires a fresh peer pipeline. |

## Source validation

```bash
python3 scripts/test_launcher_only_architecture.py
python3 scripts/test_desktop_client_selection.py
python3 scripts/test_desktop_runtime_helpers.py
python3 scripts/test_turn_relay_plumbing.py
python3 scripts/test_obsolete_components_removed.py
python3 scripts/test_stream_fps_plumbing.py
python3 scripts/test_dockerfile_pins.py
python3 scripts/test_dockerfile_pins_mutations.py
bash -n entrypoint.sh healthcheck.sh scripts/dpad-launch-session scripts/vm-bootstrap.sh \
  scripts/launcher-toggle scripts/dpad-publish-desktop-config scripts/swaymsg-desktop-compat
```

A source-only pass is not a production release. A new image must still be built,
inspected, and exercised on an NVIDIA VM before promotion.
