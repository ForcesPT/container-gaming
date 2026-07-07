#!/usr/bin/env bash
# =============================================================================
# DpadCloud — Vast KVM VM on-start bootstrap (multi-tenant: 1 user per GPU)
# =============================================================================
# Takes a fresh `vastai/kvm:ubuntu_cli_22.04-2025-11-21` VM from boot to N
# running `forcespt/dpadcloud-gaming` containers — one per GPU — each with its
# own Selkies tunnel URL printed to the console.
#
# Phases (each idempotent — safe to re-run, safe across the one reboot below):
#   1. ensure  nvidia_drm.modeset = Y   (REQUIRED for the DFP / full-Steam path;
#          if the VM boots with N, set it persistently + reload, or reboot once)
#   2. install nvidia-container-toolkit (needed for `docker run --gpus ...`)
#   3. pull  forcespt/dpadcloud-gaming:SteamUbuntu24.04VM  (or build; DPAD_BUILD=1)
#   4. detect GPU count N, launch N containers (one per GPU):
#        container i  ->  --gpus '"device=i"'  -p (3478+i):(3478+i)
#                        DPAD_COTURN_PORT=3478+i  DPAD_TURN_EXTERNAL_PORT=VAST_TCP_PORT_(3478+i)
#                        unique per-session password, its own Selkies (cloudflared) URL
#   5. wait for each container's Selkies tunnel URL and print them all
#
# Vast maps each exposed internal port to a RANDOM external port and injects
# VAST_TCP_PORT_<internal>. So at VM creation expose one TCP port per GPU:
#   1 GPU : -p 3478:3478
#   2 GPUs: -p 3478:3478 -p 3479:3479
#   4 GPUs: -p 3478:3478 -p 3479:3479 -p 3480:3480 -p 3481:3481
# (general: -p 3478..(3478+N-1)). Vast's 64-port limit → up to 64 users/VM.
# Add the matching UDP ports (-p 3478:3478/udp ...) to enable lower-latency UDP
# TURN (Vast injects VAST_UDP_PORT_<internal>). coturn already listens UDP; with
# both WebRTC peers on the same coturn the relay short-circuits internally, so
# only the listen port needs a UDP map (no relay port range to expose).
# A GPU whose port wasn't exposed is skipped (with a warning); the rest still run.
#
# Reboot safety: phase 1 may `reboot` once. This script installs itself as a
# systemd oneshot (dpadcloud-bootstrap.service) which re-runs at every boot;
# after the reboot modeset is already Y and phases 2-5 continue.
#
# Usage:
#   Live test (run as root on the VM):
#       curl -fsSL https://raw.githubusercontent.com/ForcesPT/container-gaming/main/scripts/vm-bootstrap.sh \
#         | bash -s -- install
#       journalctl -u dpadcloud-bootstrap -f
#   As a Vast on-start script (paste into the on-start field):
#       mkdir -p /opt/dpadcloud && \
#       curl -fsSL https://raw.githubusercontent.com/ForcesPT/container-gaming/main/scripts/vm-bootstrap.sh \
#         -o /opt/dpadcloud/vm-bootstrap.sh && \
#       chmod +x /opt/dpadcloud/vm-bootstrap.sh && \
#       /opt/dpadcloud/vm-bootstrap.sh install
#
# Env overrides (optional):
#   DPAD_SESSION_PASSWORDS  comma-separated per-session browser passwords
#                           (one per GPU; default: pass0,pass1,...)
#   DPAD_ISOLATION          privileged (default) | caps  (caps drops --privileged
#                           for tighter per-GPU isolation: --cap-add SYS_ADMIN
#                           --device /dev/uinput + --gpus device=i)
#   DPAD_TURN_BASE_PORT     default 3478
#   DPAD_BUILD=1            clone+build instead of pull (dev path)
#   DPAD_REPO_URL, DPAD_REPO_DIR, SELKIES_BASIC_AUTH_USER
# =============================================================================
set -uo pipefail

# Load Vast-injected instance env (PUBLIC_IPADDR, VAST_TCP_PORT_<n>, ...) so the
# bootstrap has them even when run as a systemd service. Vast writes these to
# /etc/environment on KVM VMs.
if [ -f /etc/environment ]; then
    set -a
    # shellcheck disable=SC1091
    . /etc/environment 2>/dev/null || true
    set +a
fi

