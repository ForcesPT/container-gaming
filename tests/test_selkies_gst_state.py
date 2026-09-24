"""Exercise the pinned Selkies pipeline state method without GPU hardware."""
import ast
import importlib.util
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
PATCHER = ROOT / 'scripts/dpad-patch-selkies-gst-state.py'


class SelkiesGstStateTest(unittest.TestCase):
    def test_both_image_builds_apply_patch(self):
        for name in ('Dockerfile', 'Dockerfile.listener-health'):
            dockerfile = (ROOT / name).read_text()
            self.assertIn('scripts/dpad-patch-selkies-gst-state.py /opt/dpadcloud/dpad-patch-selkies-gst-state.py', dockerfile)
            self.assertIn('RUN python3 /opt/dpadcloud/dpad-patch-selkies-gst-state.py', dockerfile)

    def test_patch_requires_exact_source_and_is_idempotent(self):
        old = '''        if res != Gst.StateChangeReturn.SUCCESS:
            raise GSTWebRTCAppError(
                "Failed to transition pipeline to PLAYING: %s" % res)'''
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'gstwebrtc_app.py'
            path.write_text('def start():\n    res = None\n    if True:\n' + old + '\n')
            subprocess.run([sys.executable, str(PATCHER), directory], check=True)
            first = path.read_bytes()
            subprocess.run([sys.executable, str(PATCHER), directory], check=True)
            self.assertEqual(path.read_bytes(), first)
            self.assertIn('Gst.StateChangeReturn.ASYNC', first.decode())
            path.write_text('def start():\n    pass\n')
            rejected = subprocess.run([sys.executable, str(PATCHER), directory], capture_output=True)
            self.assertNotEqual(rejected.returncode, 0)

    @unittest.skipUnless(os.environ.get('DPAD_SELKIES_SOURCE'), 'requires installed pinned Selkies source')
    def test_real_start_pipeline_accepts_valid_state_results(self):
        path = os.environ['DPAD_SELKIES_SOURCE']
        if path == 'auto':
            path = str(Path(importlib.util.find_spec('selkies_gstreamer').origin).parent / 'gstwebrtc_app.py')
        source = Path(path).read_text()
        self.assertIn('# DPAD_GST_STATE_V1', source)
        tree = ast.parse(source)
        methods = [node for cls in tree.body if isinstance(cls, ast.ClassDef)
                   for node in cls.body if isinstance(node, ast.FunctionDef) and node.name == 'start_pipeline']
        self.assertEqual(len(methods), 1)
        method = methods[0]
        method.decorator_list = []

        class State:
            PLAYING = 'playing'

        class Return:
            SUCCESS = 'success'
            ASYNC = 'async'
            NO_PREROLL = 'no-preroll'
            FAILURE = 'failure'

        class Gst:
            class Pipeline:
                result = None

                @classmethod
                def new(cls):
                    return cls()

                def set_state(self, state):
                    assert state == 'playing'
                    return self.result
        Gst.State = State
        Gst.StateChangeReturn = Return

        class App:
            def build_webrtcbin_pipeline(self, audio_only):
                pass

            def build_audio_pipeline(self):
                pass

        namespace = {'Gst': Gst, 'GSTWebRTCAppError': RuntimeError,
                     'logger': type('Logger', (), {'info': staticmethod(lambda *_: None)})()}
        exec(compile(ast.Module(body=[method], type_ignores=[]), '<pinned Selkies start_pipeline>', 'exec'), namespace)
        App.start_pipeline = namespace['start_pipeline']
        for result in (Return.SUCCESS, Return.ASYNC, Return.NO_PREROLL):
            Gst.Pipeline.result = result
            App().start_pipeline(audio_only=True)
        Gst.Pipeline.result = Return.FAILURE
        with self.assertRaisesRegex(RuntimeError, 'Failed to transition pipeline to PLAYING'):
            App().start_pipeline(audio_only=True)


if __name__ == '__main__':
    unittest.main()
