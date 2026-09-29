#!/bin/bash
# Disposable container only: use a fake Epic child to exercise the real Faugus runner.
set -euo pipefail

export HOME=/home/dpad
test "${DPAD_EPIC_BACKEND:-}" = faugus
state=/tmp/dpad-faugus-handoff-smoke
mkdir -m 700 "$state"
chown dpad:dpad "$state"
exe="$state/faugus/prefixes/epic-games/drive_c/Program Files/Epic Games/Launcher/Portal/Binaries/Win64/EpicGamesLauncher.exe"
mkdir -p "$(dirname "$exe")"
touch "$exe"
chown -R dpad:dpad "$state"

cat >/usr/bin/umu-run <<'STUB'
#!/bin/sh
set -eu
test "$FAUGUSID" = dpad-epic
test -z "${PROTON_USE_WINED3D:-}"
test "$VK_ICD_FILENAMES" = /etc/vulkan/icd.d/nvidia_icd.json
/usr/bin/python3 - <<'PY'
import os
import subprocess

child = '''import ctypes
import time
from pathlib import Path
ctypes.CDLL(None).prctl(15, b'EpicGamesLaunc', 0, 0, 0)
Path('/tmp/dpad-faugus-handoff-smoke/child-started').write_text('started')
time.sleep(5)
Path('/tmp/dpad-faugus-handoff-smoke/child-finished').write_text('finished')
'''
subprocess.Popen(['/usr/bin/python3', '-c', child], env=os.environ.copy(),
                 start_new_session=True, stdout=subprocess.DEVNULL,
                 stderr=subprocess.DEVNULL, close_fds=True)
PY
STUB
chmod +x /usr/bin/umu-run

started=$(date +%s)
timeout 45s runuser -u dpad -- env HOME=/home/dpad DPAD_VOLUME_MOUNT="$state" \
    dbus-run-session -- xvfb-run -a /opt/dpadcloud/epic-launch > "$state/runner.log" 2>&1
elapsed=$(($(date +%s) - started))
test -f "$state/child-started"
test -f "$state/child-finished"
test "$elapsed" -ge 20
grep -q 'dpad-epic: UMU parent exited; allowing Epic process handoff' "$state/runner.log"
grep -q 'dpad-epic: Epic processes are quiet; finalizing' "$state/runner.log"
echo "Actual Faugus runner preserved the fake Epic child; elapsed ${elapsed}s."