REPO_URL="${DPAD_REPO_URL:-https://github.com/ForcesPT/container-gaming.git}"
REPO_DIR="${DPAD_REPO_DIR:-/opt/dpadcloud/container-gaming}"
SCRIPT_PATH="/opt/dpadcloud/vm-bootstrap.sh"
IMAGE_TAG="forcespt/dpadcloud-gaming:SteamUbuntu24.04VM"
CONTAINER_PREFIX="dpad"
URL_FILE="/opt/dpadcloud/selkies-urls.txt"
TAG_FILE="/opt/dpadcloud/.image-tag"
SERVICE_NAME="dpadcloud-bootstrap.service"
SELKIES_USER="${SELKIES_BASIC_AUTH_USER:-dpad}"
TURN_BASE_PORT="${DPAD_TURN_BASE_PORT:-3478}"
# CDI (default) = per-GPU isolation + DRM device + userns/DFP, no --privileged.
# legacy = old --privileged --gpus device=i (no isolation; use only to debug).
ISOLATION="${DPAD_ISOLATION:-cdi}"

log()  { echo "[dpadcloud-bootstrap] $*"; }
err()  { echo "[dpadcloud-bootstrap][ERROR] $*" >&2; }
have() { command -v "$1" >/dev/null 2>&1; }

# -----------------------------------------------------------------------------
# Phase 1: nvidia_drm.modeset = Y  (DFP Xorg / DRM master / Steam UI need KMS)
# -----------------------------------------------------------------------------
ensure_modeset() {
    local cur
    cur="$(cat /sys/module/nvidia_drm/parameters/modeset 2>/dev/null || true)"
    log "nvidia_drm.modeset = ${cur:-?} (need Y)"
    [ "$cur" = "Y" ] && { log "modeset already Y"; return 0; }

    echo 'options nvidia_drm modeset=Y' > /etc/modprobe.d/nvidia-drm-modeset.conf
    update-initramfs -u >/dev/null 2>&1 || true

    if modprobe -r nvidia_drm nvidia_modeset nvidia_uvm nvidia 2>/dev/null; then
        modprobe nvidia_drm modeset=1
        cur="$(cat /sys/module/nvidia_drm/parameters/modeset 2>/dev/null || true)"
        [ "$cur" = "Y" ] && { log "modeset flipped to Y live (no reboot needed)"; return 0; }
    fi

    log "modeset still not Y after live reload — rebooting ONCE to apply"
    log "(the dpadcloud-bootstrap service will continue automatically after reboot)"
    sync; sleep 3; reboot; exit 0
}

# -----------------------------------------------------------------------------
# Phase 2: nvidia-container-toolkit
# -----------------------------------------------------------------------------
ensure_nct() {
    if have nvidia-ctk; then
        log "nvidia-container-toolkit already installed"
    else
        log "installing nvidia-container-toolkit"
        curl -fsSL https://nvidia.github.io/libnvidia-container/gpgkey \
            | gpg --dearmor -o /usr/share/keyrings/nvidia-container-toolkit-keyring.gpg
        curl -fsSL https://nvidia.github.io/libnvidia-container/stable/deb/nvidia-container-toolkit.list \
            | sed 's#deb https://#deb [signed-by=/usr/share/keyrings/nvidia-container-toolkit-keyring.gpg] https://#g' \
            > /etc/apt/sources.list.d/nvidia-container-toolkit.list
        apt-get update
        DEBIAN_FRONTEND=noninteractive apt-get install -y nvidia-container-toolkit
    fi
    nvidia-ctk runtime configure --runtime=docker
    systemctl restart docker
    if ! docker run --rm --gpus all nvidia/cuda:12.8.1-runtime-ubuntu24.04 nvidia-smi >/dev/null 2>&1; then
        err "container cannot see the GPU after nvidia-container-toolkit install"
        docker run --rm --gpus all nvidia/cuda:12.8.1-runtime-ubuntu24.04 nvidia-smi || true
        return 1
    fi
    log "GPU visible inside a container (nvidia-container-toolkit OK)"
    # Generate a CDI spec so each container can be pinned to one GPU with its
    # full device set (/dev/nvidiaX + /dev/dri/cardX + renderDXXX) via
    # `--runtime=nvidia -e NVIDIA_VISIBLE_DEVICES=nvidia.com/gpu=i`. This is what
    # gives per-GPU isolation AND the DRM device needed for the DFP/full-Steam
    # path without --privileged. Idempotent; regenerate after driver changes.
    mkdir -p /etc/cdi
    if nvidia-ctk cdi generate --output=/etc/cdi/nvidia.yaml >/tmp/cdi-gen.log 2>&1; then
        log "CDI spec generated ($(nvidia-ctk cdi list 2>/dev/null | grep -c 'nvidia.com/gpu=') devices)"
    else
        err "CDI spec generation failed (see /tmp/cdi-gen.log) — CDI launch will not work"
    fi
}

