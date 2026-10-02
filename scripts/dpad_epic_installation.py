#!/usr/bin/python3
"""Portable official Epic installation records. No login or entitlement creation.

Export only from a completed official installation. Runtime registration is an
opt-in candidate and requires a release-bound capsule plus private writable COW
storage. Never copy a signed-in prefix or arbitrary launcher configuration.
"""
import argparse
import base64
from contextlib import contextmanager
import fcntl
import hashlib
import json
import os
from pathlib import Path, PureWindowsPath
import re
import stat
import sys
import tempfile
import time

MAX_JSON = 64 * 1024
MAX_MANIFEST = 8 * 1024 * 1024
UUID = r'[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}'
DIGEST = r'[a-f0-9]{64}'
# This allowlist intentionally excludes account IDs, URLs, tokens and local paths.
TEXT = {'AppName': 128, 'AppVersionString': 256, 'CatalogNamespace': 128,
        'CatalogItemId': 128, 'DisplayName': 512, 'LaunchExecutable': 1024,
        'LaunchCommand': 4096, 'InstallationGuid': 128}
OPTIONAL_TEXT = {'MainGameAppName': 128, 'MandatoryAppFolderName': 128,
                 'PrereqName': 256, 'PrereqPath': 1024, 'PrereqArgs': 1024}
FLAGS = {'bIsIncompleteInstall', 'bNeedsValidation', 'bIsManaged',
         'bCanRunOffline', 'bRequiresAuth', 'bIsApplication', 'bIsExecutable',
         'bIsUE4Project', 'bIsThirdPartyManagedApp'}


def unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('duplicate JSON key')
        result[key] = value
    return result


def read_bytes(path, limit, *, sealed=False, private=False):
    path = Path(path)
    # Reject redirects in parents too, not just a symlink at the final filename.
    if not path.is_absolute() or path.resolve() != path:
        raise ValueError('noncanonical artifact path')
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, 'rb') as stream:
        info = os.fstat(stream.fileno())
        if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_size > limit
                or sealed and info.st_mode & 0o222
                or private and (info.st_uid != os.geteuid() or info.st_mode & 0o022)):
            raise ValueError('unsafe artifact')
        data = stream.read(limit + 1)
        if len(data) > limit:
            raise ValueError('artifact size limit')
        return data


def safe_relative(value, *, empty=False):
    if empty and value == '':
        return value
    if not isinstance(value, str) or not value or len(value) > 1024:
        raise ValueError('invalid relative path')
    parts = value.replace('\\', '/').split('/')
    if any(not p or p in ('.', '..') or re.search(r'[\x00-\x1f\x7f:<>"|?*]', p)
           or p.endswith((' ', '.'))
           or re.fullmatch(r'(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\..*)?', p, re.I)
           for p in parts):
        raise ValueError('unsafe relative path')
    return '/'.join(parts)


def normalize_item(raw):
    if not isinstance(raw, dict):
        raise ValueError('official item must be an object')
    result = {}
    for fields, required in ((TEXT, True), (OPTIONAL_TEXT, False)):
        for key, limit in fields.items():
            if not required and key not in raw:
                continue
            value = raw.get(key)
            if (not isinstance(value, str) or len(value) > limit
                    or not value and key not in {'LaunchCommand', *OPTIONAL_TEXT}
                    or any(ord(c) < 32 or ord(c) == 127 for c in value)):
                raise ValueError('invalid official item text')
            result[key] = value
    for key in ('LaunchCommand', 'PrereqArgs'):
        if re.search(r'(?i)(AUTH_(PASSWORD|LOGIN|TYPE)|access_token|refresh_token|bearer\s)', result.get(key, '')):
            raise ValueError('account data is not installation metadata')
    for key in ('AppName', 'CatalogNamespace', 'CatalogItemId', 'InstallationGuid'):
        if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,127}', result[key]):
            raise ValueError('invalid official catalog identity')
    result['LaunchExecutable'] = safe_relative(result['LaunchExecutable'])
    if 'PrereqPath' in result:
        result['PrereqPath'] = safe_relative(result['PrereqPath'], empty=True)
    for key in FLAGS:
        if key in raw:
            if type(raw[key]) is not bool:
                raise ValueError('invalid official item flag')
            result[key] = raw[key]
    # An incomplete or unverified install is not an importable template.
    if raw.get('bIsIncompleteInstall') is not False or raw.get('bNeedsValidation') is not False:
        raise ValueError('completed official installation required')
    for key in ('InstallSize', 'FormatVersion'):
        value = raw.get(key)
        if type(value) is not int or value < 0 or value > 2 * 1024**4:
            raise ValueError('invalid official item number')
        result[key] = value
    for key in ('InstallTags', 'PrereqIds'):
        if key in raw:
            values = raw[key]
            if (not isinstance(values, list) or len(values) > 128
                    or any(not isinstance(v, str) or len(v) > 256
                           or re.search(r'[\x00-\x1f\x7f]', v) for v in values)):
                raise ValueError('invalid official item list')
            result[key] = values
    return result


