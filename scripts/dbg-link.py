import gi, os, sys
gi.require_version("Gst", "1.0")
gi.require_version("GstWebRTC", "1.0")
from gi.repository import Gst, GstWebRTC
Gst.init(None)
print("Gst version:", Gst.version(), flush=True)

# Check nvh264enc properties
enc = Gst.ElementFactory.make("nvh264enc", "nvenc")
props = [p.name for p in enc.list_properties()]
print("nvh264enc has rate-control:", "rate-control" in props, flush=True)
print("nvh264enc has rc-mode:", "rc-mode" in props, flush=True)

# Now replicate selkies build_video_pipeline for the waylanddisplaysrc + nvh264enc path.
os.environ["DPAD_VIDEO_SRC"] = "waylanddisplaysrc"
gpu_id = 0
framerate = 60

# source branch (waylanddisplaysrc)
src = Gst.ElementFactory.make("waylanddisplaysrc", "x11")
if gpu_id >= 0:
    src.set_property("cuda-device-id", gpu_id)
caps = Gst.caps_from_string("video/x-raw(memory:CUDAMemory)")
caps.set_value("width", 1920)
caps.set_value("height", 1080)
caps.set_value("framerate", Gst.Fraction(framerate, 1))
cf = Gst.ElementFactory.make("capsfilter")
cf.set_property("caps", caps)

# selkies nvh264enc branch: set bitrate + rate-control/rc-mode (the EXACT selkies code)
video_bitrate = 8000
enc.set_property("bitrate", int(video_bitrate * 1000))
print("set bitrate OK", flush=True)
# selkies line 367-370
if Gst.version().major == 1 and 20 < Gst.version().minor <= 24:
    try:
        enc.set_property("rate-control", "cbr")
        print("set rate-control=cbr OK", flush=True)
    except TypeError as e:
        print("set rate-control FAILED:", e, flush=True)
else:
    try:
        enc.set_property("rc-mode", "cbr")
        print("set rc-mode=cbr OK", flush=True)
    except TypeError as e:
        print("set rc-mode FAILED:", e, flush=True)

# h264enc_capsfilter + rtph264pay + capsfilter (selkies lines ~380-400)
h264caps = Gst.caps_from_string("video/x-h264,profile=baseline,stream-format=byte-stream,alignment=au")
hcf = Gst.ElementFactory.make("capsfilter")
hcf.set_property("caps", h264caps)
pay = Gst.ElementFactory.make("rtph264pay", "rtp")
paycaps = Gst.caps_from_string("application/x-rtp,media=video,encoding-name=H264,clock-rate=90000,payload=96")
pcf = Gst.ElementFactory.make("capsfilter")
pcf.set_property("caps", paycaps)

# add all + link with debug (selkies line 1050-1056)
p = Gst.Pipeline.new()
els = [src, cf, enc, hcf, pay, pcf]
for e in els:
    p.add(e)
for i in range(len(els) - 1):
    a, b = els[i], els[i + 1]
    sp = a.get_static_pad("src")
    dp = b.get_static_pad("sink")
    print("DPADLINK %s->%s" % (a.get_name(), b.get_name()), flush=True)
    print("  src.pad_caps=%s" % sp.query_caps(None).to_string()[:100], flush=True)
    print("  sink.pad_caps=%s" % dp.query_caps(None).to_string()[:100], flush=True)
    r = Gst.Element.link(a, b)
    print("  => %s" % r, flush=True)
    if not r:
        print("  LINK FAILED", flush=True)
        break
