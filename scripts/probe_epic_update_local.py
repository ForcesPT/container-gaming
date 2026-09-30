#!/usr/bin/python3
"""Account-free, disposable-container Epic update probe. Never sign in here.

Run as dpad under Xvfb in the existing private image, with /workspace mounted
read-only. This observes actual vendor logs before implementing a readiness gate.
It does not certify GPU operation or change the image's default launcher.
"""
import json
import argparse
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
            'Application finished with code', 'Changed service status to',
            'wine_vkCreateInstance', 'Failed to find a suitable pixel format',
            'Required Vulkan extension', 'Failed to create Vulkan',
            'VK_ERROR_', 'Could not create a D3D11 device',
            'D3D11CreateDevice:', 'err:', 'wine:', 'Error:',
            'error:', 'Unhandled exception', 'probe_service_', 'PROBE_',
            'trace:seh:raise_exception', 'trace:seh:call_stack_handlers',
            'trace:seh:dispatch_exception')
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


def collect_runtime_errors(root):
    stages = []
    for path in root.rglob('*.log'):
        if path.is_symlink() or not path.is_file() or path.stat().st_size > 8 * 1024 * 1024:
            continue
        for line in path.read_text(errors='replace').splitlines():
            stage = sanitized_stage(line)
            if stage and stage not in stages:
                stages.append(stage)
    return stages[-30:]


def online_services_evidence(prefix, launched_ns=0):
    """Vendor pre-login markers only; never emit account or environment values."""
    evidence = dict(installed_host=False, installer_success=False,
                    system_service_child=False, service_update_success=False,
                    main_service_ready=False, host_success=False,
                    missing_session_guid=False, starter_init_error=False,
                    minimum_version_not_satisfied=False)
    evidence['installed_host'] = (prefix / 'drive_c/Program Files (x86)/Epic Games/'
                                  'Epic Online Services/service/EpicOnlineServicesHost.exe').is_file()
    for path in prefix.rglob('*.log'):
        if path.is_symlink() or not path.is_file():
            continue
        info = path.stat()
        if info.st_size > 8 * 1024 * 1024 or info.st_mtime_ns < launched_ns:
            continue
        text = path.read_text(errors='replace')
        evidence['installer_success'] |= 'Epic Online Services installer completed with return code: 0' in text
        evidence['minimum_version_not_satisfied'] |= 'MinimumVersionNotSatisfied' in text
        if 'EpicOnlineServices' not in str(path):
            continue
        evidence['system_service_child'] |= bool(re.search(r'"isSystemUser"\s*:\s*true', text))
        evidence['service_update_success'] |= "Outcome: 'DC_UPDATE_SUCCESS'" in text
        evidence['main_service_ready'] |= 'MAINSERVICE_READY' in text
        evidence['host_success'] |= ('EpicOnlineServicesHost-' in path.name
                                     and 'Application finished with code 0' in text)
        evidence['missing_session_guid'] |= 'EOS_SESSION_GUID environment variable is required' in text
        evidence['starter_init_error'] |= 'STARTER_INIT_ERROR' in text
    evidence['local_eos_initialization_passed'] = (
        all(evidence[k] for k in ('installed_host', 'installer_success', 'system_service_child',
                                  'service_update_success', 'main_service_ready', 'host_success'))
        and not any(evidence[k] for k in ('missing_session_guid', 'starter_init_error',
                                         'minimum_version_not_satisfied')))
    evidence['gpu_login_qualified'] = False
    return evidence


def epic_service_configuration(prefix):
    """Fresh account-free prefix only: whitelist service configuration fields."""
    registry = prefix / 'system.reg'
    if not registry.is_file() or registry.stat().st_size > 16 * 1024 * 1024:
        return []
    services = []
    for section in re.split(r'(?=^\[)', registry.read_text(errors='replace'), flags=re.M):
        header = section.splitlines()[0] if section else ''
        if 'Services' not in header or 'Epic' not in header:
            continue
        values = {'section': header}
        for line in section.splitlines()[1:]:
            if any(line.startswith('"' + key + '"=') for key in ('DisplayName', 'ImagePath', 'Type')):
                key, value = line.split('=', 1)
                values[key.strip('"')] = value
        services.append(values)
    return services


