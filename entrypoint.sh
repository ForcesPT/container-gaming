#!/bin/bash
# =============================================================================
# DpadCloud Gaming Container Entrypoint (Ubuntu 24.04)
# Boot order:
#   dbus -> Xvfb -> XFCE -> PulseAudio(null-sink) -> coturn
#        -> NVENC topology + flexgrip LD_PRELOAD
#        -> Sunshine (NVENC host; encoder for BOTH mws and native Moonlight)
#        -> Selkies-GStreamer (127.0.0.1:16100, TURN=coturn) [browser fallback]
#        -> moonlight-web-stream (0.0.0.0:8080, Sunshine NVENC) [browser primary]
#        -> cloudflared (HTTPS tunnels: mws + Selkies) -> Tailscale (native Moonlight)
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
TURN_PORT_EXT="${VAST_UDP_PORT_73478:-${VAST_TCP_PORT_73478:-3478}}"

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
chown -R "${USER_NAME}:${USER_NAME}" "${XDG_RUNTIME_DIR}"

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
        local NVXCFG_ARGS=(--virtual="${SCREEN_W}x${SCREEN_H}" --depth="$SCREEN_D" \
            --mode="$MODE_NAME" --allow-empty-initial-configuration --no-probe-all-gpus \
            --only-one-x-screen --no-sli --no-base-mosaic \
            --use-display-device=None --connected-monitor=None)
        # NOTE: NULL/NoScanout mode (UseDisplayDevice=None) is REQUIRED on Vast:
        # Vast strips --cap-add SYS_ADMIN, so we CANNOT become DRM master, which
        # the DFP/virtual-monitor path needs ("Failed to acquire modesetting
        # permission"). NULL mode runs the nvidia DDX WITHOUT KMS, so Xorg comes
        # up and GL/Vulkan render on the GPU. Capture is via XGetImage on the root
        # window (backing store enabled) -- works for Selkies. Vulkan present to
        # an X window goes through the DDX Present path (no DRM master needed);
        # DXVK/Proton on this path to be validated.
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
    # Do NOT set __EGL_VENDOR_LIBRARY_FILENAMES=50_mesa.json here — that Mesa
    # override only exists to stop NVIDIA EGL GBM segfaulting on a virtual
    # framebuffer. On a real nvidia X screen we WANT the NVIDIA GLX/EGL vendor.
    /usr/bin/Xorg "${DISPLAY_NUM}" -config /etc/X11/xorg.conf -noreset -novtswitch \
        -sharevts +extension RANDR +extension RENDER +extension GLX +extension XVideo \
        +extension DOUBLE-BUFFER +extension DAMAGE +extension COMPOSITE +extension XTEST \
        -dpms -s off -nolisten tcp -ac -iglx -verbose vt7 >/tmp/xorg.log 2>&1 &
    sleep 3
    if pgrep -x Xorg >/dev/null; then
        echo "    Xorg running (nvidia DDX)"
        X_SERVER=Xorg
    else
        echo "    WARNING: Xorg failed to start — falling back to Xvfb. /tmp/xorg.log tail:"
        tail -n 20 /tmp/xorg.log 2>/dev/null | sed 's/^/      /'
        rm -f /tmp/.X${DISPLAY_NUM#:}-lock /tmp/.X11-unix/X${DISPLAY_NUM#:}
    fi
fi

if [ -z "$X_SERVER" ]; then
    echo "[*] Starting Xvfb on ${DISPLAY_NUM} (software framebuffer — debug/fallback)..."
    export DPAD_XORG=0
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
        *llvmpipe*|*"glxinfo failed"*) echo "    WARNING: Xorg is rendering on software (llvmpipe) — the nvidia DDX did not bind the GPU. Check /tmp/xorg.log and that NVIDIA_DRIVER_CAPABILITIES=all + a GPU is assigned." ;;
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

# --- Steam autostart (XFCE session) ---
# Drop a Steam.desktop into the XFCE autostart dir so Steam launches when the
# desktop session comes up — same pattern Steam-Headless uses. Under a real
# Xorg+nvidia screen Steam + Proton/DXVK render on the GPU directly (no vglrun);
# under Xvfb (debug) we wrap with vgl-steam so the VGL bridge still applies.
# STEAM_ARGS defaults to -silent (override e.g. -tenfoot for Big Picture).
# Disable with DPAD_AUTOSTART_STEAM=0 to boot a bare desktop for debugging.
STEAM_ARGS="${STEAM_ARGS:--silent}"
mkdir -p "${USER_HOME}/.config/autostart"
if [ "${DPAD_AUTOSTART_STEAM:-1}" = "1" ]; then
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
    chown -R "${USER_NAME}:${USER_NAME}" "${USER_HOME}/.config/autostart"
    echo "[*] Steam autostart configured: ${STEAM_EXEC} ${STEAM_ARGS} (direct launch after desktop -> /tmp/steam.log)"