# -----------------------------------------------------------------------------
# Phase 2b: enable unprivileged user namespaces on the VM host
# -----------------------------------------------------------------------------
# Steam (and pressure-vessel/Flatpak) running as the non-root dpad user needs
# UNPRIVILEGED userns, not just root's CAP_SYS_ADMIN userns. The gating sysctls
# are host-level (VM kernel) and can't be set from inside a non-privileged
# container, so set them here on the VM host. The container launch also passes
# --security-opt seccomp=unconfined --security-opt apparmor=unconfined.
# -----------------------------------------------------------------------------
ensure_userns() {
    local f=/etc/sysctl.d/99-dpad-userns.conf
    cat > "$f" <<'EOF'
kernel.unprivileged_userns_clone=1
kernel.apparmor_restrict_unprivileged_userns=0
# Steam + CEF (steamwebhelper) under gamescope open far more than the default
# 65536 memory mappings; without this Steam's GL composer thread dies with
# 'mmap() failed: Cannot allocate memory' and gamescope crash-loops. Steam Deck
# sets 1048576.
vm.max_map_count=1048576
EOF
    sysctl --system >/dev/null 2>&1 || true
    local u a m
    u="$(sysctl -n kernel.unprivileged_userns_clone 2>/dev/null || echo ?)"
    a="$(sysctl -n kernel.apparmor_restrict_unprivileged_userns 2>/dev/null || echo ?)"
    m="$(sysctl -n vm.max_map_count 2>/dev/null || echo ?)"
    log "unprivileged userns: unprivileged_userns_clone=${u}  apparmor_restrict_unprivileged_userns=${a}  vm.max_map_count=${m}"
}

ensure_git() {
    have git && return 0
    log "installing git"
    apt-get update
    DEBIAN_FRONTEND=noninteractive apt-get install -y git
}

ensure_repo() {
    ensure_git
    if [ -d "$REPO_DIR/.git" ]; then
        log "updating repo at $REPO_DIR"
        git -C "$REPO_DIR" pull --ff-only || log "pull failed — continuing with existing checkout"
    else
        log "cloning $REPO_URL → $REPO_DIR"
        mkdir -p "$(dirname "$REPO_DIR")"
        git clone --depth 1 "$REPO_URL" "$REPO_DIR" || { err "git clone failed"; return 1; }
    fi
}

detect_build_args() {
    local cc major
    cc="$(nvidia-smi --query-gpu=compute_cap --format=csv,noheader 2>/dev/null | head -1 | tr -d ' ')"
    major="${cc%%.*}"
    log "first GPU compute_cap = ${cc:-?}" >&2   # stderr: stdout is captured by the caller
    if [ -n "$major" ] && [ "$major" -ge 12 ] 2>/dev/null; then
        echo "12.8.1 12-8"     # Blackwell (sm_120+) needs CUDA >= 12.8
    else
        echo "12.5.1 12-5"
    fi
}

# -----------------------------------------------------------------------------
# Phase 3: image — pull (default) or build (DPAD_BUILD=1)
# -----------------------------------------------------------------------------
ensure_image() {
    if [ "${DPAD_BUILD:-0}" = "1" ]; then
        ensure_repo || return 1
        local cuda_ver cuda_pkg
        read -r cuda_ver cuda_pkg <<< "$(detect_build_args)"
        log "building image ${IMAGE_TAG} (CUDA $cuda_ver / $cuda_pkg)"
        docker build --build-arg "CUDA_VERSION=${cuda_ver}" --build-arg "CUDA_PKG=${cuda_pkg}" \
            -t "${IMAGE_TAG}" "$REPO_DIR" || { err "docker build failed"; return 1; }
    else
        log "pulling image ${IMAGE_TAG} from Docker Hub"
        docker pull "${IMAGE_TAG}" || { err "docker pull failed"; return 1; }
    fi
    echo "${IMAGE_TAG}" > "$TAG_FILE"
    log "image ready: ${IMAGE_TAG}"
}

