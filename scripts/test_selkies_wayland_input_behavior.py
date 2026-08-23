#!/usr/bin/env python3
"""Behavioral harness for Wayland-first Selkies mouse/key routing."""

import importlib.util
import os
from pathlib import Path
import subprocess
import sys
import types

ROOT = Path(__file__).resolve().parents[1]
PATCH = ROOT / "scripts" / "dpad_input_patch.py"
os.environ["DPAD_INPUT_DISPLAY"] = ":0"
desktop = os.environ.get("DPAD_TEST_DESKTOP", "labwc")
os.environ["DPAD_DESKTOP_CLIENT"] = desktop

records = []
xtest_records = []
display_ready = False


class FakeDisplay:
    def keysym_to_keycode(self, _keysym):
        return 30

    def sync(self):
        pass

    def screen(self):
        return types.SimpleNamespace(root=1)


def open_display(_name):
    if not display_ready:
        raise RuntimeError("XWayland not ready")
    return FakeDisplay()


class WebRTCInput:
    def connect(self):
        pass

    def _WebRTCInput__keyboard_connect(self):
        pass

    def _WebRTCInput__mouse_connect(self):
        pass

    def reset_keyboard(self):
        pass

    def send_x11_keypress(self, *_args):
        records.append(("original-key", _args))

    def send_mouse(self, *_args):
        records.append(("original-mouse", _args))

    def on_message(self, msg):
        return msg

    def start_cursor_monitor(self):
        return None


webrtc = types.ModuleType("webrtc_input")
setattr(webrtc, "WebRTCInput", WebRTCInput)
for name, value in {
    "MOUSE_BUTTON_LEFT": 1,
    "MOUSE_BUTTON_MIDDLE": 2,
    "MOUSE_BUTTON_RIGHT": 3,
    "MOUSE_POSITION": 10,
    "MOUSE_MOVE": 11,
    "MOUSE_SCROLL_UP": 12,
    "MOUSE_SCROLL_DOWN": 13,
    "MOUSE_BUTTON": 14,
    "MOUSE_BUTTON_PRESS": 15,
    "MOUSE_BUTTON_RELEASE": 16,
}.items():
    setattr(webrtc, name, value)

selkies = types.ModuleType("selkies_gstreamer")
setattr(selkies, "webrtc_input", webrtc)
xlib = types.ModuleType("Xlib")
setattr(xlib, "display", types.SimpleNamespace(Display=open_display))
setattr(xlib, "X", types.SimpleNamespace(
    KeyPress=2,
    KeyRelease=3,
    MotionNotify=6,
    ButtonPress=4,
    ButtonRelease=5,
    NONE=0,
))
xlib_ext = types.ModuleType("Xlib.ext")
setattr(xlib_ext, "xtest", types.SimpleNamespace(fake_input=lambda *_a, **_k: xtest_records.append((_a, _k))))
xlib_protocol = types.ModuleType("Xlib.protocol")
xlib_protocol_display = types.ModuleType("Xlib.protocol.display")
setattr(xlib_protocol_display, "Display", type("ProtocolDisplay", (), {}))
setattr(xlib_protocol, "display", xlib_protocol_display)

wayland = types.ModuleType("dpad_wayland_input")
setattr(wayland, "pointer_motion_absolute", lambda x, y: records.append(("absolute", x, y)) or True)
setattr(wayland, "pointer_motion_relative", lambda x, y: records.append(("relative", x, y)) or True)
setattr(wayland, "pointer_button", lambda button, pressed: records.append(("button", button, pressed)) or True)
setattr(wayland, "pointer_axis", lambda x, y: records.append(("axis", x, y)) or True)
setattr(wayland, "keyboard_key", lambda key, pressed: records.append(("key", key, pressed)) or True)

sys.modules.update({
    "webrtc_input": webrtc,
    "selkies_gstreamer": selkies,
    "selkies_gstreamer.webrtc_input": webrtc,
    "Xlib": xlib,
    "Xlib.ext": xlib_ext,
    "Xlib.protocol": xlib_protocol,
    "Xlib.protocol.display": xlib_protocol_display,
    "dpad_wayland_input": wayland,
})

spec = importlib.util.spec_from_file_location("dpad_input_patch_under_test", PATCH)
if spec is None or spec.loader is None:
    raise SystemExit("could not load dpad input patch")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

client = WebRTCInput()

if desktop == "sway":
    display_ready = True
    client.send_mouse(webrtc.MOUSE_POSITION, (40, 50))
    client.send_mouse(webrtc.MOUSE_BUTTON, (webrtc.MOUSE_BUTTON_PRESS, webrtc.MOUSE_BUTTON_LEFT))
    client.send_x11_keypress(0x61, True)
    assert records == []
    assert [event[0][1] for event in xtest_records] == [
        xlib.X.MotionNotify,
        xlib.X.ButtonPress,
        xlib.X.KeyPress,
    ]
    print("Sway retains its XTest-only input path: PASS")
    raise SystemExit(0)

client.send_mouse(webrtc.MOUSE_POSITION, (40, 50))
client.send_mouse(webrtc.MOUSE_MOVE, (-2, 3))
client.send_mouse(webrtc.MOUSE_BUTTON, (webrtc.MOUSE_BUTTON_PRESS, webrtc.MOUSE_BUTTON_LEFT))
client.send_mouse(webrtc.MOUSE_SCROLL_DOWN, None)

assert records == [
    ("absolute", 40, 50),
    ("relative", -2, 3),
    ("button", 0x110, True),
    ("axis", 0, -120),
]
assert xtest_records == []

# Keyboard keysyms need XWayland only for keysym -> evdev conversion. Once it
# appears, the resulting evdev code still goes through the Wayland seat.
display_ready = True
client.send_x11_keypress(0x61, True)
assert records[-1] == ("key", 22, True)
assert xtest_records == []

# A rejected compositor event must fall back to XTest rather than dropping
# input. Cover both pointer and keyboard routes.
setattr(wayland, "pointer_button", lambda button, pressed: records.append(("rejected-button", button, pressed)) or False)
client.send_mouse(webrtc.MOUSE_BUTTON, (webrtc.MOUSE_BUTTON_RELEASE, webrtc.MOUSE_BUTTON_LEFT))
assert records[-1] == ("rejected-button", 0x110, False)
assert xtest_records[-1][0][1] == xlib.X.ButtonRelease
assert xtest_records[-1][1]["detail"] == 1

setattr(wayland, "keyboard_key", lambda key, pressed: records.append(("rejected-key", key, pressed)) or False)
client.send_x11_keypress(0x61, False)
assert records[-1] == ("rejected-key", 22, False)
assert xtest_records[-1][0][1] == xlib.X.KeyRelease
assert xtest_records[-1][1]["detail"] == 30

subprocess.run(
    [sys.executable, str(Path(__file__).resolve())],
    env={**os.environ, "DPAD_TEST_DESKTOP": "sway"},
    check=True,
)

print("Selkies routes input to Wayland before XTest: PASS")
