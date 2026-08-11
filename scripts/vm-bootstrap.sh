#!/usr/bin/env bash
# =============================================================================
# DpadCloud — Vast KVM VM on-start bootstrap (multi-tenant: 1 user per GPU)
# =============================================================================
# Takes a fresh `vastai/kvm:ubuntu_cli_22.04-2025-11-21` VM from boot to N
# running `forcespt/dpadcloud-gaming` containers — one per GPU — each with its
# own Selkies tunnel URL printed to the console.
#
# Phases (each idempotent — safe to re-run, safe across the one reboot below):
#   1. ensure  nvidia_drm.modeset = Y   (REQUIRED for BOTH the gamescope
#          --backend headless path AND the DFP Xorg path; if the VM boots with
#          N, set it persistently + reload, or reboot once)
#   2. install nvidia-container-toolkit (needed for `docker run --gpus ...`)
#   3. pull  forcespt/dpadcloud-gaming:dpad-SteamOS  (or build; DPAD_BUILD=1)
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
#   DPAD_ISOLATION          cdi (default) | legacy  (cdi = per-GPU isolation
#                           via --runtime=nvidia + NVIDIA_VISIBLE_DEVICES=
#                           nvidia.com/gpu=i + --cap-add SYS_ADMIN, no
#                           --privileged; legacy = old --privileged --gpus
#                           device=i, no isolation, debug only)
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

# Default to the gamescope headless MVP (the validated path: full interactive
# Steam in the browser with video+audio+keyboard+mouse+gamepad, no DRM master ->
# N-on-N-GPUs multi-tenant). Set DPAD_GAMESCOPE=0 in /etc/environment to opt out
# to the DFP Xorg path (1 full-Steam session per VM, DRM master).
DPAD_GAMESCOPE="${DPAD_GAMESCOPE:-1}"

REPO_URL="${DPAD_REPO_URL:-https://github.com/ForcesPT/container-gaming.git}"
REPO_DIR="${DPAD_REPO_DIR:-/opt/dpadcloud/container-gaming}"
SCRIPT_PATH="/opt/dpadcloud/vm-bootstrap.sh"
# Image tag is selected dynamically by image_tag_for_gpu() in Phase 3:
# Blackwell (compute_cap >= 12 / sm_120+) -> :dpad-SteamOS-rtx50 (CUDA 12.8.1);
# else -> :dpad-SteamOS (CUDA 12.5.1). DPAD_IMAGE_TAG overrides both.
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
# Phase 0: NVIDIA driver = R580 LTS  (REQUIRED on the L4 oversubscription pool.
# The UpCloud AI/ML Ubuntu template ships driver 595.58.03, which produces
# SEVERE whole-frame flicker on the L4 headless stream — a same-box A/B proved
# 595 = unusable, 580 = only the mild pre-existing Steam-menu flicker (gamescope
# #1964, acceptable). See cloud/docs/DRIVER-CUDA-MATRIX.md §3/§5 +
# UPCLOUD-L4-DEPLOY-2026-07.md §13.9. Only 595 is downgraded; 580 is left alone,
# other versions are warned-but-left (don't break a working host). Idempotent —
# after the reboot this sees 580 and returns. The systemd service resumes after.)
# -----------------------------------------------------------------------------
# ---- R580 variant detection (proprietary vs open) ----
# gamescope headless does NOT support the NVIDIA proprietary driver (emersion,
# gamescope issue #255): Mesa EGL/glamor can't match the GPU PCI id → Steam
# CEF composites a BLACK screen while audio plays (the capture+encoder pipeline
# is fine — it's faithfully encoding black). The OPEN variant of R580
# (`nvidia-driver-580-open`, what UpCloud runs as 580.173.02-open) works — its
# Mesa EGL/GBM glamor path works in headless. This is a proprietary-vs-open
# VARIANT issue, NOT a version issue (R580 LTS is the deliberate choice —
# longest support to Aug 2028; R595 causes severe L4 flicker; R610 is NFB).
# Scaleway's "Ubuntu Noble GPU OS 12 passthrough" image ships the PROPRIETARY
# `nvidia-dkms-580-server` (580.126.20) → must swap to open (the SERVER driver
# build's EGL/GBM glamor black-screens gamescope-headless + crashes the
# gst-wayland-display compositor). OVH's "Ubuntu 24.04 - NVIDIA - v580" image
# ships the PLAIN DESKTOP PROPRIETARY `nvidia-driver-580` / `nvidia-dkms-580`
# (no -server, no -open) → does NOT need the swap: the DESKTOP proprietary
# build's render-node EGL/GBM glamor works for BOTH compositors — empirically
# validated 2026-08-11 on an OVH GRA11 l4-90 (580.159.03, license: NVIDIA):
#   - gamescope-headless + Steam -> frame mean 38.4/255 (content; the -server
#     variant's black screen is 0.3/255)
#   - wayland-display + sway + dpad-launcher picker -> the gst-wayland-display
#     compositor EGL-inits off /dev/dri/renderD128 (the wayland-1 socket
#     appears), sway stays up, the Electron picker renders + captures, + the
#     umu/GE-Proton Battle.net prefix init runs.
# So the swap is gated on the -580-server SERVER variant only; the plain desktop
# proprietary variant (OVH) is kept as-is (no swap, no reboot — saves ~6-10 min
# + a reboot on every OVH cold boot). UpCloud is already open post-595-downgrade.
# (The earlier §16.6 "OVH plain must swap" claim was a misdiagnosis: the §16.1
# gamescope-as-Wayland-client crash was reattributed in §16.2 to a Mesa
# EGL-vendor override leak, not the proprietary variant.) See
# cloud/docs/STATUS.md §4 #42 + cloud/docs/DEPLOY-RUNBOOK.md §5 +
# WAYLAND-ARCHITECTURE.md §16.6 (the now-disproven OVH-plain-swap rationale).
# NOTE: the script runs under `set -uo pipefail` (line ~61), so `grep -qE` in a
# pipeline is a trap: grep -q exits on the first match → SIGPIPE kills the
# upstream awk → pipefail propagates 141 → the function returns non-zero (false)
# even when it SHOULD return true (the proprietary packages ARE installed).
# That made ensure_driver_580 skip the swap on Scaleway → black screen. Fix:
# `grep -E ... >/dev/null` reads ALL input (no early exit → no SIGPIPE) so the
# pipeline exit is grep's real status (0=match) under pipefail.
has_proprietary_580() {
    # Proprietary (non-open) 580 installed? Two variants, DIFFERENT behavior:
    # - server: nvidia-*-580-server / libnvidia-*-580-server (Scaleway's image)
    #   → the SERVER driver build's EGL/GBM glamor is unusable in headless
    #   gamescope (black screen, gamescope #255, frame mean 0.3/255) AND crashes
    #   the gst-wayland-display compositor (EGL 'dri2 screen', §16.6) → MUST swap.
    # - plain:  nvidia-(dkms|driver)-580 (OVH's "Ubuntu 24.04 - NVIDIA - v580";
    #   no -server, no -open) → the DESKTOP driver build's render-node EGL/GBM
    #   glamor works for BOTH compositors (validated 2026-08-11, see the header
    #   comment) → NO swap, keep the proprietary driver.
    # nvidia-utils-580 / nvidia-kernel-common-580 / libnvidia-*-580 are SHARED
    # with the -open variant — NOT matched for the plain case, or an already-
    # open host (nvidia-dkms-580-open installed) would falsely read as
    # proprietary (those shared packages are deps of -open too).
    dpkg -l 2>/dev/null | awk '/^ii/{print $2}' \
        | grep -E 'nvidia-(dkms|driver|kernel-common|utils)-580-server$|^libnvidia-.*-580-server$|nvidia-(dkms|driver)-580$' >/dev/null
}
has_580_server() {
    # The -580-server variant (Scaleway). Its userspace (libnvidia-*-580-server,
    # nvidia-kernel-common-580-server) is SEPARATE from -open's + its packages
    # Conflict WITHOUT Replaces → the swap needs a broad purge first (apt can't
    # auto-resolve — observed live, §16.6). The plain variant (OVH) has clean
    # Conflicts+Replaces to -open + shared userspace → apt resolves it with NO
    # purge (§16.1). Used to choose the purge strategy in ensure_driver_580.
    dpkg -l 2>/dev/null | awk '/^ii/{print $2}' \
        | grep -E 'nvidia-(dkms|driver|kernel-common|utils)-580-server$|^libnvidia-.*-580-server$' >/dev/null
}
has_open_580() {
    dpkg -l 2>/dev/null | awk '/^ii/{print $2}' | grep -E 'nvidia-(dkms|driver)-580-open$' >/dev/null
}

