import importlib.util
import pathlib
import tempfile
import unittest
import uuid
import hashlib
from contextlib import contextmanager

spec = importlib.util.spec_from_file_location('instant', pathlib.Path(__file__).with_name('dpad_instant_mount.py'))
assert spec and spec.loader
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)

@contextmanager
def fixture():
    with tempfile.TemporaryDirectory() as d:
        root = pathlib.Path(d)
        release = str(uuid.uuid4())
        bundle = root / release
        bundle.mkdir()
        (bundle / 'files').mkdir()
        (bundle / 'files' / 'Game.exe').write_bytes(b'fixture')
        (bundle / 'files' / 'Game.exe').chmod(0o444)
        (bundle / 'manifest.jsonl').write_text('fixture manifest\n')
        (bundle / 'manifest.jsonl').chmod(0o444)
        (bundle / 'files').chmod(0o555)
        bundle.chmod(0o555)
        image = 'forcespt/dpadcloud-gaming@sha256:' + 'a' * 64
        config = dict(sessionId=str(uuid.uuid4()), releaseId=release,
                      manifestSha256=hashlib.sha256(b'fixture manifest\n').hexdigest(),
                      image=image, slot=0, app='Curry', scratchGiB=20, expiresAt=200,
                      metadata=dict(app='Curry', title='Fixture', version='pinned-1', executable='Game.exe',
                                    launchParameters='', requiresOwnershipToken=True, installSize=7))
        mount = dict(target=str(root), source='10.80.0.2:/releases', fstype='nfs4', options='ro,nosuid,nodev,vers=4.1')
        try:
            yield config, image, mount, root, bundle
        finally:
            bundle.chmod(0o755)
            (bundle / 'files').chmod(0o755)

