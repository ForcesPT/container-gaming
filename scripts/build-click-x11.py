#!/usr/bin/env python3
"""Click one deterministic build-time installer control on disposable Xvfb."""
import argparse
import time

from Xlib import X, display
from Xlib.ext import xtest


def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument("--display", default=":9")
    p.add_argument("--title-part", action="append", required=True)
    p.add_argument("--timeout", type=int, default=120)
    p.add_argument("--x-fraction", type=float, default=0.5)
    p.add_argument("--y-from-bottom", type=int, default=49)
    return p.parse_args()


def main():
    args = parse_args()
    if not 0.0 <= args.x_fraction <= 1.0 or args.y_from_bottom < 0:
        raise SystemExit("invalid click geometry")
    wanted = [part.casefold() for part in args.title_part]
    dpy = display.Display(args.display)
    root = dpy.screen().root
    deadline = time.monotonic() + args.timeout
    while time.monotonic() < deadline:
        for window in root.query_tree().children:
            try:
                title = (window.get_wm_name() or "").casefold()
                if not all(part in title for part in wanted):
                    continue
                geometry = window.get_geometry()
                translated = window.translate_coords(root, 0, 0)
                # python-xlib reports root translation with the source offset
                # negated for this Xvfb/Wine setup (verified against pixels).
                x = -translated.x + round(geometry.width * args.x_fraction)
                y = -translated.y + geometry.height - args.y_from_bottom
                root_geometry = root.get_geometry()
                if not (0 <= x < root_geometry.width and 0 <= y < root_geometry.height):
                    raise SystemExit(f"refusing out-of-bounds click {x},{y}")
                root.warp_pointer(x, y)
                dpy.sync()
                pointer = root.query_pointer()
                if (pointer.root_x, pointer.root_y) != (x, y):
                    raise SystemExit(
                        f"pointer warp verification failed: {pointer.root_x},{pointer.root_y} != {x},{y}"
                    )
                time.sleep(0.10)
                xtest.fake_input(dpy, X.ButtonPress, 1)
                dpy.sync()
                time.sleep(0.15)
                xtest.fake_input(dpy, X.ButtonRelease, 1)
                dpy.sync()
                print(f"BUILD_INSTALLER_CONTROL_CLICKED title={title!r} x={x} y={y}")
                return
            except (AttributeError, TypeError):
                continue
        time.sleep(1)
    raise SystemExit("matching installer window not found before deadline")


if __name__ == "__main__":
    main()
