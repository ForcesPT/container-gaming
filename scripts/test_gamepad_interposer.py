#!/usr/bin/env python3
# Standalone validation of the Selkies v1.6.2 joystick interposer plumbing.
# Mimics what Selkies' gamepad.py does on the SERVER side (socket + config +
# js_event structs) and what an app (Steam/SDL) does on the CLIENT side (open
# /dev/input/js0 with the interposer LD_PRELOADed, read js_event structs).
# Run INSIDE the container as root (needs /dev/input/js0 + the interposer .so):
#   LD_PRELOAD=/usr/lib/x86_64-linux-gnu/selkies_joystick_interposer.so \
#     python3 /tmp/test_gamepad_interposer.py
# Prints each decoded js_event. If events arrive, the socket->interposer->
# /dev/input/js0 path is proven end-to-end (the gamepad analog of XTest).

import os
import sys
import struct
import socket
import stat
import threading
import time
import ctypes

# Match selkies_gstreamer/gamepad.py v1.6.2 constants.
MAX_BTNS = 512
MAX_AXES = 64
JS_EVENT_BUTTON = 0x01
JS_EVENT_AXIS = 0x02
# STANDARD_XPAD_CONFIG btn_map/axes_map (linux input event codes from
# input_event_codes; hardcode the subset we need to keep this self-contained).
BTN_A, BTN_B, BTN_X, BTN_Y = 0x130, 0x131, 0x133, 0x134
BTN_TL, BTN_TR, BTN_SELECT, BTN_START = 0x136, 0x137, 0x13a, 0x13b
BTN_MODE, BTN_THUMBL, BTN_THUMBR = 0x13c, 0x13d, 0x13e
ABS_X, ABS_Y, ABS_Z, ABS_RX, ABS_RY, ABS_RZ = 0x00, 0x01, 0x02, 0x03, 0x04, 0x05
ABS_HAT0X, ABS_HAT0Y = 0x10, 0x11

BTN_MAP = [BTN_A, BTN_B, BTN_X, BTN_Y, BTN_TL, BTN_TR, BTN_SELECT,
           BTN_START, BTN_MODE, BTN_THUMBL, BTN_THUMBR]
AXES_MAP = [ABS_X, ABS_Y, ABS_Z, ABS_RX, ABS_RY, ABS_RZ, ABS_HAT0X, ABS_HAT0Y]
NUM_BTNS = len(BTN_MAP)
NUM_AXES = len(AXES_MAP)
EVDEV_CONFIG = os.environ.get("DPAD_GAMEPAD_INTERPOSER") == "evdev"

SOCK = "/tmp/selkies_js0.sock"
JS_EVENT_FMT = "IhBB"  # time(u32) value(s16) type(u8) number(u8) = js_event
JS_EVENT_SIZE = struct.calcsize(JS_EVENT_FMT)


def make_config():
    btn = list(BTN_MAP) + [0] * (MAX_BTNS - NUM_BTNS)
    axes = list(AXES_MAP) + [0] * (MAX_AXES - NUM_AXES)
    if EVDEV_CONFIG:
        # MAIN-branch evdev js_config_t: aligned name, USB identity, counts,
        # maps, and final structure padding = exactly 1360 bytes.
        fmt = "255sxHHHHH%dH%dB6s" % (MAX_BTNS, MAX_AXES)
        return struct.pack(
            fmt,
            b"Selkies Controller",
            0x045E,
            0x028E,
            0x0114,
            NUM_BTNS,
            NUM_AXES,
            *btn,
            *axes,
            b"\0" * 6,
        )
    # v1.6.2 classic js_config_t = 1348 bytes with native uint16 alignment.
    fmt = "255sHH%dH%dB" % (MAX_BTNS, MAX_AXES)
    return struct.pack(fmt, b"Selkies Controller", NUM_BTNS, NUM_AXES, *btn, *axes)


def js_event(typ, number, value):
    ts = int((time.time() * 1000) % 1000000000)
    return struct.pack(JS_EVENT_FMT, ts, value, typ, number)


