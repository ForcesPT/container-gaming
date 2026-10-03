"""Real Docker/FUSE restart qualification. Creates only account-free fixtures.

The packaged Instant entrypoint and overlay setup run with fixture-only error
verbosity. A sentinel replaces the downstream desktop and checks registration.
All containers are new, network-disabled and removed by immutable identity.
"""
import argparse
import json
from pathlib import Path
import subprocess
import tempfile
import time
import uuid

BASE = 'sha256:d2955c976a42bef21fa9bc0d5b4155ce976152d64b157a519431fdf192fb6d3f'
ROOT = Path(__file__).resolve().parents[1]

BOOT = r"""
import base64, json, os, stat, subprocess, sys
from pathlib import Path
sys.path.insert(0, '/tmp/fixture-scripts')
from test_epic_installation import fixture
state = Path('/fixture'); state.mkdir(exist_ok=True)
record = state / 'record.json'
if not record.exists():
    binding, capsule, digest, source, _, _ = fixture(state)
    (source / 'Game.exe').chmod(0o444); source.chmod(0o555)
    record.write_text(json.dumps(dict(binding=binding, capsule=str(capsule),
                                    digest=digest, source=str(source))))
data = json.loads(record.read_text())
base = Path('/opt/dpad-instant'); base.mkdir(exist_ok=True)
for name, content in [('game', data['source']), ('epic', data['capsule'])]:
    target = base / name; target.mkdir(exist_ok=True)
    subprocess.run(['mount', '--bind', content, str(target)], check=True)
    subprocess.run(['mount', '-o', 'remount,bind,ro', str(target)], check=True)
if not Path('/dev/fuse').exists():
    os.mknod('/dev/fuse', stat.S_IFCHR | 0o666, os.makedev(10, 229))
os.environ.update(DPAD_FAUGUS_INSTANT_TEST='1',
    DPAD_EPIC_INSTALLATION_BINDING=base64.b64encode(json.dumps(data['binding']).encode()).decode(),
    DPAD_EPIC_INSTALLATION_SHA256=data['digest'], DPAD_INSTANT_APP=data['binding']['app'],
    DPAD_INSTANT_METADATA=base64.b64encode(json.dumps(data['binding']).encode()).decode())
# Only error verbosity is changed in this account-free fixture. Keep the actual
# preparation and packaged entrypoint control flow, including exit-on-failure.
overlay = Path('/opt/dpadcloud/dpad_epic_overlay.py')
text = overlay.read_text()
text = text.replace('except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError):',
    'except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError) as error:\n'
    '        print(type(error).__name__ + ": " + str(error), file=sys.stderr)')
overlay.write_text(text)
entrypoint = Path('/opt/dpadcloud/entrypoint.sh')
entrypoint.write_text('''#!/bin/bash
set -e
runuser -u dpad -- env HOME=/home/dpad python3 -I /opt/dpadcloud/dpad_epic_installation.py register >/tmp/registration-fixture.log
python3 - <<'CHECK'
from pathlib import Path
import hashlib
import json
lower = Path('/opt/dpad-instant/game/Game.exe')
merged = Path('/opt/dpad-instant/official-game')
assert lower.read_bytes() == b'fixture'
state = Path('/fixture/boots')
boots = int(state.read_text()) if state.exists() else 0
private = merged / 'private-session-marker'
item = Path('/home/dpad/Faugus/epic-games/drive_c/ProgramData/Epic/EpicGamesLauncher/Data/Manifests/FixtureGame_guid.item')
registration = hashlib.sha256(item.read_bytes()).hexdigest()
checkpoint = Path('/fixture/registration-sha256')
if boots:
    assert checkpoint.read_text() == registration
else:
    checkpoint.write_text(registration)
inventory = json.loads(Path('/home/dpad/Faugus/epic-games/drive_c/ProgramData/Epic/UnrealEngineLauncher/LauncherInstalled.dat').read_text())
assert len([row for row in inventory['InstallationList'] if row['AppName'] == 'FixtureGame']) == 1
if boots:
    assert private.read_bytes() == b'active-session-only'
    assert (merged / 'Game.exe').read_bytes() == b'private replacement'
else:
    private.write_bytes(b'active-session-only')
    (merged / 'Game.exe.new').write_bytes(b'private replacement')
    (merged / 'Game.exe.new').replace(merged / 'Game.exe')
state.write_text(str(boots + 1))
print('DPAD_TEST_OVERLAY_READY boot=' + str(boots + 1), flush=True)
CHECK
exec sleep infinity
''')
entrypoint.chmod(0o755)
os.execv('/opt/dpadcloud/faugus-instant-entrypoint',
         ['/opt/dpadcloud/faugus-instant-entrypoint'])
"""


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--image', default=BASE)
    parser.add_argument('--expect', choices=['baseline-failure', 'recovery'], required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if not args.output.is_absolute() or args.output.exists():
        raise SystemExit('Use an absolute new receipt file')
    args.output.parent.mkdir(parents=True, exist_ok=True)

    def run(command, *, check=True):
        return subprocess.run(command, capture_output=True, text=True,
                              check=check, timeout=45)

    identity = None
    name = 'dpad-local-overlay-' + uuid.uuid4().hex[:12]
    evidence = {'image': args.image, 'accountUsed': False, 'network': 'none',
                'paidResourcesCreated': 0, 'productionChanged': False}
    try:
        identity = run(['docker', 'create', '--name', name, '--network', 'none',
                        '--label', 'com.dpadplay.local-fixture=epic-overlay-restart',
                        '--device', '/dev/fuse', '--cap-add', 'SYS_ADMIN', '--security-opt', 'seccomp=unconfined',
                        '--security-opt', 'apparmor=unconfined', '--entrypoint', 'python3',
                        args.image, '/tmp/overlay-restart-boot.py']).stdout.strip()
        assert len(identity) == 64
        run(['docker', 'cp', str(ROOT / 'scripts') + '/.', identity + ':/tmp/fixture-scripts'])
        with tempfile.TemporaryDirectory() as temp:
            boot = Path(temp) / 'boot.py'; boot.write_text(BOOT, encoding='utf-8')
            run(['docker', 'cp', str(boot), identity + ':/tmp/overlay-restart-boot.py'])

        def wait(boot_number):
            deadline = time.monotonic() + 30
            while time.monotonic() < deadline:
                state = json.loads(run(['docker', 'inspect', '--format', '{{json .State}}', identity]).stdout)
                logs = run(['docker', 'logs', '--since', state['StartedAt'], identity]).stdout
                if state['Running'] and f'DPAD_TEST_OVERLAY_READY boot={boot_number}' in logs:
                    return True
                if not state['Running']:
                    assert state['ExitCode'] == 1, 'unexpected fixture exit'
                    evidence['restartExitCode'] = state['ExitCode']
                    result = run(['docker', 'logs', '--since', state['StartedAt'], identity])
                    # This container contains only synthetic fixture data.
                    args.output.with_suffix('.fixture.log').write_text(result.stdout + result.stderr)
                    evidence['overlayRefusal'] = 'Official Epic private game overlay refused' in result.stderr
                    if boot_number == 1:
                        print((result.stdout + result.stderr)[-1500:])
                    return False
                time.sleep(.2)
            raise AssertionError('overlay boot deadline exceeded')

        run(['docker', 'start', identity]); assert wait(1), 'initial overlay boot failed'
        evidence['initialBootPassed'] = True
        run(['docker', 'restart', '--time', '1', identity])
        recovered = wait(2)
        evidence['sameContainerRestartRecovered'] = recovered
        if args.expect == 'baseline-failure':
            assert not recovered and evidence.get('overlayRefusal'), 'baseline did not reproduce'
        else:
            assert recovered, 'same-container overlay restart failed'
            run(['docker', 'restart', '--time', '1', identity]); assert wait(3)
            evidence.update(repeatedRestartPassed=True, activeSessionWritesPreserved=True,
                            sharedLowerUnchanged=True, officialRegistrationReplayPassed=True)
        evidence['status'] = 'baseline-reproduced' if not recovered else 'local-overlay-recovery-qualified'
    finally:
        if identity:
            run(['docker', 'rm', '-f', identity])
            assert run(['docker', 'container', 'inspect', identity], check=False).returncode != 0
        evidence['localContainerRemoved'] = identity is not None
    args.output.write_text(json.dumps(evidence, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(evidence))


if __name__ == '__main__':
    main()
