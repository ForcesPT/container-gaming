#!/bin/bash
# =============================================================================
# DpadCloud Gaming Container Entrypoint (Ubuntu 24.04)
# Boot order:
#   dbus -> Xvfb -> XFCE -> PulseAudio(null-sink) -> coturn
#        -> NVENC topology + flexgrip LD_PRELOAD
#        -> Selkies-GStreamer (127.0.0.1:16100, TURN=coturn) [browser stream]
#        -> cloudflared (HTTPS tunnel for Selkies)
# =============================================================================

set -o pipefail

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
# still rides on cloudflared quick tunnels (outbound HTTPS -> zero inbound HTTP
# ports), exactly like Vast.
DPAD_PROVIDER="${DPAD_PROVIDER:-}"
if [ -z "$DPAD_PROVIDER" ] && [ -n "${RUNPOD_POD_ID:-}" ]; then
    DPAD_PROVIDER="runpod"
fi
TURN_PORT_LISTEN="${TURN_PORT_LISTEN:-${TURN_PORT_EXT}}"   # port coturn binds (internal)
if [ "$DPAD_PROVIDER" = "runpod" ]; then
    RUNPOD_COTURN_PORT="${DPAD_COTURN_PORT:-3478}"   # internal port coturn binds + the TCP port you expose (≤65535 for the RunPod UI)
    TURN_PORT_LISTEN="$RUNPOD_COTURN_PORT"
fi

# --- Display mode: DFP (connected virtual monitor) vs NULL (NoScanout) -------
# DFP gives CEF's browser composer a real connected monitor so the Steam UI
# window maps — needs DRM master (userns-capable host + --privileged + nothing
# else holding DRM master, e.g. Vast KVM VM `ubuntu_terminal` / RunPod Secure
# Cloud). NULL mode runs the nvidia DDX WITHOUT KMS (the Vast-Docker path: no
# userns, no DRM master) — desktop/Games render on the GPU but the Steam UI
# window can't be created (CEF "Could not find display info"), so on NULL hosts
# the product path is headless steamcmd + dpad-launch.
# auto = DFP if `unshare -U` works AND nvidia_drm.modeset=Y, else NULL.
DPAD_DISPLAY_MODE="${DPAD_DISPLAY_MODE:-auto}"
if [ "$DPAD_DISPLAY_MODE" = "auto" ]; then
    if unshare -U true 2>/dev/null && [ "$(cat /sys/module/nvidia_drm/parameters/modeset 2>/dev/null)" = "Y" ]; then
        DPAD_DISPLAY_MODE=dfp
    else
        DPAD_DISPLAY_MODE=null
    fi
fi
echo "[*] Display mode: ${DPAD_DISPLAY_MODE} (userns=$(unshare -U true 2>/dev/null && echo yes || echo no), nvidia_drm.modeset=$(cat /sys/module/nvidia_drm/parameters/modeset 2>/dev/null || echo ?))"

# CEF/Chrome needs a large /dev/shm for shared memory; Docker's default 64 MB
# makes steamwebhelper crash-loop ("Failed creating offscreen shared JS context"
# → "steamwebhelper is not responding"). On a --privileged container we remount
# it bigger; else the launcher must pass --shm-size=2g (or --ipc=host). Only
# matters for the DFP/full-Steam path.
if [ "${DPAD_DISPLAY_MODE}" = "dfp" ]; then
    if mount -o remount,size=2g /dev/shm 2>/dev/null; then
        echo "    /dev/shm enlarged to 2G for CEF shared memory (was $(df -h /dev/shm 2>/dev/null | tail -1 | awk '{print $2}'))"
    else
        echo "    NOTE: /dev/shm remount failed ($(df -h /dev/shm 2>/dev/null | tail -1 | awk '{print $2}')) — if steamwebhelper crash-loops, re-launch with --shm-size=2g or --ipc=host"
    fi
fi

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
# Steam's first-run "update status" UI (updateui_gl.cpp) creates an OpenGL font
# texture. On gamescope's headless Xwayland that GL context can't create the
# texture → "UpdateUI CreateGlFont regular failed" → Steam exits → gamescope
# 'Primary child shut down' → segfault loop. On Xvfb + mesa/llvmpipe (software
# GL) the GL font works fine, so we bootstrap Steam ONCE on Xvfb to download the
# full client. Once the full client is installed, Steam uses the "console"
# update UI (no GL font) and runs cleanly under gamescope headless Xwayland
# (validated upstream — gamescope issue #1984). Idempotent: skips if the full
# client is already present (so a build-time pre-bootstrap makes this a no-op).
# Also fixes ~/.steam/root: the Dockerfile used to leave it as a real directory
# (for Proton-GE) which makes steam.sh's `rm -f ~/.steam/root` fail.
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

    echo "[*] Bootstrapping Steam client on Xvfb (first-run GL updater needs software GL, not gamescope Xwayland) — downloads ~300MB once..."
    as_user "Xvfb :8 -screen 0 1280x720x24 +extension GLX +extension RANDR >/tmp/xvfb-bootstrap.log 2>&1 &" 2>/dev/null
    sleep 2
    # Use the /usr/bin/steam wrapper (Debian steam-installer) — on a fresh
    # container that goes straight to gamescope mode, ~/.steam/debian-installation/
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
        as_user "cd ${USER_HOME}; export DISPLAY=:8 HOME=${USER_HOME} USER=${USER_NAME} XDG_RUNTIME_DIR=${XDG_RUNTIME_DIR} PULSE_SERVER=${PULSE_SERVER} DBUS_SESSION_BUS_ADDRESS='${DBUS_SESSION_BUS_ADDRESS}'; exec ${steam_cmd} -gamepadui" >/tmp/steam-bootstrap.log 2>&1 &
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
        echo "[*] WARNING: Steam bootstrap incomplete — gamescope may fail at the GL updater UI. See /tmp/steam-bootstrap.log"
        tail -20 /tmp/steam-bootstrap.log 2>/dev/null | sed 's/^/    /'
    fi
}

# --- Stage 2: bridge gamescope's PipeWire node to Xvfb :2 -> Selkies (ximagesrc) ---
# Selkies v1.6.x only does ximagesrc (no pipewiresrc option), and gamescope's
# headless Xwayland has no root pixmap (ximagesrc on gamescope's :0 is black).
# So we bridge: Xvfb :2 + (pipewiresrc target-object=gamescope ! videoconvert !
# ximagesink display=:2), then Selkies ximagesrc-captures :2 -> nvh264enc ->
# WebRTC -> coturn -> cloudflared. Validated on-instance: the bridge paints real
# gamescope UI content onto :2 (1.1MB captured frame). Needs gstreamer1.0-tools
# (gst-launch-1.0) in the image — added in the Dockerfile gamescope step.
start_gamescope_stream() {
    # Stage 2 video source. Default = pipewiresrc (zero-copy-ish: Selkies reads
    # gamescope's PipeWire node directly -> cudaupload -> cudaconvert -> nvh264enc,
    # no Xvfb :2 / ximagesrc bridge, no CPU videoconvert). Set DPAD_VIDEO_SRC=ximagesrc
    # to revert to the :2 bridge path (Selkies 1.6.x's original ximagesrc capture).
    local video_src="${DPAD_VIDEO_SRC:-pipewiresrc}"
    # clear stale logs + the Xvfb :2 lock/socket files (the lock + the ABSTRACT
    # socket @/tmp/.X11-unix/X2 persist across restarts; a stale Xvfb :2 holding it
    # makes a new Xvfb :2 fail with 'Cannot establish any listening sockets' -> :2
    # never comes up -> bridge paints into nothing -> ximagesrc-captures :2 black).
    rm -f /tmp/selkies.log /tmp/bridge.log /tmp/coturn.log /tmp/cloudflared-selkies.log /tmp/xvfb2.log /tmp/rtc_config.json /tmp/.X2-lock /tmp/.X11-unix/X2 2>/dev/null
    pkill -9 -f "Xvfb :2" 2>/dev/null || true
    pkill -9 -f "pipewiresrc target-object=gamescope ! videoconvert" 2>/dev/null || true
    sleep 1
    local GS_W GS_H enc rtc url
    GS_W="$(printf '%s' "${SCREEN_RESOLUTION:-1920x1080x24}" | cut -dx -f1)"; [ -z "$GS_W" ] && GS_W=1920
    GS_H="$(printf '%s' "${SCREEN_RESOLUTION:-1920x1080x24}" | cut -dx -f2)"; [ -z "$GS_H" ] && GS_H=1080

    if [ "$video_src" = "pipewiresrc" ]; then
        echo "[*] Stage 2 (zero-copy): Selkies captures gamescope's PipeWire node directly (pipewiresrc -> cudaupload -> cudaconvert -> nvh264enc); no Xvfb :2 / ximagesrc bridge — saves the GPU->CPU->:2->ximagesrc round-trip + the CPU videoconvert passes. (Set DPAD_VIDEO_SRC=ximagesrc to revert to the :2 bridge path.)"
    else
        echo "[*] Stage 2: bridging gamescope PipeWire node -> Xvfb :2 -> Selkies (ximagesrc)"
        # start Xvfb :2 and VERIFY the socket came up. Retry once if a stale holder
        # raced us (kill everything on :2 and try again).
        start_xvfb2() {
            as_user "Xvfb :2 -ac -screen 0 ${GS_W}x${GS_H}x24 +extension GLX +extension RANDR >/tmp/xvfb2.log 2>&1 &" 2>/dev/null
            sleep 2
            [ -S /tmp/.X11-unix/X2 ]
        }
        if ! start_xvfb2; then
            echo "    Xvfb :2 first try failed — killing stale holders and retrying"
            pkill -9 -f "Xvfb :2" 2>/dev/null || true
            rm -f /tmp/.X2-lock /tmp/.X11-unix/X2 2>/dev/null
            sleep 1
            start_xvfb2 || { echo "    WARNING: Xvfb :2 would not start — Selkies will stream black (see /tmp/xvfb2.log)"; tail -12 /tmp/xvfb2.log 2>/dev/null | sed 's/^/      /'; }
        fi
        [ -S /tmp/.X11-unix/X2 ] && echo "    Xvfb :2 up (socket /tmp/.X11-unix/X2)" || echo "    WARNING: Xvfb :2 socket missing"

        # bridge: pipewiresrc(gamescope) -> videoconvert -> ximagesink on :2.
        as_user "export XDG_RUNTIME_DIR=${XDG_RUNTIME_DIR}; gst-launch-1.0 pipewiresrc target-object=gamescope ! videoconvert ! ximagesink display=:2 sync=false force-aspect-ratio=false >/tmp/bridge.log 2>&1 &" 2>/dev/null
        sleep 3
        pgrep -f "pipewiresrc target-object=gamescope" >/dev/null && echo "    bridge gst running" || { echo "    WARNING: bridge gst failed"; tail -12 /tmp/bridge.log 2>/dev/null | sed 's/^/      /'; }
    fi

    if ! pgrep -x turnserver >/dev/null; then
        echo "[*] Starting coturn on ${TURN_PORT_EXT}..."
        turnserver -n -a --lt-cred-mech --fingerprint --no-stun --no-multicast-peers --no-cli --listening-ip=0.0.0.0 --realm=dpadcloud --user="${TURN_USER}:${TURN_PASS}" -p "${TURN_PORT_LISTEN:-${TURN_PORT_EXT}}" -X "${PUBLIC_IP:-localhost}" >/tmp/coturn.log 2>&1 &
        sleep 2
        pgrep -x turnserver >/dev/null && echo "    coturn running" || echo "    WARNING: coturn failed (see /tmp/coturn.log)"
    fi

    # Audio for Selkies pulsesrc is served by pipewire-pulse (started in
    # start_gamescope_session): a null sink + dummy.monitor source on the
    # ${PULSE_SERVER} socket. Just verify the socket is up so the boot log is
    # explicit about whether Selkies audio will negotiate.
    if [ -S "${XDG_RUNTIME_DIR}/pulse/native" ]; then
        echo "    audio socket OK (${XDG_RUNTIME_DIR}/pulse/native)"
        echo "    --- sinks ---"; as_user "export PULSE_SERVER=unix:${XDG_RUNTIME_DIR}/pulse/native XDG_RUNTIME_DIR=${XDG_RUNTIME_DIR}; pactl list short sinks 2>/dev/null" | sed 's/^/      /'
    else
        echo "    WARNING: pipewire-pulse socket missing — Selkies audio will fail (pulsesrc Connection refused)"
    fi

    rtc=/tmp/rtc_config.json
    _listen="${TURN_PORT_LISTEN:-${TURN_PORT_EXT}}"
    # Real external ports per protocol (empty if that protocol's port wasn't exposed
    # at the VM). Vast forbids the same port as BOTH tcp and udp, so usually only
    # ONE is set; emit ICE entries only for the exposed protocol(s) — UDP for low
    # latency, TCP as a fallback on providers that allow both. coturn already
    # listens both (no --no-udp); with both peers on the same coturn the relay
    # short-circuits internally, so only the listen port needs mapping.
    TCP_EXT="${DPAD_TURN_EXTERNAL_PORT:-$(printenv VAST_TCP_PORT_${_listen} 2>/dev/null || true)}"
    UDP_EXT="${DPAD_TURN_UDP_EXTERNAL_PORT:-$(printenv VAST_UDP_PORT_${_listen} 2>/dev/null || true)}"
    _ices=""
    add_ice() { [ -n "$_ices" ] && _ices+=","; _ices+="{\"urls\":[\"$1\"],\"username\":\"${TURN_USER}\",\"credential\":\"${TURN_PASS}\"}"; }
    if [ -n "$UDP_EXT" ]; then
        add_ice "turn:127.0.0.1:${_listen}?transport=udp"
        add_ice "turn:${PUBLIC_IP}:${UDP_EXT}?transport=udp"
    fi
    if [ -n "$TCP_EXT" ]; then
        add_ice "turn:127.0.0.1:${_listen}?transport=tcp"
        add_ice "turn:${PUBLIC_IP}:${TCP_EXT}?transport=tcp"
    fi
    printf '%s' "{\"iceServers\":[${_ices}],\"iceTransportPolicy\":\"all\"}" > "$rtc"
    chmod 644 "$rtc"
    if [ -z "$_ices" ]; then
        echo "    WARNING: no TURN port exposed (need -p ${_listen}:${_listen}/udp or /tcp) — WebRTC media will fail"
    elif [ -n "$UDP_EXT" ] && [ -n "$TCP_EXT" ]; then
        echo "    TURN: UDP turn:${PUBLIC_IP}:${UDP_EXT} (lower latency) + TCP turn:${PUBLIC_IP}:${TCP_EXT} (fallback)"
    elif [ -n "$UDP_EXT" ]; then
        echo "    TURN: UDP turn:${PUBLIC_IP}:${UDP_EXT} (lower latency; no TCP fallback — Vast forbids same-port tcp+udp)"
    else
        echo "    TURN: TCP turn:${PUBLIC_IP}:${TCP_EXT} (expose -p ${_listen}:${_listen}/udp for lower-latency UDP TURN)"
    fi

    enc="${DPAD_GAMESCOPE_ENCODER:-nvh264enc}"

    # Stage 3a — input routing. Selkies' XTest input normally lands on the
    # capture display (:2, the Xvfb bridge target), which only holds a painted
    # copy of the gamescope frame — so clicks/keys never reach Steam. The real
    # app runs inside gamescope's headless Xwayland, whose display we discover
    # from the gamescope log (e.g. :0). DPAD_INPUT_DISPLAY tells the baked-in
    # dpad_input_patch.py (a site-packages .pth) to override Selkies'
    # send_x11_keypress/send_mouse and inject via XTest on THAT display instead
    # of :2 — so keyboard/mouse reach gamescope -> Steam. Capture stays on :2.
    # If discovery fails, leave DPAD_INPUT_DISPLAY empty -> input stays on :2
    # (current behavior: video works, input doesn't) — a safe fallback.
    local in_dpy=""
    # gamescope's Xwayland display number can vary per boot (and across health-loop
    # restarts), so take the LAST 'Starting Xwayland on :N' line in the log (the
    # current gamescope), not the first (which could be a stale earlier launch).
    in_dpy="$(grep -oE 'Starting Xwayland on :[0-9]+' /tmp/gamescope-steam.log 2>/dev/null | tail -1 | grep -oE ':[0-9]+')"
    [ -z "$in_dpy" ] && in_dpy="$(pgrep -af Xwayland 2>/dev/null | grep -oE 'Xwayland :[0-9]+' | head -1 | grep -oE ':[0-9]+')"
    if [ -n "$in_dpy" ] && [ -S "/tmp/.X11-unix/X${in_dpy#:}" ]; then
        echo "    input -> gamescope Xwayland ${in_dpy} (XTest, DPAD_INPUT_DISPLAY=${in_dpy})"
    else
        echo "    WARNING: gamescope Xwayland display not found — input stays on :2 (no control); video still works"
        in_dpy=""
    fi

    # DISPLAY for Selkies itself: with pipewiresrc capture there is no Xvfb :2,
    # so point any default X usage (e.g. a fallback display.Display()) at
    # gamescope's Xwayland (:0) instead of a non-existent :2. With ximagesrc, :2
    # is the capture display. (dpad_input_patch.py sets self.xdisplay to in_dpy
    # regardless, so this only matters for any unpatched default-open path.)
    local selkies_dpy=":2"
    [ "$video_src" = "pipewiresrc" ] && selkies_dpy="${in_dpy:-:0}"

    # Selkies launch command (reused by the NVENC-register retry below).
    local selkies_cmd="export DISPLAY=${selkies_dpy} DPAD_VIDEO_SRC=${video_src} DPAD_INPUT_DISPLAY=${in_dpy} XDG_RUNTIME_DIR=${XDG_RUNTIME_DIR} PULSE_SERVER=${PULSE_SERVER} PIPEWIRE_LATENCY=10ms GST_DEBUG=1 LD_PRELOAD='${LD_PRELOAD:-${SELKIES_INTERPOSER}}' SDL_JOYSTICK_DEVICE=/dev/input/js0 SELKIES_INTERPOSER='${SELKIES_INTERPOSER}'; . /opt/gstreamer/gst-env; selkies-gstreamer --addr=127.0.0.1 --port=16100 --enable_https=false --encoder=${enc} --enable_basic_auth=true --basic_auth_user='${SELKIES_USER}' --basic_auth_password='${SELKIES_PASS}' --enable_resize=false --enable_cursors=true --rtc_config_json='${rtc}' --js_socket_path=/tmp --web_root=${SELKIES_WEB_ROOT}"
    # Launch Selkies, then verify the encoder registered. On multi-GPU hosts
    # (NVIDIA driver 570+) the FIRST nvh264enc open on a non-zero GPU minor can
    # fail at plugin-register time (gstnvenc.c NvEncOpenEncodeSessionEx 'error
    # code 2' — an intermittent NVENC peer-init with the unmounted host GPU 0;
    # the flexgrip interposer's gpuId->minor matching is unreliable here). The
    # SECOND open always succeeds (the driver is then 'warm'), so retry the
    # launch when the encoder fails to register. Tunable via
    # DPAD_SELKIES_RETRIES (default 3); each attempt sleeps ~6s for register.
    local attempt=0 max_attempts="${DPAD_SELKIES_RETRIES:-3}" err_before err_after
    while :; do
        attempt=$((attempt+1))
        err_before="$(grep -ac 'NvEncOpenEncodeSessionEx failed' /tmp/selkies.log 2>/dev/null || echo 0)"
        as_user "${selkies_cmd}" >>/tmp/selkies.log 2>&1 &
        sleep 6
        if ! pgrep -f selkies-gstreamer >/dev/null; then
            echo "    WARNING: selkies failed to start (attempt ${attempt}; see /tmp/selkies.log)"; tail -20 /tmp/selkies.log 2>/dev/null | sed 's/^/      /'
            break
        fi
        err_after="$(grep -ac 'NvEncOpenEncodeSessionEx failed' /tmp/selkies.log 2>/dev/null || echo 0)"
        if [ "${enc}" = "nvh264enc" ] && [ "${err_after}" -gt "${err_before}" ]; then
            if [ "${attempt}" -lt "${max_attempts}" ]; then
                echo "    NVENC encoder failed to register (driver 570+ peer-init race, attempt ${attempt}/${max_attempts}) — restarting Selkies"
                pkill -f selkies-gstreamer 2>/dev/null; sleep 2
                continue
            fi
            echo "    WARNING: nvh264enc failed to register after ${max_attempts} attempts (see /tmp/selkies.log) — video may be broken; set DPAD_GAMESCOPE_ENCODER=x264enc for software fallback"
            tail -8 /tmp/selkies.log 2>/dev/null | sed 's/^/      /'
        fi
        echo "    Selkies running on 127.0.0.1:16100 (gamescope bridge, encoder=${enc})$([ "${attempt}" -gt 1 ] && echo " — encoder registered on attempt ${attempt}/${max_attempts}")"
        break
    done

    cloudflared tunnel --no-autoupdate --url http://localhost:16100 >/tmp/cloudflared-selkies.log 2>&1 &
    sleep 10
    url="$(grep -oE 'https://[a-z0-9.-]+trycloudflare.com' /tmp/cloudflared-selkies.log 2>/dev/null | head -1)"
    if [ -n "$url" ]; then
        echo "    ▶ gamescope browser stream: ${url}  (login ${SELKIES_USER} / ${SELKIES_PASS})"
    else
        echo "    Selkies tunnel URL not captured (see /tmp/cloudflared-selkies.log)"
    fi
}

