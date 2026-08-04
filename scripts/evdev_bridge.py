#!/usr/bin/env python3
# evdev_bridge.py — dual-serve bridge for the evdev gamepad interposer.
#
# Started by entrypoint.sh ONLY when DPAD_GAMEPAD_INTERPOSER=evdev (the gate).
# The working classic-joystick path is the default; this is dormant until then.
#
# WHY (docs/PROJECT_STATE.md §6 + scripts/gamepad-evdev-fallback/README.md):
#   Steam ships SDL3, which discovers gamepads via libudev + evdev
#   (/dev/input/event*), not the legacy joystick API. The evdev interposer
#   (joystick_interposer_main.c) + fake-libudev (libudev.so.1) make SDL3 discover
#   4 virtual Microsoft X-Box 360 pads at /dev/input/js{0-3} + event100{0-3}.
#   But that interposer reads `struct input_event` (24B on x86_64 / 16B on i386)
#   on /dev/input/event100N — it does NOT translate js_event (confirmed live
#   2026-08-05: it recv's sizeof(input_event) raw into the app buffer). Selkies
#   v1.6.2's SelkiesGamepad only serves js_event (8B) on /tmp/selkies_jsN.sock.
#   So the evdev path needs a server that sends input_event on a separate socket.
#
# This bridge IS that server, and it does it WITHOUT monkey-patching Selkies:
#   - per pad N (0..3): connect as a CLIENT to /tmp/selkies_jsN.sock (Selkies'
#     server) — read + discard the 1360B js_config_t, then read 8B js_events.
#   - per pad N: SERVE on /tmp/selkies_event100N.sock — on the interposer
#     connecting: send the 1360B config, read the 1-byte arch specifier
#     (= sizeof(long): 4 i386 / 8 x86_64) so the input_event timeval matches the
#     client's long size, then translate + forward each js_event as
#     input_event + EV_SYN.
#
#   js_event (8B) "IhBB":  time u32, value s16, type u8, number u8
#   input_event (24B/16B): timeval{long sec, long usec} + type u16 + code u16 + value s32
#     BUTTON js -> EV_KEY  code=BTN_MAP[number]   value=value  + SYN
#     AXIS   js -> EV_ABS  code=AXES_MAP[number]   value=value  + SYN
#
# Testable without a real gamepad: a feeder (jsfeeder_main.py / a simple test
# feeder) on /tmp/selkies_js0.sock + evclient opening /dev/input/event1000 under
# the interposer validates the dispatch end-to-end.
#
# Requires DPAD_GAMEPAD_INTERPOSER=evdev so dpad_gamepad_patch.py is also active
# (Selkies then sends the 1360B config on the js socket, which this bridge
# discards). See scripts/gamepad-evdev-fallback/README.md.

import os
import sys
import struct
import time
import asyncio
import signal

# --- input_event_codes subset (linux/input-event-codes.h) ---
EV_SYN = 0x00
EV_KEY = 0x01
EV_ABS = 0x03
SYN_REPORT = 0x00
JS_EVENT_BUTTON = 0x01
JS_EVENT_AXIS = 0x02

# STANDARD_XPAD_CONFIG — must match gamepad.py + fake-libudev (Microsoft X-Box 360 pad)
BTN_MAP = [0x130, 0x131, 0x133, 0x134, 0x136, 0x137, 0x13a, 0x13b, 0x13c, 0x13d, 0x13e]  # BTN_A..BTN_THUMBR (11)
AXES_MAP = [0x00, 0x01, 0x02, 0x03, 0x04, 0x05, 0x10, 0x11]                              # ABS_X..ABS_HAT0Y (8)
VENDOR, PRODUCT, VERSION = 0x045e, 0x028e, 0x0114
NAME = b"Selkies Controller"
MAX_BTNS, MAX_AXES = 512, 64
CONFIG_SIZE = 1360  # MAIN-branch js_config_t (matches dpad_gamepad_patch.py / jsfeeder_main.py)
NUM_PADS = 4

JS_EVENT_SIZE = 8


def log(msg):
    print("[evdev_bridge] " + msg, file=sys.stderr, flush=True)


def make_config():
    """The 1360B MAIN-branch js_config_t (matches dpad_gamepad_patch.py + jsfeeder_main.py)."""
    fmt = "255sxHHHHH%dH%dB6s" % (MAX_BTNS, MAX_AXES)
    btn = list(BTN_MAP) + [0] * (MAX_BTNS - len(BTN_MAP))
    axes = list(AXES_MAP) + [0] * (MAX_AXES - len(AXES_MAP))
    return struct.pack(fmt, NAME, VENDOR, PRODUCT, VERSION,
                       len(BTN_MAP), len(AXES_MAP), *btn, *axes, b"\0" * 6)


CONFIG = make_config()


