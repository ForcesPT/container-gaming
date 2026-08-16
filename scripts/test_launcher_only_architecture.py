#!/usr/bin/env python3
"""Regression guard for the launcher-only Steam desktop architecture."""

from pathlib import Path
import re
import sys

root = Path(__file__).resolve().parents[1]
errors: list[str] = []

runtime_files = (
    "Dockerfile",
    "entrypoint.sh",
    "healthcheck.sh",
    "scripts/dpad-launch-session",
    "scripts/vm-bootstrap.sh",
    "scripts/build-bootstrap-steam.sh",
    "scripts/wayland-display-probe.sh",
    "scripts/relaunch-probe.sh",
)

retired_tokens = (
    "gamescope",
    "gamepadui",
    "DPAD_GAMESCOPE",
    "DPAD_WAYLAND_CLIENT",
    "DPAD_STORE_SHELL",
)

for relative in runtime_files:
    text = (root / relative).read_text()
    for retired in retired_tokens:
        if retired in text:
            errors.append(f"{relative} still references retired token {retired}")

entrypoint = (root / "entrypoint.sh").read_text()
for required in (
    "start_launcher_session()",
    'SHELL_APP="/opt/dpadcloud/launcher-shell"',
    "exec sway --unsupported-gpu",
    "waylanddisplaysrc",
):
    if required not in entrypoint:
        errors.append(f"entrypoint missing launcher-only requirement: {required}")

launcher = (root / "launcher/src/main.js").read_text()
steam = re.search(r"id:\s*'steam'.*?cmd:\s*\[([^\]]*)\]", launcher, re.S)
if not steam:
    errors.append("launcher Steam store definition is missing")
elif steam.group(1).strip() != "'steam'":
    errors.append(f"launcher must start the official desktop Steam app without modes: [{steam.group(1).strip()}]")

launch_session = (root / "scripts/dpad-launch-session").read_text()
if "--device /dev/dri" not in launch_session:
    errors.append("session launcher must always expose /dev/dri to gst-wayland-display")

steam_wrapper = (root / "scripts/steam-desktop").read_text()
if "exec /usr/bin/steam" not in steam_wrapper:
    errors.append("desktop Steam wrapper must exec Valve's official client")
if "COPY scripts/steam-desktop /usr/local/bin/steam" not in (root / "Dockerfile").read_text():
    errors.append("image must install the desktop Steam wrapper ahead of the cached launcher bundle")
if "HEALTHCHECK" not in (root / "Dockerfile").read_text():
    errors.append("launcher desktop healthcheck is not installed in the final image")

healthcheck = (root / "healthcheck.sh").read_text()
for required in ("selkies-gstreamer", "pipewire", "sway"):
    if required not in healthcheck:
        errors.append(f"healthcheck does not require {required}")

if (root / "scripts/gamescope-headless-drmprops.patch").exists():
    errors.append("retired gamescope patch still exists")

if errors:
    print("Launcher-only architecture validation failed:", file=sys.stderr)
    for error in errors:
        print(f"- {error}", file=sys.stderr)
    raise SystemExit(1)

print("Launcher-only Steam desktop architecture is enforced")
