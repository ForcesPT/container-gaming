"""Host-side exact Instant cleanup; never calls the legacy slot-only stop command."""
import re
import os
import stat
import json
import subprocess


class Engine:
    def __init__(self, run=subprocess.run, deadline=None):
        self.run = run
        self.deadline = deadline

    def command(self, *args):
        import time
        budget = 30 if self.deadline is None else min(30, self.deadline-time.time())
        if budget <= 0:
            raise TimeoutError('Instant startup deadline exceeded')
        return self.run(['/usr/bin/docker', *args], check=True, capture_output=True, text=True, timeout=budget).stdout

    def inspect(self, identity):
        rows = json.loads(self.command('inspect', identity))
        if len(rows) != 1:
            raise ValueError('ambiguous container')
        return rows[0]

    def list_containers(self):
        ids = self.command('ps', '-aq', '--no-trunc').split()
        rows = []
        for identity in ids:
            if not re.fullmatch(r'[a-f0-9]{64}', identity):
                raise ValueError('invalid engine identity')
            row = self.inspect(identity)
            rows.append(dict(Id=row['Id'], Names=[row['Name']], Labels=row['Config'].get('Labels') or {}))
        return rows

    def stop_session(self, session, slot):
        # The controller persists cancellation and stops the exact TLS gateway
        # before removing its immutable container ID. Never bypass its tombstone.
        self.run(['/usr/local/bin/dpad-launch-session', 'stop', str(slot), session],
                 check=True, capture_output=True, text=True, timeout=120)



def write_request(path, request):
    raw = json.dumps(request, sort_keys=True).encode()
    if len(raw) > 4096:
        raise ValueError('oversized request')
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    except FileExistsError:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(fd, 'rb') as stream:
            info = os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) != 0o600 or info.st_nlink != 1 or stream.read(4097) != raw:
                raise ValueError('conflicting request')
    else:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(raw); stream.flush(); os.fsync(stream.fileno())



def cleanup(engine, session, release, slot):
    for value in (session, release):
        if not re.fullmatch(r'[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}', value):
            raise ValueError('invalid identity')
    if type(slot) is not int or not 0 <= slot < 32:
        raise ValueError('invalid slot')
    name = '/dpad-slot-' + str(slot)
    rows = engine.list_containers()
    owned = [row for row in rows if name in row['Names']]
    if len(owned) > 1:
        raise ValueError('ambiguous slot')
    if owned:
        row = engine.inspect(owned[0]['Id'])
        labels = row['Config'].get('Labels') or {}
        if labels.get('dpad.instant.session') != session or labels.get('dpad.instant.release') != release:
            raise ValueError('slot owner mismatch')
        # Instant launches have no Docker volumes. Never delete an unexpected
        # customer volume or claim its writable state was cleaned.
        if any(m['Type'] == 'volume' for m in row['Mounts']):
            raise ValueError('unexpected persistent state')
        if not re.fullmatch(r'[a-f0-9]{64}', row['Id']):
            raise ValueError('invalid container identity')
    engine.stop_session(session, slot)
    remaining = engine.list_containers()
    if any(name in row['Names'] or (row.get('Labels') or {}).get('dpad.instant.session') == session for row in remaining):
        raise ValueError('container cleanup unconfirmed')


def check_ready(engine, session, release, slot):
    row = engine.inspect('dpad-slot-' + str(slot))
    labels = row['Config'].get('Labels') or {}
    if not row['State']['Running'] or labels.get('dpad.instant.session') != session or labels.get('dpad.instant.release') != release:
        raise ValueError('runtime identity/readiness mismatch')
    engine.command('exec', row['Id'], 'sh', '-ec', "grep -q '^DPAD_INSTANT_INSTALLATION ' /tmp/instant-registration.log; pgrep -x dpad-launcher >/dev/null")


def disk_status(engine, session, release, slot, usage):
    """Read-only probe; terminalization and cleanup belong to the control plane."""
    if slot != 0:
        raise ValueError('dedicated slot required')
    row = engine.inspect('dpad-slot-0')
    labels = row['Config'].get('Labels') or {}
    if not row['State']['Running'] or labels.get('dpad.instant.session') != session or labels.get('dpad.instant.release') != release or labels.get('dpad.instant.storage') != 'dedicated-ephemeral':
        raise ValueError('disk probe owner mismatch')
    root = engine.command('info', '--format', '{{.DockerRootDir}}').strip()
    if not root.startswith('/'):
        raise ValueError('invalid Docker root')
    free = min(usage(root).free, usage('/').free)
    return dict(status='low_space' if free < 5*1024**3 else 'storage_ok', sessionId=session, releaseId=release, slot=slot, freeBytes=free)


