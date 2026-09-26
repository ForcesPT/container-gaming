"""Validate the transform against the exact pinned client, before JS execution."""
import hashlib
from pathlib import Path
import runpy
import sys
import tempfile
import unittest

SOURCE = Path(sys.argv.pop())
PATCHER = Path(__file__).resolve().parents[1] / 'scripts/dpad-patch-selkies-reconnect'
module = runpy.run_path(str(PATCHER))
NAMES = ('app.js', 'signalling.js', 'webrtc.js')


class ReconnectPatchTests(unittest.TestCase):
    def test_supported_source_and_idempotence(self):
        for name in NAMES:
            with self.subTest(name=name):
                patched = module['transform'](name, (SOURCE / name).read_text())
                self.assertIn(module['MARKER'], patched)
                self.assertEqual(module['transform'](name, patched), patched)

    def test_unknown_source_denies_before_any_write(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for name in NAMES:
                (root / name).write_text((SOURCE / name).read_text())
            (root / 'signalling.js').write_text('unsupported future source')
            before = {name: hashlib.sha256((root / name).read_bytes()).digest() for name in NAMES}
            with self.assertRaises(ValueError):
                module['main'](root)
            self.assertEqual(before, {name: hashlib.sha256((root / name).read_bytes()).digest() for name in NAMES})

    def test_changed_method_body_is_rejected(self):
        for name in ('signalling.js', 'webrtc.js'):
            with self.subTest(name=name):
                source = (SOURCE / name).read_text()
                with self.assertRaises(ValueError):
                    module['transform'](name, source + '\n// changed upstream body\n')


if __name__ == '__main__':
    unittest.main()
