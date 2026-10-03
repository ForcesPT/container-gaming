"""Disposable-container startup ordering; no real client, account or network."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

if os.environ.get('DPAD_TEST_EPIC_STARTUP') != '1':
    raise SystemExit('disposable-container opt-in required')


class StartupTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.events = self.root / 'events'
        source = Path(__file__).with_name('launcher-shell').read_text()
        self.shell = self.root / 'launcher-shell'
        self.shell.write_text(source)
        prepare = self.root / 'faugus-epic-launch'
        prepare.write_text('''#!/bin/bash
set -eu
if [ "$1" = --instant ] || [ "$1" = --open ]; then
    echo "$1" >> "$EPIC_TEST_EVENTS"
    exit 0
fi
test "$1" = --prepare-only
echo prepare >> "$EPIC_TEST_EVENTS"
test "${EPIC_TEST_PREP_FAIL:-0}" != 1
touch "$EPIC_TEST_READY"
''')
        prepare.chmod(0o755)
        (self.root / 'dpad_epic_installation.py').write_text('''import os, sys
from pathlib import Path
assert Path(os.environ['EPIC_TEST_READY']).is_file(), 'registration ran before client preparation'
assert os.environ.get('EPIC_TEST_REG_FAIL') != '1', 'registration refused'
with open(os.environ['EPIC_TEST_EVENTS'], 'a') as stream: stream.write(sys.argv[1] + '\\n')
''')
        # Only the opt-in, disposable test container's launcher is replaced.
        app = Path('/opt/dpadcloud/launcher/dpad-launcher')
        original, mode = app.read_bytes(), app.stat().st_mode
        self.addCleanup(app.chmod, mode)
        self.addCleanup(app.write_bytes, original)
        app.write_text('#!/bin/bash\necho picker >> "$EPIC_TEST_EVENTS"\n')
        app.chmod(0o755)
        self.env = {**os.environ, 'DPAD_INSTANT_APP': 'Fixture',
                    'DPAD_EPIC_BACKEND': 'faugus', 'DPAD_FAUGUS_INSTANT_TEST': '1',
                    'DPAD_EPIC_INSTALLATION_SHA256': 'a' * 64,
                    'EPIC_TEST_EVENTS': str(self.events),
                    'EPIC_TEST_READY': str(self.root / 'ready')}

    def test_client_preparation_precedes_registration_and_direct_epic(self):
        subprocess.run(['bash', str(self.shell)], env=self.env, check=True, timeout=5)
        self.assertEqual(self.events.read_text().splitlines(), ['prepare', 'register', '--instant'])

    def test_cloud_compute_keeps_store_picker(self):
        env = {key: value for key, value in self.env.items() if not key.startswith('DPAD_INSTANT_')}
        subprocess.run(['bash', str(self.shell)], env=env, check=True, timeout=5)
        self.assertEqual(self.events.read_text().splitlines(), ['picker'])

    def test_failed_registration_never_opens_any_store(self):
        result = subprocess.run(['bash', str(self.shell)],
                                env={**self.env, 'EPIC_TEST_REG_FAIL': '1'}, timeout=5)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.events.read_text().splitlines(), ['prepare'])

    def test_unqualified_instant_never_falls_back_to_picker(self):
        result = subprocess.run(['bash', str(self.shell)],
                                env={**self.env, 'DPAD_EPIC_INSTALLATION_SHA256': ''}, timeout=5)
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(self.events.exists())

    def test_instant_restore_opens_only_epic_without_game_request(self):
        (self.root / 'ready').touch()
        toggle = self.root / 'launcher-toggle'
        toggle.write_text(Path(__file__).with_name('launcher-toggle').read_text())
        subprocess.run(['bash', str(toggle)], env=self.env, check=True, timeout=5)
        self.assertEqual(self.events.read_text().splitlines(), ['launch-uri', '--open'])

    def test_failed_preparation_does_not_register_or_open_picker(self):
        result = subprocess.run(['bash', str(self.shell)],
                                env={**self.env, 'EPIC_TEST_PREP_FAIL': '1'}, timeout=5)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.events.read_text().splitlines(), ['prepare'])


if __name__ == '__main__':
    unittest.main()
