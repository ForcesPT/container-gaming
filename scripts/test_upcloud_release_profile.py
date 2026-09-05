#!/usr/bin/env python3
"""Local production-function regression checks; never execute host mutations."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parent
IMAGE = 'forcespt/dpadcloud-gaming@sha256:' + 'a' * 64

class ProfileTests(unittest.TestCase):
    def shell(self, file, body, env=None, source=None):
        source = (source if source is not None else (ROOT / file).read_text()).rsplit('\ncase "${1:-', 1)[0]
        with tempfile.TemporaryDirectory() as tmp:
            source = source.replace('/opt/dpadcloud', tmp).replace('/etc/environment', tmp + '/environment').replace('/etc/cdi',tmp+'/cdi').replace('/tmp/cdi-gen.log',tmp+'/cdi.log').replace('/etc/modprobe.d',tmp+'/modprobe.d')
            Path(tmp, 'modprobe.d').mkdir()
            body = body.replace('/opt/dpadcloud', tmp)
            script = source + '\n' + body
            return subprocess.run(['bash', '-c', script], text=True, capture_output=True,
                env={**{k:v for k,v in os.environ.items() if not k.startswith('DPAD_')}, **(env or {})})

    HOST_READS = """
MODESET=Y
DRIVER=595.58.03
BOOT=11111111-1111-1111-1111-111111111111
nvidia-smi() { if [ "$1" = --query-gpu=name,driver_version ]; then echo "NVIDIA L4, $DRIVER"; return; fi; printf '%s\\n' "$DRIVER"; }
cat() {
 case "${1:-}" in
  /sys/module/nvidia_drm/parameters/modeset) [ "$MODESET" != missing ] || return 1; printf '%s\\n' "$MODESET";;
  /proc/sys/kernel/random/boot_id) [ "$BOOT" != missing ] || return 1; printf '%s\\n' "$BOOT";;
  *) command cat "$@";;
 esac
}
"""
    PREP_STUBS = """
release_profile() { :; }
docker() { :; }
have() { return 0; }
mutation() { echo "$*" >> /opt/dpadcloud/mutations; }
ensure_no_auto_updates() { mutation updates; }
systemctl() { mutation systemctl; }
ensure_driver_580() { mutation driver; }
ensure_stock595_codecs() { mutation codecs; }
ensure_nct() { mutation nct; }
ensure_docker_xfs_quota() { mutation xfs; }
ensure_userns() { mutation userns; }
ensure_image() { mutation image; }
ensure_mps() { mutation mps; }
run_all_containers() { mutation containers; }
report_all_urls() { echo SESSION_READY; }
modprobe() { mutation modprobe; return 1; }
update-initramfs() { mutation initramfs; }
reboot() { mutation reboot; }
sync() { :; }
sleep() { :; }
VM_READY_FILE=/opt/dpadcloud/vm-ready
trap 'if [ -e /opt/dpadcloud/mutations ]; then command cat /opt/dpadcloud/mutations; fi; if [ -e "$VM_READY_FILE" ]; then echo MARKER_READY; fi' EXIT
"""

    def test_stock_modeset_rejected_before_any_mutation(self):
        for call in ('bootstrap', 'ensure_modeset'):
            for value in ('N', 'missing'):
                for skip in ('0', '1'):
                    with self.subTest(call=call, modeset=value, skip=skip):
                        p = self.shell('vm-bootstrap.sh', self.HOST_READS + self.PREP_STUBS +
                            f'\nMODESET={value}\n{call}\n',
                            {'DPAD_RELEASE_PROFILE':'upcloud-stock595', 'DPAD_SKIP_MODESET':skip})
                        self.assertNotEqual(p.returncode, 0, p.stdout+p.stderr)
                        self.assertIn('stock595 requires nvidia_drm.modeset already Y', p.stderr)
                        for event in ('updates','systemctl','driver','codecs','nct','xfs','userns','image','mps','modprobe','initramfs','reboot','MARKER_READY'):
                            self.assertNotIn(event, p.stdout.splitlines())

    def test_stock_identity_change_rejects_readiness(self):
        for warm in ('0', '1'):
            for change in ('DRIVER=580.1', 'BOOT=22222222-2222-2222-2222-222222222222', 'BOOT=missing'):
                with self.subTest(warm=warm, change=change):
                    p = self.shell('vm-bootstrap.sh', self.HOST_READS + self.PREP_STUBS +
                        '\nensure_no_auto_updates() { mutation updates; '+change+'; }\nbootstrap\n',
                        {'DPAD_RELEASE_PROFILE':'upcloud-stock595', 'DPAD_WARM_VM':warm})
                    self.assertNotEqual(p.returncode, 0, p.stdout+p.stderr)
                    self.assertNotIn('DPAD_VM_READY', p.stdout)
                    self.assertNotIn('MARKER_READY', p.stdout)
                    self.assertNotIn('SESSION_READY', p.stdout)

    def test_stock_missing_initial_identity_rejects_preparation(self):
        for change in ('DRIVER=', 'BOOT=missing'):
            p = self.shell('vm-bootstrap.sh', self.HOST_READS + self.PREP_STUBS +
                '\n'+change+'\nbootstrap\n', {'DPAD_RELEASE_PROFILE':'upcloud-stock595'})
            self.assertNotEqual(p.returncode, 0, p.stdout+p.stderr)
            self.assertNotIn('updates', p.stdout.splitlines())

    def test_stock_new_invocation_accepts_new_boot(self):
        p = self.shell('vm-bootstrap.sh', self.HOST_READS + self.PREP_STUBS + """
