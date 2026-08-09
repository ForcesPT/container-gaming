#!/usr/bin/env python3
# patch_live_resolution.py — add the live in-stream Resolution dropdown to the
# Selkies web client + the selkies-gstreamer data-channel handler. Idempotent.
#
# Runtime overlay (run by entrypoint.sh at every container boot, mirroring the
# patch_gst_web_cursors.sh overlay pattern) so the live-resolution feature ships
# WITHOUT a Docker image rebuild + push. Patches three files in-place:
#   1. /opt/gst-web/index.html         — the Resolution <v-select> (UI)
#   2. /opt/gst-web/app.js              — data + the watcher that sends _arg_res
#   3. selkies_gstreamer/webrtc_input.py — the _arg_res handler (write
#      /tmp/dpad_resolution + SIGTERM selkies; the entrypoint health loop
#      relaunches selkies + sway at the new resolution; the browser reconnects)
#
# The compositor caps + sway output mode are driven by /tmp/dpad_resolution,
# read by the entrypoint's build_selkies_cmd() + the sway heredoc (§18.7).
# See container-gaming/docs/WAYLAND-ARCHITECTURE.md §18.7.

import os

def patch_file(path, guard, transform):
    try:
        s = open(path, encoding="utf-8").read()
    except FileNotFoundError:
        print("SKIP %s (not found)" % path)
        return
    if guard(s):
        print("SKIP %s (already patched)" % path)
        return
    new = transform(s)
    if new is None:
        print("FAIL %s (anchor not found)" % path)
        return
    open(path, "w", encoding="utf-8").write(new)
    print("OK %s patched" % path)

# 1) index.html — the Resolution v-select after the Video framerate select.
def patch_index(s):
    anchor = '''                <v-select :items="videoFramerateOptions" label="Video framerate" menu-props="left"
                  v-model="videoFramerate" hint="Framerate selection for host video encoder" persistent-hint>
                </v-select>
              </p>'''
    if anchor not in s:
        return None
    addition = anchor + '''
              <p>
                <v-select :items="videoResolutionOptions" label="Resolution" menu-props="left"
                  v-model="videoResolution" hint="Stream resolution (live switch — reconnects ~6s)" persistent-hint>
                </v-select>
              </p>'''
    return s.replace(anchor, addition, 1)

patch_file("/opt/gst-web/index.html",
           lambda s: "videoResolutionOptions" in s,
           patch_index)

# 2) app.js — data (videoResolution + options) + the watcher (sends _arg_res).
def patch_appjs(s):
    data_anchor = "            videoFramerate: 60,"
    if data_anchor not in s:
        return None
    data_inject = '''            videoResolution: '1920x1080',
            videoResolutionOptions: [
                { text: '720p', value: '1280x720' },
                { text: '1080p', value: '1920x1080' },
                { text: '1440p', value: '2560x1440' },
                { text: '4K', value: '3840x2160' },
            ],
'''
    s = s.replace(data_anchor, data_inject + data_anchor, 1)
    watch_anchor = '''        videoFramerate(newValue) {
            if (newValue === null) return;
            console.log("video framerate changed to " + newValue);
            webrtc.sendDataChannelMessage('_arg_fps,' + newValue);
            this.setIntParam("videoFramerate", newValue);
        },'''
    if watch_anchor not in s:
        return None
    watch_inject = watch_anchor + '''
        videoResolution(newValue) {
            if (newValue === null) return;
            console.log("video resolution changed to " + newValue);
            webrtc.sendDataChannelMessage('_arg_res,' + newValue);
            this.setIntParam("videoResolution", newValue);
        },'''
    return s.replace(watch_anchor, watch_inject, 1)

patch_file("/opt/gst-web/app.js",
           lambda s: "videoResolution(newValue)" in s,
           patch_appjs)

# 3) webrtc_input.py — the _arg_res data-channel handler.
def patch_webrtc_input(s):
    py_anchor = '''        elif toks[0] == "_arg_fps":
            # Set framerate
            fps = int(toks[1])
            logger.info("Setting framerate to: %d" % fps)
            self.on_set_fps(fps)'''
    if py_anchor not in s:
        return None
    py_inject = py_anchor + '''
        elif toks[0] == "_arg_res":
            # DPAD §18.7: live stream resolution change (web dropdown).
            res = toks[1]
            parts = res.split("x")
            if len(parts) == 2 and parts[0].isdigit() and parts[1].isdigit():
                w, h = [int(i) + int(i) % 2 for i in parts]
                res = "%dx%d" % (w, h)
                logger.info("DPAD: live resolution change to %s -- writing /tmp/dpad_resolution + restarting selkies" % res)
                try:
                    with open("/tmp/dpad_resolution", "w") as f:
                        f.write(res)
                except Exception as e:
                    logger.error("failed to write /tmp/dpad_resolution: %s" % e)
                try:
                    import subprocess
                    subprocess.Popen(["swaymsg", "output", "*", "mode", "--custom", res],
                                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                except Exception as e:
                    logger.warning("swaymsg output mode set failed: %s" % e)
                import os as _os, signal as _signal, threading as _threading
                def _selfterm(_delay=0.5):
                    import time; time.sleep(_delay)
                    _os.kill(_os.getpid(), _signal.SIGTERM)
                _threading.Thread(target=_selfterm, daemon=True).start()
            else:
                logger.warning("DPAD: rejecting resolution change, invalid WxH: %s" % res)'''
    return s.replace(py_anchor, py_inject, 1)

# Find the pip-installed webrtc_input.py (selkies_gstreamer 1.6.2).
wi_candidates = [
    "/usr/local/lib/python3.12/dist-packages/selkies_gstreamer/webrtc_input.py",
    "/usr/local/lib/python3.13/dist-packages/selkies_gstreamer/webrtc_input.py",
]
import glob
wi_candidates += glob.glob("/usr/local/lib/python*/dist-packages/selkies_gstreamer/webrtc_input.py")
for c in dict.fromkeys(wi_candidates):
    patch_file(c, lambda s: 'toks[0] == "_arg_res"' in s, patch_webrtc_input)

print("patch_live_resolution done")
