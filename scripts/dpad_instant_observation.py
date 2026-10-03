#!/usr/bin/python3
"""Observe only the sealed selected Epic game. No account files or client logs.

Guest observations are hints for session UI/admin checks, never proof of billing,
refunds, entitlement, cloud synchronization or shared-library integrity.
"""
import json
import os
from pathlib import Path
import re
import sys

import importlib.util
import psutil
# -I disables current-directory/module-path imports. Load the reviewed sibling
# by its packaged path; never import a helper from the caller's working directory.
spec = importlib.util.spec_from_file_location('dpad_epic_installation', Path(__file__).with_name('dpad_epic_installation.py'))
installation = importlib.util.module_from_spec(spec)
spec.loader.exec_module(installation)


def same_prefix(value, prefix):
    if value.rstrip('/') == str(prefix):
        return True
    alias = prefix / 'pfx'
    return (value.rstrip('/') == str(alias) and alias.is_symlink()
            and alias.resolve(strict=True) == prefix)


def selected_game_running(binding, prefix, processes=None):
    """Exact selected executable and private UMU prefix, including Wine renames.

    An unreadable candidate is unknown, not a game-exit event. Launcher/child
    executables with other names require a future qualified per-game contract.
    """
    relative = installation.safe_relative(binding['executable'])
    app = binding['app']
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,127}', app):
        raise ValueError('selected app identity invalid')
    prefix = Path(prefix)
    installation.private_dir(prefix, create=False)
    if not prefix.is_dir():
        raise ValueError('selected prefix missing')
    windows = ('C:/DpadPlay/Games/' + app + '/' + relative).casefold()
    unix = str(prefix / 'drive_c/DpadPlay/Games' / app / relative).casefold()
    overlay = ('/opt/dpad-instant/official-game/' + relative).casefold()
    names = {Path(relative).name.casefold(), Path(relative).name.casefold()[:15], 'gamethread'}
    unknown = False
    for process in psutil.process_iter() if processes is None else processes:
        own = False
        try:
            if process.uids().effective != os.geteuid():
                continue
            own = True
            if process.name().casefold() not in names:
                continue
            environment = process.environ()
            if environment.get('FAUGUSID') != 'dpad-epic' or not same_prefix(environment.get('WINEPREFIX', ''), prefix):
                continue
            if any(arg.replace('\\', '/').casefold() in (windows, unix, overlay) for arg in process.cmdline()):
                return True
        except psutil.NoSuchProcess:
            continue
        except (psutil.Error, OSError, ValueError, KeyError):
            if own:
                unknown = True
    return None if unknown else False


def selected_update_hint(binding, prefix, capsule):
    """Read one public installation record. Do not export its contents/version."""
    guid = capsule['item']['InstallationGuid']
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,127}', guid):
        raise ValueError('selected record identity invalid')
    path = Path(prefix) / 'drive_c/ProgramData/Epic/EpicGamesLauncher/Data/Manifests' / (guid + '.item')
    try:
        item = json.loads(installation.read_bytes(path, installation.MAX_JSON, private=True), object_pairs_hook=installation.unique)
        version = item.get('AppVersionString')
        if (item.get('AppName') != binding['app'] or not isinstance(version, str)
                or not 1 <= len(version) <= 200 or any(ord(c) < 32 or ord(c) == 127 for c in version)):
            return None
        return version != binding['version']
    except (OSError, ValueError, TypeError, KeyError):
        return None


class GameState:
    def __init__(self, quiet_seconds=15):
        self.quiet_seconds = quiet_seconds
        self.state = 'waiting'
        self.quiet_since = None
        self.seen = False
        self.cycle = 0
        self.closed = False

    def observe(self, active, now):
        if active is True:
            if not self.seen or self.closed:
                self.cycle += 1
            self.seen = True
            self.closed = False
            self.state, self.quiet_since = 'running', None
        elif active is None:
            # Lost evidence must not count toward the continuous quiet interval.
            self.quiet_since = None
            self.state = 'unknown'
        elif not self.seen:
            self.state, self.quiet_since = 'waiting', None
        else:
            if self.quiet_since is None:
                self.quiet_since = now
            if now - self.quiet_since >= self.quiet_seconds:
                self.state = 'exited'
                self.closed = True
        return self.state


def selected_observation():
    binding, _ = installation.session_binding()
    # Validate the exact read-only official capsule before deriving a record path.
    installation.session_launch_uri(binding)
    encoded = installation.read_bytes(Path('/opt/dpad-instant/epic/installation.json'), installation.MAX_JSON, sealed=True)
    capsule = json.loads(encoded, object_pairs_hook=installation.unique)
    prefix = installation.session_prefix()
    return {'schema': 1, 'releaseId': binding['releaseId'],
            'gameRunning': selected_game_running(binding, prefix),
            'updateHint': selected_update_hint(binding, prefix, capsule)}


if __name__ == '__main__':
    try:
        if sys.argv[1:] == ['--require-stopped']:
            if selected_observation()['gameRunning'] is not False:
                raise ValueError('selected game still running or unknown')
        elif len(sys.argv) == 1:
            print(json.dumps(selected_observation(), separators=(',', ':')))
        else:
            raise ValueError('unexpected arguments')
    except (ValueError, OSError, TypeError, KeyError):
        print('Selected game observation unavailable', file=sys.stderr)
        sys.exit(1)
