"""Execute the maintained preservation branch with temporary paths; no mounts/root."""
import pathlib
import subprocess
import tempfile
import unittest

SOURCE = pathlib.Path(__file__).with_name('vm-bootstrap.sh')

class StoragePreservation(unittest.TestCase):
    def branch(self, mounted=False, backup=False):
        with tempfile.TemporaryDirectory() as temp:
            root = pathlib.Path(temp)
            store = root / 'docker'
            store.mkdir()
            (store / 'image-evidence').write_text('existing image')
            if backup:
                (root / 'docker.pre-xfs').mkdir()
            text = SOURCE.read_text()
            start = text.index('    if [ -d /var/lib/docker ]')
            end = text.index('    mkdir -p /var/lib/docker', start)
            branch = text[start:end].replace('/var/lib/docker', str(store))
            script = ('err() { printf "%s\\n" "$*" >&2; }; '
                      f'mountpoint() {{ return {0 if mounted else 1}; }}; '
                      'preserve() {\n' + branch + '\n}; preserve')
            result = subprocess.run(['bash', '-c', script], text=True, capture_output=True)
            return result, (root / 'docker.pre-xfs/image-evidence').exists(), (store / 'image-evidence').exists()

    def readiness(self, fstype='ext4', options='rw,pquota', mounted=True, stale=False):
        # Execute only the readiness branch: never format, mount or stop Docker.
        with tempfile.TemporaryDirectory() as temp:
            root = pathlib.Path(temp)
            image = root / 'image'
            fstab = root / 'fstab'
            if stale:
                image.touch()
            fstab.write_text(f'{image} /var/lib/docker xfs loop,pquota 0 0\n' if stale else '')
            text = SOURCE.read_text()
            start = text.index('    local img=', text.index('ensure_docker_xfs_quota()'))
            end = text.index('    command -v mkfs.xfs', start)
            branch = text[start:end].replace('/var/lib/dpad-docker-xfs.img', str(image)).replace('/etc/fstab', str(fstab))
            script = ('log() { :; }; err() { printf "%s\\n" "$*" >&2; }; '
                      f'mountpoint() {{ return {0 if mounted else 1}; }}; '
                      f'findmnt() {{ case "$*" in *FSTYPE*) printf "%s\\n" "{fstype}";; *) printf "%s\\n" "{options}";; esac; }}; '
                      'ready() {\n' + branch + '\nreturn 77; }; ready')
            return subprocess.run(['bash', '-c', script], text=True, capture_output=True)

    def test_dedicated_storage_dispatch_never_calls_quota_setup(self):
        text = SOURCE.read_text()
        start = text.index('ensure_session_storage() {')
        end = text.index('\n}\n', start) + 3
        branch = text[start:end]
        for mode, slots, warm, expected in [('dedicated-ephemeral', '1', '1', 0),
                                           ('dedicated-ephemeral', '2', '1', 1),
                                           ('dedicated-ephemeral', '1', '0', 1),
                                           ('unknown', '1', '1', 1), ('', '1', '1', 77)]:
            with self.subTest(mode=mode, slots=slots, warm=warm):
                script = ('log() { :; }; err() { :; }; ensure_docker_xfs_quota() { return 77; }; '
                          'docker() { printf /var/lib/docker; }; python3() { return 0; }; '
                          + branch + f'\nDPAD_INSTANT_STORAGE={mode!r}; DPAD_MAX_SESSIONS={slots}; DPAD_WARM_VM={warm}; ensure_session_storage')
                result = subprocess.run(['bash', '-c', script], capture_output=True)
                self.assertEqual(result.returncode, expected)
        self.assertIn('    ensure_session_storage   || return 1', text)

    def test_non_xfs_mount_is_not_quota_ready(self):
        result = self.readiness()
        self.assertNotEqual(result.returncode, 0, 'ext4 is not Docker overlay2 XFS quota storage')

    def test_stale_image_and_fstab_are_not_readiness(self):
        result = self.readiness(mounted=False, stale=True)
        self.assertEqual(result.returncode, 1, 'stale mount requires recovery, not success or reformatting')
        self.assertIn('recovery', result.stderr)

    def test_read_only_xfs_is_not_ready(self):
        result = self.readiness(fstype='xfs', options='ro,pquota')
        self.assertEqual(result.returncode, 1, 'read-only Docker storage cannot run sessions')

    def test_quota_accounting_without_enforcement_is_not_ready(self):
        for option in ['pqnoenforce', 'prjnoenforce', 'noquota']:
            with self.subTest(option=option):
                result = self.readiness(fstype='xfs', options='rw,pquota,' + option)
                self.assertEqual(result.returncode, 1, 'quota enforcement is explicitly disabled')

    def test_valid_xfs_mount_is_idempotent(self):
        for option in ['pquota', 'prjquota']:
            self.assertEqual(self.readiness(fstype='xfs', options='rw,' + option).returncode, 0)

    def test_failed_restore_retains_the_backup(self):
        with tempfile.TemporaryDirectory() as temp:
            store = pathlib.Path(temp) / 'docker'
            store.mkdir()
            backup = pathlib.Path(str(store) + '.pre-xfs')
            backup.mkdir()
            (backup / 'image').write_text('keep me')
            text = SOURCE.read_text()
            start = text.index('    if [ -d /var/lib/docker.pre-xfs ]; then')
            end = text.index('\n    # Docker 29+', start)
            branch = text[start:end].replace('/var/lib/docker', str(store))
            result = subprocess.run(['bash', '-c', 'err() { :; }; cp() { return 1; }; restore() {\n' + branch + '\n}; restore'], capture_output=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertTrue((backup / 'image').exists())

    def test_existing_backup_is_not_overwritten_or_nested(self):
        result, preserved, original = self.branch(backup=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertTrue(original)
        self.assertFalse(preserved)

    def test_mounted_store_is_not_renamed(self):
        result, preserved, original = self.branch(mounted=True)
        self.assertTrue(original)
        self.assertFalse(preserved)

    def test_unmounted_existing_image_is_preserved_without_shell_warning(self):
        result, preserved, original = self.branch()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stderr, '')
        self.assertTrue(preserved)
        self.assertFalse(original)

if __name__ == '__main__':
    unittest.main()
