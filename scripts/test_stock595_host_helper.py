#!/usr/bin/env python3
"""Production helper tests with tmp fixtures and fake package executables."""
from importlib.machinery import SourceFileLoader
from pathlib import Path
import json
import os
import tempfile
import subprocess
import unittest
from unittest.mock import patch

helper = SourceFileLoader('stock595_helper', str(Path(__file__).with_name('dpad-stock595-codecs.py'))).load_module()
IMAGE = 'forcespt/dpadcloud-gaming@sha256:' + 'a'*64
ENV = dict(DPAD_RELEASE_PROFILE='upcloud-stock595', DPAD_PROVIDER='upcloud', DPAD_IMAGE_TAG=IMAGE)

class HelperTests(unittest.TestCase):
    def test_stock595_accepts_exact_l4_and_l40s_only(self):
        image = ('forcespt/dpadcloud-gaming@sha256:'
                 '207c38a46a2a768698291a37f8073b7c4c0e0bed21e5b84253c44f7bc078882a')
        env = {**ENV, 'DPAD_IMAGE_TAG': image}
        expected = {**env, 'DPAD_DRIVER_POLICY': 'host',
                    'DPAD_ENCODER': 'nvcudah264enc',
                    'DPAD_COMPOSITOR_EGL': 'multivendor',
                    'DPAD_DESKTOP_CLIENT': 'sway'}
        denied = [f'{name}, 595.58.03' for name in (
            'NVIDIA L40', 'NVIDIA L4S', 'NVIDIA L40SX', 'NVIDIA L400',
            'NVIDIA A40', 'NVIDIA RTX 6000 Ada Generation',
            'L40S', 'nvidia l40s', 'NVIDIA L40S vGPU', '',
        )]
        denied += [f'{name}, {driver}'
                   for name in ('NVIDIA L4', 'NVIDIA L40S')
                   for driver in ('595.58.04', '580.178.04', '595.58.030')]
        denied += ['NVIDIA L4, 595.58.03\nNVIDIA L40S, 595.58.03',
                   'NVIDIA L40S, 595.58.03\nNVIDIA L40S, 595.58.03']
        # Only external host identity/configuration inputs are fixtures. Exercise
        # the real profile decision without executing bootstrap, Docker or APT.
        with tempfile.TemporaryDirectory() as tmp, \
                patch.object(helper, 'CONFIG', Path(tmp) / 'profile.json'), \
                patch.dict(os.environ, env, clear=True):
            for device in denied:
                with self.subTest(rejected=device), \
                        patch.object(helper, 'identity', return_value=(device, 'boot')), \
                        self.assertRaises(ValueError):
                    helper.profile(image)
            for name in ('NVIDIA L4', 'NVIDIA L40S'):
                with self.subTest(accepted=name), patch.object(
                        helper, 'identity', return_value=(f'{name}, 595.58.03', 'boot')):
                    try:
                        values = helper.profile(image)
                    except ValueError as exc:
                        self.fail(f'{name} with exact driver 595.58.03 must be accepted: {exc}')
                    self.assertEqual(values, expected)

    def test_profile_tuple_and_enums(self):
        with patch.object(helper, 'CONFIG', Path('/nonexistent/profile.json')), patch.object(helper, 'identity', return_value=('NVIDIA L4, 595.58.03','boot')):
            with patch.dict(os.environ, ENV, clear=True):
                values = helper.profile(IMAGE)
                self.assertEqual([values[k] for k in ('DPAD_DRIVER_POLICY','DPAD_ENCODER','DPAD_COMPOSITOR_EGL','DPAD_DESKTOP_CLIENT')], ['host','nvcudah264enc','multivendor','sway'])
            for k, v in [('DPAD_PROVIDER','ovh'),('DPAD_RELEASE_PROFILE',''),('DPAD_DRIVER_POLICY','validated'),('DPAD_ENCODER','bad'),('DPAD_COMPOSITOR_EGL','bad'),('DPAD_DESKTOP_CLIENT','bad'),('DPAD_BUILD','1'),('DPAD_WARM_VM','0'),('DPAD_SKIP_MODESET','1')]:
                with self.subTest(k=k), patch.dict(os.environ, {**ENV,k:v}, clear=True), self.assertRaises(ValueError): helper.profile(IMAGE)
            for device in ('NVIDIA L40, 595.58.03','NVIDIA L4, 595.58.04','NVIDIA L4, 580.1','NVIDIA L4, 595.58.03\nNVIDIA L4, 595.58.03'):
                with patch.dict(os.environ, ENV, clear=True), patch.object(helper,'identity',return_value=(device,'boot')), self.assertRaises(ValueError): helper.profile(IMAGE)
            for image in ('tag:latest', IMAGE+'\n', IMAGE.replace('a'*64,'b'*64)):
                with patch.dict(os.environ, ENV, clear=True), self.assertRaises(ValueError): helper.profile(image)

    def test_persisted_settings_survive_empty_environment_and_reject_drift(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(helper,'CONFIG',Path(tmp)/'profile.json'), patch.object(helper,'secure_path'), patch.object(helper,'identity',return_value=('NVIDIA L4, 595.58.03','boot')):
            with patch.dict(os.environ, ENV, clear=True): values = helper.profile(IMAGE)
            helper.write_evidence(helper.CONFIG, json.dumps(values))
            with patch.dict(os.environ, {}, clear=True): self.assertEqual(helper.profile(''), values)
            for k,v in [('DPAD_RELEASE_PROFILE','default'),('DPAD_ENCODER','nvh264enc'),('DPAD_PROVIDER','ovh')]:
                with patch.dict(os.environ,{k:v},clear=True), self.assertRaises(ValueError): helper.profile(IMAGE)

    def test_unsafe_paths(self):
        with tempfile.TemporaryDirectory() as tmp:
            f = Path(tmp)/'log'; f.write_text('keep')
            link = Path(tmp)/'link'; link.symlink_to(f)
            for path in (f,link,Path(tmp)):
                with self.assertRaises(ValueError): helper.secure_path(path)
            with patch.object(helper,'secure_path'):
                with self.assertRaises(OSError): helper.safe_open(link)
                hard = Path(tmp)/'hard'; os.link(f,hard)
                with self.assertRaises(ValueError): helper.safe_open(hard)
            self.assertEqual(f.read_text(),'keep')

    def test_signed_sources_required(self):
        for value in ('deb [trusted=yes] https://repo stable main', 'Trusted: yes', 'Allow-Insecure: yes', 'deb [allow-insecure=yes] https://repo stable main'):
            with self.subTest(value=value), self.assertRaises(ValueError): helper.validate_sources(value)

    def transaction(self, installed=None, scenario='normal'):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            state = root/'state.json'
            state.write_text(json.dumps(installed or {}))
            (root/'boot').write_text('original-boot')
            source = Path(helper.__file__).read_text().replace("Path('/opt/dpadcloud')", 'Path(' + repr(tmp) + ')')
            source = source.replace("Path('/proc/sys/kernel/random/boot_id')", 'Path(' + repr(str(root/'boot')) + ')')
            # Only fixture ownership is virtualized; command execution, selection,
            # simulation, real hook, postchecks, locks and output writes are real.
            source = source.replace('    import stat\n', '    if Path(path).is_relative_to(BASE): return\n    import stat\n')
            (root/'dpad-stock595-codecs.py').write_text(source)
            (root/'dpad-stock595-apt-hook.py').write_text(Path(helper.__file__).with_name('dpad-stock595-apt-hook.py').read_text())
            executable = root/'fake'
            executable.write_text(r"""#!/usr/bin/python3
import json, os, pathlib, subprocess, sys
root = pathlib.Path(__file__).parent
state = root/'state.json'
data = json.loads(state.read_text())
name = pathlib.Path(sys.argv[0]).name
args = sys.argv[1:]
scenario = os.environ['SCENARIO']
version = '595.58.03-1ubuntu1'
if name == 'nvidia-smi':
    print('NVIDIA L4, ' + ('595.58.04' if (root/'changed-driver').exists() else '595.58.03'))
elif name == 'docker':
    if scenario == 'active': print('customer')
    if scenario == 'docker-fail': sys.exit(1)
elif name == 'dpkg':
    if scenario == 'pending': print('pending kernel configure')
elif name == 'apt-cache': print(args[-1] + ' | ' + version + ' | signed repo')
elif name == 'dpkg-query':
    record = data.get(args[-1].split(':')[0])
    if record is None: sys.exit(1)
    sys.stdout.write(record)
elif name == 'dpkg-deb':
    package = pathlib.Path(args[-1]).stem
    print(package + '\n' + version + '\namd64')
elif name == 'apt-get':
    wanted = [a.split(':')[0] for a in args if ':amd64=' in a]
    if '--simulate' in args:
        for p in wanted: print('Inst ' + p + ' (' + version + ' repo [amd64])')
        if scenario == 'extra-plan': print('Inst linux-image (1 repo [amd64])')
        print('0 upgraded, ' + str(len(wanted)) + ' newly installed, 0 to remove and 0 not upgraded.')
    else:
        (root/'apt-called').touch()
        paths = [str(root/(p+'.deb')) for p in wanted]
        if scenario == 'extra-real': paths += [str(root/'linux-image.deb')]
        if scenario == 'boot-before-hook': (root/'boot').write_text('new-boot')
        hook = next(a.split('=/usr/bin/python3 ')[1] for a in args if a.startswith('DPkg::Pre-Install-Pkgs::='))
        result = subprocess.run(['/usr/bin/python3',hook],input='\n'.join(paths)+'\n',text=True)
        if result.returncode: sys.exit(result.returncode)
        (root/'installed').touch()
        for p in wanted: data[p] = 'installed\t'+version+'\tamd64'
        state.write_text(json.dumps(data))
        if scenario == 'boot-after': (root/'boot').write_text('new-boot')
        if scenario == 'driver-after': (root/'changed-driver').touch()
else: sys.exit(99)
""")
            executable.chmod(0o755)
            for name in ('nvidia-smi','docker','dpkg','apt-cache','dpkg-query','dpkg-deb','apt-get'):
                (root/name).symlink_to(executable)
            result = subprocess.run(['/usr/bin/python3',str(root/'dpad-stock595-codecs.py')],
                env={**ENV,'PATH':tmp+':/usr/bin:/bin','SCENARIO':scenario},capture_output=True,text=True)
            return result, (root/'apt-called').exists(), (root/'installed').exists()

    def test_actual_package_transaction(self):
        exact = 'installed\t595.58.03-1ubuntu1\tamd64'
        for installed in ({}, {'libnvidia-encode':exact}, dict.fromkeys(helper.NAMES,exact)):
            with self.subTest(installed=installed):
                p, apt, changed = self.transaction(installed)
                self.assertEqual(p.returncode, 0, p.stdout+p.stderr)
                self.assertEqual(apt, len(installed) != 2)
                self.assertEqual(changed, apt)
        for record in ('installed\t580.1\tamd64','unpacked\t595.58.03-1ubuntu1\tamd64','installed\t595.58.03-1ubuntu1\ti386'):
            p, apt, changed = self.transaction({'libnvidia-encode':record})
            self.assertNotEqual(p.returncode, 0)
            self.assertFalse(apt)
        for scenario in ('active','docker-fail','pending','extra-plan','extra-real','boot-before-hook','boot-after','driver-after'):
            with self.subTest(scenario=scenario):
                p, apt, changed = self.transaction(scenario=scenario)
                self.assertNotEqual(p.returncode, 0, p.stdout+p.stderr)
                if scenario not in ('boot-after','driver-after'): self.assertFalse(changed)

if __name__ == '__main__': unittest.main(verbosity=2)
