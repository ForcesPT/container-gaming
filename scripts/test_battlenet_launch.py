#!/usr/bin/env python3
"""Regression checks for the Battle.net installer-to-client handoff."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
script = (ROOT / "scripts" / "battlenet-launch").read_text()

background_install = '"$UMU_RUN" "$SETUP_EXE" >>"$LOG" 2>&1 &'
installed_poll = 'while [ $i -lt 90 ] && ! bn_installed; do'
close_auto_client = 'wlrctl window close "app_id:steam_app_battlenet"'
bounded_wait = 'installer_wait_deadline=$((SECONDS + 30))'
terminate_stuck = 'kill "$installer_pid" 2>/dev/null || true'
wait_install = 'wait "$installer_pid"'
controlled_launch = 'exec "$UMU_RUN" "$EXE" $BN_CEF_ARGS'

for required in (
    background_install,
    'installer_pid=$!',
    installed_poll,
    close_auto_client,
    bounded_wait,
    terminate_stuck,
    wait_install,
    controlled_launch,
):
    if required not in script:
        raise SystemExit(f"Battle.net installer handoff missing: {required}")

positions = [script.index(item) for item in (
    background_install,
    'installer_pid=$!',
    installed_poll,
    close_auto_client,
    bounded_wait,
    terminate_stuck,
    wait_install,
    controlled_launch,
)]
if positions != sorted(positions):
    raise SystemExit("Battle.net installer handoff ordering is unsafe")

if '--disable-gpu --in-process-gpu' not in script:
    raise SystemExit("Battle.net controlled launch lost software-rendering flags")

print("Battle.net installer handoff: PASS")
