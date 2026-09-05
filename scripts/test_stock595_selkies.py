#!/usr/bin/env python3
"""CPU contract tests: never claim actual NVIDIA encoding or EGL acceptance."""
import importlib.util
import os
from pathlib import Path
import subprocess
import tempfile
from types import SimpleNamespace as NS
import unittest

ROOT = Path(__file__).resolve().parents[1]
PROPS = {'preset', 'tune', 'multi-pass', 'rate-control', 'bitrate', 'gop-size',
         'strict-gop', 'aud', 'b-adapt', 'rc-lookahead', 'vbv-buffer-size',
         'b-frames', 'zero-reorder-delay', 'cabac', 'repeat-sequence-header'}

class Element:
    def __init__(self, factory, name=None):
        self.factory, self.name, self.props = factory, name, {}
    def list_properties(self):
        return [NS(name=n) for n in PROPS]
    def set_property(self, name, value):
        if self.factory.startswith('nvcudah264') and name not in PROPS:
            raise ValueError('wrong modern property: ' + name)
        self.props[name] = value
    def get_property(self, name):
        return self.props[name]

class GstFixture:
    def __init__(self, missing=()):
        self.made = []
        def make(factory, name=None):
            if factory in missing:
                return None
            e = Element(factory, name)
            self.made.append(e)
            return e
        self.ElementFactory = NS(make=make, find=lambda n: n not in missing)
    def caps_from_string(self, value):
        return value

