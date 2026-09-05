#!/usr/bin/env python3
"""Explicit GStreamer 1.24 CUDA H.264 path; no automatic encoder fallback.

Imported by patched Selkies and used as a bounded preflight in its runtime env.
The probe validates synthetic hardware video, not compositor/browser readiness.
"""
import argparse
import ctypes
import json
import os
from pathlib import Path
import stat
import sys

NVIDIA_EGL = '/run/dpad-nvidia/egl.json'
NVIDIA_VK = '/run/dpad-nvidia/nvidia_icd.json'
MESA_EGL = '/usr/share/glvnd/egl_vendor.d/50_mesa.json'


def validate_mesa():
    path = Path(MESA_EGL)
    for item in [path, *path.parents]:
        info = item.lstat()
        if info.st_uid != 0 or info.st_mode & 0o022 or stat.S_ISLNK(info.st_mode):
            raise RuntimeError(f'untrusted Mesa discovery path: {item}')
    if not path.is_file() or json.loads(path.read_text()) != {
        'file_format_version': '1.0.0', 'ICD': {'library_path': 'libEGL_mesa.so.0'}
    }:
        raise RuntimeError('unexpected Mesa discovery manifest')


def compositor_environment(mode, environ, validate=validate_mesa):
    if mode not in ('nvidia', 'multivendor'):
        raise ValueError('DPAD_COMPOSITOR_EGL must be nvidia or multivendor')
    env = dict(environ)
    if mode == 'multivendor':
        validate()
    env['__EGL_VENDOR_LIBRARY_FILENAMES'] = NVIDIA_EGL + (':' + MESA_EGL if mode == 'multivendor' else '')
    # VK_DRIVER_FILES supersedes VK_ICD_FILENAMES in newer loaders. Set both.
    env['VK_ICD_FILENAMES'] = env['VK_DRIVER_FILES'] = NVIDIA_VK
    return env


def make(Gst, factory, name=None):
    element = Gst.ElementFactory.make(factory, name)
    if element is None:
        raise RuntimeError(f'required GStreamer factory unavailable: {factory}; check matching host video libraries and regenerate CDI')
    return element


