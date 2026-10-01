"""Preserve client and per-game settings when changing the fallback runner."""
import tempfile
from pathlib import Path
import unittest
import vdf
from dpad_steam_proton_default import set_default


class SteamDefaultTests(unittest.TestCase):
    def test_preserves_account_and_per_game_choices(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            tool = root / 'compatibilitytools.d/GE-Proton11-7'
            tool.mkdir(parents=True)
            (tool / 'proton').touch()
            (tool / 'compatibilitytool.vdf').write_text(vdf.dumps({
                'compatibilitytools': {'compat_tools': {'GE-Proton11-7-x86_64': {}}}}))
            config = root / 'config'
            config.mkdir(mode=0o700)
            path = config / 'config.vdf'
            old = {'installconfigstore': {'Software': {'Valve': {'Steam': {
                'OtherSetting': 'keep', 'CompatToolMapping': {
                    '0': {'name': 'old'}, '123': {'name': 'custom-tool'}}}}}}}
            path.write_text(vdf.dumps(old))
            set_default(root, 'GE-Proton11-7')
            result = vdf.loads(path.read_text())['installconfigstore']['Software']['Valve']['Steam']
            self.assertEqual(result['OtherSetting'], 'keep')
            self.assertEqual(result['CompatToolMapping']['123'], {'name': 'custom-tool'})
            self.assertEqual(result['CompatToolMapping']['0']['name'], 'GE-Proton11-7-x86_64')
            first = path.read_bytes()
            set_default(root, 'GE-Proton11-7')
            self.assertEqual(first, path.read_bytes())
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)

    def test_missing_tool_does_not_touch_configuration(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            with self.assertRaisesRegex(ValueError, 'unavailable'):
                set_default(root, 'missing')
            self.assertFalse((root / 'config').exists())


if __name__ == '__main__':
    unittest.main()
