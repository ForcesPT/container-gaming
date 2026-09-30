#!/usr/bin/python3
"""Permit a second-instance restore only for this user's managed Epic client."""
import os
from pathlib import Path
import sys
import stat

import psutil


def managed_client_running(prefix, processes=None):
    prefix = str(Path(prefix))
    for process in psutil.process_iter() if processes is None else processes:
        try:
            if process.uids().effective != os.geteuid():
                continue
            name = process.name().casefold()
            # Unreal renames the main Wine process after startup. UMU also
            # exposes the prefix through its pfx symlink, with a trailing slash.
            if not (name.startswith('epicgameslaun') or name == 'gamethread'):
                continue
            env = process.environ()
            if env.get('FAUGUSID') != 'dpad-epic':
                continue
            wine_prefix = env.get('WINEPREFIX', '').rstrip('/')
            if wine_prefix != prefix:
                alias = Path(prefix) / 'pfx'
                if (wine_prefix != str(alias) or not alias.is_symlink()
                        or alias.resolve(strict=True) != Path(prefix).resolve(strict=True)):
                    continue
            arguments = process.cmdline()
            # An updater commandlet uses the same executable, but cannot
            # restore a signed-in client window.
            if any(arg.casefold().startswith('-commandlet') for arg in arguments):
                continue
            executable = prefix + '/drive_c/Program Files/Epic Games/Launcher/Portal/Binaries/Win64/EpicGamesLauncher.exe'
            # Wine can use either a Unix path or the Windows equivalent in argv.
            windows_executable = r'C:\Program Files\Epic Games\Launcher\Portal\Binaries\Win64\EpicGamesLauncher.exe'
            if any(arg.casefold() in (executable.casefold(), windows_executable.casefold())
                   for arg in arguments):
                return True
        except (psutil.Error, OSError, KeyError):
            continue
    return False


if __name__ == '__main__':
    if len(sys.argv) != 2 or not Path(sys.argv[1]).is_absolute():
        raise SystemExit('usage: dpad_epic_resume.py ABSOLUTE_PREFIX')
    info = Path(sys.argv[1]).lstat()
    if (not stat.S_ISDIR(info.st_mode) or info.st_uid != os.geteuid()
            or stat.S_IMODE(info.st_mode) & 0o077):
        raise SystemExit('Epic prefix is not private')
    if not managed_client_running(sys.argv[1]):
        raise SystemExit('No matching managed Epic client is available to reopen')
