import json
import subprocess
import unittest
from unittest.mock import patch
import instant_gpu_preflight as preflight

IMAGE = 'forcespt/dpadcloud-gaming@sha256:' + 'a' * 64
REV = 'b' * 40

class PreflightTests(unittest.TestCase):
    def test_mutable_image_is_rejected_before_docker(self):
        with patch.object(subprocess, 'run') as run:
            with self.assertRaisesRegex(ValueError, 'digest'):
                preflight.check('forcespt/dpadcloud-gaming:latest', REV)
            run.assert_not_called()

    def test_source_mismatch_rejects_before_running_container(self):
        data = [{'RepoDigests': [IMAGE], 'Config': {'Labels': {}}}]
        with patch.object(subprocess, 'run', return_value=subprocess.CompletedProcess([], 0, json.dumps(data), '')) as run:
            with self.assertRaisesRegex(ValueError, 'revision'):
                preflight.check(IMAGE, REV)
            self.assertEqual(run.call_count, 1)

    def test_timeout_still_cleans_up_its_own_probe(self):
        data = [{'RepoDigests': [IMAGE], 'Config': {'Labels': {'org.opencontainers.image.revision': REV}}}]
        results = [subprocess.CompletedProcess([], 0, json.dumps(data), ''), subprocess.TimeoutExpired('docker', 90), subprocess.CompletedProcess([], 0, '', '')]
        with patch.object(subprocess, 'run', side_effect=results) as run:
            with self.assertRaises(subprocess.TimeoutExpired):
                preflight.check(IMAGE, REV)
            self.assertEqual(run.call_args.args[0][1:3], ['rm', '-f'])

    def test_missing_encoder_is_a_failure_not_gpu_acceptance(self):
        calls = []
        def run(args, **kwargs):
            calls.append(args)
            if args[1:3] == ['image', 'inspect']:
                return subprocess.CompletedProcess(args, 0, json.dumps([{'RepoDigests': [IMAGE], 'Config': {'Labels': {'org.opencontainers.image.revision': REV}}}]), '')
            if args[1] == 'run':
                return subprocess.CompletedProcess(args, 1, '', "No such element or plugin 'nvh264enc'")
            return subprocess.CompletedProcess(args, 0, '', '')
        with patch.object(subprocess, 'run', side_effect=run):
            with self.assertRaisesRegex(RuntimeError, 'encoding'):
                preflight.check(IMAGE, REV)
        probe = next(c for c in calls if c[1] == 'run')
        self.assertIn('--pull=never', probe)
        self.assertIn('--network=none', probe)
        self.assertIn('. /opt/gstreamer/gst-env', probe[-1])
        self.assertFalse(any('volume' in a or '/srv/' in a for a in probe))
        self.assertEqual(calls[-1][1:3], ['rm', '-f'])

if __name__ == '__main__':
    unittest.main()
