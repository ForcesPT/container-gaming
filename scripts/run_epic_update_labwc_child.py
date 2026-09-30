#!/usr/bin/python3
"""Bounded local compositor child. No production desktop configuration."""
import json
import os
from pathlib import Path
import subprocess

runtime = Path(os.environ['XDG_RUNTIME_DIR'])
if not str(runtime).startswith('/tmp/dpad-epic-labwc.') or os.geteuid() == 0:
    raise SystemExit('run only in the disposable account-free local harness')
result = 1
try:
    print('ACCOUNT_FREE_PROBE_LABWC_DISPLAY_READY', flush=True)
    subprocess.run(['glxinfo', '-B'], timeout=15, check=True)
    subprocess.run(['xrandr', '--current'], timeout=15, check=True)
    result = subprocess.run(['/usr/bin/python3', '/workspace/scripts/probe_epic_update_local.py',
                             *json.loads(os.environ['DPAD_PROBE_ARGS'])]).returncode
finally:
    (runtime / 'probe-exit').write_text(str(result))
    subprocess.run(['labwc', '--exit'], timeout=10)