class MountTests(unittest.TestCase):
    def test_dedicated_ephemeral_omits_quota_but_retains_readonly_release(self):
        with fixture() as (config, image, mount, root, bundle):
            config['storageMode'] = 'dedicated-ephemeral'
            args = m.compile_mount(config, 0, image, mount, root, now=100)
            self.assertNotIn('--storage-opt', args)
            self.assertTrue(any('readonly,bind-recursive=disabled' in arg for arg in args))
            with self.assertRaises(ValueError):
                m.compile_mount({**config, 'slot': 1}, 1, image, mount, root, now=100)
            with self.assertRaises(ValueError):
                m.compile_mount({**config, 'storageMode': 'unlimited'}, 0, image, mount, root, now=100)

    def test_dedicated_host_requires_free_disk_and_no_running_peer(self):
        from types import SimpleNamespace
        config = {'scratchGiB': 20}
        usage = lambda path: SimpleNamespace(free=30 * 1024**3)
        m.check_dedicated_storage(config, '/var/lib/docker', [], usage)
        with self.assertRaises(ValueError):
            m.check_dedicated_storage(config, '/var/lib/docker', ['peer'], usage)
        with self.assertRaises(ValueError):
            m.check_dedicated_storage(config, '/var/lib/docker', [], lambda path: SimpleNamespace(free=24 * 1024**3))
        with self.assertRaises(ValueError):
            m.check_dedicated_storage(config, 'relative', [], usage)
        with self.assertRaises(ValueError):
            m.check_dedicated_storage(config, '/var/lib/docker', [], lambda path: SimpleNamespace(free=(4 if path == '/' else 30) * 1024**3))

    def test_pinned_registration_metadata_reaches_container(self):
        import base64
        import json
        with fixture() as (config, image, mount, root, bundle):
            args = m.compile_mount(config, 0, image, mount, root, now=100)
            encoded = next(a.split('=', 1)[1] for a in args if a.startswith('DPAD_INSTANT_METADATA='))
            self.assertEqual(json.loads(base64.b64decode(encoded)), config['metadata'])
            with self.assertRaises(ValueError):
                m.compile_mount({**config, 'metadata': {**config['metadata'], 'app': 'Other'}}, 0, image, mount, root, now=100)

    def test_selected_release_only(self):
        with fixture() as (config, image, mount, root, bundle):
            args = m.compile_mount(config, 0, image, mount, root, now=100)
            self.assertIn('type=bind,src=' + str(bundle / 'files') + ',dst=/opt/dpad-instant/game,readonly,bind-recursive=disabled', args)
            self.assertIn(f"dpad.instant.session={config['sessionId']}", args)
            self.assertIn('size=20g', args)
            self.assertIn('--pull=never', args)
            self.assertNotIn(str(root), args)

    def test_untrusted_mount_or_session_is_rejected(self):
        with fixture() as (config, image, mount, root, bundle):
            changes = [('slot', 1), ('slot', True), ('expiresAt', 99), ('expiresAt', 1000),
                       ('image', 'forcespt/dpadcloud-gaming:latest'), ('scratchGiB', 0),
                       ('scratchGiB', True), ('scratchGiB', 201), ('app', 'Curry\n-e'),
                       ('sessionId', '../escape'), ('unexpected', 'field')]
            for key, value in changes:
                with self.subTest(key=key, value=value):
                    with self.assertRaises(ValueError):
                        m.compile_mount({**config, key: value}, 0, image, mount, root, now=100)
            for key, value in [('source', 'public.example:/releases'), ('fstype', 'ext4'),
                               ('target', '/other'), ('options', 'rw,nosuid,nodev,vers=4.1'),
                               ('options', 'ro,vers=4.1')]:
                with self.subTest(key=key, value=value):
                    with self.assertRaises(ValueError):
                        m.compile_mount(config, 0, image, {**mount, key: value}, root, now=100)

    def test_launcher_refuses_invalid_contract_before_docker(self):
        import subprocess
        import os
        import sys
        with tempfile.TemporaryDirectory() as d:
            root = pathlib.Path(d)
            log = root / 'calls'
            docker = root / 'docker'
            docker.write_text('#!' + sys.executable + '\nimport os,sys,pathlib\np=pathlib.Path(os.environ["CALL_LOG"]);p.open("a").write(sys.argv[1]+"\\n")\nif sys.argv[1]=="logs":print("DPAD_READY fixture")\n')
            docker.chmod(0o755)
            launcher = pathlib.Path(__file__).with_name('dpad-launch-session')
            env = {**os.environ, 'PATH': d + ':' + os.environ['PATH'], 'CALL_LOG': str(log), 'DPAD_INSTANT_CONFIG': '/tmp/untrusted'}
            result = subprocess.run(['bash', str(launcher), 'launch', '0', 'none', 'none', 'fixture-password'], env=env, capture_output=True, timeout=10)
            self.assertNotEqual(result.returncode, 0)
            self.assertFalse(log.exists(), 'validation must precede any Docker call')
            env.pop('DPAD_INSTANT_CONFIG')
            result = subprocess.run(['bash', str(launcher), 'launch', '0', 'none', 'none', 'fixture-password'], env=env, capture_output=True, timeout=10)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn('run', log.read_text())

    def test_real_launcher_consumes_validated_arguments_without_replacing_occupied_slot(self):
        import subprocess
        import os
        import sys
        import time
        import json
        with fixture() as (config, image, mount, root, bundle):
            now = int(time.time())
            config['expiresAt'] = now + 300
            args = m.compile_mount(config, 0, image, mount, root, now=now)
            launcher = root / 'dpad-launch-session'
            launcher.write_bytes(pathlib.Path(__file__).with_name('dpad-launch-session').read_bytes())
            # Root-owned-request/kernel-NFS CLI seam is a fixture here; compile_mount
            # and the maintained Bash launcher above/below are real, not stubbed.
            (root / 'dpad_instant_mount.py').write_text('print(' + repr(str(config['expiresAt']) + '\n' + '\n'.join(args)) + ')\n')
            docker = root / 'docker'
            docker.write_text('#!' + sys.executable + '\nimport os,sys,json,pathlib\np=pathlib.Path(os.environ["CALL_LOG"]);p.open("a").write(json.dumps(sys.argv[1:])+"\\n")\nif sys.argv[1]=="logs":print("DPAD_READY fixture")\nif sys.argv[1]=="ps" and os.environ.get("OCCUPIED"):print("dpad-slot-0")\n')
            docker.chmod(0o755)
            log = root / 'calls'
            env = {**os.environ, 'PATH': str(root) + ':' + os.environ['PATH'], 'CALL_LOG': str(log), 'DPAD_INSTANT_CONFIG': '/fixture-request'}
            command = ['bash', str(launcher), 'launch', '0', 'none', 'none', 'fixture-password', image]
            result = subprocess.run(command, env=env, capture_output=True, timeout=10)
            self.assertEqual(result.returncode, 0, result.stderr)
            calls = [json.loads(line) for line in log.read_text().splitlines()]
            launch = next(row for row in calls if row[0] == 'run')
            for value in args:
                self.assertIn(value, launch)
            self.assertEqual(launch.count('--storage-opt'), 1)
            self.assertEqual(launch[-1], image)
            log.unlink()
            result = subprocess.run(command, env={**env, 'OCCUPIED': '1'}, capture_output=True, timeout=10)
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual([json.loads(line)[0] for line in log.read_text().splitlines()], ['ps'])

    def test_cli_rejects_untrusted_request(self):
        import subprocess
        import sys
        result = subprocess.run([sys.executable, str(pathlib.Path(__file__).with_name('dpad_instant_mount.py')), '/tmp/not-a-trusted-request', '0', 'tag'], capture_output=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(result.stdout, b'')

    def test_writable_release_and_changed_manifest_rejected(self):
        with fixture() as (config, image, mount, root, bundle):
            bundle.chmod(0o755)
            with self.assertRaises(ValueError):
                m.compile_mount(config, 0, image, mount, root, now=100)
            bundle.chmod(0o555)
            with self.assertRaises(ValueError):
                m.compile_mount({**config, 'manifestSha256': 'b' * 64}, 0, image, mount, root, now=100)

if __name__ == '__main__':
    unittest.main()
