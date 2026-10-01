"""Existing Steam volumes receive the image tool without deleting old files."""
from pathlib import Path
import tempfile
import unittest
from dpad_publish_proton import publish


class ImageRunnerTests(unittest.TestCase):
    def test_old_volume_gets_current_tool_and_preserves_old_runner(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            baked = root / 'image/GE-Proton11-7'
            baked.mkdir(parents=True)
            (baked / 'proton').write_text('#!/bin/sh\nexit 0\n')
            (baked / 'proton').chmod(0o755)
            install = root / 'volume/steam-install'
            tool = install / 'compatibilitytools.d/GE-Proton11-7'
            tool.mkdir(parents=True)
            (tool / 'old-file').write_text('keep')
            (install / 'account-marker').write_text('private')
            publish(install, 'GE-Proton11-7', root / 'image')
            self.assertEqual(tool.resolve(), baked.resolve())
            old = list((install / '.dpad-image-runners').glob('*previous-*'))
            self.assertEqual(len(old), 1)
            self.assertEqual((old[0] / 'old-file').read_text(), 'keep')
            self.assertEqual((install / 'account-marker').read_text(), 'private')
            publish(install, 'GE-Proton11-7', root / 'image')
            self.assertEqual(len(list((install / '.dpad-image-runners').glob('*previous-*'))), 1)

    def test_explicit_other_tool_is_untouched(self):
        with tempfile.TemporaryDirectory() as temp:
            install = Path(temp)
            publish(install, 'custom-tool', install / 'absent-image')
            self.assertEqual(list(install.iterdir()), [])

    def test_traversal_is_refused(self):
        with tempfile.TemporaryDirectory() as temp:
            with self.assertRaisesRegex(ValueError, 'Invalid'):
                publish(Path(temp), '../other')


if __name__ == '__main__':
    unittest.main()
