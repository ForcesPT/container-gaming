#!/usr/bin/env python3
# dbg-patch-link.py — patch the selkies link loop to print the actual pad caps
# + capsfilter caps at each link, so we can see WHY capsfilter0 -> nvenc fails
# in the real selkies context (vs the standalone dbg-link.py which links fine).
import sys
p = sys.argv[1] if len(sys.argv) > 1 else "/usr/local/lib/python3.12/dist-packages/selkies_gstreamer/gstwebrtc_app.py"
s = open(p, encoding="utf-8").read()

# The link loop (selkies' original, post-pipewire-patch):
OLD = (
    '        for i in range(len(pipeline_elements) - 1):\n'
    '            if not Gst.Element.link(pipeline_elements[i], pipeline_elements[i + 1]):\n'
    '                raise GSTWebRTCAppError("Failed to link {} -> {}".format(pipeline_elements[i].get_name(), pipeline_elements[i + 1].get_name()))'
)
NEW = (
    '        for i in range(len(pipeline_elements) - 1):\n'
    '            a, b = pipeline_elements[i], pipeline_elements[i + 1]\n'
    '            try:\n'
    '                a_caps = a.get_property("caps").to_string() if "caps" in [pp.name for pp in a.list_properties()] and a.get_property("caps") is not None else "(no caps prop)"\n'
    '            except Exception as _e:\n'
    '                a_caps = "(err: %s)" % _e\n'
    '            sp = a.get_static_pad("src"); dp = b.get_static_pad("sink")\n'
    '            print("DPADLINK %s -> %s" % (a.get_name(), b.get_name()), flush=True)\n'
    '            print("  a caps prop: %s" % a_caps[:120], flush=True)\n'
    '            print("  a src pad query_caps: %s" % sp.query_caps(None).to_string()[:120], flush=True)\n'
    '            print("  b sink pad query_caps: %s" % dp.query_caps(None).to_string()[:120], flush=True)\n'
    '            r = Gst.Element.link(a, b)\n'
    '            print("  => %s" % r, flush=True)\n'
    '            if not r:\n'
    '                raise GSTWebRTCAppError("Failed to link {} -> {}".format(a.get_name(), b.get_name()))'
)
if "DPADLINK" in s:
    print("already debug-patched"); sys.exit(0)
if OLD not in s:
    print("ERROR: link loop anchor not found"); sys.exit(1)
s = s.replace(OLD, NEW, 1)
import ast; ast.parse(s)
open(p, "w", encoding="utf-8").write(s)
print("debug-patched the link loop in", p)
