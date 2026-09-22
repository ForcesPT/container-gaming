#!/usr/bin/env python3
"""Local shell policy checks, with service/Docker boundaries simulated."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).parent
IMAGE = 'example.invalid/gaming@sha256:' + 'a' * 64
POLICY = 'DPAD_DRIVER_POLICY=host\nDPAD_OVERLAY_POLICY=image-only\nDPAD_IMAGE_TAG=' + IMAGE + '\nDPAD_RELEASE_PROFILE=default\nDPAD_PROVIDER=massedcompute\nDPAD_ENCODER=\nDPAD_COMPOSITOR_EGL=nvidia\n'
BAD_POLICIES = ('missing', 'empty', 'truncated', 'wrong-driver', 'wrong-overlay', 'symlink', 'marker-symlink', 'marker-loss', 'both-lost', 'owner', 'writable')

def bad_policy(root, mutation):
    import hashlib
    policy = root / 'transport-release.env'
    marker = root / 'transport-managed'
    policy.write_text(POLICY)
    marker.write_text('b' * 40 + ' ' + hashlib.sha256(POLICY.encode()).hexdigest() + '\n')
    if mutation in ('missing', 'both-lost'): policy.unlink()
    if mutation in ('marker-loss', 'both-lost'): marker.unlink()
    if mutation == 'empty': policy.write_text('')
    if mutation == 'truncated': policy.write_text(POLICY.split('DPAD_RELEASE_PROFILE')[0])
    if mutation == 'wrong-driver': policy.write_text(POLICY.replace('=host', '=validated'))
    if mutation == 'wrong-overlay': policy.write_text(POLICY.replace('=image-only', '=legacy'))
    if mutation in ('symlink', 'marker-symlink'):
        target = policy if mutation == 'symlink' else marker
        target.rename(root / 'other')
        target.symlink_to(root / 'other')
    return '1000 755' if mutation == 'owner' else '0 777' if mutation == 'writable' else '0 755'


class TransportHostTests(unittest.TestCase):
    def shell(self, file, body):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            policy = 'DPAD_DRIVER_POLICY=host\nDPAD_OVERLAY_POLICY=image-only\nDPAD_IMAGE_TAG=' + IMAGE + '\nDPAD_RELEASE_PROFILE=default\nDPAD_PROVIDER=massedcompute\nDPAD_ENCODER=\nDPAD_COMPOSITOR_EGL=nvidia\n'
            (root / 'transport-release.env').write_text(policy)
            import hashlib
            (root / 'transport-managed').write_text('b' * 40 + ' ' + hashlib.sha256(policy.encode()).hexdigest() + '\n')
            (root / 'environment').write_text('DPAD_DRIVER_POLICY=validated\n')
            for name in ('evdev_bridge.py', 'extract-nvrtc.sh', 'dpad_input_patch.py'):
                (root / name).touch()
            bundle = root / ('stream-hotfix-' + '0' * 64)
            bundle.mkdir()
            for name in ('entrypoint.sh', 'dpad-resolve-stream-quality', 'patch_live_resolution.py'):
                (bundle / name).touch()
                (bundle / name).chmod(0o755)
            (root / 'stream-hotfix-current').symlink_to(bundle)
            source = (ROOT / file).read_text().rsplit('\ncase "${1:-', 1)[0]
            source = source.replace('/opt/dpadcloud', tmp).replace('/etc/environment', tmp + '/environment')
            body = body.replace('/opt/dpadcloud', tmp)
            # Ownership checks stay in production; simulate root metadata in this non-root sandbox.
            script = 'stat() { echo "0 755"; }\n' + source + '\n' + body
            return subprocess.run(['bash', '-c', script], capture_output=True, text=True,
                                  env={k:v for k,v in os.environ.items() if not k.startswith('DPAD_')})

    def test_stock595_managed_policy_accepts_labwc_and_rejects_unknown_desktops(self):
        import shlex
        policy = ('DPAD_DRIVER_POLICY=host\nDPAD_OVERLAY_POLICY=image-only\nDPAD_IMAGE_TAG=' + IMAGE
                  + '\nDPAD_RELEASE_PROFILE=upcloud-stock595\nDPAD_PROVIDER=upcloud\n'
                  'DPAD_ENCODER=nvcudah264enc\nDPAD_COMPOSITOR_EGL=multivendor\n'
                  'DPAD_DESKTOP_CLIENT={desktop}\n'
                  'DPAD_STOCK595_CODEC_INSTALLER=/opt/dpadcloud/dpad-stock595-codecs.py\n'
                  'DPAD_STOCK595_CODEC_HOOK=/opt/dpadcloud/dpad-stock595-apt-hook.py\n')
        for file in ('dpad-launch-session', 'vm-bootstrap.sh'):
            for desktop in ('labwc', 'sway', 'unknown', ''):
                with self.subTest(file=file, desktop=desktop):
                    # Codec/GPU boundary is a no-op fixture; real policy parsing,
                    # digest verification, selector exports and refusal run below.
                    body = ('printf %s ' + shlex.quote(policy.format(desktop=desktop))
                            + ' > /opt/dpadcloud/transport-release.env\n'
                            'hash=$(sha256sum /opt/dpadcloud/transport-release.env)\n'
                            "printf '%s %s\\n' " + 'b' * 40 + ' "${hash%% *}" > /opt/dpadcloud/transport-managed\n'
                            'touch /opt/dpadcloud/dpad-stock595-codecs.py /opt/dpadcloud/dpad-stock595-apt-hook.py\n'
                            'release_profile "" || exit 1\n'
                            "printf 'SELECTED:%s:%s:%s:%s\\n' \"$DPAD_DESKTOP_CLIENT\" \"$DPAD_DRIVER_POLICY\" \"$DPAD_ENCODER\" \"$DPAD_COMPOSITOR_EGL\"\n")
                    result = self.shell(file, body)
                    if desktop in ('labwc', 'sway'):
                        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                        self.assertIn('SELECTED:' + desktop + ':host:nvcudah264enc:multivendor', result.stdout)
                    else:
                        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
                        self.assertNotIn('SELECTED:', result.stdout)

    def test_managed_backend_policy_loss_fails_before_docker(self):
        for policy in BAD_POLICIES:
            with self.subTest(policy=policy), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                metadata = bad_policy(root, policy)
                (root / 'dpad_input_patch.py').touch()
                source = (ROOT / 'dpad-launch-session').read_text().replace('/opt/dpadcloud', tmp)
                backend = root / 'dpad-launch-session-backend'
                backend.write_text(source.replace('set -uo pipefail', 'set -uo pipefail\nstat() { echo "' + metadata + '"; }'))
                (root / 'docker').write_text('#!/bin/bash\necho "$*" >> "$EFFECTS"\ncase "$1" in inspect) exit 1;; run) echo "DOCKER:$*";; logs) echo "DPAD_READY fixture";; esac\n')
                (root / 'docker').chmod(0o755)
                result = subprocess.run(['bash', str(backend), 'launch', '0', 'none', 'none', 'pass', IMAGE],
                    capture_output=True, text=True, env={**{k:v for k,v in os.environ.items() if not k.startswith('DPAD_')}, 'PATH': tmp + ':' + os.environ['PATH'], 'EFFECTS': tmp + '/effects'})
                self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertNotIn('DOCKER:', result.stdout)
                self.assertFalse((root / 'effects').exists(), result.stdout + result.stderr)

    def test_managed_bootstrap_loss_rejected_on_install_and_service(self):
        for action in ('install', 'run'):
            for policy in BAD_POLICIES:
                with self.subTest(action=action, policy=policy), tempfile.TemporaryDirectory() as tmp:
                    root = Path(tmp)
                    metadata = bad_policy(root, policy)
                    source = (ROOT / 'vm-bootstrap.sh').read_text().replace('/opt/dpadcloud', tmp).replace('/etc/environment', tmp + '/environment')
                    prefix, dispatch = source.rsplit('\ncase "${1:-', 1)
                    sentinels = '\nstat() { echo "' + metadata + '"; }\n'
                    for name in ('ensure_no_auto_updates', 'ensure_driver_580', 'ensure_image', 'systemctl', 'mkdir', 'curl', 'cp'):
                        sentinels += name + '() { echo FORBIDDEN_EFFECT; return 1; };\n'
                    path = root / 'vm-bootstrap-transport.sh'
                    path.write_text(prefix + sentinels + '\ncase "${1:-' + dispatch)
                    result = subprocess.run(['bash', str(path), action], text=True, capture_output=True,
                        env={k:v for k,v in os.environ.items() if not k.startswith('DPAD_')})
                    self.assertNotEqual(result.returncode, 0)
                    self.assertNotIn('FORBIDDEN_EFFECT', result.stdout)

    def test_policy_must_match_durable_managed_identity(self):
        for file in ('dpad-launch-session', 'vm-bootstrap.sh'):
            for mutation in ('missing-marker', 'truncated', 'wrong-driver', 'wrong-overlay', 'wrong-image', 'symlink', 'unsafe-owner'):
                with self.subTest(file=file, mutation=mutation):
                    body = {
                        'missing-marker': 'rm /opt/dpadcloud/transport-managed',
                        'truncated': "printf 'DPAD_DRIVER_POLICY=host\\nDPAD_OVERLAY_POLICY=image-only\\nDPAD_IMAGE_TAG=" + IMAGE + "\\n' > /opt/dpadcloud/transport-release.env",
                        'wrong-driver': "printf 'DPAD_DRIVER_POLICY=validated\\n' >> /opt/dpadcloud/transport-release.env",
                        'wrong-overlay': "printf 'DPAD_OVERLAY_POLICY=legacy\\n' >> /opt/dpadcloud/transport-release.env",
                        'wrong-image': "printf 'DPAD_IMAGE_TAG=untrusted:latest\\n' >> /opt/dpadcloud/transport-release.env",
                        'symlink': 'mv /opt/dpadcloud/transport-release.env /opt/dpadcloud/other; ln -s /opt/dpadcloud/other /opt/dpadcloud/transport-release.env',
                        'unsafe-owner': 'stat() { echo "1000 755"; }',
                    }[mutation]
                    result = self.shell(file, body + '\nrelease_profile "" || exit 1\necho ACCEPTED')
                    self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
                    self.assertNotIn('ACCEPTED', result.stdout)

    def test_bound_policy_still_requires_complete_exact_schema(self):
        for file in ('dpad-launch-session', 'vm-bootstrap.sh'):
            result = self.shell(file, '''
printf 'DPAD_DRIVER_POLICY=host\\nDPAD_OVERLAY_POLICY=image-only\\nDPAD_IMAGE_TAG=''' + IMAGE + '''\\n' > /opt/dpadcloud/transport-release.env
hash=$(sha256sum /opt/dpadcloud/transport-release.env)
printf '%s %s\\n' ''' + 'b' * 40 + ''' "${hash%% *}" > /opt/dpadcloud/transport-managed
release_profile "" || exit 1
echo ACCEPTED
''')
            self.assertNotEqual(result.returncode, 0, file + result.stdout + result.stderr)

    def test_managed_install_keeps_managed_service_entrypoint(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'systemd').mkdir()
            policy = 'DPAD_DRIVER_POLICY=host\nDPAD_OVERLAY_POLICY=image-only\nDPAD_IMAGE_TAG=' + IMAGE + '\nDPAD_RELEASE_PROFILE=default\nDPAD_PROVIDER=massedcompute\nDPAD_ENCODER=\nDPAD_COMPOSITOR_EGL=nvidia\n'
            (root / 'transport-release.env').write_text(policy)
            import hashlib
            (root / 'transport-managed').write_text('b' * 40 + ' ' + hashlib.sha256(policy.encode()).hexdigest() + '\n')
            source = (ROOT / 'vm-bootstrap.sh').read_text().replace('/opt/dpadcloud', tmp).replace('/etc/environment', tmp + '/environment').replace('/etc/systemd/system', tmp + '/systemd')
            source = source.replace('set -uo pipefail', 'set -uo pipefail\nstat() { echo "0 755"; }\nsystemctl() { :; }\ncurl() { echo FORBIDDEN_DOWNLOAD; return 1; }')
            path = root / 'vm-bootstrap-transport.sh'
            path.write_text(source)
            result = subprocess.run(['bash', str(path), 'install'], text=True, capture_output=True,
                env={k:v for k,v in os.environ.items() if not k.startswith('DPAD_')})
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn('ExecStart=' + str(path), (root / 'systemd/dpadcloud-bootstrap.service').read_text())
            self.assertNotIn('FORBIDDEN_DOWNLOAD', result.stdout)

    def test_coherent_tree_contains_matching_controller_gateway_and_unit(self):
        import hashlib
        pins = {
            'dpad-session-control': '05f8491d8e1863f76a54b3c59d54ed3660487b1fc594d4b07f4304a52766dce4',
            'dpad-guest-tls': '1e5ef5a3421630f231c76e29e286d790754a32155aebea16df49447da58392d8',
            'dpad-guest-tls@.service': '752ec05d5f0a4a493b357808fb8a581332c17bd590ad936ccd726224a6f071be',
        }
        for name, digest in pins.items():
            self.assertTrue((ROOT / name).is_file(), name)
            self.assertEqual(hashlib.sha256((ROOT / name).read_bytes()).hexdigest(), digest)
        result = subprocess.run(['python3', str(ROOT / 'dpad-session-control'), 'protocol'], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), 'DPAD_SESSION_CONTROL_V1')

    def test_bootstrap_image_only_never_fetches_legacy_overlays(self):
        result = self.shell('vm-bootstrap.sh', """
