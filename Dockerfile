# =============================================================================
# DpadCloud Gaming Container — Ubuntu 24.04 (noble) + CUDA 12.5.1
#
# Two slim images, ONE Dockerfile (multi-stage):
#   docker build --target vast-docker -t forcespt/dpadcloud-gaming:dpad-heroic   .
#   docker build --target vast-vm      -t forcespt/dpadcloud-gaming:dpad-SteamOS .
#
#   :dpad-heroic   Vast Docker (no userns): Heroic desktop + Selkies stream.
#                  Steam is blocked on Vast Docker (no userns -> CEF crashes),
#                  so Heroic (Electron + --no-sandbox, no userns) is the launcher
#                  for Epic/GOG/Amazon; games run via umu/Proton-direct. A general
#                  cloud desktop (XFCE + Firefox) for non-Steam games + work.
#   :dpad-SteamOS  Vast KVM VM (userns): Steam/gamescope (full Steam, Big Picture)
#                  + Selkies stream. No desktop. Fast-boot: the Steam client is
#                  pre-bootstrapped at build time (~2.1 GB) so a fresh container
#                  reaches the stream URL in ~50 s instead of a 3-4 min download.
#                  Native Steam downloads its own Proton at runtime, so GE-Proton
#                  is NOT baked in (it was only for the dpad-launch Proton-direct
#                  path, which is gone).
#
# Both images use Selkies-GStreamer as the ONLY browser stream (mws, Sunshine,
# and Tailscale/native-Moonlight have been removed).
#
# Base is nvidia/cuda:12.5.1-BASE (not -runtime): the runtime base's CUDA math
# libs (libcublas/libcusparse/libcufft/libnpp/libcusolver/libcurand, ~1.6 GB)
# are unused by NVENC/Selkies — we install only cuda-cudart (cudaupload/
# cudaconvert) + cuda-nvrtc (nvh264enc JIT). cuda-compat (datacenter forward-
# compat) is dropped (consumer GPUs). Big image-size win vs the old 16 GB image.
#
# An `interposer-builder` stage compiles the Selkies joystick interposer .so
# (x86_64 + i386) and libnvenc_fix.so, so gcc-multilib stays out of the finals.
# =============================================================================

ARG CUDA_VERSION=12.5.1
ARG CUDA_PKG=12-5
ARG DEBIAN_FRONTEND=noninteractive
ARG CLOUDFLARED_VERSION=2025.7.0
ARG VIRTUALGL_VERSION=3.1.4
ARG HEROIC_VERSION=v2.22.0

