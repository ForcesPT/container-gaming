#!/usr/bin/env python3
# patch_selkies_pipewire.py — make Selkies capture gamescope's PipeWire node
# directly (pipewiresrc, no Xvfb :2 / ximagesrc bridge) AND make the Selkies
# FPS slider work on the live source via a `videorate` throttle.
#
# Selkies 1.6.x hardcodes `ximagesrc`. With DPAD_VIDEO_SRC=pipewiresrc we switch
# the source to pipewiresrc(target-object=gamescope, always-copy=True). gamescope
# is a LIVE push source (framerate 0/1), so the FPS slider can't throttle the
# source caps (forcing N/1 made negotiation fail + crashed gamescope). So we
# insert `videorate` + a framerate capsfilter after the source: videorate
# drops/duplicates to match the requested rate, so the FPS slider takes effect
# (15fps = lower bandwidth) without touching the live source's caps.
#
# Pipeline (nvh264enc):
#   pipewiresrc(BGRx, always-copy) -> capsfilter(BGRx) -> videorate ->
#   capsfilter(BGRx, framerate=N/1) -> cudaupload -> cudaconvert(GPU BGRx->NV12) ->
#   nvcudah264enc -> rtph264pay -> webrtcbin
#
# Patches (all idempotent on the patched result):
#   1. build_video_pipeline: pipewiresrc source branch + videorate + framerate
#      capsfilter (gated on DPAD_VIDEO_SRC=pipewiresrc; else original ximagesrc).
#   2. assembly: prepend videorate + framerate_capsfilter for the pipewiresrc path.
#   3. set_framerate: update the framerate capsfilter (videorate) for pipewiresrc
#      instead of forcing framerate on the source caps (which crashed gamescope).
#   4. guard set_pointer_visible (show-pointer is ximagesrc-only).
#   5. guard start_ximagesrc (endx/endy are ximagesrc-only; resize is disabled
#      with --enable_resize=false but guard for safety).
#
# Usage: python3 patch_selkies_pipewire.py [path/to/gstwebrtc_app.py]
import sys, textwrap, ast

path = sys.argv[1] if len(sys.argv) > 1 else "/usr/local/lib/python3.12/dist-packages/selkies_gstreamer/gstwebrtc_app.py"
MARKER = 'os.environ.get("DPAD_VIDEO_SRC", "") == "pipewiresrc"'
START = '        self.ximagesrc = Gst.ElementFactory.make("ximagesrc", "x11")'
END = '        self.ximagesrc_capsfilter.set_property("caps", self.ximagesrc_caps)'
VIDEORATE_MARK = 'self.videorate = Gst.ElementFactory.make("videorate")'

s = open(path, encoding="utf-8").read()

# --- patch 1: pipewiresrc source branch + videorate + framerate capsfilter ----
if VIDEORATE_MARK in s:
    print("patch_selkies_pipewire: source branch + videorate already present, skipping")