# Install the OPEN variant of R580 LTS + set modeset=Y persistently + reboot
# ONCE to load it. Shared by the 595-downgrade + the proprietary-swap paths.
# `apt-get update` first so the open metapackage is in the index. FATAL on
# failure (return 1) so a broken/black-screen VM never goes `ready`.
install_open_580_and_reboot() {
    apt-get update >/dev/null 2>&1 || true
    # Install R580 LTS (open kernel modules). apt swaps the dkms metapackage.
    if ! DEBIAN_FRONTEND=noninteractive apt-get install -y nvidia-driver-580-open >/tmp/dpad-driver-580-open.log 2>&1; then
        err "nvidia-driver-580-open install failed (see /tmp/dpad-driver-580-open.log)"
        tail -20 /tmp/dpad-driver-580-open.log >&2 || true
        return 1
    fi
    # Set modeset=Y persistently so it's active right after the reboot (580 does
    # NOT enable modeset by default, unlike 595 — and gamescope headless needs it).
    echo 'options nvidia_drm modeset=Y' > /etc/modprobe.d/nvidia-drm-modeset.conf
    update-initramfs -u >/dev/null 2>&1 || true
    log "open R580 applied — rebooting ONCE to load the new driver"
    log "(the dpadcloud-bootstrap service will continue automatically after reboot)"
    sync; sleep 3; reboot; exit 0
}

ensure_driver_580() {
    local drv
    drv="$(nvidia-smi --query-gpu=driver_version --format=csv,noheader 2>/dev/null | head -1 | tr -d '[:space:]')"
    log "NVIDIA driver = ${drv:-?} (need 580.x on the L4 pool)"
    [ -z "$drv" ] && { log "no driver detected — skipping driver pin (template has none?)"; return 0; }
    case "$drv" in
        580.*)
            # Right BRANCH (R580 LTS). Check the VARIANT: a PROPRIETARY 580
            # (the -580-server variant on Scaleway, OR the plain nvidia-driver-580
            # on OVH's v580 image) renders a BLACK screen in headless gamescope +
            # crashes the gst-wayland-display compositor's EGL/GBM glamor → swap to
            # the open variant + reboot. The OPEN variant is the no-op (UpCloud
            # post-downgrade). FATAL on swap failure so a black-screen VM never
            # goes `ready`. See the §16.6 note in has_proprietary_580 above.
            if has_proprietary_580 && ! has_open_580; then
                # Two proprietary 580 variants exist, both → EGL/GBM glamor fails
                # in headless gamescope (black screen, gamescope #255) AND in the
                # gst-wayland-display compositor (EGL 'dri2 screen' crash, §16.6).
                # Both swap to nvidia-driver-580-open. The PURGE strategy differs.
                # The open driver is universal (works for gamescope-headless +
                # wayland-display), so always swap — a warm VM may host either
                # compositor via N-to-N reuse, and the host driver must support
                # both (the driver is VM-level; the compositor is per-container).
                if has_580_server; then
                    # Scaleway's image: nvidia-*-580-server. Its userspace
                    # (libnvidia-*-580-server, nvidia-kernel-common-580-server) is
                    # SEPARATE from -open's + the -server packages Conflict WITHOUT
                    # Replaces → apt can't auto-resolve (the install fails with a
                    # nvidia-kernel-common-580 conflict — observed in the reverted
                    # 1bb6f26 attempt). So PURGE the whole -580-server stack FIRST
                    # (the dkms/driver/kernel-common/utils metapackages + the
                    # libnvidia-*-580-server userspace libs), then install -open
                    # (which pulls the non-server userspace libs as deps).
                    log "driver is 580 PROPRIETARY (nvidia-dkms-580-server, e.g. Scaleway) — headless gamescope renders BLACK; swapping to nvidia-driver-580-open"
                    local purge_pkgs
                    # Extract the package NAME first (awk '{print $2}') then match
                    # `-580-server` on the NAME — anchoring `$` on the full dpkg -l
                    # line (the earlier `awk '/^ii.*-580-server$/{print $2}'`) was a
                    # bug: a dpkg line ends with the description ("NVIDIA DKMS
                    # package"), NOT `-580-server`, so purge_pkgs was EMPTY → the
                    # purge was skipped → the install hit the nvidia-kernel-common-580
                    # conflict. Match any nvidia/libnvidia package whose NAME
                    # contains `-580-server` (captures the dkms/driver/kernel-common/
                    # utils/headless/kernel-source/compute-utils metapackages + the
                    # libnvidia-*-580-server:amd64 userspace libs + the firmware pkg).
                    purge_pkgs="$(dpkg -l 2>/dev/null | awk '/^ii/{print $2}' | grep -E '^(nvidia|libnvidia)-.*-580-server' | sort -u | paste -sd ' ')"
                    if [ -n "$purge_pkgs" ]; then
                        log "purging proprietary -580-server packages: $purge_pkgs"
                        if ! DEBIAN_FRONTEND=noninteractive apt-get purge -y $purge_pkgs >/tmp/dpad-driver-580-purge.log 2>&1; then
                            err "purge of proprietary -580-server packages failed (see /tmp/dpad-driver-580-purge.log)"
                            tail -20 /tmp/dpad-driver-580-purge.log >&2 || true
                            return 1
                        fi
                    fi
                else
                    # OVH's "Ubuntu 24.04 - NVIDIA - v580" image: the PLAIN
                    # DESKTOP proprietary nvidia-driver-580 / nvidia-dkms-580
                    # (no -server, no -open). Unlike the -580-server SERVER build
                    # (Scaleway, whose EGL/GBM glamor black-screens gamescope-
                    # headless + crashes the compositor), the DESKTOP proprietary
                    # build's render-node EGL/GBM glamor works for BOTH
                    # compositors — empirically validated 2026-08-11 on an OVH
                    # GRA11 l4-90 (580.159.03, license: NVIDIA):
                    #   - gamescope-headless + Steam  -> frame mean 38.4/255
                    #     (content; the -server variant's black screen is 0.3/255)
                    #   - wayland-display + sway + dpad-launcher picker -> the
                    #     gst-wayland-display compositor EGL-inits off
                    #     /dev/dri/renderD128 (the wayland-1 socket appears),
                    #     sway stays up, the Electron picker renders + captures,
                    #     + umu/GE-Proton Battle.net prefix init runs.
                    # No swap, no reboot needed → KEEP the proprietary driver
                    # (saves ~6-10 min + a reboot on every OVH cold boot). The
                    # §16.6 "OVH plain must swap" claim was a misdiagnosis: the
                    # §16.1 gamescope-as-client crash was reattributed in §16.2
                    # to a Mesa EGL-vendor override leak, not the variant.
                    log "driver is 580 PROPRIETARY (plain desktop nvidia-driver-580, e.g. OVH v580 image) — render-node EGL/GBM glamor works for both compositors (validated 2026-08-11 on OVH l4-90); keeping the proprietary driver (no swap, no reboot)"
                    return 0
                fi
                # Only the -580-server (Scaleway) branch reaches here — it purged
                # above + now swaps to the open variant + reboots.
                install_open_580_and_reboot || return 1
                return 1   # unreachable (install_open_580_and_reboot reboots or returns 1)
            fi
            log "driver already 580 LTS (open variant) — good"
            return 0
            ;;
        595.*) : ;;  # the known-bad flicker driver — downgrade below
        *)    log "WARNING: driver $drv is not 580 or 595 — leaving it (only 595 is auto-downgraded)"; return 0 ;;
    esac

    log "driver is 595 (severe L4 flicker) — downgrading to nvidia-driver-580-open + reboot"
    # Remove the version-pinning package(s) so apt is free to install 580.
    local pin
    pin="$(dpkg -l 2>/dev/null | awk '/^ii.*nvidia-driver-pinning/{print $2}' | paste -sd ' ')"
    if [ -n "$pin" ]; then
        log "removing pinning package(s): $pin"
        DEBIAN_FRONTEND=noninteractive apt-get remove -y $pin >/dev/null 2>&1 || true
    fi
    install_open_580_and_reboot || return 1
}

