#!/bin/bash
# =============================================================================
# extract-nvrtc.sh — replace the Selkies-GStreamer tarball's bundled libnvrtc
# 11.4 with a libnvrtc that can JIT for sm_89 (L4/Ada) + sm_120 (Blackwell).
#
# Why: the bundled GStreamer (1.24.x) ships libnvrtc 11.4.152 (Oct 2021), which
# can't JIT for sm_89/sm_120 → cudaconvert's NVRTC JIT fails:
#   `cudanvrtc: nvrtc: error: invalid value for --gpu-architecture (-arch)`
# The video pipeline starts but produces NO capturable video ("cubin fallback"
# doesn't yield usable frames) → the browser sits on "Waiting for stream"
# (webrtcbin never adds a video m-line, m=video:0). Steam's CEF + the Lutris
# shell both hit this on the L4 / Blackwell.
#
# Fix (canonical, from the official Selkies `selkies-gstreamer-entrypoint.sh`):
# extract a libnvrtc matching the host CUDA, CAPPED to 12.9 for host CUDA>=13
# (GStreamer issue #4655 — 13.x libnvrtc has a cudaconvert ABI mismatch).
# 12.9.86 JITs for sm_89 + sm_120.
#
# Idempotent: no-op if libnvrtc.so.12.9.86 is already in place.
# Tolerant: on download/extract failure it LEAVES the bundled libnvrtc (so the
# boot still works, just with the NVRTC error). A build-time bake (Dockerfile)
# adds a hard `test -f` verify so the image build FAILS loud if the bake didn't
# land; the runtime call (entrypoint) is wrapped in `|| true`.
#
# Used two ways:
#   * Build time (Dockerfile, after the Selkies tarball extract):  RUN this to
#     bake libnvrtc 12.9.86 into the image  →  fast boot, no per-boot download.
#   * Runtime (entrypoint, early in boot):  `bash extract-nvrtc.sh || true`
#     so the entrypoint bind-mount hotfix path ships the fix to EXISTING images
#     (no Docker Hub rebuild — gotcha #19). No-op when baked (MARK check).
#
# Companion docs: STORES-PLAN.md §17.2/§17.5, PROJECT_STATE.md §6 #10.
# Reference impl mirrors cloud/scripts/extract-nvrtc.sh (the live-VM version).
# =============================================================================
set -e

LIBDIR=/opt/gstreamer/lib/x86_64-linux-gnu
MARK="$LIBDIR/libnvrtc.so.12.9.86"

# Fast path: already installed (baked, or a prior run) — just ensure the
# unversioned symlink points at 12.9 + exit. This is the common case once baked.
if [ -f "$MARK" ]; then
    ln -sf libnvrtc.so.12.9.86 "$LIBDIR/libnvrtc.so" 2>/dev/null || true
    exit 0
fi

# The GStreamer lib dir must exist (Selkies tarball extracted). If it doesn't,
# we're running somewhere unexpected — bail without touching anything.
if [ ! -d "$LIBDIR" ]; then
    echo "extract-nvrtc: $LIBDIR not present — nothing to fix (no Selkies tarball?)" >&2
    exit 0
fi

cd /tmp
URL="https://developer.download.nvidia.com/compute/cuda/redist/cuda_nvrtc/linux-x86_64/"
# Pick the newest 12.9.x archive (NVIDIA keeps a couple of patch versions here).
ARCHIVE="$(curl -fsSL "$URL" 2>/dev/null | grep -oP "(?<=href=')cuda_nvrtc-linux-x86_64-12\.9\.[0-9]+-archive\.tar\.xz" | sort -V | tail -n 1)"
if [ -z "$ARCHIVE" ]; then
    echo "extract-nvrtc: no 12.9 archive found at $URL — leaving bundled libnvrtc (NVRTC JIT will fail on sm_89/sm_120)" >&2
    exit 0
fi

if ! curl -fsSL "${URL}${ARCHIVE}" -o /tmp/_nvrtc.txz 2>/dev/null; then
    echo "extract-nvrtc: download failed for ${ARCHIVE} — leaving bundled libnvrtc" >&2
    exit 0
fi

rm -rf /tmp/_cnv && mkdir -p /tmp/_cnv
if ! tar -xJf /tmp/_nvrtc.txz -C /tmp/_cnv 2>/dev/null; then
    echo "extract-nvrtc: tar extract failed — leaving bundled libnvrtc" >&2
    rm -f /tmp/_nvrtc.txz; rm -rf /tmp/_cnv
    exit 0
fi

SRC="$(ls -d /tmp/_cnv/cuda_nvrtc-linux-x86_64-12.9.*-archive/lib 2>/dev/null | head -1)"
if [ -z "$SRC" ] || [ ! -d "$SRC" ]; then
    echo "extract-nvrtc: extracted archive has no lib/ dir — leaving bundled libnvrtc" >&2
    rm -f /tmp/_nvrtc.txz; rm -rf /tmp/_cnv
    exit 0
fi

# Swap in the new libnvrtc. Only rm the old AFTER we have the new in hand (so
# a mid-swap failure can't leave the image with NO libnvrtc at all).
rm -f "$LIBDIR"/libnvrtc.so "$LIBDIR"/libnvrtc.so.11* "$LIBDIR"/libnvrtc.so.12* "$LIBDIR"/libnvrtc-builtins.so*
mv -f "$SRC"/libnvrtc*.so* "$LIBDIR/" 2>/dev/null || true
mv -f "$SRC"/libnvrtc-builtins.so* "$LIBDIR/" 2>/dev/null || true
# Unversioned symlink -> the real 12.9.86 lib (fallback: newest 12.x present).
if [ -f "$MARK" ]; then
    ln -sf libnvrtc.so.12.9.86 "$LIBDIR/libnvrtc.so" 2>/dev/null
else
    _NEW="$(ls "$LIBDIR"/libnvrtc.so.12* 2>/dev/null | grep -v alt | sort -V | tail -1)"
    [ -n "$_NEW" ] && ln -sf "$(basename "$_NEW")" "$LIBDIR/libnvrtc.so" 2>/dev/null
fi

rm -f /tmp/_nvrtc.txz; rm -rf /tmp/_cnv
echo "extract-nvrtc: installed libnvrtc 12.9.86 into $LIBDIR"