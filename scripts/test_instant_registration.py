import importlib.util
import pathlib
import tempfile
import unittest

spec = importlib.util.spec_from_file_location('registration', pathlib.Path(__file__).with_name('dpad_instant_register.py'))
assert spec and spec.loader
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)

class RegistrationTests(unittest.TestCase):
    def test_registry_preparation_refuses_redirects_and_unsafe_parents(self):
        import os
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as tmp:
            home = pathlib.Path(tmp) / 'home'; home.mkdir(mode=0o700)
            outside = pathlib.Path(tmp) / 'outside'; outside.mkdir(mode=0o775); outside.chmod(0o775)
            (home / '.config').symlink_to(outside, target_is_directory=True)
            with self.assertRaises((OSError, ValueError)):
                m.prepare_private_registry(home)
            self.assertEqual(outside.stat().st_mode & 0o777, 0o775)
            (home / '.config').unlink()
            m.prepare_private_registry(home)
            target = home / '.config/heroic/legendaryConfig'
            target.chmod(0o777)
            with self.assertRaises(ValueError): m.prepare_private_registry(home)
            self.assertEqual(target.stat().st_mode & 0o777, 0o777)
            target.chmod(0o775)
            with patch.object(m.os, 'geteuid', return_value=os.geteuid()+1):
                with self.assertRaises(ValueError): m.prepare_private_registry(home)
            self.assertEqual(target.stat().st_mode & 0o777, 0o775)

    def test_namespace_handoff_and_real_legendary_inventory(self):
        import json
        import os
        import subprocess
        from unittest.mock import patch
        from test_instant_mount import fixture, m as mount_module
        from legendary.lfs.lgndry import LGDLFS
        with fixture() as (config, image, mount, root, bundle):
            home = root / 'home'; home.mkdir(mode=0o700)
            # Real Heroic creates these two private directories with mode 0775.
            private = home / '.config/heroic/legendaryConfig/legendary'
            private.mkdir(parents=True, mode=0o775)
            private.chmod(0o775); private.parent.chmod(0o775)
            heroic = root / 'heroic'
            heroic.write_text('#!/bin/sh\ntest -f "$HOME/.config/heroic/legendaryConfig/legendary/installed.json" || exit 43\nprintf called > "$HOME/heroic-called"\n')
            heroic.chmod(0o755)
            env = {**os.environ, 'HOME': str(home), 'HEROIC_BIN': str(heroic)}
            env.pop('XDG_CONFIG_HOME', None)
            args = mount_module.compile_mount(config, 0, image, mount, root, now=100)
            for arg in args:
                if arg.startswith('DPAD_INSTANT_'):
                    key, value = arg.split('=', 1); env[key] = value
            launcher = pathlib.Path(__file__).with_name('epic-launch')
            command = ['bwrap', '--unshare-user', '--unshare-net', '--die-with-parent',
                       '--ro-bind', '/', '/', '--proc', '/proc', '--dev', '/dev', '--tmpfs', '/tmp',
                       '--bind', str(root), str(root), '--ro-bind', str(launcher.parent), str(launcher.parent),
                       '--tmpfs', '/opt', '--dir', '/opt/dpad-instant',
                       '--ro-bind', str(bundle / 'files'), '/opt/dpad-instant/game',
                       'bash', str(launcher)]
            result = subprocess.run(command, env=env, capture_output=True, timeout=20)
            self.assertEqual(result.returncode, 0, result.stderr.decode())
            self.assertTrue((home / 'heroic-called').is_file())
            directory = home / '.config/heroic/legendaryConfig/legendary'
            with patch.dict(os.environ, {'LEGENDARY_CONFIG_PATH': str(directory)}):
                inventory = LGDLFS()
                record = inventory.get_installed_game('Curry')
                self.assertIsNotNone(record)
                self.assertEqual(record.install_path, '/opt/dpad-instant/game')
                self.assertEqual(record.version, 'pinned-1')
                self.assertTrue(record.requires_ot)
                self.assertFalse(record.can_run_offline)
                self.assertIsNone(inventory.userdata)
            self.assertEqual((bundle / 'files' / 'Game.exe').read_bytes(), b'fixture')
            self.assertEqual([p.name for p in (bundle / 'files').iterdir()], ['Game.exe'])
            # Missing metadata must not fall back to ordinary install UI.
            (home / 'heroic-called').unlink()
            env.pop('DPAD_INSTANT_METADATA')
            result = subprocess.run(command, env=env, capture_output=True, timeout=20)
            self.assertNotEqual(result.returncode, 0)
            self.assertFalse((home / 'heroic-called').exists())
            # A sealed directory on a writable mount is NOT sufficient.
            env['DPAD_INSTANT_METADATA'] = next(a.split('=', 1)[1] for a in args if a.startswith('DPAD_INSTANT_METADATA='))
            writable = list(command)
            writable[writable.index(str(bundle / 'files')) - 1] = '--bind'
            result = subprocess.run(writable, env=env, capture_output=True, timeout=20)
            self.assertNotEqual(result.returncode, 0)
            self.assertFalse((home / 'heroic-called').exists())
            # No Instant contract means the ordinary Cloud Compute path still runs.
            env.pop('DPAD_INSTANT_APP'); env.pop('DPAD_INSTANT_METADATA')
            result = subprocess.run(writable, env=env, capture_output=True, timeout=20)
            self.assertEqual(result.returncode, 0, result.stderr.decode())
            self.assertTrue((home / 'heroic-called').exists())
            # Register before the desktop shell can open ANY Heroic instance.
            (directory / 'installed.json').unlink()
            app = root / 'desktop-app'; app.mkdir()
            binary = app / 'dpad-launcher'
            binary.write_text('#!/bin/sh\ntest -f "$HOME/.config/heroic/legendaryConfig/legendary/installed.json" || exit 43\n')
            binary.chmod(0o755)
            for arg in args:
                if arg.startswith('DPAD_INSTANT_'):
                    key, value = arg.split('=', 1); env[key] = value
            shell_command = command[:-2] + ['--dir', '/opt/dpadcloud', '--ro-bind', str(app),
                                          '/opt/dpadcloud/launcher', 'bash', str(launcher.with_name('launcher-shell'))]
            result = subprocess.run(shell_command, env=env, capture_output=True, timeout=20)
            self.assertEqual(result.returncode, 0, result.stderr.decode())

    def test_invalid_metadata_and_redirected_state_are_refused(self):
        import json
        with tempfile.TemporaryDirectory() as d:
            root = pathlib.Path(d); home = root / 'home'; home.mkdir(mode=0o700)
            game = root / 'game'; game.mkdir(); (game / 'Game.exe').write_bytes(b'fixture')
            (game / 'Game.exe').chmod(0o444); game.chmod(0o555)
            data = dict(app='Curry', title='Fixture', version='pinned-1', executable='Game.exe',
                        launchParameters='', requiresOwnershipToken=True, installSize=7)
            try:
                for change in [{'executable': '../outside'}, {'executable': '.'}, {'app': '--offline'}, {'app': '../other'}, {'requiresOwnershipToken': 'false'},
                               {'installSize': -1}, {'installSize': True}, {'userToken': 'not-allowed'}, {'version': ''}]:
                    with self.subTest(change=change), self.assertRaises(ValueError):
                        m.register(home, game, {**data, **change})
                m.register(home, game, data)
                registry = home / '.config/heroic/legendaryConfig/legendary/installed.json'
                original = registry.read_bytes()
                with self.assertRaises(ValueError):
                    m.register(home, game, {**data, 'version': 'different'})
                self.assertEqual(registry.read_bytes(), original)
                registry.unlink()
                outside = root / 'outside'; outside.write_text('{}')
                registry.symlink_to(outside)
                with self.assertRaises(ValueError):
                    m.register(home, game, data)
                self.assertEqual(outside.read_text(), '{}')
            finally:
                game.chmod(0o755)

    def test_registration_is_private_idempotent_and_not_entitlement(self):
        import json
        with tempfile.TemporaryDirectory() as d:
            root = pathlib.Path(d)
            home = root / 'home'; home.mkdir(mode=0o700)
            game = root / 'game'; game.mkdir()
            exe = game / 'Game.exe'; exe.write_bytes(b'fixture'); exe.chmod(0o444)
            game.chmod(0o555)
            data = dict(app='Curry', title='Fixture', version='pinned-1', executable='Game.exe',
                        launchParameters='', requiresOwnershipToken=True, installSize=7)
            before = exe.stat()
            try:
                result = m.register(home, game, data)
                self.assertEqual(result, 'registered')
                self.assertEqual(m.register(home, game, data), 'already_registered')
                registry = home / '.config/heroic/legendaryConfig/legendary/installed.json'
                record = json.loads(registry.read_text())['Curry']
                self.assertEqual(record['install_path'], str(game))
                self.assertEqual(record['version'], 'pinned-1')
                self.assertFalse(record['can_run_offline'])
                self.assertTrue(record['requires_ot'])
                self.assertTrue(record['needs_verification'])
                self.assertEqual(registry.stat().st_mode & 0o777, 0o600)
                self.assertFalse((registry.parent / 'user.json').exists())
                self.assertEqual(exe.read_bytes(), b'fixture')
                self.assertEqual(exe.stat().st_mtime_ns, before.st_mtime_ns)
                self.assertEqual(list(game.iterdir()), [exe])
            finally:
                game.chmod(0o755)

if __name__ == '__main__':
    unittest.main()
