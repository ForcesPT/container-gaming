#!/usr/bin/env python3
"""Run the real bootstrap policy functions with local command fixtures."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class DriverPolicyTests(unittest.TestCase):
    def policy(self, version, packages='', **env):
        source = (ROOT / 'scripts/vm-bootstrap.sh').read_text()
        functions = source[source.index('has_proprietary_580() {'):source.index('# Phase 0a:')]
        with tempfile.TemporaryDirectory() as tmp:
            functions = functions.replace('/tmp/dpad-driver-', tmp + '/driver-')
            script = '''set -uo pipefail
log() { echo "$*"; }
err() { echo "$*" >&2; }
nvidia-smi() { [ -n "$FIXTURE_VERSION" ] || return 1; echo "$FIXTURE_VERSION"; }
dpkg() { printf '%s\\n' "$FIXTURE_PACKAGES"; }
apt-get() { echo "APT $*" >&2; }
''' + functions + '''
install_open_580_and_reboot() { echo SWAP; }
ensure_driver_580
'''
            runtime = {k: v for k, v in os.environ.items() if k not in ('DPAD_DRIVER_POLICY', 'DPAD_SKIP_DRIVER_SWAP')}
            return subprocess.run(['bash', '-c', script], env={**runtime, 'FIXTURE_VERSION': version, 'FIXTURE_PACKAGES': packages, **env}, text=True, capture_output=True)

    def test_host_policy_preserves_595(self):
        result = self.policy('595.58.03', DPAD_DRIVER_POLICY='host')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn('SWAP', result.stdout)
        self.assertNotIn('APT', result.stderr)

    def test_default_matrix(self):
        for version, packages, swap in [
            ('580.159.03', 'ii nvidia-driver-580 580 amd64 desktop', False),
            ('580.159.03', 'ii nvidia-driver-580-server 580 amd64 server', True),
            ('595.58.03', '', True),
            ('570.172.08', 'ii nvidia-driver-570-open 570 amd64 open', False),
            ('580.173.02', 'ii nvidia-driver-580-open 580 amd64 open', False),
            ('610.1', '', False),
        ]:
            with self.subTest(version=version, packages=packages):
                result = self.policy(version, packages)
                self.assertEqual('SWAP' in result.stdout, swap, result.stdout + result.stderr)

    def test_invalid_policy_and_missing_host_driver_fail(self):
        for version, config in [('595.58.03', {'DPAD_DRIVER_POLICY': 'typo'}),
                                ('595.58.03', {'DPAD_DRIVER_POLICY': ''}),
                                ('', {'DPAD_DRIVER_POLICY': 'host'}),
                                ('', {'DPAD_SKIP_DRIVER_SWAP': '1'}),
                                ('bad', {'DPAD_DRIVER_POLICY': 'host'}),
                                ('595.58.03', {'DPAD_SKIP_DRIVER_SWAP': 'yes'}),
                                ('595.58.03', {'DPAD_DRIVER_POLICY': 'validated', 'DPAD_SKIP_DRIVER_SWAP': '1'})]:
            with self.subTest(version=version, config=config):
                result = self.policy(version, **config)
                self.assertNotEqual(result.returncode, 0)
                self.assertNotIn('SWAP', result.stdout)
                self.assertNotIn('APT', result.stderr)

    def test_host_and_legacy_opt_in_preserve_all_variants(self):
        for config in ({'DPAD_DRIVER_POLICY': 'host'}, {'DPAD_SKIP_DRIVER_SWAP': '1'}):
            for version in ('570.172.08', '580.173.02', '595.58.03'):
                with self.subTest(config=config, version=version):
                    result = self.policy(version, 'ii nvidia-driver-580-server 580 amd64 server', **config)
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertNotIn('SWAP', result.stdout)
                    self.assertNotIn('APT', result.stderr)


if __name__ == '__main__':
    unittest.main(verbosity=2)