# =============================================================================
# Stage: interposer-builder
#   Builds the patched Selkies v1.6.2 joystick interposer .so (x86_64 AND i386 —
#   Steam's main binary is 32-bit and loads the i386 .so) + libnvenc_fix.so
#   (NVENC #1249 multi-GPU fix). Keeps gcc-multilib out of the final images.
# =============================================================================
FROM nvidia/cuda:${CUDA_VERSION}-base-ubuntu24.04 AS interposer-builder
RUN apt-get update && apt-get install -y --no-install-recommends gcc-multilib libc6-dev-i386 \
    && rm -rf /var/lib/apt/lists/*
COPY scripts/joystick_interposer_v162.c /tmp/joystick_interposer_v162.c
COPY scripts/nvenc_fix.c /tmp/nvenc_fix.c
RUN mkdir -p /out/x86_64 /out/i386 \
    && gcc -shared -fPIC -O2 -ldl -o /out/x86_64/selkies_joystick_interposer.so /tmp/joystick_interposer_v162.c \
    && gcc -shared -fPIC -O2 -m32 -ldl -o /out/i386/selkies_joystick_interposer.so /tmp/joystick_interposer_v162.c \
    && gcc -shared -fPIC -O2 -o /out/x86_64/libnvenc_fix.so /tmp/nvenc_fix.c -ldl

# =============================================================================
# Stage: base — shared by both final images
#   Selkies-GStreamer + coturn + cloudflared + NVENC fix + display/audio/Mesa/
#   X/Python + the dpad user. No launcher, no desktop — those are per-target.
# =============================================================================
FROM nvidia/cuda:${CUDA_VERSION}-base-ubuntu24.04 AS base
ARG CUDA_VERSION
ARG CUDA_PKG
ARG DEBIAN_FRONTEND
ARG CLOUDFLARED_VERSION
ARG VIRTUALGL_VERSION

LABEL maintainer="dpadcloud"
LABEL description="DpadCloud gaming base: Selkies + coturn + NVENC (Ubuntu 24.04)"

# --- Runtime env (uid 1001 = the desktop user) ---
# NVIDIA_VISIBLE_DEVICES is intentionally NOT set: on multi-GPU Vast hosts
# `=all` makes the encoder grab device 0, which may not be the assigned GPU.
ENV NVIDIA_DRIVER_CAPABILITIES=all
ENV DISPLAY=:0
ENV USERNAME=dpad
ENV HOME=/home/dpad
ENV PUID=1001
ENV PGID=1001
ENV XDG_RUNTIME_DIR=/run/user/1001
ENV PULSE_SERVER=unix:/run/user/1001/pulse/native
ENV PULSE_RUNTIME_PATH=/run/user/1001/pulse
ENV PIPEWIRE_RUNTIME_DIR=/run/user/1001
ENV PIPEWIRE_LATENCY=128/48000
ENV GST_DEBUG="*:2"
ENV GSTREAMER_PATH=/opt/gstreamer
ENV SELKIES_WEB_ROOT=/opt/gst-web
ENV PATH=/opt/dpadcloud:${PATH}
ENV SDL_VIDEODRIVER=x11
# Noble (24.04) enforces PEP 668 — allow pip3 to install the Selkies wheel.
ENV PIP_BREAK_SYSTEM_PACKAGES=1

# --- 1. i386 + base + display + audio + gaming deps + coturn + mesa + vulkan + python (gstreamer gir) ---
# Build tools (gcc/multilib/dev) are NOT installed here — the interposer .so
# comes from the interposer-builder stage. (xfce4/xfce4-goodies are per-target.)
RUN dpkg --add-architecture i386 && \
    apt-get update && apt-get install -y --no-install-recommends \
      ca-certificates curl wget git gnupg2 sudo socat jq unzip xz-utils \
      xserver-xorg-core xserver-xorg-legacy xvfb x11-xserver-utils x11-utils mesa-utils \
      libgl1-mesa-dri libegl-mesa0 libgles2 libglvnd0 \
      libglx-mesa0 libglx0 libgl1 \
      dbus-x11 \
      libpulse0 libopus0 libvpx9 libdrm2 libva2 libvdpau1 \
      libssl3t64 libffi8 libwayland-egl1 libxcb-dri3-0 libxext6 libxfixes3 \
      libxv1 libxtst6 libxi6 libxrandr2 libxinerama1 libxcursor1 \
      libxcomposite1 libxdamage1 libnss3 libgbm1 \
      libgtk-3-0t64 libasound2t64 libc6:i386 libgl1:i386 \
      coturn \
      python3 python3-pip python3-gi python3-gi-cairo \
      gir1.2-gstreamer-1.0 gir1.2-gst-plugins-base-1.0 \
      glib-networking libgudev-1.0-0 libgcrypt20 libjack-jackd2-0 \
      alsa-utils x264 x265 aom-tools libopenh264-dev \
      htop nano tmux \
    # Bake the GLVND-neutral libglx.so (from xserver-xorg-core) into the nvidia
    # private ModulePath. libglx-mesa0 installs its self-registering Mesa libglx.so
    # over xserver-xorg-core's, and on 610.x nvidia ships only libglxserver_nvidia.so
    # (no standalone libglx.so), so without this the loaded libglx.so is Mesa's,
    # which self-registers its swrast/DRISWRAST GLX vendor for screen 0 BEFORE
    # nvidia's libglxserver_nvidia.so -> "Another vendor already registered for
    # screen 0" -> GL falls back to Mesa/zink -> ximagesrc can't capture -> no
    # stream (the cuda_max_good>=13.3 Blackwell bug). The xorg.conf lists the
    # nvidia ModulePath first, so Xorg loads this neutral dispatcher instead of
    # Mesa's; it loads only nvidia's vendor module -> nvidia wins screen 0.
    && mkdir -p /usr/lib/xorg/modules/nvidia/extensions \
    && apt-get download xserver-xorg-core \
    && dpkg-deb -x xserver-xorg-core_*.deb /tmp/xsoc \
    && if [ -f /tmp/xsoc/usr/lib/xorg/modules/extensions/libglx.so ]; then \
         cp /tmp/xsoc/usr/lib/xorg/modules/extensions/libglx.so /usr/lib/xorg/modules/nvidia/extensions/libglx.so \
         && echo "Baked GLVND libglx.so into nvidia ModulePath"; \
       else echo "xserver-xorg-core .deb has no libglx.so — GLVND dispatcher not available"; fi \
    && rm -rf /tmp/xsoc xserver-xorg-core_*.deb \
    && rm -rf /var/lib/apt/lists/*

# --- 2. Create the desktop user (uid 1001) ---
RUN useradd -m -s /bin/bash -u ${PUID} ${USERNAME} && \
    groupadd -f games && \
    usermod -aG sudo,audio,video,input,plugdev,games ${USERNAME} && \
    mkdir -p /etc/sudoers.d && \
    echo "${USERNAME} ALL=(ALL) NOPASSWD:ALL" >> /etc/sudoers.d/${USERNAME} && \
    chmod 0440 /etc/sudoers.d/${USERNAME}

# --- 3. CUDA: cudart (cudaupload/cudaconvert) + nvrtc (nvh264enc JIT) only.
#    NO math libs (cublas/cusparse/...), NO cuda-compat (datacenter) — unused by
#    NVENC/Selkies; the -base image doesn't ship them, so we save ~1.7 GB. ---
RUN apt-get update && apt-get install -y --no-install-recommends \
      cuda-cudart-${CUDA_PKG} cuda-nvrtc-${CUDA_PKG} \
    && rm -rf /var/lib/apt/lists/*

# --- 4. Selkies-GStreamer (browser WebRTC streaming — the only stream) ---
#    GPL GStreamer tarball + python wheel + web app + joystick interposer deb.
#    The deb's interposer .so has the JSIOCGNAME-returns-0 bug (SDL3 rejects the
#    device), so we OVERWRITE it with the patched .so from interposer-builder.
COPY scripts/joystick_interposer_v162.c /tmp/joystick_interposer_v162.c
# Build deps (python3-dev/build-essential/libevdev-dev/libudev-dev) are needed ONLY
# to build the Selkies wheel's `evdev` C extension; they are PURGED at the end of
# this RUN so the compiler doesn't ship in the final image.
RUN apt-get update && apt-get install -y --no-install-recommends \
        python3-dev build-essential libevdev-dev libudev-dev \
    && SELKIES_VERSION="$(curl -fsSL 'https://api.github.com/repos/selkies-project/selkies/releases/latest' | jq -r '.tag_name' | sed 's/[^0-9\.\-]*//g')" && \
    UBUNTU_VER="$(grep '^VERSION_ID=' /etc/os-release | cut -d= -f2 | tr -d '\"')" && \
    ARCH="$(dpkg --print-architecture)" && \
    echo "Installing Selkies-GStreamer v${SELKIES_VERSION} (ubuntu${UBUNTU_VER})..." && \
    cd /opt && curl -fsSL "https://github.com/selkies-project/selkies/releases/download/v${SELKIES_VERSION}/gstreamer-selkies_gpl_v${SELKIES_VERSION}_ubuntu${UBUNTU_VER}_${ARCH}.tar.gz" | tar -xzf - && \
    cd /tmp && curl -O -fsSL "https://github.com/selkies-project/selkies/releases/download/v${SELKIES_VERSION}/selkies_gstreamer-${SELKIES_VERSION}-py3-none-any.whl" && \
    pip3 install --no-cache-dir --force-reinstall --break-system-packages "selkies_gstreamer-${SELKIES_VERSION}-py3-none-any.whl" "websockets<14.0" && \
    rm -f "selkies_gstreamer-${SELKIES_VERSION}-py3-none-any.whl" && \
    cd /opt && curl -fsSL "https://github.com/selkies-project/selkies/releases/download/v${SELKIES_VERSION}/selkies-gstreamer-web_v${SELKIES_VERSION}.tar.gz" | tar -xzf - && \
    cd /tmp && curl -o selkies-js-interposer.deb -fsSL "https://github.com/selkies-project/selkies/releases/download/v${SELKIES_VERSION}/selkies-js-interposer_v${SELKIES_VERSION}_ubuntu${UBUNTU_VER}_${ARCH}.deb" && \
    apt-get update && apt-get install -y --no-install-recommends ./selkies-js-interposer.deb && \
    rm -f selkies-js-interposer.deb && \
    rm -f /tmp/joystick_interposer_v162.c && \
    apt-get purge -y python3-dev build-essential libevdev-dev libudev-dev && \
    apt-get autoremove -y --purge && \
    apt-get clean && rm -rf /var/lib/apt/lists/* /var/cache/debconf/* /var/log/* /tmp/* /var/tmp/*
# Overwrite the deb's interposer .so with the patched build (JSIOCGNAME returns
# name length so SDL3 accepts the Selkies virtual gamepad) for BOTH arches.
COPY --from=interposer-builder /out/x86_64/selkies_joystick_interposer.so /usr/lib/x86_64-linux-gnu/selkies_joystick_interposer.so
COPY --from=interposer-builder /out/i386/selkies_joystick_interposer.so /usr/lib/i386-linux-gnu/selkies_joystick_interposer.so

# Selkies input router (.pth, auto-loaded; no-op when DPAD_INPUT_DISPLAY unset —
# only the gamescope path sets it). Kept in base so both images share it.
COPY scripts/dpad_input_patch.py scripts/dpad_input_patch.pth /usr/local/lib/python3.12/dist-packages/

# gamescope headless does not composite the X cursor into its PipeWire output,
# so the only visible cursor source is Selkies' XFIXES cursor overlay. This
# patcher disables Selkies' auto pointer-lock in the web client so the server
# cursor stays visible + mouse stays absolute for UI nav. Both paths need it.
COPY scripts/patch_gst_web_cursors.sh /opt/dpadcloud/patch_gst_web_cursors.sh
RUN chmod +x /opt/dpadcloud/patch_gst_web_cursors.sh \
    && /opt/dpadcloud/patch_gst_web_cursors.sh /opt/gst-web/input.js

# --- 5. cloudflared (HTTPS tunnel front for Selkies) ---
RUN cd /tmp && curl -fsSL -o cloudflared \
      "https://github.com/cloudflare/cloudflared/releases/download/${CLOUDFLARED_VERSION}/cloudflared-linux-amd64" && \
    install -m 0755 cloudflared /usr/local/bin/cloudflared && rm -f cloudflared && \
    cloudflared --version || true

# --- 6. NVENC #1249 fix (libnvenc_fix.so from interposer-builder) ---
# Fixes nvidia-container-toolkit #1249 on driver >=570 when only a slice of a
# multi-GPU host is assigned (filters GET_ATTACHED_IDS to mounted GPUs).
COPY --from=interposer-builder /out/x86_64/libnvenc_fix.so /opt/dpadcloud/libnvenc_fix.so

# --- 7. VirtualGL (GPU-accelerated GL into the headless Xvfb; the Xorg path
#    doesn't need it, but the Xvfb debug fallback / vgl-steam / proton-wined3d
#    launchers do). Small (~3 MB); kept in base for the debug path. ---
RUN apt-get update && apt-get install -y --no-install-recommends libglu1-mesa && \
    cd /tmp && wget -q --show-progress \
      "https://github.com/VirtualGL/virtualgl/releases/download/${VIRTUALGL_VERSION}/virtualgl_${VIRTUALGL_VERSION}_amd64.deb" \
      -O vgl.deb && \
    (dpkg -i vgl.deb || true) && apt-get install -f -y --no-install-recommends && \
    rm -f vgl.deb && rm -rf /var/lib/apt/lists/* && \
    (command -v vglrun >/dev/null 2>&1 && echo "VirtualGL ${VIRTUALGL_VERSION} installed: $(command -v vglrun)") || \
      (echo "ERROR: vglrun not found after install" && exit 1)

# --- 8. pulseaudio-utils (pactl) + the pulseaudio daemon (Xorg path audio).
#    vast-vm uses pipewire-pulse (installed in its own stage); this is for the
#    Xorg/Heroic path. Best-effort (|| true) so a noble pipewire-pulse conflict
#    can't break the build. ---
RUN apt-get update && apt-get install -y --no-install-recommends pulseaudio-utils xsel \
    && (apt-get install -y --no-install-recommends pulseaudio || echo "pulseaudio daemon install skipped") \
    && rm -rf /var/lib/apt/lists/*

# --- 9. Vulkan loader + tools (diag only) ---
RUN apt-get update && apt-get install -y --no-install-recommends \
      libvulkan1 libvulkan1:i386 vulkan-tools mesa-vulkan-drivers mesa-vulkan-drivers:i386 \
    && rm -rf /var/lib/apt/lists/*

# --- 10. locale + Xwrapper (common) ---
RUN apt-get update && apt-get install -y --no-install-recommends locales && \
    echo 'en_US.UTF-8 UTF-8' >> /etc/locale.gen && locale-gen en_US.UTF-8 && \
    rm -rf /var/lib/apt/lists/*
ENV LANG=en_US.UTF-8
ENV LC_ALL=en_US.UTF-8
RUN mkdir -p /etc/X11 && \
    printf 'allowed_users=anybody\nneeds_root_rights=yes\n' > /etc/X11/Xwrapper.config

# --- 11. COPY configs + entrypoint + common launcher scripts + display-driver installer ---
COPY configs/ ${HOME}/.config/
COPY configs/xorg/xorg.conf.template /opt/dpadcloud/xorg.conf.template
COPY entrypoint.sh healthcheck.sh /opt/dpadcloud/
# vgl-steam / proton-wined3d / vgl-test = the Xvfb+VGL debug launchers; dpad-launch
# = the steamcmd-based headless launcher (still useful as a manual CLI for native
# games). mws-autopair + bubbleroot are GONE (mws/Sunshine + proot removed).
COPY scripts/vgl-steam scripts/proton-wined3d scripts/vgl-test scripts/install-display-drivers scripts/dpad-launch /opt/dpadcloud/
# Strip CR (CRLF) — repo is edited on Windows; `#!/bin/bash\r` fails to exec.
RUN sed -i 's/\r$//' /opt/dpadcloud/entrypoint.sh /opt/dpadcloud/healthcheck.sh \
        /opt/dpadcloud/vgl-steam /opt/dpadcloud/proton-wined3d /opt/dpadcloud/vgl-test \
        /opt/dpadcloud/install-display-drivers /opt/dpadcloud/dpad-launch \
        ${HOME}/.config/sunshine/sunshine.conf 2>/dev/null || true && \
    chmod +x /opt/dpadcloud/*.sh \
        /opt/dpadcloud/vgl-steam /opt/dpadcloud/proton-wined3d /opt/dpadcloud/vgl-test \
        /opt/dpadcloud/install-display-drivers /opt/dpadcloud/dpad-launch && \
    chown -R ${USERNAME}:${USERNAME} ${HOME}/.config && \
    rm -f ${HOME}/.config/autostart/*.desktop 2>/dev/null || true

# Put the user-facing launchers on the DEFAULT PATH (survives /etc/environment reset).
RUN ln -sf /opt/dpadcloud/vgl-steam /usr/local/bin/vgl-steam && \
    ln -sf /opt/dpadcloud/vgl-test /usr/local/bin/vgl-test && \
    ln -sf /opt/dpadcloud/proton-wined3d /usr/local/bin/proton-wined3d && \
    ln -sf /opt/dpadcloud/dpad-launch /usr/local/bin/dpad-launch

# =============================================================================
# Stage: vast-docker  ->  :dpad-heroic
#   Vast Docker: Heroic Games Launcher + XFCE desktop + Firefox (cloud desktop +
#   non-Steam games). No Steam, no gamescope, no Proton baked in (Heroic
#   downloads its own Proton at runtime). Default launcher = heroic.
# =============================================================================
FROM base AS vast-docker
ARG DEBIAN_FRONTEND
ARG HEROIC_VERSION
LABEL description="DpadCloud Vast Docker: Heroic desktop + Selkies (Ubuntu 24.04)"
# Default to the Heroic launcher (Steam is blocked on Vast Docker).
ENV DPAD_LAUNCHER=heroic

# --- XFCE desktop (light) ---
RUN apt-get update && apt-get install -y --no-install-recommends xfce4 xfce4-goodies \
    && rm -rf /var/lib/apt/lists/*

# --- Heroic Games Launcher (Epic + GOG + Amazon) ---
# Heroic is Electron (runs with --no-sandbox, no userns). Games launch via
# umu-launcher (Proton WITHOUT pressure-vessel) -> the Proton-direct flow.
# accountsservice: Heroic queries org.freedesktop.Accounts over D-Bus and
# degrades if it can't reach it (Steam-Headless #210).
RUN set -e; \
    HEROIC_VER_STR="${HEROIC_VERSION#v}"; \
    HEROIC_DEB="Heroic-${HEROIC_VER_STR}-linux-amd64.deb"; \
    apt-get update && apt-get install -y --no-install-recommends accountsservice curl; \
    cd /tmp && curl -fsSL -o "/tmp/${HEROIC_DEB}" \
      "https://github.com/Heroic-Games-Launcher/HeroicGamesLauncher/releases/download/${HEROIC_VERSION}/${HEROIC_DEB}" \
    && ( dpkg -i "/tmp/${HEROIC_DEB}" || apt-get install -f -y ) \
    && rm -f "/tmp/${HEROIC_DEB}" \
    && rm -rf /var/lib/apt/lists/* \
    && command -v heroic

# --- Firefox (real .deb from Mozilla's apt repo — NOT snap). For Heroic
#    external "buy on store" links + a desktop browser on the streamed session. ---
RUN set -e; \
    install -d -m 0755 /etc/apt/keyrings; \
    wget -q https://packages.mozilla.org/apt/repo-signing-key.gpg \
      -O /etc/apt/keyrings/packages.mozilla.org.asc; \
    echo "deb [signed-by=/etc/apt/keyrings/packages.mozilla.org.asc] https://packages.mozilla.org/apt mozilla main" \
      > /etc/apt/sources.list.d/mozilla.list; \
    # Pin the Mozilla origin above the Ubuntu snap-stub firefox (whose 1: epoch
    # would otherwise win) so apt installs the real .deb, not the broken snap.
    printf 'Package: firefox*\nPin: origin packages.mozilla.org\nPin-Priority: 1001\n' > /etc/apt/preferences.d/mozilla; \
    apt-get update && apt-get install -y --no-install-recommends firefox; \
    update-alternatives --install /usr/bin/x-www-browser x-www-browser /usr/bin/firefox 200 2>/dev/null || true; \
    rm -rf /var/lib/apt/lists/*

# Heroic launcher wrapper (the entrypoint calls /opt/dpadcloud/heroic-launch).
COPY scripts/heroic-launch /opt/dpadcloud/heroic-launch
RUN sed -i 's/\r$//' /opt/dpadcloud/heroic-launch && chmod +x /opt/dpadcloud/heroic-launch

# --- SSH server (B1: dpadplay VPS reverse-proxy tunnel) ---
# The dpadplay VPS autossh-tunnels to localhost:16100 (Selkies) through the
# Vast-mapped port 22, so the stream URL can be play-<id>.dpadplay.com instead
# of trycloudflare.com. Media/input stay direct via coturn — this carries ONLY
# the signaling WebSocket. Pubkey-only; the key is injected at runtime via
# DPAD_ORCHESTRATOR_PUBKEY (see entrypoint.sh). Backward-compatible: cloudflared
# still runs as a fallback until the orchestrator switches to DPAD_TUNNEL=ssh.
RUN apt-get update && apt-get install -y --no-install-recommends openssh-server \
    && mkdir -p /run/sshd && rm -rf /var/lib/apt/lists/*

EXPOSE 16100/tcp 22/tcp
# 3478 (coturn TURN) is opt-in via -p 3478:3478 at launch (not EXPOSE'd — see
# the ports comment in the base stage). No 8080/47989/47990/41641 (mws/Sunshine/
# Tailscale removed).
USER root
ENTRYPOINT ["/opt/dpadcloud/entrypoint.sh"]

# =============================================================================
# Stage: vast-vm  ->  :dpad-SteamOS
#   Vast KVM VM: Steam + gamescope (full Steam, Big Picture) + Selkies stream.
#   Fast-boot: the Steam client is pre-bootstrapped at build time. No desktop
#   (XFCE), no Heroic, no Firefox. Native Steam downloads its own Proton at
#   runtime, so GE-Proton is NOT baked in. Default mode = gamescope.
# =============================================================================
FROM base AS vast-vm
ARG DEBIAN_FRONTEND
LABEL description="DpadCloud Vast VM: Steam + gamescope + Selkies (Ubuntu 24.04)"
# Default to the gamescope headless + Steam multi-tenant path.
ENV DPAD_GAMESCOPE=1

# --- Steam (+ steam-libs amd64/i386 so the Steam runtime has its deps) ---
RUN apt-get update && \
    ( apt-get install -y steam-installer \
      || ( curl -fsSL -o /tmp/steam.deb "https://cdn.fastly.steamstatic.com/client/installer/steam.deb" \
           && apt-get install -y /tmp/steam.deb && rm -f /tmp/steam.deb ) ) && \
    apt-get update && \
    ( apt-get install -y steam-libs-amd64 steam-libs-i386 2>/dev/null \
      || echo "    (steam-libs-* not separate packages; Steam fetches its runtime on first launch)" ) && \
    ( ln -sf /usr/games/steam /usr/bin/steam 2>/dev/null || ln -sf /usr/bin/steam-launch /usr/bin/steam 2>/dev/null || true ) && \
    rm -rf /var/lib/apt/lists/*

# --- zenity license wrapper — auto-accept Steam's "proprietary (binary-only)"
#    license dialog (Steam-Headless #218) so the Steam UI starts non-interactively
#    on userns hosts. Other zenity calls pass through to the real binary. ---
RUN apt-get update && apt-get install -y --no-install-recommends zenity && rm -rf /var/lib/apt/lists/* && \
    if command -v zenity >/dev/null 2>&1; then \
      mv /usr/bin/zenity /usr/bin/zenity.real; \
      printf '%s\n' '#!/bin/bash' \
        'for a in "$@"; do case "$a" in *"Steam is proprietary"*|*"binary-only"*) exit 0;; esac; done' \
        'exec /usr/bin/zenity.real "$@"' > /usr/bin/zenity; \
      chmod +x /usr/bin/zenity; \
    fi

# --- gamescope + PipeWire (the multi-tenant full-Steam path; no DRM master) ---
#    gamescope isn't in Ubuntu 24.04 repos — use the 3v1n0 PPA. Binary lands in
#    /usr/games (NOT in PATH); symlink helpers to /usr/bin so gamescope finds
#    gamescopereaper. PipeWire + wireplumber must run before gamescope. The
#    pipewiresrc zero-copy Selkies capture path (patch below) needs gstreamer1.0-
#    pipewire; gstreamer1.0-x provides ximagesink for the :2-bridge fallback.
RUN apt-get update && apt-get install -y --no-install-recommends software-properties-common && \
    add-apt-repository -y ppa:3v1n0/gamescope && \
    apt-get update && apt-get install -y --no-install-recommends \
        gamescope pipewire pipewire-audio pipewire-pulse pipewire-audio-client-libraries \
        wireplumber libeis-dev gstreamer1.0-pipewire \
        gstreamer1.0-tools gstreamer1.0-plugins-good gstreamer1.0-plugins-bad \
        gstreamer1.0-x gstreamer1.0-plugins-base pulseaudio-utils && \
    for b in gamescope gamescopereaper gamescopestream gamescopectl; do \
        [ -e /usr/games/$b ] && ln -sf /usr/games/$b /usr/bin/$b; \
    done && \
    (command -v gamescope && gamescope --version 2>&1 | head -1) && \
    rm -rf /var/lib/apt/lists/*

# --- Stage 2 zero-copy: patch Selkies' build_video_pipeline to capture
#    gamescope's PipeWire node directly (pipewiresrc -> cudaupload -> cudaconvert
#    -> nvh264enc) instead of ximagesrc on an Xvfb :2 bridge. Gated on
#    DPAD_VIDEO_SRC=pipewiresrc at runtime (the entrypoint default for gamescope
#    mode); DPAD_VIDEO_SRC=ximagesrc reverts. Idempotent. ---
COPY scripts/patch_selkies_pipewire.py /opt/dpadcloud/patch_selkies_pipewire.py
RUN python3 /opt/dpadcloud/patch_selkies_pipewire.py /usr/local/lib/python3.12/dist-packages/selkies_gstreamer/gstwebrtc_app.py \
    && rm -f /opt/dpadcloud/patch_selkies_pipewire.py

# --- Fix ~/.steam/root: Steam's steam.sh expects a symlink it can rm -f and
#    recreate; a real dir there makes steam.sh's rm fail and corrupts Steam's
#    first-run GL updater under gamescope headless. (No Proton-GE step here —
#    compatibilitytools.d is created empty; native Steam downloads Proton.) ---
RUN mkdir -p ${HOME}/.steam/debian-installation/compatibilitytools.d && \
    rm -rf ${HOME}/.steam/root && \
    ln -s ${HOME}/.steam/debian-installation ${HOME}/.steam/root && \
    chown -R ${USERNAME}:${USERNAME} ${HOME}/.steam

# --- Pre-bootstrap the full Steam client at BUILD TIME (~2.1 GB, baked in) so
#    a fresh-boot container reaches the stream URL in ~50 s instead of a 3-4 min
#    first-run download. Runs on Xvfb :8 + mesa/llvmpipe (software GL — NO GPU
#    needed; works in a plain `docker build`). Does NOT log in (no Steam Guard
#    at build). Best-effort: always succeeds; the entrypoint re-bootstraps at
#    runtime as a fallback. Placed late so editing entrypoint/scripts does NOT
#    invalidate this expensive layer. Idempotent. ---
COPY scripts/build-bootstrap-steam.sh /tmp/build-bootstrap-steam.sh
RUN chmod +x /tmp/build-bootstrap-steam.sh \
    && /tmp/build-bootstrap-steam.sh \
    && rm -f /tmp/build-bootstrap-steam.sh \
    && chown -R ${USERNAME}:${USERNAME} ${HOME}/.steam

EXPOSE 16100/tcp
# 3478 (coturn TURN) opt-in via -p 3478:3478 at launch. No 8080/47989/47990/41641.
USER root
ENTRYPOINT ["/opt/dpadcloud/entrypoint.sh"]