# -----------------------------------------------------------------------------
# Phase 0a: disable unattended-upgrades / apt auto-upgrades (CRITICAL for live
# sessions). Ubuntu's apt-daily-upgrade.timer runs unattended-upgrades, which
# upgrades packages — incl. the KERNEL + libc6 + openssh — and needrestart then
# issues `systemctl daemon-reexec` + restarts containerd/docker/nvidia-*, which
# KILLS every running game container mid-session (observed live 2026-07-30:
# dpad-slot-0 died exit 137 ~2 min after DPAD_READY; a new kernel was also staged,
# which would shift the NVIDIA driver on the next reboot). On a gaming VM we own
# the driver + kernel image; apt must NEVER touch them under a live session.
# Idempotent + safe to run first (needs nothing else set up).
# -----------------------------------------------------------------------------
ensure_no_auto_updates() {
    log "disabling unattended-upgrades / apt auto-upgrades (protects live sessions)"
    # Stop + mask the apt periodic upgrade timers/services so they can't fire.
    systemctl disable --now apt-daily.timer apt-daily-upgrade.timer 2>/dev/null || true
    systemctl mask apt-daily-upgrade.service apt-daily-upgrade.timer \
        unattended-upgrades.service 2>/dev/null || true
    # The apt periodic flags are the source of truth for unattended-upgrades.
    cat > /etc/apt/apt.conf.d/20auto-upgrades <<'EOF'
// DpadCloud: no automatic package lists/installs on gaming VMs (would restart
// services / shift the kernel + NVIDIA driver under live sessions).
APT::Periodic::Update-Package-Lists "0";
APT::Periodic::Unattended-Upgrade "0";
APT::Periodic::Download-Upgradeable-Packages "0";
APT::Periodic::AutocleanInterval "0";
EOF
    # needrestart (pulled in by unattended-upgrades) is the actual trigger of
    # the daemon-reexec service-restart cascade. Tell it to LIST services that
    # need a restart but NOT to restart them ('l' = list-only). Manual `apt`
    # calls are unaffected; only the automatic churn is suppressed.
    if dpkg-query -W -f='${Status}' needrestart >/dev/null 2>&1; then
        mkdir -p /etc/needrestart/conf.d
        cat > /etc/needrestart/conf.d/99-dpad.conf <<'EOF'
# DpadCloud: never auto-restart services (would kill live game containers).
$nrconf{restart} = 'l';
EOF
        log "needrestart set to restart-mode=list (no auto-restart)"
    fi
    log "unattended-upgrades / apt auto-upgrades disabled"
    return 0
}

