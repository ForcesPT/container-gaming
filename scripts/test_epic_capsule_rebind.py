"""Public record reuse; no account, client UI or network is involved."""
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_epic_installation import fixture, m


class RebindTests(unittest.TestCase):
    def test_new_release_retains_genuine_record_provenance_and_game_identity(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            binding, source, digest, *_ = fixture(root)
            original = (source / 'installation.json').read_bytes()
            target = {**binding, 'releaseId': '22222222-2222-4222-8222-222222222222'}
            out = root / 'rebound'
            result = m.rebind_capsule(source, digest, binding, target, out)
            capsule = json.loads((out / 'installation.json').read_bytes())
            before = json.loads(original)
            self.assertEqual(capsule, {**before, 'releaseId': target['releaseId']})
            self.assertEqual(result, hashlib.sha256((out / 'installation.json').read_bytes()).hexdigest())
            self.assertEqual((out / 'vendor.manifest').read_bytes(), (source / 'vendor.manifest').read_bytes())
            self.assertEqual((source / 'installation.json').read_bytes(), original)
            with self.assertRaises(FileExistsError):
                m.rebind_capsule(source, digest, binding, target, out)

    def test_no_other_binding_field_can_be_changed(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            binding, source, digest, *_ = fixture(root)
            target = {**binding, 'releaseId': '22222222-2222-4222-8222-222222222222'}
            for key in ('payloadManifestSha256', 'vendorManifestSha256', 'app', 'version', 'executable', 'installSize'):
                with self.subTest(key=key), self.assertRaises(ValueError):
                    m.rebind_capsule(source, digest, binding, {**target, key: 'changed'}, root / key)
                self.assertFalse((root / key).exists())
            for bad_target in (binding, {**target, 'token': 'forbidden'}, {**target, 'releaseId': 'latest'}):
                with self.assertRaises(ValueError):
                    m.rebind_capsule(source, digest, binding, bad_target, root / 'bad')
            with self.assertRaises(ValueError):
                m.rebind_capsule(source, 'f' * 64, binding, target, root / 'tampered')


if __name__ == '__main__':
    unittest.main()
