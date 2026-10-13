"""Production runtime permissions and real helper CLI, no account/client state."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

HELPER=Path(os.environ.get('DPAD_TEST_REPLAY_HELPER',Path(__file__).with_name('dpad_instant_replay.py')))

class StartupTests(unittest.TestCase):
    def setUp(self):
        temporary=tempfile.TemporaryDirectory();self.addCleanup(temporary.cleanup)
        self.root=Path(temporary.name);self.runtime=self.root/'run'/'user'/str(os.geteuid())
        self.runtime.mkdir(parents=True);self.runtime.chmod(0o1777)
        # Relocate only the fixture runtime; execute the actual helper's CLI.
        self.helper=self.root/'dpad_instant_replay.py'
        self.helper.write_text(HELPER.read_text().replace("Path('/run/user')",'Path('+repr(str(self.root/'run'/'user'))+')'))
        self.env={**os.environ,'DISPLAY':':0','XDG_RUNTIME_DIR':str(self.runtime),
                  'SYNTHETIC_ACCOUNT_SECRET':'must-not-be-exported'}

    def publish(self):
        return subprocess.run(['python3','-I',str(self.helper),'--publish-environment'],env=self.env,capture_output=True,text=True,timeout=5)

    def test_actual_startup_cli_does_not_abort_on_entrypoint_runtime(self):
        result=self.publish();self.assertEqual(result.returncode,0,result.stderr)
        receipt=self.runtime/'dpad-instant'/'dpad-instant-desktop.json'
        self.assertEqual(receipt.stat().st_mode&0o7777,0o600)
        self.assertNotIn('must-not-be-exported',receipt.read_text())
        self.assertEqual(self.runtime.stat().st_mode&0o7777,0o1777)

    def test_actual_replay_cli_restores_environment_to_selected_wrapper(self):
        result=self.publish();self.assertEqual(result.returncode,0,result.stderr)
        wrapper=self.root/'faugus-epic-launch'
        wrapper.write_text('#!/usr/bin/python3\nimport json,os,sys\nprint(json.dumps({"args":sys.argv[1:],"display":os.environ["DISPLAY"],"runtime":os.environ["XDG_RUNTIME_DIR"]}))\n')
        wrapper.chmod(0o755)
        result=subprocess.run(['python3','-I',str(self.helper)],env={**self.env,'DISPLAY':':99'},capture_output=True,text=True,timeout=5)
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertEqual(json.loads(result.stdout),{'args':['--replay'],'display':':0','runtime':str(self.runtime)})

if __name__=='__main__':unittest.main()
