#!/bin/bash
# =============================================================================
# DpadCloud Gaming Container Entrypoint (Ubuntu 24.04)
# Boot order:
#   D-Bus -> Steam bootstrap check -> PipeWire -> coturn -> Selkies
#   -> gst-wayland-display compositor -> nested Sway -> DpadPlay launcher
#   -> Valve Steam desktop client or another selected store application
# =============================================================================

set -o pipefail

# NVRTC fix: ensure libnvrtc 12.9.86 is in the GStreamer lib dir before
# selkies-gstreamer starts (the bundled 11.4 can't JIT for sm_89 L4/Ada or
# sm_120 Blackwell → cudaconvert's NVRTC JIT fails → no capturable video →
# browser stuck on "Waiting for stream"). Idempotent + tolerant: a no-op if
# the image baked it (Dockerfile 4b) or a prior run already installed it; on a
# download failure it leaves the bundled lib in place (boot still works, just
# with the NVRTC error). Ships to EXISTING images via the entrypoint bind-mount
# hotfix path (no Docker Hub rebuild). STORES-PLAN.md §17.2/§17.5, PROJECT_STATE.md
# §6 #10.
bash /opt/dpadcloud/extract-nvrtc.sh 2>/dev/null || true

echo "=========================================="
echo "  DpadCloud Gaming Container Booting..."
echo "=========================================="

USER_NAME="dpad"
USER_HOME="/home/dpad"
DISPLAY_NUM="${DISPLAY:-:0}"
SCREEN_RES="${SCREEN_RESOLUTION:-1920x1080x24}"

# --- Config from env (Vast sets PUBLIC_IPADDR, OPEN_BUTTON_TOKEN, VAST_*_PORT) ---
PUBLIC_IP="${PUBLIC_IPADDR:-}"
if [ -z "$PUBLIC_IP" ]; then
    PUBLIC_IP="$(curl -fs4 -m 5 https://checkip.amazonaws.com 2>/dev/null | tr -d '[:space:]')"
fi
[ -z "$PUBLIC_IP" ] && PUBLIC_IP="$(curl -fs4 -m 5 https://api.ipify.org 2>/dev/null | tr -d '[:space:]')"
OPEN_TOKEN="${OPEN_BUTTON_TOKEN:-dpadcloud}"
SUNSHINE_PASS="${SUNSHINE_PASSWORD:-dpadcloud}"
SELKIES_USER="${SELKIES_BASIC_AUTH_USER:-dpad}"
SELKIES_PASS="${SELKIES_BASIC_AUTH_PASSWORD:-${OPEN_TOKEN}}"
TURN_USER="${TURN_USERNAME:-turnuser}"
TURN_PASS="${TURN_PASSWORD:-${OPEN_TOKEN}}"
# Auto-detect the exposed coturn port. Vast sets VAST_(TCP|UDP)_PORT_<internal>=<external>
# for each -p <internal>:<internal>. coturn must LISTEN on the INTERNAL port
# (the -p internal side) while the browser ICE uses the EXTERNAL (the value).
# Prefer the identity port 73478, then the standard TURN port 3478; override the
# internal listen port with DPAD_COTURN_PORT. (The previous hardcode of 73478
# broke hosts/templates that expose 3478 instead — coturn bound 73478 internally
# but the port-forward targeted 3478, so coturn was unreachable → "Connection
# Failed".) Try TCP first, then UDP.
TURN_PORT_LISTEN="${DPAD_COTURN_PORT:-${TURN_PORT_LISTEN:-}}"
TURN_PORT_EXT=""
for _p in 73478 3478; do
    _v="$(printenv "VAST_TCP_PORT_$_p" 2>/dev/null | tr -d '[:space:]')"
    [ -z "$_v" ] && _v="$(printenv "VAST_UDP_PORT_$_p" 2>/dev/null | tr -d '[:space:]')"
    if [ -n "$_v" ]; then
        TURN_PORT_EXT="$_v"
        [ -z "$TURN_PORT_LISTEN" ] && TURN_PORT_LISTEN="$_p"
        break
    fi
done
# Fallback: nothing detected → assume 1:1 on the standard TURN port 3478.
[ -z "$TURN_PORT_EXT" ] && TURN_PORT_EXT="${TURN_PORT_LISTEN:-3478}"
[ -z "$TURN_PORT_LISTEN" ] && TURN_PORT_LISTEN="3478"

# --- Provider: RunPod (userns-capable; no UDP; TCP port proxying) ------------
# RunPod has no UDP and maps each TCP port to publicIp:<externalPort> where
# externalPort != the internal port by default. The RunPod *console UI* also
# caps port numbers at 65535, so the >70000 "symmetrical port" request tokens
# (which the REST API accepts as a special signal) cannot be entered via the UI.
# So we expose coturn's listening port (3478, the standard TURN port) as a normal
# TCP port: coturn binds 3478 internally (TURN_PORT_LISTEN), and the entrypoint
# queries the RunPod API for the mapped EXTERNAL port (portMappings["3478"]) +
# the pod publicIp, then points the browser's TURN ICE server at
# publicIp:<externalPort> (TURN_PORT_EXT).
# Why a single normal port is enough: when both WebRTC peers are TURN clients of
# the SAME coturn, media relays internally over their two control connections to
# coturn's listening port; the per-allocation relay ports are never contacted
# externally. So only coturn's listening port needs to be reachable. The web UI
# is published by the DpadPlay stream-bridge/Caddy path.
DPAD_PROVIDER="${DPAD_PROVIDER:-}"
if [ -z "$DPAD_PROVIDER" ] && [ -n "${RUNPOD_POD_ID:-}" ]; then
    DPAD_PROVIDER="runpod"
fi
TURN_PORT_LISTEN="${TURN_PORT_LISTEN:-${TURN_PORT_EXT}}"   # port coturn binds (internal)
if [ "$DPAD_PROVIDER" = "runpod" ]; then
    RUNPOD_COTURN_PORT="${DPAD_COTURN_PORT:-3478}"   # internal port coturn binds + the TCP port you expose (≤65535 for the RunPod UI)
    TURN_PORT_LISTEN="$RUNPOD_COTURN_PORT"
fi

# The launcher passes --shm-size=2g for Steam/Electron CEF. The session uses
# render-node EGL only and never requires a display-owner mode or DRM master.