release_profile "${DPAD_IMAGE_TAG:-}" || exit
docker() { printf 'DOCKER:%s\\n' "$*"; }
curl() { echo FORBIDDEN_OVERLAY; return 1; }
TAG_FILE=/opt/dpadcloud/image-tag
ensure_image
""")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('DOCKER:pull ' + IMAGE, result.stdout)
        self.assertNotIn('FORBIDDEN_OVERLAY', result.stdout)

    def test_backend_reloads_policies_and_uses_only_image(self):
        result = self.shell('dpad-launch-session', '''
docker() { case "$1" in run) printf '%s\\n' "$@";; logs) echo "DPAD_READY fixture";; esac; }
launch 0 none none pass ''' + IMAGE)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('DPAD_DRIVER_POLICY=host', result.stdout)
        self.assertIn('DPAD_INPUT_HOTFIX=0', result.stdout)
        for name in ('entrypoint.sh', 'dpad-resolve-stream-quality', 'patch_live_resolution.py', 'evdev_bridge.py', 'extract-nvrtc.sh', 'dpad_input_patch.py'):
            self.assertNotIn(name, result.stdout)

    def test_bootstrap_reload_overrides_legacy_environment(self):
        result = self.shell('vm-bootstrap.sh', '''
release_profile "${DPAD_IMAGE_TAG:-}" || exit
nvidia-smi() { echo 595.58.03; }
apt-get() { echo FORBIDDEN_DRIVER_MUTATION; return 1; }
ensure_driver_580 || exit
printf 'POLICY:%s:%s\\n' "$DPAD_DRIVER_POLICY" "$DPAD_OVERLAY_POLICY"
''')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('POLICY:host:image-only', result.stdout)
        self.assertNotIn('FORBIDDEN_DRIVER_MUTATION', result.stdout)

if __name__ == '__main__': unittest.main(verbosity=2)
