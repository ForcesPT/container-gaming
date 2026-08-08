#!/usr/bin/env python3
# patch_selkies_waylanddisplay.py — make Selkies capture the gst-wayland-display
# compositor (waylanddisplaysrc, CUDAMemory zero-copy) instead of gamescope's
# PipeWire node (pipewiresrc) or the Xvfb :2 bridge (ximagesrc).
#
# DPAD_COMPOSITOR=wayland-display path (WAYLAND-ARCHITECTURE.md). A Smithay
# micro-compositor (games-on-whales/gst-wayland-display) runs AS the GStreamer
# source element: it initialises EGL off the DRM render node (NO DRM master →
# N-on-N) + emits CUDAMemory buffers directly. gamescope runs as a Wayland
# CLIENT of this compositor (--backend wayland) + provides XWayland :0 to
# Steam/Wine. The compositor creates wayland-N in $XDG_RUNTIME_DIR on start;
# the entrypoint polls for it + launches gamescope with WAYLAND_DISPLAY=wayland-N.
#
# Gated on DPAD_VIDEO_SRC=waylanddisplaysrc (set by the entrypoint gate when
# DPAD_COMPOSITOR=wayland-display). Default DPAD_VIDEO_SRC=pipewiresrc → the
# gamescope-headless path is unchanged (no regression).
#
# Pipeline (nvh264enc) — NO cudaupload/cudaconvert (the source is already
# CUDAMemory; live-proven on an OVH L4 that waylanddisplaysrc ! nvh264enc
# negotiates directly + NVRTC-error=0, §13.14):
#   waylanddisplaysrc(cuda-device-id=0) -> capsfilter(CUDAMemory,BGRA,WxH@N/1) ->
#   nvh264enc -> h264enc_capsfilter -> rtph264pay -> webrtcbin
#
# Patches (idempotent on the patched result; runs AFTER patch_selkies_pipewire.py):
#   1. build_video_pipeline source branch: prepend `if waylanddisplaysrc:` before
#      the pipewire `if pipewiresrc:` (turning it into if/elif/else). The wayland
#      branch makes self.ximagesrc=waylanddisplaysrc + the CUDAMemory BGRA caps
#      (also the compositor's output WxH@N). No videorate (the compositor renders
#      at the negotiated framerate).
#   2. assembly: for the waylanddisplaysrc path, skip cudaupload/cudaconvert/
#      cudaconvert_capsfilter (link waylanddisplaysrc -> nvh264enc directly).
#      The pipewire patch's set_pointer_visible + start_ximagesrc guards already
#      cover waylanddisplaysrc (it lacks show-pointer/endx, same as pipewiresrc),
#      + set_framerate's pipewire-patched else branch handles the CUDAMemory
#      capsfilter — no new guards needed.
#
# Usage: python3 patch_selkies_waylanddisplay.py [path/to/gstwebrtc_app.py]
# (Run AFTER patch_selkies_pipewire.py — anchors on the pipewire-patched `if
# pipewiresrc:` line + the nvh264enc assembly line.)
import sys, ast

path = sys.argv[1] if len(sys.argv) > 1 else "/usr/local/lib/python3.12/dist-packages/selkies_gstreamer/gstwebrtc_app.py"
WAYLAND_MARK = 'os.environ.get("DPAD_VIDEO_SRC", "") == "waylanddisplaysrc"'
PIPEWIRE_IF = '        if os.environ.get("DPAD_VIDEO_SRC", "") == "pipewiresrc":'
ASM_LINE = '            pipeline_elements += [cudaupload, cudaconvert, cudaconvert_capsfilter, nvh264enc, h264enc_capsfilter, rtph264pay, rtph264pay_capsfilter]'

s = open(path, encoding="utf-8").read()

# --- patch 1: source branch — prepend `if waylanddisplaysrc:` before the pipewire if -
if WAYLAND_MARK in s:
    print("patch_selkies_waylanddisplay: source branch already present, skipping")
elif PIPEWIRE_IF not in s:
    print("patch_selkies_waylanddisplay: ERROR — pipewire `if pipewiresrc:` line not found")
    print("  (this patch must run AFTER patch_selkies_pipewire.py)")
    sys.exit(1)