bootstrap || exit 1
BOOT=22222222-2222-2222-2222-222222222222
bootstrap
""", {'DPAD_RELEASE_PROFILE':'upcloud-stock595'})
        self.assertEqual(p.returncode, 0, p.stdout+p.stderr)
        self.assertEqual(p.stdout.splitlines().count('DPAD_VM_READY'), 2)

    def test_default_modeset_matches_committed_baseline(self):
        baseline = subprocess.run(['git','show','HEAD:scripts/vm-bootstrap.sh'],cwd=ROOT,
                                  text=True,capture_output=True,check=True).stdout
        for mode in ('Y','N','missing'):
            for skip in ('0','1'):
                body = self.HOST_READS + self.PREP_STUBS + f'\nMODESET={mode}\nensure_modeset\n'
                env = {'DPAD_RELEASE_PROFILE':'default', 'DPAD_SKIP_MODESET':skip}
                old = self.shell('vm-bootstrap.sh', body, env, source=baseline)
                new = self.shell('vm-bootstrap.sh', body, env)
                self.assertEqual((new.returncode,new.stdout,new.stderr), (old.returncode,old.stdout,old.stderr))

    def test_default_launch_argv_matches_committed_baseline(self):
        baseline = subprocess.run(['git','show','HEAD:scripts/dpad-launch-session'],cwd=ROOT,
                                  text=True,capture_output=True,check=True).stdout
        body = """
