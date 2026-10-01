"""Remove only Galaxy's exact duplicate startup entry from an idle prefix."""
from pathlib import Path
import tempfile
import unittest
from dpad_gog_autostart import disable, RUN_KEY


class GalaxyStartupTests(unittest.TestCase):
    def test_exact_idle_entry_only(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            entry = '"GogGalaxy"="C:\\\\Program Files\\\\GOG Galaxy\\\\GalaxyClient.exe /launchViaAutoStart"\n'
            preserved = '"OtherApp"="keep"\n'
            tail = '\n[Software\\\\PrivateAccount]\n"account-marker"="keep"\n'
            registry = root / 'user.reg'
            registry.write_text(RUN_KEY + ' 123\n' + entry + preserved + tail)
            original = registry.read_bytes()
            self.assertFalse(disable(root, active=lambda p: True))
            self.assertEqual(registry.read_bytes(), original)
            self.assertTrue(disable(root, active=lambda p: False))
            self.assertEqual(registry.read_text(), RUN_KEY + ' 123\n' + preserved + tail)
            self.assertFalse(disable(root, active=lambda p: False))

    def test_same_name_other_command_is_preserved(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            content = RUN_KEY + ' 123\n"GogGalaxy"="custom.exe"\n'
            (root / 'user.reg').write_text(content)
            self.assertFalse(disable(root, active=lambda p: False))
            self.assertEqual((root / 'user.reg').read_text(), content)


if __name__ == '__main__':
    unittest.main()
