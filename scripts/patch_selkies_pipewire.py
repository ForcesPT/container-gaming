#!/usr/bin/env python3
# patch_selkies_pipewire.py — add a pipewiresrc source branch to Selkies'
# build_video_pipeline (zero-copy-ish capture of gamescope's PipeWire node,
# no Xvfb :2 / ximagesrc bridge) + guard set_pointer_visible for pipewiresrc.
#
# Selkies 1.6.x hardcodes `ximagesrc` as the video source. This patch:
#   1. wraps the source-creation block in build_video_pipeline in
#      `if DPAD_VIDEO_SRC == "pipewiresrc": <pipewiresrc> else: <ximagesrc>`.
#      The encoder branch + the assembly (`pipeline_elements = [self.ximagesrc,
#      self.ximagesrc_capsfilter] + [...]`) reuse self.ximagesrc unchanged, so
#      only the source element changes. The proven pipeline becomes:
#        pipewiresrc(target-object=gamescope, BGRx) -> cudaupload ->
#        cudaconvert(GPU BGRx->NV12) -> nvcudah264enc -> rtph264pay -> webrtcbin
#   2. guards set_pointer_visible: "show-pointer" is an ximagesrc property; the
#      pipewiresrc "x11" element lacks it -> set_property raises TypeError.
#      Skip it when the element has no such property (gamescope's cursor is
#      already in the captured frame).
#
# Both patches are idempotent. Usage: python3 patch_selkies_pipewire.py [path]
import sys, textwrap, ast

path = sys.argv[1] if len(sys.argv) > 1 else "/usr/local/lib/python3.12/dist-packages/selkies_gstreamer/gstwebrtc_app.py"
MARKER = 'os.environ.get("DPAD_VIDEO_SRC", "") == "pipewiresrc"'
START = '        self.ximagesrc = Gst.ElementFactory.make("ximagesrc", "x11")'
END = '        self.ximagesrc_capsfilter.set_property("caps", self.ximagesrc_caps)'

s = open(path, encoding="utf-8").read()

# --- patch 1: the pipewiresrc source branch ---------------------------------
if MARKER in s:
    print("patch_selkies_pipewire: source branch already present, skipping")
else:
    if START not in s or END not in s:
        print("patch_selkies_pipewire: ERROR — ximagesrc source block not found; Selkies version mismatch?")
        sys.exit(1)
    i0 = s.index(START)
    i1 = s.index(END, i0) + len(END)
    if s[i1] == "\n":
        i1 += 1
    original_block = s[i0:i1]
    pipewire_block = (
        '        # --- DPAD zero-copy video source (Stage 2-zero-copy) ---------------\n'
        '        # When DPAD_VIDEO_SRC=pipewiresrc, capture gamescope\'s PipeWire node\n'
        '        # directly instead of ximagesrc on Xvfb :2. Eliminates the PipeWire->X11\n'
        '        # bridge (ximagesink :2 + ximagesrc) + the CPU videoconvert passes:\n'
        '        #   pipewiresrc(BGRx) -> cudaupload -> cudaconvert(GPU BGRx->NV12) -> nvh264enc.\n'
        '        # gamescope advertises no dmabuf modifier (modifier 0) so pipewiresrc\n'
        '        # negotiates system-memory BGRx (not true dmabuf zero-copy), but this\n'
        '        # still removes the :2 round-trip + the CPU colorspace converts. Reuses\n'
        '        # self.ximagesrc / self.ximagesrc_capsfilter so the encoder branch +\n'
        '        # assembly (pipeline_elements) work unchanged.\n'
        '        if ' + MARKER + ':\n'
        '            self.ximagesrc = Gst.ElementFactory.make("pipewiresrc", "x11")\n'
        '            self.ximagesrc.set_property("target-object", os.environ.get("DPAD_PIPEWIRE_TARGET", "gamescope"))\n'
        '            self.ximagesrc.set_property("always-copy", False)\n'
        '            self.ximagesrc_caps = Gst.caps_from_string("video/x-raw,format=BGRx")\n'
        '            self.ximagesrc_capsfilter = Gst.ElementFactory.make("capsfilter")\n'
        '            self.ximagesrc_capsfilter.set_property("caps", self.ximagesrc_caps)\n'
        '        else:\n'
        + textwrap.indent(original_block, "            ")
    )
    s = s[:i0] + pipewire_block + s[i1:]
    try:
        ast.parse(s)
    except SyntaxError as e:
        print("patch_selkies_pipewire: ERROR — source-branch patch does not parse: %r" % e)
        sys.exit(1)
    print("patch_selkies_pipewire: source branch added (DPAD_VIDEO_SRC=pipewiresrc)")

# --- patch 2: guard set_pointer_visible -----------------------------------
SPV_ANCHOR = (
    '        element = Gst.Bin.get_by_name(self.pipeline, "x11")\n'
    '        element.set_property("show-pointer", visible)\n'
)
SPV_REPLACE = (
    '        element = Gst.Bin.get_by_name(self.pipeline, "x11")\n'
    '        # "show-pointer" is an ximagesrc property; with the pipewiresrc source\n'
    '        # (DPAD_VIDEO_SRC=pipewiresrc) the "x11" element is a GstPipeWireSrc with\n'
    '        # no such property -> set_property raises TypeError. Skip it then\n'
    '        # (gamescope\'s cursor is already in the captured frame).\n'
    '        if any(p.name == "show-pointer" for p in element.list_properties()):\n'
    '            element.set_property("show-pointer", visible)\n'
)
if SPV_REPLACE in s:
    print("patch_selkies_pipewire: set_pointer_visible already guarded")
elif SPV_ANCHOR in s:
    s = s.replace(SPV_ANCHOR, SPV_REPLACE)
    try:
        ast.parse(s)
    except SyntaxError as e:
        print("patch_selkies_pipewire: ERROR — SPV guard does not parse: %r" % e)
        sys.exit(1)
    print("patch_selkies_pipewire: guarded set_pointer_visible")
else:
    print("patch_selkies_pipewire: WARNING — set_pointer_visible anchor not found; skipping")

open(path, "w", encoding="utf-8").write(s)
print("patch_selkies_pipewire: wrote %s" % path)