# --- DPAD_GAMESCOPE mode: gamescope --backend headless + Steam (multi-tenant) ---
# Renders the Steam UI on the GPU via Vulkan/gamescope-WSI with NO DRM master, so
# N sessions on N GPUs in one VM don't contend for the nvidia-modeset singleton.
# Steam runs as dpad with the entrypoint session env (DBUS/XDG/PULSE/HOME/USER).
# PipeWire+wireplumber run first so gamescope's capture node is available.
# NOTE: capture/stream (PipeWire -> NVENC -> WebRTC) is wired in a later stage;
# this function currently gets the Steam UI rendering in headless gamescope.
# --- NVENC multi-GPU topology + flexgrip auto-enable (nvidia-container-toolkit #1249) ---
# On driver >=570, NVENC's GET_ATTACHED_IDS returns ALL host GPUs; it then
# peer-inits with the ones whose /dev/nvidiaX aren't mounted and bails with
# NV_ENC_ERR_UNSUPPORTED_DEVICE (error code 2) — so a gamescope or DFP
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
# assembles LD_PRELOAD. Shared by the gamescope path (start_gamescope_session)
# and the DFP path (which has its own inline copy of this detection below).
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

start_gamescope_session() {
    echo "[*] DPAD_GAMESCOPE mode: gamescope --backend headless + Steam (no DRM master)"
    # gamescope headless does NOT composite the X cursor into its PipeWire output,
    # so the only visible cursor source is Selkies' XFIXES cursor overlay. Enable it
    # (cursors=true) AND gate the web client's auto pointer-lock so the CSS cursor
    # stays visible (pointer lock hides the CSS cursor) + mouse stays absolute for
    # UI navigation. (The dpad_input_patch.py .pth makes XFIXES safe; the old
    # crash was when the :2 bridge was broken.)
    bash /opt/dpadcloud/patch_gst_web_cursors.sh "${SELKIES_WEB_ROOT}/input.js" 2>/dev/null || true
    local GS_W GS_H STEAM_ARGS
    GS_W="$(printf '%s' "${SCREEN_RESOLUTION:-1920x1080x24}" | cut -dx -f1)"
    GS_H="$(printf '%s' "${SCREEN_RESOLUTION:-1920x1080x24}" | cut -dx -f2)"
    [ -z "$GS_W" ] && GS_W=1920
    [ -z "$GS_H" ] && GS_H=1080
    STEAM_ARGS="${DPAD_STEAM_ARGS:--gamepadui}"

    # Bootstrap the Steam full client on Xvfb BEFORE entering gamescope. Steam's
    # first-run GL updater UI can't create its font texture on gamescope headless
    # Xwayland; on Xvfb (software GL) it works. Once the full client is installed,
    # Steam uses the console updater UI which runs fine under gamescope.
    bootstrap_steam_on_xvfb

    # PipeWire + wireplumber (as dpad, with the session env) — gamescope's
    # capture node needs pipewire running before it starts.
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
        echo "    WARNING: PipeWire not ready after 15s — see /tmp/pipewire.log (gamescope capture node may be unavailable)"
    fi

    # pipewire-pulse: PulseAudio-compatible server so Selkies' pulsesrc can
    # capture audio. It creates the ${PULSE_SERVER} socket (unix:/run/user/<uid>
    # /pulse/native). gamescope mode has no hardware audio, so create a null
    # sink — its .monitor source is what Selkies' pulsesrc captures (silence
    # is fine; the point is a CAPTURABLE source so the audio pipeline negotiates
    # instead of failing with 'pulsesrc Connection refused' -> browser stuck
    # on 'Waiting for stream'). Replaces the separate PulseAudio daemon (which
    # also isn't installed in this image — only pulseaudio-utils/pactl is).
    echo "[*] Starting pipewire-pulse (PulseAudio compat) + null audio sink..."
    mkdir -p "${XDG_RUNTIME_DIR}/pulse" 2>/dev/null
    chmod 1777 "${XDG_RUNTIME_DIR}/pulse" 2>/dev/null
    as_user "export XDG_RUNTIME_DIR=${XDG_RUNTIME_DIR} DBUS_SESSION_BUS_ADDRESS='${DBUS_SESSION_BUS_ADDRESS}' HOME=${USER_HOME}; pipewire-pulse >/tmp/pipewire-pulse.log 2>&1 &"
    local pp_wait=0
    while [ $pp_wait -lt 15 ]; do
        [ -S "${XDG_RUNTIME_DIR}/pulse/native" ] && break
        sleep 1; pp_wait=$((pp_wait+1))
    done
    if [ -S "${XDG_RUNTIME_DIR}/pulse/native" ]; then
        echo "    pipewire-pulse ready (socket ${XDG_RUNTIME_DIR}/pulse/native)"
        # module-null-sink is supported by pipewire-pulse; gives a default sink
        # + a dummy.monitor source for pulsesrc to capture.
        as_user "export PULSE_SERVER=unix:${XDG_RUNTIME_DIR}/pulse/native XDG_RUNTIME_DIR=${XDG_RUNTIME_DIR}; pactl load-module module-null-sink sink_name=dummy sink_properties=device.description=DummyOutput 2>/dev/null; pactl set-default-sink dummy 2>/dev/null; pactl set-default-source dummy.monitor 2>/dev/null" >/dev/null 2>&1 || true
        echo "    --- audio sinks ---"; as_user "export PULSE_SERVER=unix:${XDG_RUNTIME_DIR}/pulse/native XDG_RUNTIME_DIR=${XDG_RUNTIME_DIR}; pactl list short sinks 2>/dev/null" | sed 's/^/      /'
    else
        echo "    WARNING: pipewire-pulse socket not up after 15s — Selkies audio will fail (see /tmp/pipewire-pulse.log)"
        tail -8 /tmp/pipewire-pulse.log 2>/dev/null | sed 's/^/      /'
    fi

    # gamescope headless + Steam (as dpad, with the session env). Unset DISPLAY/
    # WAYLAND_DISPLAY so gamescope doesn't try to nest; VK_ICD pins the NVIDIA ICD.
    # chown ~dpad first — a root boot process (D-Bus/install-display-drivers) can
    # create ~/.local root-owned, which makes Steam's `mkdir ~/.local/share/icons`
    # EPERM and abort the launch (gamescope then 'Primary child shut down').
    # Targeted chown: only fix files NOT already dpad:dpad (see bootstrap_steam_on_xvfb
    # note — a blanket `chown -R` copy-up's ~4GB/33k files on overlayfs, ~120s, for
    # zero benefit since the image already owns everything as dpad). This is the
    # gamescope-mode cold-boot critical path (was 69% of boot time).
    find "${USER_HOME}" ! \( -user "${USER_NAME}" -group "${USER_NAME}" \) -exec chown "${USER_NAME}:${USER_NAME}" {} + 2>/dev/null || true

    # Gamepad (Selkies joystick interposer, the v1.6.2 LD_PRELOAD shim). The
    # gamescope path `exit 0`s before the global interposer setup further down, so
    # set it up here. The interposer intercepts open("/dev/input/jsN") in the app
    # (Steam's SDL) and redirects it to /tmp/selkies_jsN.sock — the socket server
    # Selkies creates when the browser connects a gamepad. This is the gamepad
    # analog of the XTest keyboard/mouse path: DIRECT, in-process, no gamescope
    # libinput/libei involved (gamescope's libinput handles only pointer/keyboard/
    # touch, and the EIS/libei socket exposes only POINTER/KEYBOARD — gamepad axes
    # have NO path through gamescope, so the interposer is the controller route).
    #
    # Steam ships SDL3, which defaults to the evdev backend (/dev/input/event* via
    # libudev) and ignores the legacy joystick API (/dev/input/js*) that the v1.6.2
    # interposer hooks. SDL3's classic joystick path (SDL_HINT_JOYSTICK_LINUX_CLASSIC)
    # re-enables the legacy /dev/input/js* backend — it uses JSIOCG* ioctls + reads
    # 8-byte js_event structs (exactly what the v1.6.2 interposer + Selkies' gamepad.py
    # serve; validated: JSIOCGVERSION/NAME/AXES/BUTTONS/AXMAP/BTNMAP all handled).
    # SDL3 auto-disables udev ONLY if SDL_GetSandbox() detects a container, but
    # SDL_DetectSandbox only checks /.flatpak-info, SNAP* env, or /run/host/
    # container-manager — NONE of which exist in a plain Vast Docker container —
    # so SDL3 sees SDL_SANDBOX_NONE and uses the LIBUDEV path. With libudev loaded
    # but no udev daemon, SDL3 enumerates zero devices AND the inotify/scandir
    # hotplug (which only runs in ENUMERATION_FALLBACK) is NOT active, so mknodding
    # /dev/input/jsN later is ignored. SDL_JOYSTICK_DISABLE_UDEV=1 forces
    # ENUMERATION_FALLBACK, activating the inotify (IN_CREATE -> MaybeAddDevice
    # for js* in classic mode) + 3s scandir-mtime hotplug the watcher relies on.
    #
    # Timing race (the gotcha): SDL3 enumerates joysticks ONCE at SDL_Init (Steam
    # startup), BEFORE the browser gamepad connects (the user presses a button only
    # after the Steam UI is up). If /dev/input/jsN exists at boot but the Selkies
    # socket /tmp/selkies_jsN.sock doesn't yet, the interposer's open() fails to
    # connect and SDL3 sees no controller (and doesn't re-scan unless a NEW js node
    # appears). Fix: do NOT pre-create /dev/input/js* at boot. Instead a root watcher
    # daemon creates /dev/input/jsN (major 13) the instant Selkies' gamepad socket
    # /tmp/selkies_jsN.sock appears (Selkies creates it when the browser connects a
    # controller), and removes it when the socket goes. The node creation fires SDL3's
    # inotify IN_CREATE -> MaybeAddDevice("/dev/input/jsN") -> open intercepted by the
    # interposer -> the now-existing socket -> Steam hotplugs the controller. (mknod
    # needs root; Selkies runs as dpad, so the watcher runs as root here.)
    # NVENC multi-GPU fix (nvidia-container-toolkit #1249): on driver 570+ a
    # gamescope container pinned to a non-zero GPU minor fails NVENC peer-init
    # (NvEncOpenEncodeSessionEx 'error code 2') — the flexgrip libnvenc_fix.so
    # interposer filters NVENC's GET_ATTACHED_IDS to only mounted GPUs. Run it
    # before the LD_PRELOAD assembly so the gamescope+Steam AND Selkies encoder
    # inherit it. (The DFP path has its own inline copy of this detection.)
    setup_nvenc_fix
    DPAD_PRELOAD=""
    [ "$NVENC_FIX_ENABLED" = "1" ] && DPAD_PRELOAD="/opt/dpadcloud/libnvenc_fix.so"
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
    # re-exported explicitly inside each gamescope+Steam launch below.
    export LD_PRELOAD="${DPAD_PRELOAD}${DPAD_PRELOAD:+:}${SELKIES_INTERPOSER}${LD_PRELOAD:+:${LD_PRELOAD}}"
    # SDL_GameController mapping for the Selkies virtual gamepad. The v1.6.2
    # interposer presents a raw joystick named "Selkies Controller" with NO
    # vendor/product ID (its js_config_t has no vendor/product fields + it
    # doesn't intercept JSIOCGID), so SDL3 can't auto-map it as a gamepad —
    # Steam Big Picture (which drives gamepadui via the SDL_GameController API)
    # would ignore it. SDL3's GUID for a zero-vendor classic js device is
    # bus(0)+crc16(name)+name-bytes (SDL_CreateJoystickGUID, vendor=0 branch):
    # crc16("Selkies Controller")=0x06d6 -> GUID 0000d60653656c6b69657320436f6e00.
    # This mapping tells SDL3 how the xpad-layout joystick indices map to a
    # standard gamepad (matches STANDARD_XPAD_CONFIG in selkies gamepad.py:
    # btn 0-10 = A/B/X/Y/TL/TR/SELECT/START/MODE/THUMBL/THUMBR, axes 0-7 =
    # X/Y/Z/RX/RY/RZ/HAT0X/HAT0Y; dpad arrives as axes 6/7, triggers as 2/5).
    export SDL_GAMECONTROLLERCONFIG='0000d60653656c6b69657320436f6e00,Selkies Controller,a:b0,b:b1,x:b2,y:b3,back:b6,guide:b8,start:b7,leftshoulder:b4,rightshoulder:b5,leftstick:b9,rightstick:b10,leftx:a0,lefty:a1,rightx:a3,righty:a4,lefttrigger:a2,righttrigger:a5,dpup:h0.1,dpdown:h0.4,dpleft:h0.8,dpright:h0.2,'
    echo "[*] Launching gamescope --backend headless -e -W ${GS_W} -H ${GS_H} -- steam ${STEAM_ARGS}"
    as_user "cd ${USER_HOME}; unset DISPLAY WAYLAND_DISPLAY; export XDG_RUNTIME_DIR=${XDG_RUNTIME_DIR} PULSE_SERVER=${PULSE_SERVER} DBUS_SESSION_BUS_ADDRESS='${DBUS_SESSION_BUS_ADDRESS}' HOME=${USER_HOME} USER=${USER_NAME} VK_ICD_FILENAMES=/etc/vulkan/icd.d/nvidia_icd.json LD_PRELOAD='${LD_PRELOAD}' SDL_JOYSTICK_DEVICE=/dev/input/js0 SDL_JOYSTICK_LINUX_CLASSIC=1 SDL_JOYSTICK_DISABLE_UDEV=1 SDL_GAMECONTROLLERCONFIG='${SDL_GAMECONTROLLERCONFIG}' SELKIES_INTERPOSER='${SELKIES_INTERPOSER}'; exec gamescope --backend headless -e -W ${GS_W} -H ${GS_H} -- steam ${STEAM_ARGS}" >/tmp/gamescope-steam.log 2>&1 &
    local gs_pid=$!

    # Steam takes ~30-40s to launch through pressure-vessel + steamwebhelper
    # under gamescope; a fixed 20s check fires too early and the health loop
    # restarts before Steam stabilises. Poll up to 90s for both processes.
    # NOTE: use `kill -0 $gs_pid` for gamescope liveness, NOT `pgrep -x gamescope` —
    # the gamescope process's comm is not exactly "gamescope" (pgrep -x is a false
    # negative), which made the health loop SIGKILL a healthy Steam every 30s.
    local ready=0
    local rw=0
    while [ $rw -lt 90 ]; do
        if kill -0 "$gs_pid" 2>/dev/null && pgrep -x steam >/dev/null; then ready=1; break; fi
        sleep 3; rw=$((rw+3))
    done
    if [ $ready -eq 1 ]; then
        echo "[*] GAMESCOPE SESSION READY — Steam UI rendering in headless gamescope (no DRM master)."
    else
        echo "[*] WARNING: gamescope/steam not both up after 90s — check /tmp/gamescope-steam.log"
    fi
    echo "    gamescope+steam log: /tmp/gamescope-steam.log"
    echo "    GPU: $(nvidia-smi -L 2>/dev/null | head -1)"
    echo "    NOTE: capture via PipeWire->Xvfb:2 bridge -> Selkies (ximagesrc)."
    start_gamescope_stream

    # health loop — restart the gamescope+steam session if gamescope dies.
    # `kill -0 $gs_pid` (not `pgrep -x gamescope` — see note above) checks the
    # exact PID we launched (the su→gamescope process).
    while true; do
        sleep 30
        if ! kill -0 "$gs_pid" 2>/dev/null; then
            echo "[*] WARNING: gamescope died — restarting session..."
            kill $gs_pid 2>/dev/null; pkill -9 -x steam 2>/dev/null; pkill -9 -x steamwebhelper 2>/dev/null; sleep 2
            rm -f ${USER_HOME}/.steam/steam/steam.pid ${USER_HOME}/.steam/debian-installation/steam.pid 2>/dev/null
            as_user "cd ${USER_HOME}; unset DISPLAY WAYLAND_DISPLAY; export XDG_RUNTIME_DIR=${XDG_RUNTIME_DIR} PULSE_SERVER=${PULSE_SERVER} DBUS_SESSION_BUS_ADDRESS='${DBUS_SESSION_BUS_ADDRESS}' HOME=${USER_HOME} USER=${USER_NAME} VK_ICD_FILENAMES=/etc/vulkan/icd.d/nvidia_icd.json LD_PRELOAD='${LD_PRELOAD}' SDL_JOYSTICK_DEVICE=/dev/input/js0 SDL_JOYSTICK_LINUX_CLASSIC=1 SDL_JOYSTICK_DISABLE_UDEV=1 SDL_GAMECONTROLLERCONFIG='${SDL_GAMECONTROLLERCONFIG}' SELKIES_INTERPOSER='${SELKIES_INTERPOSER}'; exec gamescope --backend headless -e -W ${GS_W} -H ${GS_H} -- steam ${STEAM_ARGS}" >/tmp/gamescope-steam.log 2>&1 &
            gs_pid=$!
        fi
        # Xvfb :2 + the PipeWire->:2 bridge / Xvfb `:2` are the Selkies capture path (ximagesrc mode). If :2 dies (or the bridge gst dies) the
        # browser goes black / loops on 'Waiting for stream'. Recover both without touching gamescope.
        # NOT run in pipewiresrc mode (no :2/bridge there; selkies pipewiresrc captures gamescope's
        # PipeWire node directly).
        if [ "${DPAD_VIDEO_SRC:-pipewiresrc}" != "pipewiresrc" ] && { [ ! -S /tmp/.X11-unix/X2 ] || ! pgrep -f "pipewiresrc target-object=gamescope" >/dev/null; }; then
            echo "[*] WARNING: Xvfb :2 or bridge died — restarting capture path..."
            pkill -9 -f "Xvfb :2" 2>/dev/null || true
            pkill -9 -f "pipewiresrc target-object=gamescope" 2>/dev/null || true
            rm -f /tmp/.X2-lock /tmp/.X11-unix/X2 2>/dev/null; sleep 1
            as_user "Xvfb :2 -ac -screen 0 ${GS_W}x${GS_H}x24 +extension GLX +extension RANDR >/tmp/xvfb2.log 2>&1 &" 2>/dev/null
            sleep 2
            as_user "export XDG_RUNTIME_DIR=${XDG_RUNTIME_DIR}; gst-launch-1.0 pipewiresrc target-object=gamescope ! videoconvert ! ximagesink display=:2 sync=false force-aspect-ratio=false >/tmp/bridge.log 2>&1 &" 2>/dev/null
        fi
    done
}

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

    # Try forward-compat (datacenter GPUs only; consumer GPUs will fail cuInit test)
    local COMPAT_DIR="${CUDA_REAL}/compat"
    if [ -d "$COMPAT_DIR" ] && compgen -G "$COMPAT_DIR/libcuda.so.*" >/dev/null 2>&1; then
        if LD_LIBRARY_PATH="$COMPAT_DIR" python3 -c "import ctypes,sys; sys.exit(0 if ctypes.CDLL('libcuda.so.1').cuInit(0)==0 else 1)" 2>/dev/null; then
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

