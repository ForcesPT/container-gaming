#!/bin/bash
# Pre-bootstrap the full Steam client at image BUILD time.
#
# Downloads the ~300MB Steam client into ~/.steam/debian-installation
# (ubuntu12_64/steamwebhelper is the completion marker) so a fresh-boot
# container's entrypoint bootstrap_steam_on_xvfb() is a NO-OP and gamescope +
# Steam come up in ~40s instead of a ~3-4min first-run download.
#
# Runs on Xvfb :8 + mesa/llvmpipe (SOFTWARE GL) — NO GPU needed, so it works in
# a plain `docker build` with no NVIDIA runtime. Does NOT log in (just
# downloads the client) -> no Steam Guard at build time. The zenity license
# wrapper (Dockerfile step 4c) auto-accepts the Steam "proprietary (binary-
# only)" prompt so the bootstrap is non-interactive.
#
# Idempotent: the entrypoint's bootstrap_steam_on_xvfb() skips if
# ubuntu12_64/steamwebhelper is already present, so this just front-loads it.
# Best-effort: ALWAYS exits 0. If the download fails (flaky network, etc.) the
# build still succeeds and the entrypoint re-bootstraps at runtime as a
# safety net — the only cost is a slower first boot, never a broken image.
#
# Invoked by the Dockerfile (9g) as root; re-execs itself as the dpad user to
# do the actual bootstrap (Steam must run as the desktop user, matching the
# runtime env).
set -u

USERNAME="dpad"
PUID="1001"
HOME_DIR="/home/dpad"
INSTALL="${HOME_DIR}/.steam/debian-installation"

# Already bootstrapped? (e.g. layer cache hit on a rebuild) -> nothing to do.
if [ -x "${INSTALL}/ubuntu12_64/steamwebhelper" ]; then
  echo "[*] Steam already bootstrapped — skipping build-time bootstrap"
  exit 0
fi

# --- dpad (non-root) path: the actual bootstrap ---------------------------
if [ "$(id -u)" -ne 0 ]; then
  cd "${HOME_DIR}"
  # Session D-Bus — Steam's CEF wants one even for the bootstrap download.
  eval "$(dbus-launch --sh-syntax 2>/dev/null)" || true
  export DBUS_SESSION_BUS_ADDRESS
  Xvfb :8 -screen 0 1280x720x24 +extension GLX +extension RANDR >/tmp/xvfb-bootstrap.log 2>&1 &
  sleep 2
  export DISPLAY=:8 HOME="${HOME_DIR}" USER="${USERNAME}" XDG_RUNTIME_DIR="/run/user/${PUID}"

  ok=0; tries=0
  while [ $tries -lt 3 ] && [ $ok -eq 0 ]; do
    tries=$((tries+1))
    rm -f "${HOME_DIR}/.steam/steam.pid" "${INSTALL}/steam.pid" "${HOME_DIR}/.steam/steam.pipe" 2>/dev/null || true
    /usr/bin/steam -gamepadui >/tmp/steam-bootstrap.log 2>&1 & sp=$!
    waited=0
    while [ $waited -lt 360 ]; do
      [ -x "${INSTALL}/ubuntu12_64/steamwebhelper" ] && { ok=1; break; }
      kill -0 "$sp" 2>/dev/null || break
      sleep 3; waited=$((waited+3))
    done
    kill "$sp" 2>/dev/null || true
    pkill -9 -u "${USERNAME}" -x steam 2>/dev/null || true
    pkill -9 -u "${USERNAME}" -x steamwebhelper 2>/dev/null || true
    rm -f "${HOME_DIR}/.steam/steam.pid" "${INSTALL}/steam.pid" "${HOME_DIR}/.steam/steam.pipe" 2>/dev/null || true
    [ $ok -eq 0 ] && { echo "    build-time bootstrap attempt $tries incomplete; retrying..."; sleep 3; }
  done
  pkill -9 -u "${USERNAME}" -x Xvfb 2>/dev/null || true
  if [ $ok -eq 1 ]; then
    echo "[*] build-time Steam bootstrap OK (ubuntu12_64/steamwebhelper present)"
  else
    echo "[*] WARNING: build-time Steam bootstrap incomplete (entrypoint will retry at boot)"
    tail -20 /tmp/steam-bootstrap.log 2>/dev/null | sed 's/^/    /'
  fi
  exit 0
fi

# --- root path: set up dirs, chown, re-exec as dpad -----------------------
mkdir -p "/run/user/${PUID}" "${INSTALL}/compatibilitytools.d"
# chown ALL of ~dpad — a prior root build step may have left ~/.local root-owned,
# which makes Steam's `mkdir ~/.local/share/icons` EPERM and abort the bootstrap
# (same fix as the entrypoint's bootstrap_steam_on_xvfb).
chown -R "${USERNAME}:${USERNAME}" "${HOME_DIR}" "/run/user/${PUID}" 2>/dev/null || true
exec su -s /bin/bash "${USERNAME}" -c "$0"