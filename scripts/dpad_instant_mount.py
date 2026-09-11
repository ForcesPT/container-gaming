"""Host-only Instant Play mount contract; never authenticates or launches a game.
Install alongside dpad-launch-session in the same verified host artifact bundle.
"""
import hashlib
import base64
import json
import re
import stat
import sys
from pathlib import Path

# -I excludes the script directory; this directory is part of the trusted bundle.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from dpad_instant_register import validate_metadata


def compile_mount(config, slot, image, mount, root, *, now):
    fields = {'sessionId', 'releaseId', 'manifestSha256', 'image', 'slot', 'app', 'scratchGiB', 'expiresAt', 'metadata'}
    if not isinstance(config, dict) or set(config) != fields:
        raise ValueError('invalid contract fields')
    def matches(key, pattern):
        return isinstance(config[key], str) and re.fullmatch(pattern, config[key])
    for key in ('sessionId', 'releaseId'):
        if not matches(key, r'[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}'):
            raise ValueError('invalid identity')
    if not matches('manifestSha256', r'[a-f0-9]{64}') or not matches('app', r'[A-Za-z0-9_-]{1,128}'):
        raise ValueError('invalid source binding')
    if not matches('image', r'forcespt/dpadcloud-gaming@sha256:[a-f0-9]{64}') or config['image'] != image:
        raise ValueError('immutable image mismatch')
    if type(config['slot']) is not int or not 0 <= config['slot'] < 32 or config['slot'] != slot:
        raise ValueError('slot mismatch')
    if type(config['scratchGiB']) is not int or not 1 <= config['scratchGiB'] <= 200:
        raise ValueError('invalid scratch budget')
    if type(config['expiresAt']) is not int or not now < config['expiresAt'] <= now + 420:
        raise ValueError('invalid launch deadline')
    validate_metadata(config['metadata'])
    if config['metadata']['app'] != config['app']:
        raise ValueError('registration app mismatch')
    metadata = base64.b64encode(json.dumps(config['metadata'], separators=(',', ':')).encode()).decode('ascii')
    root = Path(root)
    if not re.fullmatch(r'/[A-Za-z0-9_/-]+', str(root)) or root.resolve() != root:
        raise ValueError('unsafe mount path')
    options = set(mount.get('options', '').split(','))
    if mount.get('target') != str(root) or mount.get('source') != '10.80.0.2:/releases' or mount.get('fstype') != 'nfs4' or not {'ro', 'nosuid', 'nodev', 'vers=4.1'} <= options or 'rw' in options:
        raise ValueError('private read-only NFS mount required')
    bundle = root / config['releaseId']
    for path in (bundle, bundle / 'files', bundle / 'manifest.jsonl'):
        info = path.lstat()
        if path.resolve() != path or info.st_mode & 0o222 or not (stat.S_ISREG(info.st_mode) if path.name == 'manifest.jsonl' else stat.S_ISDIR(info.st_mode)):
            raise ValueError('unsealed or redirected release')
    if (bundle / 'manifest.jsonl').stat().st_size > 16 * 1024 * 1024:
        raise ValueError('oversized manifest')
    if hashlib.sha256((bundle / 'manifest.jsonl').read_bytes()).hexdigest() != config['manifestSha256']:
        raise ValueError('manifest mismatch')
    return ['--pull=never', '--mount', f'type=bind,src={bundle}/files,dst=/opt/dpad-instant/game,readonly,bind-recursive=disabled',
            '--label', 'dpad.instant.session=' + config['sessionId'],
            '--label', 'dpad.instant.release=' + config['releaseId'],
            '--storage-opt', f"size={config['scratchGiB']}g", '-e', 'DPAD_STORES=epic',
            '-e', 'DPAD_INSTANT_APP=' + config['app'],
            '-e', 'DPAD_INSTANT_METADATA=' + metadata]


def main():
    import json
    import os
    import sys
    import subprocess
    import time
    if len(sys.argv) != 4 or not re.fullmatch(r'/run/dpad-instant/requests/[a-f0-9-]{36}\.json', sys.argv[1]):
        raise ValueError('trusted request required')
    path = Path(sys.argv[1])
    for parent in path.parents:
        info = parent.lstat()
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o022:
            raise ValueError('untrusted request parent')
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd) as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_uid != 0 or stat.S_IMODE(info.st_mode) != 0o600 or info.st_nlink != 1 or info.st_size > 4096:
            raise ValueError('untrusted request')
        def unique(pairs):
            result = {}
            for k, v in pairs:
                if k in result:
                    raise ValueError('duplicate field')
                result[k] = v
            return result
        config = json.load(stream, object_pairs_hook=unique)
    if not isinstance(config, dict) or config.get('sessionId') != path.stem:
        raise ValueError('request identity mismatch')
    root = Path('/srv/dpad-instant/paris/releases')
    result = subprocess.run(['/usr/bin/findmnt', '--json', '--mountpoint', str(root), '--output', 'TARGET,SOURCE,FSTYPE,OPTIONS'], capture_output=True, check=True, timeout=10)
    mounts = json.loads(result.stdout)['filesystems']
    if len(mounts) != 1:
        raise ValueError('ambiguous mount')
    args = compile_mount(config, int(sys.argv[2]), sys.argv[3], mounts[0], root, now=time.time())
    print(config['expiresAt'])
    print('\n'.join(args))


if __name__ == '__main__':
    try:
        main()
    except Exception:
        import sys
        print('Instant mount validation refused', file=sys.stderr)
        sys.exit(1)
