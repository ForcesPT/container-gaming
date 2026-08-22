#!/usr/bin/env python3
"""Regression guard for per-slot ports under Docker host networking."""
from pathlib import Path
import os
import re
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
launcher = (ROOT / "scripts/dpad-launch-session").read_text()
entrypoint = (ROOT / "entrypoint.sh").read_text()
healthcheck = (ROOT / "healthcheck.sh").read_text()
errors: list[str] = []


def require(text: str, source: str, message: str) -> None:
    if text not in source:
        errors.append(message)


def forbid(text: str, source: str, message: str) -> None:
    if text in source:
        errors.append(message)


base_match = re.search(r"^TURN_RELAY_BASE=(\d+)$", launcher, re.MULTILINE)
span_match = re.search(r"^TURN_RELAY_SPAN=(\d+)$", launcher, re.MULTILINE)
if not base_match or not span_match:
    errors.append("session launcher must define fixed TURN_RELAY_BASE and TURN_RELAY_SPAN")
else:
    base = int(base_match.group(1))
    span = int(span_match.group(1))
    if span < 16:
        errors.append("each session needs at least 16 relay allocation ports")
    ranges = [(base + slot * span, base + (slot + 1) * span - 1) for slot in range(32)]
    if any(lo < 1024 or hi > 65535 for lo, hi in ranges):
        errors.append("the first 32 session relay ranges must stay within unprivileged UDP ports")
    if any(ranges[i][1] >= ranges[i + 1][0] for i in range(len(ranges) - 1)):
        errors.append("per-slot relay ranges must not overlap")

require('DPAD_MAX_SLOTS=32', launcher,
        "launcher must define the supported slot ceiling")
require('[[ "$slot" =~ ^(0|[1-9][0-9]?)$ ]]', launcher,
        "slot must be canonical and bounded in length before arithmetic expansion")
require('[ "$slot" -lt "$DPAD_MAX_SLOTS" ]', launcher,
        "launcher must reject slots outside the supported range before arithmetic")
require('relay_min=$(( TURN_RELAY_BASE + slot * TURN_RELAY_SPAN ))', launcher,
        "launcher must derive a deterministic per-slot relay minimum")
require('relay_max=$(( relay_min + TURN_RELAY_SPAN - 1 ))', launcher,
        "launcher must derive the matching relay maximum")
require('[ "$relay_max" -le 65535 ]', launcher,
        "launcher must reject relay ranges beyond UDP port 65535")
forbid('-p "${relay_min}-${relay_max}:${relay_min}-${relay_max}/udp"', launcher,
       "host-network sessions must not publish Docker relay mappings")
require('--network host', launcher,
        "sessions must use host networking to avoid TURN relay hairpin failure")
require('-e DPAD_SELKIES_PORT="$selkies_port"', launcher,
        "launcher must pass the per-slot Selkies port into the container")
require('-e DPAD_TURN_RELAY_MIN_PORT="$relay_min"', launcher,
        "launcher must pass the relay minimum into the container")
require('-e DPAD_TURN_RELAY_MAX_PORT="$relay_max"', launcher,
        "launcher must pass the relay maximum into the container")

require('DPAD_TURN_RELAY_MIN_PORT', entrypoint,
        "entrypoint must consume the relay minimum")
require('DPAD_TURN_RELAY_MAX_PORT', entrypoint,
        "entrypoint must consume the relay maximum")
require('--min-port="${DPAD_TURN_RELAY_MIN_PORT}"', entrypoint,
        "coturn must be constrained to the published relay minimum")
require('--max-port="${DPAD_TURN_RELAY_MAX_PORT}"', entrypoint,
        "coturn must be constrained to the published relay maximum")
require('expected both DPAD_TURN_RELAY_MIN_PORT and DPAD_TURN_RELAY_MAX_PORT', entrypoint,
        "a partial relay range must fail closed")
require('invalid TURN relay range', entrypoint,
        "malformed or reversed relay ranges must fail closed")
require('invalid DPAD_SELKIES_PORT', entrypoint,
        "malformed Selkies ports must fail closed")
require('^[0-9]{4,5}$', entrypoint,
        "runtime port validation must bound digit length before shell integer comparisons")
require('ERROR: coturn failed to start', entrypoint,
        "configured TURN startup must fail closed")
require('--port=${selkies_port}', entrypoint,
        "Selkies must listen on its selected per-slot port")
require('DPAD_SELKIES_PORT', healthcheck,
        "healthcheck must probe the selected per-slot Selkies port")


def emitted_docker_args(slot: str) -> list[str]:
    with tempfile.TemporaryDirectory() as td:
        fake = Path(td) / "docker"
        log = Path(td) / "docker.args"
        fake.write_text(
            "#!/bin/bash\n"
            "case \"${1:-}\" in\n"
            "  ps) exit 0 ;;\n"
            "  run) printf '%s\\n' \"$@\" >\"$FAKE_DOCKER_LOG\"; exit 0 ;;\n"
            "  logs) echo 'DPAD_READY slot=fake'; exit 0 ;;\n"
            "  *) exit 0 ;;\n"
            "esac\n"
        )
        fake.chmod(0o755)
        env = os.environ.copy()
        env.update(
            PATH=f"{td}:{env['PATH']}",
            FAKE_DOCKER_LOG=str(log),
            DPAD_EPHEMERAL_DISK_GB="1",
        )
        result = subprocess.run(
            ["bash", str(ROOT / "scripts/dpad-launch-session"), "launch", slot,
             "none", "none", "test-password", "test-image"],
            text=True,
            capture_output=True,
            env=env,
        )
        if result.returncode:
            errors.append(f"launcher slot {slot} failed under fake Docker: {result.stderr}")
            return []
        return log.read_text().splitlines()[1:]  # drop the `run` subcommand


slot0 = emitted_docker_args("0")
slot1 = emitted_docker_args("1")
for args, selkies_port, minimum, maximum in (
    (slot0, "16100", "40000", "40063"),
    (slot1, "16101", "40064", "40127"),
):
    for expected in ("host", f"DPAD_SELKIES_PORT={selkies_port}",
                     f"DPAD_TURN_RELAY_MIN_PORT={minimum}",
                     f"DPAD_TURN_RELAY_MAX_PORT={maximum}"):
        if expected not in args:
            errors.append(f"real launcher args missing {expected}")
    if "--network" not in args:
        errors.append("real launcher args missing --network")
    if "-p" in args:
        errors.append("real launcher must not emit -p under host networking")

for bad_slot in ("1+1", "01", "32", "18446744073709551616", "9999999999999999999"):
    invalid = subprocess.run(
        ["bash", str(ROOT / "scripts/dpad-launch-session"), "launch", bad_slot,
         "none", "none", "test-password", "test-image"],
        text=True,
        capture_output=True,
    )
    if invalid.returncode == 0 or "invalid slot" not in invalid.stderr:
        errors.append(f"real launcher must reject unsafe slot value {bad_slot!r}")

if errors:
    print("TURN relay plumbing validation FAILED:", file=sys.stderr)
    for error in errors:
        print(f" - {error}", file=sys.stderr)
    raise SystemExit(1)

print("Per-slot host-network TURN/Selkies plumbing is enforced")
