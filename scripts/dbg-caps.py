import gi
gi.require_version("Gst", "1.0")
from gi.repository import Gst
Gst.init(None)
c = Gst.caps_from_string("video/x-raw(memory:CUDAMemory)")
print("after from_string:", c.to_string(), flush=True)
c.set_value("width", 1920)
print("after set_value width:", c.to_string(), flush=True)
c.set_value("height", 1080)
c.set_value("framerate", Gst.Fraction(60, 1))
print("after set_value h+framerate:", c.to_string(), flush=True)
# Also test: does set_value on a Caps affect the feature? Try building via structure.
c2 = Gst.caps_from_string("video/x-raw(memory:CUDAMemory),width=1920,height=1080,framerate=60/1")
print("full from_string:", c2.to_string(), flush=True)