else:
    if MARKER not in s:
        if START not in s or END not in s:
            print("patch_selkies_pipewire: ERROR — ximagesrc source block not found; Selkies version mismatch?")
            sys.exit(1)
        i0 = s.index(START); i1 = s.index(END, i0) + len(END)
        if s[i1] == "\n": i1 += 1
        original_block = s[i0:i1]
        pipewire_block = (
            '        # --- DPAD zero-copy video source (Stage 2-zero-copy) ---------------\n'
            '        # DPAD_VIDEO_SRC=pipewiresrc: capture gamescope\'s PipeWire node directly\n'
            '        # instead of ximagesrc on Xvfb :2 — removes the PipeWire->X11 bridge\n'
            '        # (ximagesink :2 + ximagesrc) + the CPU videoconvert passes. gamescope\n'
            '        # advertises no dmabuf modifier (modifier 0) so pipewiresrc negotiates\n'
            '        # system-memory BGRx (not true dmabuf zero-copy), but the :2 round-trip\n'
            '        # + CPU colorspace converts are gone. always-copy=True returns gamescope\'s\n'
            '        # buffer immediately (False -> gamescope "Already had a buffer" crash).\n'
            '        # videorate + the framerate capsfilter throttle to the FPS slider (gamescope\n'
            '        # is a live 0/1 source, so the rate is enforced here, not on the source).\n'
            '        # Reuses self.ximagesrc / self.ximagesrc_capsfilter for the encoder branch\n'
            '        # + assembly; videorate/framerate_capsfilter are added to the assembly.\n'
            '        if ' + MARKER + ':\n'
            '            self.ximagesrc = Gst.ElementFactory.make("pipewiresrc", "x11")\n'
            '            self.ximagesrc.set_property("target-object", os.environ.get("DPAD_PIPEWIRE_TARGET", "gamescope"))\n'
            '            self.ximagesrc.set_property("always-copy", True)\n'
            '            self.ximagesrc_caps = Gst.caps_from_string("video/x-raw,format=BGRx")\n'
            '            self.ximagesrc_capsfilter = Gst.ElementFactory.make("capsfilter")\n'
            '            self.ximagesrc_capsfilter.set_property("caps", self.ximagesrc_caps)\n'
            '            # FPS throttle: videorate drops/duplicates to match the requested\n'
            '            # framerate; self.framerate_capsfilter holds it (set_framerate updates it).\n'
            '            self.videorate = Gst.ElementFactory.make("videorate")\n'
            '            self.framerate_caps = Gst.caps_from_string("video/x-raw,format=BGRx")\n'
            '            self.framerate_caps.set_value("framerate", Gst.Fraction(self.framerate, 1))\n'
            '            self.framerate_capsfilter = Gst.ElementFactory.make("capsfilter")\n'
            '            self.framerate_capsfilter.set_property("caps", self.framerate_caps)\n'
            '        else:\n'
            + textwrap.indent(original_block, "            ")
        )
        s = s[:i0] + pipewire_block + s[i1:]
    else:
        # source branch already present (older patch without videorate): insert videorate
        anchor = (
            '            self.ximagesrc_capsfilter.set_property("caps", self.ximagesrc_caps)\n'
            '        else:\n'
        )
        repl = (
            '            self.ximagesrc_capsfilter.set_property("caps", self.ximagesrc_caps)\n'
            '            # FPS throttle: videorate drops/duplicates to match the requested\n'
            '            # framerate; self.framerate_capsfilter holds it (set_framerate updates it).\n'
            '            self.videorate = Gst.ElementFactory.make("videorate")\n'
            '            self.framerate_caps = Gst.caps_from_string("video/x-raw,format=BGRx")\n'
            '            self.framerate_caps.set_value("framerate", Gst.Fraction(self.framerate, 1))\n'
            '            self.framerate_capsfilter = Gst.ElementFactory.make("capsfilter")\n'
            '            self.framerate_capsfilter.set_property("caps", self.framerate_caps)\n'
            '        else:\n'
        )
        if anchor not in s:
            print("patch_selkies_pipewire: ERROR — could not place videorate (anchor not found)")
            sys.exit(1)
        s = s.replace(anchor, repl, 1)
    try:
        ast.parse(s)
    except SyntaxError as e:
        print("patch_selkies_pipewire: ERROR — source-branch patch does not parse: %r" % e)
        sys.exit(1)
    print("patch_selkies_pipewire: source branch + videorate added")

# --- patch 2: assembly — add videorate + framerate_capsfilter for pipewiresrc -
ASM_MARK = 'pipeline_elements += [self.videorate, self.framerate_capsfilter]'
ASM_ANCHOR = '        pipeline_elements = [self.ximagesrc, self.ximagesrc_capsfilter]\n'
if ASM_MARK in s:
    print("patch_selkies_pipewire: assembly already wired, skipping")
elif ASM_ANCHOR in s:
    s = s.replace(ASM_ANCHOR, ASM_ANCHOR +
        '        # DPAD: for the pipewiresrc path, insert videorate + the framerate\n'
        '        # capsfilter (the FPS throttle) between the source capsfilter and the encoder.\n'
        '        if ' + MARKER + ':\n'
        '            pipeline_elements += [self.videorate, self.framerate_capsfilter]\n', 1)
    try:
        ast.parse(s)
    except SyntaxError as e:
        print("patch_selkies_pipewire: ERROR — assembly patch does not parse: %r" % e)
        sys.exit(1)
    print("patch_selkies_pipewire: assembly wired (videorate inserted for pipewiresrc)")
else:
    print("patch_selkies_pipewire: WARNING — assembly anchor not found; skipping")

# --- patch 3: set_framerate — update the videorate framerate capsfilter -------
# Replace the original 3-line caps rebuild (or the older BGRx-no-framerate guard)
# with: pipewiresrc -> update framerate_capsfilter; ximagesrc -> original behavior.
FPS_NEW_MARK = 'self.framerate_capsfilter.set_property("caps", self.framerate_caps)'
FPS_ORIG = (
    '            self.ximagesrc_caps = Gst.caps_from_string("video/x-raw")\n'
    '            self.ximagesrc_caps.set_value("framerate", Gst.Fraction(self.framerate, 1))\n'
    '            self.ximagesrc_capsfilter.set_property("caps", self.ximagesrc_caps)\n'
)
# older guard (pre-videorate) to replace too:
FPS_OLD = (
    '            if os.environ.get("DPAD_VIDEO_SRC", "") == "pipewiresrc":\n'
    '                self.ximagesrc_caps = Gst.caps_from_string("video/x-raw,format=BGRx")\n'
    '            else:\n'
    '                self.ximagesrc_caps = Gst.caps_from_string("video/x-raw")\n'
    '                self.ximagesrc_caps.set_value("framerate", Gst.Fraction(self.framerate, 1))\n'
    '            self.ximagesrc_capsfilter.set_property("caps", self.ximagesrc_caps)\n'
)
FPS_NEW = (
    '            # DPAD: pipewiresrc is a live source - update the videorate framerate\n'
    '            # capsfilter (the FPS throttle), NOT the source caps (forcing N/1 on the\n'
    '            # source made negotiation fail + crashed gamescope). ximagesrc keeps the\n'
    '            # original behavior (force framerate on the pull source).\n'
    '            if os.environ.get("DPAD_VIDEO_SRC", "") == "pipewiresrc":\n'
    '                self.framerate_caps = Gst.caps_from_string("video/x-raw,format=BGRx")\n'
    '                self.framerate_caps.set_value("framerate", Gst.Fraction(self.framerate, 1))\n'
    '                self.framerate_capsfilter.set_property("caps", self.framerate_caps)\n'
    '            else:\n'
    '                self.ximagesrc_caps = Gst.caps_from_string("video/x-raw")\n'
    '                self.ximagesrc_caps.set_value("framerate", Gst.Fraction(self.framerate, 1))\n'
    '                self.ximagesrc_capsfilter.set_property("caps", self.ximagesrc_caps)\n'
)
if FPS_NEW_MARK in s and FPS_NEW in s:
    print("patch_selkies_pipewire: set_framerate already videorate-aware, skipping")