def input_event_packer(arch):
    """Return a function(type, code, value) -> bytes for the client's sizeof(long).

    struct input_event { struct timeval time; __u16 type; __u16 code; __s32 value }
    struct timeval { long tv_sec, long tv_usec }  -> arch bytes each.
    """
    # "=" prefix = standard size, no alignment padding. q/i = 8B/4B signed.
    fmt = "=iiHHi" if arch == 4 else "=qqHHi"   # 16B i386 / 24B x86_64
    size = struct.calcsize(fmt)

    def mk(ev_type, code, value):
        now = time.time()
        sec = int(now)
        usec = int((now - sec) * 1000000)
        return struct.pack(fmt, sec, usec, ev_type, code, value)

    mk.size = size
    return mk


def js_to_input(js8, mk):
    """js_event (8B) -> input_event + EV_SYN bytes, or None if not a button/axis event."""
    if len(js8) < JS_EVENT_SIZE:
        return None
    _t, value, jtype, number = struct.unpack("IhBB", js8[:JS_EVENT_SIZE])
    if jtype == JS_EVENT_BUTTON:
        if number >= len(BTN_MAP):
            return None
        return mk(EV_KEY, BTN_MAP[number], int(value)) + mk(EV_SYN, SYN_REPORT, 0)
    if jtype == JS_EVENT_AXIS:
        if number >= len(AXES_MAP):
            return None
        return mk(EV_ABS, AXES_MAP[number], int(value)) + mk(EV_SYN, SYN_REPORT, 0)
    return None


class PadBridge:
    def __init__(self, n):
        self.n = n
        self.js_sock = "/tmp/selkies_js%d.sock" % n
        self.ev_sock = "/tmp/selkies_event100%d.sock" % n
        self.ev_clients = {}   # fd -> (writer, mk)
        self.js_buf = b""
        self.js_config_done = False

    # --- event server (the evdev interposer connects here) ---
    async def ev_server_main(self):
        try:
            os.unlink(self.ev_sock)
        except FileNotFoundError:
            pass
        srv = await asyncio.start_unix_server(self._ev_client_cb, path=self.ev_sock)
        log("pad %d: event server listening on %s" % (self.n, self.ev_sock))
        return srv

    async def _ev_client_cb(self, reader, writer):
        sock = writer.get_extra_info("socket")
        fd = sock.fileno() if sock else -1
        mk = None
        try:
            writer.write(CONFIG)
            await writer.drain()
            # the interposer reads config, then SENDS a 1-byte arch specifier (sizeof(long)).
            arch_byte = await reader.readexactly(1)
            arch = arch_byte[0]
            mk = input_event_packer(arch)
            self.ev_clients[fd] = (writer, mk)
            log("pad %d: evdev interposer connected (fd %d, arch=%d, input_event=%dB)"
                % (self.n, fd, arch, mk.size))
            # keep the connection open until the interposer closes (EOF)
            while True:
                b = await reader.read(1)
                if not b:
                    break
        except asyncio.IncompleteReadError:
            pass
        except Exception as e:
            log("pad %d: event client fd %d ended: %r" % (self.n, fd, e))
        finally:
            self.ev_clients.pop(fd, None)
            try:
                writer.close()
            except Exception:
                pass

    # --- js client (connects to Selkies' js socket) ---
    async def js_client_main(self):
        reader = writer = None
        # wait for Selkies to create the js socket, then connect (retry — Selkies
        # unlinks+rebinds across restarts).
        while True:
            if not os.path.exists(self.js_sock):
                await asyncio.sleep(0.5)
                continue
            try:
                reader, writer = await asyncio.open_unix_connection(self.js_sock)
                break
            except (FileNotFoundError, ConnectionRefusedError):
                await asyncio.sleep(0.5)
        log("pad %d: js client connected to %s" % (self.n, self.js_sock))
        try:
            while True:
                chunk = await reader.read(4096)
                if not chunk:
                    break
                self.js_buf += chunk
                # first CONFIG_SIZE bytes are the js_config_t from Selkies — discard.
                if not self.js_config_done:
                    if len(self.js_buf) < CONFIG_SIZE:
                        continue
                    self.js_buf = self.js_buf[CONFIG_SIZE:]
                    self.js_config_done = True
                # then 8B js_events.
                dead = []
                while len(self.js_buf) >= JS_EVENT_SIZE:
                    js8, self.js_buf = self.js_buf[:JS_EVENT_SIZE], self.js_buf[JS_EVENT_SIZE:]
                    for fd, (w, mk) in list(self.ev_clients.items()):
                        ie = js_to_input(js8, mk)
                        if ie is None:
                            continue
                        try:
                            w.write(ie)
                        except Exception:
                            dead.append(fd)
                for fd in dead:
                    self.ev_clients.pop(fd, None)
        except Exception as e:
            log("pad %d: js client ended: %r" % (self.n, e))
        finally:
            if writer:
                try:
                    writer.close()
                except Exception:
                    pass


async def main():
    pads = [PadBridge(n) for n in range(NUM_PADS)]
    for p in pads:
        asyncio.create_task(p.ev_server_main())
        asyncio.create_task(p.js_client_main())
    log("bridge up: %d pads (js -> event1000-1003)" % NUM_PADS)
    await asyncio.Event().wait()  # run forever


if __name__ == "__main__":
    signal.signal(signal.SIGINT, lambda *_: sys.exit(0))
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass