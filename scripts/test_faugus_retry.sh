#!/bin/bash
# Run in the candidate Linux image with the three updated scripts in /tmp.
set -euo pipefail
tmp="$(mktemp -d)"
trap 'rm -rf -- "$tmp"' EXIT
mkdir -p "$tmp/bin" "$tmp/home" "$tmp/private" "$tmp/scripts"
cp /tmp/faugus-epic-launch-new "$tmp/scripts/faugus-epic-launch"
cp /tmp/dpad_faugus_prepare-new.py "$tmp/scripts/dpad_faugus_prepare.py"
cp /tmp/dpad_epic_updater_failed-new.py "$tmp/scripts/dpad_epic_updater_failed.py"
chmod +x "$tmp/scripts/faugus-epic-launch"
cat >"$tmp/bin/faugus-launcher" <<'STUB'
#!/bin/bash
set -euo pipefail
count=0
if [ -f "$FAUGUS_TEST_COUNT" ]; then count="$(cat "$FAUGUS_TEST_COUNT")"; fi
count=$((count + 1))
echo "$count" > "$FAUGUS_TEST_COUNT"
if { [ "$FAUGUS_TEST_MODE" = fail-first ] && [ "$count" -eq 1 ]; } \
   || [ "$FAUGUS_TEST_MODE" = fail-always ]; then
    logs="$WINEPREFIX/drive_c/users/steamuser/AppData/Local/EpicGamesLauncher/Saved/Logs"
    mkdir -p "$logs"
    echo 'Application finished with code 8 (StartServiceFailed)' > "$logs/EpicGamesUpdater-test.log"
fi
STUB
chmod +x "$tmp/bin/faugus-launcher"
export HOME="$tmp/home" DPAD_FAUGUS_STATE_ROOT="$tmp/private"
export PATH="$tmp/bin:$PATH" FAUGUS_TEST_COUNT="$tmp/count"
exe="$tmp/private/prefixes/epic-games/drive_c/Program Files/Epic Games/Launcher/Portal/Binaries/Win64/EpicGamesLauncher.exe"
mkdir -p "$(dirname "$exe")"
touch "$exe"
export FAUGUS_TEST_MODE=fail-first
"$tmp/scripts/faugus-epic-launch" >"$tmp/fail-first.log" 2>&1
test "$(cat "$tmp/count")" = 2
grep -q 'retrying the launcher once' "$tmp/fail-first.log"
rm "$tmp/count"
export FAUGUS_TEST_MODE=normal
"$tmp/scripts/faugus-epic-launch" >"$tmp/normal.log" 2>&1
test "$(cat "$tmp/count")" = 1
! grep -q 'retrying the launcher once' "$tmp/normal.log"
rm "$tmp/count"
export FAUGUS_TEST_MODE=fail-always
if "$tmp/scripts/faugus-epic-launch" >"$tmp/fail-always.log" 2>&1; then
    echo 'second service failure should fail closed' >&2
    exit 1
fi
test "$(cat "$tmp/count")" = 2
grep -q 'Epic updater service failed again' "$tmp/fail-always.log"
echo FAUGUS_RETRY_TEST_OK
