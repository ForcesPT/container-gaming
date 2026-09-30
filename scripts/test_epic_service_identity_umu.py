#!/usr/bin/python3
"""Run the account-free SCM boundary fixture in the actual UMU runtime."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

binary = Path(sys.argv[1]).resolve(strict=True)
runner = Path.home() / '.steam/debian-installation/compatibilitytools.d/GE-Proton10-34'
with tempfile.TemporaryDirectory(prefix='dpad-epic-scm-') as directory:
    prefix = Path(directory) / 'prefix'
    prefix.mkdir(mode=0o700)
    env = dict(os.environ, WINEPREFIX=str(prefix), PROTONPATH=str(runner),
               GAMEID='umu-default', UMU_RUNTIME_UPDATE='0', WINEDEBUG='-all',
               DPAD_ACCOUNT_FREE_SERVICE_FIXTURE='1')
    result = subprocess.run(['umu-run', str(binary), '--compare'], env=env,
                            capture_output=True, text=True, timeout=120)
    if result.returncode:
        raise SystemExit(f'Account-free Epic SCM fixture failed: exit={result.returncode}; '
                         + result.stderr[-1200:])
    reports = [json.loads((prefix / 'drive_c' / f'eos-identity-{index}.json').read_text())
               for index in range(6)]
    if [item['case'] for item in reports if item['system_user']] != [0]:
        raise SystemExit('Epic LocalSystem scope changed')
    print(json.dumps({'stage': 'epic_system_service_scope', 'cases': reports,
                      'expected_system_cases': [0]}))
