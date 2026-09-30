#!/usr/bin/python3
"""Account-free, disposable-container Epic update probe. Never sign in here.

Run as dpad under Xvfb in the existing private image, with /workspace mounted
read-only. This observes actual vendor logs before implementing a readiness gate.
It does not certify GPU operation or change the image's default launcher.
"""
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import time

import psutil


def sanitized_stage(line):
    # Deliberately exclude authentication, URLs, account IDs and arbitrary logs.
    tags = ('LogSelfUpdate', 'LogBuildPatchServices', 'Self update install commandlet',
            'Application finished with code', 'Changed service status to')
    if not any(tag in line for tag in tags):
        return None
    if 'Build Stat:' in line:
        return None
    if any(word in line.casefold() for word in ('token', 'auth', 'account', 'password', 'cookie')):
        return None
    line = re.sub(r'https?://\S+', '[url]', line)
    line = re.sub(r'[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+', '[email]', line)
    line = re.sub(r'\b[a-fA-F0-9]{24,}\b', '[id]', line)
    return line[:300]


def collect_stages(prefix, launched_ns):
    roots = [prefix / 'drive_c/users', prefix / 'drive_c/ProgramData/Epic']
    logs = []
    for root in roots:
        for path in root.rglob('*.log'):
            if path.is_symlink() or not path.is_file():
                continue
            info = path.stat()
            if info.st_size > 16 * 1024 * 1024 or info.st_mtime_ns < launched_ns:
                continue
            stages = []
            for line in path.read_text(errors='replace').splitlines():
                stage = sanitized_stage(line)
                if stage:
                    stages.append({'file': path.name, 'stage': stage})
            if stages:
                logs.append((info.st_mtime_ns, stages[-12:]))
    # Filesystem enumeration order is unrelated to updater launch order.
    return [stage for _, stages in sorted(logs)[-6:] for stage in stages]


def client_identity(prefix):
    """Only identity booleans, never command lines or environment values."""
    executable = str(prefix / 'drive_c/Program Files/Epic Games/Launcher/Portal/Binaries/Win64/EpicGamesLauncher.exe')
    windows = r'C:\Program Files\Epic Games\Launcher\Portal\Binaries\Win64\EpicGamesLauncher.exe'
    identities = []
    for process in psutil.process_iter():
        try:
            if process.uids().effective != os.geteuid():
                continue
            if not any(arg.casefold() in (executable.casefold(), windows.casefold())
                       for arg in process.cmdline()):
                continue
            environment = process.environ()
            identities.append({'name': process.name(),
                               'exact_executable': True,
                               'exact_prefix': environment.get('WINEPREFIX') == str(prefix),
                               'umu_pfx_alias': environment.get('WINEPREFIX', '').rstrip('/') == str(prefix / 'pfx'),
                               'managed_marker': environment.get('FAUGUSID') == 'dpad-epic',
                               'opengl': environment.get('PROTON_USE_WINED3D') == '1'})
        except (psutil.Error, OSError):
            continue
    return identities


def stop_probe_tree(child):
    # This container is disposable and contains no accounts or user sessions.
    processes = []
    try:
        owner = psutil.Process(child.pid)
        processes = owner.children(recursive=True) + [owner]
    except psutil.NoSuchProcess:
        pass
    for process in reversed(processes):
        try:
            process.terminate()
        except psutil.NoSuchProcess:
            pass
    _, remaining = psutil.wait_procs(processes, timeout=10)
    for process in remaining:
        try:
            process.kill()
        except psutil.NoSuchProcess:
            pass
    child.wait(timeout=15)


def main():
    if (os.geteuid() == 0 or not os.environ.get('DISPLAY')
            or not Path('/.dockerenv').is_file()):
        raise SystemExit('run as the image user under Xvfb in a disposable container')
    with tempfile.TemporaryDirectory(prefix='dpad-epic-update-probe-') as temporary:
        root = Path(temporary)
        scripts = root / 'scripts'
        scripts.mkdir(mode=0o700)
        for name in ('faugus-epic-launch', 'dpad_faugus_prepare.py',
                     'dpad_epic_resume.py', 'dpad_epic_updater_failed.py'):
            shutil.copyfile(Path('/opt/dpadcloud') / name, scripts / name)
        wrapper = scripts / 'faugus-epic-launch'
        source = wrapper.read_text()
        if source.count('unset PROTON_USE_WINED3D') != 1:
            raise SystemExit('installed wrapper changed; probe refused')
        wrapper.write_text(source.replace('unset PROTON_USE_WINED3D', 'export PROTON_USE_WINED3D=1'))
        wrapper.chmod(0o700)
        state = root / 'private'
        state.mkdir(mode=0o700)
        software_icd = Path('/usr/share/vulkan/icd.d/lvp_icd.json')
        if not software_icd.is_file():
            raise SystemExit('local software Vulkan driver is unavailable; probe refused')
        environment = {**os.environ, 'DPAD_FAUGUS_STATE_ROOT': str(state),
                       'DPAD_EPIC_DIAGNOSTICS': '0',
                       'VK_ICD_FILENAMES': str(software_icd)}
        print(json.dumps({'stage': 'account_free_probe_started',
                          'private_prefix': True, 'graphics': 'opengl',
                          'vulkan': 'local_software_only'}), flush=True)
        with (root / 'prepare.log').open('w') as output:
            prepared = subprocess.run([str(wrapper), '--prepare-only'], env=environment,
                                      stdout=output, stderr=subprocess.STDOUT, timeout=340)
        print(json.dumps({'stage': 'silent_msi', 'exit': prepared.returncode}), flush=True)
        if prepared.returncode:
            raise SystemExit('silent install failed; no launcher probe performed')
        prefix = state / 'prefixes/epic-games'
        launched_ns = time.time_ns()
        with (root / 'launch.log').open('w') as output:
            child = subprocess.Popen([str(wrapper)], env=environment, stdout=output,
                                     stderr=subprocess.STDOUT, start_new_session=True)
            try:
                deadline = time.monotonic() + 180
                observed = set()
                while child.poll() is None and time.monotonic() < deadline:
                    for identity in client_identity(prefix):
                        encoded = json.dumps(identity, sort_keys=True)
                        if encoded not in observed:
                            observed.add(encoded)
                            print(json.dumps({'stage': 'client_identity', **identity}), flush=True)
                    time.sleep(2)
                print(json.dumps({'stage': 'opengl_update_observation',
                                  'exit': child.poll(), 'bounded_stop': child.poll() is None,
                                  'update_readiness_qualified': False,
                                  'vendor_stages': collect_stages(prefix, launched_ns)}), flush=True)
            finally:
                if child.poll() is None:
                    stop_probe_tree(child)
        print('ACCOUNT_FREE_EPIC_UPDATE_PROBE_COMPLETE', flush=True)


if __name__ == '__main__':
    main()
