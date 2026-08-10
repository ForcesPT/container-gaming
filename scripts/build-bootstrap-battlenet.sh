#!/bin/bash
# Pre-bootstrap the Battle.net Wine prefix at image BUILD time (STORES-PLAN
# §7 piece 2 / §10 piece 2). Cuts the ~2-min `umu-run winetricks` (corefonts
# win10 vcrun2022 d3dcompiler_47) + the Steam Linux Runtime download
# (~657 MB to ~/.local/share/umu) from every first Battle.net launch — the
# prefix + SLR are baked, so a first launch only runs the Blizzard installer
# (the user clicks through it in the stream) + logs in.
#
# Why only the prefix (not the full Battle.net install): the Battle.net-Setup
# Chromium GUI won't complete headless (it needs a real display/interaction to
# finish downloading Battle.net.exe — validated: even with --disable-gpu under
# Xvfb the Agent.exe launches but the install stalls before Battle.net.exe).
# So the build bakes everything UP TO the installer: the winetricks-initialized
# prefix + the Battle.net.config + the downloaded Battle.net-Setup.exe. The
# runtime wrapper (battlenet-launch) copies this prefix to the session's
# WINEPREFIX on first launch + runs the installer there (with the user).
#
# Runs as the dpad user (umu-run + the SLR must land in ~dpad, matching the
# runtime env) on Xvfb :9 + mesa/llvmpipe (SOFTWARE GL — NO GPU needed, works
# in a plain `docker build`). Idempotent + best-effort: always exits 0; if the
# winetricks/SLR download fails (flaky network), the build still succeeds +
# battlenet-launch falls back to the full runtime winetricks (the prebaked
# marker is only written on success).
#
# Bakes:
#   /opt/dpadcloud/battlenet-prefix         the winetricks-initialized Wine prefix
#                                            (+ Battle.net.config + Setup.exe +
#                                             a .dpad-prebaked marker), owned by
#                                             dpad — the runtime copy SOURCE.
#   /home/dpad/.local/share/umu             the Steam Linux Runtime (~657 MB),
#                                            reused at runtime (no first-run
#                                            umu SLR download).
# Invoked by the Dockerfile (vast-vm, piece (f)) as root; re-execs as dpad.
set -u

USERNAME="dpad"
PUID="1001"
HOME_DIR="/home/dpad"
GP_DIR="${HOME_DIR}/.steam/debian-installation/compatibilitytools.d/GE-Proton11-3"
PREFIX_SRC="/opt/dpadcloud/battlenet-prefix"   # the baked copy source (stable image path, NOT ~/Games which setup_stores symlinks to the volume at runtime)
MARKER="${PREFIX_SRC}/.dpad-prebaked"

# Already prebaked? (layer cache hit on a rebuild) -> nothing to do.
if [ -f "${MARKER}" ]; then
  echo "[*] Battle.net prefix already prebaked — skipping build-time bootstrap"
  exit 0
fi

