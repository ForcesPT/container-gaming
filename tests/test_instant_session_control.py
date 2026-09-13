"""Real Instant cleanup + real controller; Docker/systemd are local shims."""
import json
import subprocess
import sys
import unittest
from pathlib import Path

import test_session_control as control_fixture
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import dpad_instant_lifecycle as lifecycle

RELEASE = '33333333-3333-4333-8333-333333333333'

class InstantControllerIntegration(unittest.TestCase):
    def setUp(self):
        self.fixture = f = control_fixture.SessionControl()
        f.setUp()
        self.addCleanup(f.doCleanups)
        shim = f.path / 'docker'
        shim.write_text(shim.read_text().replace("'com.dpadplay.session':s['session']", "'com.dpadplay.session':s['session'],'dpad.instant.session':s['session'],'dpad.instant.release':'" + RELEASE + "'"))
        f.record()
        path = f.state / (control_fixture.OLD + '.json')
        record = json.loads(path.read_text())
        record.update(container=control_fixture.CID, gatewayUnit='dpad-guest-tls@' + control_fixture.OLD + '.service')
        path.write_text(json.dumps(record))
        def run(args, **kwargs):
            if args[0] == '/usr/local/bin/dpad-launch-session':
                args = [sys.executable, str(control_fixture.SCRIPT), *args[1:]]
            else:
                self.assertEqual(args[0], '/usr/bin/docker')
                args = [str(f.path/'docker'), *(['container', 'ls'] if args[1] == 'ps' else args[1:])]
            return subprocess.run(args, env=f.env, **kwargs)
        self.engine = lifecycle.Engine(run)

    def test_cleanup_stops_gateway_and_persists_cancellation_before_pin_receipt(self):
        f = self.fixture
        lifecycle.cleanup(self.engine, control_fixture.OLD, RELEASE, 0)
        record = json.loads((f.state/(control_fixture.OLD+'.json')).read_text())
        self.assertEqual(record['phase'], 'stopped')
        self.assertEqual(f.native()['removed'], [control_fixture.CID])
        self.assertEqual(f.native()['unit_actions'][0], ['stop', 'dpad-guest-tls@'+control_fixture.OLD+'.service'])
        self.assertNotEqual(f.run_control('launch','0','none','none','password','image',control_fixture.OLD).returncode, 0)
        lifecycle.cleanup(self.engine, control_fixture.OLD, RELEASE, 0)
        self.assertEqual(f.native()['removed'], [control_fixture.CID])

    def test_failed_gateway_stop_retains_container_and_cannot_confirm_cleanup(self):
        f = self.fixture
        f.write_native(unit_stop_refused=True)
        with self.assertRaises(subprocess.CalledProcessError):
            lifecycle.cleanup(self.engine, control_fixture.OLD, RELEASE, 0)
        self.assertTrue(f.native()['present'])
        self.assertEqual(f.native()['removed'], [])
        self.assertEqual(json.loads((f.state/(control_fixture.OLD+'.json')).read_text())['phase'], 'stopping')

    def test_late_cleanup_cannot_touch_replacement(self):
        f = self.fixture
        f.write_native(session=control_fixture.NEW)
        with self.assertRaises(ValueError):
            lifecycle.cleanup(self.engine, control_fixture.OLD, RELEASE, 0)
        self.assertEqual(f.native()['removed'], [])
        self.assertNotIn('unit_actions', f.native())

if __name__ == '__main__':
    unittest.main()
