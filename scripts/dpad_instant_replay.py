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


def private_state(runtime, create=False):
    # The desktop entrypoint uses a sticky 1777 runtime for compositor/audio
    # sockets. Keep the receipt in a private child without changing those sockets.
    info = runtime.lstat()
    if (not stat.S_ISDIR(info.st_mode) or runtime.resolve() != runtime
            or info.st_uid != os.geteuid()
            or stat.S_IMODE(info.st_mode) not in (0o700, 0o1777)):
        raise ValueError('owned desktop runtime required')
    state = runtime / 'dpad-instant'
    if create:
        try:
            state.mkdir(mode=0o700)
        except FileExistsError:
            pass
    info = state.lstat()
    if (not stat.S_ISDIR(info.st_mode) or state.resolve() != state
            or info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) != 0o700):
        raise ValueError('private replay state required')
    return state


def publish(runtime, environment):
    value = {'schema': 1, 'environment': {key: environment[key] for key in KEYS if key in environment}}
    validate(value, runtime)
    state = private_state(runtime, create=True)
    fd, name = tempfile.mkstemp(prefix='.dpad-replay-', dir=state)
    try:
        with os.fdopen(fd, 'w', encoding='utf8') as stream:
            json.dump(value, stream); stream.flush(); os.fsync(stream.fileno())
        os.replace(name, state / 'dpad-instant-desktop.json')
    finally:
        Path(name).unlink(missing_ok=True)


def read(runtime):
    state = private_state(runtime)
    fd = os.open(state / 'dpad-instant-desktop.json', os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
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