else:
    wayland_branch = (
        '        if ' + WAYLAND_MARK + ':\n'
        '            # --- DPAD wayland-display compositor source (gst-wayland-display) ---\n'
        '            # DPAD_COMPOSITOR=wayland-display: a Smithay micro-compositor runs as\n'
        '            # the GStreamer source (waylanddisplaysrc) — it initialises EGL off\n'
        '            # the DRM render node (no DRM master -> N-on-N) + emits CUDAMemory\n'
        '            # buffers directly (no cudaupload/cudaconvert/NVRTC; live-proven on\n'
        '            # an OVH L4 that NVRTC-error=0 on this path, §13.14). gamescope runs\n'
        '            # as a Wayland CLIENT of this compositor (--backend wayland) +\n'
        '            # provides XWayland :0 to Steam/Wine. The compositor creates\n'
        '            # wayland-N in $XDG_RUNTIME_DIR on start; the entrypoint polls for\n'
        '            # it + launches gamescope with WAYLAND_DISPLAY=wayland-N.\n'
        '            self.ximagesrc = Gst.ElementFactory.make("waylanddisplaysrc", "x11")\n'
        '            if self.gpu_id >= 0:\n'
        '                self.ximagesrc.set_property("cuda-device-id", self.gpu_id)\n'
        '            # CUDAMemory BGRA caps — also the compositor output size + framerate\n'
        '            # (the compositor queries these to set its output mode). nvh264enc\n'
        '            # accepts CUDAMemory BGRA directly (live-proven) -> no cudaconvert.\n'
        '            self.ximagesrc_caps = Gst.caps_from_string("video/x-raw(memory:CUDAMemory),format=BGRA")\n'
        '            self.ximagesrc_caps.set_value("width", int(os.environ.get("DPAD_STREAM_WIDTH", "1920")))\n'
        '            self.ximagesrc_caps.set_value("height", int(os.environ.get("DPAD_STREAM_HEIGHT", "1080")))\n'
        '            self.ximagesrc_caps.set_value("framerate", Gst.Fraction(self.framerate, 1))\n'
        '            self.ximagesrc_capsfilter = Gst.ElementFactory.make("capsfilter")\n'
        '            self.ximagesrc_capsfilter.set_property("caps", self.ximagesrc_caps)\n'
        '            # No videorate: the compositor renders at the negotiated framerate.\n'
        '        elif ' + 'os.environ.get("DPAD_VIDEO_SRC", "") == "pipewiresrc":'
    )
    s = s.replace(PIPEWIRE_IF, wayland_branch, 1)
    try:
        ast.parse(s)
    except SyntaxError as e:
        print("patch_selkies_waylanddisplay: ERROR — source-branch patch does not parse: %r" % e)
        sys.exit(1)
    print("patch_selkies_waylanddisplay: source branch added (if waylanddisplaysrc / elif pipewiresrc / else ximagesrc)")

# --- patch 2: assembly — skip cudaupload/cudaconvert for the waylanddisplaysrc path -
ASM_MARK = 'if os.environ.get("DPAD_VIDEO_SRC", "") == "waylanddisplaysrc":\n                pipeline_elements += [nvh264enc, h264enc_capsfilter, rtph264pay, rtph264pay_capsfilter]'
if ASM_MARK in s:
    print("patch_selkies_waylanddisplay: assembly already wayland-aware, skipping")
elif ASM_LINE not in s:
    print("patch_selkies_waylanddisplay: WARNING — nvh264enc assembly line not found; skipping")
else:
    repl = (
        '            # DPAD: waylanddisplaysrc emits CUDAMemory directly -> skip\n'
        '            # cudaupload/cudaconvert (and their NVRTC JIT, §13.14).\n'
        '            if os.environ.get("DPAD_VIDEO_SRC", "") == "waylanddisplaysrc":\n'
        '                pipeline_elements += [nvh264enc, h264enc_capsfilter, rtph264pay, rtph264pay_capsfilter]\n'
        '            else:\n'
        '                pipeline_elements += [cudaupload, cudaconvert, cudaconvert_capsfilter, nvh264enc, h264enc_capsfilter, rtph264pay, rtph264pay_capsfilter]'
    )
    s = s.replace(ASM_LINE, repl, 1)
    try:
        ast.parse(s)
    except SyntaxError as e:
        print("patch_selkies_waylanddisplay: ERROR — assembly patch does not parse: %r" % e)
        sys.exit(1)
    print("patch_selkies_waylanddisplay: assembly wayland-aware (skip cudaupload/cudaconvert for waylanddisplaysrc)")

# final parse + write
try:
    ast.parse(s)
except SyntaxError as e:
    print("patch_selkies_waylanddisplay: ERROR — final file does not parse: %r" % e)
    sys.exit(1)
open(path, "w", encoding="utf-8").write(s)
print("patch_selkies_waylanddisplay: wrote %s" % path)