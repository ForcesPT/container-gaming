#!/bin/bash
# Disposable container only: exercise Faugus with a stub, without logging in.
set -euo pipefail
test "${DPAD_EPIC_BACKEND}" = faugus
export HOME=/home/dpad
runuser -u dpad -- /usr/bin/python3 /opt/dpadcloud/dpad_faugus_prepare.py
cat >/usr/bin/umu-run <<'STUB'
#!/bin/sh
test "$PROTONPATH" = /home/dpad/.steam/debian-installation/compatibilitytools.d/GE-Proton11-3 || exit 21
test "$UMU_RUNTIME_UPDATE" = 0 || exit 22
test "$WINEPREFIX" = /home/dpad/Faugus/epic-games || exit 23
echo FAUGUS_PINNED_RUNTIME_OK
STUB
chmod +x /usr/bin/umu-run
export PROTONPATH=/home/dpad/.steam/debian-installation/compatibilitytools.d/GE-Proton11-3
export WINEPREFIX=/home/dpad/Faugus/epic-games
export UMU_RUNTIME_UPDATE=0 FAUGUS_DISABLE_UPDATES=1
timeout 30s runuser -u dpad -- dbus-run-session -- xvfb-run -a /usr/local/bin/faugus-launcher --run '/usr/bin/umu-run /tmp/no-game.exe' > /tmp/faugus-smoke.log 2>&1
grep -q FAUGUS_PINNED_RUNTIME_OK /tmp/faugus-smoke.log
test ! -f /home/dpad/.local/share/faugus-launcher/umu-run
echo 'Faugus actual runner passed with a stub UMU; no account or game launch tested.'
mv /opt/dpadcloud/launcher/dpad-launcher /opt/dpadcloud/launcher/dpad-launcher.real
printf '#!/bin/sh\nexit 0\n' > /opt/dpadcloud/launcher/dpad-launcher
chmod +x /opt/dpadcloud/launcher/dpad-launcher
DPAD_INSTANT_APP=sample /opt/dpadcloud/launcher-shell >/tmp/instant-gate.log 2>&1
grep -q 'client-only canary; shared game import is not registered' /tmp/instant-gate.log
if DPAD_FAUGUS_CLIENT_ONLY_TEST= DPAD_INSTANT_APP=sample /opt/dpadcloud/launcher-shell >/tmp/instant-gate-disabled.log 2>&1; then
    echo 'Instant qualification gate unexpectedly allowed launch' >&2
    exit 1
fi
grep -q 'official Epic Instant import is not qualified' /tmp/instant-gate-disabled.log
mv /opt/dpadcloud/launcher/dpad-launcher.real /opt/dpadcloud/launcher/dpad-launcher

# Exercise the real wrapper and XDG inventory using a private volume, twice.
mkdir -m 700 /tmp/faugus-private-volume
chown dpad:dpad /tmp/faugus-private-volume
cat >/usr/bin/umu-run <<'STUB'
#!/bin/sh
set -eu
test "$PROTONPATH" = /home/dpad/.steam/debian-installation/compatibilitytools.d/GE-Proton11-3
test "$UMU_RUNTIME_UPDATE" = 0
test "$WINEPREFIX" = /tmp/faugus-private-volume/faugus/prefixes/epic-games
test "$XDG_DATA_HOME" = /tmp/faugus-private-volume/faugus/data
case "$1" in
    msiexec)
        target="$WINEPREFIX/drive_c/Program Files/Epic Games/Launcher/Portal/Binaries/Win64/EpicGamesLauncher.exe"
        mkdir -p "$(dirname "$target")"
        touch "$target"
        echo installer >> /tmp/faugus-private-volume/events
        ;;
    *EpicGamesLauncher.exe)
        echo client >> /tmp/faugus-private-volume/events
        ;;
    *) exit 25 ;;
esac
STUB
for attempt in 1 2; do
    timeout 30s runuser -u dpad -- env DPAD_VOLUME_MOUNT=/tmp/faugus-private-volume \
        dbus-run-session -- xvfb-run -a /opt/dpadcloud/epic-launch > /tmp/faugus-wrapper.log 2>&1
done
test "$(grep -c installer /tmp/faugus-private-volume/events)" = 1
test "$(grep -c client /tmp/faugus-private-volume/events)" = 2
echo 'Persistent-volume wrapper passed: one stub installation, two client launches.'
