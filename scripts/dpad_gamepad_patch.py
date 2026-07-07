# dpad_gamepad_patch.py — make Selkies' v1.6.2 gamepad socket server speak the
# MAIN-branch interposer config protocol so the evdev-capable interposer (the
# one that fixes Steam/SDL3 in containers, Selkies issue #168 / PR #173) reads
# our config.
#
# Auto-loaded at Python startup via dpad_gamepad_patch.pth in site-packages
# (same .pth pattern as dpad_input_patch.py).
#
# WHY: Steam ships SDL3, which discovers gamepads via libudev + evdev
# (/dev/input/event*), NOT the legacy joystick API (/dev/input/js*). The v1.6.2
# interposer only hooks the joystick API, so Steam can't see the gamepad. The
# MAIN-branch interposer adds evdev interception + a companion fake-libudev
# (LD_PRELOAD) that lies to libudev so SDL3 discovers 4 virtual XBox pads at
# /dev/input/js0 + /dev/input/event1000-1003. That interposer reads a NEW
# js_config_t (1360 bytes: name[255]+pad + vendor/product/version/num_btns/
# num_axes (5x u16) + btn_map[512](u16) + axes_map[64](u8) + padding[6]) and
# sends a 1-byte arch specifier back (harmless if the server leaves it unread).
# This patch rewrites SelkiesGamepad.__make_config to emit that 1360-byte struct
# so the new interposer reads it cleanly. The browser->WebRTC->Selkies gamepad
# event path (js_event structs) is unchanged — the new interposer translates
# js_events to input_events for evdev clients itself.
#
# Gated on DPAD_GAMEPAD_INTERPOSER=evdev. Unset = original v1.6.2 config
# (1347 bytes) for the legacy joystick-only interposer (kept for the DFP path
# / older apps that read /dev/input/js* directly).
#
# IMPORTANT: like webrtc_input, `gamepad` is imported both as a top-level module
# (`from gamepad import SelkiesGamepad` in webrtc_input.py) and as
# `selkies_gstreamer.gamepad` — two separate module objects. We patch BOTH.

import os
import sys
import struct

MAX_BTNS = 512
MAX_AXES = 64

# Microsoft X-Box 360 pad identity — must match fake-libudev's FAKE_UDEV_* so the
# device the app discovers via libudev matches the one the interposer serves.
_DEFAULT_VENDOR = 0x045e
_DEFAULT_PRODUCT = 0x028e
_DEFAULT_VERSION = 0x0114


def _log(msg):
    print("dpad_gamepad: " + msg, file=sys.stderr, flush=True)


def _patch():
    if os.environ.get("DPAD_GAMEPAD_INTERPOSER", "") != "evdev":
        return
    mods = {}
    # webrtc_input.py does `from gamepad import SelkiesGamepad` — i.e. the
    # TOP-LEVEL `gamepad` module. That only resolves if the selkies_gstreamer
    # package dir is on sys.path (gamepad.py lives at selkies_gstreamer/gamepad.py
    # but is imported as top-level). At .pth time that dir isn't on sys.path yet,
    # so add it explicitly — then the `gamepad` module object we patch is the SAME
    # one webrtc_input will reuse from sys.modules at runtime (no second import).
    try:
        import selkies_gstreamer
        sg_dir = os.path.dirname(os.path.abspath(selkies_gstreamer.__file__))
        if sg_dir not in sys.path:
            sys.path.insert(0, sg_dir)
    except Exception:
        pass
    for name in ("gamepad", "selkies_gstreamer.gamepad"):
        try:
            m = __import__(name, fromlist=["SelkiesGamepad"])
        except Exception:
            continue
        cls = getattr(m, "SelkiesGamepad", None)
        if cls is not None:
            mods[id(cls)] = cls
    if not mods:
        _log("disabled (no SelkiesGamepad class found)")
        return

    def make_config(self):
        # Mirror SelkiesGamepad.__make_config but emit the MAIN-branch js_config_t
        # (1360 bytes). struct.pack adds no alignment padding, so emit the 1-byte
        # pad after name[255] explicitly ("255sx") to match the C struct's
        # uint16 alignment of the following vendor field.
        if not self.config:
            return None
        num_btns = len(self.config["btn_map"])
        num_axes = len(self.config["axes_map"])
        btn_map = [i for i in self.config["btn_map"]]
        axes_map = [i for i in self.config["axes_map"]]
        btn_map[num_btns:MAX_BTNS] = [0] * (MAX_BTNS - num_btns)
        axes_map[num_axes:MAX_AXES] = [0] * (MAX_AXES - num_axes)
        vendor = self.config.get("vendor", _DEFAULT_VENDOR)
        product = self.config.get("product", _DEFAULT_PRODUCT)
        version = self.config.get("version", _DEFAULT_VERSION)
        fmt = "255sxHHHHH%dH%dB6s" % (MAX_BTNS, MAX_AXES)
        data = struct.pack(
            fmt,
            self.config["name"].encode(),
            vendor, product, version,
            num_btns, num_axes,
            *btn_map, *axes_map,
            b"\0" * 6,
        )
        return data

    n = 0
    for cls in mods.values():
        # __make_config is name-mangled? No — it's just a normal method with a
        # dunder prefix; assign onto the class directly.
        cls._SelkiesGamepad__make_config = make_config
        n += 1
    _log("patched SelkiesGamepad.__make_config -> 1360-byte evdev interposer config (%d class(es))" % n)


_patch()