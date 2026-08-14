#!/bin/bash
# Pre-bootstrap the EA App Wine prefix at image BUILD time — mirrors
# build-bootstrap-battlenet.sh. Cuts the ~2-min `umu-run winetricks`
# (corefonts win10 vcrun2022 d3dcompiler_47) + the Steam Linux Runtime
# download (~657 MB to ~/.local/share/umu) + the EAappInstaller.exe
# download from every first EA App launch.
#
# What gets baked (same as Battle.net):
#   /opt/dpadcloud/ea-prefix          the winetricks-initialized Wine prefix
#                                     (+ EAappInstaller.exe + a .dpad-prebaked
#                                      marker), owned by dpad — the runtime
#                                      copy source.
#   /home/dpad/.local/share/umu       the Steam Linux Runtime (~657 MB),
#                                     reused at runtime (no first-run umu SLR
#                                     download). SHARED with battlenet-prefix
#                                     (the SLR is the same for all umu-run
#                                     stores — only downloaded once).
#
# The EA App installer (EAappInstaller.exe) is a Chromium/CEF GUI — it may
# not complete headless (same limitation as Battle.net-Setup.exe). So the
# build bakes everything UP TO the installer: the winetricks-initialized
# prefix + the downloaded EAappInstaller.exe. The runtime wrapper
# (ea-launch) copies this prefix to the session's WINEPREFIX on first
# launch + runs the installer there (with the user in the stream). If the
# silent install succeeds (best-effort), the runtime skips the installer
# entirely → first click goes straight to login.
#
# Runs as the dpad user (umu-run + the SLR must land in ~dpad, matching the
# runtime env) on Xvfb :9 + mesa/llvmpipe (SOFTWARE GL — NO GPU needed).
#
# ⚠️ BAKE METHOD (same as battlenet): does NOT work under standard buildkit
# `docker build` — wineserver/wine crash in buildkit's user-namespace
# sandbox. Bake via the privileged-container + commit workflow:
#   1. docker run --privileged --entrypoint /bin/bash <img> /tmp/this-script
#   2. docker commit -c 'ENTRYPOINT ["/opt/dpadcloud/entrypoint.sh"]' \
#                     -c 'CMD ["/bin/bash"]' <container> <img>
# Idempotent + best-effort: always exits 0.
#
# Invoked by the Dockerfile (vast-vm) as root; re-execs as dpad.
set -u

USERNAME="dpad"
PUID="1001"
HOME_DIR="/home/dpad"
GP_DIR="${HOME_DIR}/.steam/debian-installation/compatibilitytools.d/GE-Proton11-3"
PREFIX_SRC="/opt/dpadcloud/ea-prefix"
MARKER="${PREFIX_SRC}/.dpad-prebaked"

# Already prebaked? (layer cache hit on a rebuild) -> nothing to do.
if [ -f "${MARKER}" ]; then
  echo "[*] EA App prefix already prebaked — skipping build-time bootstrap"
  exit 0
fi

