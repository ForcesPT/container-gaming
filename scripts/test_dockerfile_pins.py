#!/usr/bin/env python3
"""Regression checks for release-critical Dockerfile download pins."""

from pathlib import Path
import re
import sys


dockerfile = Path(__file__).resolve().parents[1] / "Dockerfile"
text = dockerfile.read_text()

required_versions = {
    "SELKIES_VERSION": r"\d+\.\d+\.\d+",
    "GE_PROTON_VERSION": r"GE-Proton\d+-\d+",
    "UMU_VERSION": r"\d+\.\d+\.\d+",
}
required_sha256 = (
    "SELKIES_GSTREAMER_SHA256",
    "SELKIES_WHEEL_SHA256",
    "SELKIES_WEB_SHA256",
    "SELKIES_INTERPOSER_SHA256",
    "WAYLAND_SHA256",
    "GST_WAYLAND_DISPLAY_SHA256",
    "GE_PROTON_SHA256",
    "UMU_SHA256",
)

errors: list[str] = []
for name, value_pattern in required_versions.items():
    match = re.search(rf"^ARG {name}=([^\s#]+)", text, re.MULTILINE)
    if not match:
        errors.append(f"missing pinned version ARG {name}")
    elif not re.fullmatch(value_pattern, match.group(1)):
        errors.append(f"invalid pinned version ARG {name}={match.group(1)!r}")

for name in required_sha256:
    match = re.search(rf"^ARG {name}=([0-9a-f]{{64}})$", text, re.MULTILINE)
    if not match:
        errors.append(f"missing non-empty 64-hex checksum ARG {name}")

if "repos/selkies-project/selkies/releases/latest" in text:
    errors.append("Selkies version still floats through GitHub releases/latest")

if re.search(r"curl[^\n]*\\\n\s*\|\s*tar", text):
    errors.append("Dockerfile still pipes a network response directly into tar")

for url_fragment in ("gitlab.freedesktop.org/wayland/wayland", "github.com/games-on-whales/gst-wayland-display/archive"):
    block_start = text.rfind(url_fragment)
    block = text[max(0, block_start - 300):block_start + 500]
    if block_start < 0 or "--retry" not in block:
        errors.append(f"download for {url_fragment} lacks bounded curl retries")

for name in required_sha256:
    if not re.search(rf"sha256sum -c[^\n]*|echo \"\${{{name}}}", text):
        # The Dockerfile uses multi-line shell commands, so require at least a
        # variable reference in a sha256sum verification block below.
        if f"${{{name}}}" not in text or "sha256sum -c" not in text:
            errors.append(f"checksum {name} is declared but not used for verification")

if errors:
    print("Dockerfile pin validation failed:", file=sys.stderr)
    for error in errors:
        print(f"- {error}", file=sys.stderr)
    raise SystemExit(1)

print("Dockerfile release-critical downloads are version- and SHA256-pinned")
