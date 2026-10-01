"""Image integration gate: private-volume Epic startup uses baked UMU offline.

The fake Faugus controller runs a real UMU/Proton console probe instead of an
account client. Run only in a disposable image container with networking off.
"""
import json
import os
from pathlib import Path
import subprocess
import tempfile

if os.environ.get('DPAD_TEST_EPIC_RUNTIME_PATH') != '1':
    raise SystemExit('disposable offline container opt-in required')
with tempfile.TemporaryDirectory() as temporary:
    root = Path(temporary)
    binaries = root / 'bin'
    binaries.mkdir()
    fake = binaries / 'faugus-launcher'
    fake.write_text('''#!/usr/bin/python3
import json, os, subprocess
from pathlib import Path
from umu.umu_consts import UMU_LOCAL
runtime = Path('/home/dpad/.local/share/umu/steamrt3')
assert UMU_LOCAL == runtime.parent, 'private data volume hid the baked runtime'
assert (runtime / '.installed.ok').is_file() and (runtime / 'run').is_file()
result = subprocess.run(['/usr/bin/umu-run', 'cmd.exe', '/c', 'echo RUNTIME_OFFLINE_PROBE_OK'],
                        capture_output=True, text=True, timeout=90)
log = result.stdout + result.stderr
Path(os.environ['DPAD_RUNTIME_PROBE_LOG']).write_text(log)
assert result.returncode == 0, 'actual offline UMU console probe failed'
assert 'RUNTIME_OFFLINE_PROBE_OK' in log, 'console probe did not execute'
assert 'Downloading steamrt' not in log and 'New install detected' not in log
Path(os.environ['DPAD_RUNTIME_PROBE_RESULT']).write_text(json.dumps({'bakedRuntime': str(runtime), 'offlineProbePassed': True}))
''')
    fake.chmod(0o755)
    state = root / 'private-volume/faugus'
    report = root / 'report.json'
    log = root / 'umu.log'
    env = {**os.environ, 'HOME': '/home/dpad', 'DPAD_FAUGUS_STATE_ROOT': str(state),
           'PATH': str(binaries) + ':' + os.environ['PATH'],
           'UMU_FOLDERS_PATH': '/deliberately-wrong-runtime-path',
           'DPAD_RUNTIME_PROBE_RESULT': str(report), 'DPAD_RUNTIME_PROBE_LOG': str(log)}
    result = subprocess.run(['/bin/bash', '/opt/dpadcloud/faugus-epic-launch'], env=env,
                            capture_output=True, text=True, timeout=120)
    if result.returncode:
        print(result.stdout + result.stderr)
        if log.exists():
            print(log.read_text())
        raise SystemExit('offline Epic volume runtime gate failed')
    assert json.loads(report.read_text())['offlineProbePassed'] is True
    assert (state / 'data/faugus-launcher/games.json').is_file()
    assert not (state / 'data/umu').exists(), 'runtime was downloaded into account data'
    print('EPIC_PRIVATE_VOLUME_BAKED_RUNTIME_OFFLINE_UMU_PROBE_OK')