docker() { case "$1" in run) printf '%s\\n' "$@";; logs) echo 'DPAD_READY fixture';; esac; }
launch 0 none none pass image:old
"""
        for provider in ('upcloud','ovh','scaleway','massedcompute','hyperstack','runpod','vast'):
            for config in ({}, {'DPAD_RELEASE_PROFILE':'default'}):
                env = {'DPAD_PROVIDER':provider, **config}
                old = self.shell('dpad-launch-session',body,env,source=baseline)
                new = self.shell('dpad-launch-session',body,env)
                self.assertEqual(new.returncode,0,new.stderr)
                self.assertEqual(new.stdout,old.stdout)

    def test_unknown_profiles_rejected_before_work(self):
        for file, call in [('vm-bootstrap.sh', 'bootstrap'), ('dpad-launch-session', 'launch 0 none none pass')]:
            p = self.shell(file, '''
ensure_no_auto_updates() { echo MUTATION; }
systemctl() { echo MUTATION; }
docker() { echo MUTATION; return 1; }
''' + call, {'DPAD_RELEASE_PROFILE':'typo'})
            self.assertNotEqual(p.returncode, 0)
            self.assertNotIn('MUTATION', p.stdout)

    def test_stock_image_never_fetches_hotfix(self):
        p = self.shell('vm-bootstrap.sh', '''
image_tag_for_gpu() { echo immutable; }
docker() { :; }
curl() { touch /opt/dpadcloud/fetched; return 1; }
TAG_FILE=/dev/null
ensure_image
[ ! -e /opt/dpadcloud/fetched ]
''', {'DPAD_RELEASE_PROFILE':'upcloud-stock595'})
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertNotIn('FETCH', p.stderr)

    def test_stock_nct_failures_stop_before_gpu_probe(self):
        body = '''
have() { return 0; }
nvidia-ctk() {
 if [ "$1" = runtime ] && [ "$FAIL_STEP" = configure ]; then return 1; fi
 if [ "$1 $2" = 'cdi generate' ] && [ "$FAIL_STEP" = cdi ]; then return 1; fi
}
systemctl() { [ "$FAIL_STEP" != restart ]; }
docker() { echo GPU_PROBE; }
if ensure_nct; then exit 0; else exit 1; fi
'''
        for step in ('configure','restart','cdi'):
            p = self.shell('vm-bootstrap.sh',body,{'DPAD_RELEASE_PROFILE':'upcloud-stock595','FAIL_STEP':step})
            self.assertNotEqual(p.returncode,0,p.stdout+p.stderr)

    def test_bootstrap_order(self):
        p = self.shell('vm-bootstrap.sh', self.HOST_READS + '''
release_profile() { echo profile; }
ensure_no_auto_updates() { echo updates; }
systemctl() { :; }
docker() { :; }
have() { return 0; }
ensure_driver_580() { echo driver; }
ensure_modeset() { echo modeset; }
ensure_stock595_codecs() { echo codecs; }
ensure_nct() { echo nct; }
ensure_docker_xfs_quota() { echo xfs; }
ensure_userns() { :; }
ensure_image() { echo image; }
ensure_mps() { echo mps; }
VM_READY_FILE=/dev/null
bootstrap
''', {'DPAD_RELEASE_PROFILE':'upcloud-stock595'})
        self.assertEqual(p.returncode, 0, p.stderr)
        expected = ['profile','updates','driver','modeset','codecs','nct','xfs','image','mps']
        self.assertEqual([x for x in p.stdout.splitlines() if x in expected], expected)

    def test_launch_baked_only_even_with_stale_files(self):
        body = """
