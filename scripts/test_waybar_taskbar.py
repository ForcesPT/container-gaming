#!/usr/bin/env python3
"""Release boundary: Waybar is the only Labwc taskbar implementation."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MAIN = (ROOT / "launcher/src/main.js").read_text()
PRELOAD = (ROOT / "launcher/src/preload.js").read_text()
PUBLISHER = (ROOT / "scripts/dpad-publish-desktop-config").read_text()

for forbidden in (
    "createTaskbarWindow",
    "DpadPlay Taskbar",
    "get-taskbar-state",
    "focus-taskbar-item",
    "close-taskbar-item",
    "configureX11DockWindow",
    "positionX11DockWindow",
):
    if forbidden in MAIN:
        raise SystemExit(f"launcher still contains custom taskbar behavior: {forbidden}")

for forbidden in ("getTaskbarState", "focusTaskbarItem", "closeTaskbarItem"):
    if forbidden in PRELOAD:
        raise SystemExit(f"preload still exposes custom taskbar IPC: {forbidden}")

for path in (
    ROOT / "launcher/src/taskbar.js",
    ROOT / "launcher/src/taskbar.html",
    ROOT / "launcher/src/taskbar.css",
    ROOT / "launcher/src/x11_dock.cjs",
):
    if path.exists():
        raise SystemExit(f"obsolete Electron taskbar asset remains: {path.name}")

for required in ("wlr/taskbar", '"layer": "overlay"', '"start_hidden": false', '"passthrough": false'):
    if required not in PUBLISHER:
        raise SystemExit(f"Waybar publisher missing contract: {required}")

if "on-click-middle" in PUBLISHER:
    raise SystemExit("Waybar must not close arbitrary taskbar windows on middle click")

if '"mode":' in PUBLISHER:
    raise SystemExit("Waybar preset modes override the required overlay layer in 0.9.24")

print("Waybar is the sole Labwc taskbar: PASS")
