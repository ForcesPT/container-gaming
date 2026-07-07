# dpad_input_patch.py — Stage 3a input router for the gamescope path.
#
# Loaded automatically at Python startup via the companion dpad_input_patch.pth
# in site-packages. When DPAD_INPUT_DISPLAY is set (e.g. ":0" = gamescope's
# headless Xwayland), it monkey-patches selkies_gstreamer.webrtc_input.WebRTCInput
# so that send_x11_keypress() and send_mouse() inject via XTest on DPAD_INPUT_DISPLAY
# instead of the capture display (:2, the Xvfb the gamescope PipeWire frame is
# painted onto). The capture pipeline (ximagesrc on :2) is unaffected — it reads
# DISPLAY directly, not this class. So video keeps streaming from :2 while
# keyboard/mouse reach gamescope -> Steam through its own Xwayland.
#
# Why XTest and not libei: gamescope IS an EIS (libeis) server and exposes an EIS
# socket ($XDG_RUNTIME_DIR/gamescope-*-ei), but the libei CLIENT library is not
# packaged on Ubuntu 24.04 (only libeis is). XTest on gamescope's rootless
# Xwayland works (validated: key/motion/button all accepted on :0) and needs no
# extra native code. Absolute mouse positioning on rootless Xwayland can be
# imperfect; relative motion, buttons, scroll, and keyboard are reliable. If
# absolute mouse proves unusable we can later build libei from source for a
# pointer-only bridge — the toggle here (unset DPAD_INPUT_DISPLAY) reverts to
# the original :2 behavior with no input.
#
# When DPAD_INPUT_DISPLAY is unset, this module does nothing (original behavior).

import os

def _patch():
    dpy = os.environ.get("DPAD_INPUT_DISPLAY", "")
    if not dpy:
        return
    try:
        from Xlib import display, X
        from Xlib.ext import xtest
        from selkies_gstreamer import webrtc_input as w
    except Exception as e:
        print("dpad_input_patch: disabled (%r)" % e)
        return

    W = w.WebRTCInput
    # X button codes (X ButtonPress/ButtonRelease detail): 1=left 2=middle 3=right
    # 4=wheel up 5=wheel down.
    XBTN = {w.MOUSE_BUTTON_LEFT: 1, w.MOUSE_BUTTON_MIDDLE: 2, w.MOUSE_BUTTON_RIGHT: 3}

    def _dpy(self):
        d = getattr(self, "_dpad_in_dpy", None)
        if d is None:
            d = display.Display(dpy)
            self._dpad_in_dpy = d
        return d

    _orig_key = W.send_x11_keypress
    def send_x11_keypress(self, keysym, down=True):
        try:
            d = _dpy(self)
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
    W.send_x11_keypress = send_x11_keypress

    _orig_mouse = W.send_mouse
    def send_mouse(self, action, data):
        try:
            d = _dpy(self)
            if action == w.MOUSE_POSITION:
                x, y = data
                xtest.fake_input(d, X.MotionNotify, detail=False, root=d.screen().root, x=x, y=y)
                d.sync()
            elif action == w.MOUSE_MOVE:
                x, y = data
                # detail=True => relative motion; root=NONE works on rootless Xwayland.
                xtest.fake_input(d, X.MotionNotify, detail=True, root=X.NONE, x=x, y=y)
                d.sync()
            elif action == w.MOUSE_SCROLL_UP:
                xtest.fake_input(d, X.ButtonPress, detail=4)
                xtest.fake_input(d, X.ButtonRelease, detail=4)
                d.sync()
            elif action == w.MOUSE_SCROLL_DOWN:
                xtest.fake_input(d, X.ButtonPress, detail=5)
                xtest.fake_input(d, X.ButtonRelease, detail=5)
                d.sync()
            elif action == w.MOUSE_BUTTON:
                btn_action, btn_enum = data
                xb = XBTN.get(btn_enum, 1)
                etype = X.ButtonPress if btn_action == w.MOUSE_BUTTON_PRESS else X.ButtonRelease
                xtest.fake_input(d, etype, detail=xb)
                d.sync()
            else:
                _orig_mouse(self, action, data)
        except Exception:
            try:
                _orig_mouse(self, action, data)
            except Exception:
                pass
    W.send_mouse = send_mouse

    print("dpad_input_patch: Selkies input -> X display %s (XTest)" % dpy)

_patch()