# --- dpad (non-root) path: the actual prebake -----------------------------
if [ "$(id -u)" -ne 0 ]; then
  cd "${HOME_DIR}"
  eval "$(dbus-launch --sh-syntax 2>/dev/null)" || true
  export DBUS_SESSION_BUS_ADDRESS
  Xvfb :9 -screen 0 1280x720x24 +extension GLX +extension RANDR >/tmp/xvfb-ea.log 2>&1 &
  sleep 2
  export DISPLAY=:9 HOME="${HOME_DIR}" USER="${USERNAME}" XDG_RUNTIME_DIR="/run/user/${PUID}"
  export WINEPREFIX="${PREFIX_SRC}"
  export PROTONPATH="${GP_DIR}"
  export STORE=eaapp GAMEID=umu-eaapp PROTON_VERB=waitforexitandrun
  export WINE_SIMULATE_WRITECOPY=1 WINEDLLOVERRIDES=locationapi=d WINEDEBUG=-all
  unset LD_PRELOAD

  ok=0
  echo "[*] build-time EA App prebake: umu-run winetricks (downloads the SLR ~657 MB + applies corefonts win10 vcrun2022 d3dcompiler_47)..."
  if umu-run winetricks -q corefonts win10 vcrun2022 d3dcompiler_47 >/tmp/ea-prebuild-wt.log 2>&1; then
    ok=1
  else
    echo "[*] WARNING: build-time umu-run winetricks exited non-zero (see /tmp/ea-prebuild-wt.log); the runtime wrapper will fall back to the full winetricks"
    tail -20 /tmp/ea-prebuild-wt.log 2>/dev/null | grep -vE 'fsync: up' | sed 's/^/    /' | tail -10
  fi

  if [ "$ok" = 1 ]; then
    # Download the EA App installer into the prefix.
    setup_dir="${PREFIX_SRC}/drive_c/ea-setup"
    mkdir -p "$setup_dir" 2>/dev/null || true
    SETUP_URL='https://origin-a.akamaihd.net/EA-Desktop-Client-Download/installer-releases/EAappInstaller.exe'
    UA='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36'
    if curl -fsSL -A "$UA" -o "$setup_dir/EAappInstaller.exe" "$SETUP_URL" 2>/dev/null; then
      echo "[*] downloaded EAappInstaller.exe ($(ls -l "$setup_dir/EAappInstaller.exe" 2>/dev/null | awk '{print $5}') bytes)"

      # Best-effort silent install: EAappInstaller.exe may support /silent
      # or --silent. If it produces EALauncher.exe, the runtime skips the
      # installer entirely. If it fails, the runtime runs the installer
      # with the user in the stream (no harm).
      ea_dir="${PREFIX_SRC}/drive_c/Program Files/Electronic Arts/EA Desktop/EA Desktop"
      if command -v umu-run >/dev/null 2>&1; then
        echo "[*] silent-installing EA App (umu-run EAappInstaller.exe)..."
        umu-run "$setup_dir/EAappInstaller.exe" >/tmp/ea-silent-build.log 2>&1 &
        si_pid=$!
        si=0
        while [ "$si" -lt 54 ] && [ ! -f "$ea_dir/EALauncher.exe" ] && [ ! -f "$ea_dir/EADesktop.exe" ]; do
          sleep 10; si=$((si+1))
          kill -0 "$si_pid" 2>/dev/null || break
        done
        if [ -f "$ea_dir/EALauncher.exe" ] || [ -f "$ea_dir/EADesktop.exe" ]; then
          echo "[*] EA App silent-installed OK (launcher exe present — runtime will skip the installer)"
        else
          echo "[*] WARNING: EA App silent-install did not produce the launcher (prefix + installer prebake only; runtime will run the installer)"
        fi
        pkill -9 -u "${USERNAME}" -f 'EA|EALauncher|EADesktop|wineserver|umu-run' 2>/dev/null || true
      fi
    else
      echo "[*] WARNING: EAappInstaller.exe download failed (the runtime wrapper will download it)"
      ok=0
    fi
  fi

  # Kill the build-time wineserver + Xvfb.
  pkill -9 -u "${USERNAME}" -x wineserver 2>/dev/null || true
  pkill -9 -u "${USERNAME}" -x Xvfb 2>/dev/null || true

  if [ "$ok" = 1 ]; then
    touch "${MARKER}"
    echo "[*] build-time EA App prebake OK (prefix + SLR + installer baked at ${PREFIX_SRC})"
  else
    echo "[*] build-time EA App prebake INCOMPLETE — runtime wrapper will do the full winetricks (no harm, just slower first launch)"
  fi
  exit 0
fi

# --- root path: set up dirs, chown, re-exec as dpad -----------------------
mkdir -p "${PREFIX_SRC}" "/run/user/${PUID}"
chown -R "${USERNAME}:${USERNAME}" "${PREFIX_SRC}" "${HOME_DIR}" "/run/user/${PUID}" 2>/dev/null || true
exec su -s /bin/bash "${USERNAME}" -c "$0"