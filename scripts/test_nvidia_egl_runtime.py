#!/usr/bin/env python3
"""Local behavioral fixtures; real ELF loading, no GPU initialization claim."""
import json
import os
from pathlib import Path
import subprocess
import shutil
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class NvidiaRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.fs = self.base / 'root'
        self.fs.mkdir()
        self.version = '595.58.03'
        for directory in ('opt/nvidia-drivers/lib64', 'opt/nvidia-drivers/lib32',
                          'opt/dpadcloud', 'etc/ld.so.conf.d', 'usr/bin',
                          'usr/lib/xorg/modules/nvidia/drivers',
                          'usr/lib/xorg/modules/nvidia/extensions',
                          'usr/share/glvnd/egl_vendor.d', 'proc/driver/nvidia', 'run'):
            (self.fs / directory).mkdir(parents=True, exist_ok=True)
        self.system_manifest = self.fs / 'usr/share/glvnd/egl_vendor.d/10_nvidia.json'
        self.system_manifest.write_text('')
        (self.fs / 'proc/driver/nvidia/version').write_text('NVRM version: NVIDIA UNIX Open Kernel Module 595.58.03\n')
        (self.fs / 'opt/nvidia-drivers/.driver-version').write_text(self.version)
        (self.fs / 'usr/lib/xorg/modules/nvidia/drivers/nvidia_drv.so').write_text('DDX fixture')
        (self.fs / 'etc/ld.so.conf.d/zz-nvidia-drivers.conf').write_text(
            ''.join(str(self.fs / f'opt/nvidia-drivers/lib{bits}') + '\n' for bits in (64, 32)))
        for bits, machine in ((64, 'elf_x86_64'), (32, 'elf_i386')):
            source = self.base / f'fixture{bits}.s'
            source.write_text('.text\n.global __egl_Main\n.global vk_icdGetInstanceProcAddr\n.global fixture_version\n.global gbmint_get_backend\n__egl_Main:\nvk_icdGetInstanceProcAddr:\nfixture_version:\ngbmint_get_backend:\n mov $595, %eax\n ret\n.section .note.GNU-stack,"",@progbits\n')
            obj = source.with_suffix('.o')
            subprocess.run(['as', f'--{bits}', '-o', str(obj), str(source)], check=True)
            libdir = self.fs / f'opt/nvidia-drivers/lib{bits}'
            library = libdir / f'libEGL_nvidia.so.{self.version}'
            subprocess.run(['ld', '-m', machine, '-shared', '-soname', 'libEGL_nvidia.so.0', '-o', str(library), str(obj)], check=True)
            (libdir / 'libEGL_nvidia.so.0').symlink_to(library.name)
            subprocess.run(['ld', '-m', machine, '-shared', '-soname', 'libnvidia-allocator.so.1', '-o', str(libdir / f'libnvidia-allocator.so.{self.version}'), str(obj)], check=True)
        (self.fs / 'opt/nvidia-drivers/lib64/nvidia_icd.json').write_text(json.dumps({'file_format_version': '1.0.0', 'ICD': {'library_path': 'libGLX_nvidia.so.0', 'api_version': '1.4.303'}}))
        self.bin = self.base / 'bin'
        self.bin.mkdir()
        for name, body in [('nvidia-smi', 'echo 595.58.03'), ('ldconfig', ':'),
                           ('curl', 'echo UNEXPECTED_DOWNLOAD >&2; exit 99')]:
            script = self.bin / name
            script.write_text('#!/bin/bash\n' + body + '\n')
            script.chmod(0o755)
        self.env = {**os.environ, 'PATH': f'{self.bin}:{os.environ["PATH"]}'}
        helper = ROOT / 'scripts/dpad-nvidia-egl'
        if helper.exists():
            # Relocate the production filesystem boundary and owner for an
            # unprivileged fixture; the executable exposes no test override.
            code = helper.read_text().replace('OWNER = 0', f'OWNER = {os.getuid()}')
            code = code.replace('TRUST_ROOT = Path("/")', f'TRUST_ROOT = Path({str(self.fs)!r})')
            for prefix in ('/opt/', '/etc/', '/usr/', '/run/', '/proc/driver/'):
                code = code.replace('"' + prefix, '"' + str(self.fs) + prefix)
            target = self.fs / 'opt/dpadcloud/dpad-nvidia-egl'
            target.write_text(code)
            target.chmod(0o755)
        code = (ROOT / 'scripts/install-display-drivers').read_text()
        for prefix in ('/opt/', '/etc/', '/usr/', '/proc/driver/'):
            code = code.replace(prefix, str(self.fs) + prefix)
        self.installer = self.base / 'installer'
        self.installer.write_text(code)
        self.manifest = self.fs / 'run/dpad-nvidia/egl.json'

    def gbm_alias(self, bits):
        arch = 'x86_64' if bits == 64 else 'i386'
        return self.fs / f'usr/lib/{arch}-linux-gnu/gbm/nvidia-drm_gbm.so'

    def test_gbm_repairs_empty_old_allocator_for_both_abis(self):
        for bits in (64, 32):
            alias = self.gbm_alias(bits)
            alias.parent.mkdir(parents=True)
            old = alias.parent.parent / 'libnvidia-allocator.so.580.1'
            old.touch()
            alias.symlink_to(old)
        result = self.run_installer()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        for bits in (64, 32):
            alias = self.gbm_alias(bits)
            self.assertEqual(alias.resolve(), self.fs / f'opt/nvidia-drivers/graphics/lib{bits}/libnvidia-allocator.so.{self.version}')
            self.assertEqual(alias.lstat().st_uid, os.getuid())
            self.assertEqual(alias.read_bytes()[4], 2 if bits == 64 else 1)
            self.assertEqual((alias.parent.parent / 'libnvidia-allocator.so.580.1').read_bytes(), b'')
        probe = subprocess.run(['python3', '-c', 'import ctypes,sys; print(ctypes.CDLL(sys.argv[1]).gbmint_get_backend())', str(self.gbm_alias(64))], text=True, capture_output=True)
        self.assertEqual(probe.returncode, 0, probe.stderr)
        self.assertEqual(probe.stdout.strip(), '595')
        self.assertEqual(self.helper('check').returncode, 0)
        self.gbm_alias(32).unlink()
        self.assertNotEqual(self.helper('check').returncode, 0)

    def test_gbm_rejects_invalid_allocator_both_abis(self):
        for bits in (64, 32):
            exact = self.fs / f'opt/nvidia-drivers/lib{bits}/libnvidia-allocator.so.{self.version}'
            good = exact.read_bytes()
            for bad in (b'', good[:20], good[:4] + bytes([1 if bits == 64 else 2]) + good[5:]):
                exact.write_bytes(bad)
                self.assertNotEqual(self.run_installer().returncode, 0)
            exact.write_bytes(good)

    def test_gbm_rejects_writable_or_escaping_alias_paths(self):
        alias = self.gbm_alias(64)
        alias.parent.mkdir(parents=True)
        alias.parent.chmod(0o777)
        self.assertNotEqual(self.run_installer().returncode, 0)
        alias.parent.chmod(0o755)
        victim = self.base / 'victim'
        victim.write_text('untouched')
        alias.symlink_to(victim)
        self.assertNotEqual(self.run_installer().returncode, 0)
        self.assertEqual(victim.read_text(), 'untouched')

    def run_installer(self):
        return subprocess.run(['bash', str(self.installer)], env=self.env, text=True, capture_output=True)

    def marker_library(self, directory, soname, marker, bits=64):
        directory.mkdir(parents=True, exist_ok=True)
        source = self.base / 'marker.s'
        source.write_text('.text\n.global review_marker\nreview_marker:\n mov $' + str(marker) + ', %eax\n ret\n.section .note.GNU-stack,"",@progbits\n')
        obj = source.with_suffix('.o')
        subprocess.run(['as', f'--{bits}', '-o', str(obj), str(source)], check=True)
        subprocess.run(['ld', '-m', 'elf_x86_64' if bits == 64 else 'elf_i386',
                        '-shared', '-soname', soname, '-o', str(directory / soname), str(obj)], check=True)

    def test_real_loader_preserves_toolkit_and_configured_cuda_compat(self):
        self.assert_loader_isolation(cold=False)

    def test_cold_real_loader_preserves_toolkit_and_configured_cuda_compat(self):
        self.assert_loader_isolation(cold=True)

    def assert_loader_isolation(self, cold):
        toolkit = self.base / 'toolkit'
        compat = self.base / 'cuda-compat'
        for name in ('libcuda.so.1', 'libnvidia-encode.so.1'):
            self.marker_library(toolkit, name, 111)
            for bits in (64, 32):
                self.marker_library(self.fs / f'opt/nvidia-drivers/lib{bits}', name, 222, bits)
        self.marker_library(compat, 'libcuda.so.1', 123)
        self.marker_library(toolkit, 'libEGL_nvidia.so.0', 580)
        if cold:
            self.prepare_cold_package()
        conf = self.fs / 'etc/ld.so.conf.d/0-compat-cuda.conf'
        conf.write_text(str(compat) + '\n' + str(toolkit) + '\n')
        registered = self.fs / 'etc/ld.so.conf.d/zz-nvidia-drivers.conf'
        combined = self.base / 'ld.so.conf'
        combined.write_text(f'include {conf}\ninclude {registered}\n')
        cache = self.base / 'ld.so.cache'
        # Real ldconfig on both the old broad configuration and its replacement;
        # all writes are confined to the fixture cache and library directories.
        ldconfig = self.bin / 'ldconfig'
        ldconfig.write_text('#!/bin/bash\nif [ "${1:-}" = -n ]; then exec /sbin/ldconfig "$@"; fi\n'
                            + f'exec /sbin/ldconfig -X -C "{cache}" -f "{combined}"\n')
        subprocess.run([str(ldconfig)], check=True)
        result = self.run_installer()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self.helper('check').returncode, 0)
        entry = (ROOT / 'entrypoint.sh').read_text()
        line = next(line for line in entry.splitlines() if line.startswith('export LD_LIBRARY_PATH="/opt/nvidia-drivers/'))
        line = line.replace('/opt/', str(self.fs) + '/opt/')
        # Use the real glibc cache, relocated inside a private loader copy by
        # replacing its fixed cache pathname with an inherited fd pathname.
        # No chroot, host cache writes, GPU, or privileged operation is needed.
        self.assertEqual(registered.read_text().splitlines(),
                         [str(self.fs / f'opt/nvidia-drivers/graphics/lib{bits}') for bits in (64, 32)])
        probe = "import ctypes; print(*(ctypes.CDLL(n).review_marker() for n in ('libcuda.so.1', 'libnvidia-encode.so.1')))"
        with cache.open('rb') as cache_fd:
            path = f'/dev/fd/{cache_fd.fileno()}'.encode() + b'\0'
            loader_bytes = Path('/lib64/ld-linux-x86-64.so.2').read_bytes()
            original = b'/etc/ld.so.cache\0'
            self.assertEqual(loader_bytes.count(original), 1)
            self.assertLessEqual(len(path), len(original))
            loader = self.base / 'ld-fixture.so'
            loader.write_bytes(loader_bytes.replace(original, path.ljust(len(original), b'\0')))
            loader.chmod(0o755)
            for scenario, inherited, expected in [('toolkit', str(toolkit), '111 111'),
                                                   ('configured CUDA cache', '', '123 111')]:
                with self.subTest(scenario=scenario):
                    env = {**self.env, 'LD_LIBRARY_PATH': inherited}
                    command = [str(loader), shutil.which('python3'), '-c', probe]
                    baseline = subprocess.run(command, env=env, pass_fds=(cache_fd.fileno(),), text=True, capture_output=True)
                    self.assertEqual(baseline.stdout.strip(), expected, baseline.stderr)
                    effective = subprocess.run(['bash', '-c', line + '\nexec "$@"', 'fixture', *command],
                                               env=env, pass_fds=(cache_fd.fileno(),), text=True, capture_output=True)
                    print(f'{scenario}: baseline={baseline.stdout.strip()} candidate={effective.stdout.strip()} expected={expected}', flush=True)
                    self.assertEqual(effective.returncode, 0, effective.stderr)
                    self.assertEqual(effective.stdout.strip(), expected)
                    egl_probe = "import ctypes; print(ctypes.CDLL('libEGL_nvidia.so.0').fixture_version())"
                    egl = subprocess.run(['bash', '-c', line + '\nexec "$@"', 'fixture',
                                          str(loader), shutil.which('python3'), '-c', egl_probe],
                                         env=env, pass_fds=(cache_fd.fileno(),), text=True, capture_output=True)
                    self.assertEqual(egl.returncode, 0, egl.stderr)
                    self.assertEqual(egl.stdout.strip(), '595')
        for bits in (64, 32):
            directory = self.fs / f'opt/nvidia-drivers/graphics/lib{bits}'
            self.assertEqual((directory / 'libEGL_nvidia.so.0').resolve().name,
                             'libEGL_nvidia.so.' + self.version)
            self.assertFalse((directory / 'libcuda.so.1').exists())
            self.assertFalse((directory / 'libnvidia-encode.so.1').exists())

    def test_graphics_dependencies_load_and_non_graphics_are_not_published(self):
        # Explicit regression inventory independent of the implementation set.
        retained = ('libGLX_nvidia', 'libGLESv1_CM_nvidia', 'libGLESv2_nvidia',
                    'libnvidia-eglcore', 'libnvidia-glcore', 'libnvidia-glsi',
                    'libnvidia-glvkspirv', 'libnvidia-gpucomp', 'libnvidia-rtcore',
                    'libnvidia-allocator', 'libnvidia-tls', 'libnvidia-vulkan-producer',
                    'libnvidia-egl-gbm', 'libnvidia-egl-wayland',
                    'libnvidia-egl-xcb', 'libnvidia-egl-xlib')
        excluded = ('libcuda', 'libnvidia-encode', 'libnvcuvid', 'libnvoptix',
                    'libnvidia-ml', 'libnvidia-ptxjitcompiler', 'libnvidia-nvvm',
                    'libnvidia-fatbinaryloader', 'libnvidia-fbc', 'libEGL', 'libGLdispatch',
                    'libnvidia-eglcore-invented')
        for bits in (64, 32):
            raw = self.fs / f'opt/nvidia-drivers/lib{bits}'
            for stem in (*retained, *excluded):
                self.marker_library(raw, stem + '.so.1', 42, bits)
            # Real DT_NEEDED closure: dropping any retained graphics dependency
            # prevents the production helper's fresh ELF64 dlopen from succeeding.
            exact = raw / ('libEGL_nvidia.so.' + self.version)
            subprocess.run(['ld', '-m', 'elf_x86_64' if bits == 64 else 'elf_i386',
                            '-shared', '-soname', 'libEGL_nvidia.so.0', '-o', str(exact),
                            str(self.base / f'fixture{bits}.o'), '--no-as-needed',
                            *(str(raw / (stem + '.so.1')) for stem in retained)], check=True)
            # Version-coupled mapped core libraries must use the driver suffix.
            for stem in retained:
                if stem in ('libnvidia-glsi', 'libnvidia-eglcore', 'libnvidia-glcore', 'libnvidia-glvkspirv'):
                    file = raw / (stem + '.so.1')
                    file.rename(raw / (stem + '.so.' + self.version))
                    file.symlink_to(stem + '.so.' + self.version)
        for cold in (False, True):
            with self.subTest(cold=cold):
                if cold:
                    self.prepare_cold_package()
                result = self.run_installer()
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertEqual(self.helper('check').returncode, 0)
                for bits in (64, 32):
                    directory = self.fs / f'opt/nvidia-drivers/graphics/lib{bits}'
                    for stem in retained:
                        self.assertTrue((directory / (stem + '.so.1')).exists(), stem)
                    for stem in excluded:
                        self.assertFalse((directory / (stem + '.so.1')).exists(), stem)

    def test_projection_contamination_rejected_and_warm_publication_repairs_it(self):
        self.assertEqual(self.run_installer().returncode, 0)
        directory = self.fs / 'opt/nvidia-drivers/graphics/lib64'
        self.marker_library(directory, 'libcuda.so.1', 222)
        self.assertNotEqual(self.helper('check').returncode, 0)
        self.assertEqual(self.run_installer().returncode, 0)
        self.assertFalse((directory / 'libcuda.so.1').exists())
        self.assertEqual(self.helper('check').returncode, 0)

    def test_graphics_alias_cannot_publish_compute_and_projection_paths_are_protected(self):
        raw = self.fs / 'opt/nvidia-drivers/lib64'
        self.marker_library(raw, 'libcuda.so.1', 222)
        (raw / 'libnvidia-egl-gbm.so.1').symlink_to('libcuda.so.1')
        self.assertNotEqual(self.run_installer().returncode, 0)
        (raw / 'libnvidia-egl-gbm.so.1').unlink()
        graphics = self.fs / 'opt/nvidia-drivers/graphics'
        if graphics.exists():
            shutil.rmtree(graphics)
        graphics.symlink_to(self.base)
        self.assertNotEqual(self.run_installer().returncode, 0)
        graphics.unlink()
        graphics.mkdir(mode=0o777)
        graphics.chmod(0o777)
        self.assertNotEqual(self.run_installer().returncode, 0)

    def test_cached_empty_manifest_is_repaired_and_loads_exact_elf(self):
        result = self.run_installer()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertTrue(self.manifest.is_file(), 'cached installer left NVIDIA EGL unregistered')
        data = json.loads(self.manifest.read_text())
        self.assertEqual(data['ICD']['library_path'], 'libEGL_nvidia.so.0')
        env = {**self.env, 'LD_LIBRARY_PATH': str(self.fs / 'opt/nvidia-drivers/graphics/lib64')}
        probe = subprocess.run(['python3', '-c', 'import ctypes; print(ctypes.CDLL("libEGL_nvidia.so.0").fixture_version())'], env=env, text=True, capture_output=True)
        self.assertEqual(probe.returncode, 0, probe.stderr)
        self.assertEqual(probe.stdout.strip(), '595')
        self.assertEqual(self.system_manifest.read_bytes(), b'')

    def helper(self, action):
        return subprocess.run([str(self.fs / 'opt/dpadcloud/dpad-nvidia-egl'), action],
                              env=self.env, text=True, capture_output=True)

    def test_missing_and_stale_system_manifests_are_never_written(self):
        for content in (None, '{"file_format_version":"1.0.0","ICD":{"library_path":"libEGL_nvidia.so.580.1"}}'):
            with self.subTest(content=content):
                if content is None:
                    self.system_manifest.unlink(missing_ok=True)
                else:
                    self.system_manifest.write_text(content)
                    self.system_manifest.chmod(0o444)
                result = self.run_installer()
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertEqual(self.system_manifest.read_text() if self.system_manifest.exists() else None, content)
                self.assertEqual(self.helper('check').returncode, 0)
                icd = json.loads((self.manifest.parent / 'nvidia_icd.json').read_text())
                self.assertEqual(icd['ICD']['api_version'], '1.4.303')

    def test_runtime_stale_manifest_is_atomically_replaced(self):
        self.assertEqual(self.run_installer().returncode, 0)
        for content in ('', '{"ICD":{"library_path":"libEGL_mesa.so.0"}}'):
            self.manifest.write_text(content)
            with self.manifest.open() as old:
                result = self.run_installer()
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(old.read(), content)  # old inode was not truncated
                self.assertEqual(self.manifest.stat().st_mode & 0o777, 0o644)
                self.assertEqual(self.manifest.stat().st_uid, os.getuid())
                self.assertEqual(self.helper('check').returncode, 0)

    def test_stock_595_manifest_101_preserves_private_manifest_semantics(self):
        source = self.fs / 'opt/nvidia-drivers/lib64/nvidia_icd.json'
        stock = '{"file_format_version":"1.0.1","ICD":{"library_path":"libGLX_nvidia.so.0","api_version":"1.4.329"}}'
        source.write_text(stock)
        for cold in (False, True):
            with self.subTest(cold=cold):
                if cold:
                    self.prepare_cold_package()
                result = self.run_installer()
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertEqual(self.helper('check').returncode, 0)
                self.assertEqual(source.read_text(), stock)
                self.assertEqual(json.loads(self.manifest.read_text()), {
                    'file_format_version': '1.0.0',
                    'ICD': {'library_path': 'libEGL_nvidia.so.0'}})
                self.assertEqual(json.loads((self.manifest.parent / 'nvidia_icd.json').read_text()), {
                    'file_format_version': '1.0.0',
                    'ICD': {'library_path': 'libEGL_nvidia.so.0', 'api_version': '1.4.329'}})

    def test_unsupported_manifest_versions_and_invalid_api_fields_fail_closed(self):
        source = self.fs / 'opt/nvidia-drivers/lib64/nvidia_icd.json'
        invalid = [
            {'file_format_version': version, 'ICD': {
                'library_path': 'libGLX_nvidia.so.0', 'api_version': '1.4.329'}}
            for version in (None, 1, '1.0.2', '1.1.0', '2.0.0', '1.0.1 ')
        ]
        invalid += [{'file_format_version': '1.0.1', 'ICD': icd}
                    for icd in ({}, None, {'api_version': None},
                                {'api_version': '2.4.329'}, {'api_version': '1.4.329junk'})]
        for metadata in invalid:
            with self.subTest(metadata=metadata):
                source.write_text(json.dumps(metadata))
                result = self.run_installer()
                self.assertNotEqual(result.returncode, 0, result.stdout)
                self.assertFalse(self.manifest.exists())
                self.assertFalse((self.manifest.parent / 'nvidia_icd.json').exists())

    def test_zero_missing_wrong_arch_or_stale_library_fails_closed(self):
        for bits in (32, 64):
            exact = self.fs / f'opt/nvidia-drivers/lib{bits}/libEGL_nvidia.so.{self.version}'
            original = exact.read_bytes()
            for bad in (b'', b'not ELF', original[:20], original[:4] + bytes([1 if bits == 64 else 2]) + original[5:], None):
                with self.subTest(bits=bits, bad=bad is None):
                    if bad is None:
                        exact.unlink()
                    else:
                        exact.write_bytes(bad)
                    result = self.run_installer()
                    self.assertNotEqual(result.returncode, 0, result.stdout)
                    self.assertFalse(self.manifest.exists())
                    exact.write_bytes(original)
            alias = exact.parent / 'libEGL_nvidia.so.0'
            alias.unlink()
            stale = exact.parent / 'libEGL_nvidia.so.580.1'
            stale.write_bytes(original)
            alias.symlink_to(stale.name)
            self.assertNotEqual(self.run_installer().returncode, 0)
            alias.unlink()
            alias.symlink_to(exact.name)

    def test_invalid_missing_or_inconsistent_driver_fails_before_download(self):
        version_file = self.fs / 'proc/driver/nvidia/version'
        for text in ('NVRM version: unsupported', 'NVRM version: 580.159.03', ''):
            version_file.write_text(text)
            result = self.run_installer()
            self.assertNotEqual(result.returncode, 0)
            self.assertNotIn('UNEXPECTED_DOWNLOAD', result.stderr)
            self.assertFalse(self.manifest.exists())
        version_file.unlink()
        self.assertNotEqual(self.run_installer().returncode, 0)

    def test_symlinks_writable_roots_and_readonly_publication_fail(self):
        self.manifest.parent.mkdir()
        victim = self.base / 'victim'
        victim.write_text('untouched')
        self.manifest.symlink_to(victim)
        self.assertNotEqual(self.run_installer().returncode, 0)
        self.assertEqual(victim.read_text(), 'untouched')
        self.manifest.unlink()
        for path in (self.manifest.parent, self.fs / 'opt', self.fs / 'opt/nvidia-drivers/lib64'):
            path.chmod(0o777)
            self.assertNotEqual(self.run_installer().returncode, 0)
            path.chmod(0o755)
        self.manifest.parent.chmod(0o555)
        self.assertNotEqual(self.run_installer().returncode, 0)
        self.manifest.parent.chmod(0o755)
        self.manifest.parent.rmdir()
        self.manifest.parent.symlink_to(self.base)
        self.assertNotEqual(self.run_installer().returncode, 0)
        self.assertFalse((self.base / 'egl.json').exists())

    def test_symlinked_ldconfig_and_library_escape_are_rejected(self):
        config = self.fs / 'etc/ld.so.conf.d/zz-nvidia-drivers.conf'
        victim = self.base / 'victim'
        victim.write_text('untouched')
        config.unlink()
        config.symlink_to(victim)
        self.assertNotEqual(self.run_installer().returncode, 0)
        self.assertEqual(victim.read_text(), 'untouched')
        config.unlink()
        config.write_text('cached')
        alias = self.fs / 'opt/nvidia-drivers/lib64/libEGL_nvidia.so.0'
        alias.unlink()
        alias.symlink_to(victim)
        self.assertNotEqual(self.run_installer().returncode, 0)

    def test_missing_helper_and_installer_failure_stop_before_ready(self):
        entry = (ROOT / 'entrypoint.sh').read_text()
        start = entry.index('if ! /opt/dpadcloud/install-display-drivers')
        end = entry.index('# --- Render-node permissions', start)
        block = entry[start:end].replace('/opt/dpadcloud/install-display-drivers', str(self.installer))
        self.installer.chmod(0o755)
        helper = self.fs / 'opt/dpadcloud/dpad-nvidia-egl'
        helper.unlink()
        result = subprocess.run(['bash', '-c', 'set -o pipefail\n' + block + '\necho DPAD_READY'],
                                env=self.env, text=True, capture_output=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn('DPAD_READY', result.stdout)

    def test_old_image_installer_success_cannot_bypass_missing_helper(self):
        entry = (ROOT / 'entrypoint.sh').read_text()
        start = entry.index('if ! /opt/dpadcloud/install-display-drivers')
        end = entry.index('# --- Render-node permissions', start)
        self.installer.write_text('#!/bin/bash\nexit 0\n')
        self.installer.chmod(0o755)
        block = entry[start:end].replace('/opt/dpadcloud/install-display-drivers', str(self.installer))
        block = block.replace('/opt/dpadcloud/dpad-nvidia-egl', str(self.base / 'missing-helper'))
        result = subprocess.run(['bash', '-c', 'set -o pipefail\n' + block + '\necho DPAD_READY'],
                                env=self.env, text=True, capture_output=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn('DPAD_READY', result.stdout)

    def prepare_cold_package(self):
        package = self.base / 'package'
        shutil.copytree(self.fs / 'opt/nvidia-drivers/lib64', package, symlinks=True)
        shutil.copytree(self.fs / 'opt/nvidia-drivers/lib32', package / '32', symlinks=True)
        (package / 'nvidia_drv.so').write_text('DDX fixture')
        runfile = self.base / 'driver.run'
        runfile.write_text('#!/bin/bash\nmkdir -p "$3"\ncp -a "' + str(package) + '/." "$3/"\n')
        curl = self.bin / 'curl'
        curl.write_text('#!/bin/bash\nwhile [ "$1" != -o ]; do shift; done\ncp "' + str(runfile) + '" "$2"\n')
        shutil.rmtree(self.fs / 'opt/nvidia-drivers')

    def test_cold_installer_preserves_both_architectures_and_private_vulkan(self):
        self.prepare_cold_package()
        result = self.run_installer()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self.helper('check').returncode, 0)
        for bits in (32, 64):
            alias = self.fs / f'opt/nvidia-drivers/lib{bits}/libEGL_nvidia.so.0'
            self.assertEqual(alias.resolve().name, 'libEGL_nvidia.so.' + self.version)
        self.assertEqual(self.system_manifest.read_bytes(), b'')

    def test_download_failure_is_fatal(self):
        (self.fs / 'opt/nvidia-drivers/.driver-version').unlink()
        result = self.run_installer()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('UNEXPECTED_DOWNLOAD', result.stderr)
        self.assertFalse(self.manifest.exists())

    def test_mount_targets_are_rejected_without_modifying_them(self):
        helper = self.fs / 'opt/dpadcloud/dpad-nvidia-egl'
        mountinfo = self.base / 'mountinfo'
        helper.write_text(helper.read_text().replace("Path('/proc/self/mountinfo')", f'Path({str(mountinfo)!r})'))
        for target in (self.fs / 'opt', self.fs / 'opt/nvidia-drivers/lib64', self.fs / 'etc/ld.so.conf.d/zz-nvidia-drivers.conf', self.manifest.parent):
            mountinfo.write_text(f'99 1 0:1 / {target} rw - tmpfs tmpfs rw\n')
            result = self.run_installer()
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('mounted installation/publication target', result.stderr)
            self.assertFalse(self.manifest.exists())

    def test_real_process_environment_for_selkies_sway_and_labwc(self):
        entry = (ROOT / 'entrypoint.sh').read_text()
        gst = self.fs / 'opt/gstreamer'
        gst.mkdir()
        (gst / 'gst-env').write_text('export LD_LIBRARY_PATH=/gstreamer-fixture __EGL_VENDOR_LIBRARY_FILENAMES=/mesa-fixture\n')
        runtime = (ROOT / 'scripts/dpad_nvenc.py').read_text()
        runtime = runtime.replace('/run/dpad-nvidia/', str(self.fs) + '/run/dpad-nvidia/')
        (self.fs / 'opt/dpadcloud/dpad_nvenc.py').write_text(runtime)
        publisher = self.fs / 'opt/dpadcloud/dpad-publish-desktop-config'
        publisher.write_text('#!/bin/bash\nexit 0\n')
        publisher.chmod(0o755)
        (self.fs / 'run/dpadcloud').mkdir()
        for program in ('selkies-gstreamer', 'sway', 'labwc'):
            fake = self.bin / program
            fake.write_text('#!/bin/bash\nprintf "%s\\n" "$__EGL_VENDOR_LIBRARY_FILENAMES" "$VK_ICD_FILENAMES" "$LD_LIBRARY_PATH" "${GBM_BACKENDS_PATH-unset}" "${GBM_BACKEND-unset}" > "$PROCESS_ENV"\n')
            fake.chmod(0o755)
            name = 'build_selkies_cmd' if program == 'selkies-gstreamer' else '_launch_' + program
            start = entry.index('    ' + name + '() {')
            stop = entry.index('\n    }', start) + len('\n    }')
            function = entry[start:stop]
            for prefix in ('/opt/', '/run/'):
                function = function.replace(prefix, str(self.fs) + prefix)
            output = self.base / (program + '.env')
            script = 'compositor_egl=nvidia; enc=nvh264enc; stream_fps=60; as_user() { bash -c "$1"; }; _dpad_res() { echo 1920x1080; }; _dpad_quality() { echo "20000 192000"; }; _dpad_w() { echo 1920; }; _dpad_h() { echo 1080; }; USER_HOME="' + str(self.base) + '"\n'
            script += function + '\n'
            script += 'cmd=$(build_selkies_cmd) && as_user "$cmd"' if program == 'selkies-gstreamer' else name + ' wayland-1; wait'
            result = subprocess.run(['bash', '-c', script], env={**self.env, 'PROCESS_ENV': str(output), 'GBM_BACKENDS_PATH': '/unsafe', 'GBM_BACKEND': 'drm'}, text=True, capture_output=True)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            values = output.read_text().splitlines()
            self.assertEqual(values[3:], ['unset', 'unset'])
            self.assertEqual(values[0], str(self.manifest))
            self.assertEqual(values[1], str(self.manifest.parent / 'nvidia_icd.json'))
            self.assertTrue(values[2].startswith(f'{self.fs}/opt/nvidia-drivers/graphics/lib64:{self.fs}/opt/nvidia-drivers/graphics/lib32'))
            if program == 'selkies-gstreamer':
                self.assertIn('/gstreamer-fixture', values[2])

    def test_optional_vulkan_layer_registration_preserves_existing_system_file(self):
        source = self.fs / 'opt/nvidia-drivers/lib64/nvidia_layers.json'
        source.write_text('{"file_format_version":"1.0.0","layer":{"name":"VK_LAYER_NV_optimus"}}')
        target = self.fs / 'etc/vulkan/implicit_layer.d/nvidia_layers.json'
        result = self.run_installer()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(target.read_text()), json.loads(source.read_text()))
        target.write_text('host-mounted fixture: preserve')
        target.chmod(0o444)
        self.assertEqual(self.run_installer().returncode, 0)
        self.assertEqual(target.read_text(), 'host-mounted fixture: preserve')

    def test_version_resolution_is_not_595_specific(self):
        previous = self.version
        for version in ('570.172.08', '580.159.03', '610.1'):
            with self.subTest(version=version):
                for bits in (32, 64):
                    directory = self.fs / f'opt/nvidia-drivers/lib{bits}'
                    (directory / ('libnvidia-allocator.so.' + previous)).rename(directory / ('libnvidia-allocator.so.' + version))
                    (directory / ('libEGL_nvidia.so.' + previous)).rename(directory / ('libEGL_nvidia.so.' + version))
                    alias = directory / 'libEGL_nvidia.so.0'
                    alias.unlink()
                    alias.symlink_to('libEGL_nvidia.so.' + version)
                (self.fs / 'proc/driver/nvidia/version').write_text('NVRM version: ' + version)
                (self.fs / 'opt/nvidia-drivers/.driver-version').write_text(version)
                (self.bin / 'nvidia-smi').write_text('#!/bin/bash\necho ' + version + '\n')
                result = self.run_installer()
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertEqual(self.helper('check').returncode, 0)
                previous = version

    def test_session_unreadable_userspace_or_runtime_directory_fails(self):
        self.manifest.parent.mkdir()
        for path, mode in ((self.fs / 'opt/nvidia-drivers/lib64', 0o700),
                           (self.fs / f'opt/nvidia-drivers/lib64/libEGL_nvidia.so.{self.version}', 0o600),
                           (self.manifest.parent, 0o700)):
            old_mode = path.stat().st_mode & 0o777
            path.chmod(mode)
            result = self.run_installer()
            self.assertNotEqual(result.returncode, 0, result.stdout)
            path.chmod(old_mode)

    def test_loader_environment_wiring(self):
        entry = (ROOT / 'entrypoint.sh').read_text()
        self.assertNotIn('/usr/share/glvnd/egl_vendor.d/10_nvidia.json', entry)
        self.assertEqual(entry.count('local egl_set="__EGL_VENDOR_LIBRARY_FILENAMES=/run/dpad-nvidia/egl.json LD_LIBRARY_PATH=/opt/nvidia-drivers/graphics/lib64:/opt/nvidia-drivers/graphics/lib32"'), 2)
        self.assertIn('. /opt/gstreamer/gst-env; unset GBM_BACKENDS_PATH GBM_BACKEND; export __EGL_VENDOR_LIBRARY_FILENAMES=/run/dpad-nvidia/egl.json VK_ICD_FILENAMES=/run/dpad-nvidia/nvidia_icd.json LD_LIBRARY_PATH=/opt/nvidia-drivers/graphics/lib64:/opt/nvidia-drivers/graphics/lib32:', entry)
        self.assertIn('scripts/dpad-nvidia-egl /opt/dpadcloud/', (ROOT / 'Dockerfile').read_text())


if __name__ == '__main__':
    unittest.main(verbosity=2)