# --- SSH server (B1: dpadplay VPS reverse-proxy tunnel) ---
# Vast maps 22 -> VAST_TCP_PORT_22; the dpadplay VPS autossh-tunnels
# localhost:16100 (Selkies signaling) through this port. Pubkey-only, the key
# injected via DPAD_ORCHESTRATOR_PUBKEY. Media/input stay direct via coturn —
# this carries only the signaling WebSocket. Starts early so the VPS can
# connect as soon as the container boots (eager tunnel = no cold-start on Play).
if command -v sshd >/dev/null 2>&1; then
    mkdir -p /run/sshd
    [ ! -e /etc/ssh/ssh_host_ed25519_key ] && ssh-keygen -A >/dev/null 2>&1 || true
    # Authorize the orchestrator pubkey for the dpad user (idempotent).
    if [ -n "${DPAD_ORCHESTRATOR_PUBKEY:-}" ]; then
        install -d -m 700 "${USER_HOME}/.ssh"
        grep -qxF "${DPAD_ORCHESTRATOR_PUBKEY}" "${USER_HOME}/.ssh/authorized_keys" 2>/dev/null \
            || echo "${DPAD_ORCHESTRATOR_PUBKEY}" >> "${USER_HOME}/.ssh/authorized_keys"
        chown -R "${USER_NAME}:${USER_NAME}" "${USER_HOME}/.ssh"
        chmod 600 "${USER_HOME}/.ssh/authorized_keys" 2>/dev/null || true
    fi
    # Hardened config: pubkey only, no passwords, no root, only the dpad user.
    if [ ! -f /etc/ssh/sshd_config.d/dpad.conf ]; then
        mkdir -p /etc/ssh/sshd_config.d
        cat > /etc/ssh/sshd_config.d/dpad.conf <<EOF
Port 22
ListenAddress 0.0.0.0
PubkeyAuthentication yes
PasswordAuthentication no
KbdInteractiveAuthentication no
PermitRootLogin no
AllowUsers ${USER_NAME}
EOF
    fi
    if /usr/sbin/sshd -t 2>/tmp/sshd-configtest.log; then
        /usr/sbin/sshd >/tmp/sshd.log 2>&1 \
            && echo "[*] SSH server on :22 (pubkey only, user=${USER_NAME}) — dpadplay VPS reverse-proxy tunnel" \
            || echo "    WARNING: sshd failed to start (see /tmp/sshd.log)"
    else
        echo "    WARNING: sshd config test failed (see /tmp/sshd-configtest.log); sshd not started"
    fi
