#!/usr/bin/env bash
# =============================================================================
# DpadCloud — Vast KVM VM on-start bootstrap
# =============================================================================
# Takes a fresh `vastai/kvm:ubuntu_cli_22.04-2025-11-21` VM from boot to a
# running `forcespt/dpadcloud-gaming` container with the Selkies tunnel URL
# printed to the console.
#
# Phases (each idempotent — safe to re-run, safe across the one reboot below):
#   1. ensure  nvidia_drm.modeset = Y   (REQUIRED for the DFP / full-Steam path;
#          if the VM boots with N, set it persistently + reload, or reboot once)
#   2. install nvidia-container-toolkit (needed for `docker run --gpus all`)
#   3. clone / pull  https://github.com/ForcesPT/container-gaming.git
#   4. build the image, auto-picking the CUDA variant by GPU arch
#          (Blackwell sm_120+ → CUDA 12.8.1 / 12-8, tag ...VM-rtx50 ;
#           else              → CUDA 12.5.1 / 12-5, tag ...VM)
#   5. run the container  ( --privileged --gpus all --shm-size=2g -p 3478:3478 )
#   6. wait for the Selkies tunnel URL in `docker logs` and print it
#
# Reboot safety: phase 1 may `reboot` once. To survive that, this script installs
# itself as a systemd oneshot service (dpadcloud-bootstrap.service) which re-runs
# at every boot; after the reboot modeset is already Y and phases 2-6 continue.
#
# Usage:
#   Live test (run as root on the VM):
#       curl -fsSL https://raw.githubusercontent.com/ForcesPT/container-gaming/main/scripts/vm-bootstrap.sh \
#         | bash -s -- install
#     ...or, after cloning:
#       ./scripts/vm-bootstrap.sh install        # install systemd unit + start it
#       ./scripts/vm-bootstrap.sh               # just run the phases (no install)
#       journalctl -u dpadcloud-bootstrap -f     # follow progress
#
#   As a Vast on-start script (paste into the instance on-start field):
#       mkdir -p /opt/dpadcloud && \
#       curl -fsSL https://raw.githubusercontent.com/ForcesPT/container-gaming/main/scripts/vm-bootstrap.sh \
#         -o /opt/dpadcloud/vm-bootstrap.sh && \
#       chmod +x /opt/dpadcloud/vm-bootstrap.sh && \
#       /opt/dpadcloud/vm-bootstrap.sh install
#
# Env overrides (optional): SUNSHINE_PASSWORD, SELKIES_BASIC_AUTH_USER,
#   SELKIES_BASIC_AUTH_PASSWORD, DPAD_REPO_URL, DPAD_REPO_DIR
# =============================================================================
set -uo pipefail

# Load Vast-injected instance env (PUBLIC_IPADDR, VAST_TCP_PORT_<n>,
# OPEN_BUTTON_TOKEN, ...) so the bootstrap has them even when run as a systemd
# service. Vast writes these to /etc/environment on KVM VMs.
if [ -f /etc/environment ]; then
    set -a
    # shellcheck disable=SC1091
    . /etc/environment 2>/dev/null || true
    set +a
fi

REPO_URL="${DPAD_REPO_URL:-https://github.com/ForcesPT/container-gaming.git}"
REPO_DIR="${DPAD_REPO_DIR:-/opt/dpadcloud/container-gaming}"
SCRIPT_PATH="/opt/dpadcloud/vm-bootstrap.sh"
# Single tag (matches the PROJECT_STATE convention). The CUDA build args below
# still vary by GPU arch; the tag name stays the same.
IMAGE_TAG="forcespt/dpadcloud-gaming:SteamUbuntu24.04VM"
CONTAINER_NAME="dpad"
URL_FILE="/opt/dpadcloud/selkies-url.txt"
TAG_FILE="/opt/dpadcloud/.image-tag"
SERVICE_NAME="dpadcloud-bootstrap.service"
SUNSHINE_PASSWORD="${SUNSHINE_PASSWORD:-pass}"
SELKIES_USER="${SELKIES_BASIC_AUTH_USER:-dpad}"
SELKIES_PASS="${SELKIES_BASIC_AUTH_PASSWORD:-pass}"

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

    # persist across reboots
    echo 'options nvidia_drm modeset=Y' > /etc/modprobe.d/nvidia-drm-modeset.conf
    update-initramfs -u >/dev/null 2>&1 || true

    # try a live module reload (works if nothing is holding the GPU)
    if modprobe -r nvidia_drm nvidia_modeset nvidia_uvm nvidia 2>/dev/null; then
        modprobe nvidia_drm modeset=1
        cur="$(cat /sys/module/nvidia_drm/parameters/modeset 2>/dev/null || true)"
        if [ "$cur" = "Y" ]; then
            log "modeset flipped to Y live (no reboot needed)"
            return 0
        fi
    fi

    # still not Y → reboot once; the systemd service resumes phases 2-6 after
    log "modeset still not Y after live reload — rebooting ONCE to apply"
    log "(the dpadcloud-bootstrap service will continue automatically after reboot)"
    sync
    sleep 3
    reboot
    exit 0   # never reached
}

