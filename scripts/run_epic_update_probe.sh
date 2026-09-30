#!/bin/bash
# Disposable-container harness. The caller must apply a 600s outer timeout.
set -euo pipefail
umask 077
task_display=:90
task_auth="$(mktemp /tmp/dpad-epic-xauth.XXXXXX)"
task_display_log="$(mktemp /tmp/dpad-epic-xvfb.XXXXXX)"
task_display_pid=
cleanup() {
    if [ -n "$task_display_pid" ]; then
        kill "$task_display_pid" 2>/dev/null || true
        wait "$task_display_pid" 2>/dev/null || true
    fi
    rm -f -- "$task_auth" "$task_display_log"
}
trap cleanup EXIT
xauth -f "$task_auth" add "$task_display" MIT-MAGIC-COOKIE-1 "$(mcookie)"
export DISPLAY="$task_display" XAUTHORITY="$task_auth"
Xvfb "$task_display" -screen 0 1280x720x24 -nolisten tcp -auth "$task_auth" >"$task_display_log" 2>&1 &
task_display_pid=$!
task_display_ready=0
for task_attempt in $(seq 1 30); do
    kill -0 "$task_display_pid" 2>/dev/null || break
    if timeout 2s xdpyinfo -display "$task_display" >/dev/null 2>&1; then
        task_display_ready=1
        break
    fi
    sleep 1
done
if [ "$task_display_ready" -ne 1 ]; then
    echo 'Probe display did not become ready; Epic was not started' >&2
    exit 1
fi
echo 'ACCOUNT_FREE_PROBE_DISPLAY_READY'
python3 /workspace/scripts/probe_epic_update_local.py
