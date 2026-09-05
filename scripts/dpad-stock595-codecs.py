#!/usr/bin/env python3
"""Narrow production UpCloud L4 stock595 host profile and codec transaction.

Worker contract (no downloads performed by this helper): install immutable-commit,
SHA256-verified artifacts owned by root, with no group/world write permission:
  /opt/dpadcloud/vm-bootstrap.sh
  /opt/dpadcloud/dpad-stock595-codecs.py
  /opt/dpadcloud/dpad-stock595-apt-hook.py
  /usr/local/bin/dpad-launch-session
Call bootstrap `install` with DPAD_RELEASE_PROFILE=upcloud-stock595,
DPAD_PROVIDER=upcloud and DPAD_IMAGE_TAG=<repository>@sha256:<digest>.
The parent worker selects the approved persisted UpCloud L4 + exact image digest;
this helper verifies immutable syntax and the actual single L4 / 595.58.03 host.
NVIDIA container toolkit must already be installed. Existing modeset/XFS/MPS
bootstrap steps remain in use. This does not authorize L40S or shared promotion.

Defaults: host driver policy, nvcudah264enc, multivendor EGL, Sway. The protected
stock595-profile.json preserves all seven selectors across systemd boots and
session launches; conflicting overrides fail. Launcher requires the same explicit
image argument. Importing this module never invokes apt or changes the host.
"""
import json
import os
from pathlib import Path
import re
import subprocess


# Worker installs these root-owned artifacts from immutable commit+SHA256 pins.
# No helper downloads. Configuration survives systemd reboot and fresh launches.
# Logs are protected, fixed host paths, never /tmp or caller-selected paths.
BASE = Path('/opt/dpadcloud')
HOOK = BASE / 'dpad-stock595-apt-hook.py'
CONFIG = BASE / 'stock595-profile.json'
EVIDENCE = BASE / 'stock595-codec-evidence'
KEYS = ('DPAD_RELEASE_PROFILE', 'DPAD_PROVIDER', 'DPAD_IMAGE_TAG',
        'DPAD_DRIVER_POLICY', 'DPAD_ENCODER', 'DPAD_COMPOSITOR_EGL', 'DPAD_DESKTOP_CLIENT')

def secure_path(path):
    import stat
    path = Path(path).absolute()
    for item in [*reversed(path.parents), path]:
        st = item.lstat()
        if st.st_uid != 0 or st.st_mode & 0o022 or stat.S_ISLNK(st.st_mode):
            raise ValueError('unsafe root-owned path: ' + str(item))
        if not (stat.S_ISREG(st.st_mode) or stat.S_ISDIR(st.st_mode)):
            raise ValueError('unsafe path type')

def safe_open(path):
    secure_path(path.parent)
    if path.exists() or path.is_symlink(): secure_path(path)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    if os.fstat(fd).st_nlink != 1:
        os.close(fd)
        raise ValueError('hardlinked output')
    return os.fdopen(fd, 'w')

def write_evidence(path, text):
    with safe_open(path) as f:
        f.truncate(0)
        f.write(text)

def identity():
    return (run(['nvidia-smi', '--query-gpu=name,driver_version', '--format=csv,noheader']).strip(),
            Path('/proc/sys/kernel/random/boot_id').read_text().strip())

def check_idle():
    # Dedicated profile host: reject all running containers, including unknown names.
    if run(['docker', 'ps', '-q']).strip():
        raise ValueError('stock595 host must have no active containers')

