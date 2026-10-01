#!/usr/bin/python3
"""Set Steam's fallback Windows-game tool, preserving per-game choices."""
import os
from pathlib import Path
import stat
import tempfile
import vdf


def set_default(install, version):
    install = Path(install).resolve(strict=True)
    tool = install / 'compatibilitytools.d' / version
    if tool.parent != install / 'compatibilitytools.d' or not (tool / 'proton').is_file():
        raise ValueError('Steam compatibility tool is unavailable')
    tools = vdf.loads((tool / 'compatibilitytool.vdf').read_text())['compatibilitytools']['compat_tools']
    if len(tools) != 1:
        raise ValueError('Ambiguous Steam compatibility tool')
    name = next(iter(tools))
    config = install / 'config'
    config.mkdir(mode=0o700, exist_ok=True)
    info = config.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o022:
        raise ValueError('Untrusted Steam config directory')
    path = config / 'config.vdf'
    data = {}
    if path.exists() or path.is_symlink():
        info = path.lstat()
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_nlink != 1 or info.st_size > 16 * 1024 * 1024:
            raise ValueError('Untrusted Steam config file')
        data = vdf.loads(path.read_text())
    node = data
    for key in ('InstallConfigStore', 'Software', 'Valve', 'Steam', 'CompatToolMapping'):
        # VDF keys are case insensitive; keep the client's existing spelling.
        existing = next((k for k in node if k.lower() == key.lower()), key)
        node = node.setdefault(existing, {})
        if not isinstance(node, dict):
            raise ValueError('Invalid Steam config structure')
    desired = {'name': name, 'config': '', 'priority': '250'}
    if node.get('0') == desired:
        return
    node['0'] = desired
    fd, temporary = tempfile.mkstemp(prefix='.dpad-proton-', dir=config)
    try:
        with os.fdopen(fd, 'w') as output:
            vdf.dump(data, output, pretty=True)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


if __name__ == '__main__':
    # Updating a running Steam client can overwrite its in-memory settings.
    running = False
    for p in Path('/proc').iterdir():
        if not p.name.isdecimal():
            continue
        try:
            if p.stat().st_uid == os.getuid() and (p / 'comm').read_text().strip() == 'steam':
                running = True
                break
        except (FileNotFoundError, PermissionError, ProcessLookupError):
            continue
    if not running:
        set_default(Path.home() / '.steam/debian-installation',
                    os.environ.get('DPAD_STEAM_PROTON_VERSION') or
                    os.environ.get('DPAD_PROTON_VERSION') or 'GE-Proton11-7')
