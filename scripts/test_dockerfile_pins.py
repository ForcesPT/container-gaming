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
    "SDL3_VERSION": "3.2.28",
    "SDL3_SHA256": "1330671214d146f8aeb1ed399fc3e081873cdb38b5189d1f8bb6ab15bbc04211",
    "VIRTUALGL_VERSION": "3.1.4",
    "VIRTUALGL_SHA256": "02edc6b599571c385389af1a006f07a70c298e1d97c580a9bfd4b39d835c51e6",
    "HEROIC_VERSION": "v2.22.0",
    "HEROIC_SHA256": "4c8585ad7c7a76bd3c8058aa995b9064f457603f3b6afbd9114433cf4af7ecd2",
    "VKD3D_PROTON_TAG": "v2.14.1",
    "VKD3D_PROTON_FILE": "vkd3d-proton-2.14.1",
    "VKD3D_PROTON_SHA256": "03c354bed971a3e35b73ca2d626658f67999626c4e99626ce2a39734a86e7dbd",
    "DXVK_VERSION": "dxvk-3.0.2",
    "DXVK_SHA256": "9c538924110a7cdef871ca36dee218c0774124374ffdeb38af4b76be55bdf7c2",
    "DXVK_NVAPI_VERSION": "dxvk-nvapi-v0.9.2",
    "DXVK_NVAPI_SHA256": "60c284223530d643c446c263f1e1a96c6de7b5ff21796219646da734d97a70d6",
    "LUTRIS_VERSION": "v0.5.22",
    "LUTRIS_SHA256": "88a350357e0438b423cdf93108f27942de094dc19f973df73839f3b0b0bafaa0",
}

# checksum, curl marker, checksum target, gated successor, fatal-handler allowed,
# exact URL template, ARGs which must be in scope in the consuming stage.
artifacts = (
    ("SELKIES_GSTREAMER_SHA256", "${SELKIES_GSTREAMER}", "${SELKIES_GSTREAMER}", 'echo "${SELKIES_WHEEL_SHA256}', False, '"${SELKIES_BASE}/${SELKIES_GSTREAMER}"', ("SELKIES_VERSION", "SELKIES_GSTREAMER_SHA256")),
    ("SELKIES_WHEEL_SHA256", "${SELKIES_WHEEL}", "${SELKIES_WHEEL}", 'echo "${SELKIES_WEB_SHA256}', False, '"${SELKIES_BASE}/${SELKIES_WHEEL}"', ("SELKIES_VERSION", "SELKIES_WHEEL_SHA256")),
    ("SELKIES_WEB_SHA256", "${SELKIES_WEB}", "${SELKIES_WEB}", 'echo "${SELKIES_INTERPOSER_SHA256}', False, '"${SELKIES_BASE}/${SELKIES_WEB}"', ("SELKIES_VERSION", "SELKIES_WEB_SHA256")),
    ("SELKIES_INTERPOSER_SHA256", "${SELKIES_INTERPOSER}", "${SELKIES_INTERPOSER}", 'tar -xzf "${SELKIES_GSTREAMER}"', False, '"${SELKIES_BASE}/${SELKIES_INTERPOSER}"', ("SELKIES_VERSION", "SELKIES_INTERPOSER_SHA256")),
    ("WAYLAND_SHA256", "gitlab.freedesktop.org/wayland/wayland", "/tmp/${WAYLAND_ARCHIVE}", 'tar -xzf "/tmp/${WAYLAND_ARCHIVE}"', False, '"https://gitlab.freedesktop.org/wayland/wayland/-/archive/${LIBWAYLAND_VERSION}/${WAYLAND_ARCHIVE}"', ("LIBWAYLAND_VERSION", "WAYLAND_SHA256")),
    ("GST_WAYLAND_DISPLAY_SHA256", "github.com/games-on-whales/gst-wayland-display/archive", "/tmp/${GWD_ARCHIVE}", 'tar -xzf "/tmp/${GWD_ARCHIVE}"', False, '"https://github.com/games-on-whales/gst-wayland-display/archive/${GST_WAYLAND_DISPLAY_REF}.tar.gz"', ("GST_WAYLAND_DISPLAY_REF", "GST_WAYLAND_DISPLAY_SHA256")),
    ("GE_PROTON_SHA256", "/tmp/ge-proton.tar.gz", "/tmp/ge-proton.tar.gz", "tar -xzf /tmp/ge-proton.tar.gz", True, '"https://github.com/GloriousEggroll/proton-ge-custom/releases/download/${GE_PROTON_VERSION}/${GE_PROTON_VERSION}.tar.gz"', ("GE_PROTON_VERSION", "GE_PROTON_SHA256")),
    ("UMU_SHA256", "/tmp/umu.deb", "/tmp/umu.deb", "apt-get update && (", True, '"https://github.com/Open-Wine-Components/umu-launcher/releases/download/${UMU_VERSION}/python3-umu-launcher_${UMU_VERSION}-1_amd64_ubuntu-noble.deb"', ("UMU_VERSION", "UMU_SHA256")),
    ("SDL3_SHA256", "SDL3.tar.gz", "SDL3.tar.gz", "tar -xzf SDL3.tar.gz", False, '"https://github.com/libsdl-org/SDL/releases/download/release-${SDL3_VERSION}/SDL3-${SDL3_VERSION}.tar.gz"', ("SDL3_VERSION", "SDL3_SHA256")),
    ("VIRTUALGL_SHA256", "virtualgl_${VIRTUALGL_VERSION}_amd64.deb", "vgl.deb", "(dpkg -i vgl.deb", False, '"https://github.com/VirtualGL/virtualgl/releases/download/${VIRTUALGL_VERSION}/virtualgl_${VIRTUALGL_VERSION}_amd64.deb"', ("VIRTUALGL_VERSION", "VIRTUALGL_SHA256")),
    ("HEROIC_SHA256", "/tmp/${HEROIC_DEB}", "/tmp/${HEROIC_DEB}", '( dpkg -i "/tmp/${HEROIC_DEB}"', False, '"https://github.com/Heroic-Games-Launcher/HeroicGamesLauncher/releases/download/${HEROIC_VERSION}/${HEROIC_DEB}"', ("HEROIC_VERSION", "HEROIC_SHA256")),
    ("VKD3D_PROTON_SHA256", "/tmp/vkd3d.tar.xz", "/tmp/vkd3d.tar.xz", "tar -xf /tmp/vkd3d.tar.xz", False, '"https://github.com/Heroic-Games-Launcher/vkd3d-proton/releases/download/${VKD3D_PROTON_TAG}/${VKD3D_PROTON_FILE}.tar.xz"', ("VKD3D_PROTON_TAG", "VKD3D_PROTON_FILE", "VKD3D_PROTON_SHA256")),
    ("DXVK_SHA256", "/tmp/dxvk.tar.gz", "/tmp/dxvk.tar.gz", "tar -xzf /tmp/dxvk.tar.gz", False, '"https://github.com/doitsujin/dxvk/releases/download/v${DXVK_VERSION#dxvk-}/${DXVK_VERSION}.tar.gz"', ("DXVK_VERSION", "DXVK_SHA256")),
    ("DXVK_NVAPI_SHA256", "/tmp/dxvk-nvapi.tar.gz", "/tmp/dxvk-nvapi.tar.gz", "tar -xzf /tmp/dxvk-nvapi.tar.gz", False, '"https://github.com/jp7677/dxvk-nvapi/releases/download/${DXVK_NVAPI_VERSION#dxvk-nvapi-}/${DXVK_NVAPI_VERSION}.tar.gz"', ("DXVK_NVAPI_VERSION", "DXVK_NVAPI_SHA256")),
    ("LUTRIS_SHA256", "/tmp/lutris.deb", "/tmp/lutris.deb", "apt-get update && (", False, '"https://github.com/lutris/lutris/releases/download/${LUTRIS_VERSION}/lutris_${LUTRIS_VERSION#v}_all.deb"', ("LUTRIS_VERSION", "LUTRIS_SHA256")),
)