def validate_capsule(capsule, binding, manifest):
    fields = {'schema', 'releaseId', 'payloadManifestSha256', 'sourceItemSha256',
              'manifestSha256', 'manifestFileName', 'item'}
    if not isinstance(capsule, dict) or set(capsule) != fields or capsule['schema'] != 1:
        raise ValueError('invalid installation capsule')
    if not re.fullmatch(UUID, capsule['releaseId']):
        raise ValueError('invalid release identity')
    for key in ('payloadManifestSha256', 'sourceItemSha256', 'manifestSha256'):
        if not isinstance(capsule[key], str) or not re.fullmatch(DIGEST, capsule[key]):
            raise ValueError('invalid installation digest')
    if not re.fullmatch(r'[A-Za-z0-9_-]{1,128}\.manifest', capsule['manifestFileName']):
        raise ValueError('unsafe official manifest filename')
    item = normalize_item(capsule['item'])
    if item != capsule['item']:
        raise ValueError('unexpected capsule fields')
    expected = {'releaseId', 'payloadManifestSha256', 'vendorManifestSha256',
                'app', 'version', 'executable', 'installSize'}
    if not isinstance(binding, dict) or set(binding) != expected:
        raise ValueError('invalid release binding')
    if (capsule['releaseId'] != binding['releaseId']
            or capsule['payloadManifestSha256'] != binding['payloadManifestSha256']
            or capsule['manifestSha256'] != binding['vendorManifestSha256']
            or item['AppName'] != binding['app']
            or item['AppVersionString'] != binding['version']
            or item['LaunchExecutable'] != safe_relative(binding['executable'])
            or item['InstallSize'] != binding['installSize']
            or not 41 <= len(manifest) <= MAX_MANIFEST
            or hashlib.sha256(manifest).hexdigest() != capsule['manifestSha256']):
        raise ValueError('official installation does not match pinned release')
    return item


def new_file(path, data, mode=0o600):
    path = Path(path)
    fd, name = tempfile.mkstemp(prefix='.dpad-epic-', dir=path.parent)
    try:
        os.fchmod(fd, mode)
        with os.fdopen(fd, 'wb') as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        # link publishes a complete file and refuses existing paths, including
        # symlinks. A failed/interrupted write never exposes a partial .item.
        os.link(name, path, follow_symlinks=False)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def export_capsule(item_path, manifest_path, binding, output):
    original = read_bytes(item_path, MAX_JSON)
    raw = json.loads(original, object_pairs_hook=unique)
    item = normalize_item(raw)
    manifest = read_bytes(manifest_path, MAX_MANIFEST)
    filename = Path(manifest_path).name
    # Require the record's real .egstore manifest, not an unrelated supplied blob.
    recorded = raw.get('ManifestFileName')
    location = PureWindowsPath(raw.get('ManifestLocation', ''))
    if not recorded and location.suffix.lower() == '.manifest':
        recorded = location.name
    if (recorded and recorded != filename) or not recorded and (location.name.lower() != '.egstore' or Path(manifest_path).parent.name != '.egstore'):
        raise ValueError('official manifest record mismatch')
    capsule = dict(schema=1, releaseId=binding['releaseId'],
                   payloadManifestSha256=binding['payloadManifestSha256'],
                   sourceItemSha256=hashlib.sha256(original).hexdigest(),
                   manifestSha256=hashlib.sha256(manifest).hexdigest(),
                   manifestFileName=filename, item=item)
    validate_capsule(capsule, binding, manifest)
    output = Path(output)
    if not output.is_absolute() or output.parent.resolve() != output.parent:
        raise ValueError('noncanonical output')
    output.mkdir(mode=0o700)  # No overwrite of a published capsule.
    encoded = json.dumps(capsule, sort_keys=True, separators=(',', ':')).encode()
    new_file(output / 'installation.json', encoded)
    new_file(output / 'vendor.manifest', manifest)
    return hashlib.sha256(encoded).hexdigest()