else
    echo "[*] sshd not installed — VPS reverse-proxy tunnel disabled (cloudflared remains)"
fi

# --- D-Bus (system + session) ---
echo "[*] Starting D-Bus..."
mkdir -p /run/dbus "${XDG_RUNTIME_DIR}/dbus"
[ ! -e /var/run/dbus/system_bus_socket ] && dbus-daemon --system --fork 2>/dev/null || true
# Start a session bus and CAPTURE its address — xfwm4/xfce4-panel/xfdesktop/
# xfsettingsd all need DBUS_SESSION_BUS_ADDRESS or they exit silently. Throwing
# the --print-address output away (the old bug) left the desktop unpainted →
# Selkies streamed a black root window with the default X cursor.
DBUS_SESSION_BUS_ADDRESS="$(as_user "export XDG_RUNTIME_DIR=${XDG_RUNTIME_DIR}; dbus-daemon --session --fork --print-address=1 2>/dev/null" | head -1)"
export DBUS_SESSION_BUS_ADDRESS
if [ -n "${DBUS_SESSION_BUS_ADDRESS}" ]; then
    echo "    D-Bus session: ${DBUS_SESSION_BUS_ADDRESS}"
else
    echo "    WARNING: D-Bus session bus address not captured — XFCE components will likely fail."
fi
sleep 1

# --- DPAD_GAMESCOPE: gamescope headless + Steam (multi-tenant full-Steam path) ---
# If set, run the gamescope session INSTEAD of the Xorg/XFCE/Selkies/Sunshine
# path and stay there (the rest of this script is the DFP/single-user path).
DPAD_GAMESCOPE="${DPAD_GAMESCOPE:-0}"
if [ "${DPAD_GAMESCOPE}" = "1" ]; then
    start_gamescope_session
    exit 0
fi

# --- Display server: REAL Xorg + nvidia DDX (gaming) or Xvfb+Mesa (debug) ---
# DPAD_XORG=1 (default): a real Xorg with the nvidia DDX driver so Vulkan gets a
#   present surface → DXVK/Proton render on the GPU (the cloud-gaming path).
# DPAD_XORG=0: Xvfb + Mesa software EGL + VirtualGL (the old path; kept ONLY as
#   a debug/fallback when the nvidia DDX isn't available or Xorg won't start).
# Steam autostart + vgl-steam both branch on which server actually came up.
export DPAD_XORG="${DPAD_XORG:-1}"
SCREEN_W="$(echo "$SCREEN_RES" | cut -dx -f1)"
SCREEN_H="$(echo "$SCREEN_RES" | cut -dx -f2)"
SCREEN_D="$(echo "$SCREEN_RES" | cut -dx -f3)"; [ -z "$SCREEN_D" ] && SCREEN_D=24
rm -f /tmp/.X${DISPLAY_NUM#:}-lock /tmp/.X11-unix/X${DISPLAY_NUM#:}

# Generate /etc/X11/xorg.conf for the assigned GPU (busid from nvidia-smi).
# nvidia-xconfig if available; else our shipped template + sed.
generate_xorg_conf() {
    local GPU_BUS_HEX BUSID B D F MODEL MODE_NAME
    GPU_BUS_HEX="$(nvidia-smi --query-gpu=pci.bus_id --format=csv,noheader 2>/dev/null | head -1)"
    # GPU_BUS_HEX like "00000000:01:00.0" -> PCI:1:0:0
    BUSID=""
    if [ -n "$GPU_BUS_HEX" ]; then
        IFS=":." read -r _b B D F <<< "$GPU_BUS_HEX"
        BUSID="PCI:$((16#${B:-0})):$((16#${D:-0})):$((16#${F:-0}))"
    fi
    MODEL="$(command -v cvt >/dev/null 2>&1 && cvt -r "$SCREEN_W" "$SCREEN_H" 60 2>/dev/null | sed -n 2p)"
    MODE_NAME="$(echo "$MODEL" | awk '{print $2}' | tr -d '"')"
    [ -z "$MODE_NAME" ] && MODE_NAME="${SCREEN_W}x${SCREEN_H}"
    rm -f /etc/X11/xorg.conf
    if command -v nvidia-xconfig >/dev/null 2>&1; then
        local DRVMAJ
        DRVMAJ="$(nvidia-smi --query-gpu=driver_version --format=csv,noheader 2>/dev/null | head -1 | cut -d. -f1)"
        # Display device: DFP (connected virtual monitor) on userns-capable hosts
        # that can be DRM master (Vast KVM VM / RunPod Secure Cloud with
        # --privileged) — CEF's browser composer needs a real connected monitor
        # to create the Steam UI window ("Could not find display info" in NULL
        # mode). NULL/NoScanout on Vast Docker (no userns / no DRM master): the
        # nvidia DDX runs WITHOUT KMS, Xorg still comes up, GL/Vulkan render on
        # the GPU, capture via XGetImage on the root window (backing store).
        # DPAD_DISPLAY_MODE is auto-detected above (dfp if userns + modeset=Y).
        local DD_ARGS=(--use-display-device=None --connected-monitor=None)
        if [ "${DPAD_DISPLAY_MODE:-null}" = "dfp" ]; then
            DD_ARGS=(--use-display-device=DFP-0 --connected-monitor=DFP-0)
        fi
        local NVXCFG_ARGS=(--virtual="${SCREEN_W}x${SCREEN_H}" --depth="$SCREEN_D" \
            --mode="$MODE_NAME" --allow-empty-initial-configuration --no-probe-all-gpus \
            --only-one-x-screen --no-sli --no-base-mosaic "${DD_ARGS[@]}")
        [ -n "$BUSID" ] && NVXCFG_ARGS+=(--busid="$BUSID")
        # --no-multigpu was removed in driver 550; only pass it on older drivers.
        if [ -z "$DRVMAJ" ] || [ "$DRVMAJ" -lt 550 ]; then NVXCFG_ARGS+=(--no-multigpu); fi
        nvidia-xconfig "${NVXCFG_ARGS[@]}" >/dev/null 2>&1 || true
        # Patch in the options Steam-Headless found necessary on a headless GPU.
        sed -i '/Driver\s\+"nvidia"/a\    Option         "PrimaryGPU" "yes"' /etc/X11/xorg.conf 2>/dev/null || true
        sed -i '/Driver\s\+"nvidia"/a\    Option         "AllowEmptyInitialConfiguration"' /etc/X11/xorg.conf 2>/dev/null || true
        sed -i '/Driver\s\+"nvidia"/a\    Option         "ModeValidation" "NoMaxPClkCheck, NoEdidMaxPClkCheck, NoMaxSizeCheck, NoHorizSyncCheck, NoVertRefreshCheck, NoVirtualSizeCheck, NoTotalSizeCheck, NoDualLinkDVICheck, NoDisplayPortBandwidthCheck, AllowNon3DVisionModes, AllowNonHDMI3DModes, AllowNonEdidModes, NoEdidHDMI2Check, AllowDpInterlaced"' /etc/X11/xorg.conf 2>/dev/null || true
        [ -n "$MODEL" ] && sed -i "/Section\s\+\"Monitor\"/a\    $MODEL" /etc/X11/xorg.conf 2>/dev/null || true
        grep -q 'AutoAddGPU' /etc/X11/xorg.conf 2>/dev/null || printf 'Section "ServerFlags"\n    Option "AutoAddGPU" "false"\nEndSection\n' >> /etc/X11/xorg.conf
    else
        cp -f /opt/dpadcloud/xorg.conf.template /etc/X11/xorg.conf
        [ -n "$BUSID" ] && sed -i "s/__BUSID__/$BUSID/" /etc/X11/xorg.conf || sed -i 's/__BUSID__/PCI:1:0:0/' /etc/X11/xorg.conf
        sed -i "s/__WIDTH__/$SCREEN_W/g; s/__HEIGHT__/$SCREEN_H/g; s/__DEPTH__/$SCREEN_D/g; s/__MODE__/$MODE_NAME/g" /etc/X11/xorg.conf
        [ -n "$MODEL" ] && sed -i "s|__MODELINE__|$MODEL|" /etc/X11/xorg.conf || sed -i '/__MODELINE__/d' /etc/X11/xorg.conf
    fi
    # Make Xorg pick up the nvidia DDX + libglx from our private ModulePath first
    # (the mesa libglx.so in the default path stays for Xvfb).
    sed -i '/Section "Files"/,/^EndSection/d' /etc/X11/xorg.conf 2>/dev/null
    cat >> /etc/X11/xorg.conf <<'FILES'
Section "Files"
    ModulePath "/usr/lib/xorg/modules/nvidia"
    ModulePath "/usr/lib/xorg/modules"
EndSection
FILES
    echo "    xorg.conf written (busid ${BUSID:-auto}, mode ${MODE_NAME})"
}

X_SERVER=""
if [ "${DPAD_XORG}" = "1" ] && [ -x /usr/bin/Xorg ] && [ -f /usr/lib/xorg/modules/nvidia/drivers/nvidia_drv.so ]; then
    echo "[*] Starting real Xorg + nvidia DDX on ${DISPLAY_NUM} (Vulkan present for DXVK/Proton)..."
    generate_xorg_conf
    # --- Force nvidia's GLX vendor to own screen 0 (fix the
    #     "GLX: Another vendor is already registered for screen 0" -> zink ->
    #     no-stream bug on cuda_max_good>=13.3 Blackwell hosts). ---
    # On 610.x nvidia ships only libglxserver_nvidia.so (no standalone libglx.so),
    # so Mesa's libglx-mesa0 libglx.so self-registers its swrast GLX vendor for
    # screen 0 BEFORE nvidia -> nvidia rejected -> GL falls back to Mesa/zink ->
    # ximagesrc can't capture -> no stream. The Dockerfile bakes
    # xserver-xorg-core's GLVND-neutral libglx.so into this nvidia private
    # ModulePath (listed first by xorg.conf); here we hide Mesa's libglx.so so
    # Xorg loads that neutral dispatcher, which loads only nvidia's vendor ->
    # nvidia wins screen 0. Mesa's libglx.so is restored on the Xvfb fallback.
    NV_GLX_DIR="/usr/lib/xorg/modules/nvidia/extensions"
    MESAGLX="/usr/lib/xorg/modules/extensions/libglx.so"
    if [ -e "${NV_GLX_DIR}/libglx.so" ]; then
        echo "    nvidia GLX dispatcher present -> hiding Mesa's libglx.so so nvidia's GLX vendor wins screen 0"
        if [ -e "$MESAGLX" ] && [ ! -e "${MESAGLX}.mesa-hidden" ]; then
            mv "$MESAGLX" "${MESAGLX}.mesa-hidden" 2>/dev/null || true
        fi
    else
        echo "    WARNING: ${NV_GLX_DIR}/libglx.so missing (Dockerfile GLVND bake failed?) -> Mesa's libglx.so stays; on cuda>=13.3 hosts this breaks the stream (zink). Rebuild the image."
    fi
    # Do NOT set __EGL_VENDOR_LIBRARY_FILENAMES=50_mesa.json here — that Mesa
    # override only exists to stop NVIDIA EGL GBM segfaulting on a virtual
    # framebuffer. On a real nvidia X screen we WANT the NVIDIA GLX/EGL vendor.
    # NOTE: do NOT pass -iglx (indirect GLX) on the nvidia Xorg. With -iglx, Mesa's
    # DRISWRAST AIGLX provider initializes and claims screen 0 first
    # ("GLX: Another vendor is already registered for screen 0") on hosts where
    # the nvidia DDX can't make screen 0 DRI2-capable (e.g. cuda_max_good>=13.3
    # NULL-mode Blackwell hosts). nvidia's GLX vendor is then rejected, GL falls
    # back to Mesa/zink, and Selkies' ximagesrc can't capture -> no stream.
    # Games use direct GLX (DRI3), not indirect, so leaving indirect GLX off (the
    # Xorg 21.1+ default) is safe and fixes the 13.3 no-stream bug.
    /usr/bin/Xorg "${DISPLAY_NUM}" -config /etc/X11/xorg.conf -noreset -novtswitch \
        -sharevts +extension RANDR +extension RENDER +extension GLX +extension XVideo \
        +extension DOUBLE-BUFFER +extension DAMAGE +extension COMPOSITE +extension XTEST \
        -dpms -s off -nolisten tcp -ac -verbose vt7 >/tmp/xorg.log 2>&1 &
    sleep 3
    if pgrep -x Xorg >/dev/null; then
        echo "    Xorg running (nvidia DDX, mode=${DPAD_DISPLAY_MODE})"
        X_SERVER=Xorg
    elif [ "${DPAD_DISPLAY_MODE:-null}" = "dfp" ] && grep -q "Failed to acquire modesetting" /tmp/xorg.log 2>/dev/null; then
        # DFP needs DRM master; if something else holds it (e.g. the VM's own
        # SDDM/desktop X) or we're not --privileged, fall back to NULL-mode Xorg
        # (GPU renders, but CEF/Steam UI needs DFP — use ubuntu_terminal VM
        # template or stop SDDM to get DRM master free for full Steam).
        echo "    DFP Xorg failed (DRM master unavailable — VM's own X holds it, or not --privileged). Falling back to NULL-mode Xorg."
        DPAD_DISPLAY_MODE=null
        generate_xorg_conf
        rm -f /tmp/.X${DISPLAY_NUM#:}-lock /tmp/.X11-unix/X${DISPLAY_NUM#:}
        /usr/bin/Xorg "${DISPLAY_NUM}" -config /etc/X11/xorg.conf -noreset -novtswitch \
            -sharevts +extension RANDR +extension RENDER +extension GLX +extension XVideo \
            +extension DOUBLE-BUFFER +extension DAMAGE +extension COMPOSITE +extension XTEST \
            -dpms -s off -nolisten tcp -ac -verbose vt7 >/tmp/xorg.log 2>&1 &
        sleep 3
        if pgrep -x Xorg >/dev/null; then
            echo "    Xorg running (nvidia DDX, NULL-mode fallback)"
            X_SERVER=Xorg
        else
            echo "    WARNING: NULL-mode Xorg also failed — falling back to Xvfb. /tmp/xorg.log tail:"
            tail -n 20 /tmp/xorg.log 2>/dev/null | sed 's/^/      /'
            rm -f /tmp/.X${DISPLAY_NUM#:}-lock /tmp/.X11-unix/X${DISPLAY_NUM#:}
        fi
    else
        echo "    WARNING: Xorg failed to start — falling back to Xvfb. /tmp/xorg.log tail:"
        tail -n 20 /tmp/xorg.log 2>/dev/null | sed 's/^/      /'
        rm -f /tmp/.X${DISPLAY_NUM#:}-lock /tmp/.X11-unix/X${DISPLAY_NUM#:}
    fi
fi

if [ -z "$X_SERVER" ]; then
    echo "[*] Starting Xvfb on ${DISPLAY_NUM} (software framebuffer — debug/fallback)..."
    export DPAD_XORG=0
    # Restore Mesa's libglx.so for Xvfb if the nvidia path hid it (Xvfb needs
    # Mesa's GLX for software rendering).
    MESAGLX="/usr/lib/xorg/modules/extensions/libglx.so"
    [ -e "${MESAGLX}.mesa-hidden" ] && [ ! -e "$MESAGLX" ] && mv "${MESAGLX}.mesa-hidden" "$MESAGLX" 2>/dev/null || true
    # Force Mesa EGL if the vendor file exists (avoids NVIDIA EGL GBM segfault on a virtual framebuffer)
    if [ -f /usr/share/glvnd/egl_vendor.d/50_mesa.json ]; then
        export __EGL_VENDOR_LIBRARY_FILENAMES=/usr/share/glvnd/egl_vendor.d/50_mesa.json
    fi
    Xvfb "${DISPLAY_NUM}" -screen 0 "${SCREEN_RES}" -dpi 96 \
        +extension COMPOSITE +extension DAMAGE +extension GLX +extension RANDR \
        +extension RENDER +extension MIT-SHM +extension XFIXES +extension XTEST \
        +iglx +render -nolisten tcp -ac -noreset -shmem >/tmp/xvfb.log 2>&1 &
    sleep 2
    pgrep -x Xvfb >/dev/null && { echo "    Xvfb running"; X_SERVER=Xvfb; } || { echo "ERROR: Xvfb failed"; cat /tmp/xvfb.log; }
fi
export DISPLAY="${DISPLAY_NUM}"
wait_sock "/tmp/.X11-unix/X${DISPLAY_NUM#:}" "X display"

# (Resolution is fixed at boot via SCREEN_RESOLUTION; dynamic resize disabled with
#  --enable_resize=false. To support on-the-fly resize, start Xvfb at 8192x4096
#  and add `cvt` + selkies-gstreamer-resize.)

# --- Renderer check ---
# Real Xorg+nvidia: GL goes straight to the GPU — no vglrun needed. We just
#   print the renderer so the boot log shows whether the nvidia DDX bound the GPU.
# Xvfb path: VirtualGL bridges GL onto the GPU's EGL offscreen backend and blits
#   the frame onto Xvfb. VGL does NOT solve Vulkan PRESENT (DXVK/Proton) — that's
#   the whole reason DPAD_XORG=1 is the default for gaming.
export VGL_DISPLAY=egl
export VGL_REFRESHRATE=60
if [ "${X_SERVER}" = "Xorg" ]; then
    VGL_RENDERER="$(as_user "DISPLAY=${DISPLAY_NUM} glxinfo -B 2>/dev/null | grep -m1 'OpenGL renderer string'" || echo 'glxinfo failed')"
    echo "[*] OpenGL renderer (Xorg+nvidia DDX): ${VGL_RENDERER}"
    case "${VGL_RENDERER}" in
        *llvmpipe*|*zink*|*swrast*|*"glxinfo failed"*) echo "    WARNING: Xorg is NOT rendering on the nvidia GPU (got '${VGL_RENDERER}'). On cuda_max_good>=13.3 hosts this is the Mesa/zink GLX-vendor-takes-screen-0 bug — check /tmp/xorg.log for 'Another vendor is already registered for screen 0'. Selkies' ximagesrc can't capture a zink screen -> no stream." ;;
    esac
else
    if command -v vglrun >/dev/null 2>&1; then
        # Unset the Mesa-only EGL vendor override for vglrun ONLY: the entrypoint
        # sets __EGL_VENDOR_LIBRARY_FILENAMES=50_mesa.json so Xvfb doesn't segfault
        # on NVIDIA EGL GBM, but vglrun's EGL backend must reach the NVIDIA EGL
        # vendor to render offscreen on the GPU (else Mesa llvmpipe = CPU).
        VGL_RENDERER=$(as_user "unset __EGL_VENDOR_LIBRARY_FILENAMES; DISPLAY=${DISPLAY_NUM} VGL_DISPLAY=egl vglrun glxinfo -B 2>/dev/null | grep -m1 'OpenGL renderer string'" || echo 'VGL test failed (no GPU renderer)')
        echo "[*] VirtualGL: ${VGL_RENDERER}"
        case "${VGL_RENDERER}" in
            *llvmpipe*|*"VGL test failed"*) echo "    WARNING: VGL is rendering on software (llvmpipe) or failed — GL games will be slow. Check NVIDIA_DRIVER_CAPABILITIES=all and that a GPU is assigned." ;;
        esac
    else
        echo "[*] VirtualGL: vglrun not found (VirtualGL not installed); GL apps will use Mesa llvmpipe (CPU)."
    fi
fi

# --- bubbleroot: proot-based bwrap shim for when user namespaces are unavailable ---
# Steam's pressure-vessel/bwrap (Steam client UI + Proton + runtime-wrapped
# native games) needs unprivileged userns OR a setuid-bwrap with CAP_SYS_ADMIN.
# On Vast neither is available (Vast strips --cap-add SYS_ADMIN, ignores
# --security-opt, host has apparmor_restrict_unprivileged_userns=1). bubbleroot
# emulates bwrap via proot ptrace (no userns/caps/setuid) so Steam can start.
# GPU/Vulkan rendering is NOT emulated - runs natively; only FS/path syscalls
# are intercepted (some loading overhead). DPAD_BUBBLEROOT=auto (default) enables
# it when `unshare -U` fails; =1 forces on; =0 forces off.
DPAD_BUBBLEROOT="${DPAD_BUBBLEROOT:-auto}"
USE_BUBBLEROOT=0
BUBBLEROOT_EXPORTS=""
STEAM_ENV_EXTRAS=""
if [ -x /opt/dpadcloud/bubbleroot ] && { command -v proot >/dev/null 2>&1 || [ -x /usr/local/bin/proot ]; }; then
    case "$DPAD_BUBBLEROOT" in
        1) USE_BUBBLEROOT=1 ;;
        0) USE_BUBBLEROOT=0 ;;
        auto) unshare -U true 2>/dev/null || USE_BUBBLEROOT=1 ;;
    esac