def official_update_evidence(prefix, launched_ns):
    child_success = up_to_date = False
    for path in (prefix / 'drive_c').rglob('*.log'):
        if path.is_symlink() or not path.is_file():
            continue
        info = path.stat()
        if info.st_mtime_ns < launched_ns or info.st_size > 16 * 1024 * 1024:
            continue
        text = path.read_text(errors='replace')
        child_success |= 'Self update install commandlet finished with exit code: 0' in text
        up_to_date |= 'Launcher is up-to-date with the latest available version.' in text
    manifest = prefix / 'drive_c/ProgramData/Epic/EpicGamesLauncher/Data/Launcher.manifest'
    current_manifest = manifest.is_file() and not manifest.is_symlink() and manifest.stat().st_size > 0
    return {'commandlet_success': child_success, 'current_manifest': current_manifest,
            'vendor_up_to_date': up_to_date,
            'local_update_completed': bool(child_success and current_manifest and up_to_date),
            'gpu_login_qualified': False}


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
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--backend', choices=('opengl', 'dxvk'), default='opengl')
    parser.add_argument('--observe-seconds', type=int, default=180)
    parser.add_argument('--diagnostics', action='store_true')
    parser.add_argument('--graphics-service-probe', action='store_true')
    parser.add_argument('--without-headless', action='store_true')
    parser.add_argument('--interactive-service', action='store_true')
    parser.add_argument('--direct-proton', action='store_true', help='diagnostic comparison outside the Steam runtime; not production acceptance')
    parser.add_argument('--epic-service-identity', action='store_true', help='fake graphics service at the exact Epic identity, fresh prefix only')
    parser.add_argument('--hold-prefix-seconds', type=int, default=0,
                        help='retain the account-free temporary prefix for bounded same-container diagnosis')
    args = parser.parse_args()
    if (args.without_headless or args.interactive_service or args.direct_proton or args.epic_service_identity) and not args.graphics_service_probe:
        parser.error('service comparison options require --graphics-service-probe')
    if args.without_headless and not args.direct_proton:
        parser.error('the fault ICD is validated only outside the Steam runtime; use --direct-proton')
    if not 30 <= args.observe_seconds <= 180:
        raise SystemExit('observation must be between 30 and 180 seconds')
    if not 0 <= args.hold_prefix_seconds <= 1800:
        parser.error('temporary prefix hold must be between 0 and 1800 seconds')
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
        if args.backend == 'opengl':
            source = source.replace('unset PROTON_USE_WINED3D', 'export PROTON_USE_WINED3D=1')
        wrapper.write_text(source)
        wrapper.chmod(0o700)
        state = root / 'private'
        state.mkdir(mode=0o700)
        software_icd = Path('/usr/share/vulkan/icd.d/lvp_icd.json')
        if args.without_headless:
            software_icd = Path('/workspace/test-results/dpad-lvp-no-headless-probe.json')
        if not software_icd.is_file():
            raise SystemExit('local software Vulkan driver is unavailable; probe refused')
        environment = {**os.environ, 'DPAD_FAUGUS_STATE_ROOT': str(state),
                       'DPAD_EPIC_DIAGNOSTICS': '1' if args.diagnostics else '0',
                       'WINEDEBUG': '-all,err+all,warn+vulkan',
                       'VK_LOADER_DEBUG': 'error,warn',
                       'VK_ICD_FILENAMES': str(software_icd)}
        print(json.dumps({'stage': 'account_free_probe_started',
                          'private_prefix': True, 'graphics': args.backend,
                          'vulkan': 'local_software_only'}), flush=True)
        if args.graphics_service_probe:
            environment.update({'PROTONPATH': '/home/dpad/.steam/debian-installation/compatibilitytools.d/GE-Proton10-34',
                                'WINEPREFIX': str(state / 'prefixes/epic-games'),
                                'GAMEID': 'umu-default', 'UMU_RUNTIME_UPDATE': '0',
                                'PROTON_ENABLE_WAYLAND': '0'})
            environment.update({'WINEDEBUG': '-all,err+all,warn+vulkan',
                                'PROTON_LOG': '1', 'PROTON_LOG_DIR': str(root)})
            if args.backend == 'opengl':
                environment['PROTON_USE_WINED3D'] = '1'
            else:
                environment.pop('PROTON_USE_WINED3D', None)
            report = 'Z:' + str(root / 'graphics-service.json').replace('/', '\\')
            if args.epic_service_identity:
                report = r'C:\dpad-graphics.json'
            with (root / 'graphics.log').open('w') as output:
                command = ['/usr/bin/umu-run', '/workspace/test-results/epic_graphics_service_probe.exe',
                           '--compare', report]
                if args.direct_proton:
                    environment.update({'STEAM_COMPAT_DATA_PATH': environment['WINEPREFIX'],
                                        'STEAM_COMPAT_CLIENT_INSTALL_PATH': '/home/dpad/.steam/debian-installation',
                                        'SteamAppId': '0', 'SteamGameId': '0'})
                    Path(environment['STEAM_COMPAT_DATA_PATH']).mkdir(parents=True, mode=0o700)
                    command = [environment['PROTONPATH'] + '/proton', 'run', *command[1:]]
                if args.interactive_service:
                    command.append('--interactive')
                elif args.epic_service_identity:
                    command.append('--epic-target')
                child = subprocess.Popen(command, env=environment, stdout=output,
                                         stderr=subprocess.STDOUT, start_new_session=True)
                try:
                    deadline = time.monotonic() + 300
                    while child.poll() is None and time.monotonic() < deadline:
                        if any(path.stat().st_size > 8 * 1024 * 1024
                               for path in root.glob('*.log') if path.is_file()):
                            print('PROBE_LOG_LIMIT_REACHED', flush=True)
                            break
                        time.sleep(0.2)
                finally:
                    if child.poll() is None:
                        stop_probe_tree(child)
            print(json.dumps({'stage': 'graphics_service_probe', 'exit': child.returncode,
                              'missing_headless': args.without_headless,
                              'interactive_service': args.interactive_service,
                              'direct_proton': args.direct_proton,
                              'epic_service_identity': args.epic_service_identity,
                              'gpu_qualified': False}), flush=True)
            contexts = []
            reports = {}
            report_file = (Path(environment['WINEPREFIX']) / 'pfx/drive_c/dpad-graphics.json'
                           if args.epic_service_identity else root / 'graphics-service.json')
            for path in [Path(str(report_file) + '.user'), report_file, *root.glob('*.log')]:
                if not path.is_file() or path.stat().st_size > 8 * 1024 * 1024:
                    continue
                for line in path.read_text(errors='replace').splitlines():
                    if line.startswith('{"context":'):
                        context = json.loads(line)
                        if context.get('context') not in contexts:
                            contexts.append(context.get('context'))
                            reports[context['context']] = context
                            print(json.dumps(context), flush=True)
            errors = collect_runtime_errors(root)
            print(json.dumps({'runtime_errors': errors}), flush=True)
            if child.returncode or set(contexts) != {'user', 'service'}:
                raise SystemExit('graphics comparison incomplete; no successful check claimed')
            service_expected = args.backend == 'opengl' or args.interactive_service or args.epic_service_identity or not args.without_headless
            matched = reports['user']['d3d11_ok'] and reports['service']['d3d11_ok'] == service_expected
            if not service_expected:
                matched = matched and any('wine_vkCreateInstance' in line and 'res=-7' in line for line in errors)
            print(json.dumps({'stage': 'graphics_comparison_result', 'matched': bool(matched),
                              'gpu_qualified': False}), flush=True)
            if not matched:
                raise SystemExit('graphics comparison did not match the controlled expectation')
            return
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
                deadline = time.monotonic() + args.observe_seconds
                observed = set()
                observed_services = set()
                while child.poll() is None and time.monotonic() < deadline:
                    if any(path.stat().st_size > 8 * 1024 * 1024
                           for path in root.rglob('*.log') if path.is_file()):
                        print('PROBE_LOG_LIMIT_REACHED', flush=True)
                        break
                    for identity in client_identity(prefix):
                        encoded = json.dumps(identity, sort_keys=True)
                        if encoded not in observed:
                            observed.add(encoded)
                            print(json.dumps({'stage': 'client_identity', **identity}), flush=True)
                    for service in epic_service_configuration(prefix):
                        encoded = json.dumps(service, sort_keys=True)
                        if encoded not in observed_services:
                            observed_services.add(encoded)
                            print(json.dumps({'stage': 'epic_service_configuration', **service}), flush=True)
                    time.sleep(2)
                print(json.dumps({'stage': 'update_observation', 'backend': args.backend,
                                  'exit': child.poll(), 'bounded_stop': child.poll() is None,
                                  'update_readiness_qualified': False,
                                  'vendor_stages': collect_stages(prefix, launched_ns),
                                  'runtime_errors': collect_runtime_errors(root)}), flush=True)
                print(json.dumps({'stage': 'official_update_evidence',
                                  **official_update_evidence(prefix, launched_ns)}), flush=True)
                print(json.dumps({'stage': 'online_services_evidence',
                                  **online_services_evidence(prefix, launched_ns)}), flush=True)
            finally:
                if child.poll() is None:
                    stop_probe_tree(child)
        print(json.dumps({'stage': 'epic_service_configuration_final',
                          'services': epic_service_configuration(prefix)}), flush=True)
        if args.hold_prefix_seconds:
            print(json.dumps({'stage': 'account_free_prefix_diagnostic_hold',
                              'seconds': args.hold_prefix_seconds, 'prefix': str(prefix)}), flush=True)
            hold_deadline = time.monotonic() + args.hold_prefix_seconds
            while time.monotonic() < hold_deadline and not (root / 'end-diagnostic-hold').exists():
                time.sleep(1)
        print('ACCOUNT_FREE_EPIC_UPDATE_PROBE_COMPLETE', flush=True)


if __name__ == '__main__':
    main()
