#!/usr/bin/env python3
# patch_selkies_waylanddisplay.py — make Selkies capture the gst-wayland-display
# compositor (waylanddisplaysrc) instead of gamescope's PipeWire node
# (pipewiresrc) or the Xvfb :2 bridge (ximagesrc).
#
# DPAD_COMPOSITOR=wayland-display path (WAYLAND-ARCHITECTURE.md §14). A Smithay
# micro-compositor (games-on-whales/gst-wayland-display) runs AS the GStreamer
# source element: it initialises EGL off the DRM render node (NO DRM master →
# N-on-N). gamescope runs as a Wayland CLIENT of this compositor (--backend
# wayland) + provides XWayland :0 to Steam/Wine. The compositor creates
# wayland-N in $XDG_RUNTIME_DIR on start; the entrypoint polls for it + launches
# gamescope with WAYLAND_DISPLAY=wayland-N.
#
# Gated on DPAD_VIDEO_SRC=waylanddisplaysrc (set by the entrypoint gate when
# DPAD_COMPOSITOR=wayland-display). Default DPAD_VIDEO_SRC=pipewiresrc → the
# gamescope-headless path is unchanged (no regression).
#
# CAPTURE FORMAT NOTE (the §2.2/§13.3 CUDAMemory-zero-copy assumption was WRONG
# for selkies' static linking): waylanddisplaysrc's src pad supports BOTH
# CUDAMemory {BGRA,RGBA} AND system-memory RGBx. The CUDAMemory path would be
# true zero-copy, BUT nvh264enc's STATIC query_caps (at Gst.Element.link time,
# before PLAYING) restricts CUDAMemory to {NV12,Y444} (not BGRA) once the
# encoder is configured → no common format → "Failed to link capsfilter0 ->
# nvenc". The §13.14 gst-launch probe worked via DYNAMIC negotiation (at
# PLAYING); selkies uses static Gst.Element.link. So the spike uses
# SYSTEM-MEMORY RGBx + the original cudaupload→cudaconvert(BGRx→NV12)→nvh264enc
# path (the validated encode pipeline; NVRTC JIT runs, extract-nvrtc.sh covers
# it). CUDAMemory zero-copy is a §13.3 follow-up (link_pads_full w/ no caps
# check, OR PR #35's NV12 DMABuf→CUDAMemory path).
#
# Pipeline (nvh264enc) — same encode tail as ximagesrc/pipewiresrc:
#   waylanddisplaysrc -> capsfilter(RGBx,WxH@N/1) -> cudaupload -> cudaconvert(->NV12)
#   -> cudaconvert_capsfilter(CUDAMemory,NV12) -> nvh264enc -> h264enc_capsfilter
#   -> rtph264pay -> webrtcbin
#
# Patches (idempotent on the patched result; runs AFTER patch_selkies_pipewire.py):
#   1. build_video_pipeline source branch: prepend `if waylanddisplaysrc:` before
#      the pipewire `if pipewiresrc:` (turning it into if/elif/else). The wayland
#      branch makes self.ximagesrc=waylanddisplaysrc + RGBx caps (WxH@N). No
#      videorate (the compositor renders at the negotiated framerate).
#   2. assembly: NO special-case (waylanddisplaysrc uses the SAME cudaupload->
#      cudaconvert->nvh264enc path as the else branch). Kept as an explicit branch
#      for clarity + so a future zero-copy path can swap it.
#   3. set_framerate (in patch_selkies_pipewire.py): the `elif waylanddisplaysrc:
#      pass` guard there prevents set_framerate's else branch from clobbering the
#      RGBx caps with video/x-raw (which would break the link).
#
# Idempotency: SOURCE_MARK is the waylanddisplaysrc element-creation line
# (specific — the assembly branch + set_framerate guard also contain
# "waylanddisplaysrc", so a loose check would skip the source-branch insertion
# → waylanddisplaysrc never created → falls through to ximagesrc → link fails).
#
# Usage: python3 patch_selkies_waylanddisplay.py [path/to/gstwebrtc_app.py]
# (Run AFTER patch_selkies_pipewire.py — anchors on the pipewire-patched
# `if pipewiresrc:` line + the nvh264enc assembly line.)
import sys, ast

