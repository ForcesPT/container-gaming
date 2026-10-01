#!/bin/bash
# Account-free EC-key persistence, including a clean wineserver restart.
set -euo pipefail
umask 077
test "$(id -u)" -ne 0 && test -f /.dockerenv && test -n "${DISPLAY:-}"
task_prefix="$(mktemp -d /tmp/dpad-store-key.XXXXXX)"
task_proton="${HOME}/.steam/debian-installation/compatibilitytools.d/${DPAD_PROTON_VERSION:-GE-Proton11-7}"
cleanup() {
    WINEPREFIX="$task_prefix/pfx" "$task_proton/files/bin/wineserver" -k 2>/dev/null || true
    case "$task_prefix" in /tmp/dpad-store-key.*) rm -rf -- "$task_prefix" ;; esac
}
trap cleanup EXIT
export STEAM_COMPAT_DATA_PATH="$task_prefix" STEAM_COMPAT_CLIENT_INSTALL_PATH="${HOME}/.steam/debian-installation"
export WINEDEBUG=-all
receipt="$task_prefix/pfx/drive_c/dpad-ncrypt-probe.txt"
"$task_proton/proton" run /workspace/test-results/ncrypt_persistence_probe.exe create
test -f "$receipt" && grep -q '^signature_bytes=64' "$receipt"
created="$(sed -n 's/^public=//p' "$receipt" | tr -d '\r')"
test -n "$created"
WINEPREFIX="$task_prefix/pfx" "$task_proton/files/bin/wineserver" -k
WINEPREFIX="$task_prefix/pfx" "$task_proton/files/bin/wineserver" -w
"$task_proton/proton" run /workspace/test-results/ncrypt_persistence_probe.exe open
opened="$(sed -n 's/^public=//p' "$receipt" | tr -d '\r')"
test "$created" = "$opened" && grep -q '^signature_bytes=64' "$receipt"
echo 'STORE_KEY_PERSISTENCE_PASS create_sign_open_same_key_after_wineserver_restart'
