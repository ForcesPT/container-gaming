# dpad_input_patch.py — Stage 3a input router for the gamescope path.
#
# Auto-loaded at Python startup via dpad_input_patch.pth in site-packages.
# When DPAD_INPUT_DISPLAY is set (e.g. ":0" = gamescope's headless Xwayland),
# it makes Selkies' WebRTCInput connect its X display to DPAD_INPUT_DISPLAY
# (gamescope's Xwayland) instead of the capture display (:2), and switches
# send_x11_keypress()/send_mouse() from pynput to XTest on that display — so
# keyboard/mouse reach gamescope -> Steam. Capture (ximagesrc on :2) reads
# DISPLAY directly and is unaffected.
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

    # --- python-xlib 0.33 bug fix -----------------------------------------
    # Display.add_extension_event sets event_classes[code]=evt (a type) for a
    # base event, then for a sub-event does event_classes[code][subcode]=evt on
    # the TYPE -> 'type object does not support item assignment'. This crashes
    # display.Display() during randr.init. Patch it to convert to a dict.
    try:
        from Xlib.protocol import display as _xpd
        if not getattr(_xpd.Display, "_dpad_aee_patched", False):
            def add_extension_event(self, code, evt, subcode=None):
                if subcode is None:
                    self.event_classes[code] = evt
                else:
                    cur = self.event_classes.get(code)
                    if isinstance(cur, dict):
                        cur[subcode] = evt
                    else:
                        self.event_classes[code] = {subcode: evt}
            _xpd.Display.add_extension_event = add_extension_event
            _xpd.Display._dpad_aee_patched = True
            _log("patched Xlib add_extension_event (randr bug fix)")
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

    # Create the :0 display now (after the bug fix) and reuse it for the
    # whole session (a second display would re-trigger the bug class-level).
    try:
        _gs_dpy = display.Display(dpy)
        _log("opened %s OK" % dpy)
    except Exception as e:
        _log("could not open %s: %r" % (dpy, e))
        return

    XBTN = {M.MOUSE_BUTTON_LEFT: 1, M.MOUSE_BUTTON_MIDDLE: 2, M.MOUSE_BUTTON_RIGHT: 3}
    W = next(iter(classes.values()))

    _orig_connect = W.connect
    async def connect(self):
        self.xdisplay = _gs_dpy
        try:
            self._WebRTCInput__keyboard_connect()
        except Exception:
            pass
        self.reset_keyboard()
        try:
            self._WebRTCInput__mouse_connect()
        except Exception:
            pass
        _log("connect: xdisplay -> %s (reused)" % dpy)

    _orig_key = W.send_x11_keypress
    def send_x11_keypress(self, keysym, down=True):
        d = getattr(self, "xdisplay", None) or _gs_dpy
        try:
            kc = d.keysym_to_keycode(keysym)
            if kc:
                xtest.fake_input(d, X.KeyPress if down else X.KeyRelease, detail=kc)
                d.sync()
                return
        except Exception:
            pass
        try:
            _orig_key(self, keysym, down=down)
        except Exception:
            pass

    _orig_mouse = W.send_mouse
    def send_mouse(self, action, data):
        d = getattr(self, "xdisplay", None) or _gs_dpy
        try:
            if action == M.MOUSE_POSITION:
                x, y = data
                xtest.fake_input(d, X.MotionNotify, detail=False, root=d.screen().root, x=x, y=y)
                d.sync()
            elif action == M.MOUSE_MOVE:
                x, y = data
                xtest.fake_input(d, X.MotionNotify, detail=True, root=X.NONE, x=x, y=y)
                d.sync()
            elif action == M.MOUSE_SCROLL_UP:
                xtest.fake_input(d, X.ButtonPress, detail=4); xtest.fake_input(d, X.ButtonRelease, detail=4); d.sync()
            elif action == M.MOUSE_SCROLL_DOWN:
                xtest.fake_input(d, X.ButtonPress, detail=5); xtest.fake_input(d, X.ButtonRelease, detail=5); d.sync()
            elif action == M.MOUSE_BUTTON:
                btn_action, btn_enum = data
                xb = XBTN.get(btn_enum, 1)
                etype = X.ButtonPress if btn_action == M.MOUSE_BUTTON_PRESS else X.ButtonRelease
                xtest.fake_input(d, etype, detail=xb); d.sync()
            else:
                _orig_mouse(self, action, data)
        except Exception:
            try: _orig_mouse(self, action, data)
            except Exception: pass

    _orig_on_message = W.on_message
    def on_message(self, msg):
        try:
            _log("on_message head=%s" % msg.split(",", 1)[0])
        except Exception:
            pass
        return _orig_on_message(self, msg)

    for cls in classes.values():
        cls.connect = connect
        cls.send_x11_keypress = send_x11_keypress
        cls.send_mouse = send_mouse
        cls.on_message = on_message

    _log("Selkies input -> X display %s (XTest, patched %d class(es))" % (dpy, len(classes)))

_patch()