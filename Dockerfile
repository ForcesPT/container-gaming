# =============================================================================
# DpadCloud Gaming Container — Ubuntu 24.04 (noble) + CUDA 12.5.1
# Base: nvidia/cuda:12.5.1-runtime-ubuntu24.04
#   * 24.04 (glibc 2.39) is required so the prebuilt moonlight-web-stream
#     binary (built against glibc 2.39) runs natively — no from-source Rust
#     build, no patchelf/glibc juggling. mws bridges Sunshine's NVENC stream
#     to a browser over WebRTC, giving the BROWSER path hardware NVENC on ALL
#     drivers (Selkies' nvh264enc falls back to x264 on driver>=570 / NVENC 13).
#   * CUDA 12.5.1 runs on ANY driver >=525 via CUDA minor-version compatibility
#     (the whole 12.x family shares the R525 baseline driver). So the wide
#     Vast pool is preserved: keep the offer filter at cuda_max_good>=12.1.
#     (A 12.8.1 variant for RTX 50/Blackwell is possible with --build-arg
#     CUDA_VERSION=12.8.1 --build-arg CUDA_PKG=12-8.)
#
# Three streaming paths, one image:
#   Browser (primary)  -> moonlight-web-stream (Sunshine h264_nvenc) <- coturn TURN
#                        <- cloudflared HTTPS tunnel (secure context: gamepad +
#                        WebCodecs + keyboard lock). No client install.
#   Browser (fallback) -> Selkies-GStreamer (NVENC on driver<570, x264 on >=570)
#                        <- same coturn <- its own cloudflared tunnel.
#   Native enthusiast  -> Sunshine (NVENC) + Moonlight over Tailscale (lowest
#                        latency, direct UDP over the Tailnet).
#
# Patterns ported from vastai/linux-desktop (PulseAudio headless null-sink,
# in-image coturn, Xvfb+Mesa-EGL display, Selkies bound to 127.0.0.1,
# OPEN_BUTTON_TOKEN creds) and vastai/base-image (install-display-drivers,
# configure_cuda minor/forward-compat, PIP_BREAK_SYSTEM_PACKAGES for noble).
# =============================================================================
ARG CUDA_VERSION=12.5.1
ARG CUDA_PKG=12-5
FROM nvidia/cuda:${CUDA_VERSION}-runtime-ubuntu24.04

LABEL maintainer="dpadcloud"
LABEL description="Lean headless cloud-gaming container: mws + Selkies + Sunshine + NVENC (Ubuntu 24.04)"

# Re-declare inside the stage: an ARG before FROM is only visible to the FROM
# line, not to RUN/ENV below. Redeclaring without a value inherits the --build-arg
# (or the global default above), so cuda-nvrtc-${CUDA_PKG} resolves correctly.
ARG CUDA_VERSION
ARG CUDA_PKG
ARG DEBIAN_FRONTEND=noninteractive
ARG PROTONGE_VERSION=GE-Proton9-25
ARG MWS_VERSION=v2.10.0
ARG CLOUDFLARED_VERSION=2025.7.0
ARG VIRTUALGL_VERSION=3.1.4

# --- Runtime env (uid 1001 = the desktop user) ---
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
ENV MWS_PATH=/opt/mws
# Encoder chosen at runtime by entrypoint (1-frame test). Do NOT hardcode here.
ENV SDL_VIDEODRIVER=x11
# Noble (24.04) enforces PEP 668 — allow pip3 to install the Selkies wheel into
# the system interpreter (mirrors vastai/base-image's noble handling).
ENV PIP_BREAK_SYSTEM_PACKAGES=1

