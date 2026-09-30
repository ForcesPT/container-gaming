#!/usr/bin/env python3
"""Explicit GPU acceptance probe; no installs, pulls, publication or game mounts.

Run on the authorized test GPU only. Success proves a short NVENC encode, not
browser streaming, EGL/compositor readiness, store login, or gameplay.
"""
import argparse
import json
import re
import subprocess
import uuid


def check(image, revision):
    if not re.fullmatch(r'forcespt/dpadcloud-gaming@sha256:[a-f0-9]{64}', image):
        raise ValueError('An immutable repository digest is required')
    if not re.fullmatch(r'[a-f0-9]{40}', revision):
        raise ValueError('A full source revision is required')
    result = subprocess.run(['docker', 'image', 'inspect', image], text=True,
                            capture_output=True, timeout=20, check=True)
    info = json.loads(result.stdout)[0]
    if image not in info.get('RepoDigests', []):
        raise ValueError('Local image repository digest mismatch')
    if (info.get('Config', {}).get('Labels') or {}).get('org.opencontainers.image.revision') != revision:
        raise ValueError('Local image source revision mismatch')
    name = 'dpad-instant-encode-probe-' + uuid.uuid4().hex
    # Use the image's own GStreamer environment, but not its desktop entrypoint.
    script = '''set -e
. /opt/gstreamer/gst-env
python3 -c 'import ctypes; [ctypes.CDLL(x) for x in ("libcuda.so.1", "libnvidia-encode.so.1", "libnvcuvid.so.1", "libEGL.so.1")]'
python3 - <<'PY'
import gi
gi.require_version('Gst', '1.0')
from gi.repository import Gst
Gst.init(None)
# Match Selkies: 1.22/1.24 keep the legacy nvh264enc beside the modern CUDA
# encoder. New drivers reject legacy presets even when NVENC itself works.
version = Gst.version()
factory = 'nvcudah264enc' if version[0] == 1 and 20 < version[1] <= 24 else 'nvh264enc'
settings = ' preset=p4 tune=ultra-low-latency' if version[0] == 1 and version[1] > 22 else ' preset=low-latency-hq'
pipeline = Gst.parse_launch('videotestsrc num-buffers=60 ! '
    'video/x-raw,width=1280,height=720,framerate=30/1 ! videoconvert ! '
    'video/x-raw,format=NV12 ! ' + factory + settings + ' ! h264parse ! fakesink')
try:
    if pipeline.set_state(Gst.State.PLAYING) == Gst.StateChangeReturn.FAILURE:
        raise RuntimeError('Encoder did not enter PLAYING')
    message = pipeline.get_bus().timed_pop_filtered(30 * Gst.SECOND, Gst.MessageType.ERROR | Gst.MessageType.EOS)
    if message is None:
        raise RuntimeError('Encoder produced no completion within 30 seconds')
    if message.type == Gst.MessageType.ERROR:
        error, debug = message.parse_error()
        raise RuntimeError(str(error))
finally:
    pipeline.set_state(Gst.State.NULL)
PY
'''
    try:
        result = subprocess.run([
            'docker', 'run', '--rm', '--name', name, '--pull=never',
            '--network=none', '--runtime=nvidia', '--gpus=all',
            '-e', 'NVIDIA_DRIVER_CAPABILITIES=all',
            '--entrypoint', '/bin/bash', image, '-c', script,
        ], text=True, capture_output=True, timeout=90)
        if result.returncode:
            raise RuntimeError('GPU encoding preflight failed: ' + result.stderr[-2000:])
    finally:
        cleanup = subprocess.run(['docker', 'rm', '-f', name], text=True,
                                 capture_output=True, timeout=20)
        if cleanup.returncode and 'No such container' not in cleanup.stderr:
            raise RuntimeError('Probe cleanup is unconfirmed; inspect ' + name)
    return {'image': image, 'revision': revision, 'nvenc': 'passed',
            'gameplay': 'not_tested', 'browserStreaming': 'not_tested'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('image')
    parser.add_argument('revision')
    args = parser.parse_args()
    try:
        print(json.dumps(check(args.image, args.revision)))
    except (ValueError, RuntimeError, OSError, subprocess.SubprocessError) as error:
        parser.exit(1, f'GPU preflight BLOCKED: {error}\n')


if __name__ == '__main__':
    main()
