#!/usr/bin/python3
"""Prepare private Faugus inventory for the official Epic client, without login."""
import json
import os
from pathlib import Path
import stat
import tempfile
import sys

RUNNER = '/home/dpad/.steam/debian-installation/compatibilitytools.d/GE-Proton10-34'
PREVIOUS_RUNNER = '/home/dpad/.steam/debian-installation/compatibilitytools.d/GE-Proton11-3'

def private_directory(path):
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    info = path.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.geteuid() or info.st_mode & 0o022:
        raise ValueError('untrusted Faugus directory')
    return path

def read_json(path, fallback):
    if not path.exists() and not path.is_symlink():
        return fallback
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid() or info.st_nlink != 1 or info.st_mode & 0o022 or info.st_size > 4 * 1024 * 1024:
        raise ValueError('untrusted Faugus inventory')
    return json.loads(path.read_text())

def save_json(path, data):
    fd, temp = tempfile.mkstemp(prefix='.dpad-', dir=path.parent)
    try:
        with os.fdopen(fd, 'w') as stream:
            json.dump(data, stream)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp, path)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)

def locations(home, state_root=None):
    home = Path(home)
    if not home.is_absolute():
        raise ValueError('HOME must be absolute')
    if state_root:
        root = Path(state_root)
        if not root.is_absolute():
            raise ValueError('Faugus state root must be absolute')
        private_directory(root)
        return (root / 'prefixes', root / 'config/faugus-launcher',
                root / 'data/faugus-launcher', root / 'state/faugus-launcher')
    return (home / 'Faugus', home / '.config/faugus-launcher',
            home / '.local/share/faugus-launcher', home / '.local/state/faugus-launcher')


def prepare_lock(home, state_root=None):
    state_dir = private_directory(locations(home, state_root)[3])
    lock_fd = os.open(state_dir / 'dpad-epic.lock', os.O_CREAT | os.O_RDONLY | os.O_NOFOLLOW, 0o600)
    try:
        info = os.fstat(lock_fd)
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid() or info.st_nlink != 1 or info.st_mode & 0o022:
            raise ValueError('untrusted Faugus lock')
    finally:
        os.close(lock_fd)


def prepare(home, runner=RUNNER, umu='/usr/bin/umu-run', state_root=None):
    home = Path(home)
    if not home.is_absolute():
        raise ValueError('HOME must be absolute')
    if not os.access(Path(runner) / 'proton', os.X_OK) or not os.access(umu, os.X_OK):
        raise ValueError('pinned UMU/GE-Proton is unavailable')
    prefixes, config_path_root, data_path_root, _ = locations(home, state_root)
    prefix = private_directory(prefixes / 'epic-games')
    config_dir = private_directory(config_path_root)
    data_dir = private_directory(data_path_root)
    prepare_lock(home, state_root)
    config_path = config_dir / 'config.json'
    config = read_json(config_path, {})
    if not isinstance(config, dict):
        raise ValueError('invalid Faugus config')
    config.update({'default-runner': runner, 'default-prefix': str(prefixes),
                   'automatic-updates': 'False', 'show-donate': 'False',
                   'steamgriddb-enabled': 'False', 'backup-auto-enabled': 'False'})
    save_json(config_path, config)
    executable = prefix / 'drive_c/Program Files/Epic Games/Launcher/Portal/Binaries/Win64/EpicGamesLauncher.exe'
    entry = {'gameid': 'dpad-epic', 'title': 'Epic Games', 'path': str(executable),
             'prefix': str(prefix), 'runner': runner, 'protonfix': 'umu-default',
             'launch_arguments': 'PROTON_ENABLE_WAYLAND=0', 'game_arguments': '',
             'playtime': 0}
    games_path = data_dir / 'games.json'
    games = read_json(games_path, [])
    if not isinstance(games, list) or any(not isinstance(game, dict) for game in games):
        raise ValueError('invalid Faugus games')
    matches = [game for game in games if game.get('gameid') == entry['gameid']]
    if len(matches) > 1:
        raise ValueError('duplicate Epic record')
    if matches:
        for key in ('path', 'prefix'):
            if matches[0].get(key) != entry[key]:
                raise ValueError('conflicting Epic record')
        if matches[0].get('runner') not in (runner, PREVIOUS_RUNNER):
            raise ValueError('conflicting Epic runner')
        entry['playtime'] = matches[0].get('playtime', 0)
        games[games.index(matches[0])] = entry
    else:
        games.append(entry)
    save_json(games_path, games)
    return executable

if __name__ == '__main__':
    try:
        if sys.argv[1:] == ['--lock-only']:
            prepare_lock(os.environ['HOME'], os.environ.get('DPAD_FAUGUS_STATE_ROOT'))
        elif not sys.argv[1:]:
            prepare(os.environ['HOME'], state_root=os.environ.get('DPAD_FAUGUS_STATE_ROOT'))
        else:
            raise ValueError('unknown preparation option')
    except (OSError, ValueError, KeyError) as error:
        raise SystemExit(f'Faugus preparation refused: {error}')