def docker_runs(source: str) -> list[tuple[str, set[str], str]]:
    """Return RUN text, ARGs in scope, and stage name."""
    lines = source.splitlines()
    runs: list[tuple[str, set[str], str]] = []
    stage = "<global>"
    stage_args: set[str] = set()
    index = 0
    while index < len(lines):
        line = lines[index]
        if re.match(r"^FROM\s+", line):
            stage = line
            stage_args = set()
        else:
            arg = re.match(r"^ARG\s+([A-Za-z_][A-Za-z0-9_]*)", line)
            if arg and stage != "<global>":
                stage_args.add(arg.group(1))
        if line.startswith("RUN "):
            body = [line]
            while body[-1].rstrip().endswith("\\") and index + 1 < len(lines):
                index += 1
                body.append(lines[index])
            runs.append(("\n".join(body), set(stage_args), stage))
        index += 1
    return runs


def shell_control_errors(command: str) -> list[str]:
    """Reject top-level success masking after a guarded download starts."""
    issues: list[str] = []
    curl_at = command.find("curl ")
    quote = None
    parens = braces = 0
    escaped = False
    index = 0
    while index < len(command):
        char = command[index]
        if escaped:
            escaped = False
            index += 1
            continue
        if char == "\\":
            escaped = True
            index += 1
            continue
        if quote:
            if char == quote:
                quote = None
            index += 1
            continue
        if char in "'\"":
            quote = char
        elif char == "(":
            parens += 1
        elif char == ")":
            parens = max(0, parens - 1)
        elif char == "{":
            braces += 1
        elif char == "}":
            braces = max(0, braces - 1)
        elif char == ";" and parens == braces == 0 and index > curl_at >= 0:
            issues.append("top-level ';' after curl can mask a guarded failure")
        elif command.startswith("||", index) and parens == braces == 0:
            rhs = command[index + 2:].lstrip()
            if not rhs or rhs[0] not in "({":
                issues.append("top-level || fallback is not a fatal group")
            else:
                opener, closer = rhs[0], ")" if rhs[0] == "(" else "}"
                depth = 0
                end = None
                rhs_quote = None
                rhs_escaped = False
                for rhs_index, rhs_char in enumerate(rhs):
                    if rhs_escaped:
                        rhs_escaped = False
                        continue
                    if rhs_char == "\\":
                        rhs_escaped = True
                        continue
                    if rhs_quote:
                        if rhs_char == rhs_quote:
                            rhs_quote = None
                        continue
                    if rhs_char in "'\"":
                        rhs_quote = rhs_char
                    elif rhs_char == opener:
                        depth += 1
                    elif rhs_char == closer:
                        depth -= 1
                        if depth == 0:
                            end = rhs_index
                            break
                group = rhs[:end + 1] if end is not None else ""
                if not re.search(r"\bexit\s+1\b", group):
                    issues.append("top-level || fallback group is not fatal")
            index += 1
        index += 1
    return issues


