#!/usr/bin/python3
"""Keep the selected desktop environment private for an owned game replay.

This is an ephemeral per-container operational file, not an account/profile
export. No client logs, credentials or store URI are persisted here.
"""
import json
import os
from pathlib import Path
import pwd
import re
import stat
import sys
import tempfile

KEYS = {'DISPLAY', 'WAYLAND_DISPLAY', 'XDG_RUNTIME_DIR', 'PULSE_SERVER', 'DBUS_SESSION_BUS_ADDRESS',
        'SWAYSOCK', 'LD_PRELOAD', 'SELKIES_INTERPOSER', 'DPAD_GAMEPAD_INTERPOSER',
        'SDL_JOYSTICK_LINUX_CLASSIC', 'SDL_JOYSTICK_DISABLE_UDEV', 'SDL_JOYSTICK_DEVICE',
        'SDL_GAMECONTROLLERCONFIG', 'SDL_GAMECONTROLLER_IGNORE_DEVICES'}


def validate(value, runtime):
    if not isinstance(value, dict) or set(value) != {'schema', 'environment'} or value['schema'] != 1:
        raise ValueError('invalid environment receipt')
    env = value['environment']
    if (not isinstance(env, dict) or not set(env).issubset(KEYS)
            or any(not isinstance(v, str) or len(v) > 8192 or '\0' in v for v in env.values())
            or not re.fullmatch(r':[0-9]{1,3}', env.get('DISPLAY', ''))
            or env.get('XDG_RUNTIME_DIR') != str(runtime)):
        raise ValueError('invalid desktop environment')
    return env


def private_runtime(runtime):
    info = runtime.lstat()
    if (not stat.S_ISDIR(info.st_mode) or runtime.resolve() != runtime
            or info.st_uid != os.geteuid() or info.st_mode & 0o077):
        raise ValueError('private runtime required')


def publish(runtime, environment):
    private_runtime(runtime)
    value = {'schema': 1, 'environment': {key: environment[key] for key in KEYS if key in environment}}
    validate(value, runtime)
    fd, name = tempfile.mkstemp(prefix='.dpad-replay-', dir=runtime)
    try:
        with os.fdopen(fd, 'w', encoding='utf8') as stream:
            json.dump(value, stream); stream.flush(); os.fsync(stream.fileno())
        os.replace(name, runtime / 'dpad-instant-desktop.json')
    finally:
        Path(name).unlink(missing_ok=True)


def read(runtime):
    private_runtime(runtime)
    fd = os.open(runtime / 'dpad-instant-desktop.json', os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        info = os.fstat(fd)
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid()
                or info.st_mode & 0o077 or info.st_nlink != 1 or info.st_size > 32768):
            raise ValueError('private environment receipt required')
        with os.fdopen(fd, 'r', encoding='utf8', closefd=False) as stream:
            return validate(json.load(stream), runtime)
    finally:
        os.close(fd)


if __name__ == '__main__':
    try:
        if os.geteuid() == 0:
            raise ValueError('session user required')
        runtime = Path('/run/user') / str(os.geteuid())
        if sys.argv[1:] == ['--publish-environment']:
            publish(runtime, os.environ)
        elif not sys.argv[1:]:
            environment = {**os.environ, **read(runtime), 'HOME': pwd.getpwuid(os.geteuid()).pw_dir, 'USER': 'dpad'}
            wrapper = str(Path(__file__).with_name('faugus-epic-launch'))
            os.execve(wrapper, [wrapper, '--replay'], environment)
        else:
            raise ValueError('unexpected replay arguments')
    except (OSError, ValueError, KeyError, TypeError):
        print('Selected game replay unavailable', file=sys.stderr)
        sys.exit(1)
