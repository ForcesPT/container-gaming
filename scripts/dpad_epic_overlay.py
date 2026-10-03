#!/usr/bin/python3
"""Prepare a container-local COW game view. Shared lower files remain read-only."""
import base64
import fcntl
import json
import os
from pathlib import Path
import stat
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from dpad_epic_installation import MAX_JSON, MAX_MANIFEST, read_bytes, unique, validate_capsule, new_file
import hashlib


def trusted_directory(path, uid, mode):
    info = path.lstat()
    if (path.resolve() != path or not stat.S_ISDIR(info.st_mode)
            or info.st_uid != uid or stat.S_IMODE(info.st_mode) != mode):
        raise ValueError('unsafe private overlay directory')


def sealed_record(path, expected):
    record = json.loads(read_bytes(path, MAX_JSON, sealed=True), object_pairs_hook=unique)
    if path.stat().st_uid != 0 or record != expected:
        raise ValueError('private overlay binding mismatch')


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
    # A Docker restart retains this exact container's writable layer, but its
    # FUSE mount/daemon disappear. Resume only a sealed, matching write layer;
    # never stack a second view or adopt an unbound/redirected directory.
    root = Path('/run/dpadcloud/epic-cow')
    root.parent.mkdir(mode=0o755, parents=True, exist_ok=True)
    if root.parent.resolve() != root.parent or root.parent.stat().st_uid != 0 or root.parent.stat().st_mode & 0o022:
        raise ValueError('unsafe runtime root')
    lock_fd = os.open(root.parent / 'epic-overlay.lock',
                      os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600)
    with os.fdopen(lock_fd, 'w') as lock:
        info = os.fstat(lock.fileno())
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != 0 or info.st_nlink != 1
                or stat.S_IMODE(info.st_mode) != 0o600):
            raise ValueError('unsafe private overlay lock')
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        prepare_view(root, lower, binding, digest, run)


def prepare_view(root, lower, binding, digest, run):
    import pwd
    user = pwd.getpwnam('dpad')
    merged = Path('/opt/dpad-instant/official-game')
    receipt = root.parent / 'epic-overlay.json'
    expected_receipt = {'releaseId': binding['releaseId'], 'game': str(merged)}
    seal = {'schema': 1, 'releaseId': binding['releaseId'], 'installationSha256': digest,
            'bindingSha256': hashlib.sha256(json.dumps(binding, sort_keys=True,
                separators=(',', ':')).encode()).hexdigest()}
    if receipt.exists() or receipt.is_symlink():
        sealed_record(receipt, expected_receipt)
    if merged.is_mount():
        raise ValueError('private game overlay is already mounted')
    if root.exists() or root.is_symlink():
        trusted_directory(root, 0, 0o700)
        sealed_record(root / 'binding.json', seal)
        for name in ('upper', 'work'):
            trusted_directory(root / name, user.pw_uid, 0o700)
        trusted_directory(merged, 0, 0o700)
        if any(merged.iterdir()):
            raise ValueError('private overlay mountpoint is not empty')
    else:
        # Refuse orphaned state rather than discarding possible private files.
        if merged.exists() or merged.is_symlink() or receipt.exists():
            raise ValueError('unbound private overlay state')
        root.mkdir(mode=0o700)
        for name in ('upper', 'work'):
            path = root / name
            path.mkdir(mode=0o700)
            os.chown(path, user.pw_uid, user.pw_gid)
        merged.mkdir(mode=0o700)
        new_file(root / 'binding.json', json.dumps(seal, sort_keys=True).encode(), 0o444)
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
    if not receipt.exists():
        new_file(receipt, json.dumps(expected_receipt).encode(), 0o444)


if __name__ == '__main__':
    try:
        if os.geteuid() != 0 or os.environ.get('DPAD_FAUGUS_INSTANT_TEST') != '1':
            raise ValueError('root canary setup required')
        binding = json.loads(base64.b64decode(os.environ['DPAD_EPIC_INSTALLATION_BINDING'], validate=True), object_pairs_hook=unique)
        prepare(binding, os.environ['DPAD_EPIC_INSTALLATION_SHA256'])
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError):
        print('Official Epic private game overlay refused', file=sys.stderr)
        sys.exit(1)