# -----------------------------------------------------------------------------
# Phase 1: nvidia_drm.modeset = Y  (REQUIRED for gamescope --backend headless
# on NVIDIA — without it vkCreateDevice fails (-7) / 'Failed to create backend' —
# AND for the DFP Xorg / DRM-master path. Steam UI needs KMS either way.)
# -----------------------------------------------------------------------------
ensure_modeset() {
    local cur
    cur="$(cat /sys/module/nvidia_drm/parameters/modeset 2>/dev/null || true)"
    log "nvidia_drm.modeset = ${cur:-?} (need Y)"
    [ "$cur" = "Y" ] && { log "modeset already Y"; return 0; }

    # Some images ship a CONFLICTING nvidia-drm modeset=0 in another modprobe.d
    # file (e.g. Hyperstack's R570 image: /etc/modprobe.d/nvidia-graphics-drivers-
    # kms.conf has "options nvidia-drm modeset=0"). modprobe.d files are processed
    # in lexical order + the LAST option wins → "nvidia-graphics-..." (modeset=0)
    # is processed AFTER "nvidia-drm-modeset.conf" (modeset=Y) → it OVERRIDES our
    # modeset=Y on boot. With modeset=0 winning, the reboot the function below
    # triggers never applies modeset=Y → the oneshot re-runs post-reboot, sees
    # modeset still N, + reboots again → a ~30s reboot loop (the VM never reaches
    # vm-ready). Neutralize ANY nvidia_drm/nvidia-drm modeset=0 in modprobe.d so
    # the modeset=Y we write below is the effective setting (validated on Hyperstack
    # 2026-08-11, R570 image nvidia-graphics-drivers-kms.conf modeset=0).
    local f
    for f in /etc/modprobe.d/*.conf; do
        [ -f "$f" ] || continue
        grep -qE 'nvidia[_-]drm[[:space:]]+modeset=0' "$f" 2>/dev/null || continue
        sed -i -E 's/(nvidia[_-]drm[[:space:]]+modeset=)0/\11/g' "$f"
        log "neutralized nvidia_drm modeset=0 in $f (rewrote to modeset=1)"
    done

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
    # Regenerate the CDI spec BEFORE the GPU-visibility check. After a driver
    # swap (e.g. the proprietary -> open R580 swap on Scaleway, ensure_driver_580),
    # the OLD CDI spec still references the previous driver's
    # libcuda.so.<old-version> (now gone) -> both `--gpus all` AND the CDI
    # `--device nvidia.com/gpu=i` path fail to mount it -> the GPU check below
    # fails AND dpad-launch-session's container can't start (observed live: after
    # the proprietary->open swap+reboot, the stale CDI referenced
    # libcuda.so.580.126.20 while the host had 580.178.04 -> every docker run
    # failed `failed to fulfil mount request: open .../libcuda.so.580.126.20: no
    # such file or directory`). Regenerating the CDI spec here (reading the
    # now-loaded driver) refreshes the libcuda path so both paths work.
    # Idempotent; also re-runs on every boot (keeps CDI in sync with the driver).
    mkdir -p /etc/cdi
    if nvidia-ctk cdi generate --output=/etc/cdi/nvidia.yaml >/tmp/cdi-gen.log 2>&1; then
        log "CDI spec generated ($(nvidia-ctk cdi list 2>/dev/null | grep -c 'nvidia.com/gpu=') devices)"
    else
        err "CDI spec generation failed (see /tmp/cdi-gen.log) — CDI launch will not work"
    fi
    if ! docker run --rm --gpus all nvidia/cuda:12.8.1-runtime-ubuntu24.04 nvidia-smi >/dev/null 2>&1; then
        err "container cannot see the GPU after nvidia-container-toolkit install"
        docker run --rm --gpus all nvidia/cuda:12.8.1-runtime-ubuntu24.04 nvidia-smi || true
        return 1
    fi
    log "GPU visible inside a container (nvidia-container-toolkit OK)"
}

# -----------------------------------------------------------------------------
# -----------------------------------------------------------------------------
# Phase 2c: Docker storage on XFS with project quotas (per-container --storage-opt size)
# -----------------------------------------------------------------------------
# Ephemeral ("no storage") sessions cap each container's rootfs at 200 GB via
# `docker run --storage-opt size=200g`. That ONLY enforces when Docker's backing
# filesystem supports project quotas — the default ext4 root does NOT (the
# option is silently accepted but NO cap is applied). So we move /var/lib/docker
# onto an XFS file (loopback, ON THE VM's OWN BOOT DISK — no extra provider
# storage needed, so it works on ephemeral-disk providers like MassedCompute)
# formatted + mounted with `prjquota`. Then --storage-opt size enforces AND
# `df /` inside a capped container reports the quota — Steam's storage UI shows
# ~200 GB, and a user physically can't write past it.
#
# Idempotent: a re-run (e.g. after the driver-downgrade reboot) no-ops once
# /var/lib/docker is on XFS prjquota. Runs AFTER ensure_nct (Docker installed +
# runtime configured) and BEFORE ensure_image (so the image is pulled INTO the
# XFS). The fstab entry re-mounts it at every boot; a docker.service drop-in
# (RequiresMountsFor) orders Docker strictly after the mount.
ensure_docker_xfs_quota() {
    local img="/var/lib/dpad-docker-xfs.img"
    # Already on XFS pquota? (idempotent — true after a reboot re-run.) Also
    # short-circuit when the XFS img + fstab entry already exist (the setup is
    # done) even if a transient findmnt/mountpoint race during a daemon-reexec
    # makes the first check miss — re-running would `systemctl stop docker` and
    # KILL live session containers on an already-correct host.
    if { mountpoint -q /var/lib/docker 2>/dev/null \
         && findmnt -no OPTIONS /var/lib/docker 2>/dev/null | grep -qw pquota; } \
       || { [ -f "$img" ] && grep -q "^[^#].* /var/lib/docker " /etc/fstab 2>/dev/null; }; then
        log "Docker storage already on XFS pquota (/var/lib/docker) — good"
        return 0
    fi
    command -v mkfs.xfs >/dev/null 2>&1 || {
        log "installing xfsprogs (mkfs.xfs)"
        apt-get update >/dev/null 2>&1 || true
        DEBIAN_FRONTEND=noninteractive apt-get install -y xfsprogs >/tmp/dpad-xfsprogs.log 2>&1 \
            || { err "xfsprogs install failed (see /tmp/dpad-xfsprogs.log)"; return 1; }
    }

    # XFS file on the VM's own boot disk (the root fs). Leave a 60 GB headroom
    # for the OS + Docker binaries + XFS metadata; the rest is the Docker store
    # (the image + N capped container writable layers). Sparse, so it only
    # consumes boot-disk space as Docker writes.
    local root_gb xfs_gb headroom
    root_gb=$(df --output=size / | awk 'NR==2{print int($1/1024/1024)}')
    # Minimum root disk to hold the OS + the Docker image (~9 GB) + a small
    # container writable layer. 30 GB is the floor (the :dpad-SteamOS image alone
    # is ~8.7 GB) — below this we FATAL (can't even fit the image). 30..120 GB
    # roots (e.g. Hyperstack's n3-L40x1 root = ~95 GB, which failed the old 120 GB
    # floor with "boot disk too small" + blocked the whole bootstrap) now proceed
    # with a smaller XFS. The loopback is sparse; the --storage-opt 200 GB cap is
    # still enforced by XFS pquota, but the effective cap is the XFS filesystem
    # size (the backing) — fine for persistent-volume users whose games live on
    # the volume; ephemeral-only users get a smaller usable cap. The full 725 GB
    # ephemeral-disk support (mkfs the secondary ephemeral block device + mount
    # /var/lib/docker on it directly) is a tested follow-up — needs a live VM to
    # verify the device-detection filters (no-fs + unmounted + not-boot + whole-
    # disk) before shipping, to avoid mkfs'ing the wrong device.
    [ "${root_gb:-0}" -lt 30 ] 2>/dev/null \
        && { err "boot disk too small for XFS Docker store (${root_gb:-?} GB; need >=30 GB to hold the image)"; return 1; }
    # Headroom for the OS + Docker binaries + XFS metadata. 60 GB on large roots
    # (preserves the existing sizing on OVH 387 GB / MassedCompute 625 GB); shrink
    # to 12 GB on small roots (<200 GB, e.g. Hyperstack 95 GB) so xfs_gb stays
    # positive + usable (95 - 12 = 83 GB XFS, ~74 GB usable after the image).
    headroom=60
    [ "$root_gb" -lt 200 ] 2>/dev/null && headroom=12
    xfs_gb=$(( root_gb - headroom ))
    log "setting up Docker storage on XFS pquota: ${img} (${xfs_gb} GB on the boot disk, root=${root_gb} GB, headroom=${headroom} GB)"

    systemctl stop docker 2>/dev/null || true
    # Preserve any existing Docker state (usually just an init scaffold — the
    # image is pulled AFTER this, so /var/lib/docker is typically empty here).
    if [ -d /var/lib/docker ] && [ ! -m /var/lib/docker ]; then
        mv /var/lib/docker /var/lib/docker.pre-xfs
    fi
    mkdir -p /var/lib/docker

    if [ ! -f "$img" ]; then
        truncate -s "${xfs_gb}G" "$img" || { err "truncate $img failed"; return 1; }
        # reflink=0: XFS reflink (CoW) can conflict with project-quota enforcement
        # on some kernels — disable it so pquota caps reliably.
        # ftype=1: overlay2 REQUIRES d_type support (ftype=1) — Docker's project-
        # quota detection + the overlay2 driver both need it. With reflink=0 mkfs
        # can default ftype=0, which breaks overlay2/quota, so set it explicitly.
        mkfs.xfs -m reflink=0 -n ftype=1 -q "$img" || { err "mkfs.xfs $img failed"; return 1; }
    fi

    # Mount now (loop,pquota — the canonical XFS project-quota option) + persist
    # via fstab (re-mounts at every boot).
    mount -t xfs -o loop,pquota "$img" /var/lib/docker \
        || { err "XFS loop mount of $img failed"; return 1; }
    if ! grep -q "^[^#]*[[:space:]]/var/lib/docker[[:space:]]" /etc/fstab 2>/dev/null; then
        echo "${img} /var/lib/docker xfs loop,pquota,defaults 0 0" >> /etc/fstab
    fi
    # Order Docker strictly after the mount (fstab mounts are local-fs, before
    # Docker, but be explicit so a race can't start Docker on the bare dir).
    # RequiresMountsFor is a [Unit] directive (NOT [Service] — systemd ignores
    # it there with 'Unknown key name'). Orders Docker strictly after the mount.
    mkdir -p /etc/systemd/system/docker.service.d
    printf '[Unit]\nRequiresMountsFor=/var/lib/docker\n' \
        > /etc/systemd/system/docker.service.d/dpad-xfs.conf
    systemctl daemon-reload

    # Restore any pre-existing Docker state into the XFS.
    if [ -d /var/lib/docker.pre-xfs ]; then
        cp -a /var/lib/docker.pre-xfs/. /var/lib/docker/ 2>/dev/null || true
        rm -rf /var/lib/docker.pre-xfs
    fi

    # Docker 29+ defaults to the containerd image store (overlayfs snapshotter),
    # which does NOT support --storage-opt size (project quotas) — it silently
    # ignores the option (no cap, no error). Disable it so Docker uses the legacy
    # overlay2 graphdriver, which enforces --storage-opt size on XFS pquota.
    # Merge into the existing daemon.json (ensure_nct wrote the nvidia runtime).
    if ! python3 -c 'import json,os; p="/etc/docker/daemon.json"; d=json.load(open(p)) if os.path.exists(p) else {}; d.setdefault("features",{})["containerd-snapshotter"]=False; json.dump(d,open(p,"w"),indent=2)' 2>/tmp/dpad-daemon-merge.log; then
        err "failed to disable containerd-snapshotter in daemon.json (see /tmp/dpad-daemon-merge.log)"; return 1
    fi
    systemctl start docker || { err "docker failed to start on the XFS store (legacy overlay2)"; return 1; }
    docker pull alpine >/dev/null 2>&1 || true
    # Cap test: a 256 MB-capped container MUST reject a 300 MB write. XFS pquota
    # enforces DIRECTLY (verified: xfs_quota limit -p stops dd at the limit), but
    # Docker's overlay2 must APPLY it to the container's upper dir. FATAL: an
    # uncapped ephemeral VM must never ship (a user could fill the host disk).
    log "verifying --storage-opt size enforces (256m cap vs 300M write)…"
    # Capture dd's FULL output — dd prints 'No space left on device' BEFORE its
    # summary line, so piping through `tail -N` drops the error and the grep
    # misses it (a working cap then falsely reported UNCAPPED — observed live
    # 2026-07-30). NOT piping through tail means `dd_rc=$?` inside the container
    # is dd's REAL exit code (ENOSPC => 1), not tail's.
    local probe
    probe=$(docker run --rm --storage-opt size=256m alpine \
        sh -c 'df -m / | tail -1; echo --- dd ---; dd if=/dev/zero of=/captest bs=1M count=300 2>&1; echo dd_rc=$?' 2>&1)
    log "CAP-PROBE: ${probe}"
    if printf '%s\n' "$probe" | grep -q 'No space left on device'; then
        log "Docker storage on XFS pquota OK — --storage-opt size enforces (per-container rootfs cap)"
        return 0
    fi
    err "XFS pquota mounted but --storage-opt size NOT enforced — VM UNCAPPED (FATAL)"
    err "  findmnt: $(findmnt -no SOURCE,FSTYPE,OPTIONS /var/lib/docker 2>/dev/null)"
    err "  xfs_info: $(xfs_info /var/lib/docker 2>&1 | tr '\n' ' ' | grep -oiE 'reflink=[0-9]|projid32bit=[0-9]|ftype=[0-9]' | tr '\n' ' ')"
    err "  xfs_quota: $(xfs_quota -x -c state /var/lib/docker 2>&1 | grep -iE 'project|quota' | tr '\n' ' ' | cut -c1-200)"
    err "  docker info: $(docker info 2>/dev/null | grep -iE 'storage driver|backing|d_type|quota|docker root' | tr '\n' ' ')"
    err "  daemon.json: $(cat /etc/docker/daemon.json 2>/dev/null | tr '\n' ' ')"
    err "  docker journal: $(journalctl -u docker --no-pager -n 6 2>/dev/null | tr '\n' ' ' | cut -c1-300)"
    err "ephemeral sessions cannot ship uncapped — refusing to mark the VM ready"
    return 1
}

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

# Pick the image tag: DPAD_IMAGE_TAG override wins; else Blackwell
# (compute_cap major >= 12, sm_120+) -> :dpad-SteamOS-rtx50 (CUDA 12.8.1);
# else the regular :dpad-SteamOS (CUDA 12.5.1). Mirrors detect_build_args'
# CUDA-version pick so the pulled tag always matches the GPU arch.
image_tag_for_gpu() {
    [ -n "${DPAD_IMAGE_TAG:-}" ] && { echo "${DPAD_IMAGE_TAG}"; return; }
    local cc major
    cc="$(nvidia-smi --query-gpu=compute_cap --format=csv,noheader 2>/dev/null | head -1 | tr -d ' ')"
    major="${cc%%.*}"
    if [ -n "$major" ] && [ "$major" -ge 12 ] 2>/dev/null; then
        echo "forcespt/dpadcloud-gaming:dpad-SteamOS-rtx50"
    else
        echo "forcespt/dpadcloud-gaming:dpad-SteamOS"
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
    local img_tag; img_tag="$(image_tag_for_gpu)"
    log "selected image: ${img_tag}"
    if [ "${DPAD_BUILD:-0}" = "1" ]; then
        ensure_repo || return 1
        local cuda_ver cuda_pkg
        read -r cuda_ver cuda_pkg <<< "$(detect_build_args)"
        log "building image ${img_tag} (CUDA $cuda_ver / $cuda_pkg)"
        docker build --build-arg "CUDA_VERSION=${cuda_ver}" --build-arg "CUDA_PKG=${cuda_pkg}" \
            -t "${img_tag}" "$REPO_DIR" || { err "docker build failed"; return 1; }
    else
        log "pulling image ${img_tag} from Docker Hub"
        docker pull "${img_tag}" || { err "docker pull failed"; return 1; }
    fi
    echo "${img_tag}" > "$TAG_FILE"
    log "image ready: ${img_tag}"

    # Fetch the repo entrypoint.sh to the host so dpad-launch-session can
    # bind-mount it over the image's baked entrypoint — lets entrypoint hotfixes
    # go live WITHOUT an image rebuild + Docker Hub push (an owner step that's
    # currently blocked). Best-effort: if the fetch fails, launches fall back to
    # the image's baked entrypoint.
    mkdir -p /opt/dpadcloud
    if curl -fsSL https://raw.githubusercontent.com/ForcesPT/container-gaming/main/entrypoint.sh \
        -o /opt/dpadcloud/entrypoint.sh 2>/dev/null; then
        chmod +x /opt/dpadcloud/entrypoint.sh 2>/dev/null || true
        log "entrypoint.sh fetched to /opt/dpadcloud (bind-mountable hotfix path)"
    else
        rm -f /opt/dpadcloud/entrypoint.sh 2>/dev/null || true
        log "entrypoint.sh fetch failed — launches will use the image's baked entrypoint"
    fi
    # Same hotfix path for evdev_bridge.py (the js_event→input_event translator,
    # started by the entrypoint ONLY in evdev mode). Lets bridge hotfixes ship
    # without an image rebuild. Best-effort: if the fetch fails, the entrypoint
    # runs the image's baked bridge.
    if curl -fsSL https://raw.githubusercontent.com/ForcesPT/container-gaming/main/scripts/evdev_bridge.py \
        -o /opt/dpadcloud/evdev_bridge.py 2>/dev/null; then
        chmod +x /opt/dpadcloud/evdev_bridge.py 2>/dev/null || true
        log "evdev_bridge.py fetched to /opt/dpadcloud (bind-mountable hotfix path)"
    else
        rm -f /opt/dpadcloud/evdev_bridge.py 2>/dev/null || true
        log "evdev_bridge.py fetch failed — evdev mode will use the image's baked bridge"
    fi
    # Same hotfix path for extract-nvrtc.sh (the entrypoint's FIRST action calls
    # it to swap the bundled libnvrtc 11.4 → 12.9.86 so cudaconvert can JIT for
    # sm_89 L4/Ada + sm_120 Blackwell — without it the video pipeline produces no
    # capturable video). Lets the NVRTC fix ship to EXISTING (pre-bake) images
    # without an image rebuild + Docker Hub push. Best-effort: if the fetch
    # fails, the entrypoint runs the image's baked script (a no-op on a baked
    # image; on a stale image the boot continues with the NVRTC error).
    if curl -fsSL https://raw.githubusercontent.com/ForcesPT/container-gaming/main/scripts/extract-nvrtc.sh \
        -o /opt/dpadcloud/extract-nvrtc.sh 2>/dev/null; then
        chmod +x /opt/dpadcloud/extract-nvrtc.sh 2>/dev/null || true
        log "extract-nvrtc.sh fetched to /opt/dpadcloud (bind-mountable hotfix path)"
    else
        rm -f /opt/dpadcloud/extract-nvrtc.sh 2>/dev/null || true
        log "extract-nvrtc.sh fetch failed — entrypoint will use the image's baked script"
    fi
    # Same hotfix path for dpad_input_patch.py (auto-loaded at Python startup via
    # dpad_input_patch.pth in site-packages; the §17.2 lazy-XTest input open +
    # the start_cursor_monitor guard live here). Lets the cursor-monitor + lazy-
    # input fixes ship to EXISTING (pre-bake) images without an image rebuild.
    # Best-effort: if the fetch fails, the image's baked patch runs (on the
    # wayland-display path the cursor monitor crashes until the rebuild bakes
    # the guard — the stream still works, it's a logged thread exception).
    if curl -fsSL https://raw.githubusercontent.com/ForcesPT/container-gaming/main/scripts/dpad_input_patch.py \
        -o /opt/dpadcloud/dpad_input_patch.py 2>/dev/null; then
        log "dpad_input_patch.py fetched to /opt/dpadcloud (bind-mountable hotfix path)"
    else
        rm -f /opt/dpadcloud/dpad_input_patch.py 2>/dev/null || true
        log "dpad_input_patch.py fetch failed — launches use the image's baked patch"
    fi
}

# -----------------------------------------------------------------------------
# Phase 4b (v2 warm-VM): start the NVIDIA MPS daemon for GPU oversubscription.
# MPS lets N containers share one GPU's SMs concurrently (the v2 tier slice —
# 3:1 Casual, 2:1 Standard, …). The daemon runs as root on the host; per-session
# containers join it via CUDA_MPS_PIPE_DIRECTORY (dpad-launch-session sets that
# env on each container). Best-effort: 1:1 (single container) works without MPS,
# so a failure here only warns (the first warm-pool test is 1:1 anyway).
# -----------------------------------------------------------------------------
ensure_mps() {
    export CUDA_MPS_PIPE_DIRECTORY="${CUDA_MPS_PIPE_DIRECTORY:-/tmp/nvidia-mps}"
    export CUDA_MPS_LOG_DIRECTORY="${CUDA_MPS_LOG_DIRECTORY:-/tmp/nvidia-mps-log}"
    mkdir -p "$CUDA_MPS_PIPE_DIRECTORY" "$CUDA_MPS_LOG_DIRECTORY"
    if ! command -v nvidia-cuda-mps-control >/dev/null 2>&1; then
        log "MPS: nvidia-cuda-mps-control not found — skipping (1:1 still works; install nvidia-cuda-toolkit for oversubscription)"
        return 0
    fi
    if pgrep -x nvidia-cuda-mps-control >/dev/null 2>&1; then
        log "MPS daemon already running"
        return 0
    fi
    # Persistence mode first (MPS wants it).
    nvidia-smi -pm 1 >/dev/null 2>&1 || true
    if nvidia-cuda-mps-control -d 2>/dev/null; then
        log "MPS daemon started (pipe $CUDA_MPS_PIPE_DIRECTORY) — oversubscription ready"
    else
        log "MPS: nvidia-cuda-mps-control -d failed — continuing (1:1 still works)"
    fi
}

# v2 warm-VM mode: DPAD_WARM_VM=1 (default) leaves the VM WARM after host prep
# (Docker + image + MPS ready) with 0 session containers — a session is a fresh
# container launched by dpad-launch-session with the user's volume (you can't
# bind-mount a volume into a running container). DPAD_WARM_VM=0 keeps the v1
# 1:1 flow (run N containers at boot + report Selkies URLs) for back-compat.
DPAD_WARM_VM="${DPAD_WARM_VM:-1}"

# v2 VM-ready marker: touched once host prep + image + MPS are done (warm-VM
# mode). The dpadplay bootstrap worker polls for this file instead of the old
# docker-ps-count heuristic (a warm VM has 0 running session containers).
VM_READY_FILE="/opt/dpadcloud/vm-ready"

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
    local tcp_var="VAST_TCP_PORT_${port}"
    local udp_var="VAST_UDP_PORT_${port}"
    local tcp_ext="${!tcp_var:-}"
    local udp_ext="${!udp_var:-}"
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

    # Vast forbids the same port as BOTH tcp and udp, so a session exposes EITHER
    # -p port:port (tcp) OR -p port:port/udp (udp, lower latency). Require at least
    # one; UDP is preferred when both are somehow set (other providers allow both).
    if [ -z "$tcp_ext" ] && [ -z "$udp_ext" ]; then
        err "VAST_TCP_PORT_${port} and VAST_UDP_PORT_${port} are both empty — port ${port} was NOT exposed at VM creation."
        err "Skipping $name (GPU $idx). Expose -p ${port}:${port} (tcp) or -p ${port}:${port}/udp (lower latency) to serve this GPU."
        return 0   # not fatal — serve as many GPUs as we have exposed ports for
    fi

    local -a iso=()
    while IFS= read -r a; do iso+=( "$a" ); done < <(isolation_args "$idx")

    # Resource partitioning (CPU + RAM) — host divided evenly across the launched
    # containers minus a reserve; computed by compute_session_resources(). The
    # GPU is already 1:1 per container via CDI. Mode = DPAD_CPU_MODE (quota
    # default). per-session overrides: DPAD_CPUS_PER_SESSION / DPAD_MEM_PER_SESSION.
    local -a res=()
    if [ "${SESSION_CPUS:-0}" -gt 0 ] 2>/dev/null; then
        case "${SESSION_CPU_MODE:-quota}" in
            pinned)
                local cs=$(( ${SESSION_RESERVE_CPUS:-0} + idx * SESSION_CPUS ))
                res+=( --cpuset-cpus="${cs}-$(( cs + SESSION_CPUS - 1 ))" ) ;;
            shares)
                res+=( --cpu-shares=$(( SESSION_CPUS * 1024 )) ) ;;
            quota|*)
                res+=( --cpus="${SESSION_CPUS}" ) ;;
        esac
    fi
    if [ "${SESSION_MEM_MB:-0}" -gt 0 ] 2>/dev/null; then
        res+=( --memory="${SESSION_MEM_MB}m" --memory-swap="${SESSION_MEM_MB}m" )
        # soft floor: the kernel reclaims elsewhere before OOM-killing this cgroup
        res+=( --memory-reservation="$(( SESSION_MEM_MB * 90 / 100 ))m" )
    fi
    res+=( --pids-limit="${DPAD_PIDS_LIMIT:-4096}" )
    log "launching $name : GPU $idx, coturn ${port} -> tcp_ext ${tcp_ext:-<none>}, udp_ext ${udp_ext:-<none>}, public ${pub_ip:-<?>}, resources: ${SESSION_CPUS:-0} cpu (${SESSION_CPU_MODE:-quota}) / ${SESSION_MEM_MB:-0}MB"
    # DPAD_GAMESCOPE=1 switches the container to the gamescope headless + Steam
    # multi-tenant path (no DRM master). Pass-through DPAD_GAMESCOPE/DPAD_STEAM_ARGS
    # so the on-start can opt in without editing the bootstrap.
    local -a gs_env=()
    [ -n "${DPAD_GAMESCOPE:-}" ]  && gs_env+=( -e "DPAD_GAMESCOPE=${DPAD_GAMESCOPE}" )
    [ -n "${DPAD_STEAM_ARGS:-}" ] && gs_env+=( -e "DPAD_STEAM_ARGS=${DPAD_STEAM_ARGS}" )
    # Map + pass whichever protocol(s) are exposed. coturn listens both tcp+udp
    # internally; only the mapped protocol is reachable externally. With both
    # WebRTC peers on the same coturn the relay short-circuits internally, so only
    # the listen port needs mapping (no relay port range to expose).
    local -a port_args=()
    [ -n "$tcp_ext" ] && port_args+=( -p "${port}:${port}"       -e "DPAD_TURN_EXTERNAL_PORT=${tcp_ext}" )
    [ -n "$udp_ext" ] && port_args+=( -p "${port}:${port}/udp" -e "DPAD_TURN_UDP_EXTERNAL_PORT=${udp_ext}" )
    docker run -d --name "$name" \
        "${iso[@]}" --shm-size=2g --ulimit nofile=1048576:1048576 \
        "${res[@]}" \
        "${port_args[@]}" \
        -e DPAD_PROVIDER=runpod -e DPAD_COTURN_PORT="$port" \
        -e "DPAD_TURN_PUBLIC_IP=${pub_ip}" \
        -e "SUNSHINE_PASSWORD=${sess_pass}" \
        -e "SELKIES_BASIC_AUTH_USER=${SELKIES_USER}" \
        -e "SELKIES_BASIC_AUTH_PASSWORD=${sess_pass}" \
        "${gs_env[@]}" \
        "$img_tag" || { err "docker run $name failed"; return 1; }
    log "$name launched (login ${SELKIES_USER}/${sess_pass})"
}

# Compute the per-container CPU + RAM slice for multi-tenant partitioning.
# The host's CPU + RAM are divided evenly across the N launched containers (1
# per GPU), minus a host reserve (docker/sshd/kernel). GPU itself is already
# 1:1 isolated per container via CDI, so only CPU + RAM are partitioned here.
#   per_cpus = (nproc - DPAD_RESERVE_CPUS)   / N
#   per_mem  = (MemTotal - DPAD_RESERVE_MEM_MB) / N
# Overrides: DPAD_CPUS_PER_SESSION / DPAD_MEM_PER_SESSION force a fixed slice.
# CPU mode: DPAD_CPU_MODE=quota (default, --cpus hard cap) | pinned (--cpuset-cpus)
# | shares (--cpu-shares, soft, borrows idle cores). Sets SESSION_CPUS,
# SESSION_MEM_MB, SESSION_CPU_MODE, SESSION_RESERVE_CPUS for run_container_for.
compute_session_resources() {
    local n="$1"
    local total_cpus total_mem_mb reserve_cpus reserve_mem
    total_cpus="$(nproc 2>/dev/null || echo 0)"
    total_mem_mb="$(awk '/MemTotal/{print int($2/1024)}' /proc/meminfo 2>/dev/null || echo 0)"
    reserve_cpus="${DPAD_RESERVE_CPUS:-2}"
    reserve_mem="${DPAD_RESERVE_MEM_MB:-4096}"
    local per_cpus per_mem
    if [ -n "${DPAD_CPUS_PER_SESSION:-}" ]; then
        per_cpus="${DPAD_CPUS_PER_SESSION}"
    elif [ "${n:-0}" -gt 0 ] 2>/dev/null; then
        per_cpus=$(( (total_cpus - reserve_cpus) / n ));
        [ "${per_cpus}" -lt 1 ] && per_cpus=1
    else
        per_cpus=0
    fi
    if [ -n "${DPAD_MEM_PER_SESSION:-}" ]; then
        per_mem="${DPAD_MEM_PER_SESSION}"
    elif [ "${n:-0}" -gt 0 ] 2>/dev/null; then
        per_mem=$(( (total_mem_mb - reserve_mem) / n ));
        [ "${per_mem}" -lt 1024 ] && per_mem=1024
    else
        per_mem=0
    fi
    SESSION_CPUS="${per_cpus}"
    SESSION_MEM_MB="${per_mem}"
    SESSION_CPU_MODE="${DPAD_CPU_MODE:-quota}"
    SESSION_RESERVE_CPUS="${reserve_cpus}"
    # Floor warnings: Steam + CEF + nvh264enc want ~3 cpu / ~6G to be comfortable.
    if [ "${per_cpus:-0}" -gt 0 ] && [ "${per_cpus:-0}" -lt 3 ] 2>/dev/null; then
        log "WARNING: per-session CPU quota is ${per_cpus} (< 3) — Steam/CEF/encoder may be CPU-starved; lower DPAD_RESERVE_CPUS or reduce DPAD_MAX_SESSIONS"
    fi
    if [ "${per_mem:-0}" -gt 0 ] && [ "${per_mem:-0}" -lt 6144 ] 2>/dev/null; then
        log "WARNING: per-session memory is ${per_mem}MB (< 6GB) — Steam/CEF need more; lower DPAD_RESERVE_MEM_MB or reduce DPAD_MAX_SESSIONS"
    fi
    log "resource partitioning: host ${total_cpus} cpu / ${total_mem_mb}MB ram; reserve ${reserve_cpus} cpu / ${reserve_mem}MB; per session (N=${n}): ${per_cpus} cpu (${SESSION_CPU_MODE}) / ${per_mem}MB"
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
    compute_session_resources "$max"
    # Stagger container launches (opt-in, DPAD_LAUNCH_STAGGER seconds, default 0).
    # NOTE: the real fix for the NVENC first-open failure on non-zero GPU minors is
    # the Selkies encoder-register retry in start_gamescope_stream (entrypoint),
    # NOT a launch stagger — a 13s gap did NOT prevent the failure (it's not an
    # encoder-vs-encoder race). Keep this only as an opt-in lever. On driver 570+
    # a container whose nvh264enc fails to register (NvEncOpenEncodeSessionEx
    # 'error code 2') would have NO video for the whole boot; the entrypoint retry
    # restarts Selkies once and the second open succeeds. A non-zero stagger here
    # just serializes boot, so the default is 0 (back-to-back launches).
    local stagger="${DPAD_LAUNCH_STAGGER:-0}"
    for (( i=0; i<max; i++ )); do
        if [ "$i" -gt 0 ] && [ "${stagger:-0}" -gt 0 ]; then
            log "staggering ${stagger}s before dpad-${i} (NVENC init race on driver 580)"
            sleep "$stagger"
        fi
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
    log "=== DpadCloud VM bootstrap starting (warm-VM mode=${DPAD_WARM_VM}) ==="
    ensure_no_auto_updates   # FIRST: stop apt from killing the session mid-boot
    systemctl start docker 2>/dev/null || true
    ensure_driver_580  || return 1   # may reboot once (595->580 OR proprietary->open); resumes here after
    ensure_modeset            # may reboot once; resumes here after
    ensure_nct                || return 1
    ensure_docker_xfs_quota   || return 1
    ensure_userns
    ensure_image              || return 1
    if [ "${DPAD_WARM_VM}" = "1" ]; then
        # v2 warm-VM: host prep + image + MPS, then emit the VM-ready marker and
        # STOP — no pre-launched session containers (a session = a fresh
        # container with the user's volume, launched by dpad-launch-session).
        ensure_mps
        mkdir -p /opt/dpadcloud
        echo "ready $(date -Is)" > "$VM_READY_FILE"
        log "DPAD_VM_READY — warm pool VM ready (Docker + image + MPS); 0 session containers"
        echo "DPAD_VM_READY"
        log "=== DpadCloud VM bootstrap complete (warm) ==="
        return 0
    fi
    # v1 back-compat: run one container per GPU + report Selkies URLs.
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
Description=DpadCloud VM bootstrap (modeset -> nct -> pull -> MPS -> warm-VM ready)
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