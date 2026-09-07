#!/usr/bin/env python3
"""Execute real bootstrap functions; stub only host/provider side effects."""
from pathlib import Path
import subprocess
import tempfile
import unittest

SOURCE = Path(__file__).with_name('vm-bootstrap.sh').read_text()

def function(name):
    start = SOURCE.index(name + '() {')
    return SOURCE[start:SOURCE.index('\n}\n', start) + 3]

class ColdStartTests(unittest.TestCase):
    def nct(self, cdi_failure=False):
        with tempfile.TemporaryDirectory() as tmp:
            code = function('ensure_nct').replace('/tmp/cdi-gen.log', tmp+'/cdi.log')
            script = '''set -eu
DPAD_OVH_COLD_START=1
DPAD_PROVIDER=ovh
DPAD_RELEASE_PROFILE=default
have() { return 0; }
log() { :; }
err() { :; }
mkdir() { :; }
systemctl() { :; }
docker() { echo UNEXPECTED_DOCKER; }
'''
            script += 'nvidia-ctk() { case "$1 $2" in "cdi generate") return '+str(int(cdi_failure))+';; "cdi list") echo nvidia.com/gpu=0;; esac; }\n'
            return subprocess.run(['bash','-c',script+code+'\nif ensure_nct; then exit 0; else exit 1; fi'], text=True,capture_output=True)

    def test_nct_does_not_download_probe_image_in_ovh_canary(self):
        result = self.nct()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn('UNEXPECTED_DOCKER', result.stdout)

    def test_failed_cdi_generation_blocks_ovh_canary(self):
        self.assertNotEqual(self.nct(cdi_failure=True).returncode, 0)

    def test_invalid_optimization_scope_fails_before_host_changes(self):
        import os
        for provider, flag, profile in [('upcloud','1','default'), ('ovh','yes','default'), ('ovh','1','upcloud-stock595')]:
            script = 'set -eu\nerr() { :; }\nrelease_profile() { echo HOST_TOUCHED; }\n' + function('bootstrap') + '\nbootstrap'
            result = subprocess.run(['bash','-c',script], text=True, capture_output=True, env={**os.environ, 'DPAD_PROVIDER':provider, 'DPAD_OVH_COLD_START':flag, 'DPAD_RELEASE_PROFILE':profile})
            self.assertNotEqual(result.returncode, 0)
            self.assertNotIn('HOST_TOUCHED', result.stdout)

    def test_gpu_failures_never_reach_ready(self):
        import os
        for failure in ('gpu', 'image', 'storage'):
            with self.subTest(failure=failure), tempfile.TemporaryDirectory() as tmp:
                names = ('release_profile', 'ensure_no_auto_updates', 'ensure_driver_580',
                         'ensure_modeset', 'ensure_stock595_codecs', 'ensure_nct',
                         'ensure_userns', 'ensure_mps', 'verify_stock595_host_identity',
                         'systemctl', 'mkdir', 'log', 'err')
                setup = 'set -eu\n' + '\n'.join(n + '() { :; }' for n in names)
                setup += '\nensure_docker_xfs_quota() { [ "$FAILURE" != storage ]; }\n'
                setup += 'ensure_image() { [ "$FAILURE" != image ] || return 1; printf "%s\\n" example/gaming > "$TAG_FILE"; }\n'
                setup += 'docker() { [ "$FAILURE" != gpu ]; }\n'
                result = subprocess.run(['bash', '-c', setup + function('ensure_gpu_image') + function('bootstrap') + '\nbootstrap'], text=True, capture_output=True,
                    env={**os.environ, 'DPAD_WARM_VM':'1', 'DPAD_PROVIDER':'ovh', 'DPAD_OVH_COLD_START':'1', 'DPAD_RELEASE_PROFILE':'default', 'FAILURE':failure, 'TAG_FILE':tmp+'/tag', 'VM_READY_FILE':tmp+'/ready'})
                self.assertNotEqual(result.returncode, 0)
                self.assertFalse(Path(tmp, 'ready').exists())
                self.assertNotIn('DPAD_VM_READY', result.stdout)

    def test_missing_image_never_launches_docker(self):
        for content in (None, ''):
            with self.subTest(content=content), tempfile.TemporaryDirectory() as tmp:
                tag = Path(tmp, 'tag')
                if content is not None:
                    tag.write_text(content)
                script = 'set -eu\nerr() { :; }\nlog() { :; }\ndocker() { echo UNSAFE; }\n'
                script += 'TAG_FILE=' + str(tag) + '\n' + function('ensure_gpu_image') + '\nensure_gpu_image'
                result = subprocess.run(['bash', '-c', script], text=True, capture_output=True)
                self.assertNotEqual(result.returncode, 0)
                self.assertNotIn('UNSAFE', result.stdout)

    def test_gpu_probe_uses_final_image_after_storage_setup(self):
        with tempfile.TemporaryDirectory() as tmp:
            setup = '''set -eu
log() { :; }
err() { echo "$*" >&2; }
systemctl() { :; }
mkdir() { :; }
ensure_no_auto_updates() { :; }
ensure_driver_580() { :; }
ensure_modeset() { :; }
ensure_nct() { echo nct; }
ensure_docker_xfs_quota() { echo storage; }
ensure_userns() { :; }
ensure_image() { echo image; printf '%s\\n' 'example/gaming@sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa' > "$TAG_FILE"; }
ensure_mps() { echo mps; }
release_profile() { :; }
ensure_stock595_codecs() { :; }
verify_stock595_host_identity() { :; }
docker() { printf 'docker'; printf ' <%s>' "$@"; printf '\\n'; }
'''
            probe = function('ensure_gpu_image') if 'ensure_gpu_image() {' in SOURCE else ''
            script = setup + probe + function('bootstrap') + '\nbootstrap\n'
            import os
            result = subprocess.run(['bash', '-c', script], text=True, capture_output=True, env={**os.environ, 'DPAD_WARM_VM':'1', 'DPAD_PROVIDER':'ovh', 'DPAD_OVH_COLD_START':'1', 'TAG_FILE':tmp+'/tag', 'VM_READY_FILE':tmp+'/ready'})
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn('docker <run> <--rm> <--pull=never>', result.stdout)
            self.assertLess(result.stdout.index('storage'), result.stdout.index('docker'))
            self.assertLess(result.stdout.index('image'), result.stdout.index('docker'))
            self.assertLess(result.stdout.index('docker'), result.stdout.index('mps'))
            self.assertIn('<--entrypoint> <nvidia-smi> <example/gaming@sha256:', result.stdout)
            self.assertNotIn('nvidia/cuda:', result.stdout)

if __name__ == '__main__':
    unittest.main(verbosity=2)