elif FPS_OLD in s:
    s = s.replace(FPS_OLD, FPS_NEW, 1)
    try: ast.parse(s)
    except SyntaxError as e: print("patch_selkies_pipewire: ERROR — set_framerate(OLD) parse: %r" % e); sys.exit(1)
    print("patch_selkies_pipewire: set_framerate upgraded to videorate-aware (replaced old guard)")
elif FPS_ORIG in s:
    s = s.replace(FPS_ORIG, FPS_NEW, 1)
    try: ast.parse(s)
    except SyntaxError as e: print("patch_selkies_pipewire: ERROR — set_framerate(ORIG) parse: %r" % e); sys.exit(1)
    print("patch_selkies_pipewire: set_framerate made videorate-aware")
else:
    print("patch_selkies_pipewire: WARNING — set_framerate anchor not found; skipping")

# --- patch 4: guard set_pointer_visible (show-pointer is ximagesrc-only) -------
SPV_ANCHOR = (
    '        element = Gst.Bin.get_by_name(self.pipeline, "x11")\n'
    '        element.set_property("show-pointer", visible)\n'
)
SPV_REPLACE = (
    '        element = Gst.Bin.get_by_name(self.pipeline, "x11")\n'
    '        # "show-pointer" is ximagesrc-only; the pipewiresrc "x11" element lacks it\n'
    '        # -> set_property raises TypeError. Skip it then (gamescope\'s cursor is\n'
    '        # already in the captured frame).\n'
    '        if any(p.name == "show-pointer" for p in element.list_properties()):\n'
    '            element.set_property("show-pointer", visible)\n'
)
if SPV_REPLACE in s:
    print("patch_selkies_pipewire: set_pointer_visible already guarded")
elif SPV_ANCHOR in s:
    s = s.replace(SPV_ANCHOR, SPV_REPLACE, 1)
    print("patch_selkies_pipewire: guarded set_pointer_visible")
else:
    print("patch_selkies_pipewire: WARNING — set_pointer_visible anchor not found; skipping")

# --- patch 5: guard start_ximagesrc (endx/endy are ximagesrc-only) ------------
START_ANCHOR = (
    '        if self.ximagesrc:\n'
    '            self.ximagesrc.set_property("endx", 0)\n'
    '            self.ximagesrc.set_property("endy", 0)\n'
    '            self.ximagesrc.set_state(Gst.State.PLAYING)\n'
)
START_REPLACE = (
    '        if self.ximagesrc:\n'
    '            # endx/endy are ximagesrc-only; skip for pipewiresrc (resize is disabled\n'
    '            # with --enable_resize=false; guard so a future resize path can\'t crash).\n'
    '            if any(p.name == "endx" for p in self.ximagesrc.list_properties()):\n'
    '                self.ximagesrc.set_property("endx", 0)\n'
    '                self.ximagesrc.set_property("endy", 0)\n'
    '            self.ximagesrc.set_state(Gst.State.PLAYING)\n'
)
if START_REPLACE in s:
    print("patch_selkies_pipewire: start_ximagesrc already guarded")
elif START_ANCHOR in s:
    s = s.replace(START_ANCHOR, START_REPLACE, 1)
    print("patch_selkies_pipewire: guarded start_ximagesrc")
else:
    print("patch_selkies_pipewire: WARNING — start_ximagesrc anchor not found; skipping")

# final parse + write
try:
    ast.parse(s)
except SyntaxError as e:
    print("patch_selkies_pipewire: ERROR — final file does not parse: %r" % e)
    sys.exit(1)
open(path, "w", encoding="utf-8").write(s)
print("patch_selkies_pipewire: wrote %s" % path)