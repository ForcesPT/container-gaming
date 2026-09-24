#!/usr/bin/env python3
"""Exit 0 only for a bound listening Unix signaling socket in this namespace.

Exit 1 means the listener is absent. Exit 2 means observation failed, which must
not trigger an automatic restart of an otherwise present Selkies process.
"""
import os
from pathlib import Path
import stat
import sys

DEFAULT = '/run/dpad-signaling/stream.sock'
LISTENING = 0x00010000


def listening(path: str) -> bool:
    try:
        info = os.lstat(path)
    except FileNotFoundError:
        return False
    if not stat.S_ISSOCK(info.st_mode):
        return False
    with open('/proc/net/unix', encoding='ascii') as stream:
        next(stream)
        for line in stream:
            fields = line.split(maxsplit=7)
            if len(fields) == 8 and fields[7].rstrip('\n') == path and int(fields[3], 16) & LISTENING:
                return True
    return False


if __name__ == '__main__':
    path = sys.argv[1] if len(sys.argv) == 2 else DEFAULT
    if len(sys.argv) > 2 or not Path(path).is_absolute():
        raise SystemExit(2)
    try:
        raise SystemExit(0 if listening(path) else 1)
    except (OSError, ValueError):
        raise SystemExit(2)
