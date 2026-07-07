#!/usr/bin/env python3
# Socket feeder speaking the MAIN-branch Selkies interposer protocol (the new
# js_config_t with vendor/product/version + the arch-byte handshake). Pairs
# with the evdev interposer opening /dev/input/event1000 (or /dev/input/js0).
#
# Protocol (main interposer, addons/js-interposer/joystick_interposer.c):
#   - interposer connects, server SENDS js_config_t first (the interposer reads
#     sizeof(js_config_t)), THEN the interposer SENDS a 1-byte arch specifier
#     (sizeof(long)) back to the server (we read+ignore it).
#   - subsequent events are js_event structs: "IhBB" (time, value, type, number)
import os, socket, struct, time, sys

MAX_BTNS, MAX_AXES = 512, 64
PATH = sys.argv[1] if len(sys.argv) > 1 else "/tmp/selkies_event1000.sock"
JS_EVENT_BUTTON, JS_EVENT_AXIS = 0x01, 0x02
# STANDARD_XPAD_CONFIG (matches fake-udev's "Microsoft X-Box 360 pad")
BTN_MAP = [0x130,0x131,0x133,0x134,0x136,0x137,0x13a,0x13b,0x13c,0x13d,0x13e]  # 11
AXES_MAP = [0x00,0x01,0x02,0x03,0x04,0x05,0x10,0x11]  # 8

def config():
    # js_config_t (main): name[255] (padded to 256 for uint16 alignment) + vendor(u16)
    # + product(u16) + version(u16) + num_btns(u16) + num_axes(u16) + btn_map[512](u16)
    # + axes_map[64](u8) + final_alignment_padding[6](u8) = 256 + 10 + 1024 + 64 + 6 = 1360
    # struct.pack has no auto-align, so emit the 1-byte pad explicitly ("255sx").
    fmt = "255sxHHHHH%dH%dB6s" % (MAX_BTNS, MAX_AXES)
    btn = list(BTN_MAP) + [0]*(MAX_BTNS-len(BTN_MAP))
    axes = list(AXES_MAP) + [0]*(MAX_AXES-len(AXES_MAP))
    return struct.pack(fmt, b"Selkies Controller", 0x045e, 0x028e, 0x0114,
                       len(BTN_MAP), len(AXES_MAP), *btn, *axes, b"\0"*6)

def ev(t, n, v):
    return struct.pack("IhBB", int((time.time()*1000)%1000000000), v, t, n)

def main():
    try: os.unlink(PATH)
    except OSError: pass
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    s.bind(PATH); s.listen(1); s.settimeout(20)
    sys.stderr.write("[feeder] listening on %s\n" % PATH); sys.stderr.flush()
    try: c, _ = s.accept()
    except socket.timeout:
        sys.stderr.write("[feeder] TIMEOUT (interposer never connected)\n"); sys.stderr.flush(); return 1
    sys.stderr.write("[feeder] interposer connected — sending config\n"); sys.stderr.flush()
    c.sendall(config())
    # the interposer sends a 1-byte arch specifier back; read+ignore it
    try: c.recv(1)
    except OSError: pass
    time.sleep(0.2)
    sys.stderr.write("[feeder] sending button + axis events\n"); sys.stderr.flush()
    c.sendall(ev(JS_EVENT_BUTTON, 0, 1)); time.sleep(0.1)
    c.sendall(ev(JS_EVENT_BUTTON, 0, 0)); time.sleep(0.1)
    c.sendall(ev(JS_EVENT_AXIS, 0, 10000)); time.sleep(0.1)
    c.sendall(ev(JS_EVENT_AXIS, 0, 0)); time.sleep(0.5)
    c.close(); s.close()
    try: os.unlink(PATH)
    except OSError: pass
    sys.stderr.write("[feeder] done\n"); sys.stderr.flush()
    return 0

if __name__ == "__main__":
    sys.exit(main())