else
    rm -f "${USER_HOME}/.config/autostart/Steam.desktop"
    echo "[*] Steam autostart: disabled (DPAD_AUTOSTART_STEAM=0)"
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

# --- Launch Steam directly (we DON'T run xfce4-session, so the XFCE autostart
# .desktop above is never processed). Background it after a short delay so the
# desktop + PulseAudio settle first. Logs to /tmp/steam.log (in the periodic dump).
if [ "${DPAD_AUTOSTART_STEAM:-1}" = "1" ] && [ -n "${STEAM_EXEC:-}" ]; then
    (
        sleep 8
        as_user "export DISPLAY=${DISPLAY_NUM} XDG_RUNTIME_DIR=${XDG_RUNTIME_DIR} PULSE_SERVER=${PULSE_SERVER} DBUS_SESSION_BUS_ADDRESS='${DBUS_SESSION_BUS_ADDRESS}'; ${STEAM_EXEC} ${STEAM_ARGS} >/tmp/steam.log 2>&1"
    ) &
    echo "[*] Steam launch scheduled in 8s (${STEAM_EXEC} ${STEAM_ARGS}) -> /tmp/steam.log"
fi

# --- PulseAudio (headless null sink; monitor is capturable for silence) ---
# PipeWire's null-sink monitor suspends when idle and pulsesrc times out against
# it; PulseAudio's null-sink monitor produces capturable silence even when idle,
# which is what we need for headless cloud-gaming audio capture.
echo "[*] Starting PulseAudio (headless null sink)..."
mkdir -p "${XDG_RUNTIME_DIR}/pulse"
chmod 1777 "${XDG_RUNTIME_DIR}" "${XDG_RUNTIME_DIR}/pulse"
chown -R "${USER_NAME}:${USER_NAME}" "${XDG_RUNTIME_DIR}"
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
if [ -S "${XDG_RUNTIME_DIR}/pulse/native" ]; then
    echo "    PulseAudio socket OK (${PULSE_SERVER})"
    echo "    --- sinks ---";  as_user "export PULSE_SERVER=${PULSE_SERVER} XDG_RUNTIME_DIR=${XDG_RUNTIME_DIR}; pactl list short sinks 2>/dev/null"
    echo "    --- sources ---"; as_user "export PULSE_SERVER=${PULSE_SERVER} XDG_RUNTIME_DIR=${XDG_RUNTIME_DIR}; pactl list short sources 2>/dev/null"
else
    echo "    PulseAudio socket MISSING:"; tail -n 20 /tmp/pulse.log 2>/dev/null || true
fi

# --- coturn (in-image TURN; Selkies WebRTC media relays through it) ---
echo "[*] Starting coturn on ${TURN_PORT_EXT}..."
if [ -n "${TURN_SERVER:-}" ]; then
    echo "    External TURN_SERVER configured — skipping local coturn"