# Resolve the RunPod public IP + mapped external TURN port. Idempotent: manual
# overrides (DPAD_TURN_PUBLIC_IP / DPAD_TURN_EXTERNAL_PORT) win and short-circuit;
# otherwise query the RunPod API. portMappings/publicIp are empty during early
# init, so this is called AGAIN lazily right before Selkies/mws launch (~60s
# in), when the data is reliably populated.
runpod_resolve_turn() {
  [ "$DPAD_PROVIDER" = "runpod" ] || return 0
  # Priority (highest first):
  #   1. Manual override envs (DPAD_TURN_PUBLIC_IP / DPAD_TURN_EXTERNAL_PORT)
  #   2. RunPod-injected envs: RUNPOD_PUBLIC_IP + RUNPOD_TCP_PORT_<internal>
  #      (RunPod auto-injects RUNPOD_PUBLIC_IP and, for each exposed TCP port N,
  #      RUNPOD_TCP_PORT_N = the external mapped port. See RunPod env-vars docs.
  #      This is the reliable, zero-config path — no API call, no manual lookup.)
  #   3. RunPod REST API (best-effort; the injected envs above usually suffice)
  # PUBLIC_IP was also pre-resolved via checkip at the top of the entrypoint
  # (on RunPod Community Cloud the egress IP usually == the public IP).
  if [ -n "${DPAD_TURN_PUBLIC_IP:-}" ]; then
    PUBLIC_IP="$DPAD_TURN_PUBLIC_IP"
  elif [ -n "${RUNPOD_PUBLIC_IP:-}" ]; then
    PUBLIC_IP="$RUNPOD_PUBLIC_IP"
  fi
  if [ -n "${DPAD_TURN_EXTERNAL_PORT:-}" ]; then
    TURN_PORT_EXT="$DPAD_TURN_EXTERNAL_PORT"
  else
    # RUNPOD_TCP_PORT_<internal> (e.g. RUNPOD_TCP_PORT_3478) = external mapped port
    local rp_var="RUNPOD_TCP_PORT_${RUNPOD_COTURN_PORT}"
    local rp_ext="${!rp_var:-}"
    if [ -n "$rp_ext" ]; then
      TURN_PORT_EXT="$rp_ext"
    else
      # Vast KVM VM: Vast maps the exposed coturn port to a random external
      # port, injected as VAST_TCP_PORT_<internal> (see docs.vast.ai networking).
      # PUBLIC_IPADDR (read into PUBLIC_IP at the top of the entrypoint) is the
      # public IP. The launcher must pass these Vast envs into the container.
      local vast_var="VAST_TCP_PORT_${RUNPOD_COTURN_PORT}"
      local vast_ext="${!vast_var:-}"
      if [ -n "$vast_ext" ]; then
        TURN_PORT_EXT="$vast_ext"
      fi
    fi
  fi
  # If the injected envs gave us both, done — no API needed.
  if [ -n "${RUNPOD_PUBLIC_IP:-}" ] && [ -n "${!RUNPOD_TCP_PORT_${RUNPOD_COTURN_PORT}:-}" ]; then
    return 0
  fi
  # API fallback for whatever's still missing (RUNPOD_API_KEY is pod-scoped).
  if [ -n "${RUNPOD_API_KEY:-}" ] && [ -n "${RUNPOD_POD_ID:-}" ]; then
    local ip="" ext="" json=""
    for i in 1 2 3 4 5; do
      json="$(curl -fsS -m 5 -H "Authorization: Bearer ${RUNPOD_API_KEY}" \
          "https://rest.runpod.io/v1/pods/${RUNPOD_POD_ID}" 2>/dev/null || true)"
      [ -z "$ip" ] && [ -z "${RUNPOD_PUBLIC_IP:-}" ] && [ -z "${DPAD_TURN_PUBLIC_IP:-}" ] \
        && ip="$(printf '%s' "$json" | sed -n 's/.*"publicIp"[[:space:]]*:[[:space:]]*"\([0-9.]*\)".*/\1/p' | head -1)"
      [ -z "$ext" ] && [ -z "${!RUNPOD_TCP_PORT_${RUNPOD_COTURN_PORT}:-}" ] && [ -z "${DPAD_TURN_EXTERNAL_PORT:-}" ] \
        && ext="$(printf '%s' "$json" | sed -n "s/.*\"${RUNPOD_COTURN_PORT}\"[[:space:]]*:[[:space:]]*\([0-9][0-9]*\).*/\1/p" | head -1)"
      [ -n "$ip" ] && [ -n "$ext" ] && break
      sleep 3
    done
    [ -n "$ip" ] && [ -z "${RUNPOD_PUBLIC_IP:-}" ] && [ -z "${DPAD_TURN_PUBLIC_IP:-}" ] && PUBLIC_IP="$ip"
    [ -n "$ext" ] && [ -z "${!RUNPOD_TCP_PORT_${RUNPOD_COTURN_PORT}:-}" ] && [ -z "${DPAD_TURN_EXTERNAL_PORT:-}" ] && TURN_PORT_EXT="$ext"
  fi
}
runpod_resolve_turn   # early best-effort (RunPod injects RUNPOD_PUBLIC_IP + RUNPOD_TCP_PORT_<n> at boot, so this usually resolves immediately)
if [ "$DPAD_PROVIDER" = "runpod" ]; then
    _rp_port_var="RUNPOD_TCP_PORT_${RUNPOD_COTURN_PORT}"
    echo "[*] Provider: RunPod  coturn_listen=${TURN_PORT_LISTEN}  turn_ext=${TURN_PORT_EXT}  public_ip=${PUBLIC_IP:-<pending>}"
    echo "    RunPod env: RUNPOD_PUBLIC_IP=${RUNPOD_PUBLIC_IP:-<unset>}  ${_rp_port_var}=${!_rp_port_var:-<unset>}  RUNPOD_POD_ID=${RUNPOD_POD_ID:-<unset>}"
fi

# --- Helper: wait for a unix socket ---
wait_sock() {
  local sock="$1" name="${2:-socket}"
  local i=0
  while [ $i -lt 120 ]; do
    if [ -S "$sock" ] && timeout 1 socat -u OPEN:/dev/null "UNIX-CONNECT:${sock}" >/dev/null 2>&1; then
      echo "    ${name} ready"; return 0
    fi
    sleep 1; i=$((i+1))
  done
  echo "    WARNING: ${name} (${sock}) not ready after 120s"; return 1
}

as_user() { su -s /bin/bash "${USER_NAME}" -c "$1"; }

