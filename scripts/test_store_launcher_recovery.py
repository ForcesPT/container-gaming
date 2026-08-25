#!/usr/bin/env python3
"""Behavioral tests for recovering stale marked store prefixes."""
import os
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"

CASES = (
    (
        "battlenet-launch",
        "drive_c/Program Files (x86)/Battle.net/Battle.net Launcher.exe",
    ),
    (
        "ea-launch",
        "drive_c/Program Files/Electronic Arts/EA Desktop/EA Desktop/EALauncher.exe",
    ),
    (
        "ubisoft-launch",
        "drive_c/Program Files (x86)/Ubisoft/Ubisoft Game Launcher/UbisoftConnect.exe",
    ),
)


def write_executable(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")
    path.chmod(0o755)


with tempfile.TemporaryDirectory() as temporary:
    root = Path(temporary)
    fake_bin = root / "bin"
    fake_bin.mkdir()
    calls = root / "calls"
    calls.mkdir()

    fake_curl = fake_bin / "curl"
    write_executable(
        fake_curl,
        """#!/bin/bash
set -eu
out=
while [ "$#" -gt 0 ]; do
    if [ "$1" = -o ]; then out=$2; shift 2; else shift; fi
done
[ -n "$out" ]
mkdir -p "$(dirname "$out")"
printf 'FRESH-INSTALLER' > "$out"
printf 'curl %s\n' "$out" >> "$TEST_CALLS/curl"
""",
    )
    fake_verify = fake_bin / "verify-windows"
    write_executable(
        fake_verify,
        """#!/bin/bash
set -eu
last=
pe_only=0
for arg in "$@"; do
    [ "$arg" = --pe-only ] && pe_only=1
    last=$arg
done
if [ "$pe_only" -eq 1 ]; then
    [ -f "$last" ] && grep -q '^VALID$' "$last"
    exit
fi
[ -f "$last" ] && grep -q '^FRESH-INSTALLER$' "$last"
printf 'verify %s\n' "$last" >> "$TEST_CALLS/verify"
""",
    )
    fake_randomize = fake_bin / "randomize-prefix"
    write_executable(fake_randomize, "#!/bin/bash\nexit 0\n")
    fake_umu = fake_bin / "umu-run"
    write_executable(
        fake_umu,
        """#!/bin/bash
set -eu
if [ "${1:-}" = winetricks ]; then exit 0; fi
case "${1:-}" in
    *.exe)
        mkdir -p "$(dirname "$TEST_INSTALLED_PATH")"
        printf 'VALID\n' > "$TEST_INSTALLED_PATH"
        ;;
esac
exit 0
""",
    )

    for launcher, installed_relative in CASES:
        for fixture in ("missing", "invalid"):
            case_root = root / f"{launcher}-{fixture}"
            home = case_root / "home"
            prefix = case_root / "prefix"
            proton = home / ".steam/debian-installation/compatibilitytools.d/GE-Proton11-3/proton"
            proton.parent.mkdir(parents=True)
            write_executable(proton, "#!/bin/bash\nexit 0\n")
            prefix.mkdir(parents=True)
            marker = prefix / ".dpad-preinstalled"
            marker.touch()
            keep = prefix / "keep-user-state"
            keep.write_text("preserve", encoding="utf-8")
            installed = prefix / installed_relative
            if fixture == "invalid":
                installed.parent.mkdir(parents=True)
                installed.write_text("BROKEN\n", encoding="utf-8")

            curl_log = calls / "curl"
            verify_log = calls / "verify"
            curl_log.unlink(missing_ok=True)
            verify_log.unlink(missing_ok=True)
            env = os.environ.copy()
            env.update(
                {
                    "HOME": str(home),
                    "USER": "dpad",
                    "WINEPREFIX": str(prefix),
                    "UMU_RUN": str(fake_umu),
                    "PATH": f"{fake_bin}:{env['PATH']}",
                    "TEST_CALLS": str(calls),
                    "TEST_INSTALLED_PATH": str(installed),
                    "DPAD_VERIFY_WINDOWS_BINARY": str(fake_verify),
                    "DPAD_RANDOMIZE_PREFIX_ID": str(fake_randomize),
                }
            )
            result = subprocess.run(
                ["bash", str(SCRIPTS / launcher)],
                env=env,
                text=True,
                capture_output=True,
                timeout=20,
            )
            if result.returncode:
                raise SystemExit(
                    f"{launcher} {fixture} recovery failed ({result.returncode}):\n"
                    f"stdout={result.stdout}\nstderr={result.stderr}"
                )
            if not curl_log.is_file() or not verify_log.is_file():
                raise SystemExit(f"{launcher} {fixture} prefix did not download and verify a fresh installer")
            if keep.read_text(encoding="utf-8") != "preserve":
                raise SystemExit(f"{launcher} {fixture} recovery damaged user state")
            if marker.exists() or marker.is_symlink():
                raise SystemExit(f"{launcher} {fixture} recovery retained the stale template marker")

print("Store launcher stale-marker recovery: PASS")
