#!/usr/bin/env python3
"""Accept valid asynchronous GStreamer pipeline startup in pinned Selkies."""
from pathlib import Path
import sys

MARKER = '# DPAD_GST_STATE_V1'
OLD = '''        if res != Gst.StateChangeReturn.SUCCESS:
            raise GSTWebRTCAppError(
                "Failed to transition pipeline to PLAYING: %s" % res)'''
NEW = '''        # Live sources may return ASYNC or NO_PREROLL while PLAYING settles.
        # The bus loop handles later errors; only an immediate failure rejects startup.
        if res not in (Gst.StateChangeReturn.SUCCESS,
                       Gst.StateChangeReturn.ASYNC,
                       Gst.StateChangeReturn.NO_PREROLL):
            raise GSTWebRTCAppError(
                "Failed to transition pipeline to PLAYING: %s" % res)'''


def main(directory):
    path = Path(directory) / 'gstwebrtc_app.py'
    source = path.read_text()
    if MARKER in source:
        if source.count(MARKER) != 1 or NEW not in source:
            raise ValueError('Selkies state patch marker mismatch')
        return
    if source.count(OLD) != 1:
        raise ValueError('unsupported Selkies pipeline state source')
    patched = MARKER + '\n' + source.replace(OLD, NEW, 1)
    compile(patched, str(path), 'exec')
    path.write_text(patched)


if __name__ == '__main__':
    main(sys.argv[1])
