#!/usr/bin/env python3
"""Regression guard for selectable Sway/Labwc desktop clients."""

from pathlib import Path
import sys

root = Path(__file__).resolve().parents[1]
errors: list[str] = []

dockerfile = (root / "Dockerfile").read_text()
entrypoint = (root / "entrypoint.sh").read_text()
launcher = (root / "scripts/dpad-launch-session").read_text()
healthcheck = (root / "healthcheck.sh").read_text()
toggle = (root / "scripts/launcher-toggle").read_text()
publisher = (root / "scripts/dpad-publish-desktop-config").read_text()

for required in (
    "sway labwc wlrctl xwayland util-linux",
    "command -v labwc",
    "labwc --version",
    "command -v wlrctl",
    "command -v flock",
    "COPY scripts/dpad-publish-desktop-config /opt/dpadcloud/dpad-publish-desktop-config",
    "COPY scripts/swaymsg-desktop-compat /usr/local/bin/swaymsg",
):
    if required not in dockerfile:
        errors.append(f"Dockerfile missing desktop package contract: {required}")

for required in (
    'DPAD_DESKTOP_CLIENT="${DPAD_DESKTOP_CLIENT:-sway}"',
    'sway|labwc)',
    'Unsupported DPAD_DESKTOP_CLIENT',
    "_launch_labwc()",
    "exec labwc --config-dir /run/dpadcloud/labwc-current",
    "/run/dpadcloud/labwc-client.log",
    "start_launcher_session || exit 1",
    "if ! install -d -o root -g root -m 0755 /run/dpadcloud",
    "/run/dpadcloud/sway-client.log /run/dpadcloud/labwc-client.log",
    "exec sway --unsupported-gpu -c /run/dpadcloud/sway.config -d",
    "/opt/dpadcloud/dpad-publish-desktop-config sway",
    "/opt/dpadcloud/dpad-publish-desktop-config labwc",
    "SWAYSOCK=${XDG_RUNTIME_DIR}/sway-ipc.labwc-compat.sock",
    'if _launch_desktop "$wl_name"; then',
    "refusing partial desktop state",
):
    if required not in entrypoint:
        errors.append(f"entrypoint missing desktop selection contract: {required}")

for unsafe in ("/tmp/dpad-sway.config", "/tmp/dpad-labwc"):
    if unsafe in entrypoint:
        errors.append(f"desktop configuration remains in world-writable /tmp: {unsafe}")

for required in (
    '[ "$EUID" -eq 0 ] && [ "$RUNTIME_DIR" != /run/dpadcloud ]',
    'flock -x 9',
    'mktemp -d "$RUNTIME_DIR/labwc.gen.XXXXXX"',
    'ln -s "$(basename "$generation")" "$link_tmp"',
    'mv -fT "$link_tmp" "$RUNTIME_DIR/labwc-current"',
    'current_target="$(readlink "$RUNTIME_DIR/labwc-current")"',
):
    if required not in publisher:
        errors.append(f"publisher missing atomic Labwc generation contract: {required}")

if '-e DPAD_DESKTOP_CLIENT="${DPAD_DESKTOP_CLIENT:-sway}"' not in launcher:
    errors.append("session launcher does not forward DPAD_DESKTOP_CLIENT with a Sway default")

for required in (
    'DPAD_DESKTOP_CLIENT:-sway',
    'window focus title:DpadPlay',
    'window focus app_id:com.dpadplay.launcher',
    'MATCH=title:DpadPlay',
    'MATCH=app_id:com.dpadplay.launcher',
    'window fullscreen "$MATCH"',
):
    if required not in toggle:
        errors.append(f"launcher-toggle missing Labwc recovery contract: {required}")

for required in (
    'desktop="${DPAD_DESKTOP_CLIENT:-sway}"',
    "/run/dpadcloud/${desktop}-client.log",
    'pgrep -x "$desktop"',
):
    if required not in healthcheck:
        errors.append(f"healthcheck missing selected-desktop contract: {required}")

gpu_test = (root / "scripts/test_reconnect_persistence_gpu.py").read_text()
for required in (
    'DESKTOP = os.environ.get("DPAD_DESKTOP_CLIENT", "sway")',
    '"-e", f"DPAD_DESKTOP_CLIENT={DESKTOP}"',
    'wait_process_identity(DESKTOP)',
    'assert_identity(DESKTOP, desktop',
    'if restarted_desktop == desktop:',
    'if restarted_xwayland == xwayland:',
    'if restarted_launcher == launcher:',
    'if restarted_socket == socket:',
):
    if required not in gpu_test:
        errors.append(f"GPU reconnect gate is not selected-desktop-aware: {required}")

if errors:
    print("Desktop-client selection validation failed:", file=sys.stderr)
    for error in errors:
        print(f"- {error}", file=sys.stderr)
    raise SystemExit(1)

print("Selectable Sway/Labwc desktop-client architecture is enforced")