def profile(image):
    values = {k: os.environ[k] for k in KEYS if k in os.environ}
    if CONFIG.exists() or CONFIG.is_symlink():
        secure_path(CONFIG)
        saved = json.loads(CONFIG.read_text())
        if set(saved) != set(KEYS): raise ValueError('invalid persisted profile')
        for k, v in saved.items():
            if k in values and values[k] != v: raise ValueError('persisted profile conflict: ' + k)
        values = saved
    defaults = dict(DPAD_DRIVER_POLICY='host', DPAD_ENCODER='nvcudah264enc',
                    DPAD_COMPOSITOR_EGL='multivendor', DPAD_DESKTOP_CLIENT='sway')
    for k, v in defaults.items(): values.setdefault(k, v)
    if values.get('DPAD_RELEASE_PROFILE') != 'upcloud-stock595' or values.get('DPAD_PROVIDER') != 'upcloud':
        raise ValueError('stock595 requires explicit UpCloud profile')
    if not image: image = values.get('DPAD_IMAGE_TAG', '')
    if not re.fullmatch(r'[a-z0-9][a-z0-9./:_-]*@sha256:[0-9a-f]{64}', image):
        raise ValueError('immutable image reference required')
    if values.get('DPAD_IMAGE_TAG', image) != image: raise ValueError('profile image mismatch')
    values['DPAD_IMAGE_TAG'] = image
    for k, allowed in dict(DPAD_DRIVER_POLICY=('host',), DPAD_ENCODER=('nvh264enc','nvcudah264enc'),
                          DPAD_COMPOSITOR_EGL=('nvidia','multivendor'), DPAD_DESKTOP_CLIENT=('sway','labwc')).items():
        if values[k] not in allowed: raise ValueError('invalid ' + k)
    if os.environ.get('DPAD_BUILD', '0') != '0' or os.environ.get('DPAD_WARM_VM', '1') != '1':
        raise ValueError('stock595 requires pulled baked image and warm session launcher')
    if os.environ.get('DPAD_SKIP_MODESET', '0') != '0':
        raise ValueError('stock595 requires normal modeset handling')
    if os.environ.get('DPAD_SKIP_DRIVER_SWAP', '0') not in ('0','1'):
        raise ValueError('invalid DPAD_SKIP_DRIVER_SWAP')
    if identity()[0] != 'NVIDIA L4, 595.58.03':
        raise ValueError('requires one actual NVIDIA L4 with exact driver 595.58.03')
    return values

NAMES = ('libnvidia-encode', 'libnvidia-decode')

def select_version(driver, versions):
    matching = {v for v in versions if re.fullmatch(r'(?:\d+:)?595\.58\.03-[A-Za-z0-9.+~]+', v)}
    if driver != '595.58.03' or matching != {'595.58.03-1ubuntu1'}:
        raise ValueError('requires exact 595.58.03-1ubuntu1 codec')
    return '595.58.03-1ubuntu1'

def choose_missing(chosen, installed):
    for name, version in installed.items():
        if name not in chosen or chosen[name] != version:
            raise ValueError('installed codec version differs; no upgrades/downgrades allowed')
    return {name: version for name, version in chosen.items() if name not in installed}

def validate_plan(plan, wanted):
    if not wanted or not set(wanted) <= set(NAMES) or set(wanted.values()) != {'595.58.03-1ubuntu1'}:
        raise ValueError('invalid install allowlist')
    summary = re.findall(r'^(\d+) upgraded, (\d+) newly installed, (\d+) to remove and \d+ not upgraded\.$', plan, re.M)
    if summary != [('0', str(len(wanted)), '0')]:
        raise ValueError('transaction summary is not a pure missing-codec install')
    seen = {}
    for line in plan.splitlines():
        if line.startswith(('Remv ', 'Purg ', 'E:', 'W:')):
            raise ValueError('apt warning/error/removal')
        if line.startswith(('Inst ', 'Conf ')):
            m = re.fullmatch(r'(Inst|Conf) (libnvidia-(?:encode|decode))(?::amd64)? \(([^ ]+) [^\n]*\[amd64\]\)', line)
            if not m or wanted.get(m[2]) != m[3]:
                raise ValueError('unexpected apt operation, architecture or version')
            if m[1] == 'Inst':
                if m[2] in seen: raise ValueError('duplicate install')
                seen[m[2]] = m[3]
    if seen != wanted:
        raise ValueError('simulation does not install exactly the missing codecs')

def validate_sources(text):
    # Reject source-level overrides that would bypass APT authentication even
    # with AllowUnauthenticated=false. Existing signed sources only; no additions.
    for line in text.splitlines():
        line = line.split('#', 1)[0]
        if re.search(r'(?:trusted|allow-insecure|allow-weak|allow-downgrade-to-insecure)\s*[:=]\s*(?:yes|true|1)\b', line, re.I):
            raise ValueError('unsigned/insecure apt source override')

def check_signed_sources():
    if os.environ.get('APT_CONFIG'):
        raise ValueError('custom apt configuration is not allowed')
    for path in [Path('/etc/apt/sources.list'), *Path('/etc/apt/sources.list.d').glob('*.list'),
                 *Path('/etc/apt/sources.list.d').glob('*.sources')]:
        if path.exists():
            secure_path(path)
            validate_sources(path.read_text())