def rebind_capsule(source, expected_digest, source_binding, target_binding, output):
    """Reuse verified public records for a new immutable release of identical bytes."""
    source = Path(source)
    encoded = read_bytes(source / 'installation.json', MAX_JSON, sealed=True)
    if (not isinstance(expected_digest, str) or not re.fullmatch(DIGEST, expected_digest)
            or hashlib.sha256(encoded).hexdigest() != expected_digest):
        raise ValueError('source capsule digest mismatch')
    capsule = json.loads(encoded, object_pairs_hook=unique)
    manifest = read_bytes(source / 'vendor.manifest', MAX_MANIFEST, sealed=True)
    validate_capsule(capsule, source_binding, manifest)
    if (not isinstance(target_binding, dict)
            or set(target_binding) != set(source_binding)
            or any(target_binding[k] != source_binding[k]
                   for k in source_binding if k != 'releaseId')
            or target_binding['releaseId'] == source_binding['releaseId']):
        raise ValueError('rebinding requires a new release with identical game bytes')
    capsule = {**capsule, 'releaseId': target_binding['releaseId']}
    validate_capsule(capsule, target_binding, manifest)
    output = Path(output)
    if not output.is_absolute() or output.parent.resolve() != output.parent:
        raise ValueError('noncanonical output')
    output.mkdir(mode=0o700)
    encoded = json.dumps(capsule, sort_keys=True, separators=(',', ':')).encode()
    new_file(output / 'installation.json', encoded)
    new_file(output / 'vendor.manifest', manifest)
    return hashlib.sha256(encoded).hexdigest()


def private_dir(path, *, create=True):
    path = Path(path)
    if not path.is_absolute() or path.resolve() != path:
        raise ValueError('redirected private directory')
    for directory in (path, *path.parents):
        if not directory.exists():
            continue
        info = directory.lstat()
        if not stat.S_ISDIR(info.st_mode) or info.st_mode & 0o022 and directory != Path('/tmp'):
            raise ValueError('unsafe private ancestor')
        if directory == path and (info.st_uid != os.geteuid() or info.st_mode & 0o077):
            raise ValueError('private user directory required')
    if create:
        path.mkdir(mode=0o700, parents=True, exist_ok=True)
    return path


@contextmanager
def registration_lock(prefix):
    """Serialize our imports without opening or altering the client's account state."""
    fd = os.open(prefix / '.dpad-epic-registration.lock',
                 os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600)
    try:
        info = os.fstat(fd)
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid()
                or info.st_nlink != 1 or info.st_mode & 0o077 or info.st_size):
            raise ValueError('unsafe registration lock')
        deadline = time.monotonic() + 5
        while True:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    raise TimeoutError('another official registration is in progress')
                time.sleep(0.05)
        yield
    finally:
        os.close(fd)


def replace_json(path, data):
    fd, name = tempfile.mkstemp(prefix='.dpad-epic-', dir=path.parent)
    try:
        with os.fdopen(fd, 'w') as stream:
            json.dump(data, stream, sort_keys=True)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def register(prefix, game, capsule_dir, binding, capsule_digest):
    prefix, game, capsule_dir = map(Path, (prefix, game, capsule_dir))
    private_dir(prefix)
    with registration_lock(prefix):
        return register_locked(prefix, game, capsule_dir, binding, capsule_digest)


def register_locked(prefix, game, capsule_dir, binding, capsule_digest):
    if not re.fullmatch(DIGEST, capsule_digest):
        raise ValueError('pinned capsule digest required')
    encoded = read_bytes(capsule_dir / 'installation.json', MAX_JSON, sealed=True)
    if hashlib.sha256(encoded).hexdigest() != capsule_digest:
        raise ValueError('capsule digest mismatch')
    capsule = json.loads(encoded, object_pairs_hook=unique)
    manifest = read_bytes(capsule_dir / 'vendor.manifest', MAX_MANIFEST, sealed=True)
    item = validate_capsule(capsule, binding, manifest)
    if (game.resolve() != game or not game.is_dir()
            or os.statvfs(game).f_flag & os.ST_RDONLY
            or (game / item['LaunchExecutable']).resolve() != game / item['LaunchExecutable']
            or not (game / item['LaunchExecutable']).is_file()):
        raise ValueError('private writable game overlay required')
    # A root-owned overlay receipt is required by main(), before this library call.
    # Per-game path prevents future imported games from replacing each other.
    app = item['AppName']
    # Preflight every existing record before creating a drive mapping or item.
    # A conflict in LauncherInstalled.dat must not leave a half-imported game.
    games = private_dir(prefix / 'drive_c/DpadPlay/Games', create=False)
    link = games / app
    if link.is_symlink():
        if link.readlink() != game:
            raise ValueError('conflicting game drive mapping')
    elif link.exists():
        raise ValueError('conflicting game drive mapping')
    store = private_dir(game / '.egstore', create=False)
    manifest_path = store / capsule['manifestFileName']
    if manifest_path.exists() or manifest_path.is_symlink():
        if read_bytes(manifest_path, MAX_MANIFEST, private=True) != manifest:
            raise ValueError('existing Epic manifest conflicts')
    install = 'C:\\DpadPlay\\Games\\' + app
    record = {**item, 'LaunchExecutable': item['LaunchExecutable'].replace('/', '\\'),
              'InstallLocation': install, 'StagingLocation': install + '\\.egstore\\bps',
              'ManifestLocation': install + '\\.egstore',
              'ManifestFileName': capsule['manifestFileName']}
    manifests = private_dir(prefix / 'drive_c/ProgramData/Epic/EpicGamesLauncher/Data/Manifests', create=False)
    target = manifests / (item['InstallationGuid'] + '.item')
    if target.exists() or target.is_symlink():
        previous = json.loads(read_bytes(target, MAX_JSON, private=True), object_pairs_hook=unique)
        if previous != record:
            raise ValueError('existing official installation conflicts')
    inventory = private_dir(prefix / 'drive_c/ProgramData/Epic/UnrealEngineLauncher', create=False) / 'LauncherInstalled.dat'
    data = json.loads(read_bytes(inventory, MAX_JSON, private=True), object_pairs_hook=unique) if inventory.exists() or inventory.is_symlink() else {'InstallationList': []}
    if not isinstance(data, dict) or not isinstance(data.get('InstallationList'), list):
        raise ValueError('invalid official installation inventory')
    entry = {'InstallLocation': install, 'NamespaceId': item['CatalogNamespace'],
             'ItemId': item['CatalogItemId'], 'ArtifactId': app,
             'AppVersion': item['AppVersionString'], 'AppName': app}
    matching = [row for row in data['InstallationList'] if isinstance(row, dict) and row.get('AppName') == app]
    if matching and matching != [entry]:
        raise ValueError('existing official inventory conflicts')
    if not matching:
        data['InstallationList'].append(entry)
    if len(json.dumps(data, sort_keys=True).encode()) > MAX_JSON:
        raise ValueError('official inventory size limit')
    private_dir(games)
    private_dir(store)
    private_dir(manifests)
    private_dir(inventory.parent)
    if not link.is_symlink():
        link.symlink_to(game, target_is_directory=True)
    if not manifest_path.exists():
        new_file(manifest_path, manifest)
    if not target.exists():
        new_file(target, json.dumps(record, sort_keys=True).encode())
    if not matching:
        replace_json(inventory, data)
    return 'official_epic_registered'