release_profile() { export DPAD_PROVIDER=upcloud DPAD_IMAGE_TAG='forcespt/dpadcloud-gaming@sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa' DPAD_DRIVER_POLICY=host DPAD_ENCODER=nvcudah264enc DPAD_COMPOSITOR_EGL=multivendor DPAD_DESKTOP_CLIENT=sway; }
mkdir -p /opt/dpadcloud
for f in evdev_bridge.py extract-nvrtc.sh dpad_input_patch.py; do touch /opt/dpadcloud/$f; done
bundle=/opt/dpadcloud/stream-hotfix-"$(printf '%064d' 0)"
mkdir "$bundle"
for f in entrypoint.sh dpad-resolve-stream-quality patch_live_resolution.py; do touch "$bundle/$f"; chmod +x "$bundle/$f"; done
ln -s "$bundle" /opt/dpadcloud/stream-hotfix-current
docker() {
 case "$1" in
  ps) :;;
  run) printf '%s\\n' "$@";;
  logs) echo 'DPAD_READY test';;
 esac
}
launch 0 none none pass """ + IMAGE
        for profile in ('upcloud-stock595', 'default'):
            p = self.shell('dpad-launch-session', body, {'DPAD_RELEASE_PROFILE':profile})
            self.assertEqual(p.returncode, 0, p.stderr)
            for name in ('entrypoint.sh','dpad-resolve-stream-quality','patch_live_resolution.py',
                         'evdev_bridge.py','extract-nvrtc.sh','dpad_input_patch.py'):
                self.assertEqual(name in p.stdout, profile == 'default', p.stdout)
            if profile == 'upcloud-stock595':
                for val in ('DPAD_ENCODER=nvcudah264enc','DPAD_COMPOSITOR_EGL=multivendor',
                            'DPAD_DESKTOP_CLIENT=sway','DPAD_DRIVER_POLICY=host','DPAD_RELEASE_PROFILE=upcloud-stock595','DPAD_INPUT_HOTFIX=0'):
                    self.assertIn(val, p.stdout)

    def test_installed_bootstrap_and_launch_reload_profile(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for file in ('dpad-stock595-codecs.py','dpad-stock595-apt-hook.py'):
                source = (ROOT/file).read_text().replace("Path('/opt/dpadcloud')", 'Path('+repr(tmp)+')')
                source = source.replace('    import stat\n','    if Path(path).is_relative_to(BASE): return\n    import stat\n')
                (root/file).write_text(source)
            smi = root/'nvidia-smi'
            smi.write_text('#!/bin/sh\necho "NVIDIA L4, 595.58.03"\n'); smi.chmod(0o755)
            bootstrap = (ROOT/'vm-bootstrap.sh').read_text().rsplit('\ncase "${1:-',1)[0]
            bootstrap = bootstrap.replace('/opt/dpadcloud',tmp).replace('/etc/environment',tmp+'/environment').replace('/etc/systemd/system',tmp)
            installed = root/'vm-bootstrap.sh'; installed.write_text(bootstrap)
            stubs = '''
stat() { echo '0 755'; }
systemctl() { :; }
docker() { :; }
have() { return 0; }
'''
            body = stubs + self.HOST_READS + '''
install_self
unset DPAD_RELEASE_PROFILE DPAD_PROVIDER DPAD_IMAGE_TAG DPAD_DRIVER_POLICY DPAD_ENCODER DPAD_COMPOSITOR_EGL DPAD_DESKTOP_CLIENT
ensure_no_auto_updates() { :; }
ensure_driver_580() { echo "PRESERVED:$DPAD_DRIVER_POLICY"; }
ensure_modeset() { :; }
ensure_stock595_codecs() { :; }
ensure_nct() { :; }
ensure_docker_xfs_quota() { :; }
ensure_userns() { :; }
ensure_image() { :; }
ensure_mps() { :; }
VM_READY_FILE=/dev/null
bootstrap
echo "RELOADED:$DPAD_RELEASE_PROFILE:$DPAD_IMAGE_TAG:$DPAD_ENCODER:$DPAD_COMPOSITOR_EGL:$DPAD_DESKTOP_CLIENT"
'''
            env = {**os.environ,'PATH':tmp+':/usr/bin:/bin','DPAD_RELEASE_PROFILE':'upcloud-stock595','DPAD_PROVIDER':'upcloud','DPAD_IMAGE_TAG':IMAGE}
            p = subprocess.run(['bash','-c',bootstrap+'\n'+body,str(installed)],env=env,capture_output=True,text=True)
            self.assertEqual(p.returncode,0,p.stdout+p.stderr)
            self.assertIn('PRESERVED:host',p.stdout)
            self.assertIn('RELOADED:upcloud-stock595:'+IMAGE+':nvcudah264enc:multivendor:sway',p.stdout)
            self.assertIn('ExecStart='+str(installed),(root/'dpadcloud-bootstrap.service').read_text())
            launcher = (ROOT/'dpad-launch-session').read_text().rsplit('\ncase "${1:-',1)[0].replace('/opt/dpadcloud',tmp)
            command = stubs + '''
docker() { case "$1" in run) printf '%s\\n' "$@";; logs) echo 'DPAD_READY fixture';; esac; }
launch 0 none none pass ''' + IMAGE
            p = subprocess.run(['bash','-c',launcher+'\n'+command],env={k:v for k,v in env.items() if not k.startswith('DPAD_')},capture_output=True,text=True)
            self.assertEqual(p.returncode,0,p.stdout+p.stderr)
            for value in ('DPAD_ENCODER=nvcudah264enc','DPAD_COMPOSITOR_EGL=multivendor','DPAD_DESKTOP_CLIENT=sway','DPAD_DRIVER_POLICY=host'):
                self.assertIn(value,p.stdout)

if __name__ == '__main__': unittest.main(verbosity=2)