else
    turnserver -n -a --log-file=/tmp/coturn.log --lt-cred-mech --fingerprint \
        --no-stun --no-multicast-peers --no-cli --no-tlsv1 --no-tlsv1_1 \
        --realm="dpadcloud" --user="${TURN_USER}:${TURN_PASS}" \
        -p "${TURN_PORT_EXT}" -X "${PUBLIC_IP:-localhost}" >/tmp/coturn.log 2>&1 &
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
    for d in /proc/driver/nvidia/gpus/*; do
        [ -d "$d" ] || continue
        pkey="$(basename "$d")"; pkey="${pkey#*:}"   # "0000:2b:00.0" -> "2b:00.0"
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
    export NVENC_FIX_DEBUG=1
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

# --- Sunshine (native Moonlight host) ---
SUNSHINE_BIN="$(command -v sunshine 2>/dev/null || echo /usr/bin/sunshine)"
if [ -x "$SUNSHINE_BIN" ]; then
    echo "[*] Configuring Sunshine..."
    as_user "mkdir -p ~/.config/sunshine"
    cp -f /home/dpad/.config/sunshine/sunshine.conf "${USER_HOME}/.config/sunshine/sunshine.conf" 2>/dev/null || true
    chown -R "${USER_NAME}:${USER_NAME}" "${USER_HOME}/.config/sunshine"
    as_user "export DISPLAY=${DISPLAY_NUM} XDG_RUNTIME_DIR=${XDG_RUNTIME_DIR} PULSE_SERVER=${PULSE_SERVER}; ${SUNSHINE_BIN} --creds admin '${SUNSHINE_PASS}'" 2>/dev/null || true
    echo "[*] Starting Sunshine..."
    as_user "export DISPLAY=${DISPLAY_NUM} XDG_RUNTIME_DIR=${XDG_RUNTIME_DIR} PULSE_SERVER=${PULSE_SERVER} LD_PRELOAD='${LD_PRELOAD}'; ${SUNSHINE_BIN} >/tmp/sunshine.log 2>&1" &
    sleep 3
    pgrep -x sunshine >/dev/null && echo "    Sunshine running" || echo "    WARNING: sunshine failed (see /tmp/sunshine.log)"
else
    echo "WARNING: sunshine not found"
fi

# --- Selkies-GStreamer (browser WebRTC streaming, bound to localhost) ---
echo "[*] Starting Selkies-GStreamer..."
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
chown -R "${USER_NAME}:${USER_NAME}" "${USER_HOME}/.cache"
rm -rf "${USER_HOME}/.cache/gstreamer-1.0"/* 2>/dev/null || true

# (Joystick interposer + flexgrip LD_PRELOAD were assembled earlier, before
# Sunshine, so both Sunshine and the Selkies encoder probe run under them.)

# coturn is exposed TCP-only on Vast (the 73478 tag) — UDP TURN would need a
# relay port range that blows Vast's 64-port limit. TCP TURN relays over the
# single listening connection. Override with SELKIES_TURN_PROTOCOL only if you
# also expose a UDP relay range.
SELKIES_TURN_PROTOCOL="${SELKIES_TURN_PROTOCOL:-tcp}"

as_user "export DISPLAY=${DISPLAY_NUM} XDG_RUNTIME_DIR=${XDG_RUNTIME_DIR} PULSE_SERVER=${PULSE_SERVER} PIPEWIRE_LATENCY=${PIPEWIRE_LATENCY} GST_DEBUG=${GST_DEBUG} LD_PRELOAD='${LD_PRELOAD}' SDL_JOYSTICK_DEVICE=/dev/input/js0 SELKIES_INTERPOSER='${SELKIES_INTERPOSER}'; . /opt/gstreamer/gst-env; selkies-gstreamer --addr=127.0.0.1 --port=16100 --enable_https=false --encoder=${SELKIES_ENC} --enable_basic_auth=true --basic_auth_user='${SELKIES_USER}' --basic_auth_password='${SELKIES_PASS}' --enable_resize=false --turn_host='${PUBLIC_IP:-127.0.0.1}' --turn_port=${TURN_PORT_EXT} --turn_protocol=${SELKIES_TURN_PROTOCOL} --turn_username='${TURN_USER}' --turn_password='${TURN_PASS}' --web_root=${SELKIES_WEB_ROOT}" >/tmp/selkies.log 2>&1 &
sleep 4
pgrep -f "selkies-gstreamer" >/dev/null && echo "    Selkies running on 127.0.0.1:16100 (encoder=${SELKIES_ENC})" || { echo "    WARNING: selkies failed (see /tmp/selkies.log)"; tail -n 30 /tmp/selkies.log; }

# --- moonlight-web-stream (PRIMARY browser path: Sunshine NVENC -> WebRTC) ---
# mws is a Moonlight client that bridges Sunshine's h264_nvenc stream to a
# browser over WebRTC, fronted by its own cloudflared tunnel. It reuses the
# in-image coturn TURN (TCP) for the WebRTC media relay — same model as Selkies,
# so on Vast only the 73478 TCP identity port needs exposing (no extra UDP range
# as long as clients relay through TURN). First-run flow (in the browser UI):
#   1) first login creates the mws admin user
#   2) add a host -> address "localhost", port empty (Sunshine default 47989)
#   3) click pair -> Sunshine shows the PIN in its Web UI -> enter it
#   4) launch an app. (Future: the orchestrator automates pairing via Sunshine's API.)
# Config: mws STRICTLY deserializes server/config.json and panics on a partial
# config (missing required fields like first_login_create_admin). So we DON'T
# hand-write it — we delete any stale one and let mws generate a schema-valid
# default (bind 0.0.0.0:8080, first_login_create_admin=true), then drive the ICE
# servers via env vars (cli.rs): DISABLE_DEFAULT_WEBRTC_ICE_SERVERS=true strips
# the bundled Google STUN, and WEBRTC_ICE_SERVER_0_* appends our coturn TURN —
# the only path that reaches mws on Vast (mws's own UDP port range isn't exposed).
MWS_URL=""
if [ -x /opt/mws/web-server ]; then
    echo "[*] Configuring moonlight-web-stream (env -> coturn TURN)..."
    mkdir -p /opt/mws/server
    chown -R "${USER_NAME}:${USER_NAME}" /opt/mws
    # Force fresh config generation each boot (avoids a stale/partial config
    # panicking; data.json — users/hosts — is separate and persists if the
    # /opt/mws/server volume is mounted).
    rm -f /opt/mws/server/config.json
    echo "[*] Starting moonlight-web-stream (web-server on 0.0.0.0:8080)..."
    as_user "cd /opt/mws && \
        DISABLE_DEFAULT_WEBRTC_ICE_SERVERS=true \
        WEBRTC_NETWORK_TYPES=udp4,tcp4 \
        WEBRTC_ICE_SERVER_0_URL='turn:${PUBLIC_IP:-127.0.0.1}:${TURN_PORT_EXT}?transport=tcp' \
        WEBRTC_ICE_SERVER_0_USERNAME='${TURN_USER}' \
        WEBRTC_ICE_SERVER_0_CREDENTIAL='${TURN_PASS}' \
        ./web-server" >/tmp/mws.log 2>&1 &
    # mws (Rust + actix) takes ~5-10s to initialize; wait for port 8080 to
    # accept connections instead of a fixed sleep (a 4s pgrep was a false
    # negative — mws was actually starting, just slowly).
    MWS_UP=0
    for i in $(seq 1 25); do
        if curl -sS -o /dev/null --connect-timeout 1 --max-time 2 "http://127.0.0.1:8080/" 2>/dev/null; then MWS_UP=1; break; fi
        sleep 1
    done
    if [ "$MWS_UP" = "1" ]; then
        echo "    mws running on 0.0.0.0:8080 (Sunshine NVENC -> WebRTC)"
    else
        echo "    WARNING: mws web-server not listening on :8080 after 25s (see /tmp/mws.log):"; tail -n 30 /tmp/mws.log
    fi
else
    echo "WARNING: moonlight-web-stream not found at /opt/mws/web-server"
fi

# --- mws <-> Sunshine auto-pairing (so the end user never sees a PIN) ---
# A background one-shot drives mws's /api/pair + Sunshine's /api/pin. Disabled
# with DPAD_MWS_AUTOPAIR=0. Only runs if mws came up. Logs to stdout +
# /tmp/mws-autopair.log (included in the periodic log dump below).
if [ "${DPAD_MWS_AUTOPAIR:-1}" = "1" ] && [ "${MWS_UP:-0}" = "1" ] && [ -x /opt/dpadcloud/mws-autopair ]; then
    echo "[*] Launching mws<->Sunshine auto-pairing (background)..."
    SUNSHINE_PASSWORD="${SUNSHINE_PASS}" /opt/dpadcloud/mws-autopair 2>&1 &
fi

# --- cloudflared (HTTPS tunnels for BOTH browser paths) ---
# mws (primary, :8080) and Selkies (fallback, :16100) each get an HTTPS tunnel
# so the secure-context gaming APIs (gamepad, WebCodecs, keyboard lock) work.
# Production: ONE named tunnel with two ingress rules in the Cloudflare dashboard
#   play-<id>.dpadcloud.com    -> http://localhost:8080  (mws, primary)
#   selkies-<id>.dpadcloud.com -> http://localhost:16100 (fallback)
# and pass CLOUDFLARED_TUNNEL_TOKEN + CLOUDFLARED_HOSTNAME (the mws/primary one).
# MVP: each gets a quick trycloudflare.com URL (two cloudflared processes).
start_quick_tunnel() {
  local local_url="$1" logfile="$2"
  cloudflared tunnel --no-autoupdate --url "$local_url" >"$logfile" 2>&1 &
  sleep 8
  grep -oE 'https://[a-z0-9.-]+trycloudflare\.com' "$logfile" 2>/dev/null | head -1
}
if [ -n "${CLOUDFLARED_TUNNEL_TOKEN:-}" ]; then
    echo "[*] Starting cloudflared named tunnel (primary -> mws :8080)..."
    cloudflared tunnel --no-autoupdate run --token "${CLOUDFLARED_TUNNEL_TOKEN}" >/tmp/cloudflared.log 2>&1 &
    MWS_URL="${CLOUDFLARED_HOSTNAME:-https://<your-tunnel-hostname>}"
    echo "    mws tunnel URL: ${MWS_URL}"
    if command -v cloudflared >/dev/null 2>&1; then
        SELKIES_URL="$(start_quick_tunnel http://localhost:16100 /tmp/cloudflared-selkies.log)"
        [ -n "$SELKIES_URL" ] && echo "    Selkies fallback tunnel: ${SELKIES_URL}" || echo "    Selkies fallback tunnel not captured (see /tmp/cloudflared-selkies.log)"
    fi
elif command -v cloudflared >/dev/null 2>&1; then
    echo "[*] Starting cloudflared quick tunnels (mws + Selkies)..."
    MWS_URL="$(start_quick_tunnel http://localhost:8080 /tmp/cloudflared-mws.log)"
    [ -n "$MWS_URL" ] && echo "    mws tunnel URL: ${MWS_URL}" || { echo "    mws tunnel URL not captured (see /tmp/cloudflared-mws.log):"; tail -n 15 /tmp/cloudflared-mws.log; }
    SELKIES_URL="$(start_quick_tunnel http://localhost:16100 /tmp/cloudflared-selkies.log)"
    [ -n "$SELKIES_URL" ] && echo "    Selkies tunnel URL: ${SELKIES_URL}" || { echo "    Selkies tunnel URL not captured (see /tmp/cloudflared-selkies.log):"; tail -n 15 /tmp/cloudflared-selkies.log; }
fi

# --- Tailscale (native-Moonlight enthusiast overlay) ---
TAILSCALE_IP=""
if [ -n "${TAILSCALE_AUTH_KEY:-}" ] && command -v tailscaled >/dev/null 2>&1; then
    echo "[*] Starting Tailscale..."
    mkdir -p /var/lib/tailscale /var/run/tailscale
    tailscaled --state=/var/lib/tailscale/tailscaled.state --socket=/var/run/tailscale/tailscaled.sock >/tmp/tailscaled.log 2>&1 &
    sleep 3
    tailscale up --authkey="${TAILSCALE_AUTH_KEY}" --hostname="${TAILSCALE_HOSTNAME:-dpadcloud}" 2>/dev/null \
        || tailscale up --authkey="${TAILSCALE_AUTH_KEY}" --hostname="${TAILSCALE_HOSTNAME:-dpadcloud}" --accept-routes 2>/dev/null \
        || echo "    WARNING: tailscale up failed (see /tmp/tailscaled.log)"
    TAILSCALE_IP="$(tailscale ip -4 2>/dev/null | head -1)"
    echo "    Tailnet IP: ${TAILSCALE_IP:-<pending>}"
fi

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
echo "  ▶ Browser click-and-play — PRIMARY (mws: Sunshine NVENC -> WebRTC):"
if [ -n "$MWS_URL" ]; then
    echo "      ${MWS_URL}"
    if [ "${DPAD_MWS_AUTOPAIR:-1}" = "1" ]; then
        echo "      Auto-pairs with Sunshine at boot — just log in and launch an app."
        echo "      (mws login: ${MWS_ADMIN_USER:-dpad} / <SUNSHINE_PASSWORD>; host 'localhost' already paired)"
    else
        echo "      First login creates the admin user; then add host 'localhost',"
        echo "      pair via Sunshine Web UI PIN, then launch an app."
    fi
else
    echo "      (no tunnel — set CLOUDFLARED_TUNNEL_TOKEN or quick-tunnel failed)"
    echo "      Local fallback: http://localhost:8080"
fi
echo ""
echo "  ▶ Browser click-and-play — FALLBACK (Selkies):"
if [ -n "$SELKIES_URL" ]; then
    echo "      ${SELKIES_URL}"
    echo "      Login: ${SELKIES_USER} / ${SELKIES_PASS}"
else
    echo "      (no tunnel — Selkies quick-tunnel failed)"
    echo "      Local fallback: http://localhost:16100  (Login: ${SELKIES_USER} / ${SELKIES_PASS})"
fi
echo ""
echo "  ▶ Native Moonlight (enthusiast, low latency):"
if [ -n "$TAILSCALE_IP" ]; then
    echo "      Moonlight → ${TAILSCALE_IP} (port 47989), Sunshine PIN in its Web UI"
else
    echo "      Set TAILSCALE_AUTH_KEY to enable; or Sunshine Web UI:"
    echo "      https://${PUBLIC_IP:-<ip>}:${VAST_TCP_PORT_47990:-47990} (admin / ${SUNSHINE_PASS})"
fi
echo ""
echo "  TURN (WebRTC media relay): ${PUBLIC_IP:-<ip>}:${TURN_PORT_EXT}  (${SELKIES_TURN_PROTOCOL}, ${TURN_USER}/<token>)"
echo ""
echo "  ▶ GPU-accelerated gaming (X server: ${X_SERVER:-?}):"
if [ "${X_SERVER}" = "Xorg" ]; then
    echo "      Steam auto-starts on login (${STEAM_ARGS}) — native Linux + Proton/DXVK"
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
        echo "=== /tmp/selkies.log (tail) ==="
        tail -n 100 /tmp/selkies.log 2>/dev/null || true
        echo "=== end selkies.log ==="
        echo "=== /tmp/mws.log (tail) ==="
        tail -n 60 /tmp/mws.log 2>/dev/null || true
        echo "=== end mws.log ==="
        echo "=== /tmp/mws-autopair.log (tail) ==="
        tail -n 40 /tmp/mws-autopair.log 2>/dev/null || true
        echo "=== end mws-autopair.log ==="
        echo "=== /tmp/sunshine.log (tail) ==="
        tail -n 60 /tmp/sunshine.log 2>/dev/null || true
        echo "=== end sunshine.log ==="
        echo "=== /tmp/pulse.log (tail) ==="
        tail -n 30 /tmp/pulse.log 2>/dev/null || true
        echo "=== end pulse.log ==="
        echo "=== /tmp/xfce.log (tail) ==="
        tail -n 30 /tmp/xfce.log 2>/dev/null || true
        echo "=== end xfce.log ==="
        echo "=== /tmp/xorg.log (tail) ==="
        tail -n 60 /tmp/xorg.log 2>/dev/null || true
        echo "=== end xorg.log ==="
        echo "=== /tmp/steam.log (tail) ==="
        tail -n 60 /tmp/steam.log 2>/dev/null || true
        echo "=== end steam.log ==="
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
        pgrep -x Xorg >/dev/null || { echo "WARNING: Xorg died, restarting"; rm -f /tmp/.X${DISPLAY_NUM#:}-lock /tmp/.X11-unix/X${DISPLAY_NUM#:}; /usr/bin/Xorg "${DISPLAY_NUM}" -config /etc/X11/xorg.conf -noreset -novtswitch -sharevts +extension RANDR +extension RENDER +extension GLX +extension XVideo +extension DAMAGE +extension COMPOSITE +extension XTEST -dpms -s off -nolisten tcp -ac -iglx -verbose vt7 >/tmp/xorg.log 2>&1 & }
    else
        pgrep -x Xvfb >/dev/null || { echo "WARNING: Xvfb died, restarting"; Xvfb "${DISPLAY_NUM}" -screen 0 "${SCREEN_RES}" -dpi 96 +extension GLX +extension RANDR +extension RENDER -ac -noreset -shmem & }
    fi
    pgrep -f "selkies-gstreamer" >/dev/null || echo "WARNING: selkies not running (see /tmp/selkies.log)"
    # mws is launched as `./web-server` (cwd /opt/mws), so pgrep on the path
    # doesn't match — check the port instead (returns 0 on any HTTP response,
    # incl. the 401 for unauthenticated /, which still means it's listening).
    curl -sS -o /dev/null --max-time 2 "http://127.0.0.1:8080/" 2>/dev/null || echo "WARNING: mws not listening on :8080 (see /tmp/mws.log)"
    pgrep -x sunshine >/dev/null || echo "WARNING: sunshine not running (see /tmp/sunshine.log)"
done