def run(args, **kwargs):
    return subprocess.run(args, check=True, text=True, capture_output=True,
                          env={**os.environ, 'LC_ALL': 'C', 'DEBIAN_FRONTEND': 'noninteractive'}, **kwargs).stdout

def main():
    profile(os.environ.get('DPAD_IMAGE_TAG', ''))
    check_idle()
    driver = '595.58.03'
    before = identity()
    secure_path(Path(__file__))
    secure_path(HOOK)
    check_signed_sources()
    if run(['dpkg', '--audit']).strip(): raise ValueError('dpkg has pending/partial operations')
    EVIDENCE.mkdir(mode=0o700, exist_ok=True)
    secure_path(EVIDENCE)
    import fcntl
    lock = safe_open(EVIDENCE / 'transaction.lock')
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    chosen, installed = {}, {}
    for name in NAMES:
        madison = run(['apt-cache', 'madison', name + ':amd64'])
        versions = [line.split('|')[1].strip() for line in madison.splitlines() if line.count('|') >= 2]
        chosen[name] = select_version(driver, versions)
        q = subprocess.run(['dpkg-query', '-W', '-f=${db:Status-Status}\t${Version}\t${Architecture}', name + ':amd64'], text=True, capture_output=True)
        if q.returncode == 0:
            status, version, arch = q.stdout.split('\t')
            if status == 'installed':
                if arch != 'amd64': raise ValueError('wrong installed architecture')
                installed[name] = version
            elif status not in ('not-installed', 'config-files'):
                raise ValueError('partially installed codec')
        elif q.returncode != 1:
            raise ValueError('dpkg-query failed')
    missing = choose_missing(chosen, installed)
    evidence = EVIDENCE
    write_evidence(evidence / 'codec-selection.json', json.dumps({'driver': driver, 'identity': before, 'chosen': chosen, 'before': installed, 'missing': missing}, indent=2) + '\n')
    if missing:
        args = ['apt-get', '-o', 'APT::Get::AllowUnauthenticated=false', '-o', 'Acquire::AllowInsecureRepositories=false', '-o', 'Acquire::AllowDowngradeToInsecureRepositories=false', '--no-install-recommends', '--no-upgrade', '--no-remove', 'install'] + [f'{n}:amd64={v}' for n, v in missing.items()]
        simulation = run(['apt-get', '--simulate'] + args[1:])
        write_evidence(evidence / 'apt-simulation.txt', simulation)
        validate_plan(simulation, missing)
        # --no-upgrade/--no-remove also constrain the real solver; exact versions
        # and no recommends keep this transaction equal to the accepted plan.
        hook = str(HOOK)
        check_idle()
        if identity() != before: raise ValueError("host identity changed before transaction")
        if not re.fullmatch(r'/[A-Za-z0-9_./-]+', hook): raise ValueError('unsafe hook path')
        try:
            output = run(args[:1] + ['-y', '-o', 'DPkg::Pre-Install-Pkgs::=/usr/bin/python3 ' + hook] + args[1:])
        finally:
            if identity() != before: raise ValueError('driver or boot ID changed during apt')
        write_evidence(evidence / 'apt-install.txt', output)
    for name, version in chosen.items():
        actual = run(['dpkg-query', '-W', '-f=${db:Status-Status}\t${Version}\t${Architecture}', name + ':amd64'])
        if actual != f'installed\t{version}\tamd64': raise ValueError('codec postcheck failed')
    if identity() != before: raise ValueError('driver or boot ID changed')
    print('Exact codec selection and installed-version checks passed')

if __name__ == '__main__':
    import sys
    if len(sys.argv) > 1 and sys.argv[1] in ('profile', 'persist'):
        values = profile(sys.argv[2])
        if sys.argv[1] == 'persist':
            write_evidence(CONFIG, json.dumps(values))
        else:
            import shlex
            print('\n'.join('export ' + k + '=' + shlex.quote(v) for k, v in values.items()))
    elif len(sys.argv) == 1:
        main()
    else:
        raise SystemExit('usage: dpad-stock595-codecs.py [profile|persist IMAGE_REF]')