path = sys.argv[1] if len(sys.argv) > 1 else "/usr/local/lib/python3.12/dist-packages/selkies_gstreamer/gstwebrtc_app.py"
WAYLAND_MARK = 'os.environ.get("DPAD_VIDEO_SRC", "") == "waylanddisplaysrc"'  # the if condition (reused below)
SOURCE_MARK = 'Gst.ElementFactory.make("waylanddisplaysrc", "x11")'           # idempotency: the source-branch creation line
PIPEWIRE_IF = '        if os.environ.get("DPAD_VIDEO_SRC", "") == "pipewiresrc":'
ASM_LINE = '            pipeline_elements += [cudaupload, cudaconvert, cudaconvert_capsfilter, nvh264enc, h264enc_capsfilter, rtph264pay, rtph264pay_capsfilter]'

s = open(path, encoding="utf-8").read()

# --- patch 1: source branch — prepend `if waylanddisplaysrc:` before the pipewire if -
if SOURCE_MARK in s:
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
        '            # the GStreamer source (waylanddisplaysrc). It initialises EGL off the\n'
        '            # DRM render node (no DRM master -> N-on-N) + supports system-memory\n'
        '            # RGBx AND CUDAMemory {BGRA,RGBA}. We use RGBx here (see the capture-\n'
        '            # format note in the patch header): nvh264enc static query_caps rejects\n'
        '            # CUDAMemory BGRA (only NV12/Y444) before PLAYING, so the zero-copy\n'
        '            # CUDAMemory path fails the static Gst.Element.link. RGBx feeds the\n'
        '            # original cudaupload->cudaconvert->nvh264enc path. gamescope runs as a\n'
        '            # Wayland CLIENT (--backend wayland); the compositor creates wayland-N\n'
        '            # in $XDG_RUNTIME_DIR on start; the entrypoint polls + launches it.\n'
        '            self.ximagesrc = Gst.ElementFactory.make("waylanddisplaysrc", "x11")\n'
        '            if self.gpu_id >= 0:\n'
        '                self.ximagesrc.set_property("cuda-device-id", self.gpu_id)\n'
        '            # System-memory RGBx caps + the compositor output size + framerate.\n'
        '            self.ximagesrc_caps = Gst.caps_from_string("video/x-raw,format=RGBx")\n'
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

# --- patch 2: assembly — waylanddisplaysrc uses the SAME cudaupload/cudaconvert path -
# (No change needed — the waylanddisplaysrc path falls into the default nvh264enc
# assembly branch, which already has [cudaupload, cudaconvert, cudaconvert_capsfilter,
# nvh264enc, ...]. Keep this section as a no-op marker; a future zero-copy path can
# add a waylanddisplaysrc-specific branch here that links waylanddisplaysrc -> nvh264enc
# directly via link_pads_full(no caps check).)
ASM_MARK = 'if os.environ.get("DPAD_VIDEO_SRC", "") == "waylanddisplaysrc":\n                pipeline_elements += [nvh264enc, h264enc_capsfilter, rtph264pay, rtph264pay_capsfilter]'
if ASM_MARK in s:
    # An older zero-copy patch left a direct-link branch; revert it to the standard
    # cudaupload/cudaconvert path so the link succeeds with system-memory RGBx.
    s = s.replace(
        '            # DPAD: waylanddisplaysrc emits CUDAMemory directly -> skip\n'
        '            # cudaupload/cudaconvert (and their NVRTC JIT, §13.14).\n'
        '            if os.environ.get("DPAD_VIDEO_SRC", "") == "waylanddisplaysrc":\n'
        '                pipeline_elements += [nvh264enc, h264enc_capsfilter, rtph264pay, rtph264pay_capsfilter]\n'
        '            else:\n'
        '                pipeline_elements += [cudaupload, cudaconvert, cudaconvert_capsfilter, nvh264enc, h264enc_capsfilter, rtph264pay, rtph264pay_capsfilter]',
        '            pipeline_elements += [cudaupload, cudaconvert, cudaconvert_capsfilter, nvh264enc, h264enc_capsfilter, rtph264pay, rtph264pay_capsfilter]',
        1)
    try:
        ast.parse(s)
    except SyntaxError as e:
        print("patch_selkies_waylanddisplay: ERROR — assembly revert does not parse: %r" % e)
        sys.exit(1)
    print("patch_selkies_waylanddisplay: reverted the direct-link assembly branch -> standard cudaupload/cudaconvert path")
elif ASM_LINE in s:
    print("patch_selkies_waylanddisplay: assembly already standard (cudaupload/cudaconvert) — no change needed")
else:
    print("patch_selkies_waylanddisplay: WARNING — nvh264enc assembly line not found; skipping")

# final parse + write
try:
    ast.parse(s)
except SyntaxError as e:
    print("patch_selkies_waylanddisplay: ERROR — final file does not parse: %r" % e)
    sys.exit(1)
open(path, "w", encoding="utf-8").write(s)
print("patch_selkies_waylanddisplay: wrote %s" % path)
