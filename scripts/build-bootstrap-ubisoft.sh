#!/bin/bash
# Privileged post-build Ubisoft Connect prefix installer.
# Run only through build-preinstall-stores.sh inside a disposable --privileged
# container; standard BuildKit cannot run umu/pressure-vessel/bwrap reliably.
set -u

USERNAME=dpad
PUID=1001
HOME_DIR=/home/dpad
GP_DIR="${HOME_DIR}/.steam/debian-installation/compatibilitytools.d/GE-Proton11-3"
PREFIX_SRC=/opt/dpadcloud/ubisoft-prefix
MARKER="${PREFIX_SRC}/.dpad-prebaked"

if { [ -f "$MARKER" ] || [ -f "${PREFIX_SRC}/.dpad-preinstalled" ]; } && \
   { [ -f "${PREFIX_SRC}/drive_c/Program Files (x86)/Ubisoft/Ubisoft Game Launcher/UbisoftConnect.exe" ] || \
     [ -f "${PREFIX_SRC}/drive_c/Program Files (x86)/Ubisoft/Ubisoft Game Launcher/upc.exe" ]; }; then
  echo "[*] Ubisoft Connect client already preinstalled"
  exit 0
fi

if [ "$(id -u)" -ne 0 ]; then
  cd "$HOME_DIR"
  eval "$(dbus-launch --sh-syntax 2>/dev/null)" || true
  export DBUS_SESSION_BUS_ADDRESS
  pkill -9 -u "$USERNAME" -x Xvfb 2>/dev/null || true
  rm -f /tmp/.X9-lock /tmp/.X11-unix/X9
  Xvfb :9 -screen 0 1280x720x24 +extension GLX +extension RANDR >/tmp/xvfb-ubisoft.log 2>&1 &
  sleep 2
  export DISPLAY=:9 HOME="$HOME_DIR" USER="$USERNAME" XDG_RUNTIME_DIR="/run/user/${PUID}"
  export WINEPREFIX="$PREFIX_SRC" PROTONPATH="$GP_DIR"
  export STORE=ubisoft GAMEID=umu-ubisoft PROTON_VERB=waitforexitandrun
  export WINE_SIMULATE_WRITECOPY=1 WINEDLLOVERRIDES=locationapi=d WINEDEBUG=-all
  unset LD_PRELOAD

  ok=0
  echo "[*] privileged Ubisoft preinstall: initializing prefix"
  if ! umu-run winetricks -q corefonts win10 vcrun2022 d3dcompiler_47 >/tmp/ubisoft-prebuild-wt.log 2>&1; then
    echo "[*] WARNING: winetricks exited non-zero; continuing to the installer because final executable verification is authoritative"
  fi
  setup_dir="$PREFIX_SRC/drive_c/ubisoft-setup"
  setup_exe="$setup_dir/UbisoftConnectInstaller.exe"
  ubi_dir="$PREFIX_SRC/drive_c/Program Files (x86)/Ubisoft/Ubisoft Game Launcher"
  mkdir -p "$setup_dir"
  if curl -fsSL -A 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)' -o "$setup_exe" https://ubi.li/4vxt9 \
      && /opt/dpadcloud/dpad-verify-windows-binary \
        --publisher 'UBISOFT ENTERTAINMENT INC.' \
        --ca-file /opt/dpadcloud/microsoft-identity-root-2020.pem \
        --ca-sha256 5367f20c7ade0e2bca790915056d086b720c33c1fa2a2661acf787e3292e1270 \
        --trusted-signing-time "$setup_exe"; then
    echo "[*] silent-installing Ubisoft Connect"
    umu-run "$setup_exe" /S >/tmp/ubisoft-silent-build.log 2>&1 &
    installer_pid=$!
    for _ in $(seq 1 90); do
      if [ -f "$ubi_dir/UbisoftConnect.exe" ] || [ -f "$ubi_dir/upc.exe" ]; then ok=1; break; fi
      kill -0 "$installer_pid" 2>/dev/null || true
      sleep 10
    done
    kill "$installer_pid" 2>/dev/null || true
    sleep 2
    kill -9 "$installer_pid" 2>/dev/null || true
    wait "$installer_pid" 2>/dev/null || true
  fi

  pkill -9 -u "$USERNAME" -f 'Ubisoft|upc.exe|wineserver|umu-run' 2>/dev/null || true
  pkill -9 -u "$USERNAME" -x Xvfb 2>/dev/null || true
  if [ "$ok" = 1 ]; then
    touch "$MARKER"
    echo "[*] Ubisoft Connect preinstall complete"
  else
    echo "[*] Ubisoft Connect preinstall incomplete" >&2
  fi
  exit 0
fi

install -d -m 0755 -o "$USERNAME" -g "$USERNAME" "$PREFIX_SRC" "/run/user/${PUID}"
exec su -s /bin/bash "$USERNAME" -c "$0"