def build_modern_tail(Gst, app):
    upload = make(Gst, 'cudaupload')
    convert = make(Gst, 'cudaconvert')
    if app.gpu_id >= 0:
        upload.set_property('cuda-device-id', app.gpu_id)
        convert.set_property('cuda-device-id', app.gpu_id)
    convert.set_property('qos', True)
    caps = make(Gst, 'capsfilter')
    caps.set_property('caps', Gst.caps_from_string('video/x-raw(memory:CUDAMemory),format=NV12'))
    factory = f'nvcudah264device{app.gpu_id}enc' if app.gpu_id > 0 else 'nvcudah264enc'
    encoder = make(Gst, factory, 'nvenc')
    # 1.24's modern CUDA factory has a different API from legacy nvh264enc.
    properties = {
        'preset': 'p4', 'tune': 'ultra-low-latency', 'multi-pass': 'two-pass-quarter',
        'rate-control': 'cbr', 'bitrate': app.fec_video_bitrate,
        'gop-size': -1 if app.keyframe_distance == -1.0 else app.keyframe_frame_distance,
        'strict-gop': True, 'aud': False, 'b-adapt': False, 'rc-lookahead': 0,
        'vbv-buffer-size': int((app.fec_video_bitrate + app.framerate - 1) // app.framerate * app.vbv_multiplier_nv),
        'b-frames': 0, 'zero-reorder-delay': True, 'cabac': True,
        'repeat-sequence-header': True,
    }
    available = {prop.name for prop in encoder.list_properties()}
    for name, value in properties.items():
        if name not in available:
            raise RuntimeError(f'{factory} lacks required property {name}')
        encoder.set_property(name, value)
        actual = encoder.get_property(name)
        actual = getattr(actual, 'value_nick', actual)
        if actual != value:
            raise RuntimeError(f'{factory} rejected {name}={value}: {actual}')
    return upload, convert, caps, encoder


def verify_pipeline(Gst, pipeline, sink, expected):
    frames = []
    sink.connect('handoff', lambda *_: frames.append(1))
    try:
        if pipeline.set_state(Gst.State.PLAYING) == Gst.StateChangeReturn.FAILURE:
            raise RuntimeError('NVENC preflight failed to enter PLAYING')
        message = pipeline.get_bus().timed_pop_filtered(30 * Gst.SECOND,
            Gst.MessageType.ERROR | Gst.MessageType.EOS)
        if message is None:
            raise RuntimeError('NVENC preflight timed out')
        if message.type == Gst.MessageType.ERROR:
            raise RuntimeError(f'NVENC preflight: {message.parse_error()}')
        if message.type != Gst.MessageType.EOS or len(frames) != expected:
            raise RuntimeError(f'NVENC preflight incomplete: {len(frames)}/{expected} decoded frames')
    finally:
        pipeline.set_state(Gst.State.NULL)


def check_profile(app, profile=None):
    if profile is None:
        profile = json.loads(os.environ.get('DPAD_NVENC_PROFILE', '{}'))
    for name, expected in profile.items():
        if getattr(app, name) != expected:
            raise RuntimeError(f'Selkies {name} differs from preflight profile; refusing override')


def preflight(width, height, fps, bitrate, packetloss):
    # Load through the existing toolkit/compat loader ordering; never prepend raw
    # extracted driver libraries or install/replace anything from this helper.
    for name in ('libcuda.so.1', 'libnvidia-encode.so.1', 'libnvcuvid.so.1'):
        ctypes.CDLL(name)
    import gi
    gi.require_version('Gst', '1.0')
    from gi.repository import Gst
    from selkies_gstreamer.gstwebrtc_app import GSTWebRTCApp
    if not getattr(GSTWebRTCApp, 'DPAD_MODERN_NVENC', False):
        raise RuntimeError('Selkies modern NVENC patch missing; rebuild required')
    Gst.init(None)
    # This also runs Selkies' own plugin/encoder validation before signaling.
    app = GSTWebRTCApp(encoder='nvcudah264enc', gpu_id=0, framerate=fps,
        video_bitrate=bitrate, keyframe_distance=-1.0, video_packetloss_percent=packetloss)
    for factory in ('waylanddisplaysrc', 'rtph264pay', 'webrtcbin'):
        if not Gst.ElementFactory.find(factory):
            raise RuntimeError(f'required GStreamer factory unavailable: {factory}')
    pipeline = Gst.Pipeline.new('dpad-nvenc-preflight')
    source = make(Gst, 'videotestsrc')
    source.set_property('num-buffers', 3)
    raw = make(Gst, 'capsfilter')
    raw.set_property('caps', Gst.caps_from_string(
        f'video/x-raw,format=RGBx,width={width},height={height},framerate={fps}/1'))
    tail = build_modern_tail(Gst, app)
    parser = make(Gst, 'h264parse')
    decoder = make(Gst, 'nvh264dec')
    sink = make(Gst, 'fakesink')
    sink.set_property('sync', False)
    sink.set_property('signal-handoffs', True)
    elements = [source, raw, *tail, parser, decoder, sink]
    for element in elements:
        pipeline.add(element)
    for first, second in zip(elements, elements[1:]):
        if not first.link(second):
            raise RuntimeError(f'NVENC preflight cannot link {first.get_name()} -> {second.get_name()}')
    verify_pipeline(Gst, pipeline, sink, 3)
    print(f'NVENC_PREFLIGHT encoder=nvcudah264enc decoded_frames=3 size={width}x{height} fps={fps} bitrate_kbps={bitrate}', file=sys.stderr)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=['check', 'exec'])
    parser.add_argument('mode', choices=['nvidia', 'multivendor'])
    parser.add_argument('args', nargs=argparse.REMAINDER)
    options = parser.parse_args()
    os.environ.update(compositor_environment(options.mode, os.environ))
    if options.action == 'exec':
        if not options.args:
            raise ValueError('missing command')
        # Selkies reads persisted JSON after CLI parsing. Reject any override
        # that would bypass the explicitly preflighted modern encode profile.
        flags = dict(arg[2:].split('=', 1) for arg in options.args[1:]
                     if arg.startswith('--') and '=' in arg)
        os.environ.pop('DPAD_NVENC_PROFILE', None)
        if flags.get('encoder') == 'nvcudah264enc':
            profile = dict(encoder='nvcudah264enc', gpu_id=0, keyframe_distance=-1.0,
                framerate=int(flags['framerate']), video_bitrate=int(flags['video_bitrate']),
                video_packetloss_percent=float(flags.get('video_packetloss_percent', '0')))
            os.environ['DPAD_NVENC_PROFILE'] = json.dumps(profile)
        os.execvp(options.args[0], options.args)
    if len(options.args) != 6:
        raise ValueError('expected encoder width height fps bitrate packetloss')
    encoder, width, height, fps, bitrate, packetloss = options.args
    if encoder == 'nvcudah264enc':
        width, height, fps, bitrate = map(int, (width, height, fps, bitrate))
        packetloss = float(packetloss)
        if not (320 <= width <= 16384 and 200 <= height <= 16384 and
                fps in (30, 60, 120, 144, 240) and 1000 <= bitrate <= 200000 and
                0 <= packetloss <= 100):
            raise ValueError('invalid modern NVENC preflight profile')
        preflight(width, height, fps, bitrate, packetloss)


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        print(f'Selkies capability preflight failed: {error}', file=sys.stderr)
        sys.exit(1)
