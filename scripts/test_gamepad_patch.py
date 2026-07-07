#!/usr/bin/env python3
# Unit-test dpad_gamepad_patch: with DPAD_GAMEPAD_INTERPOSER=evdev the patched
# SelkiesGamepad.__make_config must emit the MAIN-branch js_config_t (1360 bytes)
# with vendor/product/version set. Without the env it stays at 1347 (v1.6.2).
import os, struct, sys
import selkies_gstreamer
sys.path.insert(0, os.path.dirname(os.path.abspath(selkies_gstreamer.__file__)))
from gamepad import SelkiesGamepad, MAX_BTNS, MAX_AXES

# build a minimal config like detect_gamepad_config + set_config would
cfg = {
    "name": "Selkies Controller",
    "btn_map": [0x130,0x131,0x133,0x134,0x136,0x137,0x13a,0x13b,0x13c,0x13d,0x13e],
    "axes_map": [0x00,0x01,0x02,0x03,0x04,0x05,0x10,0x11],
    "vendor": 0x045e, "product": 0x028e, "version": 0x0114,
}

# SelkiesGamepad.__init__(socket_path, loop) — give dummies
g = SelkiesGamepad("/tmp/x.sock", None)
g.config = cfg
data = g._SelkiesGamepad__make_config()
print("config bytes:", len(data))
# unpack the header to verify fields (skip name[255]+1 pad = 256)
name = data[:255].rstrip(b"\0").decode()
vendor, product, version, num_btns, num_axes = struct.unpack_from("HHHHH", data, 256)
print("name=%r vendor=0x%04x product=0x%04x version=0x%04x num_btns=%d num_axes=%d"
      % (name, vendor, product, version, num_btns, num_axes))
ok = (len(data) == 1360 and vendor == 0x045e and product == 0x028e
      and num_btns == 11 and num_axes == 8)
print("RESULT:", "OK (1360-byte evdev config)" if ok else "FAIL")
sys.exit(0 if ok else 1)