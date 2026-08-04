#!/usr/bin/env python3
# udev_enum_probe.py — confirm fake-libudev exposes the 4 virtual X-Box pads
# via a libudev enumerate query (the exact query Steam's SDL3 makes).
# Run INSIDE the container with LD_PRELOAD=.../dpad_fake_libudev.so so the
# fake libudev is the one answering. Prints every input device libudev returns
# with ID_INPUT_JOYSTICK=1 (SDL3's match). Expect js0-3 + event1000-1003.
import ctypes, ctypes.util, os, sys

libpath = ctypes.util.find_library("udev")
if not libpath:
    # the fake lib is /usr/lib/x86_64-linux-gnu/libudev.so.1 (LD_PRELOAD'd)
    for p in ("/usr/lib/x86_64-linux-gnu/libudev.so.1", "/usr/lib/i386-linux-gnu/libudev.so.1"):
        if os.path.exists(p):
            libpath = p
            break
if not libpath:
    print("NO libudev found"); sys.exit(2)
print("loading:", libpath, "(LD_PRELOAD=%s)" % os.environ.get("LD_PRELOAD", ""))
u = ctypes.CDLL(libpath)

u.udev_new.restype = ctypes.c_void_p
u.udev_enumerate_new.restype = ctypes.c_void_p
u.udev_enumerate_add_match_subsystem.restype = ctypes.c_int
u.udev_enumerate_add_match_property.restype = ctypes.c_int
u.udev_enumerate_scan_devices.restype = ctypes.c_int
u.udev_enumerate_get_list_entry.restype = ctypes.c_void_p
u.udev_list_entry_get_next.restype = ctypes.c_void_p
u.udev_list_entry_get_name.restype = ctypes.c_char_p
u.udev_device_new_from_syspath.restype = ctypes.c_void_p
u.udev_device_get_devnode.restype = ctypes.c_char_p
u.udev_device_get_property_value.restype = ctypes.c_char_p

ud = u.udev_new(None)
en = u.udev_enumerate_new(ud)
u.udev_enumerate_add_match_subsystem(en, b"input")
u.udev_enumerate_add_match_property(en, b"ID_INPUT_JOYSTICK", b"1")
u.udev_enumerate_scan_devices(en)
entry = u.udev_enumerate_get_list_entry(en)
count = 0
while entry:
    name = u.udev_list_entry_get_name(entry)
    if not name:
        entry = u.udev_list_entry_get_next(entry); continue
    dev = u.udev_device_new_from_syspath(ud, name)
    if dev:
        node = u.udev_device_get_devnode(dev)
        if node:
            count += 1
            print("JOYSTICK:", node.decode())
    entry = u.udev_list_entry_get_next(entry)
print("total ID_INPUT_JOYSTICK devices:", count)