#!/usr/bin/python3
"""Expose the image runner after Steam's install root moves onto a user volume."""
import fcntl
import os
from pathlib import Path
import stat
import sys
import uuid


def owned_directory(path):
    path.mkdir(mode=0o700, exist_ok=True)
    info = path.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o022:
        raise ValueError('Untrusted compatibility directory')
    return path


def publish(install, version, baked_root=Path('/opt/dpadcloud/proton')):
    if Path(version).name != version or version in ('.', '..'):
        raise ValueError('Invalid runner version')
    source = Path(baked_root) / version
    if not source.is_dir():
        return  # Explicit overrides can select an existing user-installed tool.
    if not os.access(source / 'proton', os.X_OK):
        raise ValueError('Image runner is incomplete')
    install = Path(install).resolve(strict=True)
    tools = owned_directory(install / 'compatibilitytools.d')
    state = owned_directory(install / '.dpad-image-runners')
    fd = os.open(state / 'publish.lock', os.O_RDONLY | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_nlink != 1 or info.st_mode & 0o022:
            raise ValueError('Untrusted compatibility lock')
        fcntl.flock(fd, fcntl.LOCK_EX)
        target = tools / version
        if target.is_symlink() and target.resolve() == source.resolve():
            return
        if target.exists() or target.is_symlink():
            info = target.lstat()
            if info.st_uid != os.getuid():
                raise ValueError('Existing runner is not owned by this user')
            # Preserve old/custom files outside Steam's tool scan. Never delete
            # a user runner or merge old components into the image's runner.
            os.rename(target, state / f'{version}-previous-{uuid.uuid4().hex}')
        temporary = tools / f'.dpad-runner-{uuid.uuid4().hex}'
        try:
            temporary.symlink_to(source, target_is_directory=True)
            os.replace(temporary, target)
        finally:
            if temporary.is_symlink():
                temporary.unlink()
    finally:
        os.close(fd)


if __name__ == '__main__':
    try:
        if len(sys.argv) != 2:
            raise ValueError('Runner version is required')
        publish(Path.home() / '.steam/debian-installation', sys.argv[1])
    except (OSError, ValueError) as error:
        raise SystemExit(f'Image runner publication refused: {error}')
