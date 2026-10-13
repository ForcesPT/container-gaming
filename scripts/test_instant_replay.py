import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest
spec=importlib.util.spec_from_file_location('replay',Path(__file__).with_name('dpad_instant_replay.py'))
replay=importlib.util.module_from_spec(spec);spec.loader.exec_module(replay)

class ReplayTests(unittest.TestCase):
    def setUp(self):
        temporary=tempfile.TemporaryDirectory();self.addCleanup(temporary.cleanup)
        self.root=Path(temporary.name);self.root.chmod(0o700)
        self.env={'DISPLAY':':0','XDG_RUNTIME_DIR':str(self.root),'PULSE_SERVER':'unix:'+str(self.root)+'/pulse/native',
                  'SYNTHETIC_ACCOUNT_SECRET':'not-allowed','DPAD_EPIC_INSTANT_LAUNCH_URI':'not-allowed'}

    def test_private_environment_contains_only_operational_allowlist(self):
        replay.publish(self.root,self.env)
        data=replay.read(self.root)
        self.assertEqual(set(data),{'DISPLAY','XDG_RUNTIME_DIR','PULSE_SERVER'})
        self.assertNotIn('not-allowed',(self.root/'dpad-instant'/'dpad-instant-desktop.json').read_text())
        self.assertEqual((self.root/'dpad-instant'/'dpad-instant-desktop.json').stat().st_mode&0o777,0o600)

    def test_unknown_fields_missing_display_and_changed_runtime_rejected(self):
        for env in ({'XDG_RUNTIME_DIR':str(self.root)}, {'DISPLAY':'localhost:0','XDG_RUNTIME_DIR':str(self.root)},
                    {'DISPLAY':':0','XDG_RUNTIME_DIR':'/other'}):
            with self.assertRaises(ValueError): replay.validate({'schema':1,'environment':env},self.root)
        with self.assertRaises(ValueError):replay.validate({'schema':1,'environment':{**self.env}},self.root)

    def test_redirect_and_shared_receipts_rejected(self):
        replay.publish(self.root,self.env);path=self.root/'dpad-instant'/'dpad-instant-desktop.json';private=self.root/'private'
        path.rename(private);path.symlink_to(private)
        with self.assertRaises(OSError):replay.read(self.root)
        path.unlink();private.rename(path);path.chmod(0o644)
        with self.assertRaises(ValueError):replay.read(self.root)

    def test_nonprivate_runtime_and_extra_receipt_keys_rejected(self):
        self.root.chmod(0o755)
        with self.assertRaises(ValueError):replay.publish(self.root,self.env)
        self.root.chmod(0o700);replay.publish(self.root,self.env)
        path=self.root/'dpad-instant'/'dpad-instant-desktop.json';v=json.loads(path.read_text());v['uri']='not-allowed';path.write_text(json.dumps(v))
        with self.assertRaises(ValueError):replay.read(self.root)

    def test_production_sticky_runtime_preserves_desktop_environment(self):
        self.root.chmod(0o1777)
        replay.publish(self.root,self.env)
        self.assertEqual(replay.read(self.root)['XDG_RUNTIME_DIR'],str(self.root))
        self.assertEqual(self.root.stat().st_mode&0o7777,0o1777)
        self.assertEqual((self.root/'dpad-instant').stat().st_mode&0o7777,0o700)

    def test_unprotected_runtime_and_shared_private_child_rejected(self):
        self.root.chmod(0o777)
        with self.assertRaises(ValueError):replay.publish(self.root,self.env)
        self.root.chmod(0o1777);(self.root/'dpad-instant').mkdir(mode=0o755)
        with self.assertRaises(ValueError):replay.publish(self.root,self.env)
        self.assertEqual((self.root/'dpad-instant').stat().st_mode&0o777,0o755)

    def test_redirected_state_and_hardlinked_receipt_rejected(self):
        destination=self.root/'other';destination.mkdir(mode=0o700)
        (self.root/'dpad-instant').symlink_to(destination,target_is_directory=True)
        with self.assertRaises(ValueError):replay.publish(self.root,self.env)
        (self.root/'dpad-instant').unlink();replay.publish(self.root,self.env)
        os.link(self.root/'dpad-instant'/'dpad-instant-desktop.json',self.root/'copy')
        with self.assertRaises(ValueError):replay.read(self.root)

if __name__=='__main__':unittest.main()