def session_prefix():
    """Use the same explicit-state/volume/home precedence as faugus-epic-launch."""
    state = os.environ.get('DPAD_FAUGUS_STATE_ROOT')
    if not state and os.environ.get('DPAD_VOLUME_MOUNT'):
        state = os.environ['DPAD_VOLUME_MOUNT'] + '/faugus'
    return Path(state) / 'prefixes/epic-games' if state else Path(os.environ['HOME']) / 'Faugus/epic-games'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='operation', required=True)
    export = commands.add_parser('export')
    for name in ('item', 'manifest', 'binding', 'output'):
        export.add_argument('--' + name, required=True)
    rebind = commands.add_parser('rebind')
    for name in ('source', 'source-sha256', 'source-binding', 'binding', 'output'):
        rebind.add_argument('--' + name, required=True)
    commands.add_parser('register')
    args = parser.parse_args()
    if args.operation == 'export':
        binding = json.loads(read_bytes(Path(args.binding), MAX_JSON), object_pairs_hook=unique)
        print(json.dumps({'capsuleSha256': export_capsule(args.item, args.manifest, binding, args.output)}))
        return
    if args.operation == 'rebind':
        source_binding = json.loads(read_bytes(Path(args.source_binding), MAX_JSON), object_pairs_hook=unique)
        binding = json.loads(read_bytes(Path(args.binding), MAX_JSON), object_pairs_hook=unique)
        print(json.dumps({'capsuleSha256': rebind_capsule(args.source, args.source_sha256,
                         source_binding, binding, args.output)}))
        return
    if os.geteuid() == 0 or os.environ.get('DPAD_FAUGUS_INSTANT_TEST') != '1':
        raise ValueError('private official registration canary required')
    binding = json.loads(base64.b64decode(os.environ['DPAD_EPIC_INSTALLATION_BINDING'], validate=True), object_pairs_hook=unique)
    receipt = json.loads(read_bytes(Path('/run/dpadcloud/epic-overlay.json'), MAX_JSON, sealed=True), object_pairs_hook=unique)
    if Path('/run/dpadcloud/epic-overlay.json').stat().st_uid != 0:
        raise ValueError('root overlay receipt required')
    if receipt != {'releaseId': binding['releaseId'], 'game': '/opt/dpad-instant/official-game'}:
        raise ValueError('overlay ownership mismatch')
    prefix = session_prefix()
    print('DPAD_INSTANT_INSTALLATION ' + register(prefix, receipt['game'],
          '/opt/dpad-instant/epic', binding, os.environ['DPAD_EPIC_INSTALLATION_SHA256']))


if __name__ == '__main__':
    try:
        main()
    except (ValueError, OSError, KeyError, TypeError):
        print('Official Epic installation refused', file=sys.stderr)
        sys.exit(1)
