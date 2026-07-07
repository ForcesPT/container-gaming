#!/usr/bin/env python3
# Query the real X cursor on :0 via XFIXES — shape, position, and whether it has
# any non-transparent pixels. Tells us if Steam hides the cursor (empty image)
# vs the cursor is real but the overlay isn't drawing it.
import os, time
from Xlib import X, display
from Xlib.ext import xfixes

d = display.Display(os.environ.get("DPAD_INPUT_DISPLAY", ":0"))
root = d.screen().root
ptr = root.query_pointer()
print("pointer root position: x=%d y=%d  same_screen=%s" % (ptr.root_x, ptr.root_y, ptr.same_screen))

# selkies pattern: d.has_extension / d.xfixes_query_version / d.xfixes_get_cursor_image
if not d.has_extension('XFIXES'):
    print("NO XFIXES extension"); raise SystemExit(1)
v = d.xfixes_query_version()
print("XFIXES version: %s.%s" % (v.major_version, v.minor_version))
img = d.xfixes_get_cursor_image(root)
print("cursor: x=%d y=%d w=%d h=%d xhot=%d yhot=%d serial=%s" % (
    img.x, img.y, img.width, img.height, img.xhot, img.yhot, img.cursor_serial))
s = sum(img.cursor_image)
print("sum(cursor_image) = %d" % s)
if s == 0:
    print("VERDICT: cursor image is EMPTY -> Steam/Big Picture hides the cursor (override=none sent to browser). No overlay can draw nothing.")
else:
    print("VERDICT: cursor image has visible pixels -> cursor IS set; if still not visible, it's an overlay/draw/position bug.")