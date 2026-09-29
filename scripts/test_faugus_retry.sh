#!/bin/bash
# Run in the candidate Linux image with the three updated scripts in /tmp.
set -euo pipefail
umask 077
tmp="$(mktemp -d)"
trap 'code=$?; if [ "$code" -ne 0 ]; then for log in "$tmp"/*.log; do [ ! -f "$log" ] || { echo "FAILED: $log" >&2; tail -n 20 "$log" >&2; }; done; fi; rm -rf -- "$tmp"' EXIT
mkdir -p "$tmp/bin" "$tmp/home" "$tmp/private" "$tmp/scripts"
cp /tmp/faugus-epic-launch-new "$tmp/scripts/faugus-epic-launch"
cp /tmp/dpad_faugus_prepare-new.py "$tmp/scripts/dpad_faugus_prepare.py"
cp /tmp/dpad_epic_updater_failed-new.py "$tmp/scripts/dpad_epic_updater_failed.py"
cp /tmp/dpad_epic_resume-new.py "$tmp/scripts/dpad_epic_resume.py"
sed -i 's/\r$//' "$tmp/scripts/faugus-epic-launch"
chmod +x "$tmp/scripts/faugus-epic-launch"
cat >"$tmp/bin/faugus-launcher" <<'STUB'
#!/bin/bash
set -euo pipefail
test -z "${PROTON_USE_WINED3D:-}"
test "$VK_ICD_FILENAMES" = /etc/vulkan/icd.d/nvidia_icd.json
count=0
if [ -f "$FAUGUS_TEST_COUNT" ]; then count="$(cat "$FAUGUS_TEST_COUNT")"; fi
count=$((count + 1))
echo "$count" > "$FAUGUS_TEST_COUNT"
printf '%s\n' "$*" > "$FAUGUS_TEST_LAST_ARGS"
printf '%s\n' "${WINEDEBUG:-}" > "$FAUGUS_TEST_LAST_WINEDEBUG"
if [ "${1:-}" = --run ]; then
    [[ "$2" == *'msiexec /i '*'/qn /norestart' ]]
    target="$WINEPREFIX/drive_c/Program Files/Epic Games/Launcher/Portal/Binaries/Win64/EpicGamesLauncher.exe"
    mkdir -p "$(dirname "$target")"
    touch "$target"
    exit 0
fi
if { [ "$FAUGUS_TEST_MODE" = fail-first ] && [ "$count" -eq 1 ]; } \
   || { [ "$FAUGUS_TEST_MODE" = fail-two ] && [ "$count" -le 2 ]; } \
   || { [ "$FAUGUS_TEST_MODE" = fail-delayed-first ] && [ "$count" -eq 1 ]; } \
   || [ "$FAUGUS_TEST_MODE" = fail-always ]; then
    logs="$WINEPREFIX/drive_c/users/steamuser/AppData/Local/EpicGamesLauncher/Saved/Logs"
    mkdir -p "$logs"
    echo 'Application finished with code 8 (StartServiceFailed)' > "$logs/EpicGamesUpdater-test.log"
fi
if [ "$FAUGUS_TEST_MODE" = fail-delayed-first ] && [ "$count" -eq 1 ]; then
    sleep 31
fi
STUB
chmod +x "$tmp/bin/faugus-launcher"
export HOME="$tmp/home" DPAD_FAUGUS_STATE_ROOT="$tmp/private"
export PATH="$tmp/bin:$PATH" FAUGUS_TEST_COUNT="$tmp/count"
export FAUGUS_TEST_LAST_ARGS="$tmp/last-args" FAUGUS_TEST_LAST_WINEDEBUG="$tmp/last-winedebug"
exe="$tmp/private/prefixes/epic-games/drive_c/Program Files/Epic Games/Launcher/Portal/Binaries/Win64/EpicGamesLauncher.exe"
mkdir -p "$(dirname "$exe")"
touch "$exe"
export FAUGUS_TEST_MODE=fail-first
"$tmp/scripts/faugus-epic-launch" >"$tmp/fail-first.log" 2>&1
test "$(cat "$tmp/count")" = 2
grep -q 'attempt 2/3' "$tmp/fail-first.log"
rm "$tmp/count"
export FAUGUS_TEST_MODE=fail-delayed-first
"$tmp/scripts/faugus-epic-launch" >"$tmp/fail-delayed-first.log" 2>&1
test "$(cat "$tmp/count")" = 2
grep -q 'attempt 2/3' "$tmp/fail-delayed-first.log"
rm "$tmp/count"
export FAUGUS_TEST_MODE=fail-two
"$tmp/scripts/faugus-epic-launch" >"$tmp/fail-two.log" 2>&1
test "$(cat "$tmp/count")" = 3
grep -q 'attempt 3/3' "$tmp/fail-two.log"
rm "$tmp/count"
export FAUGUS_TEST_MODE=normal
"$tmp/scripts/faugus-epic-launch" >"$tmp/normal.log" 2>&1
test "$(cat "$tmp/count")" = 1
! grep -q 'retrying the launcher' "$tmp/normal.log"
! grep -q -- '--logs' "$tmp/last-args"
rm "$tmp/count"
export FAUGUS_TEST_MODE=fail-always
if "$tmp/scripts/faugus-epic-launch" >"$tmp/fail-always.log" 2>&1; then
    echo 'third service failure should fail closed' >&2
    exit 1
fi
test "$(cat "$tmp/count")" = 3
grep -q 'Epic updater service failed after three attempts' "$tmp/fail-always.log"
rm "$tmp/count"
export FAUGUS_TEST_MODE=normal DPAD_EPIC_DIAGNOSTICS=1
"$tmp/scripts/faugus-epic-launch" >"$tmp/diagnostic.log" 2>&1
test "$(cat "$tmp/count")" = 1
grep -q -- '--game dpad-epic --logs' "$tmp/last-args"
grep -qx -- '-all,err+all' "$tmp/last-winedebug"
rm "$tmp/count" "$exe"
unset DPAD_EPIC_DIAGNOSTICS
"$tmp/scripts/faugus-epic-launch" --prepare-only >"$tmp/prepare.log" 2>&1
test "$(cat "$tmp/count")" = 1
test -f "$exe"
grep -q '/qn /norestart' "$tmp/last-args"
"$tmp/scripts/faugus-epic-launch" --prepare-only >>"$tmp/prepare.log" 2>&1
test "$(cat "$tmp/count")" = 1 # prepared prefix is reused, no client/login launched
if "$tmp/scripts/faugus-epic-launch" --resume >"$tmp/resume-free-lock.log" 2>&1; then
    echo 'resume must refuse without a live launch owner' >&2; exit 1
fi
if flock "$tmp/private/state/faugus-launcher/dpad-epic.lock" "$tmp/scripts/faugus-epic-launch" --resume >"$tmp/resume-no-client.log" 2>&1; then
    echo 'resume must refuse when a lock owner has no matching Epic client' >&2; exit 1
fi
echo FAUGUS_RETRY_TEST_OK
