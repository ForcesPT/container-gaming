#!/usr/bin/env python3
"""Regression checks for release-critical Dockerfile download pins."""

from pathlib import Path
import re
import sys


text = (Path(__file__).resolve().parents[1] / "Dockerfile").read_text()

expected_args = {
    "SELKIES_VERSION": "1.6.2",
    "SELKIES_GSTREAMER_SHA256": "339ca3ab35eb8c2ad7de9a8a3dc59292a9cffe11ebf4bc6bc6a9397de23f9b90",
    "SELKIES_WHEEL_SHA256": "f426ae093853492ecf857609efd4c9bd2141b24c619118561e42220927554eee",
    "SELKIES_WEB_SHA256": "71fcc35d59f8d8a6c6b72472c20a45af207ab56a0d0553af34b731a2e966d0c6",
    "SELKIES_INTERPOSER_SHA256": "84edf046587de0e2284186b90601cc2c08670042c1bd38b46a4f02d677704c4d",
    "LIBWAYLAND_VERSION": "1.23.1",
    "WAYLAND_SHA256": "158ec49af498f2558c7fbf7e8b070d010d4e270cc6076003a18a6c813f87e244",
    "GST_WAYLAND_DISPLAY_REF": "b15285a2f1bb4dae5725b049915a4971664fafc6",
    "GST_WAYLAND_DISPLAY_SHA256": "0aecd9df1a5a50a3a9b21ccc00468f4e1f4054242468e5c63fd7e09d542c9e29",
    "GE_PROTON_VERSION": "GE-Proton11-3",
    "GE_PROTON_SHA256": "861c2edc8d40d051fb1e7a692deb953be52bd339c46d90f2b7dde50ddad91266",
    "UMU_VERSION": "1.4.4",
    "UMU_SHA256": "86b7a234f77fbcd13699654656192a12ed3852ec2bcc721506ae4f91436b3793",
}

# Each tuple binds a checksum to its exact downloaded filename and the next
# command that may run only after verification succeeds. Shared Selkies assets
# deliberately form one explicit verification chain.
artifacts = (
    ("SELKIES_GSTREAMER_SHA256", "${SELKIES_GSTREAMER}", "${SELKIES_GSTREAMER}", 'echo "${SELKIES_WHEEL_SHA256}', False),
    ("SELKIES_WHEEL_SHA256", "${SELKIES_WHEEL}", "${SELKIES_WHEEL}", 'echo "${SELKIES_WEB_SHA256}', False),
    ("SELKIES_WEB_SHA256", "${SELKIES_WEB}", "${SELKIES_WEB}", 'echo "${SELKIES_INTERPOSER_SHA256}', False),
    ("SELKIES_INTERPOSER_SHA256", "${SELKIES_INTERPOSER}", "${SELKIES_INTERPOSER}", 'tar -xzf "${SELKIES_GSTREAMER}"', False),
    ("WAYLAND_SHA256", "gitlab.freedesktop.org/wayland/wayland", "/tmp/${WAYLAND_ARCHIVE}", 'tar -xzf "/tmp/${WAYLAND_ARCHIVE}"', False),
    ("GST_WAYLAND_DISPLAY_SHA256", "github.com/games-on-whales/gst-wayland-display/archive", "/tmp/${GWD_ARCHIVE}", 'tar -xzf "/tmp/${GWD_ARCHIVE}"', False),
    ("GE_PROTON_SHA256", "/tmp/ge-proton.tar.gz", "/tmp/ge-proton.tar.gz", "tar -xzf /tmp/ge-proton.tar.gz", True),
    ("UMU_SHA256", "/tmp/umu.deb", "/tmp/umu.deb", "apt-get update && (", True),
)

errors: list[str] = []
runs = re.findall(r"(?ms)^RUN\s+.*?(?=^[A-Z][A-Z]+(?:\s|$)|\Z)", text)

for name, expected in expected_args.items():
    if not re.search(rf"^ARG {re.escape(name)}={re.escape(expected)}$", text, re.MULTILINE):
        errors.append(f"expected exact pin ARG {name}={expected}")

if "repos/selkies-project/selkies/releases/latest" in text:
    errors.append("Selkies version still floats through GitHub releases/latest")
if re.search(r"\|\s*tar\b", text):
    errors.append("Dockerfile still pipes a network response directly into tar")

for checksum, marker, checksum_target, next_command, allows_fatal_handler in artifacts:
    blocks = [run for run in runs if marker in run and f"${{{checksum}}}" in run]
    if len(blocks) != 1:
        errors.append(f"expected one download RUN coupling {marker} to {checksum}, found {len(blocks)}")
        continue
    block = blocks[0]
    normalized = block.replace("\\\n", " ")
    verify_match = re.search(
        rf'echo\s+"\$\{{{re.escape(checksum)}\}}\s{{2}}{re.escape(checksum_target)}"\s*\|\s*sha256sum\s+-c\s+-',
        normalized,
    )
    if not verify_match:
        errors.append(f"{checksum} is not bound to exact target {checksum_target}")
        continue
    if normalized.count(f"${{{checksum}}}") != 1:
        errors.append(f"{checksum} must appear exactly once in its artifact RUN")
    next_index = normalized.find(next_command, verify_match.end())
    if next_index < 0:
        errors.append(f"required successor for {checksum} is missing: {next_command}")
    else:
        bridge = normalized[verify_match.end() : next_index]
        direct_gate = r"\s*&&\s*"
        fatal_gate = r"\s*\|\|\s*\{[^{}]*\bexit\s+1\s*;?\s*\}\s*&&\s*"
        allowed_gate = fatal_gate if allows_fatal_handler else direct_gate
        if not re.fullmatch(allowed_gate, bridge):
            errors.append(
                f"{checksum} does not exclusively gate its required successor"
            )
    pre_verify = normalized[: verify_match.start()]
    if re.search(
        rf"(?:tar\b|pip3\s+install|apt-get\s+install)[^&;\n]*{re.escape(marker)}",
        pre_verify,
    ):
        errors.append(f"artifact for {checksum} is consumed before verification")
    curl_commands = [
        command
        for command in normalized.split("&&")
        if "curl " in command and marker in command
    ]
    if len(curl_commands) != 1:
        errors.append(f"expected one curl command for {marker}, found {len(curl_commands)}")
    elif not all(flag in curl_commands[0] for flag in ("--retry 8", "--retry-all-errors", "--retry-delay 3")):
        errors.append(f"download for {marker} lacks bounded curl retries")

if errors:
    print("Dockerfile pin validation failed:", file=sys.stderr)
    for error in errors:
        print(f"- {error}", file=sys.stderr)
    raise SystemExit(1)

print("Dockerfile release-critical downloads are exactly pinned and verified")