fi
if [ "$USE_BUBBLEROOT" = "1" ]; then
    ln -sf /opt/dpadcloud/bubbleroot /usr/local/bin/bwrap
    export BWRAP=/opt/dpadcloud/bubbleroot
    export PRESSURE_VESSEL_BWRAP=/opt/dpadcloud/bubbleroot
    BUBBLEROOT_EXPORTS=$'export BWRAP=/opt/dpadcloud/bubbleroot
export PRESSURE_VESSEL_BWRAP=/opt/dpadcloud/bubbleroot'
    STEAM_ENV_EXTRAS="BWRAP=/opt/dpadcloud/bubbleroot PRESSURE_VESSEL_BWRAP=/opt/dpadcloud/bubbleroot"
    echo "[*] bubbleroot: ENABLED (user namespaces unavailable - Steam/Proton via proot shim; GPU/Vulkan still native)"
else
    echo "[*] bubbleroot: disabled (user namespaces available or proot/bubbleroot missing)"
fi

# --- Steam autostart (XFCE session) ---
# Drop a Steam.desktop into the XFCE autostart dir so Steam launches when the
# desktop session comes up — same pattern Steam-Headless uses. Under a real
# Xorg+nvidia screen Steam + Proton/DXVK render on the GPU directly (no vglrun);
# under Xvfb (debug) we wrap with vgl-steam so the VGL bridge still applies.
# STEAM_ARGS: on the DFP/full-Steam path we WANT the window visible (no -silent);
# on the NULL/headless path -silent is fine (the Steam UI can't show there anyway
# and the product path is steamcmd + dpad-launch). Set STEAM_ARGS explicitly to
# override (e.g. -tenfoot for Big Picture). Disable autostart with
# DPAD_AUTOSTART_STEAM=0.
if [ -z "${STEAM_ARGS+x}" ]; then
    if [ "${DPAD_DISPLAY_MODE:-null}" = "dfp" ]; then STEAM_ARGS=""; else STEAM_ARGS="-silent"; fi
fi
# --- Launcher selection (DFP/non-gamescope path) ---
# DPAD_LAUNCHER: steam (default, for the Vast KVM VM / RunPod full-Steam path) |
#                heroic (Epic+GOG+Amazon, the Vast Docker storefront path:
#                Electron + --no-sandbox + umu/Proton-direct, NO userns needed) |
#                none (boot a bare desktop for debugging). On Vast Docker set
#                DPAD_LAUNCHER=heroic; Steam is unusable there (no userns ->
#                pressure-vessel/CEF crash). DPAD_GAMESCOPE=1 short-circuits this
#                whole section (gamescope path exit 0's above), so this only
#                governs the Xorg/XFCE/Selkies single-user path.
# Back-compat: DPAD_AUTOSTART_STEAM=0 historically meant "bare desktop". Only
# honour it as "none" when DPAD_LAUNCHER wasn't explicitly set by the user.
if [ -z "${DPAD_LAUNCHER+x}" ]; then
    if [ "${DPAD_AUTOSTART_STEAM:-1}" = "0" ]; then
        DPAD_LAUNCHER="none"
    else
        DPAD_LAUNCHER="steam"
    fi
fi
# --- Heroic: force umu to skip the Steam Runtime container (Vast Docker) ---
# umu (Heroic's Proton wrapper) always wraps games in a pressure-vessel
# (bubblewrap) Steam Runtime container, which needs user namespaces. Vast
# Docker has no userns -> the container breaks game launches (game renders via
# DXVK then exits). umu won't drop the container by design (upstream #40,
# wontfix), but UMU_NO_RUNTIME=1 + PROTONFIXES_DISABLE=1 force umu to skip the
# runtime container + protonfixes and run Proton DIRECTLY on the host — the same
# Proton-direct path dpad-launch PATH B validated on Vast Docker.
#
# The catch: Heroic builds the game-launch environment itself and STRIPS our
# exported UMU_NO_RUNTIME/PROTONFIXES_DISABLE before spawning umu_run.py (the
# env never reaches the umu child). So we wrap umu_run.py itself with a tiny
# Python shim that sets the env, then execs the real umu zipapp. Heroic calls
# `python3 umu_run.py` on every Play, so the wrapper is used automatically.
#
# Heroic downloads umu_run.py into ~/.config/heroic/tools/runtimes/umu/ on first
# use (NOT present at boot), so a background watcher waits for it to appear,
# wraps it (idempotent — skips if already wrapped, detected by the marker), and
# re-checks in case Heroic re-downloads/updates umu. Runs only for the Heroic
# launcher path; harmless for the VM/Steam path (gated on DPAD_LAUNCHER=heroic).
heroic_wrap_umu() {
    local UMU_DIR="${USER_HOME}/.config/heroic/tools/runtimes/umu"
    local UMU="${UMU_DIR}/umu_run.py" REAL="${UMU_DIR}/umu_run.real.py"
    [ -f "${UMU}" ] || return 0
    # Already wrapped? (marker present)
    grep -q 'DPAD_UMU_WRAPPER' "${UMU}" 2>/dev/null && return 0
    # Back up the real umu (kept for inspection/revert; we no longer exec it).
    [ -f "${REAL}" ] || cp -p "${UMU}" "${REAL}"
    cat > "${UMU}" <<'PYEOF'
#!/usr/bin/env python3
# DPAD_UMU_WRAPPER - bypass umu entirely on no-userns hosts (Vast Docker).
# umu ALWAYS wraps games in a pressure-vessel (bubblewrap) Steam Runtime container
# that needs user namespaces, and won't drop it by design (upstream #40). On
# Vast Docker the container crashes or crawls via the bubbleroot/proot shim, and
# umu 1.4.x ignores UMU_NO_RUNTIME=1. So instead of running umu at all, run
# GE-Proton DIRECTLY - the same Proton-direct path dpad-launch PATH B validated on
# Vast Docker (equivalent to Heroic's "Disable umu" = ON). Heroic sets PROTONPATH /
# WINEPREFIX / STEAM_COMPAT_* in this process env and calls us as:
#   python3 umu_run.py <game.exe> [game args...]
# so we exec:  $PROTONPATH/proton waitforexitandrun <game.exe> [game args...]
import os, sys
proton = os.path.join(os.environ["PROTONPATH"], "proton")
os.execv(proton, [proton, "waitforexitandrun"] + sys.argv[1:])
PYEOF
    chown "${USER_NAME}:${USER_NAME}" "${UMU}" "${REAL}" 2>/dev/null || true
    chmod 755 "${UMU}"
    echo "[*] Heroic: wrapped umu_run.py -> Proton-direct (bypass umu/pressure-vessel container; no userns needed)"
}
if [ "${DPAD_LAUNCHER}" = "heroic" ]; then
    # Try once now (umu may already be present from a prior boot/persistent volume).
    heroic_wrap_umu
    # Background watcher: wrap umu_run.py as soon as Heroic downloads it, and
    # re-check every 10s (re-wrap if Heroic updates umu). Low cost; exits never.
    (
        for _ in $(seq 1 30); do   # first ~5 min: check every 10s (first download)
            heroic_wrap_umu
            sleep 10
        done
        while true; do             # then every 60s forever (catch re-downloads)
            heroic_wrap_umu
            sleep 60
        done
    ) &
