#!/usr/bin/env python3
"""Regression: deterministic installer click must not mutate X focus."""
from pathlib import Path
import runpy
import sys
import types

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/build-click-x11.py"
events = []


class Geometry:
    width = 480
    height = 480


class Translation:
    x = -400
    y = -120


class Pointer:
    root_x = 640
    root_y = 551


class Window:
    def get_wm_name(self):
        return "EA\xa0app installer"

    def get_geometry(self):
        return Geometry()

    def translate_coords(self, _root, _x, _y):
        return Translation()

    def raise_window(self):
        raise AssertionError("installer click must not raise/focus the Wine window")

    def set_input_focus(self, *_args):
        raise AssertionError("installer click must not raise/focus the Wine window")


class Root:
    def query_tree(self):
        return types.SimpleNamespace(children=[Window()])

    def get_geometry(self):
        return types.SimpleNamespace(width=1280, height=720)

    def warp_pointer(self, x, y):
        events.append(("warp", x, y))

    def query_pointer(self):
        return Pointer()


class Display:
    def __init__(self, _name):
        self.root = Root()

    def screen(self):
        return types.SimpleNamespace(root=self.root)

    def sync(self):
        events.append(("sync",))


xlib = types.ModuleType("Xlib")
xlib.X = types.SimpleNamespace(ButtonPress=4, ButtonRelease=5)
xlib.display = types.SimpleNamespace(Display=Display)
xlib_ext = types.ModuleType("Xlib.ext")
xlib_ext.xtest = types.SimpleNamespace(
    fake_input=lambda _display, event_type, button: events.append(("button", event_type, button))
)
sys.modules["Xlib"] = xlib
sys.modules["Xlib.ext"] = xlib_ext
sys.argv = [
    str(SCRIPT),
    "--display", ":9",
    "--title-part", "ea",
    "--title-part", "installer",
    "--timeout", "1",
    "--x-fraction", "0.5",
    "--y-from-bottom", "49",
]
runpy.run_path(str(SCRIPT), run_name="__main__")
buttons = [event for event in events if event[0] == "button"]
if buttons != [("button", 4, 1), ("button", 5, 1)]:
    raise SystemExit(f"installer click did not emit one press/release pair: {buttons}")
if ("warp", 640, 551) not in events:
    raise SystemExit(f"installer click used unexpected geometry: {events}")
warp_index = events.index(("warp", 640, 551))
press_index = events.index(("button", 4, 1))
release_index = events.index(("button", 5, 1))
if not warp_index < press_index < release_index:
    raise SystemExit(f"installer click event ordering is unsafe: {events}")
if not any(event[0] == "sync" for event in events[warp_index + 1:press_index]):
    raise SystemExit(f"installer pointer warp was not synchronized before click: {events}")
print("Build X11 installer click behavior: PASS")
