"""Local candidate contract tests; no account, installer or GPU needed."""
import json
from pathlib import Path
import tempfile
import unittest
from dpad_faugus_prepare import PREVIOUS_RUNNERS, prepare


class PreparationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.runner = self.root / 'runner'
        self.runner.mkdir()
        self.proton = self.runner / 'proton'
        self.proton.write_text('#!/bin/sh\nexit 0\n')
        self.proton.chmod(0o755)

    def tearDown(self):
        self.temp.cleanup()

    def prep(self, name='a'):
        return prepare(str(self.root / name), str(self.runner), str(self.proton))

    def inventory(self, name='a'):
        return self.root / name / '.local/share/faugus-launcher/games.json'

    def test_accounts_have_separate_prefixes_and_state(self):
        first, second = self.prep(), self.prep('b')
        self.assertNotEqual(first, second)
        self.assertEqual((self.root / 'a' / 'Faugus' / 'epic-games').stat().st_mode & 0o777, 0o700)
        self.assertEqual(json.loads(self.inventory('b').read_text())[0]['playtime'], 0)
        self.assertEqual(self.inventory().stat().st_mode & 0o777, 0o600)

    def test_epic_prefix_must_not_be_group_readable(self):
        self.prep()
        prefix = self.root / 'a' / 'Faugus' / 'epic-games'
        prefix.chmod(0o755)
        with self.assertRaisesRegex(ValueError, 'prefix permissions'):
            self.prep()

    def test_repeated_preparation_preserves_games_and_playtime(self):
        self.prep()
        games = json.loads(self.inventory().read_text())
        games[0]['playtime'] = 42
        games[0]['pre_launch'] = 'unwanted command'
        games.append({'gameid': 'other', 'title': 'Another game'})
        self.inventory().write_text(json.dumps(games))
        self.prep()
        result = json.loads(self.inventory().read_text())
        self.assertEqual(result[0]['playtime'], 42)
        self.assertNotIn('pre_launch', result[0])
        self.assertEqual(result[1], games[1])

    def test_managed_epic_record_restores_updater_bypass(self):
        self.prep()
        games = json.loads(self.inventory().read_text())
        games[0]['game_arguments'] = ''
        self.inventory().write_text(json.dumps(games))
        self.prep()
        self.assertEqual(json.loads(self.inventory().read_text())[0]['game_arguments'], '-SkipBuildPatchPrereq')

    def test_conflicting_managed_record_is_refused(self):
        self.prep()
        games = json.loads(self.inventory().read_text())
        games[0]['prefix'] = '/another-account'
        self.inventory().write_text(json.dumps(games))
        with self.assertRaisesRegex(ValueError, 'conflicting'):
            self.prep()

    def test_previous_pinned_runner_migrates_without_losing_playtime(self):
        self.prep()
        games = json.loads(self.inventory().read_text())
        for previous in PREVIOUS_RUNNERS:
            with self.subTest(previous=previous):
                games[0]['runner'] = previous
                games[0]['playtime'] = 17
                self.inventory().write_text(json.dumps(games))
                self.prep()
                migrated = json.loads(self.inventory().read_text())[0]
                self.assertEqual(migrated['runner'], str(self.runner))
                self.assertEqual(migrated['playtime'], 17)

    def test_inventory_symlink_is_refused_without_changing_target(self):
        self.prep()
        target = self.root / 'target'
        target.write_text('[]')
        self.inventory().unlink()
        self.inventory().symlink_to(target)
        with self.assertRaisesRegex(ValueError, 'untrusted'):
            self.prep()
        self.assertEqual(target.read_text(), '[]')

    def test_missing_pinned_runner_is_refused(self):
        self.proton.unlink()
        with self.assertRaisesRegex(ValueError, 'unavailable'):
            self.prep()

    def test_private_volume_survives_home_replacement(self):
        volume = self.root / 'private-volume'
        first = prepare(str(self.root / 'first-home'), str(self.runner), str(self.proton), str(volume))
        first.parent.mkdir(parents=True)
        first.write_text('installed-client-marker')
        inventory = volume / 'data/faugus-launcher/games.json'
        games = json.loads(inventory.read_text())
        games[0]['playtime'] = 17
        inventory.write_text(json.dumps(games))
        second = prepare(str(self.root / 'replacement-home'), str(self.runner), str(self.proton), str(volume))
        self.assertEqual(first, second)
        self.assertEqual(second.read_text(), 'installed-client-marker')
        self.assertEqual(json.loads(inventory.read_text())[0]['playtime'], 17)

    def test_other_private_volume_has_no_client_state(self):
        first = prepare(str(self.root / 'a'), str(self.runner), str(self.proton), str(self.root / 'volume-a'))
        first.parent.mkdir(parents=True)
        first.write_text('account-a-marker')
        second = prepare(str(self.root / 'b'), str(self.runner), str(self.proton), str(self.root / 'volume-b'))
        self.assertFalse(second.exists())
        self.assertNotEqual(first, second)

    def test_untrusted_volume_is_refused(self):
        volume = self.root / 'unsafe'
        volume.mkdir(mode=0o777)
        volume.chmod(0o777)
        with self.assertRaisesRegex(ValueError, 'untrusted'):
            prepare(str(self.root / 'a'), str(self.runner), str(self.proton), str(volume))


if __name__ == '__main__':
    unittest.main()