# --- Steam first-run bootstrap on Xvfb (software GL) ---
# Download and initialize the full official client before the interactive desktop.
# This keeps the first launcher click fast and avoids presenting the updater as the
# user's first Steam window. Idempotent when the build-time bootstrap succeeded.
bootstrap_steam_on_xvfb() {
    local steam_install="${USER_HOME}/.steam/debian-installation"
    if [ -x "${steam_install}/ubuntu12_64/steamwebhelper" ]; then
        echo "[*] Steam client already bootstrapped — skipping Xvfb bootstrap"
        return 0
    fi

    # Ensure ~/.steam/root is a symlink to the install (relocate Proton-GE if the
    # Dockerfile left root as a real directory).
    mkdir -p "${steam_install}/compatibilitytools.d" 2>/dev/null
    if [ -e "${USER_HOME}/.steam/root" ] && [ ! -L "${USER_HOME}/.steam/root" ]; then
        for d in "${USER_HOME}/.steam/root/compatibilitytools.d"/*; do
            [ -d "$d" ] && mv "$d" "${steam_install}/compatibilitytools.d/" 2>/dev/null
        done
        rm -rf "${USER_HOME}/.steam/root"
        ln -s "${steam_install}" "${USER_HOME}/.steam/root"
    fi
    # chown ALL of ~dpad (not just .steam) — a root boot process (D-Bus /
    # install-display-drivers) can create ~/.local root-owned, which makes
    # Steam's `mkdir ~/.local/share/icons` EPERM and abort the bootstrap.
    # Mirrors the DFP path's chown. Targeted: only chown files NOT already owned
    # by dpad:dpad. A blanket `chown -R` walks all ~33k files in ~dpad (the
    # pre-baked Steam client) and, on overlayfs without metacopy, copy-up's every
    # file (~4GB, ~120s) even when the owner is already correct. Only a handful of
    # root-owned files (from D-Bus / install-display-drivers) actually need fixing.
    find "${USER_HOME}" ! \( -user "${USER_NAME}" -group "${USER_NAME}" \) -exec chown "${USER_NAME}:${USER_NAME}" {} + 2>/dev/null || true

    echo "[*] Bootstrapping the official Steam desktop client on Xvfb — downloads ~300MB once..."
    as_user "Xvfb :8 -screen 0 1280x720x24 +extension GLX +extension RANDR >/tmp/xvfb-bootstrap.log 2>&1 &" 2>/dev/null
    sleep 2
    # Use the /usr/bin/steam wrapper (Debian steam-installer) — on a fresh
    # container, ~/.steam/debian-installation/
    # steam.sh doesn't exist yet; the wrapper extracts bootstraplinux_ubuntu12_32
    # tar.xz into ~/.steam/debian-installation/ on first run, then execs steam.sh.
    local steam_cmd="/usr/bin/steam"
    [ -x "$steam_cmd" ] || steam_cmd="${steam_install}/steam.sh"
    if [ ! -x "$steam_cmd" ]; then
        echo "[*] WARNING: no Steam launcher found (/usr/bin/steam nor ${steam_install}/steam.sh) — bootstrap aborted"
        pkill -9 -u "${USER_NAME}" -x Xvfb 2>/dev/null
        return 1
    fi
    local tries=0 ok=0
    while [ $tries -lt 3 ] && [ $ok -eq 0 ]; do
        tries=$((tries+1))
        rm -f "${USER_HOME}/.steam/steam.pid" "${steam_install}/steam.pid" "${USER_HOME}/.steam/steam.pipe" 2>/dev/null
        as_user "cd ${USER_HOME}; export DISPLAY=:8 HOME=${USER_HOME} USER=${USER_NAME} XDG_RUNTIME_DIR=${XDG_RUNTIME_DIR} PULSE_SERVER=${PULSE_SERVER} DBUS_SESSION_BUS_ADDRESS='${DBUS_SESSION_BUS_ADDRESS}'; exec ${steam_cmd}" >/tmp/steam-bootstrap.log 2>&1 &
        local sp=$! waited=0
        while [ $waited -lt 360 ]; do
            [ -x "${steam_install}/ubuntu12_64/steamwebhelper" ] && { ok=1; break; }
            kill -0 "$sp" 2>/dev/null || break
            sleep 3; waited=$((waited+3))
        done
        kill "$sp" 2>/dev/null
        pkill -9 -u "${USER_NAME}" -x steam 2>/dev/null
        pkill -9 -u "${USER_NAME}" -x steamwebhelper 2>/dev/null
        rm -f "${USER_HOME}/.steam/steam.pid" "${steam_install}/steam.pid" "${USER_HOME}/.steam/steam.pipe" 2>/dev/null
        [ $ok -eq 0 ] && { echo "    bootstrap attempt $tries incomplete; retrying..."; sleep 3; }
    done
    pkill -9 -u "${USER_NAME}" -x Xvfb 2>/dev/null
    if [ $ok -eq 1 ]; then
        echo "[*] Steam client bootstrapped OK"
    else
        echo "[*] WARNING: Steam bootstrap incomplete — the desktop client may update on first launch. See /tmp/steam-bootstrap.log"
        tail -20 /tmp/steam-bootstrap.log 2>/dev/null | sed 's/^/    /'
    fi
}

# --- NVENC multi-GPU topology + flexgrip auto-enable (nvidia-container-toolkit #1249) ---
# On driver >=570, NVENC's GET_ATTACHED_IDS returns ALL host GPUs; it then
# peer-inits with the ones whose /dev/nvidiaX aren't mounted and bails with
# NV_ENC_ERR_UNSUPPORTED_DEVICE (error code 2) — so a per-GPU session
# container pinned to a non-zero GPU minor can't open an NVENC encode session
# (reproduced: dpad-1 on /dev/nvidia1 failed every fresh boot; the Selkies
# nvh264enc plugin failed to register / build_video_pipeline raised and Selkies
# exited -> 502). The flexgrip libnvenc_fix.so LD_PRELOAD interposer filters
# that list to only mounted GPUs (scripts/nvenc_fix.c — matches the RM gpuId
# to the full PCI domain:bus:slot, since single-bus multi-GPU hosts share bus 0
# and differ only by slot). Auto-enabled when the container has a SLICE of a
# multi-GPU host (host GPU count > mounted /dev/nvidiaX count) on driver
# 570..609; override with DPAD_NVENC_FIX=1|0|auto. Sets NVENC_FIX_ENABLED +
# exports NVENC_FIX_AVAILABLE/DEBUG. The caller derives DPAD_PRELOAD and
# assembles LD_PRELOAD for Selkies, Sway and all store applications.
setup_nvenc_fix() {
    echo "    --- NVENC topology (#1249 check) ---"
    DRIVER_MAJOR="$(nvidia-smi --query-gpu=driver_version --format=csv,noheader 2>/dev/null | head -1 | cut -d. -f1)"
    HOST_GPU_COUNT="$(find /proc/driver/nvidia/gpus -mindepth 1 -maxdepth 1 -type d 2>/dev/null | wc -l)"
    MOUNTED_GPU_COUNT="$(ls /dev/nvidia[0-9] 2>/dev/null | wc -l)"
    VISIBLE_GPU_COUNT="$(nvidia-smi -L 2>/dev/null | grep -c '^GPU ')"
    VISIBLE_BITMASK=0
    while IFS= read -r busid; do
        [ -z "$busid" ] && continue
        key="${busid#*:}"
        key="${key,,}"   # nvidia-smi emits UPPERCASE hex (0B), /proc is lowercase (0b) — case-insensitive compare (slots with hex letters like 0B/0D fail otherwise)
        for d in /proc/driver/nvidia/gpus/*; do
            [ -d "$d" ] || continue
            pkey="$(basename "$d")"; pkey="${pkey#*:}"; pkey="${pkey,,}"
            if [ "$pkey" = "$key" ]; then
                minor="$(grep -oP 'Device Minor:\s*\K[0-9]+' "$d/information" 2>/dev/null)"
                [ -n "$minor" ] && VISIBLE_BITMASK=$(( VISIBLE_BITMASK | (1 << minor) ))
                break
            fi
        done
    done < <(nvidia-smi --query-gpu=pci.bus_id --format=csv,noheader 2>/dev/null)
    if [ "$VISIBLE_BITMASK" = "0" ]; then
        while IFS= read -r idx; do
            [ -z "$idx" ] && continue
            VISIBLE_BITMASK=$(( VISIBLE_BITMASK | (1 << idx) ))
        done < <(nvidia-smi --query-gpu=index --format=csv,noheader 2>/dev/null)
    fi
    if [ "$VISIBLE_BITMASK" = "0" ]; then
        echo "    WARNING: visible-GPU mask is 0 (pci.bus_id='$(nvidia-smi --query-gpu=pci.bus_id --format=csv,noheader 2>/dev/null | tr '\n' ' ')'); flexgrip won't filter"
    fi
    echo "    driver_major: ${DRIVER_MAJOR:-?}  host(/proc): ${HOST_GPU_COUNT}  mounted: ${MOUNTED_GPU_COUNT}  visible(nvidia-smi): ${VISIBLE_GPU_COUNT} (mask $(printf '0x%x' ${VISIBLE_BITMASK}))"
    find /proc/driver/nvidia/gpus -mindepth 1 -maxdepth 1 -type d -printf '      /proc GPU: %f\n' 2>/dev/null | head -8
    ls /dev/nvidia[0-9] 2>/dev/null | sed 's/^/      mounted: /'
    NVENC_FIX_ENABLED=0
    case "${DPAD_NVENC_FIX:-auto}" in
        1) NVENC_FIX_ENABLED=1 ;;
        0) NVENC_FIX_ENABLED=0 ;;
        auto)
            if (( ${DRIVER_MAJOR:-0} >= 570 )) && (( ${DRIVER_MAJOR:-0} < 610 )); then
                if (( ${HOST_GPU_COUNT:-0} > ${MOUNTED_GPU_COUNT:-0} )) \
                   || (( ${VISIBLE_GPU_COUNT:-0} < ${MOUNTED_GPU_COUNT:-0} )); then
                    NVENC_FIX_ENABLED=1
                fi
            fi
            ;;
    esac
    if [ "$NVENC_FIX_ENABLED" = "1" ] && [ -f /opt/dpadcloud/libnvenc_fix.so ]; then
        export NVENC_FIX_DEBUG=${DPAD_NVENC_FIX_DEBUG:-0}
        export NVENC_FIX_AVAILABLE="$(printf '0x%x' "$VISIBLE_BITMASK")"
        echo "    DPAD_NVENC_FIX: ENABLED — filter GET_ATTACHED_IDS to visible GPUs (mask ${NVENC_FIX_AVAILABLE})"
    elif [ "$NVENC_FIX_ENABLED" = "1" ]; then
        echo "    DPAD_NVENC_FIX: requested but /opt/dpadcloud/libnvenc_fix.so missing — cannot enable"
        NVENC_FIX_ENABLED=0
    else
        echo "    DPAD_NVENC_FIX: disabled (all host GPUs accessible or driver<570/>=610 — NVENC native)"
    fi
}

# -----------------------------------------------------------------------------
# Per-user persistent library volume (docs/cloud/docs/V2-PLAN.md §5).
#
# A v2 session bind-mounts the user's UpCloud block-storage volume (mounted on
# the VM host at /mnt/dpad-vol/<volId>, labelled dpadvol-<uuid8>) into the
# container at DPAD_VOLUME_MOUNT (default /mnt/dpad-library). The whole Steam
# INSTALL ROOT (~/.steam/debian-installation) is symlinked to <vol>/steam-install
# so the Steam client + library (games, config, saves, Proton) all live ON THE
# VOLUME. This is required because Steam FORCES its library "0" = the install
# root + reports Settings->Storage free space as statvfs() of that path's
# filesystem — with the install root on the rootfs it shows the uncapped rootfs
# (~647 GB), not the volume. Putting the install root on the volume makes the
# display, the free-space check, AND the install target all reference the volume
# (exact). The client (~2.1 GB) is baked into the image + copied to the volume
# ONCE (first launch); fast-boot is preserved (client present on the attached
# volume). A game downloads ONCE and persists across sessions. The volume is
# region-locked (UpCloud storages attach only within their zone); changing
# regions is a rare paid migration. A tier switch within the region reuses the
# same volume.
#
# Idempotent + safe with no volume (DPAD_VOLUME_MOUNT unset → no-op, back-compat
# for the ephemeral/Vast-era runs). On the FIRST launch the volume is empty;
# Steam starts fresh, logs in, installs games to the volume. Every launch after,
# the volume holds the library + login → Steam sees them. If the image shipped
# any content under those subpaths (it doesn't — only the client binary), it's
# migrated into the volume once before symlinking.
setup_user_volume() {
    local vol="${DPAD_VOLUME_MOUNT:-}"
    [ -z "$vol" ] && return 0
    if [ ! -d "$vol" ]; then
        echo "[*] WARNING: DPAD_VOLUME_MOUNT=$vol is not a directory — running with NO persistent library (ephemeral)."
        return 0
    fi
    echo "[*] User library volume: $vol (persistent Steam install + library on the volume)"
    # The volume is a fresh ext4 (root-owned on the host). The container runs
    # Steam as dpad (uid 1001) — make the volume writable by dpad. This chown
    # runs as root (entrypoint, before dropping to dpad) + propagates to the
    # host mount (bind mount shares ownership).
    chown -R "${USER_NAME}:${USER_NAME}" "$vol" 2>/dev/null || true

    local si="${USER_HOME}/.steam/debian-installation"
    local target="$vol/steam-install"

    # The Steam CLIENT must live ON THE VOLUME so Steam's library "0" (the
    # install root) is on the volume's filesystem. Steam FORCES library "0" =
    # the install root (it overwrites any pre-seeded "0"=volume within minutes
    # — observed live), and Settings->Storage reports statvfs() of the library
    # "0" path's filesystem. With the install root on the rootfs it shows the
    # uncapped rootfs (~647 GB), not the volume. Moving the install root onto
    # the volume makes the display, the free-space check, AND the install target
    # all reference the volume (exact). The client (~2.1 GB) is baked into the
    # image; copy it to the volume ONCE (first launch on this volume); every
    # later launch reuses the volume's copy. The "fast boot" (no 3-4 min
    # first-run Steam download) is preserved — the client is present on the
    # attached volume. Steam auto-updates the volume's copy going forward.

    # Old-layout migration: earlier builds symlinked the subpaths (steamapps/
    # config/userdata/compatibilitytools.d) at the volume TOP level. Move them
    # into steam-install/ so existing libraries aren't lost, before seeding.
    if [ ! -d "$target" ]; then
        if [ -d "$vol/steamapps" ] || [ -d "$vol/config" ]; then
            echo "    migrating old top-level library layout -> $target/ (one-time)"
            mkdir -p "$target"
            for sub in steamapps config userdata compatibilitytools.d; do
                [ -e "$vol/$sub" ] && mv "$vol/$sub" "$target/" 2>/dev/null || true
            done
        fi
    fi

    # Seed the client into the volume if not already there (first launch).
    if [ ! -x "$target/ubuntu12_64/steamwebhelper" ]; then
        if [ -d "$si" ] && [ ! -L "$si" ] && [ -x "$si/ubuntu12_64/steamwebhelper" ]; then
            echo "    first launch on this volume — copying Steam client (~2.1 GB) to the volume (one-time)"
            mkdir -p "$target"
            cp -a "$si/." "$target/" 2>/dev/null || true
            chown -R "${USER_NAME}:${USER_NAME}" "$target" 2>/dev/null || true
        else
            echo "    WARNING: no baked Steam client to seed + volume has none — Steam will re-download on first boot (slow)"
        fi
    fi

    # Replace the install root with a symlink to the volume's steam-install.
    # statvfs() follows the symlink -> the volume's filesystem -> Storage shows
    # the volume's size. Steam's forced library "0" = install root now resolves
    # to the volume. (Idempotent: re-launch re-uses the existing link.)
    if [ -L "$si" ]; then
        if [ "$(readlink -f "$si" 2>/dev/null)" != "$(readlink -f "$target" 2>/dev/null)" ]; then
            rm -f "$si"; ln -s "$target" "$si"
        fi
    else
        rm -rf "$si"
        ln -s "$target" "$si"
    fi
    chown -h "${USER_NAME}:${USER_NAME}" "$si" 2>/dev/null || true
    echo "    Steam install root -> $target (on the volume; Storage shows the volume)"
}

setup_stores() {
    # Per-store state (Wine prefixes for Battle.net/EA/Ubisoft; legendary/gogdl
    # tokens for Epic/GOG) lives on the persistent volume under <vol>/games/<store>
    # (STORES-PLAN §9), symlinked into ~/Games so each store's wrapper finds a
    # fixed path (~/Games/battlenet, ~/Games/ea-app, ...). Ephemeral sessions
    # (no volume) use ~/Games on the (capped, 200 GB) rootfs — the prefix won't
    # persist, so the user re-installs + re-logs-in each session (the
    # multi-store-picker value prop for ephemeral users).
    #
    # Gated on DPAD_STORES (comma list from the worker's /etc/environment)
    # containing a store that uses ~/Games — v1: battlenet, epic, gog. (Steam
    # uses the install-root-on-volume path in setup_user_volume, not ~/Games.)
    # Epic + GOG also need ~/.config/heroic persisted (Heroic's config holds
    # the legendary/gogdl login tokens + the library DB so the user is auto-
    # logged-in on relaunch).
    local vol="${DPAD_VOLUME_MOUNT:-}"
    local stores="${DPAD_STORES:-}"
    [ -z "$stores" ] && return 0
    local need_games=0 need_heroic=0
    case ",${stores}," in
        *,battlenet,*) need_games=1 ;;
        *,epic,*) need_games=1; need_heroic=1 ;;
        *,gog,*) need_games=1; need_heroic=1 ;;
    esac
    [ "$need_games" = "0" ] && return 0
    local games_link="${USER_HOME}/Games"
    if [ -n "$vol" ] && [ -d "$vol" ]; then
        local vol_games="$vol/games"
        mkdir -p "$vol_games" 2>/dev/null || true
        chown -R "${USER_NAME}:${USER_NAME}" "$vol_games" 2>/dev/null || true
        # Symlink ~/Games -> <vol>/games (idempotent). Non-destructive: only
        # create/replace the link when ~/Games is absent or already a symlink;
        # a pre-existing real ~/Games (rare on a fresh volume) is left in place
        # so existing data isn't moved/lost — the wrapper uses it as-is.
        if [ ! -e "$games_link" ]; then
            ln -s "$vol_games" "$games_link"
        elif [ -L "$games_link" ] && [ "$(readlink -f "$games_link" 2>/dev/null)" != "$(readlink -f "$vol_games" 2>/dev/null)" ]; then
            rm -f "$games_link"; ln -s "$vol_games" "$games_link"
        fi
        chown -h "${USER_NAME}:${USER_NAME}" "$games_link" 2>/dev/null || true
        echo "    ~/Games -> $vol_games (store state persists on the volume)"

        # Heroic config (Epic + GOG login tokens, library DB, game settings).
        # ~/.config/heroic -> <vol>/heroic-config so login persists across
        # End+relaunch — same pattern as the Steam install-root symlink.
        if [ "$need_heroic" = "1" ]; then
            local heroic_link="${USER_HOME}/.config/heroic"
            local vol_heroic="$vol/heroic-config"
            mkdir -p "$vol_heroic" 2>/dev/null || true
            chown -R "${USER_NAME}:${USER_NAME}" "$vol_heroic" 2>/dev/null || true
            if [ ! -e "$heroic_link" ]; then
                ln -s "$vol_heroic" "$heroic_link"
            elif [ -L "$heroic_link" ] && [ "$(readlink -f "$heroic_link" 2>/dev/null)" != "$(readlink -f "$vol_heroic" 2>/dev/null)" ]; then
                rm -f "$heroic_link"; ln -s "$vol_heroic" "$heroic_link"
            fi
            chown -h "${USER_NAME}:${USER_NAME}" "$heroic_link" 2>/dev/null || true
            echo "    ~/.config/heroic -> $vol_heroic (Epic/GOG login persists on the volume)"
        fi
    else
        mkdir -p "$games_link" 2>/dev/null || true
        chown -R "${USER_NAME}:${USER_NAME}" "$games_link" 2>/dev/null || true
        echo "    ~/Games on the rootfs (ephemeral; store state will NOT persist)"
        if [ "$need_heroic" = "1" ]; then
            mkdir -p "${USER_HOME}/.config/heroic" 2>/dev/null || true
            chown -R "${USER_NAME}:${USER_NAME}" "${USER_HOME}/.config/heroic" 2>/dev/null || true
            echo "    ~/.config/heroic on the rootfs (ephemeral; Epic/GOG login will NOT persist)"
        fi
    fi
}

setup_gamepad_interposer() {
    # Sets up the gamepad interposer (classic or evdev) + the LD_PRELOAD assembly.
    # Sets the launcher desktop's preload and SDL controller environment and
    # starts either the classic hotplug watcher or evdev bridge.
    DPAD_PRELOAD=""
    [ "$NVENC_FIX_ENABLED" = "1" ] && DPAD_PRELOAD="/opt/dpadcloud/libnvenc_fix.so"
    SDL_GP_ENV=""
    if [ "${DPAD_GAMEPAD_INTERPOSER:-}" = "evdev" ]; then
        # === evdev gamepad path (DPAD_GAMEPAD_INTERPOSER=evdev, opt-in) ===
        # fake-libudev + the MAIN-branch evdev interposer (both arches via $LIB)
        # make SDL3 discover 4 virtual Microsoft X-Box 360 pads at
        # /dev/input/js{0-3} + event100{0-3} (no udev daemon, no CLASSIC hint, no
        # GUID hack — the pads report vendor 0x045e so SDL3 auto-maps them). The
        # evdev interposer reads struct input_event on event100N; evdev_bridge.py
        # translates Selkies' js_event -> input_event+SYN (scripts/evdev_bridge.py).
        # The default/classic path is the else branch.
        export SELKIES_INTERPOSER='/usr/$LIB/selkies_joystick_interposer_evdev.so'
        mkdir -pm1777 /dev/input 2>/dev/null
        # static dummy nodes (no hotplug watcher — fake-libudev advertises them;
        # the interposer intercepts open() by path). jsN minor=N; event100N minor=64+1000+N.
        for n in 0 1 2 3; do
            rm -f "/dev/input/js${n}" "/dev/input/event100${n}" 2>/dev/null
            mknod "/dev/input/js${n}"       c 13 "${n}"           2>/dev/null && chmod 666 "/dev/input/js${n}"       2>/dev/null
            mknod "/dev/input/event100${n}" c 13 "$((64+1000+n))"  2>/dev/null && chmod 666 "/dev/input/event100${n}" 2>/dev/null
        done
        # evdev_bridge.py: Selkies js socket -> input_event on event100N. Detached;
        # the health loop (below) restarts it if it dies.
        setsid python3 /opt/dpadcloud/evdev_bridge.py >>/tmp/evdev_bridge.log 2>&1 </dev/null &
        export LD_PRELOAD="${DPAD_PRELOAD}${DPAD_PRELOAD:+:}/usr/\$LIB/dpad_fake_libudev.so:/usr/\$LIB/selkies_joystick_interposer_evdev.so${LD_PRELOAD:+:${LD_PRELOAD}}"
        # NO SDL_JOYSTICK_LINUX_CLASSIC / SDL_JOYSTICK_DISABLE_UDEV / SDL_GAMECONTROLLERCONFIG
        # (the evdev path uses native SDL3 libudev discovery + auto-maps the XBox pad).
        echo "[*] Gamepad: EVDEV path (DPAD_GAMEPAD_INTERPOSER=evdev) — fake-libudev + evdev interposer + evdev_bridge.py"
    else
        # === classic joystick path (default) ===
        export SELKIES_INTERPOSER='/usr/$LIB/selkies_joystick_interposer.so'
        mkdir -pm1777 /dev/input 2>/dev/null
        rm -f /dev/input/js0 /dev/input/js1 /dev/input/js2 /dev/input/js3 2>/dev/null || true
        # Root gamepad-hotplug watcher: mknod /dev/input/jsN when Selkies' gamepad socket
        # appears, rm it when the socket goes (so a reconnect re-triggers IN_CREATE).
        ( while true; do
              for n in 0 1 2 3; do
                if [ -S "/tmp/selkies_js${n}.sock" ] && [ ! -e "/dev/input/js${n}" ]; then
                  mknod "/dev/input/js${n}" c 13 "${n}" 2>/dev/null && chmod 666 "/dev/input/js${n}" 2>/dev/null
                elif [ ! -S "/tmp/selkies_js${n}.sock" ] && [ -e "/dev/input/js${n}" ]; then
                  rm -f "/dev/input/js${n}" 2>/dev/null
                fi
              done
              sleep 0.3
          done ) &
        # as_user (su) strips the parent env, so LD_PRELOAD/SDL_JOYSTICK_* must be
        # re-exported explicitly inside the nested Sway desktop.
        export LD_PRELOAD="${DPAD_PRELOAD}${DPAD_PRELOAD:+:}${SELKIES_INTERPOSER}${LD_PRELOAD:+:${LD_PRELOAD}}"
        # SDL_GameController mapping for the Selkies virtual gamepad. The v1.6.2
        # interposer presents a raw joystick named "Selkies Controller" with NO
        # vendor/product ID (its js_config_t has no vendor/product fields + it
        # doesn't intercept JSIOCGID), so SDL3 can't auto-map it as a gamepad —
        # Steam and the launcher use SDL_GameController, so this mapping is required. SDL3's GUID for a zero-vendor classic js device is
        # bus(0)+crc16(name)+name-bytes (SDL_CreateJoystickGUID, vendor=0 branch):
        # crc16("Selkies Controller")=0x06d6 -> GUID 0000d60653656c6b69657320436f6e00.
        # This mapping tells SDL3 how the xpad-layout joystick indices map to a
        # standard gamepad (matches STANDARD_XPAD_CONFIG in selkies gamepad.py:
        # btn 0-10 = A/B/X/Y/TL/TR/SELECT/START/MODE/THUMBL/THUMBR, axes 0-7 =
        # X/Y/Z/RX/RY/RZ/HAT0X/HAT0Y; dpad arrives as axes 6/7, triggers as 2/5).
        export SDL_GAMECONTROLLERCONFIG='0000d60653656c6b69657320436f6e00,Selkies Controller,a:b0,b:b1,x:b2,y:b3,back:b6,guide:b8,start:b7,leftshoulder:b4,rightshoulder:b5,leftstick:b9,rightstick:b10,leftx:a0,lefty:a1,rightx:a3,righty:a4,lefttrigger:a2,righttrigger:a5,dpup:h0.1,dpdown:h0.4,dpleft:h0.8,dpright:h0.2,'
        SDL_GP_ENV="SDL_JOYSTICK_DEVICE=/dev/input/js0 SDL_JOYSTICK_LINUX_CLASSIC=1 SDL_JOYSTICK_DISABLE_UDEV=1 SDL_GAMECONTROLLERCONFIG='${SDL_GAMECONTROLLERCONFIG}'"
        echo "[*] Gamepad: classic joystick path (default)"
    fi
}

start_launcher_session() {
    echo "[*] Launcher-only desktop: gst-wayland-display + nested Sway + DpadPlay launcher"
    echo "[*] Steam is installed as a standard store application and opens from the DpadPlay launcher."

    # --- input hotfix overlay ---
    if [ "${DPAD_INPUT_HOTFIX:-0}" = "1" ]; then
        local _hb="https://raw.githubusercontent.com/ForcesPT/container-gaming/main/scripts"
        if curl -fsSL "${_hb}/dpad_input_patch.py" -o /usr/local/lib/python3.12/dist-packages/dpad_input_patch.py 2>/dev/null; then
            echo "    input hotfix: dpad_input_patch.py updated from repo main"
        fi
        if curl -fsSL "${_hb}/patch_gst_web_cursors.sh" -o /opt/dpadcloud/patch_gst_web_cursors.sh 2>/dev/null; then
            chmod +x /opt/dpadcloud/patch_gst_web_cursors.sh 2>/dev/null
            echo "    input hotfix: patch_gst_web_cursors.sh updated from repo main"
        fi
    fi
    bash /opt/dpadcloud/patch_gst_web_cursors.sh "${SELKIES_WEB_ROOT}/input.js" "${DPAD_DEFAULT_GAMING_MODE:-0}" 2>/dev/null || true

    # --- live-resolution overlay (§18.7) ---
    # The in-stream Resolution dropdown (web client) + the _arg_res data-channel
    # handler (selkies) are NOT baked in the image (the rebuild + Docker Hub push
    # is the blocked owner step). Fetch the idempotent patcher from repo main to
    # /opt/dpadcloud (bind-mountable hotfix path) + run it so a fresh `docker
    # run` / new VM bootstrap gets the live-resolution feature with NO image
    # rebuild. Best-effort (network failure falls back to the image's baked web
    # client + pip package — no dropdown, but the stream still works at the
    # DPAD_WD_* default). Only on the wayland-display path (the compositor caps
    # + sway output mode are what the dropdown drives).
    local _hb_res="https://raw.githubusercontent.com/ForcesPT/container-gaming/main/scripts"
    if curl -fsSL "${_hb_res}/patch_live_resolution.py" -o /opt/dpadcloud/patch_live_resolution.py 2>/dev/null; then
        chmod +x /opt/dpadcloud/patch_live_resolution.py 2>/dev/null || true
        python3 /opt/dpadcloud/patch_live_resolution.py >/tmp/patch_live_resolution.log 2>&1 || true
        echo "    live-resolution overlay applied (see /tmp/patch_live_resolution.log)"
    else
        echo "    live-resolution overlay: fetch failed — using the image's baked web client (no dropdown)"
    fi

    # --- fixed session shell ---
    local SHELL_APP="/opt/dpadcloud/launcher-shell"
    echo "[*] Session shell: DpadPlay launcher (Steam and all other stores open as applications)"

    # --- shared session prep ---
    setup_user_volume
    setup_stores
    bootstrap_steam_on_xvfb

    # PipeWire + wireplumber — the compositor doesn't need PipeWire for video, but
    # Selkies' pulsesrc needs it for audio (the null sink + dummy.monitor source).
    echo "[*] Starting PipeWire + wireplumber..."
    as_user "export XDG_RUNTIME_DIR=${XDG_RUNTIME_DIR} DBUS_SESSION_BUS_ADDRESS='${DBUS_SESSION_BUS_ADDRESS}' HOME=${USER_HOME}; pipewire >/tmp/pipewire.log 2>&1 & sleep 1; wireplumber >/tmp/wireplumber.log 2>&1 &"
    local pw_wait=0
    while [ $pw_wait -lt 15 ]; do
        as_user "export XDG_RUNTIME_DIR=${XDG_RUNTIME_DIR}; pw-cli info 0 >/dev/null 2>&1" && break
        sleep 1; pw_wait=$((pw_wait+1))
    done
    if as_user "export XDG_RUNTIME_DIR=${XDG_RUNTIME_DIR}; pw-cli info 0 >/dev/null 2>&1"; then
        echo "    PipeWire ready"
    else
        echo "    WARNING: PipeWire not ready after 15s — see /tmp/pipewire.log (Selkies audio may fail)"
    fi

    # pipewire-pulse + null sink (Selkies pulsesrc capture source)
    echo "[*] Starting pipewire-pulse (PulseAudio compat) + null audio sink..."
    mkdir -p "${XDG_RUNTIME_DIR}/pulse" 2>/dev/null; chmod 1777 "${XDG_RUNTIME_DIR}/pulse" 2>/dev/null
    as_user "export XDG_RUNTIME_DIR=${XDG_RUNTIME_DIR} DBUS_SESSION_BUS_ADDRESS='${DBUS_SESSION_BUS_ADDRESS}' HOME=${USER_HOME}; pipewire-pulse >/tmp/pipewire-pulse.log 2>&1 &"
    local pp_wait=0
    while [ $pp_wait -lt 15 ]; do [ -S "${XDG_RUNTIME_DIR}/pulse/native" ] && break; sleep 1; pp_wait=$((pp_wait+1)); done
    if [ -S "${XDG_RUNTIME_DIR}/pulse/native" ]; then
        echo "    pipewire-pulse ready (socket ${XDG_RUNTIME_DIR}/pulse/native)"
        as_user "export PULSE_SERVER=unix:${XDG_RUNTIME_DIR}/pulse/native XDG_RUNTIME_DIR=${XDG_RUNTIME_DIR}; pactl load-module module-null-sink sink_name=dummy sink_properties=device.description=DummyOutput 2>/dev/null; pactl set-default-sink dummy 2>/dev/null; pactl set-default-source dummy.monitor 2>/dev/null" >/dev/null 2>&1 || true
    else
        echo "    WARNING: pipewire-pulse socket not up after 15s — Selkies audio will fail (see /tmp/pipewire-pulse.log)"
        tail -8 /tmp/pipewire-pulse.log 2>/dev/null | sed 's/^/      /'
    fi

    find "${USER_HOME}" ! \( -user "${USER_NAME}" -group "${USER_NAME}" \) -exec chown "${USER_NAME}:${USER_NAME}" {} + 2>/dev/null || true
    setup_nvenc_fix
    setup_gamepad_interposer

    # Sway's XWayland requires the standard root-owned X11 socket directory.
    rm -rf /tmp/.X11-unix; mkdir -p /tmp/.X11-unix; chown root:root /tmp/.X11-unix; chmod 1777 /tmp/.X11-unix
    # Dummy Xvfb :99 exists only for pynput import before Sway creates XWayland.
    # The input patch switches to Sway's :0 display when it becomes available.
    as_user "Xvfb :99 -ac -screen 0 1x1x24 >/tmp/xvfb99.log 2>&1 &" 2>/dev/null
    sleep 1

    # --- coturn + rtc_config ---
    rm -f /tmp/selkies.log /tmp/coturn.log /tmp/rtc_config.json 2>/dev/null
    if ! pgrep -x turnserver >/dev/null; then
        echo "[*] Starting coturn on ${TURN_PORT_EXT}..."
        turnserver -n -a --lt-cred-mech --fingerprint --no-stun --no-multicast-peers --no-cli --listening-ip=0.0.0.0 --realm=dpadcloud --user="${TURN_USER}:${TURN_PASS}" -p "${TURN_PORT_LISTEN:-${TURN_PORT_EXT}}" -X "${PUBLIC_IP:-localhost}" >/tmp/coturn.log 2>&1 &
        sleep 2
        pgrep -x turnserver >/dev/null && echo "    coturn running" || echo "    WARNING: coturn failed (see /tmp/coturn.log)"
    fi
    [ -S "${XDG_RUNTIME_DIR}/pulse/native" ] && echo "    audio socket OK (${XDG_RUNTIME_DIR}/pulse/native)" || echo "    WARNING: pipewire-pulse socket missing — Selkies audio will fail"
    local rtc=/tmp/rtc_config.json _listen="${TURN_PORT_LISTEN:-${TURN_PORT_EXT}}"
    local TCP_EXT="${DPAD_TURN_EXTERNAL_PORT:-$(printenv VAST_TCP_PORT_${_listen} 2>/dev/null || true)}"
    local UDP_EXT="${DPAD_TURN_UDP_EXTERNAL_PORT:-$(printenv VAST_UDP_PORT_${_listen} 2>/dev/null || true)}"
    local _ices=""
    [ -n "$UDP_EXT" ] && { [ -n "$_ices" ] && _ices+=","; _ices+="{\"urls\":[\"turn:127.0.0.1:${_listen}?transport=udp\"],\"username\":\"${TURN_USER}\",\"credential\":\"${TURN_PASS}\"},{\"urls\":[\"turn:${PUBLIC_IP}:${UDP_EXT}?transport=udp\"],\"username\":\"${TURN_USER}\",\"credential\":\"${TURN_PASS}\"}"; }
    [ -n "$TCP_EXT" ] && { [ -n "$_ices" ] && _ices+=","; _ices+="{\"urls\":[\"turn:127.0.0.1:${_listen}?transport=tcp\"],\"username\":\"${TURN_USER}\",\"credential\":\"${TURN_PASS}\"},{\"urls\":[\"turn:${PUBLIC_IP}:${TCP_EXT}?transport=tcp\"],\"username\":\"${TURN_USER}\",\"credential\":\"${TURN_PASS}\"}"; }
    printf '%s' "{\"iceServers\":[${_ices}],\"iceTransportPolicy\":\"all\"}" > "$rtc"; chmod 644 "$rtc"
    [ -z "$_ices" ] && echo "    WARNING: no TURN port exposed — WebRTC media will fail"

    # --- selkies FIRST (is the compositor via waylanddisplaysrc) ---
    # DPAD_VIDEO_SRC=waylanddisplaysrc gates the patch_selkies_waylanddisplay.py
    # branch in selkies' build_video_pipeline. The compositor does NOT start until a
    # WebRTC peer connects (on_session → start_pipeline → waylanddisplaysrc starts
    # → creates wayland-N in $XDG_RUNTIME_DIR). So: launch selkies, fire DPAD_READY
    # (listening), then the health loop polls for the socket and launches Sway.
    local enc="${DPAD_ENCODER:-nvh264enc}"
    local video_src="waylanddisplaysrc"
    # Live-resolution helpers (§18.7): /tmp/dpad_resolution is written by the
    # selkies _arg_res data-channel handler (the web dropdown). Both the
    # compositor caps (DPAD_STREAM_WIDTH/HEIGHT) + the sway `output * mode`
    # read it, so a live change → handler kills selkies → this health loop
    # relaunches selkies (new caps) + sway (new output mode) at the new res.
    # Defaults to DPAD_WD_WIDTH/HEIGHT (the launch env / 1080p).
    _dpad_res() { [ -f /tmp/dpad_resolution ] && cat /tmp/dpad_resolution || echo "${DPAD_WD_WIDTH:-1920}x${DPAD_WD_HEIGHT:-1080}"; }
    _dpad_w() { _dpad_res | cut -dx -f1; }
    _dpad_h() { _dpad_res | cut -dx -f2; }
    # Build the selkies-gstreamer launch command. A function (not a captured
    # string) so each (re)launch re-reads /tmp/dpad_resolution — the health
    # loop's restart-on-death path picks up a live resolution change.
    build_selkies_cmd() {
      echo "export DISPLAY=:99 DPAD_VIDEO_SRC=${video_src} DPAD_INPUT_DISPLAY=:0 DPAD_STREAM_WIDTH=$(_dpad_w) DPAD_STREAM_HEIGHT=$(_dpad_h) XDG_RUNTIME_DIR=${XDG_RUNTIME_DIR} PULSE_SERVER=${PULSE_SERVER} PIPEWIRE_LATENCY=10ms GST_DEBUG=1 LD_PRELOAD='${LD_PRELOAD:-${SELKIES_INTERPOSER}}' SDL_JOYSTICK_DEVICE=/dev/input/js0 SELKIES_INTERPOSER='${SELKIES_INTERPOSER}' DPAD_GAMEPAD_INTERPOSER=${DPAD_GAMEPAD_INTERPOSER:-}; . /opt/gstreamer/gst-env; selkies-gstreamer --addr=${DPAD_SELKIES_BIND:-127.0.0.1} --port=16100 --enable_https=false --encoder=${enc} --enable_basic_auth=true --basic_auth_user='${SELKIES_USER}' --basic_auth_password='${SELKIES_PASS}' --enable_resize=false --enable_cursors=true --rtc_config_json='${rtc}' --audio_packetloss_percent=${DPAD_AUDIO_PACKETLOSS:-0} --video_packetloss_percent=${DPAD_VIDEO_PACKETLOSS:-0} --js_socket_path=/tmp --web_root=${SELKIES_WEB_ROOT}"
    }
    echo "[*] Launching selkies (wayland-display compositor; video_src=${video_src}, encoder=${enc})..."
    as_user "$(build_selkies_cmd)" >>/tmp/selkies.log 2>&1 &
    sleep 6
    if ! pgrep -f selkies-gstreamer >/dev/null; then
        echo "    WARNING: selkies failed to start (see /tmp/selkies.log)"; tail -20 /tmp/selkies.log 2>/dev/null | sed 's/^/      /'
        return 1
    fi
    echo "    Selkies listening on ${DPAD_SELKIES_BIND:-127.0.0.1}:16100 (wayland-display compositor; encoder=${enc}, audio_fec=${DPAD_AUDIO_PACKETLOSS:-0}%, video_fec=${DPAD_VIDEO_PACKETLOSS:-0}%)"
    echo "DPAD_READY slot=${DPAD_SLOT:-0} bind=${DPAD_SELKIES_BIND:-127.0.0.1}:16100 encoder=${enc}"
    echo "    NOTE: video appears after a peer connects and the Sway launcher desktop starts"

    # Nested Sway is the only desktop client. It provides XWayland for the
    # official Steam desktop client and Windows store launchers while remaining a
    # render-node client of gst-wayland-display (no DRM master).
    _launch_sway() {
        local wl_name="$1"
        local egl_unset="unset DISPLAY __EGL_VENDOR_LIBRARY_FILENAMES"
        local egl_set="__EGL_VENDOR_LIBRARY_FILENAMES=/usr/share/glvnd/egl_vendor.d/10_nvidia.json"
        local shared_env="WAYLAND_DISPLAY=${wl_name} XDG_RUNTIME_DIR=${XDG_RUNTIME_DIR} PULSE_SERVER=${PULSE_SERVER} DBUS_SESSION_BUS_ADDRESS='${DBUS_SESSION_BUS_ADDRESS}' HOME=${USER_HOME} USER=${USER_NAME} VK_ICD_FILENAMES=/etc/vulkan/icd.d/nvidia_icd.json LD_PRELOAD='${LD_PRELOAD}' ${SDL_GP_ENV} SELKIES_INTERPOSER='${SELKIES_INTERPOSER}'"
        cat > /tmp/dpad-sway.config <<SWAYCFG
# DpadPlay nested Sway desktop
output * mode --custom $(_dpad_w)x$(_dpad_h)
default_border none
default_floating_border none
for_window [app_id=".*"] fullscreen enable
for_window [class=".*"] fullscreen enable
bindsym Mod4+l exec /opt/dpadcloud/launcher-toggle
bindsym Mod4+q kill
bindsym Mod4+k kill
exec ${SHELL_APP}
SWAYCFG
        as_user "cd ${USER_HOME}; ${egl_unset}; export ${shared_env} ${egl_set} WLR_BACKENDS=wayland XDG_CURRENT_DESKTOP=sway WLR_LIBINPUT_NO_DEVICES=1; exec sway --unsupported-gpu -c /tmp/dpad-sway.config -d" >>/tmp/sway-client.log 2>&1 &
    }

    # --- health loop: peer starts compositor -> launch the Sway desktop ---
    local sway_pid="" sway_launched=0
    while true; do
        sleep 5
        local wl_sock="" wl_name=""
        for f in "${XDG_RUNTIME_DIR}"/wayland-*; do
            [ -S "$f" ] || continue
            wl_sock="$f"; wl_name="$(basename "$f")"; break
        done
        if [ -n "$wl_name" ] && [ $sway_launched -eq 0 ]; then
            echo "[*] Compositor socket ${wl_name} appeared — launching Sway + DpadPlay launcher"
            _launch_sway "$wl_name"
            sway_pid=$!
            sway_launched=1
        fi
        if [ $sway_launched -eq 1 ] && [ -n "$sway_pid" ] && ! kill -0 "$sway_pid" 2>/dev/null; then
            echo "[*] WARNING: Sway desktop died — restarting..."
            pkill -9 -x sway 2>/dev/null || true
            if [ -n "$wl_name" ] && [ -S "$wl_sock" ]; then
                _launch_sway "$wl_name"
                sway_pid=$!
            else
                sway_launched=0
            fi
        fi
        if ! pgrep -f selkies-gstreamer >/dev/null; then
            echo "[*] WARNING: selkies-gstreamer died — restarting compositor and desktop..."
            pkill -f selkies-gstreamer 2>/dev/null || true
            pkill -9 -x sway 2>/dev/null || true
            sleep 2
            as_user "$(build_selkies_cmd)" >>/tmp/selkies.log 2>&1 &
            sway_launched=0
        fi
        if [ "${DPAD_GAMEPAD_INTERPOSER:-}" = "evdev" ] && ! pgrep -f evdev_bridge.py >/dev/null; then
            echo "[*] WARNING: evdev_bridge.py died — restarting..."
            setsid python3 /opt/dpadcloud/evdev_bridge.py >>/tmp/evdev_bridge.log 2>&1 </dev/null &
        fi
    done
}

# --- Raise thread/file limits}

# --- Raise thread/file limits (best-effort) ---
# Some Vast hosts default to low RLIMIT_NPROC/NOFILE, which makes Sunshine, mws,
# and XFCE fail to spawn threads ("Resource temporarily unavailable" / EAGAIN ->
# Sunshine Aborted at startup, mws panic, XFCE GLib-ERROR). Raise them as high as
# the hard cap allows. The diagnostic below prints the cgroup pids limit too — if
# that's a low number (not "max"), it's the binding constraint and ulimit can't
# help (the host needs a higher pids.max or a different instance).
ulimit -Hu 1048576 2>/dev/null || true
ulimit -u  1048576 2>/dev/null || true
ulimit -Hn 1048576 2>/dev/null || true
ulimit -n  1048576 2>/dev/null || true
echo "[*] Resource limits: nproc=$(ulimit -u 2>/dev/null) nofile=$(ulimit -n 2>/dev/null)  cgroup_pids.max=$( (cat /sys/fs/cgroup/pids.max 2>/dev/null || grep -h '' /sys/fs/cgroup/*/pids.max 2>/dev/null | head -1) || echo '?')"