def socket_server(ready, accepted):
    try:
        os.unlink(SOCK)
    except OSError:
        pass
    srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    srv.bind(SOCK)
    srv.listen(1)
    srv.settimeout(15)
    ready.set()
    print("[server] listening on %s" % SOCK, flush=True)
    try:
        conn, _ = srv.accept()
    except socket.timeout:
        print("[server] TIMEOUT — interposer never connected (open /dev/input/js0 failed?)", flush=True)
        return
    accepted.set()
    print("[server] interposer connected — sending config + events", flush=True)
    conn.sendall(make_config())
    time.sleep(0.3)
    # button A press + release
    conn.sendall(js_event(JS_EVENT_BUTTON, 0, 1)); time.sleep(0.1)
    conn.sendall(js_event(JS_EVENT_BUTTON, 0, 0)); time.sleep(0.1)
    # left stick X axis to the right
    conn.sendall(js_event(JS_EVENT_AXIS, 0, 10000)); time.sleep(0.1)
    conn.sendall(js_event(JS_EVENT_AXIS, 0, 0)); time.sleep(0.2)
    print("[server] events sent; keeping socket open 5s for client to drain", flush=True)
    time.sleep(5)
    conn.close()
    srv.close()
    try:
        os.unlink(SOCK)
    except OSError:
        pass


def main():
    os.makedirs("/dev/input", exist_ok=True)
    for i in range(4):
        placeholder = "/dev/input/js%d" % i
        try:
            current = os.lstat(placeholder)
            if not stat.S_ISREG(current.st_mode):
                raise SystemExit(f"refusing non-regular joystick placeholder: {placeholder}")
            os.truncate(placeholder, 0)
        except FileNotFoundError:
            os.mknod(placeholder, stat.S_IFREG | 0o600)
        except OSError:
            pass
    ready = threading.Event()
    accepted = threading.Event()
    t = threading.Thread(target=socket_server, args=(ready, accepted), daemon=True)
    t.start()
    ready.wait(2)
    time.sleep(0.3)  # let the socket server bind

    default_interposer = (
        "/usr/lib/x86_64-linux-gnu/selkies_joystick_interposer_evdev.so"
        if EVDEV_CONFIG
        else "/usr/lib/x86_64-linux-gnu/selkies_joystick_interposer.so"
    )
    interposer = os.environ.get("SELKIES_INTERPOSER", default_interposer)
    print("[client] opening /dev/input/js0 (interposer=%s, LD_PRELOAD present=%s)"
          % (interposer, "LD_PRELOAD" in os.environ), flush=True)
    # The interposer intercepts this open() and connects to /tmp/selkies_js0.sock.
    # Call the process-global C open() symbol directly. CPython's os.open()
    # uses openat64 on current glibc and bypasses this interposer, which hooks
    # open() exactly like SDL/Wine clients do.
    libc = ctypes.CDLL(None, use_errno=True)
    libc.open.argtypes = (ctypes.c_char_p, ctypes.c_int)
    libc.open.restype = ctypes.c_int
    fd = libc.open(b"/dev/input/js0", os.O_RDONLY | os.O_NONBLOCK)
    if fd < 0:
        error = ctypes.get_errno()
        raise OSError(error, os.strerror(error), "/dev/input/js0")
    print("[client] open() returned fd=%d (interposer redirected to socket)" % fd, flush=True)

    # Drain js_event structs as they arrive.
    deadline = time.time() + 8
    got = 0
    decoded = []
    buf = b""
    while time.time() < deadline:
        try:
            chunk = os.read(fd, JS_EVENT_SIZE * 8)
            if chunk:
                buf += chunk
        except BlockingIOError:
            time.sleep(0.05)
            continue
        except OSError as e:
            print("[client] read error: %r" % e, flush=True)
            break
        while len(buf) >= JS_EVENT_SIZE:
            ev, buf = buf[:JS_EVENT_SIZE], buf[JS_EVENT_SIZE:]
            ts, val, typ, num = struct.unpack(JS_EVENT_FMT, ev)
            tname = {JS_EVENT_BUTTON: "BTN", JS_EVENT_AXIS: "AXIS"}.get(typ, "0x%02x" % typ)
            print("[client] js_event  %s num=%d value=%d  (raw ts=%d typ=%d)" % (tname, num, val, ts, typ), flush=True)
            decoded.append((typ, num, val))
            got += 1
    expected = [
        (JS_EVENT_BUTTON, 0, 1),
        (JS_EVENT_BUTTON, 0, 0),
        (JS_EVENT_AXIS, 0, 10000),
        (JS_EVENT_AXIS, 0, 0),
    ]
    ok = accepted.is_set() and decoded == expected
    print("[client] decoded %d events — %s" % (got, "OK: plumbing works" if ok else "FAIL: wrong events"), flush=True)
    os.close(fd)
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()