def main():
    import sys
    import fcntl
    from pathlib import Path
    if os.geteuid() != 0:
        raise ValueError('root host authority required')
    import base64, time, signal
    if len(sys.argv) == 7 and sys.argv[1] == 'launch':
        if len(sys.argv[2]) > 6000:
            raise ValueError('oversized request')
        config = json.loads(base64.b64decode(sys.argv[2], validate=True))
        session, release, slot_text = config['sessionId'], config['releaseId'], str(config['slot'])
        if type(config['expiresAt']) is not int or not time.time() < config['expiresAt'] <= time.time() + 420:
            raise ValueError('launch deadline exceeded')
        if not all(re.fullmatch(r'[0-9]{2,4}', v) for v in sys.argv[4:]):
            raise ValueError('invalid display configuration')
    elif len(sys.argv) == 5 and sys.argv[1] in ('cleanup', 'disk-status'):
        config = None
        session, release, slot_text = sys.argv[2:]
    else:
        raise ValueError('invalid operation')
    for identity in (session, release):
        if not re.fullmatch(r'[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}', identity):
            raise ValueError('invalid identity')
    if not re.fullmatch(r'[0-9]{1,2}', slot_text):
        raise ValueError('invalid slot')
    slot = int(slot_text)
    root = Path('/run/dpad-instant')
    root.mkdir(mode=0o700, exist_ok=True)
    for parent in (root, *root.parents):
        info = parent.lstat()
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o022:
            raise ValueError('untrusted host runtime directory')
    fd = os.open(root / ('slot-' + str(slot) + '.lock'), os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, 'w') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        request = root / 'requests' / (session + '.json')
        if config is not None:
            request.parent.mkdir(mode=0o700, exist_ok=True)
            info = request.parent.lstat()
            if not stat.S_ISDIR(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o022:
                raise ValueError('untrusted request directory')
            write_request(request, config)
            env = {**os.environ, 'DPAD_SESSION_BACKEND': str(Path(__file__).resolve().with_name('dpad-launch-session')), 'DPAD_INSTANT_CONFIG': str(request), 'DPAD_WD_WIDTH': sys.argv[4], 'DPAD_WD_HEIGHT': sys.argv[5], 'DPAD_STREAM_FPS': sys.argv[6]}
            # An interrupted launch retains its request and pin for reconciliation.
            process = subprocess.Popen(['/usr/local/bin/dpad-launch-session', 'launch', slot_text, 'none', 'none', sys.argv[3], config['image'], session],
                                       env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
            try:
                code = process.wait(timeout=max(0.01, config['expiresAt'] - time.time()))
            except BaseException:
                os.killpg(process.pid, signal.SIGKILL); process.wait()
                raise
            if code or time.time() >= config['expiresAt']:
                raise ValueError('launcher failed or exceeded deadline')
            engine = Engine(deadline=config['expiresAt'])
            while True:
                if time.time() >= config['expiresAt']:
                    raise ValueError('runtime readiness deadline exceeded')
                try:
                    check_ready(engine, session, release, slot)
                    break
                except subprocess.CalledProcessError:
                    time.sleep(min(1, max(0, config['expiresAt'] - time.time())))
            if time.time() >= config['expiresAt']:
                raise TimeoutError('Instant startup deadline exceeded')
            print(json.dumps(dict(status='runtime_ready', sessionId=session, releaseId=release, slot=slot)))
            return
        if sys.argv[1] == 'disk-status':
            import shutil
            print(json.dumps(disk_status(Engine(), session, release, slot, shutil.disk_usage)))
            return
        cleanup(Engine(), session, release, slot)
        if request.exists() or request.is_symlink():
            request.unlink()
        print(json.dumps(dict(status='cleanup_confirmed', sessionId=session, releaseId=release, slot=slot)))


if __name__ == '__main__':
    try:
        main()
    except Exception:
        import sys
        print('Instant lifecycle refused', file=sys.stderr)
        sys.exit(1)