# --- NVIDIA check (non-fatal) ---
echo "[*] Checking NVIDIA GPU..."
if command -v nvidia-smi >/dev/null 2>&1; then
    nvidia-smi --query-gpu=name,driver_version,memory.total --format=csv || echo "WARNING: nvidia-smi query failed"
else
    echo "WARNING: nvidia-smi not found. GPU may not be accessible."
fi

# --- NVIDIA display-driver userspace libs (ported from vast-ai/base-image) ---
# Some Vast hosts install only the *compute* driver, so libGL/libEGL/libvulkan
# are missing and VirtualGL/Selkies can't render to the GPU. Download+extract
# the matched .run graphics libs (idempotent; ~300MB first run, cached after).
# This does NOT touch libnvidia-encode (NVENC) — that's toolkit-injected; the
# multi-GPU NVENC peer-init bug (#1249) is handled by the flexgrip block below.
echo "[*] Ensuring NVIDIA display-driver userspace libs (libGL/EGL/Vulkan)..."
if [ -x /opt/dpadcloud/install-display-drivers ]; then
    /opt/dpadcloud/install-display-drivers 2>&1 | sed 's/^/    /' || echo "    (display-driver install skipped/failed, continuing)"
else
    echo "    install-display-drivers not present — skipping (graphics libs rely on toolkit injection)"
