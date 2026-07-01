# =============================================================================
# DpadCloud Gaming Container (B2 + B2b — lean, low-latency)
# Base: CUDA 12.1 runtime (<= every Vast.ai host's Max Cuda, so NVENC works).
# Browser path:  Selkies (NVENC) <- in-image coturn TURN <- cloudflared (HTTPS)
# Native path:    Sunshine (NVENC) + Moonlight over Tailscale
# Patterns ported from vastai/linux-desktop (PipeWire audio, coturn TURN,
# Xvfb+Mesa-EGL display, Selkies bound to 127.0.0.1, OPEN_BUTTON_TOKEN creds).
# =============================================================================

# Build-time CUDA variant. Two supported values (one Dockerfile, two tags):
#   12.1.1 / 12-1  -> driver >=525, widest pool (Turing..Hopper). No RTX 50/Blackwell.
#   12.8.1 / 12-8  -> driver >=570, RTX 50/Blackwell (sm_120) + Ada/Ampere on modern
#                     drivers + datacenter H100/B200. This is the #1249 regression
#                     range — the flexgrip interposer (step 9d) handles NVENC on
#                     multi-GPU hosts where only a slice of the host is assigned.
# Build the RTX-50 variant:
#   docker buildx build --build-arg CUDA_VERSION=12.8.1 --build-arg CUDA_PKG=12-8 \
#       -t dpadcloud:gaming-cuda12.8 .
# =============================================================================
ARG CUDA_VERSION=12.1.1
ARG CUDA_PKG=12-1
FROM nvidia/cuda:${CUDA_VERSION}-runtime-ubuntu22.04

LABEL maintainer="dpadcloud"
LABEL description="Lean headless cloud-gaming container: Selkies + Sunshine + NVENC"

# Re-declare inside the stage: an ARG before FROM is only visible to the FROM
# line, not to RUN/ENV below. Redeclaring without a value inherits the --build-arg
# (or the global default above), so cuda-nvrtc-${CUDA_PKG} resolves correctly.
ARG CUDA_VERSION
ARG CUDA_PKG
ARG DEBIAN_FRONTEND=noninteractive
ARG PROTONGE_VERSION=GE-Proton9-25

# --- Runtime env (mirror Vast's working setup; uid 1001 = the desktop user) ---
# NVIDIA_VISIBLE_DEVICES is intentionally NOT set here: on multi-GPU Vast hosts
# `=all` makes the container see every GPU and the encoder grabs device 0, which
# may not be the one assigned to this instance, so NvEncOpenEncodeSessionEx fails.
# Letting Vast inject the assigned GPU keeps device 0 = the assigned GPU.
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
# Encoder chosen at runtime by entrypoint (1-frame test). Do NOT hardcode here.
ENV SDL_VIDEODRIVER=x11

