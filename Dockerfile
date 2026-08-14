# syntax=docker/dockerfile:1
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
RUN apt-get update && apt-get install -y --no-install-recommends gcc-multilib libc6-dev-i386 make \
    && rm -rf /var/lib/apt/lists/*
COPY scripts/joystick_interposer_v162.c /tmp/joystick_interposer_v162.c
COPY scripts/nvenc_fix.c /tmp/nvenc_fix.c
# evdev gamepad path (DPAD_GAMEPAD_INTERPOSER=evdev, default OFF): the MAIN-branch
# evdev interposer + fake-libudev, built x86_64 + i386 (Steam's main binary is
# 32-bit). Coexists with the v1.6.2 classic interposer; only LD_PRELOAD'd when
# the gate is set (entrypoint.sh). See scripts/gamepad-evdev-fallback/README.md.
COPY scripts/gamepad-evdev-fallback/joystick_interposer_main.c /tmp/joystick_interposer_main.c
COPY scripts/gamepad-evdev-fallback/fake-udev/ /tmp/fake-udev/
RUN mkdir -p /out/x86_64 /out/i386 \
    && gcc -shared -fPIC -O2 -ldl -o /out/x86_64/selkies_joystick_interposer.so /tmp/joystick_interposer_v162.c \
    && gcc -shared -fPIC -O2 -m32 -ldl -o /out/i386/selkies_joystick_interposer.so /tmp/joystick_interposer_v162.c \
    && gcc -shared -fPIC -O2 -o /out/x86_64/libnvenc_fix.so /tmp/nvenc_fix.c -ldl \
    && gcc -shared -fPIC -O2 -ldl -o /out/x86_64/selkies_joystick_interposer_evdev.so /tmp/joystick_interposer_main.c \
    && gcc -shared -fPIC -O2 -m32 -ldl -o /out/i386/selkies_joystick_interposer_evdev.so /tmp/joystick_interposer_main.c \
    && cd /tmp/fake-udev && make all all32 \
    && cp /tmp/fake-udev/libudev.so.1 /out/x86_64/dpad_fake_libudev.so \
    && cp /tmp/fake-udev/libudev_x86.so.1 /out/i386/dpad_fake_libudev.so

# =============================================================================
# Stage: gamescope-builder
#   Builds a PATCHED gamescope from the UPSTREAM 3.16.25 release tag (the 3v1n0
#   PPA only ships 3.16.19; upstream is at 3.16.25 — 6 point releases newer, the
#   bet being a newer gamescope may have fixed the PipeWire black-frame / `out of
#   buffers` race that made the UpCloud L4 stream UNUSABLE; see
#   cloud/docs/UPCLOUD-L4-DEPLOY-2026-07.md §13). meson fetches the wrapped
#   subprojects (glm/stb/wlroots/vkroots/libdisplay-info/libliftoff) itself.
#
#   The single patch (scripts/gamescope-headless-drmprops.patch) is now Fix-1-ONLY
#   (rebased for 3.16.25):
#     - relaxes the headless !drmProps.hasPrimary abort to a warning (headless
#       does no KMS scanout, so a primary DRM node is not required);
#     - adds a /dev/dri/renderD* scan fallback when drmProps.hasRender is false
#       (gamescope's VkPhysicalDeviceDrmPropertiesEXT query returns zeros on some
#       driver/device/container combos even though vulkaninfo sees
#       hasPrimary=hasRender=true on the same device).
#     Reproduced on UpCloud Helsinki NVIDIA L4 (driver 580 AND 595). Same error
#     class as the Metalhost probe (STEAM-PROVIDER-RESEARCH.md §5a) + gamescope
#     #1966. Upstream PR #2073 (merged 2026-04-28) does NOT fix our case — it only
#     added the `if (!hasDrmProps)` (lavapipe) branch; the `!hasPrimary`/`!hasRender`
#     aborts inside the `else` block are UNCHANGED in 3.16.25, so this patch is
#     still required.
#
#   DROPPED vs the old 3.16.19 patch: Fix 2 (gamescope PR #2094 —
#     `screenshotImageFlags.bSampled = true` + the NVIDIA R/B swap). It was the §12
#     diagnosis for the black-frame flicker, but was REBUILT + HUMAN-TESTED on the
#     UpCloud L4 and did NOT fix the flicker (§13): our Selkies `pipewiresrc` path
#     negotiates BGRx (RGB), NOT NV12, so gamescope's `paint_pipewire()`
#     `isYcbcr()` is false and the screenshot-texture path where PR #2094 lives
#     NEVER EXECUTES — it was dead code on our path. Removed to keep the patch
#     focused. (If a future capture path switches to NV12, re-add PR #2094.)
#
#   Build deps come from the 3v1n0 PPA's `apt-get build-dep gamescope` (still
#   deb-src-enabled) — a proven superset of 3.16.25's system-dep needs; the
#   version-sensitive subprojects (wlroots/libliftoff/etc.) are fetched by meson
#   as wraps. Keeps the heavy build deps out of the final image; only the 4
#   patched binaries are COPY'd into vast-vm.
# =============================================================================
FROM nvidia/cuda:${CUDA_VERSION}-base-ubuntu24.04 AS gamescope-builder
ARG DEBIAN_FRONTEND
RUN apt-get update && apt-get install -y --no-install-recommends \
        software-properties-common ca-certificates dpkg-dev git \
        meson ninja-build build-essential pkg-config cmake glslang-tools python3-jinja2 \
    && add-apt-repository -y ppa:3v1n0/gamescope \
    && sed -i 's/^Types: deb$/Types: deb deb-src/' /etc/apt/sources.list.d/3v1n0-*.sources \
    && apt-get update \
    && apt-get build-dep -y gamescope \
    && rm -rf /var/lib/apt/lists/*
COPY scripts/gamescope-headless-drmprops.patch /tmp/gamescope-headless-drmprops.patch
# --recurse-submodules: 3.16.25 added src/reshade (and uses wlroots/libliftoff/vkroots/
# libdisplay-info/openvr/SPIRV-Headers) as git SUBMODULES, not meson wraps
# (reshade has no .wrap). The 3v1n0 apt-get source tarball vendored them; a bare
# git clone leaves the dirs empty -> meson 'Include dir reshade/source does not
# exist'. --shallow-submodules keeps the submodule clones depth-1 (faster).
RUN git clone --depth 1 --branch 3.16.25 --recurse-submodules --shallow-submodules https://github.com/ValveSoftware/gamescope.git /tmp/gamescope \
    && cd /tmp/gamescope \
    && patch -p1 < /tmp/gamescope-headless-drmprops.patch \
    && meson setup build -Denable_tests=false \
    && ninja -C build \
    && mkdir -p /out \
    && cp build/src/gamescope build/src/gamescopereaper build/src/gamescopestream build/src/gamescopectl /out/

# =============================================================================
# Stage: sdl3-builder
#   Builds SDL3 from source with MINIMAL backends — only the subsystems
#   lutris-gamepad-ui needs for gamepad INPUT via its koffi FFI dlopen
#   (joystick/hidapi/events). Video/audio/render/GPU/OpenGL/Vulkan are OFF —
#   the Electron app does the rendering; SDL3 is only on the input path. This
#   fixes PROJECT_STATE.md §6 #12 / STORES-PLAN.md §17.4: lutris-gamepad-ui's
#   koffi dlopen can't find libSDL3 (it lives only in Steam's runtime dirs, not
#   on the system library path) → the SDL3 gamepad path
#   (LUTRIS_GAMEPAD_UI_ENABLE_SDL_INPUT=1) is broken → gamepad won't navigate
#   the Lutris UI. See WAYLAND-ARCHITECTURE.md §5.6.
#
#   SDL3 is NOT in Ubuntu 24.04 (Noble) repos (landed in 24.10 oracular); the
#   oracular libsdl3-0 .deb drags a newer libpipewire-0.3-0t64 +
#   gstreamer1.0-pipewire that would churn the pinned GStreamer/Selkies stack
#   → build from source instead. Minimal backends → small lib + zero dep churn
#   in the final image. Pinned to the latest stable SDL3 (3.2.28, 2025-12-02);
#   bump SDL3_VERSION on rollover. SDL3's SOVERSION is 0 (deliberate — kept
#   across the 3.x series; only bumps on an incompatible change, which would
#   rename the lib to SDL4), so `cmake --install` emits libSDL3.so.0 directly —
#   the exact SONAME lutris-gamepad-ui's koffi dlopens (§17.4). No symlink games.
# =============================================================================
FROM nvidia/cuda:${CUDA_VERSION}-base-ubuntu24.04 AS sdl3-builder
ARG DEBIAN_FRONTEND
ARG SDL3_VERSION=3.2.28
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential cmake ninja-build pkg-config curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*
# Video OFF cascades to render/gpu/opengl/vulkan (all depend on video); audio OFF.
# Joystick/hidapi/events stay ON (the default) — the only subsystems the app
# uses via koffi. SHARED=ON/STATIC=OFF → only the .so ships; no libSDL3.a bloat.
# SDL3's SOVERSION is 0 (deliberate — see SDL3 CMakeLists.txt: "Increment this
# only if there is an incompatible change, but then we should rename the
# library from SDL3 to SDL4"; SOVERSION stays 0 across the 3.x series), so
# `cmake --install` emits libSDL3.so.0.2.28 + the libSDL3.so.0 SONAME symlink +
# the bare libSDL3.so link — i.e. it ALREADY produces the libSDL3.so.0 the app
# dlopens (§17.4). No manual symlinks needed.
# SDL_UNIX_CONSOLE_BUILD=ON skips SDL3's hard FATAL "no X11/Wayland dev libs"
# check (cmake/macros.cmake:381) — we have no X11/Wayland in this builder
# stage + don't want windows anyway (the Electron app renders; SDL3 is input-
# only). The sanctioned skip per SDL3 docs/README-cmake.md.
RUN set -e; \
    mkdir -p /tmp/sdl3 && cd /tmp/sdl3 \
    && curl -fsSL -o SDL3.tar.gz \
      "https://github.com/libsdl-org/SDL/releases/download/release-${SDL3_VERSION}/SDL3-${SDL3_VERSION}.tar.gz" \
    && tar -xzf SDL3.tar.gz --strip-components=1 \
    && cmake -S . -B build -GNinja \
        -DCMAKE_BUILD_TYPE=Release \
        -DCMAKE_INSTALL_PREFIX=/out \
        -DSDL_SHARED=ON -DSDL_STATIC=OFF \
        -DSDL_TESTS=OFF -DSDL_INSTALL_TESTS=OFF \
        -DSDL_VIDEO=OFF -DSDL_AUDIO=OFF \
        -DSDL_UNIX_CONSOLE_BUILD=ON \
    && cmake --build build --parallel "$(nproc)" \
    && cmake --install build \
    && rm -rf /tmp/sdl3
# Sanity: cmake --install produced the SONAME the app dlopens (§17.4's
# "Unable to load libSDL3.so.0") + the real versioned file. No manual symlinks —
# SDL3's SOVERSION is 0, so libSDL3.so.0 is the canonical SONAME, not a stale
# pre-release name.
RUN set -e; \
    cd /out/lib \
    && test -f libSDL3.so.0 \
    && test -f libSDL3.so.0.2.28 \
    && test -L libSDL3.so

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
# evdev gamepad path (default OFF): the evdev interposer + fake-libudev, both
# arches (alongside the v1.6.2 classic interposer above). LD_PRELOAD'd per-arch
# via /usr/$LIB/... only when DPAD_GAMEPAD_INTERPOSER=evdev (entrypoint.sh).
# evdev_bridge.py translates Selkies' js_event -> input_event on the event100N
# sockets (scripts/evdev_bridge.py).
COPY --from=interposer-builder /out/x86_64/selkies_joystick_interposer_evdev.so /usr/lib/x86_64-linux-gnu/selkies_joystick_interposer_evdev.so
COPY --from=interposer-builder /out/i386/selkies_joystick_interposer_evdev.so /usr/lib/i386-linux-gnu/selkies_joystick_interposer_evdev.so
COPY --from=interposer-builder /out/x86_64/dpad_fake_libudev.so /usr/lib/x86_64-linux-gnu/dpad_fake_libudev.so
COPY --from=interposer-builder /out/i386/dpad_fake_libudev.so /usr/lib/i386-linux-gnu/dpad_fake_libudev.so

# --- 4b. NVRTC fix: replace the bundled libnvrtc 11.4 with 12.9.86 ---
#    The Selkies GStreamer tarball above ships libnvrtc 11.4.152, which can't
#    JIT for sm_89 (L4/Ada) or sm_120 (Blackwell) → cudaconvert's NVRTC JIT
#    fails → the video pipeline starts but produces no capturable video
#    (webrtcbin never adds a video m-line; browser stuck on "Waiting for
#    stream"). 12.9.86 JITs for both. Canonical fix from the official Selkies
#    `selkies-gstreamer-entrypoint.sh` (capped to 12.9 for host CUDA>=13 per
#    GStreamer issue #4655). Idempotent + tolerant (leaves the bundled lib on
#    failure); the `test -f` makes the BUILD fail loud if the bake didn't land
#    (a silent skip would ship a broken-stream image). STORES-PLAN.md §17.2,
#    PROJECT_STATE.md §6 #10. Also COPY'd to /opt/dpadcloud/ below so the
#    entrypoint can re-run it (no-op when baked) — lets the entrypoint bind-mount
#    hotfix path ship the fix to EXISTING images without a Docker Hub rebuild.
COPY scripts/extract-nvrtc.sh /tmp/extract-nvrtc.sh
RUN sed -i 's/\r$//' /tmp/extract-nvrtc.sh && chmod +x /tmp/extract-nvrtc.sh \
    && bash /tmp/extract-nvrtc.sh \
    && test -f /opt/gstreamer/lib/x86_64-linux-gnu/libnvrtc.so.12.9.86 \
        || { echo "FATAL: libnvrtc 12.9.86 bake failed — video would be broken"; exit 1; } \
    && rm -f /tmp/extract-nvrtc.sh

# Selkies input router (.pth, auto-loaded; no-op when DPAD_INPUT_DISPLAY unset —
# only the gamescope path sets it). Kept in base so both images share it.
COPY scripts/dpad_input_patch.py scripts/dpad_input_patch.pth /usr/local/lib/python3.12/dist-packages/
# dpad_gamepad_patch.py: under DPAD_GAMEPAD_INTERPOSER=evdev, makes Selkies emit the
# 1360B MAIN-branch js_config_t (vendor 0x045e XBox 360) on the js socket, which
# evdev_bridge.py discards + re-serves on the event100N sockets. Harmless when the
# gate is unset (the .pth no-ops). Mirrors dpad_input_patch.py's .pth pattern.
COPY scripts/dpad_gamepad_patch.py scripts/dpad_gamepad_patch.pth /usr/local/lib/python3.12/dist-packages/

# gamescope headless does not composite the X cursor into its PipeWire output,
# so the only visible cursor source is Selkies' XFIXES cursor overlay. This
# patcher disables Selkies' auto pointer-lock in the web client so the server
# cursor stays visible + mouse stays absolute for UI nav. Both paths need it.
COPY scripts/patch_gst_web_cursors.sh /opt/dpadcloud/patch_gst_web_cursors.sh
RUN chmod +x /opt/dpadcloud/patch_gst_web_cursors.sh \
    && /opt/dpadcloud/patch_gst_web_cursors.sh /opt/gst-web/input.js

# --- 4b. Live-resolution dropdown (§18.7) — bake the in-stream Resolution ---
# selector + the _arg_res data-channel handler into the web client + the
# selkies pip package at build time. The idempotent patcher also runs at boot
# (entrypoint fetch-from-main overlay) so future fixes ship without a rebuild;
# baked here so a brand-new container has the dropdown with NO network fetch.
COPY scripts/patch_live_resolution.py /opt/dpadcloud/patch_live_resolution.py
RUN chmod +x /opt/dpadcloud/patch_live_resolution.py \
    && /opt/dpadcloud/patch_live_resolution.py

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
COPY entrypoint.sh healthcheck.sh scripts/evdev_bridge.py scripts/extract-nvrtc.sh /opt/dpadcloud/
# vgl-steam / proton-wined3d / vgl-test = the Xvfb+VGL debug launchers (kept as
# manual debug fallbacks). dpad-launch (the deprecated Vast steamcmd headless
# launcher, no Steam UI — docs/PROJECT_STATE.md §7) is NO LONGER baked in.
# mws-autopair + bubbleroot are GONE (mws/Sunshine + proot removed).
COPY scripts/vgl-steam scripts/proton-wined3d scripts/vgl-test scripts/install-display-drivers /opt/dpadcloud/
# Strip CR (CRLF) — repo is edited on Windows; `#!/bin/bash\r` fails to exec.
RUN sed -i 's/\r$//' /opt/dpadcloud/entrypoint.sh /opt/dpadcloud/healthcheck.sh \
        /opt/dpadcloud/vgl-steam /opt/dpadcloud/proton-wined3d /opt/dpadcloud/vgl-test \
        /opt/dpadcloud/install-display-drivers /opt/dpadcloud/evdev_bridge.py \
        /opt/dpadcloud/extract-nvrtc.sh \
        ${HOME}/.config/sunshine/sunshine.conf 2>/dev/null || true && \
    chmod +x /opt/dpadcloud/*.sh \
        /opt/dpadcloud/vgl-steam /opt/dpadcloud/proton-wined3d /opt/dpadcloud/vgl-test \
        /opt/dpadcloud/install-display-drivers /opt/dpadcloud/extract-nvrtc.sh && \
    chown -R ${USERNAME}:${USERNAME} ${HOME}/.config && \
    rm -f ${HOME}/.config/autostart/*.desktop 2>/dev/null || true

# Put the user-facing launchers on the DEFAULT PATH (survives /etc/environment reset).
RUN ln -sf /opt/dpadcloud/vgl-steam /usr/local/bin/vgl-steam && \
    ln -sf /opt/dpadcloud/vgl-test /usr/local/bin/vgl-test && \
    ln -sf /opt/dpadcloud/proton-wined3d /usr/local/bin/proton-wined3d

# =============================================================================
# Stage: wayland-display-builder
#   Builds the gst-wayland-display GStreamer plugin (with the `cuda` feature for
#   CUDAMemory zero-copy output) — the compositor + capture layer for the
#   DPAD_COMPOSITOR=wayland-display path (WAYLAND-ARCHITECTURE.md). A Smithay
#   micro-compositor (games-on-whales/gst-wayland-display, commit b15285a2 = the
#   stable head; ≥ the 2025-10 "dynamically link to CUDA" commit e89d9f5, §13.2)
#   that initialises EGL off the DRM render node (NO DRM master → N-on-N
#   preserved, §2.1) and emits CUDAMemory buffers directly to a GStreamer
#   pipeline (no cudaupload/cudaconvert/NVRTC — §2.2).
#
#   SPIKE-VALIDATED 2026-08-08 (built + gst-inspect loads, all 5 properties + the
#   CUDAMemory caps present). See WAYLAND-ARCHITECTURE.md §13 for the full build
#   notes; the findings baked in here:
#   - Build deps: gstreamer-cuda-1.0.pc's Requires pulls gstreamer-gl-1.0 +
#     wayland-client/cursor/egl + x11/x11-xcb + glesv2/opengl (system dev libs;
#     the /opt/gstreamer bundle has the GStreamer 1.24.6 bits but NOT the GL/
#     Wayland/X libs). libclang-dev for Smithay's bindgen (drm/gbm/egl). libssl-dev
#     for cargo-c (openssl-sys). libudev-dev + libinput-dev for Smithay's
#     backend_libinput/backend_udev (the link needs -ludev -linput). libffi-dev +
#     libxml2-dev + libexpat1-dev for the libwayland 1.23 meson build (scanner).
#   - libgobject-2.0-dev / libgmodule-2.0-dev are NOT separate Ubuntu 24.04
#     packages (part of libglib2.0-dev) — do not list them.
#   - Rust ≥1.88 via rustup (apt rustc is too old for edition 2024; the plugin
#     Cargo.toml rust-version = "1.88"). cargo-c via `cargo install cargo-c`.
#   - gst-cuda-1.0 is ALREADY in the /opt/gstreamer bundle (§13.1) → COPY it,
#     PKG_CONFIG_PATH = /usr/local (libwayland 1.23) + /opt/gstreamer. Do NOT
#     apt-install libgstreamer*-dev (system 1.22 — version mismatch).
#   - libwayland 1.23 from source → /usr/local: Ubuntu 24.04 ships 1.22, but
#     wayland-display-core requires the wayland-server `libwayland_1_23` feature
#     (set_default_max_buffer_size — actually CALLED in code, not just a decl,
#     §13.9). Building 1.23.1 from source (meson, ~5 s) is the fix. vast-vm must
#     SHIP /usr/local/lib/x86_64-linux-gnu/libwayland-*.so.0.23.1 (the apt 1.22
#     client/cursor/egl stay; only the server needs 1.23 — but ship all 4 for a
#     consistent set on LD_LIBRARY_PATH). §13.9.
#   - The plugin's `cuda = []` feature does NOT forward to wayland-display-core
#     (`cuda = ["dep:libloading"]`) → must pass `--features "cuda,wayland-
#     display-core/cuda"` (§13.10). Build from the gst-plugin-wayland-display
#     crate dir; cargo-cinstall's [package.metadata.capi.library] install_subdir
#     = "gstreamer-1.0" → the .so lands at /out/lib/x86_64-linux-gnu/gstreamer-1.0/
#     (Debian multiarch libdir, NOT /out/lib/gstreamer-1.0).
#   - The c-bindings C API crate (libgstwaylanddisplay + the display_init input
#     API, §13.5) is NOT built here — it's phase-A native-Wayland input work, not
#     the spike (which validates Steam via gamescope-as-client, input via XTest).
#
#   ORPHAN STAGE (not referenced by vast-vm yet): BuildKit does NOT build
#   unreferenced stages during a normal `docker build .` (target = vast-vm), so
#   adding this stage is a no-op for the current image + the live-site flow. It's
#   buildable explicitly via `docker build --target wayland-display-builder` (the
#   spike validation path). Wiring it into vast-vm (COPY the plugin .so + the
#   libwayland 1.23 .so + add the entrypoint DPAD_COMPOSITOR gate) happens AFTER
#   the live spike validates the compositor→Selkies path on one VM (§8 step 2).
FROM nvidia/cuda:${CUDA_VERSION}-base-ubuntu24.04 AS wayland-display-builder
ARG DEBIAN_FRONTEND
ARG GST_WAYLAND_DISPLAY_REF=b15285a2f1bb4dae5725b049915a4971664fafc6
ARG LIBWAYLAND_VERSION=1.23.1
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential pkg-config curl ca-certificates python3 \
        meson ninja-build \
        libglib2.0-dev \
        libwayland-dev wayland-protocols \
        libdrm-dev libgbm-dev libegl-dev libgles2-mesa-dev libgl-dev \
        libxkbcommon-dev libx11-dev libx11-xcb-dev libxcb1-dev \
        libclang-dev \
        libssl-dev \
        libudev-dev libinput-dev \
        libffi-dev libxml2-dev libexpat1-dev \
    && curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs \
        | sh -s -- -y --default-toolchain stable --profile minimal \
    && rm -rf /var/lib/apt/lists/*
ENV PATH=/root/.cargo/bin:${PATH}
# The GStreamer 1.24.6 bundle (gstreamer-1.0/base/video/cuda/allocators .pc +
# headers + .so) from the base stage. PKG_CONFIG_PATH below makes cargo-c find it.
COPY --from=base /opt/gstreamer /opt/gstreamer
# Build libwayland 1.23 from source → /usr/local. Ubuntu 24.04 only has 1.22;
# gst-wayland-display requires 1.23 (the set_default_max_buffer_size API, gated
# by the wayland-server `libwayland_1_23` feature, is CALLED in code, §13.9).
# /usr/local/lib/x86_64-linux-gnu/pkgconfig/wayland-server.pc (1.23) is found
# BEFORE the apt 1.22 one via PKG_CONFIG_PATH. vast-vm ships the built .so (§13.9).
RUN set -e; \
    curl -fsSL "https://gitlab.freedesktop.org/wayland/wayland/-/archive/${LIBWAYLAND_VERSION}/wayland-${LIBWAYLAND_VERSION}.tar.gz" \
      | tar -xzf - -C /tmp \
    && cd "/tmp/wayland-${LIBWAYLAND_VERSION}" \
    && meson setup build --prefix=/usr/local --buildtype=release \
         -Ddocumentation=false -Dtests=false -Dscanner=true \
    && meson compile -C build \
    && meson install -C build \
    && ldconfig \
    && rm -rf "/tmp/wayland-${LIBWAYLAND_VERSION}" \
    && test -f /usr/local/lib/x86_64-linux-gnu/libwayland-server.so.0
ENV PKG_CONFIG_PATH=/usr/local/lib/x86_64-linux-gnu/pkgconfig:/opt/gstreamer/lib/x86_64-linux-gnu/pkgconfig
RUN cargo install cargo-c
# Build the plugin with the cuda feature (CUDAMemory zero-copy output). The
# `wayland-display-core/cuda` forwarding is REQUIRED (the plugin's `cuda = []`
# doesn't forward to wayland-display-core's `cuda = ["dep:libloading"]`, §13.10).
# install_subdir = "gstreamer-1.0" → /out/lib/x86_64-linux-gnu/gstreamer-1.0/.
RUN set -e; \
    curl -fsSL "https://github.com/games-on-whales/gst-wayland-display/archive/${GST_WAYLAND_DISPLAY_REF}.tar.gz" \
      | tar -xzf - -C /tmp \
    && mv "/tmp/gst-wayland-display-${GST_WAYLAND_DISPLAY_REF}" /tmp/gwd \
    && cd /tmp/gwd/gst-plugin-wayland-display \
    && cargo cinstall --features "cuda,wayland-display-core/cuda" --prefix=/out \
    && test -f /out/lib/x86_64-linux-gnu/gstreamer-1.0/libgstwaylanddisplaysrc.so \
    && rm -rf /tmp/gwd

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
#    libpixman-1-0 is explicitly installed from the PPA (0.46.4) because the
#    gamescope-builder stage's apt-get build-dep pulls libpixman-1-dev 0.46.4
#    from the same PPA, and gamescope 3.16.25's wlroots 0.19 calls
#    pixman_region32_empty which only 0.46.4+ exports — noble's stock 0.42.2
#    exports zero pixman_region32_* symbols, so without this the 3.16.25
#    gamescope binary crashes at startup with 'undefined symbol:
#    pixman_region32_empty'.
#    sway + xwayland: the §16.4 fallback Wayland client for
#    DPAD_COMPOSITOR=wayland-display. gamescope --backend wayland drops its
#    client connection to gst-wayland-display on Nvidia after Steam launches
#    (§16.3, 'IWaitable hung up'); sway (a wlroots compositor run NESTED as a
#    Wayland client of gst-wayland-display, the games-on-whales RUN_SWAY=1 model)
#    is the documented more-stable fallback. sway provides XWayland to Steam/
#    Lutris (same role as gamescope-as-client); the compositor still captures it.
#    `xwayland` is the XWayland binary sway launches for X apps. INERT by
#    default: nothing launches sway until the entrypoint's DPAD_WAYLAND_CLIENT=sway
#    gate (default gamescope = no regression). PENDING LIVE VALIDATION (§16.5 step 4).
RUN apt-get update && apt-get install -y --no-install-recommends software-properties-common && \
    add-apt-repository -y ppa:3v1n0/gamescope && \
    apt-get update && apt-get install -y --no-install-recommends \
        gamescope pipewire pipewire-audio pipewire-pulse pipewire-audio-client-libraries \
        wireplumber libeis-dev gstreamer1.0-pipewire \
        gstreamer1.0-tools gstreamer1.0-plugins-good gstreamer1.0-plugins-bad \
        gstreamer1.0-x gstreamer1.0-plugins-base pulseaudio-utils \
        libpixman-1-0 \
        sway xwayland && \
    for b in gamescope gamescopereaper gamescopestream gamescopectl; do \
        [ -e /usr/games/$b ] && ln -sf /usr/games/$b /usr/bin/$b; \
    done && \
    (command -v gamescope && gamescope --version 2>&1 | head -1) && \
    (command -v sway && sway --version 2>&1 | head -1) && \
    rm -rf /var/lib/apt/lists/*

# --- Patched gamescope binaries from gamescope-builder (headless hasPrimary /
#    render-node fix — see gamescope-headless-drmprops.patch). Overrides the
#    deb's /usr/games/ binaries; the /usr/bin symlinks above stay valid. ---
COPY --from=gamescope-builder /out/gamescope /out/gamescopereaper /out/gamescopestream /out/gamescopectl /tmp/gs-patched/
RUN cp -f /tmp/gs-patched/gamescope       /usr/games/gamescope \
    && cp -f /tmp/gs-patched/gamescopereaper /usr/games/gamescopereaper \
    && cp -f /tmp/gs-patched/gamescopestream /usr/games/gamescopestream \
    && cp -f /tmp/gs-patched/gamescopectl  /usr/games/gamescopectl \
    && chmod 755 /usr/games/gamescope /usr/games/gamescopereaper /usr/games/gamescopestream /usr/games/gamescopectl \
    && rm -rf /tmp/gs-patched

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

# --- Multi-store foundation (docs/STORES-PLAN.md). OFF by default: these
#    layers just PLACE binaries in the image; nothing launches them until the
#    entrypoint's DPAD_STORE_SHELL gate is wired (a later commit). The
#    validated Steam path (gamescope --backend headless -- steam -gamepadui)
#    is UNCHANGED — a fresh build still boots Steam exactly as before. Build-
#    test in isolation: `docker build --target vast-vm` succeeds + the image
#    still reaches DPAD_READY on a Steam session. v1 stores = Steam + Epic +
#    GOG + Battle.net; EA App + Ubisoft Connect are v1.1 drop-ins (same
#    pattern as Battle.net). ---
#
#    (0) Heroic Games Launcher — the Epic + GOG store backend. Heroic is an
#        Electron app (like dpad-launcher) that bundles `legendary` (Epic CLI)
#        + `gogdl` (GOG CLI) for login, game install, + game launch. The
#        epic-launch / gog-launch wrappers spawn it in the same sway/XWayland
#        session. The .deb is ~150 MB; the accountsservice dep avoids a D-Bus
#        degradation warning (Steam-Headless #210). --no-sandbox at runtime
#        (no setuid chrome-sandbox in the container). Heroic config persists on
#        the volume via setup_stores (~/.config/heroic -> <vol>/heroic-config).
#        NOTE: Heroic is also installed in the vast-docker stage (the deprecated
#        :dpad-heroic image); this vast-vm install is separate so the SteamOS
#        image has it for the Epic/GOG store cards. The base ARG HEROIC_VERSION
#        (v2.22.0) is inherited.
ARG HEROIC_VERSION
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

#    (a0) Pre-bake Heroic's Wine tools (DXVK, VKD3D-Proton, DXVK-NVAPI) so
#         Heroic doesn't try to download them at runtime (which fails on
#         transient network issues — the vkd3d-proton download from GitHub
#         socket-hangs ~50% of the time on fresh VMs). Heroic checks for the
#         existing dir in ~/.config/heroic/tools/ and skips the download if
#         present. Versions match what Heroic 2.22.0 fetches by default.
ARG VKD3D_PROTON_TAG=v2.14.1
ARG VKD3D_PROTON_FILE=vkd3d-proton-2.14.1
ARG DXVK_VERSION=dxvk-3.0.2
ARG DXVK_NVAPI_VERSION=dxvk-nvapi-v0.9.2
RUN set -e; \
    TOOLS_DIR="${HOME}/.config/heroic/tools"; \
    mkdir -p "${TOOLS_DIR}/vkd3d" "${TOOLS_DIR}/dxvk" "${TOOLS_DIR}/dxvk-nvapi"; \
    curl -fsSL -o /tmp/vkd3d.tar.xz \
      "https://github.com/Heroic-Games-Launcher/vkd3d-proton/releases/download/${VKD3D_PROTON_TAG}/${VKD3D_PROTON_FILE}.tar.xz" \
    && tar -xf /tmp/vkd3d.tar.xz -C "${TOOLS_DIR}/vkd3d" --strip-components=1 \
    && rm -f /tmp/vkd3d.tar.xz \
    && curl -fsSL -o /tmp/dxvk.tar.gz \
      "https://github.com/doitsujin/dxvk/releases/download/v3.0.2/${DXVK_VERSION}.tar.gz" \
    && tar -xzf /tmp/dxvk.tar.gz -C "${TOOLS_DIR}/dxvk" --strip-components=1 \
    && rm -f /tmp/dxvk.tar.gz \
    && curl -fsSL -o /tmp/dxvk-nvapi.tar.gz \
      "https://github.com/jp7677/dxvk-nvapi/releases/download/v0.9.2/${DXVK_NVAPI_VERSION}.tar.gz" \
    && tar -xzf /tmp/dxvk-nvapi.tar.gz -C "${TOOLS_DIR}/dxvk-nvapi" --strip-components=1 \
    && rm -f /tmp/dxvk-nvapi.tar.gz \
    && chown -R ${USERNAME}:${USERNAME} "${TOOLS_DIR}" \
    && test -d "${TOOLS_DIR}/vkd3d/x64" \
    && test -d "${TOOLS_DIR}/dxvk/x64" \
    && test -d "${TOOLS_DIR}/dxvk-nvapi/x64"

#    (a0b) Suppress Heroic's "new version available" nag. The .deb install
#          can't auto-update, so the notification is noise. Heroic reads
#          checkForUpdates from ~/.config/heroic/store/config.json.
RUN mkdir -p "${HOME}/.config/heroic/store" && \
    echo '{"checkForUpdates":false,"darkMode":true,"minimizeOnClose":true,"autoUpdateGames":false}' \
    > "${HOME}/.config/heroic/store/config.json" && \
    chown -R ${USERNAME}:${USERNAME} "${HOME}/.config/heroic"

#    (a) GE-Proton11-3 into compatibilitytools.d. The Battle.net white-screen
#        fix is in (GE-Proton11-2 changelog: "Battle.net: fixed Wine Wayland
#        white-screen behavior" + "--in-process-gpu handling for Wine Wayland
#        launchers"); 11-3 is the hotfix on top. Also bundles the NVIDIA
#        compatibility libs (NVAPI/CUDA/NVENC/NVML/OptiX) + umu.exe ("works
#        the same way steam.exe does… helps 3rd-party launchers run the same
#        way Steam runs them") + the Diablo IV/Marvel Rivals upstream fixes +
#        the DualSense haptics/hotplug work. All Windows launchers run via
#        Xwayland (PROTON_ENABLE_WAYLAND unset) — STORES-PLAN §4/§5. Not yet
#        SHA-pinned (matches the existing curl-download pattern; a future
#        hardening can add the .sha512sum check + an ARG bump on version rollover).
ARG GE_PROTON_VERSION=GE-Proton11-3
RUN set -e; \
    GP_DIR="${HOME}/.steam/debian-installation/compatibilitytools.d/${GE_PROTON_VERSION}"; \
    mkdir -p "${GP_DIR}"; \
    curl -fsSL -o /tmp/ge-proton.tar.gz \
      "https://github.com/GloriousEggroll/proton-ge-custom/releases/download/${GE_PROTON_VERSION}/${GE_PROTON_VERSION}.tar.gz" \
    && tar -xzf /tmp/ge-proton.tar.gz -C "${GP_DIR}" --strip-components=1 \
    && rm -f /tmp/ge-proton.tar.gz \
    && chown -R ${USERNAME}:${USERNAME} "${GP_DIR}" \
    && test -x "${GP_DIR}/proton"  # sanity: the runner binary is present + executable

#    (b) lutris-gamepad-ui AppImage (v0.2.0) — the Option-B2 store-picker shell
#        (a gamepad-navigable 10-foot-UI frontend over Lutris). Downloaded but
#        NOT launched yet (the entrypoint DPAD_STORE_SHELL gate is a later
#        commit). v0.2.0 migrated to SDL3 input (aligns with
#        LUTRIS_GAMEPAD_UI_ENABLE_SDL_INPUT=1, which the entrypoint will set —
#        the Web Gamepad API default won't work in-container) + has Ubuntu-
#        24.04 fallbacks in its Python wrapper (aligns with this image's base).
#        Lutris itself (the backend) is installed in a later commit (piece 1b).
ARG LUTRIS_GAMEPAD_UI_VERSION=v0.2.0
RUN set -e; \
    curl -fsSL -o /tmp/lutris-gamepad-ui.AppImage \
      "https://github.com/andrew-ld/lutris-gamepad-ui/releases/download/${LUTRIS_GAMEPAD_UI_VERSION}/lutris-gamepad-ui-x64.AppImage" \
    && chmod +x /tmp/lutris-gamepad-ui.AppImage \
    && test -s /tmp/lutris-gamepad-ui.AppImage \
    && cd /opt/dpadcloud && /tmp/lutris-gamepad-ui.AppImage --appimage-extract >/dev/null 2>&1 \
    && mv /opt/dpadcloud/squashfs-root /opt/dpadcloud/lutris-gamepad-ui \
    && rm -f /tmp/lutris-gamepad-ui.AppImage \
    && test -x /opt/dpadcloud/lutris-gamepad-ui/AppRun  # sanity: extracted AppRun is executable (no FUSE needed at runtime)

#    lutris-shell wrapper — the entrypoint's DPAD_STORE_SHELL gate (a later
#    commit) execs this instead of `steam -gamepadui` when DPAD_STORE_SHELL=lutris.
#    Mirrors scripts/heroic-launch (the vast-docker Heroic wrapper): sets
#    LUTRIS_GAMEPAD_UI_ENABLE_SDL_INPUT=1 + --no-sandbox + runs the extracted
#    AppRun. See scripts/lutris-shell for the full rationale.
COPY scripts/lutris-shell /opt/dpadcloud/lutris-shell
RUN sed -i 's/\r$//' /opt/dpadcloud/lutris-shell && chmod +x /opt/dpadcloud/lutris-shell

#    (c) dpad-launcher — the 10-foot Electron store-picker shell (replaces
#        lutris-gamepad-ui; the entrypoint's DPAD_STORE_SHELL=picker gate execs
#        launcher-shell). Shipped as the forcespt/dpadcloud-launcher Docker image
#        (a FROM-scratch file bundle holding the Linux Electron AppDir at
#        /opt/dpadcloud/launcher, built locally via launcher/scripts/build.sh +
#        launcher/Dockerfile). The AppDir bundles koffi (native, unpacked) for
#        the SDL3 gamepad poll. The Electron runtime libs (libnss/libgtk/
#        libasound/libxss/...) are already present (lutris-gamepad-ui is also
#        Electron); libSDL3.so.0 below is shared with lutris-gamepad-ui's koffi
#        path. See launcher/README + WAYLAND-ARCHITECTURE.md.
COPY --from=forcespt/dpadcloud-launcher:0.1.3 /opt/dpadcloud/launcher /opt/dpadcloud/launcher
RUN chmod +x /opt/dpadcloud/launcher/dpad-launcher
#    launcher-shell wrapper — the entrypoint's DPAD_STORE_SHELL=picker gate
#    execs this instead of `steam -gamepadui` / `lutris-shell` (--no-sandbox;
#    inherits the session's SDL3/interposer env).
COPY scripts/launcher-shell /opt/dpadcloud/launcher-shell
RUN sed -i 's/\r$//' /opt/dpadcloud/launcher-shell && chmod +x /opt/dpadcloud/launcher-shell
#    launcher-toggle — bound to Super+L in the sway config; shows the launcher
#    from scratchpad or relaunches it if the process died (recovery path).
COPY scripts/launcher-toggle /opt/dpadcloud/launcher-toggle
RUN sed -i 's/\r$//' /opt/dpadcloud/launcher-toggle && chmod +x /opt/dpadcloud/launcher-toggle

#    (c2) battlenet-launch — the Battle.net store wrapper the dpad-launcher's
#         "Battle.net" card spawns (launcher/src/main.js). Runs the Blizzard
#         installer into a Wine prefix on first launch, then launches Battle.net.exe
#         under GE-Proton11-3 (the white-screen fix). The prefix lives at
#         ~/Games/battlenet (-> <vol>/games/battlenet via setup_stores). STORES-PLAN §7.
#         On PATH at /usr/local/bin so the launcher's `which('battlenet-launch')`
#         availability check resolves it (mirror the gamescope/lutris symlink pattern).
COPY scripts/battlenet-launch /opt/dpadcloud/battlenet-launch
RUN sed -i 's/\r$//' /opt/dpadcloud/battlenet-launch && chmod +x /opt/dpadcloud/battlenet-launch \
    && ln -sf /opt/dpadcloud/battlenet-launch /usr/local/bin/battlenet-launch \
    && test -x /usr/local/bin/battlenet-launch

#    (c2b) ea-launch + ubisoft-launch — the EA App + Ubisoft Connect store
#         wrappers the dpad-launcher's "EA App" / "Ubisoft Connect" cards spawn
#         (launcher/src/main.js). Same pattern as battlenet-launch: run the
#         Windows installer (EAappInstaller.exe / UbisoftConnectInstaller.exe)
#         into a Wine prefix on first launch under GE-Proton11-3 via umu-run,
#         then launch EALauncher.exe / UbisoftConnect.exe with CEF software
#         compositing (--disable-gpu --in-process-gpu). Prefixes live at
#         ~/Games/ea-app + ~/Games/ubisoft (-> <vol>/games/ea-app /
#         <vol>/games/ubisoft via setup_stores). STORES-PLAN §8 (v1.1 drop-ins,
#         now promoted to v1). On PATH at /usr/local/bin so the launcher's
#         `which()` availability check resolves it. ⚠️ Ubisoft Connect is
#         more fragile than EA App (April 2026 client update broke auth under
#         standard Proton; GE-Proton is the workaround — see ubisoft-launch
#         header). Live validation required.
COPY scripts/ea-launch /opt/dpadcloud/ea-launch
COPY scripts/ubisoft-launch /opt/dpadcloud/ubisoft-launch
COPY scripts/dpad-open-url /opt/dpadcloud/dpad-open-url
RUN sed -i 's/\r$//' /opt/dpadcloud/ea-launch /opt/dpadcloud/ubisoft-launch /opt/dpadcloud/dpad-open-url \
    && chmod +x /opt/dpadcloud/ea-launch /opt/dpadcloud/ubisoft-launch /opt/dpadcloud/dpad-open-url \
    && ln -sf /opt/dpadcloud/ea-launch /usr/local/bin/ea-launch \
    && ln -sf /opt/dpadcloud/ubisoft-launch /usr/local/bin/ubisoft-launch \
    && ln -sf /opt/dpadcloud/dpad-open-url /usr/local/bin/xdg-open \
    && test -x /usr/local/bin/ea-launch \
    && test -x /usr/local/bin/ubisoft-launch \
    && test -x /usr/local/bin/xdg-open

#    (c2a) epic-launch + gog-launch — the Epic + GOG store wrappers the
#         dpad-launcher's "Epic Games" / "GOG" cards spawn (launcher/src/main.js).
#         Each spawns Heroic Games Launcher (baked in the base stage, inherited
#         by vast-vm), which bundles legendary (Epic) / gogdl (GOG) for login +
#         game install + game launch. On PATH at /usr/local/bin so the launcher's
#         `which()` availability check resolves it (mirror the battlenet-launch
#         symlink pattern). The prefix/game installs + Heroic config persist on
#         the volume via the entrypoint's setup_stores. STORES-PLAN §7.
COPY scripts/epic-launch /opt/dpadcloud/epic-launch
COPY scripts/gog-launch /opt/dpadcloud/gog-launch
RUN sed -i 's/\r$//' /opt/dpadcloud/epic-launch /opt/dpadcloud/gog-launch \
    && chmod +x /opt/dpadcloud/epic-launch /opt/dpadcloud/gog-launch \
    && ln -sf /opt/dpadcloud/epic-launch /usr/local/bin/epic-launch \
    && ln -sf /opt/dpadcloud/gog-launch /usr/local/bin/gog-launch \
    && test -x /usr/local/bin/epic-launch \
    && test -x /usr/local/bin/gog-launch

#    (d) libSDL3 for lutris-gamepad-ui's gamepad input (koffi FFI dlopen). SDL3
#        is NOT in Noble repos; the oracular libsdl3-0 .deb churns the pinned
#        GStreamer/PipeWire stack → built from source in the sdl3-builder stage
#        with MINIMAL backends (joystick/hidapi/events only — the Electron app
#        renders; SDL3 is only on the input path). Fixes §17.4: the app's koffi
#        dlopen("libSDL3.so.0") couldn't find libSDL3 (it lived only in Steam's
#        runtime dirs) → gamepad wouldn't navigate the Lutris UI. SDL3's SOVERSION
#        is 0 (deliberate, stays 0 across 3.x — see the SDL3 CMakeLists.txt), so
#        cmake --install already emits libSDL3.so.0 (the exact SONAME the app
#        dlopens) + the bare libSDL3.so link; the COPY glob carries both. See
#        WAYLAND-ARCHITECTURE.md §5.6. Independent of the compositor: ships
#        gamepad nav for the Lutris shell under BOTH the current gamescope-
#        headless path AND the new wayland-display path.
COPY --from=sdl3-builder /out/lib/libSDL3.so.0.2.28 /usr/lib/x86_64-linux-gnu/libSDL3.so.0.2.28
# Recreate the SONAME + bare-link symlinks (Docker COPY derefs symlinks on a
# glob, which would duplicate the ~1.5MB lib as 3 real files + spew ldconfig
# "not a symbolic link" warnings). One real file + two relative symlinks.
RUN set -e; \
    cd /usr/lib/x86_64-linux-gnu \
    && ln -sf libSDL3.so.0.2.28 libSDL3.so.0 \
    && ln -sf libSDL3.so.0.2.28 libSDL3.so \
    && ldconfig \
    && test -L libSDL3.so.0 \
    && test -e libSDL3.so.0  # sanity: the SONAME the app dlopens resolves

# --- DPAD_COMPOSITOR=wayland-display: the gst-wayland-display plugin (the
#     compositor + capture layer, WAYLAND-ARCHITECTURE.md). Built in the
#     wayland-display-builder stage (Smithay + the `cuda` feature → CUDAMemory
#     zero-copy output). Dropped into the default GStreamer plugin dir so
#     selkies-gstreamer's `Gst.ElementFactory.make("waylanddisplaysrc")` finds
#     it (the patch_selkies_waylanddisplay.py branch, gated on
#     DPAD_VIDEO_SRC=waylanddisplaysrc). INERT by default: the gamescope-headless
#     path never instantiates the element (the plugin's cuda init only runs when
#     waylanddisplaysrc is created). The runtime libwayland is the prod image's
#     1.24.0 (≥1.23 — already has wl_client_set_max_buffer_size; no libwayland
#     COPY needed, §13.14). Live-validated on an OVH L4 (§13.14).
COPY --from=wayland-display-builder /out/lib/x86_64-linux-gnu/gstreamer-1.0/libgstwaylanddisplaysrc.so /opt/gstreamer/lib/x86_64-linux-gnu/gstreamer-1.0/libgstwaylanddisplaysrc.so

# Apply the waylanddisplaysrc capture-branch patch to Selkies (in the vast-vm
# stage, late, so the base stage stays cached — base already bakes the pipewire
# patch; this patch anchors on the pipewire-patched gstwebrtc_app.py). Gated on
# DPAD_VIDEO_SRC=waylanddisplaysrc; default pipewiresrc → no regression.
COPY scripts/patch_selkies_waylanddisplay.py /opt/dpadcloud/patch_selkies_waylanddisplay.py
RUN python3 /opt/dpadcloud/patch_selkies_waylanddisplay.py /usr/local/lib/python3.12/dist-packages/selkies_gstreamer/gstwebrtc_app.py \
    && rm -f /opt/dpadcloud/patch_selkies_waylanddisplay.py

#    (c) Wine + winetricks + Lutris (the backend the gamepad-UI shells out to).
#        i386 is already enabled in the base stage; libgtk-3-0t64 + python3-gi are
#        already installed there, so the Lutris .deb's apt-resolved deps are
#        mostly present (it pulls webkit2gtk for the store-login browser auth,
#        libnotify, etc. automatically). Lutris v0.5.22 .deb from the GitHub
#        releases page (matches the existing Steam.deb / Heroic.deb pattern;
#        apt resolves the GTK/python/system deps). NOT launched yet — the
#        entrypoint DPAD_STORE_SHELL gate is a later commit; today the image
#        still boots Steam. umu-launcher (GE-Proton via umu for non-Steam
#        Windows games) is DEFERRED to piece 1c: the Battle.net install script
#        uses runner: wine, so the Wine stack alone makes Lutris functional
#        for the v1 Battle.net pre-bake (piece 2). STORES-PLAN §7.
ARG LUTRIS_VERSION=v0.5.22
RUN set -e; \
    apt-get update && apt-get install -y --no-install-recommends wine wine32 wine64 winetricks \
    && rm -rf /var/lib/apt/lists/* \
    && command -v wine && command -v winetricks \
    && cd /tmp && curl -fsSL -o /tmp/lutris.deb \
      "https://github.com/lutris/lutris/releases/download/${LUTRIS_VERSION}/lutris_${LUTRIS_VERSION#v}_all.deb" \
    && apt-get update && ( apt-get install -y --no-install-recommends /tmp/lutris.deb \
                           || ( apt-get install -f -y && dpkg -i /tmp/lutris.deb ) ) \
    && rm -f /tmp/lutris.deb && rm -rf /var/lib/apt/lists/* \
    && ln -sf /usr/games/lutris /usr/bin/lutris \
    && command -v lutris  # sanity: the Lutris CLI is on PATH (deb ships it in /usr/games, symlink to /usr/bin — same as gamescope)

#    (e) umu-launcher — the Steam-Linux-Runtime container wrapper for non-Steam
#        Windows games (STORES-PLAN §10 piece 1c). Replaces raw `wine` in
#        battlenet-launch so the 32-bit Blizzard Update Agent (Agent.exe) runs
#        under Valve's tested wow64 (inside the Steam Linux Runtime container)
#        instead of Wine 11's experimental new wow64 — the documented-fragile
#        manual-wine wall that stalled the Battle.net install (PROJECT_STATE §18).
#        umu-run wraps GE-Proton11-3 (the white-screen fix + the NVIDIA compat
#        libs) in the SLR + applies store/game protonfixes (STORE=battlenet).
#        The deb ships only the umu-run Python launcher + the umu_delta Rust
#        ext (~3 MB, cpython-3.12 — matches Noble's Python 3.12); the ~1–2 GB
#        Steam Linux Runtime + pressure-vessel download to
#        $HOME/.local/share/umu on the FIRST umu-run (one-time per VM, first-
#        run latency; the VM has network). Deps apt-resolved: python3-xlib,
#        apparmor-profiles (ships the bwrap-userns-restrict extra profile the
#        deb's /etc/apparmor.d/bwrap-userns-restrict-umu symlink points at),
#        libgl1-mesa-dri:i386 + libglx-mesa0:i386 (32-bit GL for the SLR's
#        matched 32-bit libs — i386 is already enabled in the base stage for
#        wine32), libzstd1. The AppArmor profile is moot in our session
#        container (it runs --security-opt apparmor=unconfined + seccomp=
#        unconfined + --cap-add SYS_ADMIN, the bwrap-nest flag set,
#        IMAGE-RUNBOOK; + the host sysctls kernel.unprivileged_userns_clone=1
#        + kernel.apparmor_restrict_unprivileged_userns=0 via vm-bootstrap).
#        If pressure-vessel hits "Can't mount proc on /newroot/proc" at runtime,
#        add --security-opt systempaths=unconfined to the docker run (the
#        fourth bwrap-nest flag) — a runtime-validation item.
ARG UMU_VERSION=1.4.4
RUN set -e; \
    apt-get update && apt-get install -y --no-install-recommends \
        python3-xlib apparmor-profiles libzstd1 \
        libgl1-mesa-dri:i386 libglx-mesa0:i386 \
    && rm -rf /var/lib/apt/lists/* \
    && cd /tmp && curl -fsSL -o /tmp/umu.deb \
      "https://github.com/Open-Wine-Components/umu-launcher/releases/download/${UMU_VERSION}/python3-umu-launcher_${UMU_VERSION}-1_amd64_ubuntu-noble.deb" \
    && apt-get update && ( apt-get install -y --no-install-recommends /tmp/umu.deb \
                           || ( apt-get install -f -y && dpkg -i /tmp/umu.deb ) ) \
    && rm -f /tmp/umu.deb && rm -rf /var/lib/apt/lists/* \
    && command -v umu-run \
    && test -s /usr/bin/umu-run \
    && python3 -c 'import umu.umu_consts'   # sanity: the launcher imports (do NOT run umu-run — it fetches the ~1-2 GB SLR on first exec)

#    (f) Build-time Battle.net prefix prebake (STORES-PLAN §7 piece 2 / §10
#        piece 2). Runs `umu-run winetricks` (corefonts win10 vcrun2022
#        d3dcompiler_47) at BUILD time as the dpad user on Xvfb :9 (software GL,
#        no GPU needed) → bakes the winetricks-initialized Wine prefix at
#        /opt/dpadcloud/battlenet-prefix (+ the Battle.net.config + the downloaded
#        Battle.net-Setup.exe + a .dpad-prebaked marker) + the Steam Linux
#        Runtime at /home/dpad/.local/share/umu (~657 MB, reused at runtime → no
#        first-run umu SLR download). The Blizzard installer itself is NOT run
#        at build time (its Chromium GUI won't complete headless — validated:
#        even --disable-gpu under Xvfb stalls before Battle.net.exe); the runtime
#        battlenet-launch copies this prefix to the session WINEPREFIX on first
#        launch + runs the installer there (user clicks through in the stream).
#        Cuts the ~2-min winetricks + the SLR download from every first launch.
#        Idempotent + best-effort (always exits 0; on failure the marker isn't
#        written + battlenet-launch falls back to the full runtime winetricks).
#        Placed late so entrypoint/script edits don't invalidate this expensive
#        (~3-5 min: SLR download + winetricks) layer.
#        ⚠️ BAKE METHOD (2026-08-12): this build-time prebake does NOT work
#        under buildkit — wineserver/wine crash in buildkit's user-namespace
#        sandbox (the `--security=insecure` RUN entitlement does NOT fix it;
#        umu's pressure-vessel→bwrap needs full privileges). So this RUN is a
#        graceful no-op on a standard `docker build` (the script exits 0
#        without the marker). The prebake is baked via the privileged-container
#        + commit workflow — see scripts/build-bootstrap-battlenet.sh header
#        (docker run --privileged → build-bootstrap-battlenet.sh →
#        docker commit -c 'ENTRYPOINT[...]' -c 'CMD[...]' → a FROM-commit
#        fixup bakes the latest battlenet-launch). Best-effort: a non-privileged
#        build ships without the prebake + the runtime battlenet-launch falls
#        back to the full winetricks + installer (no broken image).
COPY scripts/build-bootstrap-battlenet.sh /tmp/build-bootstrap-battlenet.sh
RUN chmod +x /tmp/build-bootstrap-battlenet.sh \
    && /tmp/build-bootstrap-battlenet.sh \
    && rm -f /tmp/build-bootstrap-battlenet.sh \
    && chown -R ${USERNAME}:${USERNAME} /opt/dpadcloud/battlenet-prefix ${HOME}/.local/share/umu 2>/dev/null || true

#    (f3) EA App prebake — same pattern as Battle.net: winetricks-initialized
#         prefix + EAappInstaller.exe + the SLR (shared with battlenet). The
#         runtime ea-launch copies this prefix on first launch → skips the
#         ~2-min winetricks + SLR download + installer download. Same
#         privileged-container + commit workflow (see battlenet header).
#         Best-effort: a non-privileged build ships without the prebake +
#         ea-launch falls back to the full winetricks + installer.
COPY scripts/build-bootstrap-ea.sh /tmp/build-bootstrap-ea.sh
RUN chmod +x /tmp/build-bootstrap-ea.sh \
    && /tmp/build-bootstrap-ea.sh \
    && rm -f /tmp/build-bootstrap-ea.sh \
    && chown -R ${USERNAME}:${USERNAME} /opt/dpadcloud/ea-prefix ${HOME}/.local/share/umu 2>/dev/null || true

EXPOSE 16100/tcp
# 3478 (coturn TURN) opt-in via -p 3478:3478 at launch. No 8080/47989/47990/41641.
USER root
ENTRYPOINT ["/opt/dpadcloud/entrypoint.sh"]