# =============================================================================
# 1. Enable i386 + base + display + audio + gaming runtime deps (no build tools)
#    Noble t64 package renames are applied ONLY where the lib was actually
#    renamed: libasound2t64, libssl3t64, libgtk-3-0t64 (confirmed present).
#    These were NOT renamed and keep their plain names: libpulse0, libva2,
#    libvdpau1, libwayland-egl1, libvpx9, libjack-jackd2-0. libgl1-mesa-glx
#    was removed in noble (libgl1-mesa-dri + libgl1 cover GL). atk/atk-bridge
#    are pulled as deps of libgtk-3-0t64. We use PulseAudio (not PipeWire) for
#    the headless null-sink monitor-capture fix, so pipewire packages are NOT
#    installed (noble's default pipewire-pulse is left inert).
# =============================================================================
RUN dpkg --add-architecture i386 && \
    apt-get update && apt-get install -y --no-install-recommends \
      ca-certificates curl wget git gnupg2 sudo socat jq unzip xz-utils \
      xserver-xorg-core xvfb x11-xserver-utils x11-utils mesa-utils \
      libgl1-mesa-dri libegl-mesa0 libgles2 libglvnd0 \
      libglx-mesa0 libglx0 libgl1 \
      xfce4 xfce4-goodies dbus-x11 \
      libpulse0 libopus0 libvpx9 libdrm2 libva2 libvdpau1 \
      libssl3t64 libffi8 libwayland-egl1 libxcb-dri3-0 libxext6 libxfixes3 \
      libxv1 libxtst6 libxi6 libxrandr2 libxinerama1 libxcursor1 \
      libxcomposite1 libxdamage1 libnss3 libgbm1 \
      libgtk-3-0t64 libasound2t64 libc6:i386 libgl1:i386 \
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
#    Parameterized by CUDA_PKG (12-5 default). NVRTC is required by the GStreamer
#    nvcodec plugin (nvh264enc compiles kernels at runtime); cuda-compat enables
#    forward-compat for datacenter GPUs. Both come from the CUDA apt repo that
#    the nvidia/cuda base image already configures.
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
# 6. Install Sunshine (host for native Moonlight AND the encoder for mws)
#    .deb from GitHub, matched to the base (ubuntu-24.04-amd64).
# =============================================================================
RUN cd /tmp && wget -q --show-progress \
      "https://github.com/LizardByte/Sunshine/releases/latest/download/sunshine-ubuntu-24.04-amd64.deb" \
      -O sunshine.deb && \
    apt-get update && dpkg -i sunshine.deb || true && \
    apt-get install -f -y --no-install-recommends && \
    rm -f sunshine.deb && rm -rf /var/lib/apt/lists/* && \
    which sunshine || (echo "ERROR: sunshine binary not found after install" && exit 1)

# =============================================================================
# 7. Install Selkies-GStreamer (browser WebRTC streaming — FALLBACK browser path)
#    GPL GStreamer tarball + python wheel + web app + joystick interposer. The
#    tarball/deb URLs are parameterized by ${UBUNTU_VER} (read from os-release),
#    so on 24.04 they resolve to the *_ubuntu24.04_amd64 artifacts automatically.
#    (Latest Selkies release = v1.6.2, bundles GStreamer 1.24.6. NOTE: 1.24.6's
#    nvcodec uses old NVENC preset GUIDs removed in NVENC 13 / driver >=570, so
#    nvh264enc falls back to x264enc on driver >=570 hosts — the mws+Sunshine
#    path above is the primary browser path on those drivers; Selkies is the
#    fallback for driver <570 or as a second opinion.)
# =============================================================================
RUN apt-get update && apt-get install -y --no-install-recommends \
      python3 python3-pip python3-dev build-essential libevdev-dev libudev-dev \
      python3-gi python3-gi-cairo gir1.2-gstreamer-1.0 gir1.2-gst-plugins-base-1.0 \
      glib-networking libgudev-1.0-0 \
      libgcrypt20 libjack-jackd2-0 alsa-utils x264 x265 aom-tools libopenh264-dev \
    && rm -rf /var/lib/apt/lists/* && \
    SELKIES_VERSION="$(curl -fsSL 'https://api.github.com/repos/selkies-project/selkies/releases/latest' | jq -r '.tag_name' | sed 's/[^0-9\.\-]*//g')" && \
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
    apt-get clean && rm -rf /var/lib/apt/lists/* /var/cache/debconf/* /var/log/* /tmp/* /var/tmp/*

# =============================================================================
# 7b. Install moonlight-web-stream (PRIMARY browser path: Sunshine NVENC -> WebRTC)
#     Prebuilt x86_64-unknown-linux-gnu release requires glibc 2.39 (= noble),
#     which is the reason this image is on 24.04. web-server spawns the streamer
#     subprocess; both + the static/ web frontend land in /opt/mws. At runtime
#     the entrypoint writes /opt/mws/server/config.json (bind 0.0.0.0:8080, coturn
#     TURN ICE) and launches web-server as the desktop user under its own
#     cloudflared tunnel. mws pairs with Sunshine like a Moonlight client (the
#     first browser login creates the mws admin user; then add host localhost,
#     pair via Sunshine's Web UI PIN, launch an app).
# =============================================================================
RUN mkdir -p /opt/mws/server && cd /tmp && \
    curl -fsSL -o mws.tar.gz \
      "https://github.com/MrCreativ3001/moonlight-web-stream/releases/download/${MWS_VERSION}/moonlight-web-x86_64-unknown-linux-gnu.tar.gz" && \
    tar -xzf mws.tar.gz --strip-components=1 -C /opt/mws && \
    rm mws.tar.gz && \
    chmod +x /opt/mws/web-server /opt/mws/streamer && \
    ls -l /opt/mws/web-server /opt/mws/streamer && \
    chown -R ${USERNAME}:${USERNAME} /opt/mws

# =============================================================================
# 8. Install cloudflared (HTTPS tunnel front for both browser paths)
# =============================================================================
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
#     mws/Selkies/Sunshine then capture. VGL does NOT solve Vulkan PRESENT
#     (DXVK/Proton) — that needs a present surface (gamescope), deferred.
#     Interim Windows-title path is WineD3D (D3D→OpenGL) + vglrun.
# =============================================================================
#     libglu1-mesa is a hard runtime dep of the VirtualGL deb; we pre-install it
#     (and refresh apt lists, which earlier steps wiped) so dpkg -i + apt -f succeed.
RUN apt-get update && apt-get install -y --no-install-recommends libglu1-mesa && \
    cd /tmp && wget -q --show-progress \
      "https://github.com/VirtualGL/virtualgl/releases/download/${VIRTUALGL_VERSION}/virtualgl_${VIRTUALGL_VERSION}_amd64.deb" \
      -O vgl.deb && \
    (dpkg -i vgl.deb || true) && apt-get install -f -y --no-install-recommends && \
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
COPY scripts/vgl-steam scripts/proton-wined3d scripts/vgl-test scripts/install-display-drivers scripts/mws-autopair /opt/dpadcloud/
# Strip any CR (CRLF) line endings — the repo is edited on Windows and
# `#!/bin/bash\r` fails to exec with "no such file or directory". Defense-in-depth.
RUN sed -i 's/\r$//' /opt/dpadcloud/entrypoint.sh /opt/dpadcloud/healthcheck.sh \
        /opt/dpadcloud/vgl-steam /opt/dpadcloud/proton-wined3d /opt/dpadcloud/vgl-test \
        /opt/dpadcloud/install-display-drivers /opt/dpadcloud/mws-autopair \
        ${HOME}/.config/sunshine/sunshine.conf 2>/dev/null || true && \
    chmod +x /opt/dpadcloud/*.sh \
        /opt/dpadcloud/vgl-steam /opt/dpadcloud/proton-wined3d /opt/dpadcloud/vgl-test \
        /opt/dpadcloud/install-display-drivers /opt/dpadcloud/mws-autopair && \
    chown -R ${USERNAME}:${USERNAME} ${HOME}/.config && \
    rm -f ${HOME}/.config/autostart/*.desktop 2>/dev/null || true

# =============================================================================
# 11. Ports
# =============================================================================
# 16100 = Selkies (localhost only; cloudflared tunnels it out over HTTPS) — fallback
# 8080  = moonlight-web-stream (primary browser path; cloudflared tunnels it) —
#         bound 0.0.0.0 so the in-container cloudflared can reach it.
# 3478  = in-image coturn TURN, TCP (relays over the single listening conn — no UDP
#         relay-port range needed). On Vast.ai request the 73478 identity tag
#         (TCP only: -p 73478:73478) and the runtime binds coturn to the real
#         port in VAST_TCP_PORT_73478. (Do NOT also add 73478/udp — Vast flags
#         tcp+udp of the same port as a duplicate.) Both mws and Selkies reuse
#         this one TURN for their WebRTC media relay.
# 47989/47990 = Sunshine (native Moonlight over Tailnet; direct if exposed)
# 41641 = Tailscale WireGuard
EXPOSE 16100/tcp
EXPOSE 8080/tcp
EXPOSE 3478/tcp
EXPOSE 47989/tcp
EXPOSE 47990/tcp
EXPOSE 41641/udp

USER root
ENTRYPOINT ["/opt/dpadcloud/entrypoint.sh"]