# -----------------------------------------------------------------------------
# Phase 4: run one container per GPU (multi-tenant)
# -----------------------------------------------------------------------------
count_gpus() {
    local n
    n="$(nvidia-smi -L 2>/dev/null | wc -l)"
    { [ -n "$n" ] && [ "$n" -ge 1 ]; } 2>/dev/null || n=1
    echo "$n"
}

# Per-session browser/Sunshine password for container <i>.
# DPAD_SESSION_PASSWORDS="pw0,pw1,..." overrides; else default pass<index>.
session_password() {
    local i="$1" pw=""
    if [ -n "${DPAD_SESSION_PASSWORDS:-}" ]; then
        pw="$(echo "$DPAD_SESSION_PASSWORDS" | awk -F',' -v i="$i" '{print $(i+1)}')"
    fi
    [ -n "$pw" ] || pw="pass${i}"
    echo "$pw"
}

# docker run arg group for GPU access/isolation
isolation_args() {
    local idx="$1"
    if [ "$ISOLATION" = "legacy" ]; then
        # old path: --privileged --gpus device=i (NO per-GPU isolation; debug only)
        printf '%s\n' --privileged --gpus "device=${idx}"
    else
        # CDI: --runtime=nvidia + NVIDIA_VISIBLE_DEVICES=nvidia.com/gpu=i injects ONLY
        # GPU i's full device set (/dev/nvidiaX + /dev/dri/cardX + renderDXXX) →
        # per-GPU isolation AND the DRM device for DFP/DRM-master, with no
        # --privileged. --cap-add SYS_ADMIN restores userns (unshare -U) + DRM
        # master. --device /dev/uinput for Sunshine input. nofile bumped (the
        # non-privileged hard cap is 1024, too low for Steam/Selkies).
        printf '%s\n' --runtime=nvidia --cap-add SYS_ADMIN --device /dev/uinput \
            --security-opt seccomp=unconfined --security-opt apparmor=unconfined \
            -e "NVIDIA_VISIBLE_DEVICES=nvidia.com/gpu=${idx}"
    fi
}

run_container_for() {
    local idx="$1"
    local img_tag; img_tag="$(cat "$TAG_FILE" 2>/dev/null || true)"
    [ -z "$img_tag" ] && { err "no image tag ($TAG_FILE)"; return 1; }

    local port=$(( TURN_BASE_PORT + idx ))
    local vast_var="VAST_TCP_PORT_${port}"
    local ext_port="${!vast_var:-}"
    local pub_ip="${PUBLIC_IPADDR:-}"
    local name="${CONTAINER_PREFIX}-${idx}"
    local sess_pass; sess_pass="$(session_password "$idx")"

    if docker inspect -f '{{.State.Running}}' "$name" 2>/dev/null | grep -q true; then
        log "container $name already running — leaving it"
        return 0
    fi
    if docker ps -a --format '{{.Names}}' | grep -qx "$name"; then
        docker rm -f "$name" >/dev/null; log "removed stopped $name"
    fi

    if [ -z "$ext_port" ]; then
        err "VAST_TCP_PORT_${port} is empty — port ${port}/tcp was NOT exposed at VM creation."
        err "Skipping $name (GPU $idx). Expose -p ${port}:${port} to serve this GPU."
        return 0   # not fatal — serve as many GPUs as we have exposed ports for
    fi

    local -a iso=()
    while IFS= read -r a; do iso+=( "$a" ); done < <(isolation_args "$idx")

    log "launching $name : GPU $idx, coturn ${port} -> ext ${ext_port}, public ${pub_ip:-<?>}"
    # DPAD_GAMESCOPE=1 switches the container to the gamescope headless + Steam
    # multi-tenant path (no DRM master). Pass-through DPAD_GAMESCOPE/DPAD_STEAM_ARGS
    # so the on-start can opt in without editing the bootstrap.
    local -a gs_env=()
    [ -n "${DPAD_GAMESCOPE:-}" ]  && gs_env+=( -e "DPAD_GAMESCOPE=${DPAD_GAMESCOPE}" )
    [ -n "${DPAD_STEAM_ARGS:-}" ] && gs_env+=( -e "DPAD_STEAM_ARGS=${DPAD_STEAM_ARGS}" )
    # UDP TURN (lower latency than TCP): if the VM exposed -p ${port}:${port}/udp,
    # Vast injects VAST_UDP_PORT_${port}. Forward the UDP port to the container and
    # pass the external UDP port so the entrypoint adds a UDP ICE entry. coturn
    # already listens UDP; both peers on the same coturn short-circuit the relay,
    # so only the listen port needs mapping (no relay range to expose).
    local udp_var="VAST_UDP_PORT_${port}"
    local udp_ext="${!udp_var:-}"
    local -a udp_args=()
    if [ -n "$udp_ext" ]; then
        udp_args+=( -p "${port}:${port}/udp" -e "DPAD_TURN_UDP_EXTERNAL_PORT=${udp_ext}" )
        log "  UDP TURN enabled: ${port}/udp -> ext ${udp_ext} (lower latency than TCP)"
    fi
    docker run -d --name "$name" \
        "${iso[@]}" --shm-size=2g --ulimit nofile=1048576:1048576 \
        -p "${port}:${port}" \
        "${udp_args[@]}" \
        -e DPAD_PROVIDER=runpod -e DPAD_COTURN_PORT="$port" \
        -e "DPAD_TURN_PUBLIC_IP=${pub_ip}" -e "DPAD_TURN_EXTERNAL_PORT=${ext_port}" \
        -e "SUNSHINE_PASSWORD=${sess_pass}" \
        -e "SELKIES_BASIC_AUTH_USER=${SELKIES_USER}" \
        -e "SELKIES_BASIC_AUTH_PASSWORD=${sess_pass}" \
        "${gs_env[@]}" \
        "$img_tag" || { err "docker run $name failed"; return 1; }
    log "$name launched (login ${SELKIES_USER}/${sess_pass})"
}

