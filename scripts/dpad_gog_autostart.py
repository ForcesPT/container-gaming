#!/usr/bin/python3
"""Keep Galaxy startup under the picker; do not edit a live Wine registry."""
import os
from pathlib import Path
import re
import stat
import sys
import tempfile

RUN_KEY = r'[Software\\Microsoft\\Windows\\CurrentVersion\\Run]'
GOG_STARTUP = re.compile(r'^"GogGalaxy"="C:\\\\Program Files(?: \(x86\))?\\\\GOG Galaxy\\\\GalaxyClient\.exe /launchViaAutoStart"\s*$')


def prefix_in_use(prefix):
    for p in Path('/proc').glob('[0-9]*'):
        try:
            if p.stat().st_uid != os.getuid():
                continue
            name = Path(os.readlink(p / 'exe')).name
            if name not in {'wine', 'wine64', 'wine-preloader', 'wine64-preloader', 'wineserver'}:
                continue
            for item in (p / 'environ').read_bytes().split(b'\0'):
                if item.startswith(b'WINEPREFIX=') and Path(os.fsdecode(item[11:])).resolve() == prefix:
                    return True
        except (FileNotFoundError, ProcessLookupError):
            continue
        except PermissionError:
            return True
    return False


def disable(prefix, active=prefix_in_use):
    prefix = Path(prefix).resolve(strict=True)
    if active(prefix):
        return False
    registry = prefix / 'user.reg'
    if not registry.exists():
        return False
    fd = os.open(registry, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_nlink != 1:
            raise ValueError('Untrusted GOG user registry')
        with os.fdopen(fd, 'r', encoding='utf-8', newline='', closefd=False) as reader:
            lines = reader.readlines()
        inside, output, changed = False, [], False
        for line in lines:
            if line.startswith('['):
                inside = line.startswith(RUN_KEY + ' ') or line.strip() == RUN_KEY
            if inside and GOG_STARTUP.fullmatch(line.rstrip('\r\n')):
                changed = True
            else:
                output.append(line)
        if not changed:
            return False
        latest = registry.lstat()
        if active(prefix) or (latest.st_dev, latest.st_ino, latest.st_mtime_ns, latest.st_size) != (info.st_dev, info.st_ino, info.st_mtime_ns, info.st_size):
            raise ValueError('GOG registry became active or changed')
        temporary_fd, temporary = tempfile.mkstemp(prefix='.dpad-gog-registry-', dir=prefix)
        try:
            with os.fdopen(temporary_fd, 'w', encoding='utf-8', newline='') as writer:
                writer.writelines(output)
                writer.flush()
                os.fsync(writer.fileno())
            os.replace(temporary, registry)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
        return True
    finally:
        os.close(fd)


if __name__ == '__main__':
    try:
        if len(sys.argv) != 2:
            raise ValueError('GOG prefix is required')
        if disable(sys.argv[1]):
            print('GOG_PICKER_MANAGED_STARTUP_READY')
    except (OSError, ValueError) as error:
        raise SystemExit(f'GOG startup preparation refused: {error}')