errors: list[str] = []
runs = docker_runs(text)
checked_shell_blocks: set[str] = set()
approved_urls_by_block: dict[str, set[str]] = {}

for name, expected in expected_args.items():
    if not re.search(rf"^ARG {re.escape(name)}={re.escape(expected)}$", text, re.MULTILINE):
        errors.append(f"expected exact pin ARG {name}={expected}")

if "repos/selkies-project/selkies/releases/latest" in text:
    errors.append("Selkies version still floats through GitHub releases/latest")
if re.search(r"\|\s*tar\b", text):
    errors.append("Dockerfile still pipes a network response directly into tar")

for checksum, marker, checksum_target, successor, allows_fatal, exact_url, required_args in artifacts:
    matches = [(run, args, stage) for run, args, stage in runs if marker in run and f"${{{checksum}}}" in run]
    if len(matches) != 1:
        errors.append(f"expected one download RUN coupling {marker} to {checksum}, found {len(matches)}")
        continue
    block, stage_args, stage = matches[0]
    missing_args = sorted(set(required_args) - stage_args)
    if missing_args:
        errors.append(f"{stage} lacks in-scope ARGs for {checksum}: {', '.join(missing_args)}")

    normalized = block.replace("\\\n", " ")
    approved_urls_by_block.setdefault(normalized, set()).add(exact_url)
    if normalized not in checked_shell_blocks:
        for issue in shell_control_errors(normalized):
            errors.append(f"{checksum} RUN: {issue}")
        checked_shell_blocks.add(normalized)
    verify_match = re.search(
        rf'echo\s+"\$\{{{re.escape(checksum)}\}}\s{{2}}{re.escape(checksum_target)}"\s*\|\s*sha256sum\s+-c\s+-',
        normalized,
    )
    if not verify_match:
        errors.append(f"{checksum} is not bound to exact target {checksum_target}")
        continue
    if normalized.count(f"${{{checksum}}}") != 1:
        errors.append(f"{checksum} must appear exactly once in its artifact RUN")

    next_index = normalized.find(successor, verify_match.end())
    if next_index < 0:
        errors.append(f"required successor for {checksum} is missing: {successor}")
    else:
        bridge = normalized[verify_match.end():next_index]
        direct_gate = r"\s*&&\s*"
        fatal_gate = r"\s*\|\|\s*\{[^{}]*\bexit\s+1\s*;?\s*\}\s*&&\s*"
        if not re.fullmatch(fatal_gate if allows_fatal else direct_gate, bridge):
            errors.append(f"{checksum} does not exclusively gate its required successor")

    pre_verify = normalized[:verify_match.start()]
    if not pre_verify.rstrip().endswith("&&"):
        errors.append(f"{checksum} verification is negated or not AND-gated")
    if re.search(rf"(?:tar\b|pip3\s+install|apt-get\s+install)[^&;]*{re.escape(marker)}", pre_verify):
        errors.append(f"artifact for {checksum} is consumed before verification")

    curl_commands = [command for command in normalized.split("&&") if "curl " in command and marker in command]
    if len(curl_commands) != 1:
        errors.append(f"expected one curl command for {marker}, found {len(curl_commands)}")
    else:
        curl_command = curl_commands[0]
        if exact_url not in curl_command:
            errors.append(f"download for {marker} does not use exact URL template {exact_url}")
        if not all(flag in curl_command for flag in ("--retry 8", "--retry-all-errors", "--retry-delay 3")):
            errors.append(f"download for {marker} lacks bounded curl retries")

for block, approved_urls in approved_urls_by_block.items():
    curl_commands = [command for command in block.split("&&") if "curl " in command]
    if len(curl_commands) != len(approved_urls):
        errors.append(
            f"guarded RUN has {len(curl_commands)} curl commands but "
            f"{len(approved_urls)} approved URLs"
        )
    for command in curl_commands:
        matched_urls = [url for url in approved_urls if url in command]
        if len(matched_urls) != 1:
            errors.append("guarded RUN contains a curl command without one exact approved URL")

if errors:
    print("Dockerfile pin validation failed:", file=sys.stderr)
    for error in errors:
        print(f"- {error}", file=sys.stderr)
    raise SystemExit(1)

print("Dockerfile release-critical downloads are exactly pinned and verified")
