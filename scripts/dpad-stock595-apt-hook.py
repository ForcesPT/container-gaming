#!/usr/bin/env python3
"""APT v1 pre-install hook: reject any .deb outside the reviewed missing pair."""
import json
from pathlib import Path
import subprocess
import sys

def validate_debs(paths, wanted, inspect):
    actual = {}
    for path in paths:
        if not path.startswith('/') or not path.endswith('.deb'): raise ValueError('unexpected apt hook input')
        name, version, arch = inspect(path).strip().split('\n')
        if arch != 'amd64' or name in actual: raise ValueError('architecture or duplicate package')
        actual[name] = version
    if actual != wanted: raise ValueError('real apt transaction differs from approved missing codecs')

if __name__ == '__main__':
    from importlib.machinery import SourceFileLoader
    helper = SourceFileLoader('stock595', str(Path(__file__).with_name('dpad-stock595-codecs.py'))).load_module()
    path = helper.EVIDENCE / 'codec-selection.json'
    helper.secure_path(path)
    selection = json.loads(path.read_text())
    wanted = selection['missing']
    if not wanted or not set(wanted) <= set(helper.NAMES) or set(wanted.values()) != {'595.58.03-1ubuntu1'}:
        raise ValueError('unsafe codec allowlist')
    helper.check_idle()
    if list(helper.identity()) != selection['identity']: raise ValueError('driver or boot ID changed')
    def inspect(path):
        p = subprocess.run(['dpkg-deb','--show','--showformat=${Package}\n${Version}\n${Architecture}\n',path],capture_output=True,text=True,check=True)
        return p.stdout
    validate_debs(sys.stdin.read().splitlines(), wanted, inspect)
