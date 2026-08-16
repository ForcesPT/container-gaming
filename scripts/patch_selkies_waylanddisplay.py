#!/usr/bin/env python3
"""Patch pristine Selkies 1.6.2 for the launcher-only Wayland source.

The image has one capture architecture, so this patch applies directly to the
stock ximagesrc implementation. It must not depend on the retired pipewiresrc
patch or retain runtime source-selection branches.
"""
import ast
import sys

path = sys.argv[1] if len(sys.argv) > 1 else "/usr/local/lib/python3.12/dist-packages/selkies_gstreamer/gstwebrtc_app.py"
source = open(path, encoding="utf-8").read()

PERSIST_MARK = 'Reusing persistent waylanddisplaysrc compositor'
PRISTINE_START = '        self.ximagesrc = Gst.ElementFactory.make("ximagesrc", "x11")'
WAYLAND_START = '        self.ximagesrc = Gst.ElementFactory.make("waylanddisplaysrc", "x11")'
END = '        self.ximagesrc_capsfilter.set_property("caps", self.ximagesrc_caps)'

if PERSIST_MARK not in source:
    if PRISTINE_START in source:
        start = source.index(PRISTINE_START)
    elif WAYLAND_START in source:
        start = source.index(WAYLAND_START)
    else:
        print("patch_selkies_waylanddisplay: ERROR — supported source block not found")
        sys.exit(1)
    if END not in source[start:]:
        print("patch_selkies_waylanddisplay: ERROR — source block end not found")
        sys.exit(1)
    end = source.index(END, start) + len(END)
    if end < len(source) and source[end] == "\n":
        end += 1
    replacement = (
        '        # DpadPlay launcher-only compositor/capture source. The Rust element\'s\n'
        '        # stop() preserves its display, so reuse this object across peer pipelines.\n'
        '        if self.ximagesrc is None:\n'
        '            self.ximagesrc = Gst.ElementFactory.make("waylanddisplaysrc", "x11")\n'
        '            if self.gpu_id >= 0:\n'
        '                self.ximagesrc.set_property("cuda-device-id", self.gpu_id)\n'
        '        else:\n'
        '            logger.info("Reusing persistent waylanddisplaysrc compositor")\n'
        '        self.ximagesrc_caps = Gst.caps_from_string("video/x-raw,format=RGBx")\n'
        '        self.ximagesrc_caps.set_value("width", int(os.environ.get("DPAD_STREAM_WIDTH", "1920")))\n'
        '        self.ximagesrc_caps.set_value("height", int(os.environ.get("DPAD_STREAM_HEIGHT", "1080")))\n'
        '        self.ximagesrc_caps.set_value("framerate", Gst.Fraction(self.framerate, 1))\n'
        '        self.ximagesrc_capsfilter = Gst.ElementFactory.make("capsfilter")\n'
        '        self.ximagesrc_capsfilter.set_property("caps", self.ximagesrc_caps)\n'
    )
    source = source[:start] + replacement + source[end:]
    print("patch_selkies_waylanddisplay: installed persistent Wayland source")
else:
    print("patch_selkies_waylanddisplay: persistent Wayland source already present")

# Resize/restart is source-agnostic. endx/endy are ximagesrc-only properties.
START_X11 = (
    '        if self.ximagesrc:\n'
    '            self.ximagesrc.set_property("endx", 0)\n'
    '            self.ximagesrc.set_property("endy", 0)\n'
    '            self.ximagesrc.set_state(Gst.State.PLAYING)\n'
)
START_WAYLAND = (
    '        if self.ximagesrc:\n'
    '            self.ximagesrc.set_state(Gst.State.PLAYING)\n'
)
if START_X11 in source:
    source = source.replace(START_X11, START_WAYLAND, 1)
    print("patch_selkies_waylanddisplay: removed ximagesrc-only restart properties")

# Preserve RGBx, size, and framerate when Selkies changes FPS at runtime.
FPS_X11 = (
    '            self.ximagesrc_caps = Gst.caps_from_string("video/x-raw")\n'
    '            self.ximagesrc_caps.set_value("framerate", Gst.Fraction(self.framerate, 1))\n'
    '            self.ximagesrc_capsfilter.set_property("caps", self.ximagesrc_caps)\n'
)
FPS_WAYLAND = (
    '            self.ximagesrc_caps = Gst.caps_from_string("video/x-raw,format=RGBx")\n'
    '            self.ximagesrc_caps.set_value("width", int(os.environ.get("DPAD_STREAM_WIDTH", "1920")))\n'
    '            self.ximagesrc_caps.set_value("height", int(os.environ.get("DPAD_STREAM_HEIGHT", "1080")))\n'
    '            self.ximagesrc_caps.set_value("framerate", Gst.Fraction(self.framerate, 1))\n'
    '            self.ximagesrc_capsfilter.set_property("caps", self.ximagesrc_caps)\n'
)
if FPS_X11 in source:
    source = source.replace(FPS_X11, FPS_WAYLAND, 1)
    print("patch_selkies_waylanddisplay: made set_framerate Wayland-aware")

# The compositor does not expose ximagesrc's show-pointer property. Cursor
# visibility is handled by the Selkies XFIXES overlay and DpadPlay web controls.
POINTER_X11 = (
    '        element = Gst.Bin.get_by_name(self.pipeline, "x11")\n'
    '        element.set_property("show-pointer", visible)\n'
)
POINTER_WAYLAND = (
    '        element = Gst.Bin.get_by_name(self.pipeline, "x11")\n'
    '        if any(prop.name == "show-pointer" for prop in element.list_properties()):\n'
    '            element.set_property("show-pointer", visible)\n'
)
if POINTER_X11 in source:
    source = source.replace(POINTER_X11, POINTER_WAYLAND, 1)
    print("patch_selkies_waylanddisplay: guarded ximagesrc-only pointer property")

try:
    ast.parse(source)
except SyntaxError as exc:
    print(f"patch_selkies_waylanddisplay: ERROR — patched source does not parse: {exc!r}")
    sys.exit(1)

open(path, "w", encoding="utf-8").write(source)
print(f"patch_selkies_waylanddisplay: wrote {path}")