fi

# --- Vulkan ICD: use libEGL_nvidia.so.0 in headless/no-X11 envs (driver 595+) ---
# NVIDIA's 595 driver (Vulkan 1.4) libGLX_nvidia.so.0 Vulkan ICD fails to init
# without an X display server — the loader reports "Could not get 'vkCreateInstance'
# via 'vk_icdGetInstanceProcAddr'" and vkCreateInstance returns NULL (driver init
# failed). NVIDIA's own installed-components docs state libEGL_nvidia.so.0 should be
# used as the Vulkan ICD "in environments where X11 client libraries are not
# available" — and the launcher desktop --backend headless path has no X display server.
# The .run installer's nvidia_icd.json points at libGLX_nvidia.so.0; rewrite it to
# libEGL_nvidia.so.0 (idempotent; both libs export the full Vulkan ICD entry points).
if [ -f /etc/vulkan/icd.d/nvidia_icd.json ] && [ -x /usr/bin/sed ]; then
    if sed -i 's#"library_path"[[:space:]]*:[[:space:]]*"libGLX_nvidia.so.0"#"library_path" : "libEGL_nvidia.so.0"#' /etc/vulkan/icd.d/nvidia_icd.json 2>/dev/null; then
        echo "    Vulkan ICD: pinned to libEGL_nvidia.so.0 (headless/no-X11 fix for driver 595+)"
    fi