# -----------------------------------------------------------------------------
# Phase 2: nvidia-container-toolkit  (for `docker run --gpus all`)
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
    # (re)configure the docker runtime + restart docker (idempotent)
    nvidia-ctk runtime configure --runtime=docker
    systemctl restart docker
    # sanity: GPU visible inside a container?
    if ! docker run --rm --gpus all nvidia/cuda:12.8.1-runtime-ubuntu24.04 nvidia-smi >/dev/null 2>&1; then
        err "container cannot see the GPU after nvidia-container-toolkit install"
        docker run --rm --gpus all nvidia/cuda:12.8.1-runtime-ubuntu24.04 nvidia-smi || true
        return 1
    fi
    log "GPU visible inside a container (nvidia-container-toolkit OK)"
}

ensure_git() {
    have git && return 0
    log "installing git"
    apt-get update
    DEBIAN_FRONTEND=noninteractive apt-get install -y git
}

# -----------------------------------------------------------------------------
# Phase 3: clone / pull the image source
# -----------------------------------------------------------------------------
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

# -----------------------------------------------------------------------------
# Phase 4: build the image (auto-pick CUDA variant by GPU compute capability)
# -----------------------------------------------------------------------------
detect_build_args() {
    local cc major
    cc="$(nvidia-smi --query-gpu=compute_cap --format=csv,noheader 2>/dev/null | head -1 | tr -d ' ')"
    major="${cc%%.*}"
    # NOTE: this diagnostic MUST go to stderr — stdout is captured by the caller
    # (`read -r ... <<< "$(detect_build_args)"`), so stdout may carry ONLY the
    # 3 tokens below.
    log "first GPU compute_cap = ${cc:-?}" >&2
    if [ -n "$major" ] && [ "$major" -ge 12 ] 2>/dev/null; then
        # Blackwell (sm_120+) needs CUDA >= 12.8
        echo "12.8.1 12-8"
    else
        echo "12.5.1 12-5"
    fi
}

ensure_image() {
    local cuda_ver cuda_pkg
    read -r cuda_ver cuda_pkg <<< "$(detect_build_args)"
    log "building image ${IMAGE_TAG} (CUDA $cuda_ver / $cuda_pkg)"
    docker build \
        --build-arg "CUDA_VERSION=${cuda_ver}" \
        --build-arg "CUDA_PKG=${cuda_pkg}" \
        -t "${IMAGE_TAG}" "$REPO_DIR" || { err "docker build failed"; return 1; }
    echo "${IMAGE_TAG}" > "$TAG_FILE"
    log "image built: ${IMAGE_TAG}"
}

