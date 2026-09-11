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
