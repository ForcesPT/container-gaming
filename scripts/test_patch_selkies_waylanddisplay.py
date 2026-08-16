#!/usr/bin/env python3
"""Regression: Wayland patch must apply to pristine Selkies 1.6.2."""
from pathlib import Path
import ast
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
PATCHER = ROOT / "scripts" / "patch_selkies_waylanddisplay.py"

STOCK_FIXTURE = '''\
import os
class Gst:
    class ElementFactory:
        @staticmethod
        def make(*args): pass
    class State:
        PLAYING = 1
    class Fraction:
        def __init__(self, *args): pass
    @staticmethod
    def caps_from_string(value): pass
    class Bin:
        @staticmethod
        def get_by_name(*args): pass

class App:
    def build_video_pipeline(self):
        self.ximagesrc = Gst.ElementFactory.make("ximagesrc", "x11")
        ximagesrc = self.ximagesrc
        ximagesrc.set_property("show-pointer", 0)
        ximagesrc.set_property("remote", 1)
        ximagesrc.set_property("blocksize", 16384)
        ximagesrc.set_property("use-damage", 0)
        self.ximagesrc_caps = Gst.caps_from_string("video/x-raw")
        self.ximagesrc_caps.set_value("framerate", Gst.Fraction(self.framerate, 1))
        self.ximagesrc_capsfilter = Gst.ElementFactory.make("capsfilter")
        self.ximagesrc_capsfilter.set_property("caps", self.ximagesrc_caps)
        pipeline_elements = [self.ximagesrc, self.ximagesrc_capsfilter]
        if self.encoder in ["nvh264enc"]:
            pipeline_elements += [cudaupload, cudaconvert, cudaconvert_capsfilter, nvh264enc, h264enc_capsfilter, rtph264pay, rtph264pay_capsfilter]

    def start_ximagesrc(self):
        if self.ximagesrc:
            self.ximagesrc.set_property("endx", 0)
            self.ximagesrc.set_property("endy", 0)
            self.ximagesrc.set_state(Gst.State.PLAYING)

    def set_framerate(self, framerate):
        if self.pipeline:
            self.framerate = framerate
            self.ximagesrc_caps = Gst.caps_from_string("video/x-raw")
            self.ximagesrc_caps.set_value("framerate", Gst.Fraction(self.framerate, 1))
            self.ximagesrc_capsfilter.set_property("caps", self.ximagesrc_caps)

    def set_pointer_visible(self, visible):
        element = Gst.Bin.get_by_name(self.pipeline, "x11")
        element.set_property("show-pointer", visible)
'''

with tempfile.TemporaryDirectory() as td:
    target = Path(td) / "gstwebrtc_app.py"
    target.write_text(STOCK_FIXTURE)
    result = subprocess.run(
        ["python3", str(PATCHER), str(target)],
        text=True,
        capture_output=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    patched = target.read_text()
    ast.parse(patched)
    assert 'Gst.ElementFactory.make("waylanddisplaysrc", "x11")' in patched
    assert 'DPAD_VIDEO_SRC", "") == "pipewiresrc"' not in patched
    assert 'set_property("show-pointer", 0)' not in patched
    assert 'set_property("endx", 0)' not in patched
    assert 'video/x-raw,format=RGBx' in patched

print("Wayland patch applies directly to pristine Selkies")
