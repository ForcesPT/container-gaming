#!/usr/bin/env python3
"""Regression guard for retired tunnel and alternate-shell components."""

from pathlib import Path
import sys


root = Path(__file__).resolve().parents[1]
errors: list[str] = []

for relative in (
    "Dockerfile",
    "entrypoint.sh",
    "docker-compose.yml",
    "scripts/dpad-launch-session",
    "scripts/launcher-shell",
    "scripts/vm-bootstrap.sh",
    "scripts/wayland-display-probe.sh",
    "scripts/relaunch-probe.sh",
    "scripts/test_dockerfile_pins.py",
    "scripts/test_dockerfile_pins_mutations.py",
):
    text = (root / relative).read_text()
    for retired in (
        "cloudflared",
        "CLOUDFLARED",
        "trycloudflare",
        "DPAD_TUNNEL",
        "lutris-gamepad-ui",
        "LUTRIS_GAMEPAD_UI",
        "lutris-shell",
        "DPAD_LUTRIS_",
        "DPAD_ORCHESTRATOR_PUBKEY",
        "DPAD_SSH_ENDPOINT",
    ):
        if retired in text:
            errors.append(f"{relative} still references retired token {retired}")

if (root / "scripts/lutris-shell").exists():
    errors.append("scripts/lutris-shell still exists")

# Lutris remains a compatibility/backend component; SDL3 remains the DpadPlay
# launcher's native gamepad-input dependency.
dockerfile = (root / "Dockerfile").read_text()
if "ARG LUTRIS_VERSION=" not in dockerfile or "lutris.deb" not in dockerfile:
    errors.append("Lutris backend was removed unexpectedly")
if "ARG SDL3_VERSION=" not in dockerfile or "libSDL3.so.0" not in dockerfile:
    errors.append("SDL3 launcher input dependency was removed unexpectedly")
if "start_launcher_session" not in (root / "entrypoint.sh").read_text():
    errors.append("DpadPlay launcher session is no longer wired")

launch_session = (root / "scripts/dpad-launch-session").read_text()
if '-p "${selkies_port}:16100"' not in launch_session:
    errors.append("per-slot Selkies host-port publication is missing")
if "DPAD_STORE_SHELL" in launch_session:
    errors.append("retired shell-selection environment is still forwarded")

if errors:
    print("Obsolete component cleanup validation failed:", file=sys.stderr)
    for error in errors:
        print(f"- {error}", file=sys.stderr)
    raise SystemExit(1)

print("Obsolete cloudflared and lutris-gamepad-ui paths are removed")