fi
# A root boot process (Xorg/D-Bus helpers) can create ~/.local (or other XDG
# dirs) root-owned, which makes Steam's `mkdir ~/.local/share/icons` EPERM and
# aborts the install. Re-claim the home dir right before Steam launches.
# Targeted: only chown files NOT already dpad:dpad (avoids the ~4GB/33k overlay
# copy-up of a blanket `chown -R`).
find "${USER_HOME}" ! \( -user "${USER_NAME}" -group "${USER_NAME}" \) -exec chown "${USER_NAME}:${USER_NAME}" {} + 2>/dev/null || true
mkdir -p "${USER_HOME}/.config/autostart"
# --- Build the autostart .desktop + wrapper for the chosen launcher ---
# Steam path: STEAM_EXEC (/usr/bin/steam on Xorg, vgl-steam on Xvfb) + STEAM_ARGS.
# Heroic path: /opt/dpadcloud/heroic-launch (which adds --no-sandbox; the Vast
# Docker no-userns case). "none" leaves a bare desktop (no autostart entry).
rm -f "${USER_HOME}/.config/autostart/Steam.desktop" "${USER_HOME}/.config/autostart/Heroic.desktop"
if [ "${DPAD_LAUNCHER}" = "steam" ] && [ "${DPAD_AUTOSTART_STEAM:-1}" = "1" ]; then
    if [ "${X_SERVER}" = "Xorg" ]; then
        STEAM_EXEC="/usr/bin/steam"
    else
        STEAM_EXEC="/opt/dpadcloud/vgl-steam"
    fi
    # Wrapper so Steam's output is captured to /tmp/steam.log (surfaced in the
    # Vast Logs tab by the periodic dump) — a .desktop Exec can't easily
    # redirect, so we launch Steam through this small script.
    cat > /opt/dpadcloud/steam-autostart <<EOF
#!/bin/bash
${BUBBLEROOT_EXPORTS}
exec ${STEAM_EXEC} ${STEAM_ARGS} >/tmp/steam.log 2>&1
EOF
    chmod +x /opt/dpadcloud/steam-autostart
    cat > "${USER_HOME}/.config/autostart/Steam.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=Steam
Exec=/opt/dpadcloud/steam-autostart
Icon=steam
Terminal=false
X-GNOME-Autostart-enabled=true
EOF
    find "${USER_HOME}/.config/autostart" ! \( -user "${USER_NAME}" -group "${USER_NAME}" \) -exec chown "${USER_NAME}:${USER_NAME}" {} + 2>/dev/null || true
    echo "[*] Steam autostart configured: ${STEAM_EXEC} ${STEAM_ARGS} (direct launch after desktop -> /tmp/steam.log)"
elif [ "${DPAD_LAUNCHER}" = "heroic" ]; then
    # Heroic Games Launcher (Epic+GOG+Amazon). heroic-launch adds --no-sandbox
    # (Electron sandbox needs userns, absent on Vast Docker) and logs to
    # /tmp/heroic.log. Override args via DPAD_HEROIC_ARGS (e.g. "--no-sandbox
    # --no-gui" for an orchestrator-triggered headless game launch, or add a
    # heroic://launch/... URL).
    HEROIC_AUTOSTART_ARGS="${DPAD_HEROIC_ARGS:---no-sandbox}"
    cat > /opt/dpadcloud/heroic-autostart <<EOF
#!/bin/bash
exec /opt/dpadcloud/heroic-launch ${HEROIC_AUTOSTART_ARGS}
EOF
    chmod +x /opt/dpadcloud/heroic-autostart
    cat > "${USER_HOME}/.config/autostart/Heroic.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=Heroic Games Launcher
Exec=/opt/dpadcloud/heroic-autostart
Icon=heroic
Terminal=false
X-GNOME-Autostart-enabled=true
EOF
    find "${USER_HOME}/.config/autostart" ! \( -user "${USER_NAME}" -group "${USER_NAME}" \) -exec chown "${USER_NAME}:${USER_NAME}" {} + 2>/dev/null || true
    echo "[*] Heroic autostart configured: heroic-launch ${HEROIC_AUTOSTART_ARGS} (direct launch after desktop -> /tmp/heroic.log)"
else
    echo "[*] Launcher autostart: disabled (DPAD_LAUNCHER=${DPAD_LAUNCHER})"
fi

# --- XFCE desktop components (light; started as user) ---
# Each component needs DISPLAY, XDG_RUNTIME_DIR, PULSE_SERVER, AND the session
# bus address. Errors go to /tmp/xfce.log (not /dev/null) so a black-screen
# boot is diagnosable from the Vast Logs tab.
echo "[*] Starting XFCE desktop..."
: > /tmp/xfce.log; chown "${USER_NAME}:${USER_NAME}" /tmp/xfce.log
XFCE_ENV="DISPLAY=${DISPLAY_NUM} XDG_RUNTIME_DIR=${XDG_RUNTIME_DIR} PULSE_SERVER=${PULSE_SERVER} DBUS_SESSION_BUS_ADDRESS=${DBUS_SESSION_BUS_ADDRESS}"
as_user "export ${XFCE_ENV}; xfwm4 --compositor=off >>/tmp/xfce.log 2>&1 &" || true
sleep 1
as_user "export ${XFCE_ENV}; xfsettingsd >>/tmp/xfce.log 2>&1 &" || true
as_user "export ${XFCE_ENV}; xfce4-panel >>/tmp/xfce.log 2>&1 &" || true
as_user "export ${XFCE_ENV}; xfdesktop >>/tmp/xfce.log 2>&1 &" || true
sleep 2
echo "    --- XFCE procs ---"
for p in xfwm4 xfsettingsd xfce4-panel xfdesktop; do
    if pgrep -x "$p" >/dev/null; then echo "    $p: running"; else echo "    $p: NOT running (see /tmp/xfce.log)"; fi
done
[ ! -s /tmp/xfce.log ] || { echo "    --- /tmp/xfce.log (tail) ---"; tail -n 15 /tmp/xfce.log | sed 's/^/      /'; }

# --- Launch the chosen launcher directly (we DON'T run xfce4-session, so
# the XFCE autostart .desktop above is never processed). Background it after a
# short delay so the desktop + PulseAudio settle first. Logs to /tmp/steam.log
# or /tmp/heroic.log (both surfaced in the periodic dump).
if [ "${DPAD_LAUNCHER}" = "steam" ] && [ "${DPAD_AUTOSTART_STEAM:-1}" = "1" ] && [ -n "${STEAM_EXEC:-}" ]; then
    (
        sleep 8
        as_user "export DISPLAY=${DISPLAY_NUM} XDG_RUNTIME_DIR=${XDG_RUNTIME_DIR} PULSE_SERVER=${PULSE_SERVER} DBUS_SESSION_BUS_ADDRESS='${DBUS_SESSION_BUS_ADDRESS}' ${STEAM_ENV_EXTRAS}; ${STEAM_EXEC} ${STEAM_ARGS} >/tmp/steam.log 2>&1"
    ) &
    echo "[*] Steam launch scheduled in 8s (${STEAM_EXEC} ${STEAM_ARGS}) -> /tmp/steam.log"
elif [ "${DPAD_LAUNCHER}" = "heroic" ] && command -v heroic >/dev/null 2>&1; then
    HEROIC_DIRECT_ARGS="${DPAD_HEROIC_ARGS:---no-sandbox}"
    (
        sleep 8
        as_user "export DISPLAY=${DISPLAY_NUM} XDG_RUNTIME_DIR=${XDG_RUNTIME_DIR} PULSE_SERVER=${PULSE_SERVER} DBUS_SESSION_BUS_ADDRESS='${DBUS_SESSION_BUS_ADDRESS}'; /opt/dpadcloud/heroic-launch ${HEROIC_DIRECT_ARGS}"
    ) &
    echo "[*] Heroic launch scheduled in 8s (heroic ${HEROIC_DIRECT_ARGS}) -> /tmp/heroic.log"
elif [ "${DPAD_LAUNCHER}" = "heroic" ]; then
    echo "    WARNING: DPAD_LAUNCHER=heroic but heroic not found on PATH — image is stale (Heroic step 4d missing?). Falling back to bare desktop."
fi

# --- Audio (headless null sink; monitor is capturable for silence) ---
# Prefer the pulseaudio daemon when present (its null-sink monitor synthesizes
# capturable silence even when idle - ideal for headless cloud-gaming audio).
# But the pulseaudio daemon is NOT always installed: on noble it can conflict
# with pipewire-pulse (installed by the gamescope step), so the Dockerfile's
# pulseaudio install is best-effort. When pulseaudio is absent, fall back to
# pipewire-pulse (PipeWire's PulseAudio-compatible server, already installed)
# plus a module-null-sink - same capturable-silence behaviour, unified across
# both the DFP and gamescope audio paths.
echo "[*] Starting audio (headless null sink)..."
mkdir -p "${XDG_RUNTIME_DIR}/pulse"
chmod 1777 "${XDG_RUNTIME_DIR}" "${XDG_RUNTIME_DIR}/pulse"
find "${XDG_RUNTIME_DIR}" ! \( -user "${USER_NAME}" -group "${USER_NAME}" \) -exec chown "${USER_NAME}:${USER_NAME}" {} + 2>/dev/null || true
if command -v pulseaudio >/dev/null 2>&1; then
    cat > /tmp/pulse-headless.pa <<EOF
load-module module-native-protocol-unix socket=${XDG_RUNTIME_DIR}/pulse/native auth-anonymous=1
load-module module-null-sink sink_name=dummy sink_properties=device.description="DummyOutput"
load-module module-always-sink
set-default-sink dummy
set-default-source dummy.monitor
EOF
    chown "${USER_NAME}:${USER_NAME}" /tmp/pulse-headless.pa
    # Run as the user (pulseaudio refuses root); unset PULSE_SERVER for the launch
    # itself so --start doesn't refuse to autospawn.
    as_user "unset PULSE_SERVER; export XDG_RUNTIME_DIR=${XDG_RUNTIME_DIR}; pulseaudio --start --log-target=stderr --disallow-exit --exit-idle-time=-1 -n -F /tmp/pulse-headless.pa" >/tmp/pulse.log 2>&1 || echo "    WARNING: pulseaudio start failed (see /tmp/pulse.log)"
    wait_sock "${XDG_RUNTIME_DIR}/pulse/native" "pulseaudio"
else
    echo "    pulseaudio daemon not installed - using pipewire-pulse (PipeWire PulseAudio compat)"
    : > /tmp/pipewire.log; : > /tmp/wireplumber.log; : > /tmp/pipewire-pulse.log
    chown "${USER_NAME}:${USER_NAME}" /tmp/pipewire.log /tmp/wireplumber.log /tmp/pipewire-pulse.log 2>/dev/null || true
    as_user "export XDG_RUNTIME_DIR=${XDG_RUNTIME_DIR} DBUS_SESSION_BUS_ADDRESS='${DBUS_SESSION_BUS_ADDRESS}' HOME=${USER_HOME}; pipewire >>/tmp/pipewire.log 2>&1 & sleep 1; wireplumber >>/tmp/wireplumber.log 2>&1 &"
    as_user "export XDG_RUNTIME_DIR=${XDG_RUNTIME_DIR} DBUS_SESSION_BUS_ADDRESS='${DBUS_SESSION_BUS_ADDRESS}' HOME=${USER_HOME}; pipewire-pulse >>/tmp/pipewire-pulse.log 2>&1 &"
    wait_sock "${XDG_RUNTIME_DIR}/pulse/native" "pipewire-pulse"
    # module-null-sink is supported by pipewire-pulse; gives a default sink + a
    # capturable .monitor source (same shape as the pulseaudio daemon path).
    if [ -S "${XDG_RUNTIME_DIR}/pulse/native" ]; then
        as_user "export PULSE_SERVER=unix:${XDG_RUNTIME_DIR}/pulse/native XDG_RUNTIME_DIR=${XDG_RUNTIME_DIR}; pactl load-module module-null-sink sink_name=dummy sink_properties=device.description=DummyOutput 2>/dev/null; pactl set-default-sink dummy 2>/dev/null; pactl set-default-source dummy.monitor 2>/dev/null" >/dev/null 2>&1 || true
    fi
fi
if [ -S "${XDG_RUNTIME_DIR}/pulse/native" ]; then
    echo "    Audio socket OK (${PULSE_SERVER})"
    echo "    --- sinks ---";  as_user "export PULSE_SERVER=${PULSE_SERVER} XDG_RUNTIME_DIR=${XDG_RUNTIME_DIR}; pactl list short sinks 2>/dev/null"
    echo "    --- sources ---"; as_user "export PULSE_SERVER=${PULSE_SERVER} XDG_RUNTIME_DIR=${XDG_RUNTIME_DIR}; pactl list short sources 2>/dev/null"
else
    echo "    Audio socket MISSING:"
    tail -n 20 /tmp/pulse.log 2>/dev/null || true
    [ -f /tmp/pipewire-pulse.log ] && { echo "    --- /tmp/pipewire-pulse.log (tail) ---"; tail -n 20 /tmp/pipewire-pulse.log | sed 's/^/      /'; }
    [ -f /tmp/pipewire.log ] && { echo "    --- /tmp/pipewire.log (tail) ---"; tail -n 15 /tmp/pipewire.log | sed 's/^/      /'; }
fi

# --- coturn (in-image TURN; Selkies WebRTC media relays through it) ---
echo "[*] Starting coturn on ${TURN_PORT_EXT}..."
if [ -n "${TURN_SERVER:-}" ]; then
    echo "    External TURN_SERVER configured — skipping local coturn"
else
    turnserver -n -a --log-file=/tmp/coturn.log --lt-cred-mech --fingerprint \
        --no-stun --no-multicast-peers --no-cli --no-tlsv1 --no-tlsv1_1 \
        --listening-ip=0.0.0.0 --listening-ip=:: \
        --realm="dpadcloud" --user="${TURN_USER}:${TURN_PASS}" \
        -p "${TURN_PORT_LISTEN:-${TURN_PORT_EXT}}" -X "${PUBLIC_IP:-localhost}" >/tmp/coturn.log 2>&1 &
    sleep 2
    pgrep -x turnserver >/dev/null && echo "    coturn running" || echo "    WARNING: coturn failed (see /tmp/coturn.log)"
fi

