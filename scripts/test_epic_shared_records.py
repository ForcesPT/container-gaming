"""Opt-in, offline qualification against an account-free genuine game capture.

Mount the game-only capture read-only at /capture and an empty results directory
at /results. Uses disposable prefix/rootfs only. Does not start Epic or a game.
"""
import base64
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import uuid

if os.environ.get('DPAD_TEST_EPIC_CAPTURE') != '1':
    raise SystemExit('disposable-container capture opt-in required')
sys.path.insert(0, '/opt/dpadcloud')
from dpad_epic_installation import rebind_capsule, validate_capsule
from dpad_epic_overlay import prepare

capture, results = Path('/capture'), Path('/results')
binding = json.loads((capture / 'binding.json').read_bytes())
receipt = json.loads((capture / 'receipt.json').read_bytes())
capsule_hash = receipt['capsuleSha256']
assert os.statvfs(capture).f_flag & os.ST_RDONLY
manifest_bytes = (capture / 'payload-manifest.jsonl').read_bytes()
assert hashlib.sha256(manifest_bytes).hexdigest() == binding['payloadManifestSha256']
entries = [json.loads(line) for line in manifest_bytes.splitlines()]


def verify_lower():
    total = 0
    for name, size, digest in entries:
        file = capture / 'files' / name
        assert file.resolve() == file and file.is_file()
        assert file.stat().st_size == size and not file.stat().st_mode & 0o222
        hasher = hashlib.sha256()
        with file.open('rb') as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b''):
                hasher.update(chunk)
        assert hasher.hexdigest() == digest
        total += size
    assert total == binding['installSize']


verify_lower()
target = {**binding, 'releaseId': str(uuid.uuid4())}
release = results / target['releaseId']; release.mkdir(mode=0o700)
digest = rebind_capsule(capture / 'epic', capsule_hash, binding, target, release / 'epic')
(release / 'binding.json').write_text(json.dumps(target, sort_keys=True))
(release / 'manifest.jsonl').write_bytes(manifest_bytes)
for file in (release / 'epic').iterdir():
    file.chmod(0o444)
(release / 'epic').chmod(0o555)
capsule = json.loads((release / 'epic/installation.json').read_bytes())
validate_capsule(capsule, target, (release / 'epic/vendor.manifest').read_bytes())
base = Path('/opt/dpad-instant'); base.mkdir(exist_ok=True)
for name, source in [('game', capture / 'files'), ('epic', release / 'epic')]:
    mount = base / name; mount.mkdir()
    subprocess.run(['mount', '--bind', str(source), str(mount)], check=True)
    subprocess.run(['mount', '-o', 'remount,bind,ro', str(mount)], check=True)
prepare(target, digest)
env = {**os.environ, 'HOME': '/home/dpad', 'DPAD_FAUGUS_INSTANT_TEST': '1',
       'DPAD_INSTANT_APP': target['app'], 'DPAD_INSTANT_METADATA': 'not-used-by-official-route',
       'DPAD_EPIC_INSTALLATION_SHA256': digest,
       'DPAD_EPIC_INSTALLATION_BINDING': base64.b64encode(json.dumps(target).encode()).decode()}
picker = Path('/opt/dpadcloud/launcher/dpad-launcher')
picker.write_text('#!/bin/bash\ntouch /tmp/dpad-registration-picker-ready\n'); picker.chmod(0o755)
for _ in range(2):
    subprocess.run(['runuser', '-u', 'dpad', '--', '/bin/bash', '/opt/dpadcloud/launcher-shell'],
                   env=env, check=True, capture_output=True, timeout=120)
assert Path('/tmp/dpad-registration-picker-ready').is_file()
prefix = Path('/home/dpad/Faugus/epic-games')
official = prefix / 'drive_c/Program Files/Epic Games/Launcher/Portal/Binaries/Win64/EpicGamesLauncher.exe'
assert official.is_file()
assert (prefix / 'drive_c/DpadPlay/Games' / target['app']).readlink() == base / 'official-game'
inventory = json.loads((prefix / 'drive_c/ProgramData/Epic/UnrealEngineLauncher/LauncherInstalled.dat').read_bytes())
assert len([row for row in inventory['InstallationList'] if row['AppName'] == target['app']]) == 1
item_path = prefix / 'drive_c/ProgramData/Epic/EpicGamesLauncher/Data/Manifests' / (capsule['item']['InstallationGuid'] + '.item')
item = json.loads(item_path.read_bytes())
assert item['InstallLocation'] == 'C:\\DpadPlay\\Games\\' + target['app']
assert item['bIsIncompleteInstall'] is False and item['bNeedsValidation'] is False
assert stat.S_IMODE(prefix.stat().st_mode) == 0o700
assert os.environ['DPAD_PROTON_VERSION'] == 'GE-Proton11-7'
assert Path('/home/dpad/.steam/debian-installation/compatibilitytools.d/GE-Proton11-7/proton').is_file()
game = base / 'official-game'
code = "from pathlib import Path; p=Path('/opt/dpad-instant/official-game'); (p/'private-save').write_text('private'); f=p/" + repr(target['executable']) + "; t=f.with_name(f.name+'.new'); t.write_bytes(b'private updater replacement'); t.replace(f)"
subprocess.run(['runuser', '-u', 'dpad', '--', 'python3', '-I', '-c', code], check=True)
assert (game / target['executable']).read_bytes() == b'private updater replacement'
assert not (capture / 'files/private-save').exists()
assert not (capture / 'files/.egstore').exists()
verify_lower()
summary = {'schema': 1, 'releaseId': target['releaseId'], 'capsuleSha256': digest,
           'sourceCapsuleSha256': capsule_hash, 'vendorManifestSha256': target['vendorManifestSha256'],
           'payloadManifestSha256': target['payloadManifestSha256'], 'app': target['app'],
           'fileCount': len(entries), 'payloadBytes': target['installSize'],
           'packagedRegistrationAndReplay': True, 'sharedLowerUnchanged': True,
           'privateUpdateAndSave': True, 'runner': 'GE-Proton11-7',
           'accountStateUsed': False, 'nfsVerified': False, 'clientUiVerified': False, 'gameplayVerified': False}
(results / 'genuine-registration.json').write_text(json.dumps(summary, sort_keys=True, indent=2) + '\n')
subprocess.run(['fusermount3', '-u', str(game)], check=True)
print(json.dumps(summary, sort_keys=True))
