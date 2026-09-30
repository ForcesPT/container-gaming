#!/usr/bin/python3
"""Prepare a container-local COW game view. Shared lower files remain read-only."""
import base64
import json
import os
from pathlib import Path
import stat
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from dpad_epic_installation import MAX_JSON, MAX_MANIFEST, read_bytes, unique, validate_capsule, new_file
import hashlib


def prepare(binding, digest, *, run=subprocess.run):
    lower = Path('/opt/dpad-instant/game')
    capsule_root = Path('/opt/dpad-instant/epic')
    for path in (lower, capsule_root):
        if path.resolve() != path or not path.is_dir() or not os.statvfs(path).f_flag & os.ST_RDONLY:
            raise ValueError('read-only shared sources required')
    encoded = read_bytes(capsule_root / 'installation.json', MAX_JSON, sealed=True)
    if hashlib.sha256(encoded).hexdigest() != digest:
        raise ValueError('capsule mismatch')
    capsule = json.loads(encoded, object_pairs_hook=unique)
    manifest = read_bytes(capsule_root / 'vendor.manifest', MAX_MANIFEST, sealed=True)
    item = validate_capsule(capsule, binding, manifest)
    executable = lower / item['LaunchExecutable']
    if executable.resolve() != executable or not executable.is_file():
        raise ValueError('pinned executable absent')
    # Never stack a second view or reuse another session's write layer.
    root = Path('/run/dpadcloud/epic-cow')
    root.parent.mkdir(mode=0o755, parents=True, exist_ok=True)
    if root.parent.resolve() != root.parent or root.parent.stat().st_uid != 0 or root.parent.stat().st_mode & 0o022:
        raise ValueError('unsafe runtime root')
    root.mkdir(mode=0o700)
    import pwd
    user = pwd.getpwnam('dpad')
    for name in ('upper', 'work'):
        path = root / name
        path.mkdir(mode=0o700)
        os.chown(path, user.pw_uid, user.pw_gid)
    merged = Path('/opt/dpad-instant/official-game')
    merged.mkdir(mode=0o700)
    fuse = Path('/dev/fuse').stat()
    if not stat.S_ISCHR(fuse.st_mode) or os.major(fuse.st_rdev) != 10 or os.minor(fuse.st_rdev) != 229:
        raise ValueError('FUSE device required')
    run(['/usr/bin/fuse-overlayfs', '-o',
         f'allow_other,lowerdir={lower},upperdir={root}/upper,workdir={root}/work',
         str(merged)], check=True, capture_output=True, timeout=15)
    # The merged root initially inherits the sealed lower permissions. chmod and
    # chown copy up that inode; they must never be applied to the shared lower.
    for directory, children, _ in os.walk(merged, followlinks=False):
        path = Path(directory)
        if path.is_symlink() or any((path / name).is_symlink() for name in children):
            raise ValueError('redirected game directory')
        os.chown(path, user.pw_uid, user.pw_gid)
        path.chmod(0o700)
    if os.statvfs(merged).f_flag & os.ST_RDONLY:
        raise ValueError('private overlay is not writable')
    new_file(root.parent / 'epic-overlay.json', json.dumps({
        'releaseId': binding['releaseId'], 'game': str(merged)}).encode(), 0o444)


if __name__ == '__main__':
    try:
        if os.geteuid() != 0 or os.environ.get('DPAD_FAUGUS_INSTANT_TEST') != '1':
            raise ValueError('root canary setup required')
        binding = json.loads(base64.b64decode(os.environ['DPAD_EPIC_INSTALLATION_BINDING'], validate=True), object_pairs_hook=unique)
        prepare(binding, os.environ['DPAD_EPIC_INSTALLATION_SHA256'])
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError):
        print('Official Epic private game overlay refused', file=sys.stderr)
        sys.exit(1)
