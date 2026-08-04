# Gamepad input — evdev path (gated, default OFF; pending rebuild + real-gamepad validation)

This directory holds the **evdev interposer + fake-libudev** approach for gamepad
input in containers. **Wired but gated** behind `DPAD_GAMEPAD_INTERPOSER=evdev`
(default unset = the classic path below); the `.so` files are built into the
image (Dockerfile `interposer-builder`) + the entrypoint sets up the nodes /
LD_PRELOAD / starts `scripts/evdev_bridge.py` only when the gate is set.
**Pending:** an image rebuild + Docker Hub push (the `.so` files need baking),
then live validation with a real controller.
The default gamepad path is the **classic joystick path** (see entrypoint.sh
`start_gamescope_session`): `SDL_JOYSTICK_LINUX_CLASSIC=1` +
`SDL_JOYSTICK_DEVICE=/dev/input/js0` + the installed v1.6.2
`selkies_joystick_interposer.so`. That path was validated end-to-end (the
interposer handles SDL3's full classic `JSIOCG*` probe sequence + serves
`js_event` structs) and is UNCHANGED by this work (the evdev branch is opt-in).

## When to use this fallback

Only if Steam's bundled SDL3 turns out NOT to honor `SDL_HINT_JOYSTICK_LINUX_CLASSIC`
(i.e. the classic path doesn't make Steam detect the gamepad with a real
controller). The evdev path is the "official" Selkies container-gamepad solution
(Selkies issue #168 / PR #173 + `addons/fake-udev`).

## What it is

Steam ships SDL3, which discovers gamepads via **libudev + evdev**
(`/dev/input/event*`) — it ignores the legacy `/dev/input/js*` API. The container
has **no udev**, so neither a real evdev device nor a uinput device gets a
`/dev/input/eventN` node for SDL3 to discover. The official fix is two
companion LD_PRELOAD libraries:

- **`fake-udev/fake-libudev-core.c`** → build to `libudev.so.1`. LD_PRELOAD it to
  lie to libudev so SDL3 "discovers" 4 virtual Microsoft X-Box 360 pads at
  `/dev/input/js0-3` + `/dev/input/event1000-1003` (no real kernel devices, no
  udev). Validated: a libudev enumeration test sees all 8 nodes with
  `ID_INPUT_JOYSTICK=1`.
- **`joystick_interposer_main.c`** (the `main`-branch evdev interposer, NOT the
  v1.6.2 one) → build to `selkies_joystick_interposer.so`. Intercepts
  `open()`/`ioctl()`/`read()` on those fake paths → Selkies' gamepad sockets.
  Reads a NEW `js_config_t` (1360 bytes: name[255]+pad + vendor/product/version/
  num_btns/num_axes (5x u16) + btn_map[512](u16) + axes_map[64](u8) + padding[6])
  and, for evdev clients, reads `sizeof(input_event)=24` bytes per event directly
  from the socket (NO js_event→input_event translation — the server must send
  `input_event` structs on `selkies_event100N.sock`).

## Why it's only the fallback (the cost)

- The new interposer's socket protocol is **incompatible** with the installed
  v1.6.2 `gamepad.py` (new `js_config_t` + a 1-byte arch-byte handshake).
- The new interposer does NOT translate js_event→input_event (confirmed live
  2026-08-05: it `recv`s `sizeof(input_event)` raw into the app buffer); the
  **server must dual-serve**: `js_event` (8B) on `selkies_jsN.sock` AND
  `input_event`+SYN (24B/16B per the client's `sizeof(long)`) on
  `selkies_event100N.sock`. The v1.6.2 `SelkiesGamepad` only serves the js socket.
  **This is now implemented WITHOUT monkey-patching Selkies** by `scripts/evdev_bridge.py`
  — an external asyncio bridge: connects to the js socket (client), reads the
  1-byte arch specifier from the interposer, and translates each `js_event` →
  `input_event`+`EV_SYN` (BUTTON→`EV_KEY`/`BTN_MAP`, AXIS→`EV_ABS`/`AXES_MAP`) on
  the event socket. **Validated live 2026-08-05 on OVH Gravelines L4** (feeder →
  bridge → real evdev interposer → evclient: `EV_KEY code=304 value=1` BTN_A,
  `EV_ABS code=0 value=10000` ABS_X — correct, not garbled). `../dpad_gamepad_patch.py`
  still makes v1.6.2 emit the 1360B config the bridge discards (gated on the same env).
- Plus `mknod` of dummy `/dev/input/js{0-3}` + `/dev/input/event100{0-3}` (major 13)
  — done by the entrypoint's evdev branch (static nodes; the health loop supervises
  `evdev_bridge.py`).

The classic path avoids ALL of that (two env vars + the already-installed
v1.6.2 interposer).

## Build (if needed)

```bash
# fake-libudev
cd fake-udev && make           # -> libudev.so.1
# evdev interposer (x86_64; add -m32 + gcc-multilib for the i386 Wine path)
gcc -shared -fPIC -O2 -Wall -ldl -o selkies_joystick_interposer.so joystick_interposer_main.c
# dummy nodes (root; major 13)
mkdir -pm1777 /dev/input
for i in 0 1 2 3; do mknod /dev/input/js$i c 13 $i; done
for i in 0 1 2 3; do n=$((1000+i)); mknod /dev/input/event$n c 13 $((64+n)); done
chmod 666 /dev/input/js* /dev/input/event100*
# launch with: LD_PRELOAD=/path/libudev.so.1:/path/selkies_joystick_interposer.so
```

## Validation artifacts in this repo's scripts/

- `../dpad_gamepad_patch.py` — `.pth` monkey-patch making v1.6.2 `SelkiesGamepad.__make_config`
  emit the 1360-byte new `js_config_t` (validated: 1360 bytes, vendor 0x045e). The
  dual-serve event dispatch (input_event on the event100N socket) is NOT in it.
- `../jsfeeder_main.py` — socket feeder speaking the new config protocol (for testing).
- `../evclient.c` — C client that opens `/dev/input/event1000` and reads `input_event`s.
- `../udev_enumerate_test.c` — libudev enumeration test (proves fake-libudev discovery).
- `../jsclassic.c` — C client mimicking SDL3's classic probe sequence (proves the v1.6.2
  interposer handles it — the ACTIVE path's validation).