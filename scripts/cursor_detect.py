#!/usr/bin/env python3
# Detect whether gamescope's PipeWire output includes the mouse cursor.
# Moves the pointer to two positions via XTest on :0, captures a PipeWire frame
# after each, and diffs them. A small moving cluster = cursor IS in the frame.
# No movement (only the moved region differs by nothing) = cursor NOT composited.
import os, sys, subprocess, time
# The dpad_input .pth fixes the xlib add_extension_event crash on import.
from Xlib import X, XK, display
from Xlib.ext import xfixes
from Xlib.ext.xtest import fake_input

DPLY = os.environ.get("DPAD_INPUT_DISPLAY", ":0")
d = display.Display(DPLY)
root = d.screen().root

def move(x, y):
    fake_input(d, X.MotionNotify, x=x, y=y)
    d.flush()
    time.sleep(0.5)

def grab(path):
    for attempt in range(4):
        if os.path.exists(path): os.remove(path)
        subprocess.run(["bash","-lc",". /opt/gstreamer/gst-env 2>/dev/null; "
            "timeout 8 gst-launch-1.0 pipewiresrc target-object=gamescope num-buffers=1 "
            "always-copy=true ! videoconvert ! pngenc ! filesink location=%s >/dev/null 2>&1" % path],
            check=False)
        if os.path.exists(path) and os.path.getsize(path) > 5000:
            return True
        time.sleep(0.6)
    return os.path.exists(path)

from PIL import Image
move(300, 300)
grab("/tmp/c1.png")
move(900, 900)
grab("/tmp/c2.png")
if not (os.path.exists("/tmp/c1.png") and os.path.exists("/tmp/c2.png")):
    print("FAIL: could not grab both frames"); sys.exit(2)
a = Image.open("/tmp/c1.png").convert("RGB")
b = Image.open("/tmp/c2.png").convert("RGB")
if a.size != b.size:
    print("size mismatch", a.size, b.size); sys.exit(2)
diffs = []
w, h = a.size
pxa = a.load(); pxb = b.load()
for y in range(0, h, 2):
    for x in range(0, w, 2):
        pa, pb = pxa[x,y], pxb[x,y]
        if abs(pa[0]-pb[0])+abs(pa[1]-pb[1])+abs(pa[2]-pb[2]) > 30:
            diffs.append((x,y))
print("total differing pixels (2x2 strided):", len(diffs))
if len(diffs) == 0:
    print("VERDICT: NO pixel changed between the two cursor positions -> cursor NOT in the PipeWire frame.")
else:
    xs=[p[0] for p in diffs]; ys=[p[1] for p in diffs]
    print("diff bounding box: x[%d..%d] y[%d..%d]" % (min(xs),max(xs),min(ys),max(ys)))
    # cursor is a small cluster; if the diff bbox is small AND near a moved position, cursor is in frame
    bw = max(xs)-min(xs); bh = max(ys)-min(ys)
    print("diff bbox size: %dx%d" % (bw, bh))
    if bw < 80 and bh < 80:
        print("VERDICT: a small cluster moved -> cursor IS in the PipeWire frame (Steam likely hides it in gamepadui).")
    else:
        print("VERDICT: large region changed -> scene moved (not a clean cursor test); re-run when Steam is idle.")