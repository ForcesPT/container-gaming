#!/usr/bin/env python3
# Socket-server feeder that mimics Selkies v1.6.2 gamepad.py: accepts the
# interposer's connection on /tmp/selkies_js0.sock, sends the js_config_t blob,
# then a button press/release + an axis motion. Pair with jsclient (C) which
# opens /dev/input/js0 under LD_PRELOAD. Run in the container:
#   python3 /tmp/jsfeeder.py &  LD_PRELOAD=... /tmp/jsclient;  kill %1
import os, socket, struct, time, sys

MAX_BTNS, MAX_AXES = 512, 64
SOCK = "/tmp/selkies_js0.sock"
JS_EVENT_BUTTON, JS_EVENT_AXIS = 0x01, 0x02
BTN_A = 0x130; ABS_X = 0x00
BTN_MAP = [0x130,0x131,0x133,0x134,0x136,0x137,0x13a,0x13b,0x13c,0x13d,0x13e]
AXES_MAP = [0x00,0x01,0x02,0x03,0x04,0x05,0x10,0x11]

def config():
    fmt = "255sHH%dH%dB" % (MAX_BTNS, MAX_AXES)
    btn = list(BTN_MAP) + [0]*(MAX_BTNS-len(BTN_MAP))
    axes = list(AXES_MAP) + [0]*(MAX_AXES-len(AXES_MAP))
    return struct.pack(fmt, b"Selkies Controller", len(BTN_MAP), len(AXES_MAP), *btn, *axes)

def ev(t, n, v):
    return struct.pack("IhBB", int((time.time()*1000)%1000000000), v, t, n)

def main():
    try: os.unlink(SOCK)
    except OSError: pass
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    s.bind(SOCK); s.listen(1); s.settimeout(20)
    sys.stderr.write("[feeder] listening on %s\n" % SOCK); sys.stderr.flush()
    try: c, _ = s.accept()
    except socket.timeout:
        sys.stderr.write("[feeder] TIMEOUT (interposer never connected)\n"); sys.stderr.flush(); return 1
    sys.stderr.write("[feeder] interposer connected — sending config + events\n"); sys.stderr.flush()
    c.sendall(config()); time.sleep(0.2)
    c.sendall(ev(JS_EVENT_BUTTON, 0, 1)); time.sleep(0.1)
    c.sendall(ev(JS_EVENT_BUTTON, 0, 0)); time.sleep(0.1)
    c.sendall(ev(JS_EVENT_AXIS, 0, 10000)); time.sleep(0.1)
    c.sendall(ev(JS_EVENT_AXIS, 0, 0)); time.sleep(0.5)
    sys.stderr.write("[feeder] events sent\n"); sys.stderr.flush()
    c.close(); s.close()
    try: os.unlink(SOCK)
    except OSError: pass
    return 0

if __name__ == "__main__":
    sys.exit(main())