# -----------------------------------------------------------------------------
# Phase 5: run the container
# -----------------------------------------------------------------------------
run_container() {
    local img_tag
    img_tag="$(cat "$TAG_FILE" 2>/dev/null || true)"
    if [ -z "$img_tag" ]; then
        err "no image tag file ($TAG_FILE) — build phase must run first"; return 1
    fi

    if docker inspect -f '{{.State.Running}}' "$CONTAINER_NAME" 2>/dev/null | grep -q true; then
        log "container $CONTAINER_NAME already running — leaving it"
        return 0
    fi
    if docker ps -a --format '{{.Names}}' | grep -qx "$CONTAINER_NAME"; then
        log "removing stopped container $CONTAINER_NAME"
        docker rm -f "$CONTAINER_NAME" >/dev/null
    fi

    log "launching container $CONTAINER_NAME (image $img_tag)"
    # Vast maps the exposed coturn port (3478) to a random external port and
    # injects VAST_TCP_PORT_3478; PUBLIC_IPADDR is the public IP. The browser's
    # TURN entry must point at <public_ip>:<external_port> so it reaches coturn
    # directly over the internet (no SSH tunnel). 3478/tcp MUST be exposed at VM
    # creation or the browser stream will not connect.
    local ext_port="${VAST_TCP_PORT_3478:-}"
    local pub_ip="${PUBLIC_IPADDR:-}"
    local -a turn_env=()
    if [ -n "$pub_ip" ];   then turn_env+=( -e "DPAD_TURN_PUBLIC_IP=$pub_ip" ); fi
    if [ -n "$ext_port" ]; then turn_env+=( -e "DPAD_TURN_EXTERNAL_PORT=$ext_port" ); fi
    if [ -z "$ext_port" ]; then
        err "VAST_TCP_PORT_3478 is empty — port 3478/tcp was NOT exposed when the VM was created."
        err "Recreate the VM exposing 3478/tcp (Vast UI: add port 3478/tcp; or CLI -p 3478:3478)."
        err "Continuing, but the browser stream will NOT connect from the internet."
    fi
    log "TURN: public_ip=${pub_ip:-<unknown>} external_port=${ext_port:-<unset-3478-not-exposed>}"
    docker run -d --name "$CONTAINER_NAME" \
        --privileged --gpus all --shm-size=2g \
        -p 3478:3478 \
        -e DPAD_PROVIDER=runpod -e DPAD_COTURN_PORT=3478 \
        "${turn_env[@]}" \
        -e "SUNSHINE_PASSWORD=${SUNSHINE_PASSWORD}" \
        -e "SELKIES_BASIC_AUTH_USER=${SELKIES_USER}" \
        -e "SELKIES_BASIC_AUTH_PASSWORD=${SELKIES_PASS}" \
        "$img_tag" || { err "docker run failed"; return 1; }
    log "container launched"
}

# -----------------------------------------------------------------------------
# Phase 6: wait for the Selkies tunnel URL and announce it
# -----------------------------------------------------------------------------
report_url() {
    log "waiting for the Selkies tunnel URL in container logs (up to 6 min)..."
    local deadline url
    deadline=$(( $(date +%s) + 360 ))
    while [ "$(date +%s)" -lt "$deadline" ]; do
        url="$(docker logs "$CONTAINER_NAME" 2>&1 \
               | grep -oiE 'https://[a-z0-9.-]+\.trycloudflare\.com' | tail -1)"
        if [ -n "$url" ]; then
            echo "$url" > "$URL_FILE"
            {
                echo "============================================================"
                echo "  DpadCloud READY."
                echo "  Selkies tunnel URL: $url"
                echo "  Browser login: ${SELKIES_USER} / ${SELKIES_PASS}"
                echo "  (also saved to $URL_FILE)"
                echo "  From your laptop, open the URL above. If the stream needs the"
                echo "  TURN port over SSH:  ssh -p <vm_ssh_port> root@<vm_ip> -L 3478:localhost:3478"
                echo "============================================================"
            } | tee /dev/console 2>/dev/null || true
            log "ready — URL: $url"
            return 0
        fi
        sleep 5
    done
    err "timed out waiting for the tunnel URL. Last 80 log lines:"
    docker logs --tail 80 "$CONTAINER_NAME" 2>&1 || true
    return 1
}

# -----------------------------------------------------------------------------
# The full bootstrap (phases 1-6), in order, with the one reboot in phase 1
# -----------------------------------------------------------------------------
bootstrap() {
    log "=== DpadCloud VM bootstrap starting ==="
    systemctl start docker 2>/dev/null || true
    ensure_modeset            # may reboot once; resumes here after
    ensure_nct                || return 1
    ensure_repo               || return 1
    ensure_image              || return 1
    run_container             || return 1
    report_url                || return 1
    log "=== DpadCloud VM bootstrap complete ==="
}

# -----------------------------------------------------------------------------
# Install this script as a systemd oneshot so it (re)runs at every boot and
# survives the phase-1 reboot. Used by the Vast on-start payload.
# -----------------------------------------------------------------------------
install_self() {
    log "installing systemd service ($SERVICE_NAME)"
    mkdir -p /opt/dpadcloud
    # Place a copy at the canonical path. Prefer the local repo checkout
    # (already correct, no network/CDN lag), then a sibling file (scp'd), then
    # the curl'd raw URL. Keeps the systemd ExecStart pointing at a known-good
    # script even on private repos or right after a push.
    if [ ! -f "$SCRIPT_PATH" ] || [ "$(readlink -f "$0" 2>/dev/null)" != "$SCRIPT_PATH" ]; then
        local src=""
        [ -f "$REPO_DIR/scripts/vm-bootstrap.sh" ] \
            && src="$REPO_DIR/scripts/vm-bootstrap.sh"
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
Description=DpadCloud VM bootstrap (modeset -> nvidia-container-toolkit -> build -> run)
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