class Stock595Tests(unittest.TestCase):
    def module(self):
        path = ROOT / 'scripts/dpad_nvenc.py'
        self.assertTrue(path.exists(), 'modern NVENC runtime helper missing')
        spec = importlib.util.spec_from_file_location('dpad_nvenc', path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def app(self, **changes):
        return NS(**dict(dict(gpu_id=0, fec_video_bitrate=20000, framerate=60,
                             keyframe_distance=-1.0, keyframe_frame_distance=-1,
                             vbv_multiplier_nv=1.5), **changes))

    def test_modern_tail_properties_and_units(self):
        gst = GstFixture()
        tail = self.module().build_modern_tail(gst, self.app())
        self.assertEqual([e.factory for e in tail],
                         ['cudaupload', 'cudaconvert', 'capsfilter', 'nvcudah264enc'])
        self.assertEqual(tail[2].props['caps'], 'video/x-raw(memory:CUDAMemory),format=NV12')
        enc = tail[-1]
        self.assertEqual(enc.name, 'nvenc')
        self.assertEqual(enc.props, dict(preset='p4', tune='ultra-low-latency',
            **{'multi-pass': 'two-pass-quarter', 'rate-control': 'cbr', 'bitrate': 20000,
               'gop-size': -1, 'strict-gop': True, 'aud': False, 'b-adapt': False,
               'rc-lookahead': 0, 'vbv-buffer-size': 501, 'b-frames': 0,
               'zero-reorder-delay': True, 'cabac': True, 'repeat-sequence-header': True}))

    def test_device_and_periodic_keyframes(self):
        gst = GstFixture()
        tail = self.module().build_modern_tail(gst, self.app(gpu_id=2,
            keyframe_distance=2, keyframe_frame_distance=240, framerate=120,
            vbv_multiplier_nv=3, fec_video_bitrate=30000))
        self.assertEqual(tail[-1].factory, 'nvcudah264device2enc')
        self.assertEqual(tail[0].props['cuda-device-id'], 2)
        self.assertEqual(tail[1].props['cuda-device-id'], 2)
        self.assertEqual(tail[-1].props['gop-size'], 240)
        self.assertEqual(tail[-1].props['vbv-buffer-size'], 750)

    def test_missing_factories_fail_without_fallback(self):
        module = self.module()
        for name in ['cudaupload', 'cudaconvert', 'capsfilter', 'nvcudah264enc']:
            with self.subTest(name=name):
                gst = GstFixture([name])
                with self.assertRaisesRegex(RuntimeError, name):
                    module.build_modern_tail(gst, self.app())
                self.assertNotIn('nvh264enc', [e.factory for e in gst.made])

    def test_missing_or_rejected_property_fails(self):
        module = self.module()
        gst = GstFixture()
        original = gst.ElementFactory.make
        def make(factory, name=None):
            e = original(factory, name)
            if factory == 'nvcudah264enc':
                e.list_properties = lambda: [NS(name=n) for n in PROPS - {'tune'}]
            return e
        gst.ElementFactory.make = make
        with self.assertRaisesRegex(RuntimeError, 'tune'):
            module.build_modern_tail(gst, self.app())

    def test_scoped_egl_default_and_opt_in(self):
        module = self.module()
        original = {'__EGL_VENDOR_LIBRARY_FILENAMES': 'untrusted', 'VK_DRIVER_FILES': 'mesa'}
        for mode, expected in [('nvidia', '/run/dpad-nvidia/egl.json'),
            ('multivendor', '/run/dpad-nvidia/egl.json:/usr/share/glvnd/egl_vendor.d/50_mesa.json')]:
            env = module.compositor_environment(mode, original, validate=lambda: None)
            self.assertEqual(env['__EGL_VENDOR_LIBRARY_FILENAMES'], expected)
            self.assertEqual(env['VK_ICD_FILENAMES'], '/run/dpad-nvidia/nvidia_icd.json')
            self.assertEqual(env['VK_DRIVER_FILES'], '/run/dpad-nvidia/nvidia_icd.json')
        self.assertEqual(original['__EGL_VENDOR_LIBRARY_FILENAMES'], 'untrusted')
        with self.assertRaises(ValueError):
            module.compositor_environment('auto', original)
        with self.assertRaises(RuntimeError):
            module.compositor_environment('multivendor', original,
                validate=lambda: (_ for _ in ()).throw(RuntimeError('missing Mesa manifest')))

    def test_entrypoint_preflight_before_start_and_readiness(self):
        text = (ROOT / 'entrypoint.sh').read_text()
        build = text[text.index('    build_selkies_cmd() {'):text.index('    local initial_resolution')]
        self.assertIn('dpad_nvenc.py', build)
        self.assertIn('as_user', build)
        self.assertIn('|| return 1', build)
        self.assertIn('${DPAD_COMPOSITOR_EGL:-nvidia}', text)
        self.assertIn('local enc="${DPAD_ENCODER:-nvh264enc}"', text)
        self.assertEqual(text.count('local egl_set="__EGL_VENDOR_LIBRARY_FILENAMES=/run/dpad-nvidia/egl.json '), 2)
        self.assertIn('selkies_cmd="$(build_selkies_cmd)" || return 1', text)

    def test_patch_wires_all_encoder_routes_and_is_idempotent(self):
        patcher = ROOT / 'scripts/patch_selkies_nvenc.py'
        self.assertTrue(patcher.exists(), 'explicit encoder patch missing')
        fixture = '''class App:
    def build_video_pipeline(self):
        if self.encoder in ["nvh264enc"]:
            cudaupload = Gst.ElementFactory.make("cudaupload")
            nvh264enc = Gst.ElementFactory.make("nvh264enc", "nvenc")
            nvh264enc.set_property("preset", "low-latency-hq")
        else:
            raise ValueError(self.encoder)
        if self.encoder in ["nvh264enc", "x264enc"]:
            codec = "H264"
        if self.encoder in ["nvh264enc"]:
            pipeline_elements = [cudaupload, cudaconvert, cudaconvert_capsfilter, nvh264enc]
    def check_plugins(self):
        supported = ["nvh264enc", "x264enc"]
        assert self.encoder in supported
    def set_video_bitrate(self, bitrate):
        if self.encoder.startswith("nv"):
            self.pipeline.set_property("bitrate", bitrate)
    def set_framerate(self, fps):
        if self.encoder.startswith("nv"):
            self.pipeline.set_property("gop-size", fps * 2)
'''
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / 'app.py'
            target.write_text(fixture)
            r = subprocess.run(['python3', str(patcher), str(target)], capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stderr)
            patched = target.read_text()
            r = subprocess.run(['python3', str(patcher), str(target)], capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertEqual(target.read_text(), patched)
            self.assertIn('nvh264enc.set_property("preset", "low-latency-hq")', patched)
            import sys
            from unittest.mock import patch
            module = self.module()
            gst = GstFixture()
            ns = {'Gst': gst}
            with patch.dict(sys.modules, {'dpad_nvenc': module}):
                exec(patched, ns)
                app = ns['App']()
                app.__dict__.update(vars(self.app()), encoder='nvcudah264enc')
                app.check_plugins()
                app.build_video_pipeline()
                app.pipeline = gst.made[-1]
                app.set_video_bitrate(35000)
                app.set_framerate(120)
            self.assertEqual(app.pipeline.props['bitrate'], 35000)
            self.assertEqual(app.pipeline.props['gop-size'], 240)
            # Unsupported source must fail without modifying it.
            target.write_text('class App: pass\n')
            r = subprocess.run(['python3', str(patcher), str(target)], capture_output=True)
            self.assertNotEqual(r.returncode, 0)
            self.assertEqual(target.read_text(), 'class App: pass\n')

    def test_preflight_requires_eos_frames_and_always_stops(self):
        module = self.module()
        for event, frames, state_fail, passed in [('eos', 3, False, True),
                ('eos', 0, False, False), ('error', 3, False, False),
                (None, 3, False, False), ('eos', 3, True, False)]:
            with self.subTest(event=event, frames=frames, state_fail=state_fail):
                states = []
                sink = NS(connect=lambda signal, callback: [callback(None, None, None) for _ in range(frames)])
                message = NS(type=event, parse_error=lambda: ('encode failed', 'debug')) if event else None
                pipeline = NS(set_state=lambda state: states.append(state) or ('failure' if state_fail else 'ok'),
                    get_bus=lambda: NS(timed_pop_filtered=lambda *args: message))
                gst = NS(State=NS(PLAYING='playing', NULL='null'), SECOND=1,
                    StateChangeReturn=NS(FAILURE='failure'),
                    MessageType=NS(ERROR=1, EOS=2))
                if event:
                    message.type = 2 if event == 'eos' else 1
                if passed:
                    module.verify_pipeline(gst, pipeline, sink, 3)
                else:
                    with self.assertRaises(RuntimeError):
                        module.verify_pipeline(gst, pipeline, sink, 3)
                self.assertEqual(states[-1], 'null')

    def test_patch_rejects_incomplete_marker(self):
        path = ROOT / 'scripts/patch_selkies_nvenc.py'
        spec = importlib.util.spec_from_file_location('patcher', path)
        patcher = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(patcher)
        partial = """class App:
    DPAD_MODERN_NVENC = True
    def build_video_pipeline(self):
        from dpad_nvenc import build_modern_tail
    def check_plugins(self): pass
    def set_framerate(self): pass
    def set_video_bitrate(self): pass
"""
        with self.assertRaises(ValueError):
            patcher.patch(partial)

    def test_runtime_rejects_profile_override(self):
        module = self.module()
        self.assertTrue(hasattr(module, 'check_profile'), 'preflight profile guard missing')
        app = self.app()
        app.encoder = 'nvcudah264enc'
        app.video_bitrate = 20000
        app.video_packetloss_percent = 0.0
        profile = dict(encoder='nvcudah264enc', framerate=60, video_bitrate=20000,
                       gpu_id=0, keyframe_distance=-1.0, video_packetloss_percent=0.0)
        module.check_profile(app, profile)
        for name, value in [('encoder', 'nvh264enc'), ('framerate', 30),
                            ('video_bitrate', 8000), ('gpu_id', 1)]:
            with self.subTest(name=name):
                old = getattr(app, name)
                setattr(app, name, value)
                with self.assertRaises(RuntimeError):
                    module.check_profile(app, profile)
                setattr(app, name, old)

    def test_session_launcher_forwards_scoped_discovery_without_default_change(self):
        text = (ROOT / 'scripts/dpad-launch-session').read_text()
        self.assertIn('-e DPAD_COMPOSITOR_EGL="${DPAD_COMPOSITOR_EGL:-nvidia}"', text)

    def test_differential_recipe_bakes_required_helpers(self):
        recipe = ROOT / 'Dockerfile.stock595'
        self.assertTrue(recipe.exists(), 'differential recipe missing')
        text = recipe.read_text()
        self.assertIn('FROM forcespt/dpadcloud-gaming@sha256:f4bf28e7e17b6717b4c83f2e0f6d598eb0761f72543ffe065be5ff27b7ff26e8', text)
        for name in ['healthcheck.sh', 'dpad-validate-stream-fps', 'dpad-publish-desktop-config',
                     'dpad-waybar', 'dpad-waybar-state-check', 'dpad-labwc-set-output-mode',
                     'launcher-shell', 'launcher-toggle', 'evdev_bridge.py', 'extract-nvrtc.sh',
                     'patch_gst_web_cursors.sh', 'entrypoint.sh', 'install-display-drivers', 'dpad-nvidia-egl',
                     'dpad-resolve-stream-quality', 'patch_live_resolution.py',
                     'dpad_nvenc.py', 'patch_selkies_nvenc.py']:
            self.assertIn(name, text)

if __name__ == '__main__':
    unittest.main(verbosity=2)
