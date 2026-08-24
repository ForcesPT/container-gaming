#!/usr/bin/env python3
"""Regression checks for EA App versioned layout and installer handoff."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
script = (ROOT / "scripts" / "ea-launch").read_text()

required = (
    'resolve_ea_installed_exe()',
    '"$EA_BASE"/*/"EA Desktop"/EALauncher.exe',
    '"$EA_BASE"/*/"EA Desktop"/EADesktop.exe',
    'EA_INST="$(resolve_ea_installed_exe 2>/dev/null || true)"',
    '"$UMU_RUN" "$SETUP_EXE" >>"$LOG" 2>&1 &',
    'installer_pid=$!',
    'while [ $i -lt 90 ] && ! ea_installed; do',
    'wlrctl window close "app_id:steam_app_eaapp"',
    'installer_wait_deadline=$((SECONDS + 30))',
    'kill "$installer_pid" 2>/dev/null || true',
    'wait "$installer_pid"',
    'exec "$UMU_RUN" "$EA_EXE" $EA_CEF_ARGS',
)
for item in required:
    if item not in script:
        raise SystemExit(f"EA launch contract missing: {item}")

versioned_desktop = '"$EA_BASE"/*/"EA Desktop"/EADesktop.exe'
versioned_launcher = '"$EA_BASE"/*/"EA Desktop"/EALauncher.exe'
if script.index(versioned_desktop) > script.index(versioned_launcher):
    raise SystemExit("EA must prefer direct EADesktop.exe so CEF flags reach the browser process")

order = [script.index(item) for item in required[4:]]
if order != sorted(order):
    raise SystemExit("EA installer handoff ordering is unsafe")

if '--disable-gpu --in-process-gpu' not in script:
    raise SystemExit("EA controlled launch lost software-rendering flags")

print("EA App launch contract: PASS")
