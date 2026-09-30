"""Real FUSE/storage acceptance in a disposable container, without an account."""
import base64
import hashlib
import importlib.util
import json
import os
from pathlib import Path
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
