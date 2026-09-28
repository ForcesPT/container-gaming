#!/usr/bin/python3
"""Report whether this Epic launch hit the updater's service-start failure."""
import os
from pathlib import Path
import stat
import sys


def failed(prefix, started_ns):
    logs = Path(prefix) / 'drive_c/users'
    for path in logs.glob('*/AppData/Local/EpicGamesLauncher/Saved/Logs/EpicGamesUpdater-*.log'):
        try:
            info = path.lstat()
            if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid()
                    or info.st_size > 1024 * 1024 or info.st_mtime_ns < started_ns):
                continue
            with path.open('rb') as stream:
                tail = stream.read()[-16384:]
            if b'StartServiceFailed' in tail and b'code 8' in tail:
                return True
        except OSError:
            continue
    return False


if __name__ == '__main__':
    if len(sys.argv) != 3:
        raise SystemExit('usage: dpad_epic_updater_failed.py PREFIX STARTED_NS')
    try:
        started_ns = int(sys.argv[2])
    except ValueError:
        raise SystemExit('invalid launch time')
    raise SystemExit(0 if failed(sys.argv[1], started_ns) else 1)
