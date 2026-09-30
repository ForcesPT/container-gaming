"""Real FUSE/storage acceptance in a disposable container, without an account."""
import base64
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
import tempfile

if os.environ.get('DPAD_TEST_EPIC_OVERLAY') != '1':
    raise SystemExit('disposable-container opt-in required')
sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_epic_installation import fixture
from dpad_epic_overlay import prepare

with tempfile.TemporaryDirectory() as temp:
    root = Path(temp)
    binding, capsule, digest, source, _, _ = fixture(root)
    original = (source / 'Game.exe').read_bytes()
    (source / 'Game.exe').chmod(0o444)
    source.chmod(0o555)
    root.chmod(0o755)
    base = Path('/opt/dpad-instant'); base.mkdir()
    for name, content in [('game', source), ('epic', capsule)]:
        target = base / name; target.mkdir()
        subprocess.run(['mount', '--bind', str(content), str(target)], check=True)
        subprocess.run(['mount', '-o', 'remount,bind,ro', str(target)], check=True)
    prepare(binding, digest)
    merged = base / 'official-game'
    assert merged.stat().st_dev != (Path('/run/dpadcloud/epic-cow') / 'upper').stat().st_dev
    env = {**os.environ, 'HOME': '/home/dpad', 'DPAD_FAUGUS_INSTANT_TEST': '1',
           'DPAD_EPIC_INSTALLATION_BINDING': base64.b64encode(json.dumps(binding).encode()).decode(),
           'DPAD_EPIC_INSTALLATION_SHA256': digest}
    if os.environ.get('DPAD_TEST_EPIC_PACKAGED_STARTUP') == '1':
        # Exercise packaged entry points with only the Electron picker replaced.
        # Real template cloning, prefix selection and registration remain intact.
        picker = Path('/opt/dpadcloud/launcher/dpad-launcher')
        original, mode = picker.read_bytes(), picker.stat().st_mode
        marker = Path('/tmp/dpad-test-picker-started')
        picker.write_text('#!/bin/bash\ntouch /tmp/dpad-test-picker-started\n')
        picker.chmod(0o755)
        env.update(DPAD_EPIC_BACKEND='faugus', DPAD_INSTANT_APP=binding['app'],
                   DPAD_INSTANT_METADATA='fixture-not-used-by-official-route')
        if os.environ.get('DPAD_TEST_EPIC_VOLUME') == '1':
            volume = Path('/home/dpad/test-volume'); volume.mkdir(mode=0o700)
            import pwd
            user = pwd.getpwnam('dpad'); os.chown(volume, user.pw_uid, user.pw_gid)
            env['DPAD_VOLUME_MOUNT'] = str(volume)
            prefix = volume / 'faugus/prefixes/epic-games'
        else:
            prefix = Path('/home/dpad/Faugus/epic-games')
        try:
            subprocess.run(['runuser', '-u', 'dpad', '--', '/bin/bash', '/opt/dpadcloud/launcher-shell'],
                           env=env, check=True, capture_output=True, text=True, timeout=90)
            assert marker.is_file(), 'picker did not start after registration'
            executable = prefix / 'drive_c/Program Files/Epic Games/Launcher/Portal/Binaries/Win64/EpicGamesLauncher.exe'
            assert executable.is_file(), 'preinstalled official client was not cloned'
            assert (prefix / 'drive_c/DpadPlay/Games/FixtureGame').readlink() == merged
            item = prefix / 'drive_c/ProgramData/Epic/EpicGamesLauncher/Data/Manifests/FixtureGame_guid.item'
            assert json.loads(item.read_text())['InstallLocation'] == 'C:\\DpadPlay\\Games\\FixtureGame'
            assert stat.S_IMODE(prefix.stat().st_mode) == 0o700
            if env.get('DPAD_VOLUME_MOUNT'):
                assert not Path('/home/dpad/Faugus/epic-games').exists(), 'registration used the wrong home prefix'
            # A second startup must retain the client and the existing game entry.
            guid = re.findall(r'"MachineGuid"="([^"]+)"', (prefix / 'system.reg').read_text())
            assert len(guid) == 1 and guid[0] != '00000000-0000-0000-0000-000000000000'
            subprocess.run(['runuser', '-u', 'dpad', '--', '/bin/bash', '/opt/dpadcloud/launcher-shell'],
                           env=env, check=True, capture_output=True, text=True, timeout=90)
            assert re.findall(r'"MachineGuid"="([^"]+)"', (prefix / 'system.reg').read_text()) == guid
            inventory = json.loads((prefix / 'drive_c/ProgramData/Epic/UnrealEngineLauncher/LauncherInstalled.dat').read_text())
            assert len([row for row in inventory['InstallationList'] if row['AppName'] == 'FixtureGame']) == 1
            print('PACKAGED_EPIC_PREPARE_REGISTER_REPLAY_OK mode=' + ('volume' if env.get('DPAD_VOLUME_MOUNT') else 'home'))
        finally:
            picker.write_bytes(original); picker.chmod(mode)
    else:
        result = subprocess.run(['runuser', '-u', 'dpad', '--', '/usr/bin/python3', '-I',
                                 str(Path(__file__).with_name('dpad_epic_installation.py')), 'register'],
                                env=env, check=True, capture_output=True, text=True, timeout=20)
        assert 'DPAD_INSTANT_INSTALLATION official_epic_registered' in result.stdout
    # Atomic updater replacement and new user state must affect only the COW view.
    code = "from pathlib import Path; p=Path('/opt/dpad-instant/official-game'); (p/'Game.exe.new').write_bytes(b'private replacement'); (p/'Game.exe.new').replace(p/'Game.exe'); (p/'private-save').write_text('session-only')"
    subprocess.run(['runuser', '-u', 'dpad', '--', 'python3', '-I', '-c', code], check=True)
    assert (merged / 'Game.exe').read_bytes() == b'private replacement'
    assert (source / 'Game.exe').read_bytes() == original
    assert stat.S_IMODE(source.stat().st_mode) == 0o555
    assert stat.S_IMODE((source / 'Game.exe').stat().st_mode) == 0o444
    assert sorted(p.name for p in source.iterdir()) == ['Game.exe']
    assert (merged / '.egstore/fixture.manifest').is_file()
    assert not (source / '.egstore').exists()
    subprocess.run(['fusermount3', '-u', str(merged)], check=True)
    print('REAL_FUSE_COW_AND_PRIVATE_OFFICIAL_REGISTRATION_OK')
    print('No account, real vendor manifest, launcher UI or game was exercised.')
