#!/usr/bin/env python3
"""Source contract for Selkies input routing through the Smithay seat."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PATCH = (ROOT / "scripts/dpad_input_patch.py").read_text()
DOCKERFILE = (ROOT / "Dockerfile").read_text()
ENTRYPOINT = (ROOT / "entrypoint.sh").read_text()

for required in (
    "import dpad_wayland_input as wayland_input",
    'native_wayland = os.environ.get("DPAD_DESKTOP_CLIENT") == "labwc"',
    "wayland_input.pointer_motion_absolute(x, y)",
    "wayland_input.pointer_motion_relative(x, y)",
    "wayland_input.pointer_button(linux_button, pressed)",
    "wayland_input.pointer_axis(0, 120)",
    "wayland_input.pointer_axis(0, -120)",
    "wayland_input.keyboard_key(kc - 8, down)",
    "LINUX_BUTTON =",
    "MOUSE_BUTTON_LEFT: 0x110",
    "MOUSE_BUTTON_RIGHT: 0x111",
    "MOUSE_BUTTON_MIDDLE: 0x112",
):
    if required not in PATCH:
        raise SystemExit(f"Selkies patch missing Wayland input route: {required}")

if PATCH.index("wayland_input.pointer_motion_absolute(x, y)") > PATCH.index("d = _get_dpy()", PATCH.index("def send_mouse")):
    raise SystemExit("mouse routing still waits for XWayland before trying the Wayland seat")

for required in (
    "COPY scripts/dpad_wayland_input.py /usr/local/lib/python3.12/dist-packages/dpad_wayland_input.py",
    "test -f /usr/local/lib/python3.12/dist-packages/dpad_wayland_input.py",
):
    if required not in DOCKERFILE:
        raise SystemExit(f"Dockerfile missing Wayland input bridge wiring: {required}")

if "DPAD_INPUT_DISPLAY=:0 DPAD_DESKTOP_CLIENT=${DPAD_DESKTOP_CLIENT}" not in ENTRYPOINT:
    raise SystemExit("Selkies launch does not receive the validated desktop-client gate")

print("Selkies Wayland-first input routing: PASS")
