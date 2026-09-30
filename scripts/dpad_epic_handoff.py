"""Keep Faugus alive while Epic hands off to its updater or relaunched client.

The managed Epic command starts under UMU. Epic may end that parent process while
its Windows child keeps running. Faugus normally kills every process with the
game's FAUGUSID as soon as the parent exits, which interrupts such handoffs.
"""

from __future__ import annotations

import time
import os
from pathlib import Path
import stat

import psutil

EPIC_MARKER = "dpad-epic"
# Linux limits /proc/<pid>/comm to 15 bytes; Wine executable names are truncated.
EPIC_NAMES = ("epicgameslaun", "epicgamesupda")


def epic_process_running(processes=None) -> bool:
    if processes is None:
        processes = psutil.process_iter()
    for process in processes:
        try:
            if process.uids().effective != os.geteuid():
                continue
            name = process.name().casefold()
            if not (any(part in name for part in EPIC_NAMES) or name == 'gamethread'):
                continue
            environment = process.environ()
            if environment.get("FAUGUSID") != EPIC_MARKER:
                continue
            if name != 'gamethread':
                return True
            # Unreal's renamed main process must still be the official client
            # in this user's private prefix. A game or UMU helper is not enough.
            prefix = Path(environment.get('WINEPREFIX', ''))
            if not prefix.is_absolute():
                continue
            prefix = prefix.resolve(strict=True)
            info = prefix.stat()
            if (not stat.S_ISDIR(info.st_mode) or info.st_uid != os.geteuid()
                    or stat.S_IMODE(info.st_mode) & 0o077):
                continue
            executable = str(prefix / 'drive_c/Program Files/Epic Games/Launcher/Portal/Binaries/Win64/EpicGamesLauncher.exe')
            windows = r'C:\Program Files\Epic Games\Launcher\Portal\Binaries\Win64\EpicGamesLauncher.exe'
            if any(arg.casefold() in (executable.casefold(), windows.casefold())
                   for arg in process.cmdline()):
                return True
        except (psutil.Error, OSError, KeyError):
            continue
    return False


def wait_for_epic_exit(on_done, *, quiet_seconds=20, interval=1,
                       active=epic_process_running, clock=time.monotonic,
                       sleep=time.sleep) -> None:
    """Wait for a continuous quiet period, then run Faugus's normal cleanup."""
    quiet_since = None
    while True:
        now = clock()
        if active():
            quiet_since = None
        elif quiet_since is None:
            quiet_since = now
        elif now - quiet_since >= quiet_seconds:
            break
        sleep(interval)
    on_done()
