"""Disposable-container test: real process guard and wrapper restore dispatch."""
import fcntl
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time

from dpad_epic_resume import managed_client_running

with tempfile.TemporaryDirectory() as temporary:
    root = Path(temporary)
    prefix = root / 'state/prefixes/epic-games'
    executable = prefix / 'drive_c/Program Files/Epic Games/Launcher/Portal/Binaries/Win64/EpicGamesLauncher.exe'
    executable.parent.mkdir(parents=True)
    prefix.chmod(0o700)
    (prefix / 'pfx').symlink_to(prefix, target_is_directory=True)
    executable.touch()
    environment = {**os.environ, 'HOME': str(root / 'home'),
                   'DPAD_FAUGUS_STATE_ROOT': str(root / 'state'),
                   'EPIC_TEST_EVENTS': str(root / 'events')}
    # This replacement is confined to a --rm test container.
    stub = Path('/usr/bin/umu-run')
    original = stub.read_bytes()
    stub.write_text('''#!/bin/bash
set -euo pipefail
test "$FAUGUSID" = dpad-epic
test "$UMU_USE_STEAM" = 1
test "$UMU_CONTAINER_NSENTER" = 1
test "$UMU_RUNTIME_UPDATE" = 0
test "$2" = -SkipBuildPatchPrereq
test "$1" = "$WINEPREFIX/drive_c/Program Files/Epic Games/Launcher/Portal/Binaries/Win64/EpicGamesLauncher.exe"
echo RESTORE_DISPATCH_OK > "$EPIC_TEST_EVENTS"
''')
    try:
        subprocess.run(['/opt/dpadcloud/faugus-epic-launch', '--prepare-only'], env=environment, check=True)
        with (root / 'state/state/faugus-launcher/dpad-epic.lock').open() as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            child = subprocess.Popen([str(executable), '-c',
                "import ctypes,time; ctypes.CDLL(None).prctl(15,b'GameThread',0,0,0); time.sleep(30)"],
                executable=sys.executable,
                env={**environment, 'FAUGUSID': 'dpad-epic', 'WINEPREFIX': str(prefix / 'pfx') + '/'})
            try:
                for _ in range(30):
                    if managed_client_running(str(prefix)): break
                    time.sleep(0.05)
                else: raise AssertionError('real marked client was not detected')
                subprocess.run(['/opt/dpadcloud/faugus-epic-launch', '--resume'],
                               env=environment, check=True, timeout=10)
                assert (root / 'events').read_text().strip() == 'RESTORE_DISPATCH_OK'
                assert child.poll() is None, 'restore must leave the existing client alive'
                blocked = subprocess.run(['/opt/dpadcloud/faugus-epic-launch'],
                                         env=environment, capture_output=True, timeout=10)
                assert blocked.returncode != 0, 'normal launch must not create a second controller'
            finally:
                child.terminate()
                child.wait(timeout=5)
    finally:
        stub.write_bytes(original)
print('EPIC_RESTORE_DISPATCH_OK')
