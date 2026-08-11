# dpad_input_patch.py — Stage 3a input router for the gamescope + wayland paths.
#
# Auto-loaded at Python startup via dpad_input_patch.pth in site-packages.
# When DPAD_INPUT_DISPLAY is set (e.g. ":0" = gamescope's headless Xwayland OR
# sway's nested-Xwayland :0 under gst-wayland-display), it makes Selkies'
# WebRTCInput connect its X display to DPAD_INPUT_DISPLAY instead of the
# capture display, and switches send_x11_keypress()/send_mouse() from pynput
# to XTest on that display — so keyboard/mouse reach Steam. Capture reads
# DISPLAY directly and is unaffected.
#
# LAZY OPEN (2026-08-09, wayland-display path): the gamescope path has :0 up
# before selkies starts, but the wayland-display path inverts the boot order
# (selkies first → peer connects → compositor → sway → Xwayland :0). So we
# install the overrides at import but OPEN DPAD_INPUT_DISPLAY LAZILY on the
# first input event (retrying until :0 appears), instead of once at import
# (which would fail + leave input dead). A no-op until :0 is up.
#
# Includes a monkey-patch for a python-xlib 0.33 bug (add_extension_event) that
# otherwise crashes display.Display() with "type object does not support item
# assignment" during randr.init.
#
# IMPORTANT: __main__.py does `from webrtc_input import WebRTCInput` (top-level),
# a SEPARATE module object from selkies_gstreamer.webrtc_input (double-import).
# We patch BOTH classes. MOUSE_* constants are module-level (identical in both).
#
# When DPAD_INPUT_DISPLAY is unset, this module does nothing (original behavior).

import os
import sys
import time

def _log(msg):
    print("dpad_input: " + msg, file=sys.stderr, flush=True)

