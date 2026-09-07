#!/usr/bin/env python3
"""CPU-only ensure_nct regression: real function, bounded external fixtures.

The fixture models the /var/run priority proven by the supplied live A/B/A;
it does not establish real NVIDIA CDI precedence or perform container injection.
No host command, package operation, network request, or GPU is used.
"""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
CODECS = ('libnvidia-encode.so.595.58.03', 'libnvcuvid.so.595.58.03')
STALE = {'kind': 'nvidia.com/gpu', 'mounts': [], 'hooks': []}


class PublicationTests(unittest.TestCase):
    def run_nct(self, profile='upcloud-stock595', provider='upcloud', fail='', repeats=1,
                source=None):
        source = source if source is not None else (ROOT / 'scripts/vm-bootstrap.sh').read_text()
        function = source.split('ensure_nct() {', 1)[1].split('\n}\n', 1)[0]
        function = 'ensure_nct() {' + function + '\n}\n'
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for directory in ('etc/cdi', 'run/cdi', 'var', 'host', 'bin'):
                (root / directory).mkdir(parents=True, exist_ok=True)
            (root / 'var/run').symlink_to('../run')
            (root / 'run/cdi/nvidia.yaml').write_text(json.dumps(STALE))
            (root / 'etc/cdi/nvidia.yaml').write_text('prior etc spec\n')
            (root / 'run/cdi/other.yaml').write_text('unrelated runtime spec\n')
            # Fresh host codec presence is the generator's external input, not
            # an assertion that these fixture bytes are loadable NVIDIA ELF.
            for codec in CODECS:
                (root / 'host' / codec).write_bytes(b'\x7fELF fixture ' + codec.encode())
            stub = root / 'bin/stub'
            stub.write_text(r'''#!/usr/bin/python3
import json, os, pathlib, sys
root = pathlib.Path(os.environ['FIXTURE_ROOT'])
name, args = pathlib.Path(sys.argv[0]).name, sys.argv[1:]
with (root/'events').open('a') as f: f.write(json.dumps([name, *args])+'\n')
fail = os.environ['FAIL_STEP']
if name == 'nvidia-ctk':
    if args == ['runtime', 'configure', '--runtime=docker']:
        sys.exit(1 if fail == 'configure' else 0)
    if args == ['cdi', 'list']:
        print('nvidia.com/gpu=0'); sys.exit(0)
    if args[:2] == ['cdi', 'generate'] and len(args) == 3:
        if fail == 'cdi': sys.exit(1)
        output = args[2].removeprefix('--output=')
        assert output in ('/etc/cdi/nvidia.yaml', '/var/run/cdi/nvidia.yaml')
        codecs = sorted(p.name for p in (root/'host').iterdir() if p.stat().st_size)
        spec = {'kind': 'nvidia.com/gpu', 'mounts': codecs,
                'hooks': [p+':soname' for p in codecs]}
        (root/output.lstrip('/')).write_text(json.dumps(spec)); sys.exit(0)
elif name == 'systemctl' and args == ['restart', 'docker']:
    sys.exit(1 if fail == 'restart' else 0)
elif name == 'mkdir' and args[:1] == ['-p'] and len(args) == 2:
    assert args[1] in ('/etc/cdi', '/var/run/cdi')
    (root/args[1].lstrip('/')).mkdir(parents=True, exist_ok=True); sys.exit(0)
elif name == 'docker' and args == ['run', '--rm', '--gpus', 'all',
        'nvidia/cuda:12.8.1-runtime-ubuntu24.04', 'nvidia-smi']:
    sys.exit(1 if fail == 'probe' else 0)
print('UNEXPECTED COMMAND: '+name+' '+repr(args), file=sys.stderr)
sys.exit(97)
''')
            stub.chmod(0o755)
            for name in ('nvidia-ctk', 'systemctl', 'mkdir', 'docker', 'curl', 'apt-get', 'gpg'):
                (root / 'bin' / name).symlink_to('stub')
            script = '''set -euo pipefail
log() { echo "$*"; }
err() { echo "$*" >&2; }
have() { [ "$FAIL_STEP" != missing ]; }
''' + function.replace('/tmp/cdi-gen.log', str(root / 'cdi-gen.log'))
            # Calling from an explicit conditional also exercises return guards
            # independent of Bash's context-sensitive errexit behavior.
            script += '\n' + '\n'.join('if ensure_nct; then :; else exit 1; fi' for _ in range(repeats))
            env = {'PATH': str(root/'bin')+':/usr/bin:/bin', 'FIXTURE_ROOT': tmp,
                   'FAIL_STEP': fail, 'DPAD_PROVIDER': provider}
            if profile is not None:
                env['DPAD_RELEASE_PROFILE'] = profile
            result = subprocess.run(['/bin/bash', '-c', script], env=env,
                                    capture_output=True, text=True, timeout=10)
            events = [json.loads(line) for line in (root/'events').read_text().splitlines()] if (root/'events').exists() else []
            return result, {
                'runtime': json.loads((root/'run/cdi/nvidia.yaml').read_text()),
                'etc': (root/'etc/cdi/nvidia.yaml').read_text(),
                'other': (root/'run/cdi/other.yaml').read_text(),
                'events': events,
                'host': {p.name: p.read_bytes() for p in (root/'host').iterdir()},
            }

    def test_stock_replaces_selected_stale_runtime_spec_with_fresh_codecs(self):
        result, state = self.run_nct()
        self.assertEqual(result.returncode, 0, result.stdout+result.stderr)
        self.assertEqual(state['runtime']['mounts'], sorted(CODECS),
                         'selected runtime CDI spec still omits freshly installed host codecs')
        self.assertEqual(state['runtime']['hooks'], [p+':soname' for p in sorted(CODECS)])
        self.assertEqual(state['etc'], 'prior etc spec\n')
        self.assertEqual(state['other'], 'unrelated runtime spec\n')
        self.assertEqual(state['host'], {p: b'\x7fELF fixture '+p.encode() for p in CODECS})
        self.assertEqual([e[0] for e in state['events']],
                         ['nvidia-ctk', 'systemctl', 'mkdir', 'nvidia-ctk', 'nvidia-ctk', 'docker'])

    def test_stock_repeated_publication_is_idempotent(self):
        once, one = self.run_nct()
        twice, two = self.run_nct(repeats=2)
        self.assertEqual((once.returncode, twice.returncode), (0, 0))
        for key in ('runtime', 'etc', 'other', 'host'):
            self.assertEqual(one[key], two[key])
        self.assertEqual(two['events'], one['events']*2)

    def test_stock_failures_stop_before_probe(self):
        for failure in ('missing', 'configure', 'restart', 'cdi'):
            with self.subTest(failure=failure):
                result, state = self.run_nct(fail=failure)
                self.assertNotEqual(result.returncode, 0)
                self.assertFalse(any(e[0] == 'docker' for e in state['events']))
                self.assertEqual(state['runtime'], STALE)
                self.assertEqual(state['etc'], 'prior etc spec\n')
                self.assertEqual(state['other'], 'unrelated runtime spec\n')

    def test_stock_gpu_probe_failure_still_fails(self):
        result, state = self.run_nct(fail='probe')
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(state['runtime']['mounts'], sorted(CODECS))
        self.assertIn('container cannot see the GPU', result.stderr)

    def test_non_stock_provider_behavior_matches_committed_baseline(self):
        baseline = subprocess.check_output(
            ['git', 'show', 'HEAD:scripts/vm-bootstrap.sh'], cwd=ROOT, text=True)
        for provider in ('upcloud', 'ovh', 'scaleway', 'massedcompute', 'hyperstack', 'runpod', 'vast'):
            for profile in (None, 'default'):
                for failure in ('', 'configure', 'restart', 'cdi', 'probe'):
                    with self.subTest(provider=provider, profile=profile, failure=failure):
                        old, before = self.run_nct(profile, provider, failure, source=baseline)
                        new, after = self.run_nct(profile, provider, failure)
                        self.assertEqual((new.returncode, new.stdout), (old.returncode, old.stdout))
                        # Temporary log paths differ; compare all actual calls,
                        # published bytes, codec inputs and return behavior.
                        self.assertEqual(after, before)
                        self.assertEqual(after['runtime'], STALE)
                        self.assertEqual(after['other'], 'unrelated runtime spec\n')


if __name__ == '__main__':
    unittest.main(verbosity=2)
