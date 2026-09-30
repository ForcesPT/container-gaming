#!/bin/bash
# Compile epic_service_identity_probe.c with the pinned local Wine builder first.
# Run as dpad in an --rm container, under xvfb-run, with a 120s outer timeout.
set -euo pipefail
umask 077
test "$(id -u)" -ne 0 && test -f /.dockerenv && test -n "${DISPLAY:-}"
task_prefix="$(mktemp -d /tmp/dpad-eos-identity.XXXXXX)"
task_proton=/home/dpad/.steam/debian-installation/compatibilitytools.d/GE-Proton10-34
cleanup() {
    WINEPREFIX="$task_prefix/pfx" "$task_proton/files/bin/wineserver" -k 2>/dev/null || true
    case "$task_prefix" in /tmp/dpad-eos-identity.*) rm -rf -- "$task_prefix" ;; esac
}
trap cleanup EXIT
export WINEPREFIX="$task_prefix" STEAM_COMPAT_DATA_PATH="$task_prefix"
export STEAM_COMPAT_CLIENT_INSTALL_PATH=/home/dpad/.steam/debian-installation
export DPAD_ACCOUNT_FREE_SERVICE_FIXTURE=1 WINEDEBUG=-all
"$task_proton/proton" run /workspace/test-results/epic_service_identity_probe.exe --compare
python3 - <<'PY'
import json
import os
from pathlib import Path
prefix = Path(os.environ['WINEPREFIX']) / 'pfx/drive_c'
reports = [json.loads((prefix / f'eos-identity-{i}.json').read_text()) for i in range(6)]
print(json.dumps({'stage': 'epic_system_service_scope', 'cases': reports,
                  'expected_system_cases': [0]}))
assert [r['case'] for r in reports if r['system_user']] == [0]
PY
