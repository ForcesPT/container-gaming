#!/usr/bin/python3
"""Run actual Wine API/CRT renderer boundaries in a disposable local prefix."""
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

binary = Path(sys.argv[1])
version = os.environ.get('DPAD_GOG_PROTON_VERSION') or os.environ.get('DPAD_PROTON_VERSION') or 'GE-Proton11-7'
runner = Path.home() / '.steam/debian-installation/compatibilitytools.d' / version
with tempfile.TemporaryDirectory(prefix='dpad-gog-gate-') as directory:
    prefix = Path(directory) / 'prefix'
    drive = prefix / 'drive_c'
    drive.mkdir(parents=True)
    env = dict(os.environ, WINEPREFIX=str(prefix), PROTONPATH=str(runner),
               GAMEID='umu-default', STORE='gog', UMU_RUNTIME_UPDATE='0', WINEDEBUG='-all')
    for name, gate, expected in [('OtherStore.exe', '1', 'win32=0 crt=0 deletion=1'),
                                 ('GalaxyClient.exe', '0', 'win32=0 crt=0 deletion=1'),
                                 ('GalaxyClient.exe', '1', 'win32=1 crt=1 deletion=1')]:
        target = drive / name
        shutil.copyfile(binary, target)
        env['DPAD_GOG_SOFTWARE_RENDERING'] = gate
        result = subprocess.run(['umu-run', str(target)], env=env, capture_output=True,
                                text=True, timeout=90)
        receipt = drive / 'dpad-gog-environment-probe.txt'
        if result.returncode or not receipt.is_file() or receipt.read_text().strip() != expected:
            raise SystemExit(f'GOG environment boundary failed: executable={name} gate={gate}')
        receipt.unlink()
        print(f'GOG_RENDERER_SCOPE_PASS executable={name} gate={gate}')