run_all_containers() {
    local n started=0 i max
    n="$(count_gpus)"
    # On consumer GPUs the nvidia-modeset path is effectively a singleton, so only
    # ONE container reliably gets the DFP/full-Steam UI at a time; the rest fall
    # back to NULL-mode (GPU rendering + stream, but no Steam UI). Cap sessions
    # with DPAD_MAX_SESSIONS (default = GPU count) — set it to 1 for a clean
    # single-user full-Steam VM even on multi-GPU hosts.
    max="${DPAD_MAX_SESSIONS:-$n}"
    [ "$max" -gt "$n" ] 2>/dev/null && max="$n"
    log "GPUs detected: $n — launching up to ${max} container(s) (DPAD_MAX_SESSIONS=${DPAD_MAX_SESSIONS:-<gpu count>})"
    for (( i=0; i<max; i++ )); do
        run_container_for "$i" && started=$((started+1))
    done
    if [ "$started" -eq 0 ]; then
        err "no containers started — expose at least -p ${TURN_BASE_PORT}:${TURN_BASE_PORT}."
        return 1
    fi
    log "launched $started container(s)"
}

# -----------------------------------------------------------------------------
# Phase 5: wait for each container's Selkies tunnel URL and announce them
# -----------------------------------------------------------------------------
report_all_urls() {
    local n i
    n="$(count_gpus)"
    local -a pending=()
    for (( i=0; i<n; i++ )); do
        local name="${CONTAINER_PREFIX}-${i}"
        docker inspect -f '{{.State.Running}}' "$name" 2>/dev/null | grep -q true && pending+=( "$i" )
    done
    [ "${#pending[@]}" -eq 0 ] && { err "no running containers to report"; return 1; }

    log "waiting for Selkies tunnel URLs (up to 7 min) for containers: ${pending[*]}"
    : > "$URL_FILE"
    local deadline=$(( $(date +%s) + 420 ))
    while [ "$(date +%s)" -lt "$deadline" ] && [ "${#pending[@]}" -gt 0 ]; do
        local -a next=()
        for idx in "${pending[@]}"; do
            local name="${CONTAINER_PREFIX}-${idx}"
            local url; url="$(docker logs "$name" 2>&1 | grep -oiE 'https://[a-z0-9.-]+\.trycloudflare\.com' | tail -1)"
            if [ -n "$url" ]; then
                local port=$(( TURN_BASE_PORT + idx ))
                local vast_var="VAST_TCP_PORT_${port}"
                local ext="${!vast_var:-${port}}"
                local sess_pass; sess_pass="$(session_password "$idx")"
                {
                    echo "---- User $idx (GPU $idx) ----"
                    echo "  Selkies tunnel URL: $url"
                    echo "  Browser login: ${SELKIES_USER} / ${sess_pass}"
                    echo "  TURN (direct, no tunnel): ${PUBLIC_IPADDR:-<?>}:${ext}"
                } | tee -a "$URL_FILE" | tee /dev/console 2>/dev/null || true
                log "ready[$idx]: $url"
            else
                next+=( "$idx" )
            fi
        done
        pending=( "${next[@]}" )
        [ "${#pending[@]}" -gt 0 ] && sleep 5
    done

    if [ "${#pending[@]}" -gt 0 ]; then
        err "timed out waiting for URLs for containers: ${pending[*]}"
        for idx in "${pending[@]}"; do
            err "--- last 40 lines of ${CONTAINER_PREFIX}-${idx} ---"
            docker logs --tail 40 "${CONTAINER_PREFIX}-${idx}" 2>&1 || true
        done
        return 1
    fi
    {
        echo "============================================================"
        echo "  DpadCloud READY — $(grep -c 'Selkies tunnel URL' "$URL_FILE" 2>/dev/null) session(s)."
        echo "  URLs listed in $URL_FILE. Open each in a browser — no SSH tunnel needed."
        echo "============================================================"
    } | tee /dev/console 2>/dev/null || true
    return 0
}

