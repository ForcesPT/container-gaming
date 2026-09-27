#!/usr/bin/python3
"""Pinned 2.4.2 adapter: use image UMU and honour disabled component updates."""
from pathlib import Path
import sys

root = Path(sys.argv[1])
path = root / 'faugus/path_manager.py'
source = path.read_text()
old = "UMU_RUN = PathManager.user_data('faugus-launcher/umu-run')"
if source.count(old) != 1:
    raise SystemExit('Unexpected Faugus UMU path')
path.write_text(source.replace(old, "UMU_RUN = '/usr/bin/umu-run'"))
path = root / 'faugus/runner.py'
source = path.read_text()
old = 'if not os.environ.get("DISABLE_UMU") and (not force_off or not self.components_exists):'
if source.count(old) != 1:
    raise SystemExit('Unexpected Faugus update branch')
path.write_text(source.replace(old, 'if not os.environ.get("DISABLE_UMU") and not force_off:'))
