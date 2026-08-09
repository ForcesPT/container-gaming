# dpad-launcher

A 10-foot, gamepad/keyboard-navigable **store launcher** that runs as the
session shell (where `lutris-shell` ran before). It's a front door to the
installed store clients — Steam (available), Battle.net / Epic / GOG / EA /
Ubisoft ("coming soon") — instead of Lutris's library-aggregator model (which
showed "no games found" on a fresh VM until each store was logged in + synced).

Selecting a store card spawns that store's client (e.g. `steam -gamepadui`) in
the same sway/XWayland session; quitting the store returns to the launcher.

## Files
- `src/main.js` — Electron main: kiosk fullscreen window; IPC `launch-store`
  (spawns the store client, inheriting the session env); `poll-gamepads` (SDL3).
- `src/preload.js` — contextBridge IPC (getStores / launchStore / pollGamepads / quit).
- `src/renderer.js` — keyboard + gamepad nav, focus, the launch overlay.
- `src/index.html` + `src/styles.css` — the UI (graphite6 palette, from the live site).
- `src/stores` — the store registry is in `main.js` (Steam available; rest coming-soon).
- `src/sdl_bindings.cjs` + `src/sdl_manager.cjs` — koffi/SDL3 gamepad (ported from
  lutris-gamepad-ui; the Web Gamepad API doesn't see the mknod'd pads in-container).
- `src/logos/*.svg` — bundled brand logos (generated from `simple-icons` via
  `scripts/gen-logos.js`; no runtime internet — the container's CSP is `img-src 'self'`).
- `scripts/build.sh` — cross-build the Linux AppDir in a node container
  (`electron-builder --linux dir`; output `dist/linux-unpacked/`).
- `scripts/gen-logos.js` — regenerate `src/logos/*.svg` from simple-icons.
- `Dockerfile` — package the AppDir into `forcespt/dpadcloud-launcher`
  (FROM scratch, COPY the AppDir to `/opt/dpadcloud/launcher`); the
  container-gaming Dockerfile `COPY --from=forcespt/dpadcloud-launcher:0.1.0`
  bakes it into the `:dpad-SteamOS` image.
- `../scripts/launcher-shell` — the wrapper the entrypoint execs as sway's
  startup app (`DPAD_STORE_SHELL=picker`).

## Build + ship
```bash
npm install                       # local deps (for `npm start` preview)
npm start                         # local preview (DPAD_LAUNCHER_DEV=1 mocks Steam available)
./scripts/build.sh                # cross-build the Linux AppDir -> dist/linux-unpacked/
docker build -t forcespt/dpadcloud-launcher:0.1.0 -t forcespt/dpadcloud-launcher:latest .
docker push forcespt/dpadcloud-launcher:0.1.0
docker push forcespt/dpadcloud-launcher:latest
```

## Runtime env (set by the entrypoint's session `shared_env`, same as lutris-shell)
- `DISPLAY=:0` (sway's XWayland), `__EGL_VENDOR_LIBRARY_FILENAMES=10_nvidia.json`,
  `VK_ICD_FILENAMES`, `XDG_RUNTIME_DIR`, `PULSE_SERVER`, `HOME`, `USER`.
- Gamepad (SDL3/koffi): `SDL_JOYSTICK_LINUX_CLASSIC=1`, `SDL_JOYSTICK_DISABLE_UDEV=1`,
  `SDL_JOYSTICK_DEVICE=/dev/input/js0`, `SDL_GAMECONTROLLERCONFIG` (the Selkies mapping),
  `LD_PRELOAD=/usr/$LIB/selkies_joystick_interposer.so` (the classic interposer).

## Controls
- Navigate: arrow keys / d-pad / left stick.
- Launch: Enter / gamepad A. Cancel overlay / quit store-back: Esc / gamepad B.
- The launch overlay (store logo + spinner) is dismissed only by B/Esc.

## Wiring
`entrypoint.sh`: `DPAD_STORE_SHELL=picker` → `SHELL_APP=/opt/dpadcloud/launcher-shell`
(both the wayland-display + gamescope-headless paths). The control plane sets
`DPAD_STORE_SHELL=picker` (the cloud worker writes it to `/etc/environment`).