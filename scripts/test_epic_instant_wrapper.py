"""Real shell/lock/inventory integration with disposable offline client doubles."""
import json
import os
from pathlib import Path
import shlex
import subprocess
import tempfile
import time
import unittest

URI = 'com.epicgames.launcher://apps/Sandbox%3ACatalog%3AArtifact?action=launch&silent=true'


class WrapperTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(); self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name); self.home = self.root / 'home'
        self.events = self.root / 'events'; self.hold = self.root / 'hold'
        script = Path(__file__).with_name('faugus-epic-launch').read_text()
        script = script.replace('/opt/dpadcloud/dpad_publish_proton.py', str(self.root / 'publish.py'))
        script = script.replace('/usr/bin/umu-run', str(self.root / 'umu-run'))
        self.wrapper = self.root / 'faugus-epic-launch'; self.wrapper.write_text(script)
        (self.root / 'publish.py').write_text('pass\n')
        (self.root / 'dpad_faugus_prepare.py').write_text(Path(__file__).with_name('dpad_faugus_prepare.py').read_text())
        (self.root / 'dpad_epic_installation.py').write_text(
            'import os\nassert os.environ.get("REFUSE_URI") != "1"\nprint(' + repr(URI) + ')\n')
        (self.root / 'dpad_epic_resume.py').write_text('import os\nassert os.environ.get("REFUSE_RESUME") != "1"\n')
        (self.root / 'dpad_epic_updater_failed.py').write_text('raise SystemExit(1)\n')
        fake = '''#!/usr/bin/python3
import os, json, time
from pathlib import Path
root = Path(os.environ['TEST_ROOT'])
if Path(__file__).name == 'umu-run':
    event = ['restore']
else:
    inventory = Path(os.environ['HOME']) / '.local/share/faugus-launcher/games.json'
    event = ['start', json.loads(inventory.read_text())[0]['game_arguments']]
with open(root/'events', 'a') as stream: stream.write(json.dumps(event) + '\\n')
deadline = time.monotonic() + 10
while Path(__file__).name != 'umu-run' and (root/'hold').exists() and time.monotonic() < deadline:
    time.sleep(.02)
'''
        for name in ('faugus-launcher', 'umu-run'):
            path = self.root / name; path.write_text(fake); path.chmod(0o755)
        runner = self.home / '.steam/debian-installation/compatibilitytools.d/GE-Proton11-7'
        runner.mkdir(parents=True); (runner / 'proton').write_text('#!/bin/sh\n'); (runner / 'proton').chmod(0o755)
        exe = self.home / 'Faugus/epic-games/drive_c/Program Files/Epic Games/Launcher/Portal/Binaries/Win64/EpicGamesLauncher.exe'
        exe.parent.mkdir(parents=True); (self.home / 'Faugus/epic-games').chmod(0o700); exe.write_bytes(b'client-double')
        self.env = {**os.environ, 'HOME': str(self.home), 'TEST_ROOT': str(self.root),
                    'PATH': str(self.root) + ':' + os.environ['PATH']}
        for key in ('DPAD_VOLUME_MOUNT', 'DPAD_FAUGUS_STATE_ROOT', 'DPAD_EPIC_PROTON_VERSION', 'DPAD_PROTON_VERSION'):
            self.env.pop(key, None)

    def run_mode(self, mode, **env):
        return subprocess.run(['bash', str(self.wrapper), mode], env={**self.env, **env},
                              capture_output=True, text=True, timeout=15)

    def recorded(self):
        return [json.loads(row) for row in self.events.read_text().splitlines()] if self.events.exists() else []

    def test_instant_uri_and_cloud_store_open(self):
        result = self.run_mode('--instant'); self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(shlex.split(self.recorded()[0][1]), ['-SkipBuildPatchPrereq', URI])
        result = self.run_mode('--open', DPAD_EPIC_INSTANT_LAUNCH_URI=URI)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.recorded()[1], ['start', '-SkipBuildPatchPrereq'])

    def test_restore_busy_client_does_not_start_second_controller_or_game(self):
        self.hold.touch()
        owner = subprocess.Popen(['bash', str(self.wrapper), '--instant'], env=self.env,
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            deadline = time.monotonic() + 5
            while not self.events.exists() and time.monotonic() < deadline: time.sleep(.02)
            self.assertTrue(self.events.exists())
            result = self.run_mode('--open'); self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual([event[0] for event in self.recorded()], ['start', 'restore'])
            refused = self.run_mode('--open', REFUSE_RESUME='1')
            self.assertNotEqual(refused.returncode, 0)
            self.assertEqual([event[0] for event in self.recorded()], ['start', 'restore'])
        finally:
            self.hold.unlink(missing_ok=True)
            owner.wait(timeout=15)

    def test_invalid_release_uri_never_opens_client(self):
        result = self.run_mode('--instant', REFUSE_URI='1')
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.recorded(), [])


if __name__ == '__main__': unittest.main()