# -----------------------------------------------------------------------------
# The full bootstrap (phases 1-5), with the one reboot in phase 1
# -----------------------------------------------------------------------------
bootstrap() {
    log "=== DpadCloud VM bootstrap starting (multi-tenant: 1 user/GPU) ==="
    systemctl start docker 2>/dev/null || true
    ensure_modeset            # may reboot once; resumes here after
    ensure_nct                || return 1
    ensure_userns
    ensure_image              || return 1
    run_all_containers        || return 1
    report_all_urls           || return 1
    log "=== DpadCloud VM bootstrap complete ==="
}

# -----------------------------------------------------------------------------
# Install this script as a systemd oneshot so it (re)runs at every boot and
# survives the phase-1 reboot. Used by the Vast on-start payload.
# -----------------------------------------------------------------------------
install_self() {
    log "installing systemd service ($SERVICE_NAME)"
    mkdir -p /opt/dpadcloud
    if [ ! -f "$SCRIPT_PATH" ] || [ "$(readlink -f "$0" 2>/dev/null)" != "$SCRIPT_PATH" ]; then
        local src=""
        [ -f "$REPO_DIR/scripts/vm-bootstrap.sh" ] && src="$REPO_DIR/scripts/vm-bootstrap.sh"
        if [ -z "$src" ] && [ -f "$(dirname "$0")/vm-bootstrap.sh" ] \
            && [ "$(readlink -f "$0" 2>/dev/null)" != "$(dirname "$0")/vm-bootstrap.sh" ]; then
            src="$(dirname "$0")/vm-bootstrap.sh"
        fi
        if [ -z "$src" ]; then
            curl -fsSL "https://raw.githubusercontent.com/ForcesPT/container-gaming/main/scripts/vm-bootstrap.sh" \
                -o "$SCRIPT_PATH" || { err "could not fetch $SCRIPT_PATH"; return 1; }
        else
            cp "$src" "$SCRIPT_PATH"
        fi
        chmod +x "$SCRIPT_PATH"
    fi

    cat > "/etc/systemd/system/${SERVICE_NAME}" <<UNIT
[Unit]
Description=DpadCloud VM bootstrap (modeset -> nct -> pull -> N containers)
After=network-online.target docker.service
Wants=network-online.target
ConditionPathExists=/usr/bin/docker

[Service]
Type=oneshot
ExecStart=${SCRIPT_PATH}
RemainAfterExit=yes
StandardOutput=journal+console
StandardError=journal+console
TimeoutStartSec=60min

[Install]
WantedBy=multi-user.target
UNIT

    systemctl daemon-reload
    systemctl enable "${SERVICE_NAME}"
    log "starting ${SERVICE_NAME} (follow: journalctl -u ${SERVICE_NAME%.service} -f)"
    systemctl restart "${SERVICE_NAME}"
}

case "${1:-run}" in
    install) install_self ;;
    run)     bootstrap ;;
    *) echo "usage: $0 [install|run]" >&2; exit 1 ;;
esac