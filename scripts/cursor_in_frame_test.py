#!/usr/bin/env python3
# Definitive test: does gamescope composite the X cursor into its PipeWire frame?
# Sets a 64x64 solid RED cursor on the root window, captures a PipeWire frame,
# counts red pixels. Red present -> gamescope composites the cursor (cursor is in
# the video, visible even during browser pointer lock). No red -> gamescope
# headless does NOT composite the cursor (need a different cursor source).
import os, subprocess, time
from Xlib import X, display
from Xlib.xobject.drawable import Pixmap

d = display.Display(os.environ.get("DPAD_INPUT_DISPLAY", ":0"))
screen = d.screen()
root = screen.root
depth = screen.root_depth

# 64x64 solid red pixmap.
w = h = 64
pm = root.create_pixmap(w, h, depth)
gc = pm.create_gc(foreground=0xff0000, background=0xff0000)
pm.poly_fill_rectangle(gc, [(0, 0, w, h)])
mask = root.create_pixmap(w, h, 1)
mgc = mask.create_gc(foreground=1, background=1)
mask.poly_fill_rectangle(mgc, [(0, 0, w, h)])
cursor = root.create_glyph_cursor(pm, mask, 0, 0, 0xff0000, 0x000000)
root.change_attributes(cursor=cursor)
d.flush()
time.sleep(0.5)

# move cursor to a known spot (center)
from Xlib.ext.xtest import fake_input
fake_input(d, X.MotionNotify, x=960, y=540)
d.flush()
time.sleep(0.6)

# capture a PipeWire frame
path = "/tmp/red_cursor_frame.png"
if os.path.exists(path): os.remove(path)
for _ in range(4):
    subprocess.run(["bash","-lc",". /opt/gstreamer/gst-env 2>/dev/null; timeout 8 gst-launch-1.0 "
        "pipewiresrc target-object=gamescope num-buffers=1 always-copy=true ! videoconvert ! "
        "pngenc ! filesink location=%s >/dev/null 2>&1" % path], check=False)
    if os.path.exists(path) and os.path.getsize(path) > 5000:
        break
    time.sleep(0.6)

# restore default cursor
root.change_attributes(cursor=X.NONE)
d.flush()

if not os.path.exists(path):
    print("FAIL: no frame captured"); raise SystemExit(2)

from PIL import Image
im = Image.open(path).convert("RGB")
px = im.load()
# count near-red pixels anywhere (cursor is 64x64 at ~960,540)
redcount = 0
W,H = im.size
for y in range(0, H, 2):
    for x in range(0, W, 2):
        r,g,b = px[x,y]
        if r > 180 and g < 80 and b < 80:
            redcount += 1
print("near-red pixels (2x2 strided):", redcount)
# also check specifically around (960,540)
cx, cy = 960, 540
local_red = 0
for y in range(cy-40, cy+40):
    for x in range(cx-40, cx+40):
        if 0 <= x < W and 0 <= y < H:
            r,g,b = px[x,y]
            if r > 180 and g < 80 and b < 80:
                local_red += 1
print("near-red pixels in 80x80 around (960,540):", local_red)
if redcount > 100 or local_red > 50:
    print("VERDICT: RED cursor visible in the PipeWire frame -> gamescope COMPOSITES the cursor. (Then the no-cursor bug is purely browser pointer-lock hiding CSS cursor — fix = the cursor is already in the video, so --enable_cursors=false should show it; recheck.)")
else:
    print("VERDICT: NO red cursor in the frame -> gamescope headless does NOT composite the X cursor into PipeWire. Fix = draw cursor another way (Selkies overlay + disable pointer lock, OR a GStreamer cursor overlay, OR gamescope cursor flag).")