def _patch():
    dpy = os.environ.get("DPAD_INPUT_DISPLAY", "")
    if not dpy:
        return
    try:
        from Xlib import display, X
        from Xlib.ext import xtest
        from selkies_gstreamer import webrtc_input as w
        import webrtc_input as w_top
    except Exception as e:
        _log("disabled (%r)" % e)
        return

    dbg = os.environ.get("DPAD_INPUT_DEBUG", "")

    # --- python-xlib 0.33 bug fix -----------------------------------------
    # python-xlib 0.33 bug: add_extension_event stores a base event as
    # event_classes[code] = evt (a TYPE), then a sub-event for the SAME code
    # does event_classes[code][subcode] = evt on the TYPE ->
    # TypeError 'type object does not support item assignment'. This fires
    # during xfixes.init inside display.Display() when two extensions collide
    # on an event code. The dispatch (parse_event_response) already handles
    # event_classes[code] being a dict {subcode: cls}, so we make add_extension_event
    # robust: promote a TYPE to a dict (base under None, sub under subcode)
    # instead of crashing. Must run BEFORE any display.Display() in the process.
    try:
        from Xlib.protocol import display as _xpd
        if not getattr(_xpd.Display, "_dpad_aee_patched", False):
            def add_extension_event(self, code, evt, subcode=None):
                cur = self.event_classes.get(code)
                if subcode is None:
                    # base event: keep under None if sub-events already exist
                    if isinstance(cur, dict):
                        cur[None] = evt
                    else:
                        self.event_classes[code] = evt
                else:
                    if cur is None:
                        self.event_classes[code] = {subcode: evt}
                    elif isinstance(cur, dict):
                        cur[subcode] = evt
                    else:
                        # base TYPE registered first -> promote to dict
                        self.event_classes[code] = {None: cur, subcode: evt}
            _xpd.Display.add_extension_event = add_extension_event
            _xpd.Display._dpad_aee_patched = True
            _log("patched Xlib add_extension_event (randr/xfixes bug fix)")
    except Exception as e:
        _log("could not patch add_extension_event: %r" % e)

    M = w
    classes = {}
    for mod in (w, w_top):
        cls = getattr(mod, "WebRTCInput", None)
        if cls is not None:
            classes[id(cls)] = cls
    if not classes:
        _log("no WebRTCInput class found")
        return

    # --- LAZY display open ------------------------------------------------
    # Open DPAD_INPUT_DISPLAY on demand + cache. The wayland-display path
    # starts selkies before sway's Xwayland :0 is up; opening at import would
    # fail + leave input dead. Retry on each input event until :0 appears.
    _gs_dpy = [None]  # mutable holder so the nested fns can reassign
    _last_err = [None]
    def _get_dpy():
        if _gs_dpy[0] is not None:
            return _gs_dpy[0]
        try:
            d = display.Display(dpy)
            _gs_dpy[0] = d
            _last_err[0] = None
            _log("opened %s OK (lazy)" % dpy)
            return d
        except Exception as e:
            # Only log the error once per distinct message to avoid spam.
            if _last_err[0] != str(e):
                _last_err[0] = str(e)
                _log("waiting for %s (will retry on input): %r" % (dpy, e))
            return None

    XBTN = {M.MOUSE_BUTTON_LEFT: 1, M.MOUSE_BUTTON_MIDDLE: 2, M.MOUSE_BUTTON_RIGHT: 3}
    W = next(iter(classes.values()))

    _orig_connect = W.connect
    async def connect(self):
        self.xdisplay = _get_dpy()  # may be None if :0 not up yet; send fns retry
        try:
            self._WebRTCInput__keyboard_connect()
        except Exception:
            pass
        self.reset_keyboard()
        try:
            self._WebRTCInput__mouse_connect()
        except Exception:
            pass
        _log("connect: xdisplay -> %s (lazy)" % dpy)

    _orig_key = W.send_x11_keypress
    def send_x11_keypress(self, keysym, down=True):
        # Inject via XTest on the DPAD_INPUT_DISPLAY Xwayland. Do NOT fall back
        # to the original pynput path: pynput's X keyboard backend touches RANDR
        # modes (BadRRModeError) on rootless Xwayland and fails noisily.
        d = _get_dpy() or getattr(self, "xdisplay", None)
        if d is None:
            return  # :0 not up yet; drop the event (retry on the next one)
        try:
            kc = d.keysym_to_keycode(keysym)
            if kc:
                xtest.fake_input(d, X.KeyPress if down else X.KeyRelease, detail=kc)
                d.sync()
                if dbg:
                    _log("key keysym=%s kc=%s down=%s OK" % (keysym, kc, down))
                return
            if dbg:
                _log("key keysym=%s -> no keycode (dropped)" % keysym)
        except Exception as e:
            # The display may have died (sway restarted) -> drop + reopen next time.
            _gs_dpy[0] = None
            if dbg:
                _log("key XTest FAILED keysym=%s %r (dropped)" % (keysym, e))

    _orig_mouse = W.send_mouse
    def send_mouse(self, action, data):
        d = _get_dpy() or getattr(self, "xdisplay", None)
        if d is None:
            return  # :0 not up yet; drop the event (retry on the next one)
        try:
            if action == M.MOUSE_POSITION:
                x, y = data
                xtest.fake_input(d, X.MotionNotify, detail=False, root=d.screen().root, x=x, y=y)
                d.sync()
            elif action == M.MOUSE_MOVE:
                x, y = data
                xtest.fake_input(d, X.MotionNotify, detail=True, root=X.NONE, x=x, y=y)
                d.sync()
            # Selkies v1.6.2 scroll constants are INVERTED relative to the physical
            # wheel, so the button numbers here look "backwards" — do NOT swap them.
            # The web client (gst-web/input.js _mouseWheel) sets button bit 4 for
            # deltaY<0 (wheel UP) and bit 3 (default) for deltaY>0 (wheel DOWN).
            # The server (webrtc_input.send_x11_mouse) maps bit 3 -> MOUSE_SCROLL_UP
            # and bit 4 -> MOUSE_SCROLL_DOWN. So MOUSE_SCROLL_UP is actually sent on
            # a wheel-DOWN and MOUSE_SCROLL_DOWN on a wheel-UP. Stock Selkies cancels
            # this with pynput.mouse.scroll(0,-1) for UP / scroll(0,1) for DOWN
            # (pynput's dy sign is itself flipped), but XTest button numbers are
            # literal: X button 4 = scroll UP, button 5 = scroll DOWN. To get
            # wheel-UP -> screen-UP we must inject button 4 for MOUSE_SCROLL_DOWN
            # (wheel-UP) and button 5 for MOUSE_SCROLL_UP (wheel-DOWN). Swapping
            # these back to 4/5 re-reverses scrolling (the original bug).
            elif action == M.MOUSE_SCROLL_UP:
                # sent on wheel-DOWN -> inject X button 5 (screen-DOWN)
                xtest.fake_input(d, X.ButtonPress, detail=5); xtest.fake_input(d, X.ButtonRelease, detail=5); d.sync()
            elif action == M.MOUSE_SCROLL_DOWN:
                # sent on wheel-UP -> inject X button 4 (screen-UP)
                xtest.fake_input(d, X.ButtonPress, detail=4); xtest.fake_input(d, X.ButtonRelease, detail=4); d.sync()
            elif action == M.MOUSE_BUTTON:
                btn_action, btn_enum = data
                xb = XBTN.get(btn_enum, 1)
                etype = X.ButtonPress if btn_action == M.MOUSE_BUTTON_PRESS else X.ButtonRelease
                xtest.fake_input(d, etype, detail=xb); d.sync()
            else:
                _orig_mouse(self, action, data)
        except Exception:
            _gs_dpy[0] = None  # display may have died -> reopen next time
            try: _orig_mouse(self, action, data)
            except Exception: pass

    _orig_on_message = W.on_message
    def on_message(self, msg):
        try:
            _log("on_message head=%s" % msg.split(",", 1)[0])
        except Exception:
            pass
        return _orig_on_message(self, msg)

    # --- start_cursor_monitor guard (2026-08-11, wayland-display path) --------
    # selkies' own start_cursor_monitor runs at startup (in a background thread
    # via run_in_executor) + dereferences self.xdisplay.has_extension('XFIXES').
    # On the wayland-display path selkies starts BEFORE sway's Xwayland :0 is up,
    # so self.xdisplay is None (the lazy _get_dpy returns None until :0 appears)
    # -> AttributeError: 'NoneType' object has no attribute 'has_extension' (a
    # logged thread exception that does NOT kill selkies, but leaves the server-
    # side cursor monitor dead on the wayland path). Wait for :0 to appear
    # (bounded, so a no-peer session doesn't block the thread forever), then run
    # the real cursor monitor. Mirrors the send_* lazy-retry pattern. The gamescope
    # path (:0 already up at selkies start) resolves immediately -> no change.
    _orig_cursor_monitor = W.start_cursor_monitor
    def start_cursor_monitor(self):
        for _ in range(180):  # up to ~3 min
            d = _get_dpy() or getattr(self, "xdisplay", None)
            if d is not None:
                self.xdisplay = d
                break
            time.sleep(1)
        if getattr(self, "xdisplay", None) is None:
            _log("start_cursor_monitor: %s never came up in 3 min - skipping cursor monitor" % dpy)
            return
        _log("start_cursor_monitor: %s up - starting cursor monitor" % dpy)
        return _orig_cursor_monitor(self)

    for cls in classes.values():
        cls.connect = connect
        cls.send_x11_keypress = send_x11_keypress
        cls.send_mouse = send_mouse
        cls.on_message = on_message
        cls.start_cursor_monitor = start_cursor_monitor

    # Try an initial open (succeeds on the gamescope path where :0 is already up;
    # no-op on the wayland-display path until sway launches). Either way the
    # overrides are installed + _get_dpy() retries until :0 appears.
    _get_dpy()
    _log("Selkies input -> X display %s (XTest lazy-open, patched %d class(es))" % (dpy, len(classes)))

_patch()