fi

# --- Render-node permissions for gst-wayland-display and nested Sway ---
# Provider images can expose renderD128 with a host GID that maps to an unrelated
# group name inside the container. Add dpad to the numeric owning group before
# the desktop session starts.
if [ -e /dev/dri ] && command -v stat >/dev/null 2>&1 && command -v usermod >/dev/null 2>&1; then
    RNODE=""
    for n in /dev/dri/renderD*; do [ -e "$n" ] && RNODE="$n" && break; done
    if [ -n "$RNODE" ]; then
        RGID="$(stat -c %g "$RNODE" 2>/dev/null || true)"
        if [ -n "$RGID" ] && ! id -G "$USER_NAME" 2>/dev/null | tr ' ' '\n' | grep -qx "$RGID"; then
            RGRP="$(getent group "$RGID" | cut -d: -f1)"
            if [ -n "$RGRP" ]; then
                usermod -aG "$RGRP" "$USER_NAME" 2>/dev/null \
                    && echo "[*] Render node $RNODE is group $RGRP (gid $RGID); added $USER_NAME to it" \
                    || echo "    WARNING: could not add $USER_NAME to group $RGRP (gid $RGID); launcher desktop may fail to open $RNODE"
            else
                # No /etc/group entry for that GID — create one and add the user.
                RGNAME="render-gid-${RGID}"
                groupadd -g "$RGID" "$RGNAME" 2>/dev/null || true
                usermod -aG "$RGNAME" "$USER_NAME" 2>/dev/null \
                    && echo "[*] Render node $RNODE is gid $RGID (no group entry); created $RGNAME + added $USER_NAME" \
                    || echo "    WARNING: could not add $USER_NAME to numeric gid $RGID; launcher desktop may fail to open $RNODE"
            fi
        fi
    fi
fi

# --- CUDA Configuration (ported from vastai/base-image 05-configure-cuda.sh) ---
# Clean stale cuda ldconfig entries, try forward-compat (datacenter GPUs),
# fall back to minor-version compat (12.1 <= host Max CUDA, guaranteed by filter).
# This prevents wrong-libcuda conflicts and may fix NVENC on datacenter GPUs.
configure_cuda() {
    command -v nvidia-smi >/dev/null 2>&1 || return 0

    # Clean ALL cuda ldconfig entries — we'll add back only what we need
    rm -f /etc/ld.so.conf.d/*cuda*.conf 2>/dev/null
    for conf in /etc/ld.so.conf.d/*.conf; do
        [[ -f "$conf" ]] || continue
        if grep -q "cuda" "$conf" 2>/dev/null; then
            sed -i '\#cuda#d' "$conf"
            [[ ! -s "$conf" ]] && rm -f "$conf"
        fi
    done
    sed -i '\#cuda#d' /etc/ld.so.conf 2>/dev/null
    ldconfig

    # Clean LD_LIBRARY_PATH of cuda entries
    if [ -n "${LD_LIBRARY_PATH:-}" ]; then
        export LD_LIBRARY_PATH=$(echo "$LD_LIBRARY_PATH" | tr ':' '\n' | grep -vE '/cuda(/|-)' | paste -sd ':')
    fi
    [ -z "${LD_LIBRARY_PATH:-}" ] && unset LD_LIBRARY_PATH

    local MAX_CUDA="$(nvidia-smi | grep -oP 'CUDA Version: \K[0-9]+\.[0-9]+' 2>/dev/null | head -1)"
    [ -z "$MAX_CUDA" ] && return 0

    # Resolve the real CUDA toolkit dir (e.g. /usr/local/cuda-12.1 or cuda-12.8)
    # so this works for both build variants (CUDA_VERSION ARG in the Dockerfile).
    local CUDA_REAL; CUDA_REAL="$(readlink -f /usr/local/cuda 2>/dev/null)"
    [ -z "$CUDA_REAL" ] && CUDA_REAL="/usr/local/cuda"
    local CUDA_VER_LABEL; CUDA_VER_LABEL="$(basename "$CUDA_REAL" | sed 's/^cuda-//')"

    # Try forward-compat (datacenter GPUs only; consumer GPUs will fail cuInit
    # test). Forward-compat is only useful when the IMAGE's CUDA is NEWER than
    # the host driver's max CUDA (it lets a newer userspace run on an older
    # driver). When image CUDA <= host max (the common case here: 12.5 <= 13.0)
    # SKIP the cuInit test entirely — it can HANG under NVIDIA MPS
    # (skb_wait_for_more_packet on the MPS control socket; observed live
    # 2026-07-30: the 2nd oversub session's boot stalled 7+ min here, exceeding
    # the launch deadline). Guard the test with a `timeout` too so a hung cuInit
    # can never wedge the boot (the fallback path uses the image's own CUDA libs,
    # which work when image CUDA <= host max).
    local COMPAT_DIR="${CUDA_REAL}/compat"
    if [ -d "$COMPAT_DIR" ] && compgen -G "$COMPAT_DIR/libcuda.so.*" >/dev/null 2>&1 \
       && dpkg --compare-versions "$CUDA_VER_LABEL" gt "$MAX_CUDA" 2>/dev/null; then
        if timeout 20 env LD_LIBRARY_PATH="$COMPAT_DIR" python3 -c "import ctypes,sys; sys.exit(0 if ctypes.CDLL('libcuda.so.1').cuInit(0)==0 else 1)" 2>/dev/null; then
            echo "$COMPAT_DIR" > /etc/ld.so.conf.d/0-compat-cuda.conf
            ldconfig
            echo "    CUDA forward compatibility enabled (datacenter GPU) — Max CUDA: ${MAX_CUDA}"
            return 0
        fi
    fi

    # Fall back: minor-version compat (CUDA <= host Max CUDA, guaranteed by our filter)
    echo "${CUDA_REAL}/lib64" > /etc/ld.so.conf.d/10-cuda.conf
    ln -sf "${CUDA_REAL}" /usr/local/cuda 2>/dev/null
    export CUDA_HOME=/usr/local/cuda
    [[ ":${PATH}:" != *":${CUDA_HOME}/bin:"* ]] && export PATH="${CUDA_HOME}/bin:${PATH}"
    ldconfig
    echo "    CUDA ${CUDA_VER_LABEL} selected (host Max CUDA: ${MAX_CUDA}, forward-compat: not available)"
}
echo "[*] Configuring CUDA..."
configure_cuda

# --- Runtime dirs ---
mkdir -p "${XDG_RUNTIME_DIR}" /tmp/.X11-unix /tmp/.ICE-unix
chmod 1777 "${XDG_RUNTIME_DIR}" /tmp/.X11-unix /tmp/.ICE-unix
find "${XDG_RUNTIME_DIR}" ! \( -user "${USER_NAME}" -group "${USER_NAME}" \) -exec chown "${USER_NAME}:${USER_NAME}" {} + 2>/dev/null || true

# The v2 control plane reaches Selkies directly through the VM's published
# port. The container does not run an SSH server or reverse signaling tunnel.

# --- D-Bus (system + session) ---
echo "[*] Starting D-Bus..."
mkdir -p /run/dbus "${XDG_RUNTIME_DIR}/dbus"
[ ! -e /var/run/dbus/system_bus_socket ] && dbus-daemon --system --fork 2>/dev/null || true
# Start a session bus for Sway, Steam, Electron store clients, and Wine launchers.
DBUS_SESSION_BUS_ADDRESS="$(as_user "export XDG_RUNTIME_DIR=${XDG_RUNTIME_DIR}; dbus-daemon --session --fork --print-address=1 2>/dev/null" | head -1)"
export DBUS_SESSION_BUS_ADDRESS
if [ -n "${DBUS_SESSION_BUS_ADDRESS}" ]; then
    echo "    D-Bus session: ${DBUS_SESSION_BUS_ADDRESS}"
else
    echo "    WARNING: D-Bus session bus address not captured — launcher/store applications may fail."
fi
sleep 1

# --- Start the only supported session architecture ---
start_launcher_session
exit 0
