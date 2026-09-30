"""Offline fixture tests; these do not claim official client/game acceptance."""
import hashlib
import importlib.util
import json
import multiprocessing
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('epic_installation', Path(__file__).with_name('dpad_epic_installation.py'))
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


def fixture(root, app='FixtureGame'):
    manifest = b'fixture vendor manifest bytes, not a real Epic manifest'
    binding = {'releaseId': '11111111-1111-4111-8111-111111111111',
               'payloadManifestSha256': 'a' * 64,
               'vendorManifestSha256': hashlib.sha256(manifest).hexdigest(),
               'app': app, 'version': 'fixture-v1', 'executable': 'Game.exe', 'installSize': 7}
    item = {'AppName': app, 'AppVersionString': 'fixture-v1', 'CatalogNamespace': 'fixture_namespace',
            'CatalogItemId': 'fixture_catalog_id', 'DisplayName': 'Fixture game',
            'LaunchExecutable': 'Game.exe', 'LaunchCommand': '', 'InstallationGuid': app + '_guid',
            'InstallSize': 7, 'FormatVersion': 0, 'bIsIncompleteInstall': False,
            'bNeedsValidation': False, 'bCanRunOffline': False,
            'ManifestLocation': r'C:\Original\.egstore', 'ManifestFileName': 'fixture.manifest',
            'AccountId': 'must_not_export', 'AuthToken': 'must_not_export', 'InstallLocation': r'C:\Original'}
    source = root / (app + '-source'); source.mkdir()
    store = source / '.egstore'; store.mkdir()
    item_path = source / 'original.item'; item_path.write_text(json.dumps(item))
    manifest_path = store / 'fixture.manifest'; manifest_path.write_bytes(manifest)
    capsule_root = root / (app + '-capsule')
    digest = m.export_capsule(item_path, manifest_path, binding, capsule_root)
    for path in capsule_root.iterdir(): path.chmod(0o444)
    capsule_root.chmod(0o555)
    game = root / (app + '-game'); game.mkdir(mode=0o700)
    (game / 'Game.exe').write_bytes(b'fixture')
    return binding, capsule_root, digest, game, item_path, manifest_path


def concurrent_register(prefix, record, ready, release, done, results, pause=False):
    try:
        if pause:
            original = m.replace_json

            def delayed_replace(path, data):
                ready.set()
                if not release.wait(5):
                    raise RuntimeError('test registration barrier expired')
                original(path, data)

            m.replace_json = delayed_replace
        binding, capsule, digest, game = record
        results.put(m.register(prefix, game, capsule, binding, digest))
    except Exception as error:
        results.put(type(error).__name__)
    finally:
        done.set()


