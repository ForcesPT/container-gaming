#!/usr/bin/env python3
# Probe whether a uinput gamepad device can be created as root inside the
# container (no python-evdev; raw ioctls via ctypes). If this works, the
# uinput-gamepad-daemon (Phase 2) is viable: Steam's SDL3 sees a real kernel
# evdev controller instead of the LD_PRELOAD /dev/input/js* shim.
import os, struct, ctypes, time, glob, sys

UINPUT = "/dev/uinput"
UI_DEV_CREATE  = 0x5501       # _IO('U',1)
UI_DEV_DESTROY = 0x5502       # _IO('U',2)
UI_DEV_SETUP   = 0x405C5503   # _IOW('U',3,struct uinput_setup=92)
UI_ABS_SETUP   = 0x405C5504   # _IOW('U',4,struct uinput_abs_setup)
UI_SET_EVBIT   = 0x40045564   # _IOW('U',100,int)
UI_SET_KEYBIT  = 0x40045565   # _IOW('U',101,int)
UI_SET_ABSBIT  = 0x40045567   # _IOW('U',103,int)
EV_KEY = 0x01; EV_ABS = 0x03; EV_SYN = 0x00
BTN_SOUTH = 0x130; ABS_X = 0x00

SETUP_FMT = "80sHHHHI"  # name[80] + input_id(4x u16) + ff_effects_max(u32) = 92

class AbsSetup(ctypes.Structure):
    _fields_ = [("code", ctypes.c_uint16), ("min", ctypes.c_int32),
                ("max", ctypes.c_int32), ("fuzz", ctypes.c_int32),
                ("flat", ctypes.c_int32), ("resolution", ctypes.c_int32)]

def main():
    libc = ctypes.CDLL(None, use_errno=True)
    try:
        fd = os.open(UINPUT, os.O_WRONLY | os.O_NONBLOCK)
        print("[uinput] open OK fd=%d" % fd)
    except OSError as e:
        print("[uinput] open FAILED %r" % e); return 1

    def ioctl(nr, arg):
        a = arg if isinstance(arg, ctypes.c_int) else ctypes.byref(arg)
        r = libc.ioctl(fd, nr, a)
        if r != 0:
            print("[uinput] ioctl %#x FAILED (%s)" % (nr, os.strerror(ctypes.get_errno())))
        return r

    if (ioctl(UI_SET_EVBIT, ctypes.c_int(EV_KEY)) or
        ioctl(UI_SET_EVBIT, ctypes.c_int(EV_ABS)) or
        ioctl(UI_SET_EVBIT, ctypes.c_int(EV_SYN)) or
        ioctl(UI_SET_KEYBIT, ctypes.c_int(BTN_SOUTH)) or
        ioctl(UI_SET_ABSBIT, ctypes.c_int(ABS_X))):
        os.close(fd); return 1
    if ioctl(UI_ABS_SETUP, AbsSetup(ABS_X, -32767, 32767, 16, 16, 256)) != 0:
        print("[uinput] (continuing without absinfo)")

    setup = struct.pack(SETUP_FMT, b"Selkies Gamepad", 0x0003, 0x045e, 0x0b12, 0x0400, 0)
    # UI_DEV_SETUP takes a pointer to the struct
    r = libc.ioctl(fd, UI_DEV_SETUP, setup)  # bytes buffer works as a pointer in ctypes
    if r != 0:
        print("[uinput] UI_DEV_SETUP FAILED (%s)" % os.strerror(ctypes.get_errno())); os.close(fd); return 1
    r = libc.ioctl(fd, UI_DEV_CREATE)
    if r != 0:
        print("[uinput] UI_DEV_CREATE FAILED (%s)" % os.strerror(ctypes.get_errno())); os.close(fd); return 1

    time.sleep(0.5)
    evs = sorted(glob.glob("/dev/input/event*"))
    print("[uinput] device created; /dev/input/event* = %s" % evs)
    EV_FMT = "llHHi"  # input_event: timeval(8+8)+type(u16)+code(u16)+value(s32) = 24
    now = int(time.time())
    def w(t, c, v):
        os.write(fd, struct.pack(EV_FMT, now, 0, t, c, v))
        os.write(fd, struct.pack(EV_FMT, now, 0, EV_SYN, 0, 0))
    w(EV_KEY, BTN_SOUTH, 1); time.sleep(0.1); w(EV_KEY, BTN_SOUTH, 0)
    print("[uinput] wrote button press/release — OK")
    time.sleep(0.5)
    libc.ioctl(fd, UI_DEV_DESTROY)
    os.close(fd)
    print("[uinput] destroyed + closed — UINPUT IS VIABLE")
    return 0

if __name__ == "__main__":
    sys.exit(main())