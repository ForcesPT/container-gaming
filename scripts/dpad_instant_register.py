"""Session-local file inventory; never creates an Epic entitlement or login.
Schema checked against Heroic v2.22.0 and Legendary 0.21.1. No network or payload writes.
"""
import fcntl
import json
import os
import re
import stat
import tempfile
from pathlib import Path, PurePosixPath


def validate_metadata(data):
    fields = {'app', 'title', 'version', 'executable', 'launchParameters', 'requiresOwnershipToken', 'installSize'}
    if not isinstance(data, dict) or set(data) != fields:
        raise ValueError('invalid metadata fields')
    for key, limit in [('app', 128), ('title', 512), ('version', 256), ('executable', 1024), ('launchParameters', 4096)]:
        value = data[key]
        if not isinstance(value, str) or len(value) > limit or (not value and key != 'launchParameters') or any(ord(c) < 32 for c in value):
            raise ValueError('invalid metadata text')
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]*', data['app']):
        raise ValueError('invalid app')
    exe = PurePosixPath(data['executable'])
    if not exe.parts or exe.is_absolute() or '..' in exe.parts or str(exe) != data['executable'] or any(c in data['executable'] for c in ('\\', ':')):
        raise ValueError('invalid executable')
    if type(data['requiresOwnershipToken']) is not bool or type(data['installSize']) is not int or not 0 < data['installSize'] <= 2 * 1024**4:
        raise ValueError('invalid metadata value')
    return data


def unique_json(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('duplicate registry key')
        result[key] = value
    return result


def register(home, game, data):
    validate_metadata(data)
    home, game = Path(home), Path(game)
    if not home.is_absolute() or home.resolve() != home or not game.is_absolute() or game.resolve() != game:
        raise ValueError('redirected session path')
    for path in (game, game / data['executable']):
        info = path.lstat()
        if path.resolve() != path or info.st_mode & 0o222 or not (stat.S_ISDIR(info.st_mode) if path == game else stat.S_ISREG(info.st_mode)):
            raise ValueError('unsealed game')
    directory = home
    for part in ('', '.config', 'heroic', 'legendaryConfig', 'legendary'):
        directory = directory / part
        if part:
            directory.mkdir(mode=0o700, exist_ok=True)
        info = directory.lstat()
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.geteuid() or info.st_mode & 0o022:
            raise ValueError('untrusted session directory')
    record = dict(app_name=data['app'], title=data['title'], version=data['version'],
                  install_path=str(game), executable=data['executable'],
                  launch_parameters=data['launchParameters'], install_size=data['installSize'],
                  requires_ot=data['requiresOwnershipToken'], can_run_offline=False,
                  needs_verification=True, platform='Windows', is_dlc=False)
    lock = os.open(directory / 'installed.json.lock', os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600)
    try:
        info = os.fstat(lock)
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_uid != os.geteuid() or info.st_mode & 0o022:
            raise ValueError('untrusted registry lock')
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        path = directory / 'installed.json'
        records = {}
        if path.exists() or path.is_symlink():
            info = path.lstat()
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_uid != os.geteuid() or info.st_mode & 0o022 or info.st_size > 16 * 1024 * 1024:
                raise ValueError('untrusted registry')
            fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
            with os.fdopen(fd) as stream:
                records = json.load(stream, object_pairs_hook=unique_json)
            if not isinstance(records, dict):
                raise ValueError('invalid registry')
        if data['app'] in records:
            existing = records[data['app']]
            # Heroic may add save paths or finish verification; retain those fields.
            identity = ('app_name', 'install_path', 'version', 'executable', 'launch_parameters', 'requires_ot', 'install_size')
            if not isinstance(existing, dict) or any(existing.get(k) != record[k] for k in identity):
                raise ValueError('existing installation conflicts with pinned release')
            return 'already_registered'
        records[data['app']] = record
        fd, temporary = tempfile.mkstemp(prefix='.instant-registration-', dir=directory)
        try:
            with os.fdopen(fd, 'w') as stream:
                json.dump(records, stream)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, path)
            parent = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            try:
                os.fsync(parent)
            finally:
                os.close(parent)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
        return 'registered'
    finally:
        os.close(lock)


def prepare_private_registry(home):
    """Tighten only Heroic's own registry directories, never payload/files.

    Walk with no-follow directory descriptors so symlinks cannot redirect chmod.
    Parent directories and world-writable/foreign-owned state still fail closed.
    """
    home = Path(home)
    if not home.is_absolute() or home.resolve() != home:
        raise ValueError('redirected session path')
    fd = os.open(home, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        for part in ('', '.config', 'heroic', 'legendaryConfig', 'legendary'):
            if part:
                try:
                    os.mkdir(part, mode=0o700, dir_fd=fd)
                except FileExistsError:
                    pass
                child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
                os.close(fd)
                fd = child
            info = os.fstat(fd)
            if info.st_uid != os.geteuid() or info.st_mode & 0o002:
                raise ValueError('untrusted session directory')
            if part in ('legendaryConfig', 'legendary'):
                os.fchmod(fd, stat.S_IMODE(info.st_mode) & ~0o022)
            elif info.st_mode & 0o022:
                raise ValueError('untrusted session directory')
    finally:
        os.close(fd)


def main():
    import base64
    import sys
    if len(sys.argv) != 1 or os.geteuid() == 0:
        raise ValueError('session user required')
    encoded = os.environ.get('DPAD_INSTANT_METADATA', '')
    if not encoded or len(encoded) > 16384:
        raise ValueError('pinned registration metadata required')
    data = json.loads(base64.b64decode(encoded, validate=True), object_pairs_hook=unique_json)
    validate_metadata(data)
    if data['app'] != os.environ.get('DPAD_INSTANT_APP'):
        raise ValueError('registration app mismatch')
    home = Path(os.environ['HOME'])
    if os.environ.get('XDG_CONFIG_HOME', '') not in ('', str(home / '.config')):
        raise ValueError('redirected Heroic configuration')
    game = Path('/opt/dpad-instant/game')
    if not os.statvfs(game).f_flag & os.ST_RDONLY:
        raise ValueError('read-only game mount required')
    os.umask(0o077)
    prepare_private_registry(home)
    print('DPAD_INSTANT_INSTALLATION ' + register(home, game, data))


if __name__ == '__main__':
    try:
        main()
    except Exception:
        import sys
        # Never print descriptor, command arguments, credentials or file contents.
        print('DPAD_INSTANT_REGISTRATION_FAILED', file=sys.stderr)
        sys.exit(1)