class OfficialInstallationTests(unittest.TestCase):
    def test_registration_selects_the_launchers_explicit_volume_or_home_prefix(self):
        with patch.dict(m.os.environ, {'HOME': '/private/home'}, clear=True):
            self.assertEqual(m.session_prefix(), Path('/private/home/Faugus/epic-games'))
            m.os.environ['DPAD_VOLUME_MOUNT'] = '/private/volume'
            self.assertEqual(m.session_prefix(), Path('/private/volume/faugus/prefixes/epic-games'))
            m.os.environ['DPAD_FAUGUS_STATE_ROOT'] = '/private/explicit'
            self.assertEqual(m.session_prefix(), Path('/private/explicit/prefixes/epic-games'))

    def test_inventory_conflict_does_not_create_partial_game_records(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); prefix = root / 'prefix'; prefix.mkdir(mode=0o700)
            binding, capsule, digest, game, _, _ = fixture(root)
            inventory = m.private_dir(prefix / 'drive_c/ProgramData/Epic/UnrealEngineLauncher') / 'LauncherInstalled.dat'
            for data in ({'InstallationList': [{'AppName': binding['app'], 'InstallLocation': 'C:\\Existing'}]},
                         {'InstallationList': 'invalid'},
                         {'InstallationList': [], 'Preserve': 'x' * m.MAX_JSON}):
                original = json.dumps(data).encode()
                inventory.write_bytes(original); inventory.chmod(0o600)
                with self.assertRaises(ValueError):
                    m.register(prefix, game, capsule, binding, digest)
                self.assertEqual(inventory.read_bytes(), original)
                self.assertFalse((prefix / 'drive_c/DpadPlay').exists())
                self.assertFalse((prefix / 'drive_c/ProgramData/Epic/EpicGamesLauncher').exists())
                self.assertFalse((game / '.egstore').exists())

    def test_concurrent_games_keep_both_entries_and_existing_inventory(self):
        ctx = multiprocessing.get_context('fork')
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); prefix = root / 'prefix'; prefix.mkdir(mode=0o700)
            records = [fixture(root, app)[:4] for app in ('FirstGame', 'SecondGame')]
            inventory = m.private_dir(prefix / 'drive_c/ProgramData/Epic/UnrealEngineLauncher') / 'LauncherInstalled.dat'
            inventory.write_text(json.dumps({'InstallationList': [{'AppName': 'ExistingGame'}], 'Keep': 'existing metadata'}))
            inventory.chmod(0o600)
            ready, release, first_done, second_done = [ctx.Event() for _ in range(4)]
            results = ctx.Queue()
            first = ctx.Process(target=concurrent_register, args=(prefix, records[0], ready, release, first_done, results, True))
            second = ctx.Process(target=concurrent_register, args=(prefix, records[1], ready, release, second_done, results))
            try:
                first.start()
                self.assertTrue(ready.wait(5), 'first importer did not reach inventory commit')
                second.start()
                self.assertFalse(second_done.wait(0.3), 'second importer bypassed the registration lock')
                release.set()
                self.assertTrue(first_done.wait(5))
                self.assertTrue(second_done.wait(5))
                first.join(2); second.join(2)
                self.assertEqual([results.get(timeout=2) for _ in range(2)], ['official_epic_registered'] * 2)
                data = json.loads(inventory.read_text())
                self.assertEqual([row['AppName'] for row in data['InstallationList']], ['ExistingGame', 'FirstGame', 'SecondGame'])
                self.assertEqual(data['Keep'], 'existing metadata')
            finally:
                release.set()
                for process in (first, second):
                    if process.pid:
                        process.join(2)
                        if process.is_alive():
                            process.terminate(); process.join(2)
                results.close()

    def test_registration_lock_rejects_symlink_and_public_file(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); prefix = root / 'prefix'; prefix.mkdir(mode=0o700)
            binding, capsule, digest, game, _, _ = fixture(root)
            outside = root / 'outside'; outside.write_text('untouched')
            lock = prefix / '.dpad-epic-registration.lock'; lock.symlink_to(outside)
            with self.assertRaises(OSError): m.register(prefix, game, capsule, binding, digest)
            self.assertEqual(outside.read_text(), 'untouched')
            lock.unlink(); lock.touch(mode=0o644); lock.chmod(0o644)
            with self.assertRaises(ValueError): m.register(prefix, game, capsule, binding, digest)
            self.assertFalse((prefix / 'drive_c').exists())

    def test_failed_file_publication_exposes_no_partial_or_overwritten_record(self):
        with tempfile.TemporaryDirectory() as temp:
            target = Path(temp) / 'game.item'
            with patch.object(m.os, 'link', side_effect=OSError('injected publication failure')):
                with self.assertRaises(OSError): m.new_file(target, b'complete record')
            self.assertEqual(list(Path(temp).iterdir()), [])
            target.write_bytes(b'existing record')
            with self.assertRaises(FileExistsError): m.new_file(target, b'replacement')
            self.assertEqual(target.read_bytes(), b'existing record')
            self.assertEqual(list(Path(temp).iterdir()), [target])

    def test_export_removes_account_state_and_preserves_vendor_identity(self):
        with tempfile.TemporaryDirectory() as temp:
            binding, capsule, _, _, _, _ = fixture(Path(temp))
            raw = (capsule / 'installation.json').read_text()
            self.assertNotIn('must_not_export', raw)
            self.assertNotIn('C:\\\\Original', raw)
            record = json.loads(raw)
            self.assertEqual(record['item']['CatalogItemId'], 'fixture_catalog_id')
            self.assertEqual(record['item']['AppName'], binding['app'])
            self.assertFalse(record['item']['bCanRunOffline'])

    def test_two_games_and_replay_preserve_existing_official_inventory(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); prefix = root / 'prefix'; prefix.mkdir(mode=0o700)
            for app in ('FirstGame', 'SecondGame'):
                binding, capsule, digest, game, _, _ = fixture(root, app)
                for _ in range(2):
                    self.assertEqual(m.register(prefix, game, capsule, binding, digest), 'official_epic_registered')
                item = json.loads((prefix / ('drive_c/ProgramData/Epic/EpicGamesLauncher/Data/Manifests/' + app + '_guid.item')).read_text())
                self.assertEqual(item['InstallLocation'], 'C:\\DpadPlay\\Games\\' + app)
                self.assertEqual(item['CatalogItemId'], 'fixture_catalog_id')
                self.assertEqual((prefix / ('drive_c/DpadPlay/Games/' + app)).readlink(), game)
                self.assertEqual((game / 'Game.exe').read_bytes(), b'fixture')
            inventory = json.loads((prefix / 'drive_c/ProgramData/Epic/UnrealEngineLauncher/LauncherInstalled.dat').read_text())
            self.assertEqual([x['AppName'] for x in inventory['InstallationList']], ['FirstGame', 'SecondGame'])

    def test_wrong_game_build_release_digest_and_payload_are_refused(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); binding, capsule, digest, game, _, _ = fixture(root)
            prefix = root / 'prefix'; prefix.mkdir(mode=0o700)
            for key, value in [('app', 'OtherGame'), ('version', 'other'), ('releaseId', '22222222-2222-4222-8222-222222222222'),
                               ('vendorManifestSha256', 'b'*64), ('payloadManifestSha256', 'c'*64), ('installSize', 8)]:
                with self.subTest(key=key), self.assertRaises(ValueError):
                    m.register(prefix, game, capsule, {**binding, key: value}, digest)
            self.assertFalse((prefix / 'drive_c').exists())
            with self.assertRaises(ValueError): m.register(prefix, game, capsule, binding, 'f'*64)

    def test_incomplete_install_and_executable_traversal_are_refused(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); binding, _, _, _, item, manifest = fixture(root)
            original = json.loads(item.read_text())
            for change in ({'bIsIncompleteInstall': True}, {'bNeedsValidation': True}, {'LaunchExecutable': '../Game.exe'}, {'CatalogItemId': ''}):
                item.write_text(json.dumps({**original, **change}))
                with self.assertRaises(ValueError): m.export_capsule(item, manifest, binding, root / 'refused')
                self.assertFalse((root / 'refused').exists())

    def test_symlink_and_changed_vendor_manifest_are_refused(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); binding, capsule, digest, game, _, _ = fixture(root)
            prefix = root / 'prefix'; prefix.mkdir(mode=0o700)
            outside = root / 'outside'; outside.mkdir(mode=0o700)
            (prefix / 'drive_c').symlink_to(outside, target_is_directory=True)
            with self.assertRaises(ValueError): m.register(prefix, game, capsule, binding, digest)
            self.assertEqual(list(outside.iterdir()), [])
            path = capsule / 'vendor.manifest'; path.chmod(0o600); path.write_bytes(b'other'*12); path.chmod(0o444)
            with self.assertRaises(ValueError): m.register(prefix, game, capsule, binding, digest)

    def test_malformed_json_and_unpinned_fields_are_refused(self):
        with tempfile.TemporaryDirectory() as temp:
            binding, capsule, _, _, _, _ = fixture(Path(temp))
            record = json.loads((capsule / 'installation.json').read_text())
            record['item']['AccountId'] = 'untrusted'
            with self.assertRaises(ValueError): m.validate_capsule(record, binding, (capsule / 'vendor.manifest').read_bytes())
            with self.assertRaises(ValueError): json.loads('{"AppName":"a","AppName":"b"}', object_pairs_hook=m.unique)


if __name__ == '__main__': unittest.main()
