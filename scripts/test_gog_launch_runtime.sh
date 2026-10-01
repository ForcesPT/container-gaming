#!/bin/bash
# Disposable container only: actual wrapper, verified vendor PE, stub runtime.
set -euo pipefail
export HOME=/home/dpad
task_prefix=/tmp/dpad-gog-runtime-prefix
install -d -m 700 -o dpad -g dpad "$task_prefix"
install -d -m 700 -o dpad -g dpad "$task_prefix/drive_c/Program Files/GOG Galaxy"
cp '/opt/dpadcloud/gog-prefix/drive_c/Program Files/GOG Galaxy/GalaxyClient.exe' \
   "$task_prefix/drive_c/Program Files/GOG Galaxy/GalaxyClient.exe"
chown dpad:dpad "$task_prefix/drive_c/Program Files/GOG Galaxy/GalaxyClient.exe"
cat >/usr/bin/umu-run <<'STUB'
#!/bin/bash
set -euo pipefail
test "$PROTONPATH" = /home/dpad/.steam/debian-installation/compatibilitytools.d/GE-Proton11-7
test "$WINEPREFIX" = /tmp/dpad-gog-runtime-prefix
test "$1" = 'C:\Program Files\GOG Galaxy\GalaxyClient.exe'
test "$2" = --in-process-gpu && test "$3" = /deelevated && test "$#" = 3
echo GOG_NATIVE_PATH_RUNTIME_PASS
STUB
chmod +x /usr/bin/umu-run
runuser -u dpad -- env WINEPREFIX="$task_prefix" DPAD_GOG_BACKEND=official \
    /opt/dpadcloud/gog-launch >/tmp/dpad-gog-runtime-output.log 2>&1
test ! -s /tmp/dpad-gog-runtime-output.log
log=/home/dpad/.local/state/dpad-stores/gog-launch.log
grep -q GOG_NATIVE_PATH_RUNTIME_PASS "$log"
test "$(stat -c %a "$log")" = 600
echo 'GOG_NATIVE_PATH_WRAPPER_PASS private_log=600 runtime=GE-Proton11-7'
