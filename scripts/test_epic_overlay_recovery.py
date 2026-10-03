"""Unsafe overlay resumption must refuse before any FUSE mutation."""
import hashlib
import json
import os
from pathlib import Path
import pwd
import tempfile
import unittest
from unittest.mock import Mock, patch

import dpad_epic_overlay as overlay


class OverlayRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name)
        self.root = self.base / 'epic-cow'; self.root.mkdir(mode=0o700)
        self.merged = self.base / 'official-game'; self.merged.mkdir(mode=0o700)
        user = pwd.getpwnam('dpad')
        for name in ('upper', 'work'):
            path = self.root / name; path.mkdir(mode=0o700)
            os.chown(path, user.pw_uid, user.pw_gid)
        self.binding = {'releaseId': '11111111-1111-4111-8111-111111111111'}
        self.digest = 'a' * 64
        self.seal = self.root / 'binding.json'
        self.seal.write_text(json.dumps({'schema': 1, **self.binding,
            'installationSha256': self.digest,
            'bindingSha256': hashlib.sha256(json.dumps(self.binding, sort_keys=True,
                separators=(',', ':')).encode()).hexdigest()}))
        self.seal.chmod(0o444)
        self.run = Mock(side_effect=AssertionError('refusal invoked FUSE'))
        self.paths = patch.object(overlay, 'Path', side_effect=lambda value:
            self.merged if value == '/opt/dpad-instant/official-game' else Path(value))
        self.paths.start()

    def tearDown(self):
        self.paths.stop()
        self.temp.cleanup()

    def refused(self, binding=None, digest=None):
        with self.assertRaises((ValueError, OSError)):
            overlay.prepare_view(self.root, self.base / 'lower',
                                 binding or self.binding, digest or self.digest, self.run)
        self.run.assert_not_called()

    def test_changed_release_or_capsule_cannot_adopt_write_layer(self):
        self.refused({'releaseId': '22222222-2222-4222-8222-222222222222'})
        self.refused(digest='b' * 64)

    def test_unsealed_or_writable_binding_is_refused(self):
        self.seal.chmod(0o644); self.refused()
        self.seal.unlink(); self.refused()

    def test_redirected_write_directory_is_refused(self):
        upper = self.root / 'upper'; upper.rmdir(); upper.symlink_to(self.merged)
        self.refused()

    def test_write_directory_with_shared_permissions_is_refused(self):
        (self.root / 'upper').chmod(0o777); self.refused()

    def test_root_not_owned_by_service_is_refused(self):
        os.chown(self.root, pwd.getpwnam('dpad').pw_uid, -1); self.refused()

    def test_nonempty_mountpoint_is_preserved_and_refused(self):
        marker = self.merged / 'private'; marker.write_text('do not discard')
        self.refused(); self.assertEqual(marker.read_text(), 'do not discard')

    def test_conflicting_registration_receipt_is_preserved_and_refused(self):
        receipt = self.base / 'epic-overlay.json'
        receipt.write_text('{"releaseId":"other","game":"other"}'); receipt.chmod(0o444)
        self.refused(); self.assertIn('other', receipt.read_text())

    def test_active_mount_is_never_stacked(self):
        with patch.object(Path, 'is_mount', return_value=True): self.refused()


if __name__ == '__main__':
    unittest.main()