# =============================================================================
# 1. Enable i386 + base + display + audio + gaming runtime deps (no build tools)
# =============================================================================
RUN dpkg --add-architecture i386 && \
    apt-get update && apt-get install -y --no-install-recommends \
      ca-certificates curl wget git gnupg2 sudo socat jq unzip xz-utils \
      xserver-xorg-core xvfb x11-xserver-utils x11-utils mesa-utils \
      libgl1-mesa-glx libgl1-mesa-dri libegl-mesa0 libgles2 libglvnd0 \
      libglx-mesa0 libglx0 libgl1 \
      xfce4 xfce4-goodies dbus-x11 \
      pipewire pipewire-pulse wireplumber \
      libpulse0 libopus0 libvpx7 libdrm2 libva2 libvdpau1 \
      libssl3 libffi8 libwayland-egl1 libxcb-dri3-0 libxext6 libxfixes3 \
      libxv1 libxtst6 libxi6 libxrandr2 libxinerama1 libxcursor1 \
      libxcomposite1 libxdamage1 libnss3 libatk1.0-0 libatk-bridge2.0-0 \
      libgtk-3-0 libgbm1 libasound2 libc6:i386 libgl1:i386 \
      coturn \
      htop nano vim tmux p7zip-full \
    && rm -rf /var/lib/apt/lists/*

# =============================================================================
# 2. Create the desktop user (uid 1001 — matches the XDG_RUNTIME_DIR paths)
# =============================================================================
RUN useradd -m -s /bin/bash -u ${PUID} ${USERNAME} && \
    groupadd -f games && \
    usermod -aG sudo,audio,video,input,plugdev,games ${USERNAME} && \
    mkdir -p /etc/sudoers.d && \
    echo "${USERNAME} ALL=(ALL) NOPASSWD:ALL" >> /etc/sudoers.d/${USERNAME} && \
    chmod 0440 /etc/sudoers.d/${USERNAME}

# =============================================================================
# 3. NVIDIA NVRTC + cuda-compat (forward-compat for datacenter GPUs)
#    Parameterized by CUDA_PKG (12-1 or 12-8) to match the base CUDA variant.
#    NVRTC is required by the GStreamer nvcodec plugin (nvh264enc compiles kernels
#    at runtime); cuda-compat enables forward-compat for datacenter GPUs.
# =============================================================================
RUN apt-get update && apt-get install -y --no-install-recommends \
      cuda-nvrtc-${CUDA_PKG} cuda-compat-${CUDA_PKG} \
    && rm -rf /var/lib/apt/lists/*

# =============================================================================
# 4. Install Steam
# =============================================================================
RUN apt-get update && apt-get install -y --no-install-recommends steam-installer \
    && rm -rf /var/lib/apt/lists/*

# =============================================================================
# 5. Install Proton-GE (Windows game compatibility, Steam-Deck-grade)
# =============================================================================
RUN mkdir -p ${HOME}/.steam/root/compatibilitytools.d && \
    cd /tmp && wget -q --show-progress \
      "https://github.com/GloriousEggroll/proton-ge-custom/releases/download/${PROTONGE_VERSION}/${PROTONGE_VERSION}.tar.gz" \
      -O proton-ge.tar.gz && \
    tar -xzf proton-ge.tar.gz -C ${HOME}/.steam/root/compatibilitytools.d/ && \
    rm proton-ge.tar.gz && \
    chown -R ${USERNAME}:${USERNAME} ${HOME}/.steam

# =============================================================================
# 6. Install Sunshine (host for native Moonlight; .deb from GitHub)
# =============================================================================
RUN cd /tmp && wget -q --show-progress \
      "https://github.com/LizardByte/Sunshine/releases/latest/download/sunshine-ubuntu-22.04-amd64.deb" \
      -O sunshine.deb && \
    apt-get update && dpkg -i sunshine.deb || true && \
    apt-get install -f -y --no-install-recommends && \
    rm -f sunshine.deb && rm -rf /var/lib/apt/lists/* && \
    which sunshine || (echo "ERROR: sunshine binary not found after install" && exit 1)

# =============================================================================
# 7. Install Selkies-GStreamer (WebRTC browser streaming)
#    GPL GStreamer tarball + python wheel + web app + joystick interposer.
#    (Latest Selkies release = v1.6.2, bundles GStreamer 1.24.6. NOTE: 1.24.6's
#    nvcodec uses old NVENC preset GUIDs removed in NVENC 13 / driver >=570, so
#    nvh264enc falls back to x264enc on driver >=570 hosts — browser path uses
#    x264 there; Sunshine handles NVENC on those hosts separately.)
# =============================================================================
RUN apt-get update && apt-get install -y --no-install-recommends \
      python3 python3-pip python3-dev build-essential libevdev-dev libudev-dev \
      python3-gi python3-gi-cairo gir1.2-gstreamer-1.0 gir1.2-gst-plugins-base-1.0 \
      libgirepository-1.0-1 glib-networking libgudev-1.0-0 \
      libgcrypt20 libjack-jackd2-0 alsa-utils x264 x265 aom-tools libopenh264-dev \
    && rm -rf /var/lib/apt/lists/* && \
    SELKIES_VERSION="$(curl -fsSL 'https://api.github.com/repos/selkies-project/selkies/releases/latest' | jq -r '.tag_name' | sed 's/[^0-9\.\-]*//g')" && \
    UBUNTU_VER="$(grep '^VERSION_ID=' /etc/os-release | cut -d= -f2 | tr -d '\"')" && \
    ARCH="$(dpkg --print-architecture)" && \
    echo "Installing Selkies-GStreamer v${SELKIES_VERSION}..." && \
    cd /opt && curl -fsSL "https://github.com/selkies-project/selkies/releases/download/v${SELKIES_VERSION}/gstreamer-selkies_gpl_v${SELKIES_VERSION}_ubuntu${UBUNTU_VER}_${ARCH}.tar.gz" | tar -xzf - && \
    cd /tmp && curl -O -fsSL "https://github.com/selkies-project/selkies/releases/download/v${SELKIES_VERSION}/selkies_gstreamer-${SELKIES_VERSION}-py3-none-any.whl" && \
    pip3 install --no-cache-dir --force-reinstall "selkies_gstreamer-${SELKIES_VERSION}-py3-none-any.whl" "websockets<14.0" && \
    rm -f "selkies_gstreamer-${SELKIES_VERSION}-py3-none-any.whl" && \
    cd /opt && curl -fsSL "https://github.com/selkies-project/selkies/releases/download/v${SELKIES_VERSION}/selkies-gstreamer-web_v${SELKIES_VERSION}.tar.gz" | tar -xzf - && \
    cd /tmp && curl -o selkies-js-interposer.deb -fsSL "https://github.com/selkies-project/selkies/releases/download/v${SELKIES_VERSION}/selkies-js-interposer_v${SELKIES_VERSION}_ubuntu${UBUNTU_VER}_${ARCH}.deb" && \
    apt-get update && apt-get install -y --no-install-recommends ./selkies-js-interposer.deb && \
    rm -f selkies-js-interposer.deb && \
    apt-get clean && rm -rf /var/lib/apt/lists/* /var/cache/debconf/* /var/log/* /tmp/* /var/tmp/*

# =============================================================================
# 8. Install cloudflared (B2b: HTTPS tunnel front for Selkies click-and-play)
# =============================================================================
ARG CLOUDFLARED_VERSION=2025.7.0
RUN cd /tmp && curl -fsSL -o cloudflared \
      "https://github.com/cloudflare/cloudflared/releases/download/${CLOUDFLARED_VERSION}/cloudflared-linux-amd64" && \
    install -m 0755 cloudflared /usr/local/bin/cloudflared && rm -f cloudflared && \
    cloudflared --version || true

# =============================================================================
# 9. Install Tailscale (native-Moonlight enthusiast path overlay)
# =============================================================================
RUN curl -fsSL https://tailscale.com/install.sh | sh

RUN apt-get update && apt-get install -y --no-install-recommends pulseaudio pulseaudio-utils xsel && rm -rf /var/lib/apt/lists/*

# =============================================================================
# 9b. Vulkan loader + tools (diag only). gamescope/DXVK present path is deferred;
#     this just lets us print what Vulkan the host exposes at boot.
# =============================================================================
RUN apt-get update && apt-get install -y --no-install-recommends \
      libvulkan1 vulkan-tools mesa-vulkan-drivers \
    && rm -rf /var/lib/apt/lists/*

# =============================================================================
# 9c. VirtualGL 3.1 (GPU-accelerated OpenGL into the headless Xvfb)
#     Without VGL, GL apps render on Mesa llvmpipe (CPU) on Xvfb → slow. vglrun
#     routes GL to the GPU's EGL offscreen backend (VGL_DISPLAY=egl needs no
#     real display) and blits the finished frame onto the Xvfb window, which
#     Selkies/Sunshine capture via ximagesrc.
#     VGL does NOT solve Vulkan PRESENT (DXVK/Proton) — that needs a present
#     surface (gamescope), deferred. Interim Windows-title path is WineD3D
#     (D3D→OpenGL) + vglrun, enabled by scripts/proton-wined3d.
# =============================================================================
ARG VIRTUALGL_VERSION=3.1.4
RUN cd /tmp && wget -q --show-progress \
      "https://github.com/VirtualGL/virtualgl/releases/download/${VIRTUALGL_VERSION}/virtualgl_${VIRTUALGL_VERSION}_amd64.deb" \
      -O vgl.deb && \
    dpkg -i vgl.deb || true && apt-get install -f -y --no-install-recommends && \
    rm -f vgl.deb && rm -rf /var/lib/apt/lists/* && \
    (command -v vglrun >/dev/null 2>&1 && echo "VirtualGL ${VIRTUALGL_VERSION} installed: $(command -v vglrun)") || \
      (echo "ERROR: vglrun not found after install" && exit 1)

# =============================================================================
# 9d. NVENC multi-GPU fix (flexgrip interposer) — fixes nvidia-container-toolkit
#     #1249 on driver >=570 when only a slice of a multi-GPU host is assigned.
#     libnvenc_fix.so intercepts NV0000_CTRL_CMD_GPU_GET_ATTACHED_IDS and filters
#     the host's GPU list to only the GPUs whose /dev/nvidiaX nodes are mounted
#     in this container, so NVENC takes the single-GPU init path instead of
#     peer-init'ing unreachable GPUs and returning NV_ENC_ERR_UNSUPPORTED_DEVICE.
#     Gated at runtime by DPAD_NVENC_FIX (auto-enabled by the entrypoint when host
#     GPU count > mounted GPU count on driver 570..609) so it never perturbs the
#     compute path unless needed. gcc is already present via build-essential (step 7).
#     Source vendored from flexgrip/nvidia-gpu-enumeration (2026-05-07 release).
# =============================================================================
COPY scripts/nvenc_fix.c /opt/dpadcloud/src/nvenc_fix.c
RUN gcc -shared -fPIC -O2 -o /opt/dpadcloud/libnvenc_fix.so /opt/dpadcloud/src/nvenc_fix.c -ldl && \
    ls -l /opt/dpadcloud/libnvenc_fix.so

# =============================================================================
# 10. Copy configs + entrypoint + launcher scripts + display-driver installer
# =============================================================================
COPY configs/ ${HOME}/.config/
COPY entrypoint.sh healthcheck.sh /opt/dpadcloud/
COPY scripts/vgl-steam scripts/proton-wined3d scripts/vgl-test scripts/install-display-drivers /opt/dpadcloud/
RUN chmod +x /opt/dpadcloud/*.sh \
        /opt/dpadcloud/vgl-steam /opt/dpadcloud/proton-wined3d /opt/dpadcloud/vgl-test \
        /opt/dpadcloud/install-display-drivers && \
    chown -R ${USERNAME}:${USERNAME} ${HOME}/.config && \
    rm -f ${HOME}/.config/autostart/*.desktop 2>/dev/null || true

# =============================================================================
# 11. Ports
# =============================================================================
# 16100 = Selkies (localhost only; cloudflared tunnels it out over HTTPS)
# 3478  = in-image coturn TURN, TCP (relays over the single listening conn — no UDP
#         relay-port range needed). On Vast.ai request the 73478 identity tag
#         (TCP only: -p 73478:73478) and the runtime binds coturn to the real
#         port in VAST_TCP_PORT_73478. (Do NOT also add 73478/udp — Vast flags
#         tcp+udp of the same port as a duplicate.)
# 47989/47990 = Sunshine (native Moonlight over Tailnet; direct if exposed)
# 41641 = Tailscale WireGuard
EXPOSE 16100/tcp
EXPOSE 3478/tcp
EXPOSE 47989/tcp
EXPOSE 47990/tcp
EXPOSE 41641/udp

USER root
ENTRYPOINT ["/opt/dpadcloud/entrypoint.sh"]