# --- dpad (non-root) path: the actual prebake -----------------------------
if [ "$(id -u)" -ne 0 ]; then
  cd "${HOME_DIR}"
  eval "$(dbus-launch --sh-syntax 2>/dev/null)" || true
  export DBUS_SESSION_BUS_ADDRESS
  Xvfb :9 -screen 0 1280x720x24 +extension GLX +extension RANDR >/tmp/xvfb-bnet.log 2>&1 &
  sleep 2
  export DISPLAY=:9 HOME="${HOME_DIR}" USER="${USERNAME}" XDG_RUNTIME_DIR="/run/user/${PUID}"
  export WINEPREFIX="${PREFIX_SRC}"
  export PROTONPATH="${GP_DIR}"
  export STORE=battlenet GAMEID=umu-battlenet PROTON_VERB=waitforexitandrun
  export WINE_SIMULATE_WRITECOPY=1 WINEDLLOVERRIDES=locationapi=d WINEDEBUG=-all
  unset LD_PRELOAD  # don't leak the (absent-at-build) gamepad interposer into the SLR

  ok=0
  echo "[*] build-time Battle.net prebake: umu-run winetricks (downloads the SLR ~657 MB + applies corefonts win10 vcrun2022 d3dcompiler_47)..."
  if umu-run winetricks -q corefonts win10 vcrun2022 d3dcompiler_47 >/tmp/bnet-prebuild-wt.log 2>&1; then
    ok=1
  else
    echo "[*] WARNING: build-time umu-run winetricks exited non-zero (see /tmp/bnet-prebuild-wt.log); the runtime wrapper will fall back to the full winetricks"
    tail -20 /tmp/bnet-prebuild-wt.log 2>/dev/null | grep -vE 'fsync: up' | sed 's/^/    /' | tail -10
  fi

  if [ "$ok" = 1 ]; then
    # Pre-write Battle.net.config (disable HW accel/sound/streaming — the
    # launcher is Chromium/CEF; HW accel misrenders headless/XWayland). Proton
    # runs the Wine prefix as the `steamuser` Windows profile (the confirmed
    # path from the live test), so write it there.
    bn_cfg_dir="${PREFIX_SRC}/drive_c/users/steamuser/AppData/Roaming/Battle.net"
    mkdir -p "$bn_cfg_dir" 2>/dev/null || true
    printf '%s' '{"Client":{"GameLaunchWindowBehavior":"2","GameSearch":{"BackgroundSearch":"true"},"HardwareAcceleration":"false","Install":{"DownloadLimitNextPatchInBps":"0"},"Sound":{"Enabled":"false"},"Streaming":{"StreamingEnabled":"false"}},"Games":{"s2":{"AdditionalLaunchArguments":"-Displaymode 1"}}}' \
      > "$bn_cfg_dir/Battle.net.config"
    echo "[*] wrote $bn_cfg_dir/Battle.net.config"

    # Download the Blizzard installer into the prefix (do NOT run it — it needs
    # interaction; the runtime wrapper runs it after copying the prefix). The
    # getInstallerForGame endpoint (the working one from the live test).
    setup_dir="${PREFIX_SRC}/drive_c/battlenet-setup"
    mkdir -p "$setup_dir" 2>/dev/null || true
    if curl -fsSL -A "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36" \
        -o "$setup_dir/Battle.net-Setup.exe" \
        "https://www.battle.net/download/getInstallerForGame?os=win&version=LIVE&gameProgram=BATTLENET_APP" 2>/dev/null; then
      echo "[*] downloaded Battle.net-Setup.exe ($(ls -l "$setup_dir/Battle.net-Setup.exe" 2>/dev/null | awk '{print $5}') bytes)"
    else
      echo "[*] WARNING: Battle.net-Setup.exe download failed (the runtime wrapper will download it)"
      ok=0
    fi
  fi

  # Kill the build-time wineserver + Xvfb (don't leave processes around).
  pkill -9 -u "${USERNAME}" -x wineserver 2>/dev/null || true
  pkill -9 -u "${USERNAME}" -x Xvfb 2>/dev/null || true

  if [ "$ok" = 1 ]; then
    # Marker: only on full success (prefix init + config + Setup.exe). The
    # runtime wrapper copies the prefix only if the marker is present.
    touch "${MARKER}"
    echo "[*] build-time Battle.net prebake OK (prefix + SLR + config + Setup.exe baked at ${PREFIX_SRC})"
  else
    echo "[*] build-time Battle.net prebake INCOMPLETE — runtime wrapper will do the full winetricks (no harm, just slower first launch)"
  fi
  exit 0
fi

# --- root path: set up dirs, chown, re-exec as dpad -----------------------
mkdir -p "${PREFIX_SRC}" "/run/user/${PUID}"
# chown the prefix src + ~dpad (a prior root build step may have left
# ~/.local root-owned -> umu's mkdir ~/.local/share/umu EPERM).
chown -R "${USERNAME}:${USERNAME}" "${PREFIX_SRC}" "${HOME_DIR}" "/run/user/${PUID}" 2>/dev/null || true
exec su -s /bin/bash "${USERNAME}" -c "$0"