# --- NVENC multi-GPU topology + flexgrip auto-enable (nvidia-container-toolkit #1249) ---
# On driver >=570, NVENC's GET_ATTACHED_IDS returns ALL host GPUs; it then
# peer-inits with the ones whose /dev/nvidiaX aren't mounted and bails with
# NV_ENC_ERR_UNSUPPORTED_DEVICE. The flexgrip interposer filters that list to
# only mounted GPUs. We auto-enable it when the topology shows we have a SLICE
# of a multi-GPU host (host GPU count > mounted /dev/nvidiaX count) on a
# 570..609 driver. Override with DPAD_NVENC_FIX=1|0|auto. This runs before
# Sunshine AND the Selkies encoder probe so both inherit the LD_PRELOAD.
echo "    --- NVENC topology (#1249 check) ---"
DRIVER_MAJOR="$(nvidia-smi --query-gpu=driver_version --format=csv,noheader 2>/dev/null | head -1 | cut -d. -f1)"
HOST_GPU_COUNT="$(find /proc/driver/nvidia/gpus -mindepth 1 -maxdepth 1 -type d 2>/dev/null | wc -l)"
MOUNTED_GPU_COUNT="$(ls /dev/nvidia[0-9] 2>/dev/null | wc -l)"
# nvidia-smi-visible GPUs = the ones this container can actually use (CUDA/NVENC).
# On some Vast hosts (NVIDIA_VISIBLE_DEVICES=void) /dev/nvidiaX nodes are mounted
# for GPUs the container CAN'T use, so the mounted count overcounts. nvidia-smi
# only enumerates the usable ones, so we build a minor-bitmask from it and hand it
# to the interposer (NVENC_FIX_AVAILABLE) so it filters GET_ATTACHED_IDS correctly.
VISIBLE_GPU_COUNT="$(nvidia-smi -L 2>/dev/null | grep -c '^GPU ')"
# Bitmask of the minors this container can actually use (nvidia-smi-visible GPUs).
# Primary: map each visible GPU's PCI bus (nvidia-smi pci.bus_id) -> /proc Device
# Minor — correct even when Vast mounts /dev/nvidiaX for GPUs we can't use (mining
# rigs) and the assigned GPU isn't at minor 0.
# Fallback: nvidia-smi "index" = minor (the standard toolkit renumbering), used if
# the PCI-bus query returns nothing or doesn't match (its format varies by driver).
VISIBLE_BITMASK=0
while IFS= read -r busid; do
    [ -z "$busid" ] && continue
    key="${busid#*:}"                       # "00000000:2b:00.0" -> "2b:00.0"
    key="${key,,}"   # nvidia-smi UPPERCASE hex vs /proc lowercase — case-insensitive compare (slots with hex letters)
    for d in /proc/driver/nvidia/gpus/*; do
        [ -d "$d" ] || continue
        pkey="$(basename "$d")"; pkey="${pkey#*:}"   # "0000:2b:00.0" -> "2b:00.0"
        pkey="${pkey,,}"
        if [ "$pkey" = "$key" ]; then
            minor="$(grep -oP 'Device Minor:\s*\K[0-9]+' "$d/information" 2>/dev/null)"
            [ -n "$minor" ] && VISIBLE_BITMASK=$(( VISIBLE_BITMASK | (1 << minor) ))
            break
        fi
    done
done < <(nvidia-smi --query-gpu=pci.bus_id --format=csv,noheader 2>/dev/null)
# Fallback: index -> minor if the PCI-bus mapping came up empty.
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
        # Enable when the container can't use ALL host GPUs: either a slice
        # (host>mounted) or mounted-but-inaccessible GPUs (visible<mounted, which
        # happens with NVIDIA_VISIBLE_DEVICES=void on Vast). driver 570..609.
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

# Joystick interposer (gamepad) + conditional flexgrip NVENC fix — assembled
# here so Sunshine, the Selkies encoder probe, and Selkies itself all inherit it.
export SELKIES_INTERPOSER='/usr/$LIB/selkies_joystick_interposer.so'
DPAD_PRELOAD=""
[ "$NVENC_FIX_ENABLED" = "1" ] && DPAD_PRELOAD="/opt/dpadcloud/libnvenc_fix.so"
export LD_PRELOAD="${DPAD_PRELOAD}${DPAD_PRELOAD:+:}${SELKIES_INTERPOSER}${LD_PRELOAD:+:${LD_PRELOAD}}"
mkdir -pm1777 /dev/input 2>/dev/null && touch /dev/input/js0 2>/dev/null && chmod 777 /dev/input/js* 2>/dev/null || true
# /dev/uinput — Sunshine creates the virtual keyboard/mouse/touch devices here
# when a stream starts. Without it Sunshine warns "Unable to create virtual
# touch screen/pen tablet" and segfaults on input injection. Create the char
# device (major 10, minor 223) world-writable so the desktop user can use it.
if [ ! -e /dev/uinput ]; then
    mknod /dev/uinput c 10 223 2>/dev/null || true
fi
chmod 666 /dev/uinput 2>/dev/null || true

# (Sunshine / mws / native Moonlight removed — Selkies is the only browser stream.)

# --- Selkies-GStreamer (browser WebRTC streaming, bound to localhost) ---
echo "[*] Starting Selkies-GStreamer..."
# On RunPod, re-resolve the TURN external port + public IP now (~60s in): the
# portMappings/publicIp are reliably populated by this point (they're often
# empty at boot T=0). Idempotent — overrides / prior resolution short-circuit it.
runpod_resolve_turn
[ -f /opt/gstreamer/gst-env ] && . /opt/gstreamer/gst-env

# Force a FRESH GStreamer registry at runtime. A registry baked during
# `docker build` (no NVIDIA driver mounted) marks the NVENC plugin
# (nvh264enc, which dlopens the host's libnvidia-encode.so.1 at scan time) as
# unloadable — and gst-inspect-1.0 never re-tries a plugin it already failed to
# load. Deleting the registry file forces a full rescan now, with the driver
# present, so NVENC is discovered. (This was masked on some hosts and not
# others → the x264enc fallback.)
rm -f "${GST_REGISTRY:-/root/.cache/gstreamer-1.0/registry.bin}" \
      /root/.cache/gstreamer-1.0/registry.* \
      "${USER_HOME}/.cache/gstreamer-1.0/registry."* 2>/dev/null || true
GST_REGISTRY_UPDATE=1 gst-inspect-1.0 -a >/dev/null 2>&1 || true

# Encoder: runtime 1-frame test (nvh264enc if CUDA/NVENC work, else x264enc).
# IMPORTANT — probe the element Selkies ACTUALLY instantiates, not the literal
# name. Selkies' pipeline builder (gstwebrtc_app.py) maps `--encoder=nvh264enc` →
# `nvcudah264enc` (the MODERN nvcodec element, P1–P7 presets + NV_ENC_TUNING_INFO)
# on GStreamer 1.21–1.24, and `--encoder=nvh265enc` → `nvcudah265enc`. The legacy
# `nvh264enc` element uses the OLD NVENC preset GUIDs that NVIDIA REMOVED in
# driver 590+ → "Selected preset not supported" on e.g. RTX 3090/driver-595.
# Probing the literal `nvh264enc` would false-negative on those hosts and fall
# back to x264enc even though Selkies would have used the working modern element.
# So we probe `nvcudah264enc` on 1.21–1.24 (else `nvh264enc`) but report/select
# the Selkies-facing name `nvh264enc`, which Selkies then re-maps internally.
GST_MINOR=$(gst-launch-1.0 --version 2>/dev/null | awk 'NR==1{print $3}' | cut -d. -f2)
actual_nvenc() {
    case "$1" in
        nvh264enc) if [ "${GST_MINOR:-0}" -gt 20 ] && [ "${GST_MINOR:-0}" -le 24 ]; then echo "nvcudah264enc"; else echo "nvh264enc"; fi ;;
        nvh265enc) if [ "${GST_MINOR:-0}" -gt 20 ] && [ "${GST_MINOR:-0}" -le 24 ]; then echo "nvcudah265enc"; else echo "nvh265enc"; fi ;;
        *) echo "$1" ;;
    esac
}
# nv* encoders pair with `cudaupload ! cudaconvert` (cudaconvert's sink needs
# CUDA memory, so cudaupload MUST precede it — without it `videotestsrc !
# cudaconvert` can't link → false negative). va* use `vapostproc`, software
# encoders use `videoconvert`. On failure we capture the GStreamer error
# (NVRTC arch vs NVENC preset vs #1249 open-session) so the boot log shows the
# real root cause — not just "FAILED".
chain_for() {
    case "$1" in
        nvh264enc|nvh265enc|nvav1enc) echo "videoconvert ! cudaupload ! cudaconvert" ;;
        vah264enc|vah265enc|vavp9enc|vaav1enc) echo "videoconvert ! vapostproc" ;;
        *) echo "videoconvert" ;;
    esac
}
SELKIES_ENC="${SELKIES_ENCODER:-}"
if [ -z "$SELKIES_ENC" ]; then
    for cand in nvh264enc nvh265enc x264enc vp8enc openh264enc; do
        test_enc="$(actual_nvenc "$cand")"
        if ! gst-inspect-1.0 "$test_enc" >/dev/null 2>&1; then
            echo "    gst $cand ($test_enc): element NOT FOUND (plugin not registered)"
            continue
        fi
        chain="$(chain_for "$cand")"
        # cudaupload/cudaconvert/vapostproc may be absent on non-NVIDIA/non-VA
        # hosts; fall back to a bare videoconvert so we still exercise the
        # encoder itself (nvcuda*h264enc also accepts sysmem via internal upload).
        case "$cand" in
            nvh264enc|nvh265enc|nvav1enc)
                { gst-inspect-1.0 cudaupload >/dev/null 2>&1 && gst-inspect-1.0 cudaconvert >/dev/null 2>&1; } || chain="videoconvert" ;;
            vah264enc|vah265enc|vavp9enc|vaav1enc)
                gst-inspect-1.0 vapostproc >/dev/null 2>&1 || chain="videoconvert" ;;
        esac
        errlog="/tmp/gst-probe-${cand}.log"
        # $chain is intentionally unquoted: it contains ` ! ` separators that
        # gst-launch needs as separate argv tokens (history expansion is off
        # in a script, so `!` is literal here).
        if gst-launch-1.0 --quiet videotestsrc num-buffers=1 ! $chain ! "$test_enc" ! fakesink >"$errlog" 2>&1; then
            echo "    gst $cand: OK (via $chain → $test_enc)"; SELKIES_ENC="$cand"; break
        else
            echo "    gst $cand: present but encode FAILED (via $chain → $test_enc) — skipping"
            grep -iE 'ERROR|nvrtc|nvenc|preset|unsupported device|architecture|could not (link|open|create|initialize|load)' "$errlog" 2>/dev/null | sed 's/^/      /' | head -10
            echo "      (full log: $errlog)"
        fi
    done
fi
[ -z "$SELKIES_ENC" ] && SELKIES_ENC="x264enc"
echo "    Selected encoder: ${SELKIES_ENC}"

# --- NVENC/CUDA diagnostic (shows why NVENC may be unavailable on a host) ---
# NVENC needs libcuda (compute cap) AND libnvidia-encode (encode cap) mounted from
# the host. nvidia-smi only needs utility/compute, so a host can show a GPU yet
# still lack encode. Print what's actually present so we can see the difference
# between hosts where nvh264enc works and hosts where it fails with error code 2.
echo "    --- NVENC/CUDA diag ---"
echo "    driver: $(nvidia-smi --query-gpu=driver_version --format=csv,noheader 2>/dev/null | head -1)"
echo "    NVIDIA_VISIBLE_DEVICES=${NVIDIA_VISIBLE_DEVICES:-<unset, Vast-assigned>}"
echo "    visible GPUs:"; nvidia-smi -L 2>/dev/null | sed 's/^/      /' || echo "      nvidia-smi -L failed"
for lib in /usr/lib/x86_64-linux-gnu/libcuda.so.1 /usr/lib/x86_64-linux-gnu/libnvidia-encode.so.1; do
    [ -e "$lib" ] && echo "    present: $lib" || echo "    MISSING: $lib"
done
echo "    --- VGL graphics libs ---"
for lib in /usr/lib/x86_64-linux-gnu/libGL.so.1 /usr/lib/x86_64-linux-gnu/libEGL.so.1 /usr/lib/x86_64-linux-gnu/libvulkan.so.1; do
    [ -e "$lib" ] && echo "    present: $lib" || echo "    MISSING: $lib"
done
echo "    Vulkan ICDs:"; ls /usr/share/vulkan/icd.d/*.json 2>/dev/null | sed 's/^/      /' || echo "      none in-image (NVIDIA ICD is host-mounted at runtime)"
ls /dev/nvidia* 2>/dev/null | sed 's/^/    dev: /' || echo "    no /dev/nvidia* devices mounted"
. /opt/gstreamer/gst-env 2>/dev/null
echo "    cuInit: $(python3 -c 'import ctypes; print(ctypes.CDLL("libcuda.so.1").cuInit(0))' 2>&1 | tail -1)"
echo "    compute_mode: $(nvidia-smi --query-gpu=compute_mode --format=csv,noheader 2>/dev/null | head -1)"
cat > /tmp/cudactx.py <<'PY'
import ctypes
c=ctypes.CDLL("libcuda.so.1")
print("cuInit=",c.cuInit(0))
n=ctypes.c_int(); c.cuDeviceGetCount(ctypes.byref(n))
d=ctypes.c_int(); c.cuDeviceGet(ctypes.byref(d),0)
x=ctypes.c_void_p()
try: r=c.cuCtxCreate_v2(ctypes.byref(x),0,d.value)
except AttributeError: r=c.cuCtxCreate(ctypes.byref(x),0,d.value)
print("cuCtxCreate=",r, "dev=",d.value)
PY
echo "    $(python3 /tmp/cudactx.py 2>&1 | tail -1)"

# Ensure the GStreamer registry cache dir is user-writable (else Selkies logs
# 'registry update failed: Permission denied' on /home/dpad/.cache/gstreamer-1.0).
mkdir -p "${USER_HOME}/.cache/gstreamer-1.0"
find "${USER_HOME}/.cache" ! \( -user "${USER_NAME}" -group "${USER_NAME}" \) -exec chown "${USER_NAME}:${USER_NAME}" {} + 2>/dev/null || true
rm -rf "${USER_HOME}/.cache/gstreamer-1.0"/* 2>/dev/null || true

# (Joystick interposer + flexgrip LD_PRELOAD were assembled earlier, before
# Sunshine, so both Sunshine and the Selkies encoder probe run under them.)

# coturn is exposed TCP-only on Vast (the 73478 tag) — UDP TURN would need a
# relay port range that blows Vast's 64-port limit. TCP TURN relays over the
# single listening connection. Override with SELKIES_TURN_PROTOCOL only if you
# also expose a UDP relay range.
SELKIES_TURN_PROTOCOL="${SELKIES_TURN_PROTOCOL:-tcp}"

# --- dual-ICE TURN config (any provider with a public IP: RunPod + Vast) -----
# On RunPod AND Vast Docker, the container can't reach its own public IP:port
# (no NAT loopback/hairpin), so Selkies (in-container) can't gather a relay candidate
# if --turn_host points at the public address. Fix: give BOTH peers a TURN server
# they can each reach, both landing on the SAME coturn (which short-circuits the
# media internally over the two control connections, so only the listening port
# needs to be exposed):
#   - Selkies (in-container)  -> turn:127.0.0.1:3478   (local, always works)
#   - browser (on the internet) -> turn:<publicIp>:<externalPort> (RunPod/Vast TCP map)
# We write an rtc_config.json with BOTH iceServers and pass it via --rtc_config_json
# (which Selkies serves to the browser AND uses for its own peer). Two entries:
#   - in-container peer  -> turn:127.0.0.1:<listen>   (coturn is in this container; always works, no NAT hairpin needed)
#   - browser (internet)  -> turn:<publicIp>:<ext>     (browser reaches coturn directly — NO SSH tunnel required)
# This fires whenever we have a REAL public IP (auto-resolved from PUBLIC_IPADDR
# on Vast, or RUNPOD_PUBLIC_IP on RunPod) — on ANY provider, not just RunPod
# (Vast Docker has the same no-hairpin problem). Setting DPAD_TURN_PUBLIC_IP=127.0.0.1
# keeps the old single-entry tunnel-mode for local debugging.
SELKIES_RTC_CONFIG=""
if [ -n "${PUBLIC_IP:-}" ] && [ "${PUBLIC_IP:-}" != "127.0.0.1" ]; then
    SELKIES_RTC_CONFIG="/opt/dpadcloud/rtc_config.json"
    cat > "$SELKIES_RTC_CONFIG" <<EOF
{"iceServers":[{"urls":["turn:127.0.0.1:${TURN_PORT_LISTEN}?transport=${SELKIES_TURN_PROTOCOL}"],"username":"${TURN_USER}","credential":"${TURN_PASS}"},{"urls":["turn:${PUBLIC_IP}:${TURN_PORT_EXT}?transport=${SELKIES_TURN_PROTOCOL}"],"username":"${TURN_USER}","credential":"${TURN_PASS}"}],"iceTransportPolicy":"all"}
EOF
    chown root:root "$SELKIES_RTC_CONFIG"; chmod 644 "$SELKIES_RTC_CONFIG"   # trusted: root-owned, not group/world-writable
    echo "[*] dual-ICE rtc_config.json written ($SELKIES_RTC_CONFIG): local 127.0.0.1:${TURN_PORT_LISTEN} + public ${PUBLIC_IP}:${TURN_PORT_EXT}"
fi

if [ -n "$SELKIES_RTC_CONFIG" ]; then
    as_user "export DISPLAY=${DISPLAY_NUM} XDG_RUNTIME_DIR=${XDG_RUNTIME_DIR} PULSE_SERVER=${PULSE_SERVER} PIPEWIRE_LATENCY=${PIPEWIRE_LATENCY} GST_DEBUG=${GST_DEBUG} LD_PRELOAD='${LD_PRELOAD}' SDL_JOYSTICK_DEVICE=/dev/input/js0 SELKIES_INTERPOSER='${SELKIES_INTERPOSER}'; . /opt/gstreamer/gst-env; selkies-gstreamer --addr=127.0.0.1 --port=16100 --enable_https=false --encoder=${SELKIES_ENC} --enable_basic_auth=true --basic_auth_user='${SELKIES_USER}' --basic_auth_password='${SELKIES_PASS}' --enable_resize=false --rtc_config_json='${SELKIES_RTC_CONFIG}' --web_root=${SELKIES_WEB_ROOT}" >/tmp/selkies.log 2>&1 &
else
    as_user "export DISPLAY=${DISPLAY_NUM} XDG_RUNTIME_DIR=${XDG_RUNTIME_DIR} PULSE_SERVER=${PULSE_SERVER} PIPEWIRE_LATENCY=${PIPEWIRE_LATENCY} GST_DEBUG=${GST_DEBUG} LD_PRELOAD='${LD_PRELOAD}' SDL_JOYSTICK_DEVICE=/dev/input/js0 SELKIES_INTERPOSER='${SELKIES_INTERPOSER}'; . /opt/gstreamer/gst-env; selkies-gstreamer --addr=127.0.0.1 --port=16100 --enable_https=false --encoder=${SELKIES_ENC} --enable_basic_auth=true --basic_auth_user='${SELKIES_USER}' --basic_auth_password='${SELKIES_PASS}' --enable_resize=false --turn_host='${PUBLIC_IP:-127.0.0.1}' --turn_port=${TURN_PORT_EXT} --turn_protocol=${SELKIES_TURN_PROTOCOL} --turn_username='${TURN_USER}' --turn_password='${TURN_PASS}' --web_root=${SELKIES_WEB_ROOT}" >/tmp/selkies.log 2>&1 &
fi
sleep 4
pgrep -f "selkies-gstreamer" >/dev/null && echo "    Selkies running on 127.0.0.1:16100 (encoder=${SELKIES_ENC})" || { echo "    WARNING: selkies failed (see /tmp/selkies.log)"; tail -n 30 /tmp/selkies.log; }

# (mws + mws-autopair removed — Selkies is the only browser stream.)

# --- cloudflared (HTTPS tunnel for Selkies) ---
# Selkies (:16100) gets an HTTPS tunnel so the secure-context gaming APIs
# (gamepad, WebCodecs, keyboard lock) work with no inbound port. Production:
# a named tunnel — pass CLOUDFLARED_TUNNEL_TOKEN + CLOUDFLARED_HOSTNAME.
# MVP: a quick trycloudflare.com URL (one cloudflared process).
start_quick_tunnel() {
  local local_url="$1" logfile="$2"
  cloudflared tunnel --no-autoupdate --url "$local_url" >"$logfile" 2>&1 &
  sleep 8
  grep -oE 'https://[a-z0-9.-]+trycloudflare\.com' "$logfile" 2>/dev/null | head -1
}
SELKIES_URL=""
if [ -n "${CLOUDFLARED_TUNNEL_TOKEN:-}" ]; then
    echo "[*] Starting cloudflared named tunnel (-> Selkies :16100)..."
    cloudflared tunnel --no-autoupdate run --token "${CLOUDFLARED_TUNNEL_TOKEN}" >/tmp/cloudflared.log 2>&1 &
    SELKIES_URL="${CLOUDFLARED_HOSTNAME:-https://<your-tunnel-hostname>}"
    echo "    Selkies tunnel URL: ${SELKIES_URL}"
elif command -v cloudflared >/dev/null 2>&1; then
    echo "[*] Starting cloudflared quick tunnel (Selkies :16100)..."
    SELKIES_URL="$(start_quick_tunnel http://localhost:16100 /tmp/cloudflared-selkies.log)"
    [ -n "$SELKIES_URL" ] && echo "    Selkies tunnel URL: ${SELKIES_URL}" || { echo "    Selkies tunnel URL not captured (see /tmp/cloudflared-selkies.log):"; tail -n 15 /tmp/cloudflared-selkies.log; }
fi

# (Tailscale / native Moonlight removed — Selkies is the only stream.)

# --- Status ---
IP="$(hostname -I 2>/dev/null | awk '{print $1}')"
echo ""
echo "=========================================="
echo "  DpadCloud Container READY!"
echo "=========================================="
echo "  Display:          ${DISPLAY_NUM} @ ${SCREEN_RES}  (${X_SERVER:-?}$( [ "${X_SERVER}" = Xorg ] && echo "+nvidia DDX" ))"
echo "  Encoder:           ${SELKIES_ENC}"
[ -n "$PUBLIC_IP" ] && echo "  Public IP:        ${PUBLIC_IP}"
echo ""
echo "  ▶ Browser click-and-play (Selkies):"
if [ -n "$SELKIES_URL" ]; then
    echo "      ${SELKIES_URL}"
    echo "      Login: ${SELKIES_USER} / ${SELKIES_PASS}"
else
    echo "      (no tunnel — Selkies quick-tunnel failed)"
    echo "      Local fallback: http://localhost:16100  (Login: ${SELKIES_USER} / ${SELKIES_PASS})"
fi
echo ""
echo "  TURN (WebRTC media relay): ${PUBLIC_IP:-<ip>}:${TURN_PORT_EXT}  (${SELKIES_TURN_PROTOCOL}, ${TURN_USER}/<token>)"
echo ""
echo "  ▶ GPU-accelerated gaming (X server: ${X_SERVER:-?}, launcher=${DPAD_LAUNCHER}):"
if [ "${X_SERVER}" = "Xorg" ]; then
    if [ "${DPAD_LAUNCHER}" = "heroic" ]; then
        echo "      Heroic auto-starts on login (Epic+GOG+Amazon, --no-sandbox) -> /tmp/heroic.log"
        echo "      Windows games via umu/Proton-direct (no pressure-vessel, no userns);"
        echo "      native Linux games run directly. Wine Manager: Proton-GE/Wine-GE."
    else
        echo "      Steam auto-starts on login (${STEAM_ARGS}) — native Linux + Proton/DXVK"
    fi
    echo "      render directly on the GPU (real Vulkan present surface)."
    echo "      Manual: vgl-steam | steam steam://rungameid/<appid>"
else
    echo "      Xvfb debug path — VirtualGL bridges native GL to the GPU (VGL_DISPLAY=${VGL_DISPLAY:-egl}):"
    echo "        vgl-test                     # sanity check (renderer + glxgears)"
    echo "        vgl-steam                    # native Linux GL titles on the GPU"
    echo "        proton-wined3d               # Windows DX9–11 via WineD3D+VGL"
    echo "        proton-wined3d <appid>       # specific Windows game"
    echo "      (DX12 / true DXVK need the real Xorg path — DPAD_XORG=1)"
fi
echo "=========================================="

# --- Periodic Selkies log dump (no SSH on Vast — stream to Logs tab) ---
(
    sleep 25
    while true; do
        echo ""
        echo "=== /tmp/selkies.log (WebRTC, no nvenc_fix) ==="
        grep -v "nvenc_fix" /tmp/selkies.log 2>/dev/null | tail -n 100 || true
        echo "=== end selkies.log ==="
        echo "=== /tmp/selkies.log (nvenc_fix poll count) ==="
        echo "nvenc_fix lines: $(grep -c nvenc_fix /tmp/selkies.log 2>/dev/null || echo 0)"
        echo "=== /tmp/rtc_config.json ==="
        cat /tmp/rtc_config.json 2>/dev/null || true
        echo "=== end rtc_config.json ==="
        echo "=== coturn listen (ss) + /tmp/coturn.log (tail) ==="
        ss -lntp 2>/dev/null | grep -iE "turnserver|3478" || true
        tail -n 40 /tmp/coturn.log 2>/dev/null || true
        echo "=== end coturn ==="
        echo "=== /tmp/pulse.log (tail) ==="
        tail -n 30 /tmp/pulse.log 2>/dev/null || true
        echo "=== end pulse.log ==="
        echo "=== /tmp/pipewire-pulse.log (tail) ==="
        tail -n 30 /tmp/pipewire-pulse.log 2>/dev/null || true
        echo "=== end pipewire-pulse.log ==="
        echo "=== /tmp/pipewire.log (tail) ==="
        tail -n 20 /tmp/pipewire.log 2>/dev/null || true
        echo "=== end pipewire.log ==="
        echo "=== /tmp/xfce.log (tail) ==="
        tail -n 30 /tmp/xfce.log 2>/dev/null || true
        echo "=== end xfce.log ==="
        echo "=== /tmp/xorg.log (tail) ==="
        tail -n 60 /tmp/xorg.log 2>/dev/null || true
        echo "=== end xorg.log ==="
        echo "=== /tmp/steam.log (tail) ==="
        tail -n 60 /tmp/steam.log 2>/dev/null || true
        echo "=== end steam.log ==="
        echo "=== /tmp/heroic.log (tail) ==="
        tail -n 60 /tmp/heroic.log 2>/dev/null || true
        echo "=== end heroic.log ==="
        echo "=== steam procs ==="
        pgrep -af steam 2>/dev/null | head -n 10 || echo "      (no steam process)"
        echo "=== /tmp/gst-probe-*.log (encoder probe errors) ==="
        for f in /tmp/gst-probe-*.log; do [ -f "$f" ] || continue; echo "--- $f ---"; tail -n 25 "$f" 2>/dev/null; done
        echo "=== end gst-probe logs ==="
        sleep 30
    done
) &

# --- Health loop ---
while true; do
    sleep 30
    if [ "${X_SERVER}" = "Xorg" ]; then
        pgrep -x Xorg >/dev/null || { echo "WARNING: Xorg died, restarting"; rm -f /tmp/.X${DISPLAY_NUM#:}-lock /tmp/.X11-unix/X${DISPLAY_NUM#:}; /usr/bin/Xorg "${DISPLAY_NUM}" -config /etc/X11/xorg.conf -noreset -novtswitch -sharevts +extension RANDR +extension RENDER +extension GLX +extension XVideo +extension DAMAGE +extension COMPOSITE +extension XTEST -dpms -s off -nolisten tcp -ac -verbose vt7 >/tmp/xorg.log 2>&1 & }
    else
        pgrep -x Xvfb >/dev/null || { echo "WARNING: Xvfb died, restarting"; Xvfb "${DISPLAY_NUM}" -screen 0 "${SCREEN_RES}" -dpi 96 +extension GLX +extension RANDR +extension RENDER -ac -noreset -shmem & }
    fi
    pgrep -f "selkies-gstreamer" >/dev/null || echo "WARNING: selkies not running (see /tmp/selkies.log)"
done